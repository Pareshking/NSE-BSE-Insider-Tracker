"""BSE announcements -> raw_v2/, archive/, and a count report. No model.

    python -m collectors.bse.announcements                     # nightly: last 3 days
    python -m collectors.bse.announcements --from 2026-10-01   # history, day by day
    python -m collectors.bse.announcements --days 1 --dry-run  # fetch and count, write nothing

The BSE half of the announcement reader's first step (docs/TODO.md item 29,
docs/ANNOUNCEMENT_READER.md): every filing BSE disseminates, so the companies
listed only on BSE are covered. A company on both exchanges files the same
document twice; both copies are kept here and the reader reads one (same file
or same text read once). Each filing is marked `on_nse` through the security
master in the report, so the BSE-only share is counted.

BSE answers 50 filings a page, newest first, with its count for the day
(collectors/bse/client.py); every day of the window is read page by page
until that count is reached, and a day that ends short is listed in the
report. Each page is stored byte for byte in raw_v2/bse/announcements/ first.
Rows are merged into archive/announcements/bse/year=YYYY/month=MM.parquet by
event_id (BSE's NEWSID), so fetching a day again never adds a filing twice.
Concall filings (CONCALL) are archived like the rest since 15 Oct (owner: everything is captured) and counted in the report.
clean/reports/announcements_bse/{date}.json counts the window by day,
category, reading group and NSE listing.

The groups come from BSE's own subcategory, mapped to the NSE collector's
groups (collectors/nse_events/announcements.py) from the 1,136 filings of
12 Oct 2026; a subcategory not seen that day is routine until it is added.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

from collectors.bse.client import BSEClient, Blocked, Failed

IST = timezone(timedelta(hours=5, minutes=30))
NIGHTLY_DAYS = 3
MAX_PAGES = 200   # 10,000 filings in a day; BSE's busiest day seen is far below
SHORT_RETRIES = 2   # a day that ends below BSE's own count is fetched again this many times, pages merged
SHORT_PAUSE = 20    # seconds before such a repeat
RECONCILIATION = 'clean/reports/announcements_bse/reconciliation/'   # {day}.json: BSE's count against ours
PREFIX = 'archive/announcements/bse/'
ATTACHMENT = 'https://www.bseindia.com/xml-data/corpfiling/AttachLive/'
COLUMNS = ('event_id', 'news_id', 'bse_code', 'company', 'category', 'subcategory', 'subject', 'headline',
           'critical', 'file_url', 'file_type', 'file_bytes', 'broadcast_at', 'disseminated_at', 'broadcast_date')

# BSE subcategories (SUBCATNAME as on 12 Oct 2026) for each reading group; the
# group names are the NSE collector's. Everything else is routine.
READING_GROUPS = {
    'buyback': (),   # 12 Oct held only 'Daily Buy Back of equity shares' (daily reporting, routine)
    'fund_raise': ('Qualified Institutional Placement', 'Preferential Issue', 'Allotment of Equity Shares'),
    'rights': (),
    'takeover': ('Open Offer', 'Open Offer - Updates',
                 'Disclosures under Reg. 29(1) of SEBI (SAST) Regulations, 2011',
                 'Disclosures under Reg. 29(2) of SEBI (SAST) Regulations, 2011',
                 'Disclosures under Reg. 31(1) and 31(2) of SEBI (SAST) Regulations, 2011'),
    # Exploratory, as on NSE: possible trouble, labelled as such wherever shown.
    'warning': ('Credit Rating', 'Resignation of Director', 'Resignation of Company Secretary / Compliance Officer',
                'Resignation of Chief Financial Officer (CFO)'),
    # Core types of the owner's triage (16 Oct) that were routine: orders and management or director changes.
    'core': ('Award of Order / Receipt of Order', 'Change in Management', 'Change in Directorate'),
    # Broad subcategories whose PDF may hold any of the above ('Others' with no subcategory too).
    'to_sort': ('General', 'Outcome of Board Meeting', 'Press Release / Media Release',
                'Press Release / Media Release (Revised)', 'Outcome without intimation', 'Acquisition',
                'Scheme of Arrangement', 'Restructuring'),
}
CONCALL = ('Analyst / Investor Meet', 'Earnings Call Transcript')   # not archived until 15 Oct (08 Oct decision); archived since
GROUP_OF = {s: g for g, subs in READING_GROUPS.items() for s in subs}


def group_of(subcategory, category=None) -> str:
    sub = str(subcategory or '').strip()
    if not sub and str(category or '').strip() == 'Others':
        return 'to_sort'
    return GROUP_OF.get(sub, 'routine')


def _text(v):
    return v.strip() if isinstance(v, str) and v.strip() else None


def _ist(text) -> pd.Timestamp | None:
    """'2026-10-12T23:57:46.997' (IST, as BSE gives it) -> aware timestamp."""
    t = pd.to_datetime(text, errors='coerce', format='ISO8601')
    return None if pd.isna(t) else t.tz_localize(IST)


def parse(rows: list[dict]) -> pd.DataFrame:
    """One row per filing, BSE's values as filed. A row without NEWSID is dropped and counted by the caller."""
    out = []
    for r in rows or []:
        news = _text(r.get('NEWSID'))
        if news is None:
            continue
        at, sent = _ist(r.get('NEWS_DT') or r.get('DT_TM')), _ist(r.get('DissemDT'))
        name = _text(r.get('ATTACHMENTNAME'))
        size = r.get('Fld_Attachsize')
        out.append({
            'event_id': f'bse:{news.lower()}', 'news_id': news,
            'bse_code': str(r['SCRIP_CD']) if r.get('SCRIP_CD') is not None else None,
            'company': _text(r.get('SLONGNAME')), 'category': _text(r.get('CATEGORYNAME')),
            'subcategory': _text(r.get('SUBCATNAME')), 'subject': _text(r.get('NEWSSUB')),
            'headline': _text(r.get('HEADLINE')), 'critical': str(r.get('CRITICALNEWS') or '').strip() == '1',
            'file_url': ATTACHMENT + name if name else None,
            'file_type': name.rsplit('.', 1)[-1].lower() if name and '.' in name else None,
            'file_bytes': int(size) if isinstance(size, (int, float)) and name else None,
            'broadcast_at': at.isoformat() if at is not None else None,
            'disseminated_at': sent.isoformat() if sent is not None else None,
            'broadcast_date': at.date().isoformat() if at is not None else None,
        })
    df = pd.DataFrame(out, columns=list(COLUMNS))
    df['file_bytes'] = df['file_bytes'].astype('Int64')
    return df


