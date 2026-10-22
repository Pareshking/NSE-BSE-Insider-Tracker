"""BSE SAST (Reg 29), corporate actions, board meetings and shareholding
patterns -> archive/ and clean/.

    python -m collectors.bse.events                          # nightly: last 30 days
    python -m collectors.bse.events --from 2025-10-08 --to 2026-10-12 --dataset sast   # history, resumable
    python -m collectors.bse.events --days 30 --dry-run      # fetch and count, write nothing
    python -m collectors.bse.events --from 2025-07-01 --dataset meetings          # results dates back to Jul 2025
    python -m collectors.bse.events --from 2025-10-08 --dataset shareholding --max-xbrl 900   # catch-up

Each answer is stored in raw_v2/bse/{sast|corporate_actions|board_meetings|
shareholding_filings|shareholding_xbrl}/ first. Rows are
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

Board meetings are announced ahead, so their window runs AHEAD_DAYS past the
end (as NSE's collector does): nightly [today - days, today + 60]. A meeting
moved to a new date comes back once at the new date and once, flagged, at the
old one; the clean step drops the old date. One board-meetings call can leave
rows out (meetings_window), so each window is read whole and in 15-day
pieces, the rows united; the report counts rows only one reading had.

Shareholding (the companies NSE's list does not carry; NSE's filing wins for a
company on both): a company whose ISIN is in NSE's
clean/current/shareholding.parquet is left out and counted. An NSE-listed
company that NSE's list leaves out (Abbott India, MCX: audit 22 Oct) is read
here; without NSE's table, a company with an NSE symbol is left out. BSE's filings list is asked for a period back from
today (client.py), 15 days nightly and a year in history mode. The holdings
are only in each filing's inline XBRL, read once per filing with NSE's parsers
into NSE's columns (promoter and public %, promoter pledge, ownership by
investor type, the promoter-group members), newest quarter first, at most
--max-xbrl a run; the rest stay `pending` and are retried on later runs, so
repeated history runs catch up. The newest submission of a company's quarter
is read and older ones are marked `superseded`. Members go to a write-once
batch under archive/bse_events/promoter_group/ and
clean/current/bse_promoter_group.parquet is rebuilt from all batches (the
clean step links insider filings through it, as through NSE's list).

--dataset takes one stream, a comma list (`meetings,shareholding`) or `all`.
"""
from __future__ import annotations

import argparse
import hashlib
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
from collectors.nse_events import parsers as nse_parsers
from insiders_clean import archive, bse_events, promoter_group

STREAMS = ('sast', 'actions', 'meetings', 'shareholding')
DATE_COLUMN = {'sast': 'trade_date_to', 'actions': 'ex_date', 'meetings': 'meeting_date', 'shareholding': 'quarter_end'}
NSE_TABLE = {'sast': 'clean/current/sast.parquet', 'actions': 'clean/current/actions.parquet',
             'meetings': 'clean/current/meetings.parquet'}
IST = timezone(timedelta(hours=5, minutes=30))
NIGHTLY_DAYS = 30  # SAST disclosures arrive days or weeks after the trade
TILE_DAYS, TILE_SHIFT = 7, 3
AHEAD_DAYS = 60    # board meetings, as NSE's collector
MEETING_PIECE_DAYS = 15   # board meetings are read whole and in pieces of this size (meetings_window)
SHP_FLAG_NIGHTLY, SHP_FLAG_HISTORY = 3, 6   # BSE's periods: 15 days, one year
MAX_XBRL_PER_RUN = 150                      # ~5 s each: about 13 minutes
GROUP_BATCHES = 'archive/bse_events/promoter_group/'
NSE_SHAREHOLDING = 'clean/current/shareholding.parquet'
# Columns read from a filing's XBRL, as NSE's collector reads them (collectors/nse_events/run_daily.py): pledges and
# totals, the member list's summary, the holding %s, and ownership by investor type (run_daily.CATEGORY_COLS).
SHP_BASE = ('xbrl_status', 'xbrl_error', 'promoter_shares', 'total_shares', 'promoter_pledged_shares',
            'promoter_encumbered_shares', 'promoter_pledge_pct', 'promoter_encumbered_pct', 'no_promoter_group',
            'promoter_holding_pct', 'public_holding_pct', 'employee_trust_pct', 'members_status', 'promoter_members',
            'members_check')
