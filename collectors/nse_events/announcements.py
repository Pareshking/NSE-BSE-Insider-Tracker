"""NSE announcements (Reg 30) -> raw_v2/, archive/, and a count report. No model.

    python -m collectors.nse_events.announcements                     # nightly: last 3 days
    python -m collectors.nse_events.announcements --from 2026-09-01   # history, one month per call

Week one of the announcement reader (docs/TODO.md item 29): collect every
announcement NSE broadcasts and count it by subject, so the volume and the
share of filings worth reading are known before any model reads a PDF.

Each answer is stored byte for byte in raw_v2/nse/announcements/ first (a
failed raw write fails the run, rule 5). Rows are merged into
archive/announcements/nse/year=YYYY/month=MM.parquet by event_id (NSE's
seq_id), so re-fetching never adds a filing twice; the month is the
broadcast date's (IST). Two feeds, `market` equities (main board) and sme
(SME board; 6-12 Oct 2026: 3,318 and 699 filings, no seq_id in both).
Concall announcements are not archived (NOT_COLLECTED, counted in the
report). Nothing goes to clean/current/: no
page reads this yet. clean/reports/announcements/{date}.json counts the
window by day, subject and reading group (READING_GROUPS) and the attachment types and sizes.

The groups come from NSE's own subject line only, so they are a first cut:
an 'Outcome of Board Meeting' or 'General Updates' filing may hold a fund
raise that only its PDF names; those are counted as `to_sort`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

from collectors.nse_events.client import Blocked, NSEClient

IST = timezone(timedelta(hours=5, minutes=30))
NIGHTLY_DAYS = 3   # late broadcasts of the last two days are picked up again
PREFIX = 'archive/announcements/nse/'
FEEDS = ('equities', 'sme')   # NSE's index= values; stored as `market`
COLUMNS = ('event_id', 'seq_id', 'market', 'symbol', 'isin', 'company', 'industry', 'subject', 'text', 'file_url',
           'file_type', 'file_size', 'file_bytes', 'has_xbrl', 'broadcast_at', 'disseminated_at', 'broadcast_date')

# NSE subject lines (the `desc` field, exactly as in Sep 2026's 104 subjects)
# for each later reading job. Everything else is routine for that purpose.
READING_GROUPS = {
    'buyback': ('Buyback', 'Public Announcement - Buyback of Shares', 'Post Buyback Public Announcement',
                'Closure of Buy Back'),
    'fund_raise': ('Qualified Institutional Placement', 'Preferential issue', 'Issue of Securities',
                   'Allotment of Securities'),
    'rights': ('Rights Issue',),
    'takeover': ('Disclosure under SEBI Takeover Regulations', 'Public Announcement-Open Offer'),
    # Exploratory: possible trouble, to be labelled as such wherever it is shown.
    'warning': ('Resignation of Statutory Auditor', 'Change in Auditors', 'Credit Rating- Revision',
                'Fraud/Default/Arrest', 'Corporate Insolvency Resolution Process',
                'Action(s) taken or orders passed', 'Action(s) initiated or orders passed',
                'Delay/default in the payment of fines/penalties/dues etc. to authority',
                'Reasons for Delayed/Non-submission of Financial Results', 'Suspension of Trading',
                'Resignation of Director/KMP/SMP'),
    # Broad subjects whose PDF may hold any of the above.
    'to_sort': ('Outcome of Board Meeting', 'General Updates', 'Updates', 'Press Release', 'Others',
                'Disclosure of material issue'),
}
# Not archived (docs/PRODUCT.md, 08 Oct: concalls say nothing about buying
# or selling); counted in the report. The raw copy keeps NSE's whole answer.
NOT_COLLECTED = ('Analysts/Institutional Investor Meet/Con. Call Updates',)
GROUP_OF = {s: g for g, subjects in READING_GROUPS.items() for s in subjects}
# 'Allotment of Securities' also covers debt (IIFL Finance's perpetual NCDs,
# 30 Sep 2026); NSE's one-line text names it, so such filings count as debt.
DEBT = re.compile(r'\bdebentures?\b|\bNCDs?\b|commercial paper|\bbonds?\b', re.IGNORECASE)
SIZE_BANDS = ((256 * 1024, 'under_256KB'), (1024 ** 2, '256KB_1MB'), (5 * 1024 ** 2, '1MB_5MB'),
              (float('inf'), 'over_5MB'))
_SIZE = re.compile(r'^\s*([\d.]+)\s*(B|BYTES|KB|MB|GB)\s*$', re.IGNORECASE)
_UNIT = {'B': 1, 'BYTES': 1, 'KB': 1024, 'MB': 1024 ** 2, 'GB': 1024 ** 3}


def group_of(subject, text=None) -> str:
    g = GROUP_OF.get(str(subject or '').strip(), 'routine')
    return 'debt' if g == 'fund_raise' and DEBT.search(str(text or '')) else g


def size_bytes(text) -> int | None:
    """'370.02 KB' -> 378900; None when NSE gave no readable size. NSE shows
    '0 Bytes' on about 400 filings a month (Sep 2026): kept as 0, as filed."""
    m = _SIZE.match(str(text or ''))
    return int(float(m.group(1)) * _UNIT[m.group(2).upper()]) if m else None


def _ist(text) -> pd.Timestamp | None:
    """'12-Oct-2026 23:46:14' (IST, as NSE shows it) -> aware timestamp."""
    t = pd.to_datetime(text, format='%d-%b-%Y %H:%M:%S', errors='coerce')
    return None if pd.isna(t) else t.tz_localize(IST)


def _text(v):
    return v.strip() if isinstance(v, str) and v.strip() else None


def _file(v):
    """NSE's attachment link, or None where it shows '-' (259 filings in Sep 2026)."""
    v = _text(v)
    return v if v and v.lower().startswith('http') else None


