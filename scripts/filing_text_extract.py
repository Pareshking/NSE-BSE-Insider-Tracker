"""Fill the filing text cache (insiders_clean/filing_text.py): download each announcement file once and keep its text.

For every NSE and BSE announcement in the window with a PDF, ZIP or XBRL file and no finished cache record, the file is
downloaded (BSE with the AttachHis fallback), turned into text exactly as the reader does it, and written to
archive/filing_text/{exchange}/year=/month=/day=.parquet. Resumable: a record already `ok` or `no_text` is skipped, a
failed one is retried up to 3 times (a missing file never). The cache is saved every 100 filings and at the end, and
the run stops starting new files at --minutes. No model is called. The XBRL-feed rows (`nse:xbrl:*`) are left out:
their files are the main feed's own.

    python scripts/filing_text_extract.py --from 2026-10-14 --to 2026-10-15
    python scripts/filing_text_extract.py            # the last 3 days, as the nightly collector's window
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import announcement_sample as sample  # noqa: E402
from insiders_clean import filing_text as ft  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
FILE_TYPES = ('pdf', 'zip', 'xbrl')
SAVE_EVERY = 100


def archive_rows(r2, exchange: str, day: date) -> pd.DataFrame:
    from clean_writer import read_parquet
    df = read_parquet(r2, f'archive/announcements/{exchange}/year={day.year}/month={day.month:02d}.parquet')
    if df is None or df.empty:
        return pd.DataFrame(columns=['event_id', 'file_url', 'file_type', 'broadcast_date'])
    df = df[df['broadcast_date'].astype(str) == day.isoformat()]
    df = df[df['file_url'].notna() & df['file_type'].isin(FILE_TYPES)]
    return df[~df['event_id'].astype(str).str.startswith('nse:xbrl:')][['event_id', 'file_url', 'file_type', 'broadcast_date']]


def extract_one(row: dict, exchange: str, tries: int, download, text_of) -> dict:
    base = {'event_id': row['event_id'], 'exchange': exchange, 'broadcast_date': str(row['broadcast_date']),
            'file_url': row['file_url'], 'tries': tries + 1, 'extractor': ft.EXTRACTOR,
            'extracted_at': datetime.now(timezone.utc).isoformat()}
    try:
        data = download(row['file_url'])
        text, notes = text_of(data, limit=None)
    except Exception as exc:  # noqa: BLE001 -- one file failing never stops the run
        reason = f'{type(exc).__name__}: {exc}'[:300]
        return {**base, 'status': 'failed', 'reason': reason, 'tries': ft.MAX_TRIES if ft.permanent(reason) else tries + 1}
    text = text.replace('\x00', '')
    return {**base, 'status': 'ok' if text.strip() else 'no_text', 'reason': None, 'file_bytes': len(data),
            'file_sha256': hashlib.sha256(data).hexdigest(), 'pages': text.count('\f') + 1 if text.strip() else 0,
            'chars': len(text), 'notes': '; '.join(notes), 'text': text}


def run(r2, first: date, last: date, minutes: float = 300, workers: int = 4, pause: float = 0.3,
        download=sample.download, text_of=sample.text_of, clock=time.monotonic, newest_first: bool = False) -> dict:
    deadline = clock() + minutes * 60
    report = {'window': [first.isoformat(), last.isoformat()], 'days': [], 'stopped_early': False}
    span = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    for day in (reversed(span) if newest_first else span):
        for exchange in ('nse', 'bse'):
            rows = archive_rows(r2, exchange, day)
            cached = ft.load_day(r2, exchange, day)
            todo = ft.pending(rows, cached)
            tries = dict(zip(cached['event_id'], cached['tries'].fillna(0).astype(int))) if len(cached) else {}
            stat = {'day': day.isoformat(), 'exchange': exchange, 'files': len(rows), 'cached': len(rows) - len(todo),
                    'ok': 0, 'no_text': 0, 'failed': 0}
            new: list[dict] = []

            def one(r):
                if clock() > deadline:
                    return None
                time.sleep(pause)
                return extract_one(r, exchange, tries.get(r['event_id'], 0), download, text_of)

            records = todo.to_dict('records') if todo is not None and len(todo) else []
            with ThreadPoolExecutor(max_workers=workers) as pool:
                for result in pool.map(one, records):
                    if result is None:
                        report['stopped_early'] = True
                        continue
                    new.append(result)
                    stat[result['status']] += 1
                    if len(new) % SAVE_EVERY == 0:
                        cached = ft.merge(cached, pd.DataFrame(new))
                        ft.save_day(r2, exchange, day, cached)
                        new = []
            if new:
                cached = ft.merge(cached, pd.DataFrame(new))
                ft.save_day(r2, exchange, day, cached)
            report['days'].append(stat)
    return report


def markdown(report: dict) -> str:
    out = ['## Filing text cache', '', f'Window {report["window"][0]} to {report["window"][1]}'
           + ('; stopped at the time budget, run again to continue' if report['stopped_early'] else ''), '',
           '| day | exchange | files | already cached | ok | no text | failed |', '|---|---|---|---|---|---|---|']
    for s in report['days']:
        out.append(f'| {s["day"]} | {s["exchange"]} | {s["files"]} | {s["cached"]} | {s["ok"]} | {s["no_text"]} | {s["failed"]} |')
    total = {k: sum(s[k] for s in report['days']) for k in ('files', 'cached', 'ok', 'no_text', 'failed')}
    out.append(f'| **all** | | {total["files"]} | {total["cached"]} | {total["ok"]} | {total["no_text"]} | {total["failed"]} |')
    return '\n'.join(out) + '\n'


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--from', dest='first', type=date.fromisoformat, default=None)
    ap.add_argument('--to', dest='last', type=date.fromisoformat, default=None)
    ap.add_argument('--minutes', type=float, default=300)
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--newest-first', action='store_true', help='start with the last day (a long fill: recent days first)')
    args = ap.parse_args(argv)
    from r2_writer import r2_client
    today = datetime.now(IST).date()
    last = args.last or today
    first = args.first or last - timedelta(days=2)
    report = run(r2_client(), first, last, args.minutes, args.workers, newest_first=args.newest_first)
    text = markdown(report)
    print(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as f:
            f.write(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
