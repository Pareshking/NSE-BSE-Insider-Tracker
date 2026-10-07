"""Nightly: NSE corporate events for the last 10 days -> archive/ and clean/.

    python -m collectors.nse_events.run_daily [--days 10] [--dataset all|sast|actions|meetings|shareholding]

For each stream it fetches [today - days, today], so filings NSE adds late
are still picked up, and merges into
archive/nse_events/{stream}/year=YYYY.parquet by event_id (re-fetching an
event never adds it twice). The year is the event's own date. Then it
rebuilds clean/current/{stream}.parquet from the whole archive and writes
clean/reports/nse_events/{date}.json.

Shareholding: the listing gives promoter and public % straight away; the
promoter pledge comes from each filing's XBRL, fetched once per filing (at
most MAX_XBRL_PER_RUN a night; the rest wait for the next night). If a
quarter's XBRL can't be parsed, the company's previous quarter's pledge
figures are carried forward with shareholding_stale = true.

A 401/403/429 from NSE stops all further NSE calls for the night; what was
already fetched is still stored.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

from clean_writer import get, list_keys, nse_lists, put, put_parquet, read_parquet
from r2_writer import BUCKET, SECURITY_MASTER_PATH, r2_client

from collectors.nse_events import parsers
from collectors.nse_events.client import Blocked, NSEClient
from insiders_clean import archive
from insiders_clean.securities import SecurityMaster, bse_list_frame, nse_list_frame

STREAMS = ('sast', 'actions', 'meetings', 'shareholding')
DATE_COLUMN = {'sast': 'trade_date_to', 'actions': 'ex_date', 'meetings': 'meeting_date',
               'shareholding': 'quarter_end'}
MAX_XBRL_PER_RUN = 300
IST = timezone(timedelta(hours=5, minutes=30))


def prefix(stream):
    return f'archive/nse_events/{stream}/'


def year_of(series: pd.Series) -> pd.Series:
    d = pd.to_datetime(series, errors='coerce')
    return d.dt.year.map(lambda y: f'year={int(y)}' if pd.notna(y) else 'year=unknown')


def merge_into_archive(r2, stream, new: pd.DataFrame, run_date: str) -> tuple[pd.DataFrame | None, int, list]:
    """Merge into year partitions; return (whole archive, added, partitions written)."""
    written, added = [], 0
    if new is not None and not new.empty:
        for part, rows in new.groupby(year_of(new[DATE_COLUMN[stream]])):
            key = f'{prefix(stream)}{part}.parquet'
            merged, n = archive.merge(read_parquet(r2, key), rows, run_date, key='event_id')
            put_parquet(r2, key, merged)
            written.append(part)
            added += n
    keys = sorted(k for k in list_keys(r2, prefix(stream)) if k.endswith('.parquet'))
    frames = [f for f in (read_parquet(r2, k) for k in keys) if f is not None and not f.empty]
    return (pd.concat(frames, ignore_index=True) if frames else None), added, written


def security_master(r2, run_date: str, notes: list) -> SecurityMaster:
    vr_path = ROOT / SECURITY_MASTER_PATH
    vr = pd.read_csv(vr_path, dtype=str, keep_default_na=False) if vr_path.exists() else None
    mcap_rows = []
    day = date.fromisoformat(run_date)
    for back in range(11):
        body = get(r2, f'reference/market_cap/{(day - timedelta(days=back)).isoformat()}/data.json')
        if body:
            mcap_rows = json.loads(body)
            break
    return SecurityMaster(vr_master=vr, nse_list=nse_list_frame(*nse_lists(r2, run_date, notes)),
                          bse_list=bse_list_frame(mcap_rows), market_cap_rows=mcap_rows)


def add_identity(df: pd.DataFrame, master: SecurityMaster) -> pd.DataFrame:
    """ISIN and display name from the security master; the row's own ISIN
    (corporate actions, shareholding) wins when present."""
    df = df.copy()
    own = df['isin'] if 'isin' in df.columns else pd.Series([None] * len(df), index=df.index)
    resolved = [master.resolve('nse', s)[0] for s in df['symbol']]
    df['isin'] = [o if isinstance(o, str) and o.strip() else r for o, r in zip(own, resolved)]
    recs = {i: master.record(i) for i in pd.Series(df['isin']).dropna().unique()}
    df['company_display'] = [(recs.get(i) or {}).get('display_name') or c for i, c in zip(df['isin'], df['company'])]
    df['unmatched_security'] = df['isin'].isna()
    return df


def clean_shareholding(arch: pd.DataFrame) -> pd.DataFrame:
    """One row per company and quarter (a revised filing replaces the
    original), with the previous quarter's pledge carried forward when this
    quarter's XBRL couldn't be parsed."""
    df = arch.copy()
    df['submission_date'] = pd.to_datetime(df['submission_date'], errors='coerce')
    df['quarter_end'] = pd.to_datetime(df['quarter_end'], errors='coerce')
    df = (df.sort_values(['symbol', 'quarter_end', 'submission_date'])
            .drop_duplicates(['symbol', 'quarter_end'], keep='last'))
    df['shareholding_stale'] = False
    cols = ['promoter_pledge_pct', 'promoter_encumbered_pct']
    for c in cols:
        if c not in df.columns:
            df[c] = None
        df[c] = pd.to_numeric(df[c], errors='coerce')
    failed = df['xbrl_status'].astype(str).ne('ok') if 'xbrl_status' in df.columns else pd.Series(True, index=df.index)
    for c in cols:
        carried = df.groupby('symbol')[c].ffill()
        df.loc[failed, c] = carried[failed]
    df.loc[failed & df['promoter_pledge_pct'].notna(), 'shareholding_stale'] = True
    return df


def fetch_xbrl(nse: NSEClient, listing: pd.DataFrame, known: pd.DataFrame | None, report: dict) -> pd.DataFrame:
    """Add pledge figures to listing rows whose XBRL hasn't been parsed yet."""
    done = set()
    if known is not None and 'xbrl_status' in known.columns:
        done = set(known.loc[known['xbrl_status'].astype(str).eq('ok'), 'event_id'])
        prev = known.set_index('event_id')
    listing = listing.copy()
    for c in ('xbrl_status', 'promoter_shares', 'total_shares', 'promoter_pledged_shares',
              'promoter_encumbered_shares', 'promoter_pledge_pct', 'promoter_encumbered_pct'):
        listing[c] = None
    fetched, blocked = 0, False
    for i, row in listing.iterrows():
        if row['event_id'] in done:
            for c in ('xbrl_status', 'promoter_shares', 'total_shares', 'promoter_pledged_shares',
                      'promoter_encumbered_shares', 'promoter_pledge_pct', 'promoter_encumbered_pct'):
                if c in prev.columns:
                    listing.at[i, c] = prev.at[row['event_id'], c]
            continue
        if blocked or fetched >= MAX_XBRL_PER_RUN or not row.get('xbrl_url'):
            listing.at[i, 'xbrl_status'] = 'pending' if row.get('xbrl_url') else 'no_xbrl'
            continue
        fetched += 1
        try:
            facts = parsers.parse_shp_xbrl(nse.xbrl(row['xbrl_url']))
            for k, v in facts.items():
                if k in listing.columns:
                    listing.at[i, k] = v
            listing.at[i, 'xbrl_status'] = 'ok'
        except Blocked:
            # Keep what was parsed tonight; the rest wait for the next run.
            listing.at[i, 'xbrl_status'] = 'pending'
            blocked = True
            report['xbrl_blocked'] = True
            report['notes'].append('NSE refused an XBRL download; remaining XBRLs wait for the next run')
        except Exception as exc:  # noqa: BLE001 -- one bad file must not stop the rest
            listing.at[i, 'xbrl_status'] = f'failed: {type(exc).__name__}'
    report['xbrl_fetched'] = fetched
    return listing