def file_type(url) -> str | None:
    """'pdf', 'zip' (224 in Sep 2026: several PDFs, or a PDF and its XML) or another extension."""
    return url.rsplit('.', 1)[-1].lower() if isinstance(url, str) and '.' in url.rsplit('/', 1)[-1] else None


def parse(rows: list[dict], market: str = 'equities') -> pd.DataFrame:
    """One row per announcement, NSE's values as filed, `market` the feed it came from. A row without a
    seq_id gets an id hashed from its own fields; a row whose broadcast time
    can't be read keeps broadcast_date empty (archived under month=unknown)."""
    out = []
    for r in rows or []:
        seq = _text(str(r.get('seq_id') or ''))
        if seq is None:
            seq = 'h' + hashlib.sha256(json.dumps(r, sort_keys=True, default=str).encode()).hexdigest()[:16]
        at, sent = _ist(r.get('an_dt')), _ist(r.get('exchdisstime'))
        out.append({
            'event_id': f'nse:{seq}', 'seq_id': seq, 'market': market, 'symbol': _text(r.get('symbol')), 'isin': _text(r.get('sm_isin')),
            'company': _text(r.get('sm_name')), 'industry': _text(r.get('smIndustry')),
            'subject': _text(r.get('desc')), 'text': _text(r.get('attchmntText')),
            'file_url': (url := _file(r.get('attchmntFile'))), 'file_type': file_type(url),
            'file_size': _text(r.get('attFileSize') or r.get('fileSize')) if url else None,
            'file_bytes': size_bytes(r.get('attFileSize') or r.get('fileSize')) if url else None,
            'has_xbrl': bool(r.get('hasXbrl')) if r.get('hasXbrl') is not None else None,
            'broadcast_at': at.isoformat() if at is not None else None,
            'disseminated_at': sent.isoformat() if sent is not None else None,
            'broadcast_date': at.date().isoformat() if at is not None else None,
        })
    df = pd.DataFrame(out, columns=list(COLUMNS))
    df['file_bytes'] = df['file_bytes'].astype('Int64')
    df['has_xbrl'] = df['has_xbrl'].astype('boolean')
    return df


def partition(broadcast_date) -> str:
    d = pd.to_datetime(broadcast_date, errors='coerce')
    return 'month=unknown' if pd.isna(d) else f'year={d.year}/month={d.month:02d}'