SHP_NUMBERS = ('promoter_shares', 'total_shares', 'promoter_pledged_shares', 'promoter_encumbered_shares',
               'promoter_pledge_pct', 'promoter_encumbered_pct', 'promoter_holding_pct', 'public_holding_pct',
               'employee_trust_pct', 'promoter_members')


def _category_cols():
    """NSE's investor-type columns and their parser (imported late: run_daily reads scripts/)."""
    from collectors.nse_events.run_daily import CATEGORY_COLS, CATEGORY_VALUES, _set_categories
    return CATEGORY_COLS, CATEGORY_VALUES, _set_categories


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


def meetings_window(bse: BSEClient, a: date, b: date, stats: dict) -> dict:
    """Every board meeting BSE gives for [a, b]: the whole window and its
    MEETING_PIECE_DAYS pieces, rows united (a row is the same row when every
    field is). One call can leave rows out: on 22 Oct 2026 October 2026 asked
    as one month answered 892 meetings twice, its two halves 309 + 607 = 916,
    and 22 Sep - 21 Dec in one call held the same 916 October meetings; the 24
    missing were recent listings (scrip codes 5449xx). The report counts rows
    that only one of the two readings had."""
    readings = [[(a, b)]]
    if (b - a).days >= MEETING_PIECE_DAYS:
        readings.append(pieces(a, b, MEETING_PIECE_DAYS))
    seen: list[dict] = [{}, {}]
    for n, tiling in enumerate(readings):
        for x, y in tiling:
            got = bse.board_meetings(x, y)
            stats['calls'] = stats.get('calls', 0) + 1
            for table in ('Table', 'Table1'):
                for r in got[table]:
                    seen[n][(table, json.dumps(r, sort_keys=True, default=str))] = r
    if len(readings) > 1:
        whole, parts = set(seen[0]), set(seen[1])
        stats['rows_only_in_whole_window'] = stats.get('rows_only_in_whole_window', 0) + len(whole - parts)
        stats['rows_only_in_pieces'] = stats.get('rows_only_in_pieces', 0) + len(parts - whole)
    rows = {**seen[0], **seen[1]}
    return {t: [r for (table, _), r in rows.items() if table == t] for t in ('Table', 'Table1')}


def fetch(bse: BSEClient, stream: str, a: date, b: date, stats: dict) -> pd.DataFrame:
    if stream == 'sast':
        frame, extra = parsers.parse_sast(sast_window(bse, a, b, stats))
        for reg, n in extra['dropped_other_regulations'].items():
            d = stats.setdefault('dropped_other_regulations', {})
            d[reg] = d.get(reg, 0) + n
    elif stream == 'meetings':
        frame, counts = parsers.parse_board_meetings(meetings_window(bse, a, b, stats))
        for k, n in counts.items():
            stats[k] = stats.get(k, 0) + n
    else:
        frame, dropped = parsers.parse_actions(bse.actions(a, b))
        stats['calls'] = stats.get('calls', 0) + 1
        stats['dropped_other_purposes'] = stats.get('dropped_other_purposes', 0) + dropped
    stats['fetched'] = stats.get('fetched', 0) + len(frame)
    return frame