def fetch_day(bse: BSEClient, day: date, known: set | None = None) -> tuple[list[dict], dict]:
    """Every page of one day; (rows, {'bse_count', 'pages', 'rows', 'short'}). With `known` (NEWSIDs already
    archived), paging stops at the first page holding only known filings: pages run newest first, so the
    rest are known too (the announcement reader's top-ups through the day)."""
    rows, total, page, caught_up = [], None, 0, False
    while page < MAX_PAGES:
        page += 1
        got, count = bse.announcements(day, page)
        total = count if count is not None else total
        rows += got
        # Do not treat a page of rows without an ID as a catch-up page: `all([])` is True, which would
        # silently stop before older pages.
        eligible = [r for r in got if r.get('NEWSID')]
        if known is not None and got and eligible and all(str(r['NEWSID']).lower() in known for r in eligible):
            caught_up = True
            break
        if not got or (total is not None and len(rows) >= total):
            break
    unique = {row_key(r) for r in rows}
    return rows, {'day': day.isoformat(), 'bse_count': total, 'pages': page, 'rows': len(rows),
                  'unique': len(unique), 'caught_up': caught_up,
                  'short': not caught_up and total is not None and len(unique) < total}


def row_key(r: dict) -> str:
    """NEWSID (lower case), else a hash of the whole row: a row without an ID is still one filing, not 'None'."""
    news = r.get('NEWSID')
    return str(news).lower() if news else 'noid:' + hashlib.sha256(json.dumps(r, sort_keys=True, default=str).encode()).hexdigest()[:16]