def run(r2, nse: NSEClient, today: date, days: int, streams=STREAMS) -> dict:
    run_date = today.isoformat()
    start = today - timedelta(days=days)
    report = {'run_date': run_date, 'window': [start.isoformat(), run_date], 'streams': {}, 'notes': []}
    master = security_master(r2, run_date, report['notes'])
    blocked = False
    for stream in streams:
        entry = report['streams'].setdefault(stream, {})
        new = None
        if not blocked:
            try:
                if stream == 'sast':
                    new = parsers.parse_sast(nse.sast_reg29(start, today))
                elif stream == 'actions':
                    new, entry['dropped_other_purposes'] = parsers.parse_corporate_actions(
                        nse.corporate_actions(start, today))
                elif stream == 'meetings':
                    # Meetings are announced ahead: look forward too.
                    new, entry['dropped_routine'] = parsers.parse_board_meetings(
                        nse.board_meetings(start, today + timedelta(days=60)))
                else:
                    listing = parsers.parse_shareholding_listing(nse.shareholding_filings(start, today))
                    known = merge_into_archive(r2, stream, None, run_date)[0]
                    new = fetch_xbrl(nse, listing, known, report)
                    blocked = bool(report.get('xbrl_blocked'))
            except Blocked as exc:
                blocked = True
                report['notes'].append(f'{stream}: NSE refused ({exc}); no further NSE calls tonight')
            except Exception as exc:  # noqa: BLE001 -- one stream failing must not stop the others
                report['notes'].append(f'{stream}: fetch failed ({type(exc).__name__}: {exc})')
        entry['fetched'] = 0 if new is None else len(new)
        arch, added, parts = merge_into_archive(r2, stream, new, run_date)
        entry.update(added=added, partitions_written=parts, archive_rows=0 if arch is None else len(arch))
        if arch is None or arch.empty:
            continue
        clean = add_identity(arch, master)
        if stream == 'shareholding':
            clean = clean_shareholding(clean)
        entry['unmatched_securities'] = int(clean['unmatched_security'].sum())
        entry['clean_rows'] = len(clean)
        put_parquet(r2, f'clean/current/{stream}.parquet', clean)
    report['nse_calls'] = nse.calls
    put(r2, f'clean/reports/nse_events/{run_date}.json', json.dumps(report, indent=2, default=str).encode(),
        'application/json')
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--days', type=int, default=10)
    ap.add_argument('--dataset', choices=('all',) + STREAMS, default='all')
    args = ap.parse_args(argv)
    today = datetime.now(IST).date()
    streams = STREAMS if args.dataset == 'all' else (args.dataset,)
    report = run(r2_client(), NSEClient(), today, args.days, streams)
    for name, s in report['streams'].items():
        print(f'  {name}: {s}')
    for n in report['notes']:
        print(f'  note: {n}')
    print(f'  NSE calls: {report["nse_calls"]}; bucket {"set" if BUCKET else "MISSING"}')


if __name__ == '__main__':
    main()