def _holding_pcts(rows: pd.DataFrame, i, got: dict) -> None:
    """Promoter, public and employee-trust % as NSE's listing gives them: of
    SEBI's base (total less shares under depository receipts,
    `pct_base_shares`), to 4 decimals. BSE's list has no holdings, so they
    come from the XBRL; when the investor types could not be read the base is
    the total."""
    base = pd.to_numeric(pd.Series([rows.at[i, 'pct_base_shares']]), errors='coerce').iloc[0]
    if pd.isna(base) or base <= 0:
        base = got['total_shares']
    rows.at[i, 'promoter_holding_pct'] = round(got['promoter_shares'] / base * 100, 4)
    public = got.get('public_shares')
    rows.at[i, 'public_holding_pct'] = None if public is None else round(public / base * 100, 4)
    trust = pd.to_numeric(pd.Series([rows.at[i, 'non_public_other_pct']]), errors='coerce').iloc[0]
    rows.at[i, 'employee_trust_pct'] = None if pd.isna(trust) else float(trust)


def _read(prev: pd.DataFrame | None, eid) -> bool:
    """Parsed before, investor types included (ok or failed): carried over, not read again."""
    if prev is None or eid not in prev.index or str(prev.at[eid, 'xbrl_status']) != 'ok':
        return False
    if 'categories_status' not in prev.columns:
        return False
    c = prev.at[eid, 'categories_status']
    return isinstance(c, str) and (c == 'ok' or c.startswith('failed'))


def shareholding_xbrl(bse: BSEClient, rows: pd.DataFrame, known: pd.DataFrame | None, stats: dict,
                      max_xbrl: int, members: list, run_date: str,
                      nse_isins: frozenset = frozenset()) -> tuple[pd.DataFrame, bool]:
    """(rows with their XBRL facts, refused). Facts already parsed are carried
    over; archive rows still `pending` are retried even when tonight's list no
    longer holds them (unless NSE's shareholding table has the company by
    then: status `on_nse`, not read). Only the newest submission of a
    company's quarter is read (others `superseded`), newest quarter first, at
    most max_xbrl. A filing parsed without the investor types is read again."""
    category_cols, category_values, set_categories = _category_cols()
    facts_cols = SHP_BASE + category_cols
    rows = rows.copy()
    prev = known.set_index('event_id') if known is not None and not known.empty else None
    if prev is not None and 'xbrl_status' in known:
        retry = known[known['xbrl_status'].astype('string').eq('pending').fillna(False)
                      & ~known['event_id'].isin(rows['event_id'])]
        rows = pd.concat([rows, retry[[c for c in retry.columns if c in rows.columns or c in facts_cols]]],
                         ignore_index=True)
    for c in facts_cols:
        rows[c] = rows[c].astype(object) if c in rows else None
    ids = ['event_id', 'bse_code', 'quarter_end', 'submission_date']
    every = pd.concat([rows[ids]] + ([known[ids]] if prev is not None else []), ignore_index=True)
    every['submission_date'] = pd.to_datetime(every['submission_date'], errors='coerce')
    newest = set(every.sort_values('submission_date', kind='stable')
                      .drop_duplicates(['bse_code', 'quarter_end'], keep='last')['event_id'])
    fetched, blocked = 0, False
    order = rows.assign(_q=pd.to_datetime(rows['quarter_end'], errors='coerce'),
                        _s=pd.to_datetime(rows['submission_date'], errors='coerce'))

    def mark(i, status):
        for c in ('xbrl_status', 'members_status', 'categories_status'):
            rows.at[i, c] = status

    for i, r in order.sort_values(['_q', '_s'], ascending=False, kind='stable').iterrows():
        eid = r['event_id']
        if _read(prev, eid):
            for c in facts_cols:
                if c in prev.columns:
                    rows.at[i, c] = prev.at[eid, c]
            continue
        if isinstance(r.get('isin'), str) and r['isin'] in nse_isins:
            rows.at[i, 'xbrl_status'] = 'on_nse'
            continue
        if not isinstance(r['xbrl_url'], str) or not r['xbrl_url']:
            mark(i, 'no_xbrl')
            continue
        if eid not in newest:
            rows.at[i, 'xbrl_status'] = 'superseded'
            continue
        if blocked or fetched >= max_xbrl:
            mark(i, 'pending')
            continue
        fetched += 1
        try:
            body = bse.shareholding_xbrl(r['xbrl_url'], {'bse_code': r['bse_code'], 'quarter_end': str(r['quarter_end'])[:10]})
        except Blocked as exc:
            mark(i, 'pending')
            blocked = True
            stats['stopped_at'] = {'chunk': f'xbrl {r["bse_code"]}', 'reason': str(exc)}
            continue
        except Failed as exc:   # one bad file must not stop the rest (a 404 is Missing)
            mark(i, f'failed: {type(exc).__name__}')
            rows.at[i, 'xbrl_error'] = str(exc)[:120]
            continue
        facts = parsers.ixbrl_facts(body.decode('utf-8', errors='replace'))
        set_categories(rows, i, facts)
        try:
            got = nse_parsers.parse_shp_xbrl(facts)
            for k in SHP_BASE:
                if k in got:
                    rows.at[i, k] = got[k]
            _holding_pcts(rows, i, got)
            rows.at[i, 'xbrl_status'], rows.at[i, 'xbrl_error'] = 'ok', None
        except ValueError as exc:
            rows.at[i, 'xbrl_status'], rows.at[i, 'xbrl_error'] = 'failed: ValueError', str(exc)[:120]
        found, check = nse_parsers.parse_shp_members(facts)
        rows.at[i, 'members_status'], rows.at[i, 'promoter_members'] = 'ok', check['members']
        rows.at[i, 'members_check'] = check['check']
        members.append(promoter_group.member_rows(found, rows.loc[i].to_dict(), check['check'],
                                                  hashlib.sha256(body).hexdigest(), run_date))
    for c in SHP_NUMBERS + category_values:
        rows[c] = pd.to_numeric(rows[c], errors='coerce')
    for c in category_cols[:3]:
        rows[c] = rows[c].astype('string')
    rows['no_promoter_group'] = rows['no_promoter_group'].astype('boolean')
    status = rows['xbrl_status'].astype(str).str.split(':').str[0]
    cstatus = rows['categories_status'].astype('string').fillna('not read').str.split(':').str[0]
    stats.update(xbrl_fetched=fetched, xbrl_status={k: int(v) for k, v in status.value_counts().items()},
                 categories_status={k: int(v) for k, v in cstatus.value_counts().items()})
    return rows, blocked