def fetch_day_complete(bse, day: date, known=None, retries: int | None = None, pause: float | None = None,
                       sleep=None) -> tuple[list, dict]:
    """fetch_day, fetched again (pages merged by row) while the day ends below BSE's own count.
    15 Oct: 31 Mar, 24 Apr and 19 May each came back about 500 filings short and a fresh fetch was complete."""
    retries = SHORT_RETRIES if retries is None else retries
    pause = SHORT_PAUSE if pause is None else pause
    rows, stats = fetch_day(bse, day, known)
    attempts = 0
    while stats['short'] and attempts < retries:
        attempts += 1
        print(f"BSE collection: {day.isoformat()} short ({stats['unique']} of {stats['bse_count']}); fetching again "
              f'({attempts} of {retries})', flush=True)
        (sleep or time.sleep)(pause)
        more, again = fetch_day(bse, day, known)
        have = {row_key(r) for r in rows}
        rows = rows + [r for r in more if row_key(r) not in have]
        total = again['bse_count'] if again['bse_count'] is not None else stats['bse_count']
        unique = len({row_key(r) for r in rows})
        stats = {**stats, 'bse_count': total, 'pages': stats['pages'] + again['pages'], 'rows': len(rows),
                 'unique': unique, 'short': total is not None and unique < total}
    stats['retries'] = attempts
    return rows, stats


def save_reconciliation(r2, stats: dict, rows: list, run_id: str | None = None) -> None:
    """BSE's count against ours for one day, kept in R2 (the latest full fetch of the day), with the rows that have no
    NEWSID (the archive cannot key them; the raw answers also hold them)."""
    from clean_writer import put
    keep = ('SCRIP_CD', 'SLONGNAME', 'NEWSSUB', 'DT_TM', 'CATEGORYNAME', 'SUBCATNAME', 'ATTACHMENTNAME')
    without_id = [{k: r.get(k) for k in keep} for r in rows if not r.get('NEWSID')][:50]
    body = {'day': stats['day'], 'bse_count': stats['bse_count'], 'fetched_unique': stats['unique'],
            'rows_without_id': sum(1 for r in rows if not r.get('NEWSID')), 'pages': stats['pages'],
            'retries': stats.get('retries', 0), 'short': stats['short'],
            'checked_at_utc': datetime.now(timezone.utc).isoformat(),
            'workflow_run_id': run_id or os.environ.get('GITHUB_RUN_ID'), 'without_id': without_id}
    put(r2, f"{RECONCILIATION}{stats['day']}.json", json.dumps(body, indent=1, default=str).encode(), 'application/json')


def known_ids(r2, day: date) -> set:
    """event ids (NEWSIDs, lower case) of `day` already in the archive."""
    from clean_writer import read_parquet
    arch = read_parquet(r2, f'{PREFIX}{partition(day.isoformat())}.parquet')
    if arch is None or arch.empty:
        return set()
    return set(arch.loc[arch['broadcast_date'] == day.isoformat(), 'news_id'].astype(str).str.lower())


def partition(broadcast_date) -> str:
    d = pd.to_datetime(broadcast_date, errors='coerce')
    return 'month=unknown' if pd.isna(d) else f'year={d.year}/month={d.month:02d}'


def merge_into_archive(r2, new: pd.DataFrame, run_date: str) -> tuple[int, list]:
    from clean_writer import put_parquet, read_parquet

    from insiders_clean import archive
    added, written = 0, []
    if new is None or new.empty:
        return 0, written
    for part, rows in new.groupby(new['broadcast_date'].map(partition)):
        key = f'{PREFIX}{part}.parquet'
        merged, n = archive.merge(read_parquet(r2, key), rows, run_date, key='event_id')
        put_parquet(r2, key, merged)
        written.append(part)
        added += n
    return added, sorted(written)


