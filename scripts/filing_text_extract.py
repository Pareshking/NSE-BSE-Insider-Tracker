"""Fill the filing text cache (insiders_clean/filing_text.py): download each announcement file once and keep its text.

For every NSE and BSE announcement in the window with a PDF, ZIP or XBRL file and no finished cache record, the file is
downloaded (BSE with the AttachHis fallback), turned into text exactly as the reader does it, and written to
archive/filing_text/{exchange}/year=/month=/day=.parquet. Resumable: a record already `ok` or `no_text` is skipped, a
failed one is retried up to 3 times (a missing file never). The cache is saved every 100 filings and at the end, and
the run stops starting new files at --minutes. No model is called. The XBRL-feed rows (`nse:xbrl:*`) are left out:
their files are the main feed's own.

Speed (14 Nov 2026 run: 3,034 files in 161 minutes; downloads about 2% of the workers' time, tesseract and drawing the
pages for it nearly all the rest). Every filing is still downloaded and gets its own record, but a file whose bytes were
already read that day (the same PDF filed on NSE and on BSE, or under two BSE announcements: 1,205 of that run's 3,026
downloads repeated an earlier size, and the pairs checked were byte-identical) takes the text of that read instead of
being OCR'd again: the same bytes through the same extractor give the same text. Filings are read --workers at a time
(FILING_TEXT_WORKERS, default one per CPU), at most 4 downloads at once from one host, the pause before each download
kept; OCR runs one page per CPU (announcement_sample.OCR_SLOTS).

    python scripts/filing_text_extract.py --from 2026-10-14 --to 2026-10-15
    python scripts/filing_text_extract.py            # the last 3 days, as the nightly collector's window
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import announcement_sample as sample  # noqa: E402
from insiders_clean import filing_text as ft  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
FILE_TYPES = ('pdf', 'zip', 'xbrl')
SAVE_EVERY = 100
PER_HOST = 4             # downloads at once from one exchange host, whatever --workers is


def default_workers() -> int:
    try:
        return max(1, int(os.environ.get('FILING_TEXT_WORKERS') or 0) or os.cpu_count() or 4)
    except ValueError:
        return max(1, os.cpu_count() or 4)


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


class SameFile:
    """text_of with a memory of one day's files: bytes already read (same sha256) give the text of that read instead of
    a second OCR of the same pages. A file another thread is reading is waited for, not read twice; when that read
    raised, a waiting filing reads the file itself, so a failure stays with the filing it happened to. Only finished
    reads are kept, and the day's cache records of the current extractor seed it."""

    def __init__(self, text_of):
        self.text_of, self.done, self.busy, self.lock = text_of, {}, {}, threading.Lock()

    def seed(self, cached: pd.DataFrame) -> None:
        if cached is None or not len(cached):
            return
        ok = cached[cached['status'].isin(ft.DONE) & (cached['extractor'] == ft.EXTRACTOR) & cached['file_sha256'].notna()]
        with self.lock:
            for sha, text, notes in zip(ok['file_sha256'], ok['text'], ok['notes']):
                self.done.setdefault((sha, None), (text if isinstance(text, str) else '',
                                                   [notes] if isinstance(notes, str) and notes else []))

    def __call__(self, data: bytes, limit=None):
        key = (hashlib.sha256(data).hexdigest(), limit)
        while True:
            with self.lock:
                if key in self.done:
                    text, notes = self.done[key]
                    return text, list(notes)
                reading = self.busy.get(key)
                if reading is None:
                    self.busy[key] = threading.Event()
                    break
            reading.wait()        # then: its text, or (it raised) this filing reads the file itself
        try:
            text, notes = self.text_of(data, limit=limit)
            with self.lock:
                self.done[key] = (text, list(notes))
            return text, notes
        finally:
            with self.lock:
                self.busy.pop(key).set()


def paced(download, per_host: int = PER_HOST):
    """download with at most per_host (never more than PER_HOST) requests in flight to one host."""
    gates, lock = {}, threading.Lock()

    def get(url):
        host = urlsplit(str(url)).netloc.lower()
        with lock:
            gate = gates.setdefault(host, threading.BoundedSemaphore(max(1, min(per_host, PER_HOST))))
        with gate:
            return download(url)
    return get


def run(r2, first: date, last: date, minutes: float = 300, workers: int = 4, pause: float = 0.3,
        download=sample.download, text_of=sample.text_of, clock=time.monotonic, newest_first: bool = False) -> dict:
    deadline = clock() + minutes * 60
    report = {'window': [first.isoformat(), last.isoformat()], 'days': [], 'stopped_early': False}
    span = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    download = paced(download)
    for day in (reversed(span) if newest_first else span):
        same = SameFile(text_of)          # one day's memory: NSE's file and BSE's copy of it are read once
        for exchange in ('nse', 'bse'):
            rows = archive_rows(r2, exchange, day)
            cached = ft.load_day(r2, exchange, day)
            same.seed(cached)
            todo = ft.pending(rows, cached)
            tries = dict(zip(cached['event_id'], cached['tries'].fillna(0).astype(int))) if len(cached) else {}
            stat = {'day': day.isoformat(), 'exchange': exchange, 'files': len(rows), 'cached': len(rows) - len(todo),
                    'ok': 0, 'no_text': 0, 'failed': 0}
            new: list[dict] = []

            def one(r):
                if clock() > deadline:
                    return None
                time.sleep(pause)
                return extract_one(r, exchange, tries.get(r['event_id'], 0), download, same)

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
    ap.add_argument('--workers', type=int, default=default_workers(), help='filings at once (FILING_TEXT_WORKERS; default one per CPU)')
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