def shareholding(store, bse: BSEClient, master, flag: int, max_xbrl: int, stats: dict, run_date: str,
                 members: list, nse_isins: frozenset = frozenset()) -> tuple[pd.DataFrame, bool]:
    """BSE's filings list for the period `flag`, BSE-only companies kept (with
    a master; a dry run keeps all), their XBRL read. (rows, refused). A
    company is left to NSE's collector when its ISIN is in NSE's shareholding
    table (`isin_in_nse_table_skipped`, or `dual_listed_skipped` when it has an
    NSE symbol). An NSE-listed company NSE's list does not carry is read here
    (`dual_listed_kept`): NSE's corporate-share-holdings-master gives no row for
    574 companies of the universe, Abbott India and MCX among them (audit
    22 Oct: symbol=ABBOTINDIA answers 0 rows). Without NSE's table, an NSE
    symbol alone leaves a company to NSE, as before."""
    listing = parsers.parse_shareholding_listing(bse.shareholding_filings(flag))
    stats.update(calls=stats.get('calls', 0) + 1, listed=len(listing))
    if master is not None and not listing.empty:
        listing = bse_events.add_identity(listing, master)
        nse = listing['nse_symbol'].notna()
        in_table = listing['isin'].isin(nse_isins)
        skip = in_table if nse_isins else nse
        stats['dual_listed_skipped'] = int((nse & skip).sum())
        stats['isin_in_nse_table_skipped'] = int((~nse & skip).sum())
        stats['dual_listed_kept'] = int((nse & ~skip).sum())
        listing = listing[~skip]
    stats['fetched'] = len(listing)
    known = store.whole('shareholding') if store is not None else None
    return shareholding_xbrl(bse, listing, known, stats, max_xbrl, members, run_date, nse_isins)