def on_nse(df: pd.DataFrame, master) -> pd.Series:
    """True where the security master gives the BSE code an NSE symbol; None without a master."""
    if master is None:
        return pd.Series([None] * len(df), index=df.index, dtype=object)
    isin = [master.resolve('bse', c)[0] if c else None for c in df['bse_code']]
    return pd.Series([bool((master.record(i) or {}).get('nse_symbol')) if i else False for i in isin],
                     index=df.index, dtype=object)


def counts(df: pd.DataFrame, listed: pd.Series | None = None) -> dict:
    if df is None or df.empty:
        return {'announcements': 0}
    groups = pd.Series([group_of(s, c) for s, c in zip(df['subcategory'], df['category'])], index=df.index)
    out = {
        'announcements': len(df),
        'companies': int(df['bse_code'].nunique()),
        'by_day': {str(k): int(v) for k, v in df['broadcast_date'].fillna('unknown').value_counts().sort_index().items()},
        'without_file': int(df['file_url'].isna().sum()),
        'file_types': {str(k): int(v) for k, v in df['file_type'].fillna('none').value_counts().items()},
        'by_group': {g: int(n) for g, n in groups.value_counts().items()},
        'subcategories_seen': {str(k): int(v) for k, v in
                               (df['category'].fillna('') + ' / ' + df['subcategory'].fillna('(none)'))
                               .value_counts().items()},
    }
    if listed is not None and listed.notna().any():
        bse_only = listed == False   # noqa: E712 -- object column: True, False or None
        out['bse_only'] = {'announcements': int(bse_only.sum()),
                           'companies': int(df.loc[bse_only, 'bse_code'].nunique()),
                           'by_group': {g: int(n) for g, n in groups[bse_only].value_counts().items()}}
    return out


def run(r2, bse: BSEClient, today: date, days: int = NIGHTLY_DAYS, start: date | None = None,
        master=None, write_report: bool = True, incremental: bool = False, end: date | None = None) -> dict:
    """The nightly window, or every day from `start` (history). `r2` None = dry run. `write_report` False:
    the announcement reader's daytime top-ups, which must not replace the nightly report."""
    from clean_writer import put
    run_date = today.isoformat()
    first = start or today - timedelta(days=days - 1)
    last = end or today
    if last < first:
        raise ValueError('end must be on or after start')
    report = {'run_date': run_date, 'window': [first.isoformat(), last.isoformat()], 'days': [], 'notes': [],
              'dry_run': r2 is None}
    frames, dropped = [], 0
    day = first
    while day <= last:
        print(f'BSE collection: starting {day.isoformat()}', flush=True)
        try:
            rows, stats = fetch_day_complete(bse, day, known_ids(r2, day) if incremental and r2 is not None else None)
        except Blocked as exc:
            report['notes'].append(f'BSE refused ({exc}); stopped, what was fetched is kept')
            print(f'BSE collection: blocked on {day.isoformat()}; stopping this window.', flush=True)
            break
        except Failed as exc:
            report['notes'].append(f'{day}: fetch failed ({exc})')
            print(f'BSE collection: failed {day.isoformat()} ({exc}); continuing but month cannot be certified.', flush=True)
            day += timedelta(days=1)
            continue
        if r2 is not None and not stats['caught_up']:   # a full fetch of the day: keep BSE's count against ours
            try:
                save_reconciliation(r2, stats, rows)
            except Exception as exc:  # noqa: BLE001 -- the record must not stop the collection
                report['notes'].append(f'{day}: reconciliation not saved ({type(exc).__name__}: {exc})')
        df = parse(rows)
        dropped += len(rows) - len(df)
        stats['concall'] = int(df['subcategory'].isin(CONCALL).sum())
        report['days'].append(stats)
        frames.append(df)
        print(f"BSE collection: finished {day.isoformat()} pages={stats['pages']} "
              f"reported={stats['bse_count']} fetched_unique={stats['unique']} short={stats['short']}",
              flush=True)
        day += timedelta(days=1)
    if dropped:
        report['notes'].append(f'{dropped} rows without NEWSID not archived')
    short = [d['day'] for d in report['days'] if d['short']]
    if short:
        report['notes'].append(f'fewer filings than BSE counts on {", ".join(short)}')
    # A finished day still short after the repeats fails the run; today's own day can grow while it is read.
    report['short_days'] = [d for d in short if d < today.isoformat()]
    new = pd.concat(frames, ignore_index=True).drop_duplicates('event_id', keep='last') if frames else None
    report['added'], report['partitions_written'] = merge_into_archive(r2, new, run_date) if r2 else (0, [])
    report['window_counts'] = counts(new, on_nse(new, master) if new is not None else None)
    report['bse_calls'], report['via'] = bse.calls, bse.via
    if r2 is not None and write_report:
        put(r2, f'clean/reports/announcements_bse/{run_date}.json',
            json.dumps(report, indent=2, default=str).encode(), 'application/json')
    return report