def merge_into_archive(r2, new: pd.DataFrame, run_date: str) -> tuple[int, list]:
    """(added, partitions written). Only the months tonight's rows fall in are rewritten."""
    from clean_writer import put_parquet, read_parquet

    from insiders_clean import archive
    added, written = 0, []
    if new is None or new.empty:
        return 0, written
    for part, rows in new.groupby(new['broadcast_date'].map(partition)):
        key = f'{PREFIX}{part}.parquet'
        old = read_parquet(r2, key)
        if old is not None and not old.empty and 'market' not in old:
            old = old.assign(market='equities')   # archived before 13 Oct: the equities feed was the only one
        merged, n = archive.merge(old, rows, run_date, key='event_id')
        put_parquet(r2, key, merged)
        written.append(part)
        added += n
    return added, sorted(written)


def counts(df: pd.DataFrame) -> dict:
    """What the window held: by broadcast day, subject, reading group and attachment. Counts only."""
    if df is None or df.empty:
        return {'announcements': 0}
    groups = pd.Series([group_of(s, t) for s, t in zip(df['subject'], df['text'])], index=df.index)
    sizes = df['file_bytes'].map(lambda b: 'size_unreadable' if pd.isna(b) else 'zero_as_filed' if b == 0 else
                                next(name for limit, name in SIZE_BANDS if b < limit))
    by_group = {}
    for g in list(READING_GROUPS) + ['debt', 'routine']:
        sub = df[groups == g]
        if sub.empty:
            continue
        by_group[g] = {'announcements': len(sub),
                       'subjects': {str(k): int(v) for k, v in sub['subject'].fillna('(none)').value_counts().items()},
                       'file_mb_total': round(float(sub['file_bytes'].dropna().sum()) / 1024 ** 2, 1),
                       'file_sizes': {str(k): int(v) for k, v in sizes[groups == g].value_counts().items()}}
    return {
        'announcements': len(df),
        'companies': int(df['symbol'].nunique()),
        'by_market': {str(k): int(v) for k, v in df['market'].value_counts().items()},
        'by_day': {str(k): int(v) for k, v in df['broadcast_date'].fillna('unknown').value_counts().sort_index().items()},
        'without_file': int(df['file_url'].isna().sum()),
        'file_types': {str(k): int(v) for k, v in df['file_type'].fillna('none').value_counts().items()},
        'without_broadcast_time': int(df['broadcast_date'].isna().sum()),
        'text_chars_median': int(df['text'].fillna('').str.len().median()),
        'file_sizes': {str(k): int(v) for k, v in sizes.value_counts().items()},
        'by_group': by_group,
        'subjects': len(df['subject'].dropna().unique()),
        'subjects_seen': {str(k): int(v) for k, v in df['subject'].fillna('(none)').value_counts().items()},
    }


def month_chunks(start: date, end: date) -> list[tuple[date, date]]:
    out, cur = [], start
    while cur <= end:
        nxt = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
        out.append((cur, min(nxt - timedelta(days=1), end)))
        cur = nxt
    return out


def run(r2, nse: NSEClient, today: date, days: int = NIGHTLY_DAYS, raw=None,
        backfill_from: date | None = None, write_report: bool = True, backfill_to: date | None = None) -> dict:
    """The window's filings into raw and the archive; the count report unless `write_report` is False
    (the announcement reader's daytime top-ups, which must not replace the nightly report)."""
    from clean_writer import put
    run_date = today.isoformat()
    start = backfill_from or today - timedelta(days=days - 1)
    end = backfill_to or today
    if end < start:
        raise ValueError('backfill_to must be on or after backfill_from')
    report = {'run_date': run_date, 'window': [start.isoformat(), end.isoformat()], 'calls': [], 'notes': []}
    frames = []
    blocked = False
    for a, b in (month_chunks(start, end) if backfill_from else [(start, end)]):
        for market in FEEDS:
            if raw is not None:
                def hook(url, resp, a=a, b=b, market=market):   # exact bytes before parsing; a failed write stops the run
                    raw.put('nse', 'announcements', resp.content, url=url, status=resp.status_code,
                            content_type=resp.headers.get('Content-Type'),
                            covers={'from': a.isoformat(), 'to': b.isoformat(), 'index': market})
                nse.on_response = hook
            try:
                rows = nse.announcements(a, b, market)
            except Blocked as exc:
                report['notes'].append(f'NSE refused ({exc}); stopped, what was fetched is kept')
                blocked = True
                break
            except Exception as exc:  # noqa: BLE001 -- one failing month or feed must not lose the others
                report['notes'].append(f'{market} {a}..{b}: fetch failed ({type(exc).__name__}: {exc})')
                continue
            df = parse(rows, market)
            skip = df['subject'].isin(NOT_COLLECTED)
            report['calls'].append({'market': market, 'from': a.isoformat(), 'to': b.isoformat(), 'rows': len(df),
                                    'not_archived_concall': int(skip.sum())})
            frames.append(df[~skip])
        if blocked:
            break
    nse.on_response = None
    new = pd.concat(frames, ignore_index=True).drop_duplicates('event_id', keep='last') if frames else None
    report['added'], report['partitions_written'] = merge_into_archive(r2, new, run_date)
    report['window_counts'] = counts(new)
    report['nse_calls'] = nse.calls
    if write_report:
        put(r2, f'clean/reports/announcements/{run_date}.json', json.dumps(report, indent=2, default=str).encode(),
            'application/json')
    return report


