"""BSE SAST (Reg 29) and corporate actions -> archive/ and clean/.

    python -m collectors.bse.events                          # nightly: last 30 days
    python -m collectors.bse.events --from 2025-10-08 --to 2026-10-12 --dataset sast   # history, resumable
    python -m collectors.bse.events --days 30 --dry-run      # fetch and count, write nothing

Each answer is stored in raw_v2/bse/{sast|corporate_actions}/ first. Rows are
merged into archive/bse_events/{stream}/year=YYYY.parquet by event_id (a hash
of the fields that identify the disclosure or action, so fetching it again
never adds it twice); the year is the row's own date. Then
clean/current/bse_{stream}.parquet is rebuilt from the whole archive, each row
linked to NSE's clean table where NSE has the same disclosure or action
(insiders_clean/bse_events.py), and clean/reports/bse_events/{date}.json says
what was fetched, added, dropped, linked and left empty.

SAST answers [] for some windows that do hold rows (client.py), so every
window is read as three tilings (the whole window, 7-day pieces, and 7-day
pieces shifted by 3 days); a 7-day piece that answers [] is split in halves
down to one day, and the rows of all tilings are united by event_id. Weekdays with no
row in any tiling are listed in the report: a holiday, a day with no
disclosure, or a day BSE did not answer for.

History (--from/--to) goes month by month and records the months done in
archive/_backfill/bse_{stream}.json, so a rerun resumes; the nightly window is
always fetched again (late filings). A 401/403/429 stops all further BSE calls
for the run; what was fetched is still stored.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

from collectors.bse import parsers
from collectors.bse.client import BSEClient, Blocked, Failed
from insiders_clean import archive, bse_events

STREAMS = ('sast', 'actions')
DATE_COLUMN = {'sast': 'trade_date_to', 'actions': 'ex_date'}
NSE_TABLE = {'sast': 'clean/current/sast.parquet', 'actions': 'clean/current/actions.parquet'}
IST = timezone(timedelta(hours=5, minutes=30))
NIGHTLY_DAYS = 30  # SAST disclosures arrive days or weeks after the trade
TILE_DAYS, TILE_SHIFT = 7, 3


def prefix(stream):
    return f'archive/bse_events/{stream}/'


def progress_key(stream):
    return f'archive/_backfill/bse_{stream}.json'


def months(a: date, b: date) -> list[tuple[date, date]]:
    out, cur = [], a
    while cur <= b:
        nxt = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
        out.append((cur, min(nxt - timedelta(days=1), b)))
        cur = nxt
    return out


def pieces(a: date, b: date, days: int, shift: int = 0) -> list[tuple[date, date]]:
    out, cur = [], a
    if shift:
        first = min(a + timedelta(days=shift - 1), b)
        out.append((a, first))
        cur = first + timedelta(days=1)
    while cur <= b:
        end = min(cur + timedelta(days=days - 1), b)
        out.append((cur, end))
        cur = end + timedelta(days=1)
    return out


def sast_window(bse: BSEClient, a: date, b: date, stats: dict) -> list[dict]:
    """Every SAST row BSE gives for [a, b], over three tilings (see above)."""
    rows, seen_days = {}, set()

    def get(x, y, split):
        got = bse.sast(x, y)
        stats['calls'] = stats.get('calls', 0) + 1
        if got or x == y or not split:
            if not got and x == y:
                stats['empty_single_days'] = stats.get('empty_single_days', 0) + 1
            return got
        stats['split_on_empty'] = stats.get('split_on_empty', 0) + 1
        mid = x + timedelta(days=(y - x).days // 2)
        return get(x, mid, split) + get(mid + timedelta(days=1), y, split)

    # Only the 7-day tiling is split (a split costs calls on days that are
    # really empty); the whole window and the shifted tiling are one call a piece.
    tilings = [([(a, b)], False), (pieces(a, b, TILE_DAYS), True)]
    if (b - a).days >= TILE_SHIFT:
        tilings.append((pieces(a, b, TILE_DAYS, TILE_SHIFT), False))
    for tiling, split in tilings:
        for x, y in tiling:
            for r in get(x, y, split):
                rows[parsers.sast_event_id(r)] = r
    for r in rows.values():
        d = pd.to_datetime(str(r.get('Acquisition_date') or '')[:10], format='%d/%m/%Y', errors='coerce')
        if pd.notna(d):
            seen_days.add(d.date())
    stats.setdefault('weekdays_without_rows', []).extend(
        (a + timedelta(days=i)).isoformat() for i in range((b - a).days + 1)
        if (a + timedelta(days=i)).weekday() < 5 and (a + timedelta(days=i)) not in seen_days)
    return list(rows.values())


def fetch(bse: BSEClient, stream: str, a: date, b: date, stats: dict) -> pd.DataFrame:
    if stream == 'sast':
        frame, extra = parsers.parse_sast(sast_window(bse, a, b, stats))
        for reg, n in extra['dropped_other_regulations'].items():
            d = stats.setdefault('dropped_other_regulations', {})
            d[reg] = d.get(reg, 0) + n
    else:
        frame, dropped = parsers.parse_actions(bse.actions(a, b))
        stats['calls'] = stats.get('calls', 0) + 1
        stats['dropped_other_purposes'] = stats.get('dropped_other_purposes', 0) + dropped
    stats['fetched'] = stats.get('fetched', 0) + len(frame)
    return frame


def year_of(series: pd.Series) -> pd.Series:
    d = pd.to_datetime(series, errors='coerce')
    return d.dt.year.map(lambda y: f'year={int(y)}' if pd.notna(y) else 'year=unknown')


class Store:
    """The archive and clean tables in R2 (functions from scripts/clean_writer.py)."""

    def __init__(self, r2):
        import clean_writer as cw
        self.r2, self.cw = r2, cw

    def merge(self, stream, new: pd.DataFrame, run_date: str) -> tuple[int, list]:
        added, parts = 0, []
        if new is None or new.empty:
            return 0, parts
        for part, rows in new.groupby(year_of(new[DATE_COLUMN[stream]])):
            key = f'{prefix(stream)}{part}.parquet'
            merged, n = archive.merge(self.cw.read_parquet(self.r2, key), rows, run_date, key='event_id')
            self.cw.put_parquet(self.r2, key, merged)
            added += n
            parts.append(part)
        return added, parts

    def whole(self, stream) -> pd.DataFrame | None:
        keys = sorted(k for k in self.cw.list_keys(self.r2, prefix(stream)) if k.endswith('.parquet'))
        frames = [f for f in (self.cw.read_parquet(self.r2, k) for k in keys) if f is not None and not f.empty]
        return pd.concat(frames, ignore_index=True) if frames else None

    def json(self, key):
        body = self.cw.get(self.r2, key)
        return json.loads(body) if body else None

    def put_json(self, key, obj):
        self.cw.put(self.r2, key, json.dumps(obj, indent=2, default=str).encode(), 'application/json')


def run(store: Store | None, bse: BSEClient, today: date, streams=STREAMS, start: date | None = None,
        end: date | None = None, days: int = NIGHTLY_DAYS, redo: bool = False, master=None, log=print) -> dict:
    """History when `start` is given (month by month, resumable), else the
    nightly window. `store` None = dry run (fetch and count only)."""
    run_date = today.isoformat()
    history = start is not None
    a, b = (start, end or today) if history else (today - timedelta(days=days), today)
    report = {'run_date': run_date, 'mode': 'history' if history else 'nightly', 'window': [a.isoformat(), b.isoformat()],
              'streams': {}, 'notes': [], 'dry_run': store is None}
    blocked = False
    for stream in streams:
        stats = report['streams'].setdefault(stream, {'chunks_done': 0, 'chunks_skipped_done': 0, 'added': 0, 'errors': []})
        progress = (store.json(progress_key(stream)) if store and history else None) or {'stream': stream, 'chunks': {}}
        done = {} if redo or not history else progress['chunks']
        for x, y in (months(a, b) if history else [(a, b)]):
            key = f'{x.isoformat()}..{y.isoformat()}'
            if blocked:
                break
            if key in done:
                stats['chunks_skipped_done'] += 1
                continue
            try:
                frame = fetch(bse, stream, x, y, stats)
            except Blocked as exc:
                blocked = True
                stats['stopped_at'] = {'chunk': key, 'reason': str(exc)}
                report['notes'].append(f'{stream}: BSE refused ({exc}); no further BSE calls this run')
                break
            except Failed as exc:
                stats['errors'].append({'chunk': key, 'error': str(exc)})
                continue
            added, parts = store.merge(stream, frame, run_date) if store else (0, [])
            stats['added'] += added
            stats['chunks_done'] += 1
            log(f'  {stream} {key}: {len(frame)} rows, {added} new')
            if store and history:
                progress['chunks'][key] = {'rows': len(frame), 'added': added, 'partitions': parts, 'done_at': run_date}
                progress['updated'] = datetime.now(timezone.utc).isoformat()
                store.put_json(progress_key(stream), progress)
        if store is None:
            continue
        arch = store.whole(stream)
        stats['archive_rows'] = 0 if arch is None else len(arch)
        if arch is None or arch.empty:
            continue
        nse_body = store.cw.get(store.r2, NSE_TABLE[stream])
        nse = pd.read_parquet(io.BytesIO(nse_body)) if nse_body else None
        if nse is None:
            report['notes'].append(f'{stream}: no NSE table to link against; every BSE row counts as BSE-only')
        clean, counts = bse_events.clean(arch, master or _master(store, run_date, report['notes']), nse, stream)
        stats['clean'] = counts
        store.cw.put_parquet(store.r2, f'clean/current/bse_{stream}.parquet', clean)
    report['bse_calls'] = bse.calls
    report['via'] = bse.via
    if store is not None:
        store.put_json(f'clean/reports/bse_events/{run_date}.json', report)
    return report


def _master(store: Store, run_date: str, notes: list):
    from collectors.nse_events.run_daily import security_master
    return security_master(store.r2, run_date, notes)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--days', type=int, default=NIGHTLY_DAYS, help='nightly window (ignored with --from)')
    ap.add_argument('--from', dest='start', type=date.fromisoformat, help='history from (month by month)')
    ap.add_argument('--to', dest='end', type=date.fromisoformat, help='history to (default today)')
    ap.add_argument('--dataset', choices=('all',) + STREAMS, default='all')
    ap.add_argument('--redo', action='store_true', help='refetch months already marked done')
    ap.add_argument('--dry-run', action='store_true', help='fetch and count; write nothing')
    args = ap.parse_args(argv)
    today = datetime.now(IST).date()
    streams = STREAMS if args.dataset == 'all' else (args.dataset,)
    store, raw = None, None
    if not args.dry_run:
        from r2_writer import r2_client

        from insiders_clean.raw_store import RawStore
        r2 = r2_client()
        store, raw = Store(r2), RawStore(r2, collector='bse_events')
    bse = BSEClient(raw=raw)
    try:
        report = run(store, bse, today, streams, args.start, args.end, args.days, args.redo)
    finally:
        bse.close()
    for name, s in report['streams'].items():
        print(f'  {name}: {json.dumps(s, default=str)[:1500]}')
    for n in report['notes']:
        print(f'  note: {n}')
    print(f'  BSE calls: {report["bse_calls"]} ({report["via"]})')
    return 2 if any(s.get('stopped_at') for s in report['streams'].values()) else 0


if __name__ == '__main__':
    sys.exit(main())