def summary_markdown(report: dict) -> str:
    c = report.get('window_counts', {})
    concall = sum(d.get('concall', 0) for d in report.get('days', []))
    only = c.get('bse_only')
    lines = [f"### BSE announcements {report['window'][0]} to {report['window'][1]}", '',
             (f"{c.get('announcements', 0)} announcements from {c.get('companies', 0)} companies, "
              f"{report.get('added', 0)} new to the archive; {concall} of them concall announcements; "
              + (f"BSE only (no NSE listing): {only['announcements']} from {only['companies']} companies."
                 if only else 'BSE-only share not counted (no security master).')), '',
             '| Reading group | Announcements | BSE only |', '|---|---|---|']
    for g, n in c.get('by_group', {}).items():
        lines.append(f"| {g} | {n} | {(only or {}).get('by_group', {}).get(g, '-') if only else '-'} |")
    lines += ['', '| Day | BSE count | Fetched | Pages |', '|---|---|---|---|']
    lines += [f"| {d['day']} | {d['bse_count']} | {d['unique']} | {d['pages']} |" for d in report.get('days', [])]
    lines += [f'- note: {n}' for n in report.get('notes', [])]
    lines.append(f"- BSE calls: {report.get('bse_calls')} ({report.get('via')})")
    return '\n'.join(lines) + '\n'


def main(argv=None):
    import os
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--days', type=int, default=NIGHTLY_DAYS)
    ap.add_argument('--from', dest='start', type=date.fromisoformat, default=None,
                    help='history: first date to fetch (YYYY-MM-DD)')
    ap.add_argument('--to', dest='end', type=date.fromisoformat, default=None,
                    help='history: last date to fetch (YYYY-MM-DD); pair with --from')
    ap.add_argument('--dry-run', action='store_true', help='fetch and count; write nothing')
    args = ap.parse_args(argv)
    today = datetime.now(IST).date()
    r2, raw, master = None, None, None
    if not args.dry_run:
        from r2_writer import r2_client

        from collectors.nse_events.run_daily import security_master
        from insiders_clean.raw_store import RawStore
        r2 = r2_client()
        raw = RawStore(r2, collector='bse_announcements')
        notes: list = []
        try:
            master = security_master(r2, today.isoformat(), notes)
        except Exception as exc:  # noqa: BLE001 -- the counts go without the BSE-only share
            print(f'  note: no security master ({type(exc).__name__}: {exc})')
    bse = BSEClient(raw=raw)
    try:
        report = run(r2, bse, today, args.days, args.start, master, end=args.end)
    finally:
        bse.close()
    text = summary_markdown(report)
    print(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as f:
            f.write(text)
    if report.get('short_days'):
        print(f"BSE collection: still short after repeats: {', '.join(report['short_days'])}", flush=True)
        return 3
    return 0 if report['days'] else 2


if __name__ == '__main__':
    sys.exit(main())