def history_collection_errors(report: dict) -> list[str]:
    """Return every coverage gap that must block a historical completion marker."""
    try:
        start, end = (date.fromisoformat(x) for x in report['window'])
    except (KeyError, TypeError, ValueError):
        return ['invalid collection window']
    expected = {
        (a.isoformat(), b.isoformat(), market)
        for a, b in month_chunks(start, end)
        for market in FEEDS
    }
    actual = {
        (str(call.get('from')), str(call.get('to')), str(call.get('market')))
        for call in report.get('calls', [])
    }
    errors = list(report.get('notes') or [])
    missing = sorted(expected - actual)
    if missing:
        errors.append('missing NSE feed windows: ' + ', '.join('/'.join(x) for x in missing))
    return errors


def summary_markdown(report: dict) -> str:
    """The run's counts as a short table for the GitHub run page."""
    c = report.get('window_counts', {})
    concall = sum(x['not_archived_concall'] for x in report.get('calls', []))
    lines = [f"### NSE announcements {report['window'][0]} to {report['window'][1]}", '',
             (f"{c.get('announcements', 0)} announcements from {c.get('companies', 0)} companies "
              f"({', '.join(f'{k} {v}' for k, v in c.get('by_market', {}).items())}), "
              f"{report.get('added', 0)} new to the archive; {concall} concall announcements not archived."), '',
             '| Reading group | Announcements | File MB |', '|---|---|---|']
    for g, e in c.get('by_group', {}).items():
        lines.append(f"| {g} | {e['announcements']} | {e['file_mb_total']} |")
    lines += ['', '| Day | Announcements |', '|---|---|']
    lines += [f'| {d} | {n} |' for d, n in c.get('by_day', {}).items()]
    lines += [f'- note: {n}' for n in report.get('notes', [])]
    return '\n'.join(lines) + '\n'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--days', type=int, default=NIGHTLY_DAYS)
    ap.add_argument('--from', dest='backfill_from', type=date.fromisoformat, default=None,
                    help='history: first date to fetch (YYYY-MM-DD)')
    ap.add_argument('--to', dest='backfill_to', type=date.fromisoformat, default=None,
                    help='history: last date to fetch (YYYY-MM-DD); pair with --from')
    ap.add_argument('--strict-history', action='store_true',
                    help='fail unless every NSE feed window was fetched without notes')
    args = ap.parse_args(argv)
    if args.strict_history and (args.backfill_from is None or args.backfill_to is None):
        ap.error('--strict-history requires both --from and --to')
    from r2_writer import BUCKET, r2_client

    from insiders_clean.raw_store import RawStore
    r2 = r2_client()
    report = run(r2, NSEClient(), datetime.now(IST).date(), args.days,
                 raw=RawStore(r2, bucket=BUCKET, collector='nse_announcements'), backfill_from=args.backfill_from,
                 backfill_to=args.backfill_to)
    text = summary_markdown(report)
    print(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as f:
            f.write(text)
    if args.strict_history:
        errors = history_collection_errors(report)
        if errors:
            sys.exit('incomplete NSE history collection: ' + '; '.join(errors))
    if not report['calls']:
        sys.exit('no announcement list was fetched')


if __name__ == '__main__':
    main()