def write_promoter_group(store, batch: list, master, now: datetime) -> dict:
    """Members parsed tonight -> a new write-once batch file, then
    clean/current/bse_promoter_group.parquet rebuilt from every batch."""
    entry = {'filings_parsed': len(batch), 'members_parsed': int(sum(len(b) for b in batch))}
    rows = [b for b in batch if b is not None and not b.empty]
    if rows:
        key = f'{GROUP_BATCHES}batch={now:%Y-%m-%dT%H%M%S}.parquet'
        if store.cw.get(store.r2, key) is None:
            store.cw.put_parquet(store.r2, key, pd.concat(rows, ignore_index=True))
            entry['batch_written'] = key
    keys = sorted(k for k in store.cw.list_keys(store.r2, GROUP_BATCHES) if k.endswith('.parquet'))
    if not keys:
        return entry
    table, counts = promoter_group.clean_members([store.cw.read_parquet(store.r2, k) for k in keys])
    entry.update(batches=len(keys), **counts)
    if not table.empty:
        table = bse_events.add_identity(table.assign(bse_code=table['symbol'].astype(str)), master)
        store.cw.put_parquet(store.r2, 'clean/current/bse_promoter_group.parquet', table)
    return entry


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
        end: date | None = None, days: int = NIGHTLY_DAYS, redo: bool = False, master=None, log=print,
        max_xbrl: int = MAX_XBRL_PER_RUN, now: datetime | None = None) -> dict:
    """History when `start` is given (month by month, resumable), else the
    nightly window. `store` None = dry run (fetch and count only)."""
    run_date = today.isoformat()
    history = start is not None
    a, b = (start, end or today) if history else (today - timedelta(days=days), today)
    report = {'run_date': run_date, 'mode': 'history' if history else 'nightly', 'window': [a.isoformat(), b.isoformat()],
              'streams': {}, 'notes': [], 'dry_run': store is None}
    blocked = False
    masters = [master]

    def get_master():
        if masters[0] is None and store is not None:
            masters[0] = _master(store, run_date, report['notes'])
        return masters[0]

    for stream in streams:
        stats = report['streams'].setdefault(stream, {'chunks_done': 0, 'chunks_skipped_done': 0, 'added': 0, 'errors': []})
        if stream == 'shareholding':
            blocked = run_shareholding(store, bse, get_master, history, max_xbrl, stats, report, run_date, now, blocked)
            continue
        progress = (store.json(progress_key(stream)) if store and history else None) or {'stream': stream, 'chunks': {}}
        done = {} if redo or not history else progress['chunks']
        last = b + timedelta(days=AHEAD_DAYS) if stream == 'meetings' and end is None else b
        for x, y in (months(a, last) if history else [(a, last)]):
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
        clean, counts = bse_events.clean(arch, get_master(), nse, stream)
        stats['clean'] = counts
        store.cw.put_parquet(store.r2, f'clean/current/bse_{stream}.parquet', clean)
    report['bse_calls'] = bse.calls
    report['via'] = bse.via
    if store is not None:
        store.put_json(f'clean/reports/bse_events/{run_date}.json', report)
    return report


def run_shareholding(store, bse, get_master, history: bool, max_xbrl: int, stats: dict, report: dict,
                     run_date: str, now: datetime | None, blocked: bool) -> bool:
    """The shareholding stream (see the module notes). Returns whether BSE
    has refused this run."""
    members: list = []
    nse_body = store.cw.get(store.r2, NSE_SHAREHOLDING) if store is not None else None
    nse = pd.read_parquet(io.BytesIO(nse_body)) if nse_body else None
    if store is not None and nse is None:
        report['notes'].append('shareholding: no NSE shareholding table; companies told apart by NSE symbol only')
    nse_isins = frozenset() if nse is None else frozenset(nse['isin'].dropna().astype(str))
    if not blocked:
        try:
            rows, blocked = shareholding(store, bse, get_master(), SHP_FLAG_HISTORY if history else SHP_FLAG_NIGHTLY,
                                         max_xbrl, stats, run_date, members, nse_isins)
        except Blocked as exc:
            blocked, rows = True, None
            stats['stopped_at'] = {'chunk': 'filings list', 'reason': str(exc)}
        except Failed as exc:
            rows = None
            stats['errors'].append({'chunk': 'filings list', 'error': str(exc)})
        if blocked:
            report['notes'].append(f'shareholding: BSE refused ({stats["stopped_at"]["reason"]}); '
                                   'no further BSE calls this run, unread filings stay pending')
        if store is not None and rows is not None:
            stats['added'] = store.merge('shareholding', rows, run_date)[0]
            stats['chunks_done'] = 1
    if store is None:
        return blocked
    arch = store.whole('shareholding')
    stats['archive_rows'] = 0 if arch is None else len(arch)
    if arch is not None and not arch.empty:
        from collectors.nse_events.run_daily import clean_shareholding, shareholding_coverage
        clean, counts = bse_events.clean(clean_shareholding(arch), get_master(), nse, 'shareholding')
        stats['clean'] = counts
        if not clean.empty:
            stats['coverage'] = shareholding_coverage(clean)
        store.cw.put_parquet(store.r2, 'clean/current/bse_shareholding.parquet', clean)
    try:  # a failure here must never cost the shareholding table written above
        report['promoter_group'] = write_promoter_group(store, members, get_master(), now or datetime.now(timezone.utc))
    except Exception as exc:  # noqa: BLE001
        report['notes'].append(f'promoter_group: failed ({type(exc).__name__}: {exc})')
    return blocked


def _master(store: Store, run_date: str, notes: list):
    from collectors.nse_events.run_daily import security_master
    return security_master(store.r2, run_date, notes)


def datasets(text: str) -> tuple:
    """'all', or a comma list of STREAMS -> those streams, in STREAMS order."""
    names = {n.strip() for n in text.split(',') if n.strip()}
    if names == {'all'}:
        return STREAMS
    unknown = sorted(names - set(STREAMS))
    if unknown or not names:
        raise argparse.ArgumentTypeError(f'unknown dataset {unknown or text}; use all or ' + ', '.join(STREAMS))
    return tuple(s for s in STREAMS if s in names)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--days', type=int, default=NIGHTLY_DAYS, help='nightly window (ignored with --from)')
    ap.add_argument('--from', dest='start', type=date.fromisoformat, help='history from (month by month)')
    ap.add_argument('--to', dest='end', type=date.fromisoformat, help='history to (default today)')
    ap.add_argument('--dataset', type=datasets, default=STREAMS,
                    help='all, or one or more of ' + ', '.join(STREAMS) + ' separated by commas')
    ap.add_argument('--redo', action='store_true', help='refetch months already marked done')
    ap.add_argument('--dry-run', action='store_true', help='fetch and count; write nothing')
    ap.add_argument('--max-xbrl', type=int, default=MAX_XBRL_PER_RUN, help='shareholding XBRL files to read this run')
    args = ap.parse_args(argv)
    today = datetime.now(IST).date()
    streams = args.dataset
    store, raw = None, None
    if not args.dry_run:
        from r2_writer import r2_client

        from insiders_clean.raw_store import RawStore
        r2 = r2_client()
        store, raw = Store(r2), RawStore(r2, collector='bse_events')
    bse = BSEClient(raw=raw)
    try:
        report = run(store, bse, today, streams, args.start, args.end, args.days, args.redo, max_xbrl=args.max_xbrl)
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
