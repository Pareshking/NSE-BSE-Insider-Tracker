"""Nightly: NSE corporate events for the last 10 days -> archive/ and clean/.

    python -m collectors.nse_events.run_daily [--days 10] [--dataset all|sast|actions|meetings|shareholding|tenders|daily_buybacks|issues]
    python -m collectors.nse_events.run_daily --dataset meetings --from 2025-07-01   # one-off backfill

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
figures are carried forward with shareholding_stale = true. A company with
no promoter group files no promoter context: promoter 0% as filed
(no_promoter_group), not a failure.

The same download gives the promoter-group member list (TODO item 21): each
filing's members go to a write-once batch under
archive/nse_events/promoter_group/, and clean/current/promoter_group.parquet
is rebuilt from all batches. A filing parsed before member lists existed is
fetched again when it is its company's latest; run with --days 120 and the
workflow's chain=1 to cover every company's latest quarter. The XBRL itself
is kept gzip-compressed in raw_v2/nse/shareholding_xbrl/ (write-once).

Buybacks (TODO 12): NSE's tender-offer list (every buyback tender with its
offer price) and the daily buyback reports of open-market buybacks are
collected as streams `tenders` and `daily_buybacks`; with the corporate
actions they make clean/current/buybacks.parquet (insiders_clean/buybacks.py).

Board meetings backfill (TODO 25): `--from DATE` with dataset meetings fetches
past meetings one calendar month per call from DATE, so the results dates of
the whole product year are in (NSE answers past ranges; Feb 2026 held 3,472
rows, the same as its two halves together). Meetings, tenders and daily
buyback reports are stored byte for byte in raw_v2/nse/{stream}/ first
(insiders_clean/raw_store.py) when the run is given a raw store.

Further issues (stream `issues`: preferential, rights and QIP, both stages;
`insiders_clean/issues.py`): every filing NSE posted in the window, one archive
row per filing with NSE's row, and the XBRL of the filings in
issues.XBRL_WANTED parsed once (at most MAX_ISSUE_XBRL_PER_RUN a night, newest
first; pending ones are retried on later nights). List responses and XBRL
files are also stored byte for byte in raw_v2/nse/further_issues/ and
raw_v2/nse/further_issue_xbrl/. The clean tables (preferential, rights, qip
and their allottee and lock-in tables) are written by scripts/clean_writer.py,
which reads this archive. To load history run once with
`--dataset issues --days 550` (an approval up to 180 days older than the first
allotment in the product window still links to it).

A 401/403/429 from NSE stops all further NSE calls for the night; what was
already fetched is still stored.
"""
from __future__ import annotations

import argparse
import threading
from concurrent.futures import ThreadPoolExecutor
import gzip
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
from insiders_clean import archive, buybacks, issues, promoter_group, raw_store, results
from insiders_clean.raw_store import RawStore
from insiders_clean.securities import SecurityMaster, bse_list_frame, nse_list_frame

STREAMS = ('sast', 'actions', 'meetings', 'shareholding', 'tenders', 'daily_buybacks')
DATE_COLUMN = {'sast': 'trade_date_to', 'actions': 'ex_date', 'meetings': 'meeting_date',
               'shareholding': 'quarter_end', 'tenders': 'offer_open', 'daily_buybacks': 'report_date'}
RAW_STREAMS = ('meetings', 'tenders', 'daily_buybacks')  # kept byte for byte in raw_v2/
MAX_XBRL_PER_RUN = 300
IST = timezone(timedelta(hours=5, minutes=30))

ISSUES = 'issues'   # further issues: preferential, rights, QIP
STREAMS = STREAMS + (ISSUES,)
DATE_COLUMN[ISSUES] = 'posted_on'
MAX_ISSUE_XBRL_PER_RUN = 300   # further-issue XBRLs (4-100 KB each) a night
RESULTS = 'results'   # financial results (integrated filing) with their XBRL: insiders_clean/results.py
STREAMS = STREAMS + (RESULTS,)
DATE_COLUMN[RESULTS] = 'broadcast_date'
MAX_RESULTS_XBRL_PER_RUN = 500   # results XBRLs (20-60 KB each) a night; the rest wait for the next night
RESULTS_PAGE = 100


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


def security_master(r2, run_date: str, notes: list, *, max_age_days: int = 10) -> SecurityMaster:
    vr_path = ROOT / SECURITY_MASTER_PATH
    vr = pd.read_csv(vr_path, dtype=str, keep_default_na=False) if vr_path.exists() else None
    mcap_rows, cap_as_of = [], None
    day = date.fromisoformat(run_date)
    if max_age_days < 0:
        raise ValueError('max_age_days must be non-negative')
    for back in range(max_age_days + 1):
        candidate_day = day - timedelta(days=back)
        body = get(r2, f'reference/market_cap/{candidate_day.isoformat()}/data.json')
        if body:
            mcap_rows, cap_as_of = json.loads(body), candidate_day.isoformat()
            break
    master = SecurityMaster(vr_master=vr, nse_list=nse_list_frame(*nse_lists(r2, run_date, notes)),
                            bse_list=bse_list_frame(mcap_rows), market_cap_rows=mcap_rows)
    master.market_cap_as_of = cap_as_of
    return master


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


def shareholding_coverage(clean: pd.DataFrame) -> dict:
    """How far the shareholding table has got: companies, the quarter each
    company's latest filing is for, how many pledge files are still waiting,
    why files failed, and how many latest filings have their promoter-group
    member list. Counts only; nothing here changes the data."""
    if clean is None or clean.empty:
        return {'companies': 0, 'pending_xbrl': 0, 'pending_latest': 0, 'pending_members': 0}
    status = clean['xbrl_status'].astype(str) if 'xbrl_status' in clean.columns else pd.Series('pending', index=clean.index)
    latest = clean.sort_values('quarter_end').groupby('symbol').tail(1)
    lstat = status.loc[latest.index]
    quarters = latest['quarter_end'].dt.strftime('%Y-%m-%d').value_counts().sort_index(ascending=False).head(4)
    col = lambda c: clean[c] if c in clean.columns else pd.Series(None, index=clean.index, dtype=object)  # noqa: E731
    failed = status.str.startswith('failed')
    mstat = col('members_status').astype('string').fillna('not fetched')
    no_group = col('no_promoter_group').astype('boolean').fillna(False)
    return {
        'companies': int(clean['symbol'].nunique()),
        'latest_quarter_of_company': {k: int(v) for k, v in quarters.items()},
        'xbrl_status': {k: int(v) for k, v in status.str.split(':').str[0].value_counts().items()},
        # Why files fail, by exception type (e.g. 'failed: KeyError') and by the parser's reason, so a failure can be
        # read from the run log.
        'xbrl_failure_types': {k: int(v) for k, v in status[failed].value_counts().items()},
        'xbrl_failure_reasons': {str(k): int(v) for k, v in col('xbrl_error')[failed].fillna('(not recorded)').value_counts().items()},
        # Parsed, with promoter shares 0 as filed: the company names no promoter group (ITC, L&T, ICICI Bank).
        'no_promoter_group': int((no_group & status.eq('ok')).sum()),
        'pending_xbrl': int((status == 'pending').sum()),
        'pending_latest': int((lstat == 'pending').sum()),
        'latest_with_pledge': int(latest['promoter_pledge_pct'].notna().sum()),
        # Promoter-group member lists (docs/TODO.md item 21): latest filing of each company.
        'members_status_latest': {str(k): int(v) for k, v in mstat.loc[latest.index].str.split(':').str[0].value_counts().items()},
        'members_check_latest': {str(k): int(v) for k, v in col('members_check').loc[latest.index].dropna().value_counts().items()},
        'pending_members': int(mstat.loc[latest.index].isin(['pending', 'not fetched']).sum()),
    }


XBRL_COLS = ('xbrl_status', 'xbrl_error', 'promoter_shares', 'total_shares', 'promoter_pledged_shares',
             'promoter_encumbered_shares', 'promoter_pledge_pct', 'promoter_encumbered_pct', 'no_promoter_group')
MEMBER_COLS = ('members_status', 'promoter_members', 'members_check')


def _latest_per_company(listing: pd.DataFrame) -> set:
    """event_ids of each company's latest filing in the listing (latest quarter, then latest submission)."""
    if listing.empty or 'symbol' not in listing:
        return set()
    order = listing.sort_values([c for c in ('symbol', 'quarter_end', 'submission_date') if c in listing], kind='stable')
    return set(order.drop_duplicates('symbol', keep='last')['event_id'])


def _keep_raw(raw, body: str, row) -> str | None:
    """Store the XBRL in the write-once raw layer, gzip-compressed (about 30x
    smaller; gzip with no timestamp, so the same file is the same blob).
    Returns the SHA-256 of the bytes NSE sent. Best effort: a storage error
    never stops the parse."""
    data = body.encode('utf-8')
    sha = raw_store.sha256_hex(data)
    if raw is not None:
        try:
            raw.put('nse', 'shareholding_xbrl', gzip.compress(data, 9, mtime=0), url=row['xbrl_url'],
                    params={'record_id': row.get('record_id'), 'symbol': row.get('symbol'), 'stored_as': 'gzip',
                            'sha256_as_sent': sha}, content_type='application/gzip',
                    covers={'quarter_end': str(row.get('quarter_end'))})
        except Exception:  # noqa: BLE001
            pass
    return sha


def fetch_xbrl(nse: NSEClient, listing: pd.DataFrame, known: pd.DataFrame | None, report: dict,
               max_xbrl: int = MAX_XBRL_PER_RUN, members: list | None = None, raw=None,
               run_date: str | None = None) -> pd.DataFrame:
    """Add pledge figures to listing rows whose XBRL hasn't been parsed yet,
    and the promoter-group member list (parsers.parse_shp_members) from the
    same download. A filing parsed before member lists existed is fetched
    again only when it is its company's latest in the listing, so a catch-up
    covers the latest quarter of every company. Parsed members are appended
    to `members` (one frame per filing); one download counts once against
    max_xbrl."""
    done, mdone, prev = set(), set(), None
    if known is not None and 'xbrl_status' in known.columns:
        done = set(known.loc[known['xbrl_status'].astype(str).eq('ok'), 'event_id'])
        if 'members_status' in known.columns:
            mdone = set(known.loc[known['members_status'].astype(str).eq('ok'), 'event_id'])
        prev = known.set_index('event_id')
    latest = _latest_per_company(listing)
    listing = listing.copy()
    for c in XBRL_COLS + MEMBER_COLS:
        listing[c] = None
    fetched, blocked = 0, False
    # Newest quarters first: the latest filing per company is what the pages show.
    for i, row in listing.sort_values('quarter_end', ascending=False, kind='stable').iterrows():
        eid = row['event_id']
        totals_done = eid in done
        if prev is not None and eid in prev.index:
            for c in XBRL_COLS + MEMBER_COLS:
                if c in prev.columns and (totals_done or c in MEMBER_COLS):
                    listing.at[i, c] = prev.at[eid, c]
        need_members = eid not in mdone and (not totals_done or eid in latest)
        if totals_done and not need_members:
            continue
        if blocked or fetched >= max_xbrl or not row.get('xbrl_url'):
            if not totals_done:
                listing.at[i, 'xbrl_status'] = 'pending' if row.get('xbrl_url') else 'no_xbrl'
            listing.at[i, 'members_status'] = 'pending' if row.get('xbrl_url') else 'no_xbrl'
            continue
        fetched += 1
        try:
            body = nse.xbrl(row['xbrl_url'])
        except Blocked:
            # Keep what was parsed tonight; the rest wait for the next run.
            if not totals_done:
                listing.at[i, 'xbrl_status'] = 'pending'
            listing.at[i, 'members_status'] = 'pending'
            blocked = True
            report['xbrl_blocked'] = True
            report['notes'].append('NSE refused an XBRL download; remaining XBRLs wait for the next run')
            continue
        except Exception as exc:  # noqa: BLE001 -- one bad file must not stop the rest
            if not totals_done:
                listing.at[i, 'xbrl_status'] = f'failed: {type(exc).__name__}'
                listing.at[i, 'xbrl_error'] = str(exc)[:120]
            listing.at[i, 'members_status'] = f'failed: {type(exc).__name__}'
            continue
        sha = _keep_raw(raw, body, row)
        if not totals_done:
            try:
                facts = parsers.parse_shp_xbrl(body)
                for k, v in facts.items():
                    if k in listing.columns:
                        listing.at[i, k] = v
                listing.at[i, 'xbrl_status'] = 'ok'
                listing.at[i, 'xbrl_error'] = None
            except Exception as exc:  # noqa: BLE001
                listing.at[i, 'xbrl_status'] = f'failed: {type(exc).__name__}'
                listing.at[i, 'xbrl_error'] = str(exc)[:120]
        try:
            found, check = parsers.parse_shp_members(body)
            listing.at[i, 'members_status'] = 'ok'
            listing.at[i, 'promoter_members'] = check['members']
            listing.at[i, 'members_check'] = check['check']
            if members is not None:
                members.append(promoter_group.member_rows(found, row.to_dict(), check['check'], sha,
                                                          run_date or ''))
        except Exception as exc:  # noqa: BLE001
            listing.at[i, 'members_status'] = f'failed: {type(exc).__name__}'
    report['xbrl_fetched'] = fetched
    return listing


def month_chunks(start: date, end: date) -> list[tuple[date, date]]:
    """Calendar months covering [start, end], clipped to it."""
    out, cur = [], start
    while cur <= end:
        nxt = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
        out.append((cur, min(nxt - timedelta(days=1), end)))
        cur = nxt
    return out


def raw_hook(raw, stream, covers):
    """on_response for the NSE client: the exact bytes into raw_v2/ before
    anything is parsed. A failed raw write fails the stream (rule 5)."""
    def hook(url, resp):
        raw.put('nse', stream, resp.content, url=url, status=resp.status_code,
                content_type=resp.headers.get('Content-Type'), covers=covers)
    return hook


def fetch_meetings(nse, start: date, today: date, raw=None, backfill_from: date | None = None):
    """(meetings, dropped). Meetings are announced ahead, so the window
    looks 60 days forward; a backfill goes one calendar month per call."""
    end = today + timedelta(days=60)
    spans = month_chunks(backfill_from, end) if backfill_from else [(start, end)]
    frames, dropped = [], 0
    for a, b in spans:
        if raw is not None:
            nse.on_response = raw_hook(raw, 'meetings', {'from': a.isoformat(), 'to': b.isoformat()})
        df, n = parsers.parse_board_meetings(nse.board_meetings(a, b))
        frames.append(df)
        dropped += n
    full = [f for f in frames if not f.empty]
    df = pd.concat(full, ignore_index=True).drop_duplicates('event_id', keep='last') if full else frames[0]
    return df, dropped


def build_buybacks(r2, master, run_date, report) -> None:
    """clean/current/buybacks.parquet from tenders, daily reports and corporate actions."""
    arch = {s: merge_into_archive(r2, s, None, run_date)[0] for s in ('tenders', 'daily_buybacks', 'actions')}
    if all(a is None or a.empty for a in arch.values()):
        return
    bb, rep = buybacks.build(arch['tenders'], arch['daily_buybacks'], arch['actions'])
    report['buybacks'] = rep
    if not bb.empty:
        put_parquet(r2, 'clean/current/buybacks.parquet', add_identity(bb, master))


def store_raw(raw: RawStore | None, dataset: str, body: str, url: str, report: dict, content_type: str, covers=None):
    """The exact text NSE sent, write-once in raw_v2. Never stops the run: a
    failure is counted in the report."""
    if raw is None:
        return
    try:
        raw.put('nse', dataset, body.encode('utf-8'), url=url, content_type=content_type, covers=covers)
    except Exception as exc:  # noqa: BLE001
        counts = report.setdefault('raw_not_stored', {})
        counts[type(exc).__name__] = counts.get(type(exc).__name__, 0) + 1


def issue_filings(nse: NSEClient, raw: RawStore | None, start: date, today: date, report: dict) -> pd.DataFrame:
    """Archive rows for every further-issue filing NSE posted in [start, today].
    A refusal stops the lists (Blocked goes up); one failing list does not."""
    frames = []
    for kind in issues.KINDS:
        for stage in ('in_principle', 'listing'):
            url = nse.further_issues_url(kind, stage, start, today)
            try:
                text = nse.get(url, as_json=False)
                store_raw(raw, 'further_issues', text, url, report, 'application/json',
                          {'from': start.isoformat(), 'to': today.isoformat(), 'kind': kind, 'stage': stage})
                j = json.loads(text)
                frames.append(issues.filing_rows(kind, stage, j.get('data', []) if isinstance(j, dict) else j))
            except Blocked:
                raise
            except Exception as exc:  # noqa: BLE001
                report['notes'].append(f'issues/{kind}/{stage}: list failed ({type(exc).__name__}: {exc})')
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=issues.FILING_COLUMNS)


def fetch_issue_xbrl(nse: NSEClient, raw: RawStore | None, rows: pd.DataFrame, known: pd.DataFrame | None,
                     report: dict, max_xbrl: int = MAX_ISSUE_XBRL_PER_RUN) -> pd.DataFrame:
    """Parsed XBRL facts on tonight's filings, each file fetched once: facts
    already parsed are carried over, and filings still 'pending' in the archive
    (refused or over the cap on an earlier night) are retried even when the
    window no longer lists them. Only issues.XBRL_WANTED are fetched."""
    rows = rows.copy()
    prev = known.set_index('event_id') if known is not None and not known.empty else None
    if prev is not None:
        pending = known[known['xbrl_status'].astype('string').eq('pending').fillna(False)
                        & ~known['event_id'].isin(rows['event_id'])]
        rows = pd.concat([rows, pending[[c for c in issues.FILING_COLUMNS if c in pending.columns]]], ignore_index=True)
    rows['xbrl_status'] = rows['xbrl_status'].astype(object)
    rows['xbrl_json'] = rows['xbrl_json'].astype(object)
    fetched, blocked = 0, False
    for i, row in rows.sort_values('posted_on', ascending=False, kind='stable', na_position='last').iterrows():
        eid = row['event_id']
        if prev is not None and eid in prev.index and str(prev.at[eid, 'xbrl_status']) == 'ok':
            rows.at[i, 'xbrl_status'], rows.at[i, 'xbrl_json'] = 'ok', prev.at[eid, 'xbrl_json']
            continue
        if (row['kind'], row['stage']) not in issues.XBRL_WANTED:
            rows.at[i, 'xbrl_status'] = 'not_needed'
            continue
        url = row['xbrl_url']
        if not isinstance(url, str) or not url.startswith('http'):
            rows.at[i, 'xbrl_status'] = 'no_xbrl'
            continue
        if blocked or fetched >= max_xbrl:
            rows.at[i, 'xbrl_status'] = 'pending'
            continue
        fetched += 1
        try:
            text = nse.xbrl(url)
            store_raw(raw, 'further_issue_xbrl', text, url, report, 'application/xml')
            rows.at[i, 'xbrl_json'] = json.dumps(issues.parse_xbrl(text), ensure_ascii=False)
            rows.at[i, 'xbrl_status'] = 'ok'
        except Blocked:
            rows.at[i, 'xbrl_status'] = 'pending'
            blocked = True
            report['issue_xbrl_blocked'] = True
            report['notes'].append('NSE refused a further-issue XBRL; the rest wait for the next run')
        except Exception as exc:  # noqa: BLE001 -- one bad file must not stop the rest
            rows.at[i, 'xbrl_status'] = f'failed: {type(exc).__name__}'
    report['issue_xbrl_fetched'] = fetched
    return rows


def results_filings(nse: NSEClient, raw: RawStore | None, start: date, today: date, report: dict) -> pd.DataFrame:
    """Every financial-results filing NSE lists for [start, today], page by page until its totalCount (or a
    page with nothing new), one window of at most 31 days at a time so that a backfill of years is not cut at
    the page limit. A refusal goes up (Blocked)."""
    seen, frames, total_all = set(), [], 0
    lo = start
    while lo <= today:
        hi = min(lo + timedelta(days=30), today)
        total = None
        for page in range(1, 101):
            url = nse.integrated_results_url(lo, hi, page, RESULTS_PAGE)
            text = nse.get(url, as_json=False)
            store_raw(raw, 'results_list', text, url, report, 'application/json',
                      {'from': lo.isoformat(), 'to': hi.isoformat(), 'page': page})
            j = json.loads(text)
            total = j.get('totalCount') if isinstance(j, dict) else None
            df = results.filing_rows(j.get('data', []) if isinstance(j, dict) else j)
            df = df[~df['seq_id'].isin(seen)]
            if df.empty:
                break
            seen.update(df['seq_id'])
            frames.append(df)
            if total is not None and len(seen) >= total_all + int(total):
                break
        total_all += int(total or 0)
        lo = hi + timedelta(days=1)
    report['results_listed'], report['results_total'] = len(seen), total_all
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=results.FILING_COLUMNS)


def fetch_results_xbrl(nse: NSEClient, raw: RawStore | None, rows: pd.DataFrame, known: pd.DataFrame | None,
                       report: dict, max_xbrl: int = MAX_RESULTS_XBRL_PER_RUN, workers: int = 1,
                       pause: tuple = (0.4, 0.9)) -> pd.DataFrame:
    """Each listed filing's XBRL read once (raw kept in raw_v2): facts already read are carried over, filings
    'pending' in the archive (refused or over the cap on an earlier night) are retried even when the window no
    longer lists them, newest first. `workers` > 1 fetches that many files at once, each worker with its own
    session and the short `pause` (a backfill of years); the nightly run keeps one worker and NSE's usual pause.
    A refusal stops every worker; what was not fetched stays pending."""
    rows = rows.copy()
    prev = known.set_index('event_id') if known is not None and not known.empty else None
    if prev is not None:
        pending = known[known['xbrl_status'].astype('string').eq('pending').fillna(False)
                        & ~known['event_id'].isin(rows['event_id'])]
        rows = pd.concat([rows, pending[[c for c in results.FILING_COLUMNS if c in pending.columns]]], ignore_index=True)
    rows['xbrl_status'] = rows['xbrl_status'].astype(object)
    rows['xbrl_json'] = rows['xbrl_json'].astype(object)
    todo = []
    for i, row in rows.sort_values('broadcast_at', ascending=False, kind='stable', na_position='last').iterrows():
        eid = row['event_id']
        if prev is not None and eid in prev.index and str(prev.at[eid, 'xbrl_status']) == 'ok':
            rows.at[i, 'xbrl_status'], rows.at[i, 'xbrl_json'] = 'ok', prev.at[eid, 'xbrl_json']
            continue
        url = row['xbrl_url']
        if not isinstance(url, str) or not url.startswith('http'):
            rows.at[i, 'xbrl_status'] = 'no_xbrl'
            continue
        if len(todo) >= max_xbrl:
            rows.at[i, 'xbrl_status'] = 'pending'
            continue
        todo.append((i, url))
    fetched, blocked = 0, False
    stop = threading.Event()
    local = threading.local()

    def get(url):
        if stop.is_set():
            return 'skipped', None
        client = nse if workers <= 1 else getattr(local, 'client', None)
        if client is None:
            client = local.client = NSEClient(pause=pause)
        try:
            return 'ok', client.xbrl(url)
        except Blocked:
            stop.set()
            return 'blocked', None
        except Exception as exc:  # noqa: BLE001 -- one bad file must not stop the rest
            return f'failed: {type(exc).__name__}', None

    if workers <= 1:
        answers = (get(url) for _, url in todo)
        pool = None
    else:
        pool = ThreadPoolExecutor(max_workers=workers)
        answers = pool.map(get, [url for _, url in todo])
    try:
        for (i, url), (state, text) in zip(todo, answers):
            if state == 'ok':
                fetched += 1
                store_raw(raw, 'results_xbrl', text, url, report, 'application/xml')
                try:
                    rows.at[i, 'xbrl_json'] = json.dumps(results.parse_xbrl(text), ensure_ascii=False)
                    rows.at[i, 'xbrl_status'] = 'ok'
                except Exception as exc:  # noqa: BLE001
                    rows.at[i, 'xbrl_status'] = f'failed: {type(exc).__name__}'
            elif state in ('blocked', 'skipped'):
                rows.at[i, 'xbrl_status'] = 'pending'
                if state == 'blocked' and not blocked:
                    blocked = True
                    report['results_xbrl_blocked'] = True
                    report['notes'].append('NSE refused a results XBRL; the rest wait for the next run')
            else:
                fetched += 1
                rows.at[i, 'xbrl_status'] = state
    finally:
        if pool is not None:
            pool.shutdown(wait=True)
    report['results_xbrl_fetched'] = fetched
    return rows


def issue_coverage(arch: pd.DataFrame | None) -> dict:
    """Filings per kind and stage, and XBRL status counts. Counts only."""
    if arch is None or arch.empty:
        return {}
    text = arch['xbrl_status'].astype('string')
    status = text.fillna('none').str.split(':').str[0]
    failed = text.dropna()
    return {'filings': {f'{k}/{s}': int(n) for (k, s), n in arch.groupby(['kind', 'stage']).size().items()},
            'xbrl_status': {k: int(v) for k, v in status.value_counts().items()},
            'xbrl_failure_types': {k: int(v) for k, v in failed[failed.str.startswith('failed')].value_counts().items()},
            'pending_xbrl': int((status == 'pending').sum())}


GROUP_BATCHES = 'archive/nse_events/promoter_group/'


def write_promoter_group(r2, batch: list, master: SecurityMaster, run_date: str, now: datetime) -> dict:
    """Promoter-group members parsed tonight -> a new write-once batch file
    (archive/nse_events/promoter_group/batch=<run time>.parquet, never
    rewritten), then clean/current/promoter_group.parquet rebuilt from every
    batch (insiders_clean/promoter_group.clean_members). Counts for the report."""
    entry = {'filings_parsed': len(batch), 'members_parsed': int(sum(len(b) for b in batch))}
    rows = pd.concat([b for b in batch if b is not None and not b.empty], ignore_index=True) \
        if any(b is not None and not b.empty for b in batch) else None
    if rows is not None:  # filings that name no member (no promoter group) add no rows
        key = f'{GROUP_BATCHES}batch={now:%Y-%m-%dT%H%M%S}.parquet'
        if get(r2, key) is None:
            put_parquet(r2, key, rows)
            entry['batch_written'] = key
    keys = sorted(k for k in list_keys(r2, GROUP_BATCHES) if k.endswith('.parquet'))
    if not keys:
        return entry
    table, counts = promoter_group.clean_members([read_parquet(r2, k) for k in keys])
    entry.update(batches=len(keys), **counts)
    if not table.empty:
        table = add_identity(table, master)
        table['isin'] = table['isin'].astype('string')
        put_parquet(r2, 'clean/current/promoter_group.parquet', table)
    return entry


def run(r2, nse: NSEClient, today: date, days: int, streams=STREAMS, max_xbrl: int = MAX_XBRL_PER_RUN,
        raw=None, backfill_from: date | None = None, max_issue_xbrl: int = MAX_ISSUE_XBRL_PER_RUN,
        now: datetime | None = None, max_results_xbrl: int = MAX_RESULTS_XBRL_PER_RUN, results_workers: int = 1,
        results_window: tuple | None = None) -> dict:
    run_date = today.isoformat()
    start = today - timedelta(days=days)
    report = {'run_date': run_date, 'window': [start.isoformat(), run_date], 'streams': {}, 'notes': []}
    if backfill_from:
        report['meetings_backfill_from'] = backfill_from.isoformat()
    master = security_master(r2, run_date, report['notes'])
    blocked = False
    members: list = []
    for stream in streams:
        entry = report['streams'].setdefault(stream, {})
        new = None
        if not blocked:
            nse.on_response = (raw_hook(raw, stream, {'from': start.isoformat(), 'to': run_date})
                               if raw is not None and stream in RAW_STREAMS else None)
            try:
                if stream == 'sast':
                    new = parsers.parse_sast(nse.sast_reg29(start, today))
                elif stream == 'actions':
                    new, entry['dropped_other_purposes'] = parsers.parse_corporate_actions(
                        nse.corporate_actions(start, today))
                elif stream == ISSUES:
                    known = merge_into_archive(r2, stream, None, run_date)[0]
                    iraw = raw if raw is not None else RawStore(r2, BUCKET, collector='collectors.nse_events.run_daily')
                    new = fetch_issue_xbrl(nse, iraw, issue_filings(nse, iraw, start, today, report), known, report,
                                           max_issue_xbrl)
                    blocked = bool(report.get('issue_xbrl_blocked'))
                elif stream == RESULTS:
                    known = merge_into_archive(r2, stream, None, run_date)[0]
                    rraw = raw if raw is not None else RawStore(r2, BUCKET, collector='collectors.nse_events.run_daily')
                    lo, hi = results_window or (start, today)
                    new = fetch_results_xbrl(nse, rraw, results_filings(nse, rraw, lo, hi, report), known, report,
                                             max_results_xbrl, results_workers)
                    blocked = bool(report.get('results_xbrl_blocked'))
                elif stream == 'meetings':
                    new, entry['dropped_routine'] = fetch_meetings(nse, start, today, raw, backfill_from)
                elif stream == 'tenders':
                    new = parsers.parse_tender_offers(nse.tender_offers_past(), nse.tender_offers_active())
                elif stream == 'daily_buybacks':
                    new = parsers.parse_daily_buybacks(nse.daily_buybacks(start, today))
                else:
                    listing = parsers.parse_shareholding_listing(nse.shareholding_filings(start, today))
                    known = merge_into_archive(r2, stream, None, run_date)[0]
                    new = fetch_xbrl(nse, listing, known, report, max_xbrl, members, raw, run_date)
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
        if stream == ISSUES:   # cleaned by scripts/clean_writer.py, which reads this archive
            entry['coverage'] = issue_coverage(arch)
            continue
        if stream == RESULTS:   # one row per filing with its summary; the full facts stay in the archive
            entry['xbrl'] = arch['xbrl_status'].astype(str).value_counts().to_dict()
            report['pending_results'] = int(entry['xbrl'].get('pending', 0))
            clean = add_identity(results.clean(arch), master)
            entry['unmatched_securities'] = int(clean['unmatched_security'].sum())
            entry['clean_rows'] = len(clean)
            put_parquet(r2, f'clean/current/{stream}.parquet', clean)
            continue
        clean = add_identity(arch, master)
        if stream == 'shareholding':
            clean = clean_shareholding(clean)
            entry['coverage'] = shareholding_coverage(clean)
            report['pending_xbrl'] = entry['coverage']['pending_xbrl']
            report['pending_members'] = entry['coverage']['pending_members']
        entry['unmatched_securities'] = int(clean['unmatched_security'].sum())
        entry['clean_rows'] = len(clean)
        put_parquet(r2, f'clean/current/{stream}.parquet', clean)
    nse.on_response = None
    if {'tenders', 'daily_buybacks', 'actions'} & set(streams):
        try:  # a failure here must never stop the event tables
            build_buybacks(r2, master, run_date, report)
        except Exception as exc:  # noqa: BLE001
            report['notes'].append(f'buybacks: failed ({type(exc).__name__}: {exc})')
    if 'shareholding' in streams:
        try:  # a failure here must never cost the shareholding table written above
            report['promoter_group'] = write_promoter_group(
                r2, members, master, run_date, now or datetime.now(timezone.utc))
        except Exception as exc:  # noqa: BLE001
            report['notes'].append(f'promoter_group: failed ({type(exc).__name__}: {exc})')
    report['nse_calls'] = nse.calls
    put(r2, f'clean/reports/nse_events/{run_date}.json', json.dumps(report, indent=2, default=str).encode(),
        'application/json')
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--days', type=int, default=10)
    ap.add_argument('--dataset', choices=('all',) + STREAMS, default='all')
    ap.add_argument('--max-xbrl', type=int, default=MAX_XBRL_PER_RUN,
                    help='shareholding pledge files to fetch this run (NSE rate-limits by IP)')
    ap.add_argument('--from', dest='backfill_from', type=date.fromisoformat, default=None,
                    help='board meetings only: backfill month by month from this date (YYYY-MM-DD)')
    ap.add_argument('--max-issue-xbrl', type=int, default=MAX_ISSUE_XBRL_PER_RUN,
                    help='further-issue XBRL files to fetch this run')
    ap.add_argument('--max-results-xbrl', type=int, default=MAX_RESULTS_XBRL_PER_RUN,
                    help='financial-results XBRL files to fetch this run')
    ap.add_argument('--results-from', type=date.fromisoformat, default=None,
                    help='results only: list this window [from, to] instead of the last --days (a backfill, window by window)')
    ap.add_argument('--results-to', type=date.fromisoformat, default=None)
    ap.add_argument('--results-workers', type=int, default=1,
                    help='results XBRL files fetched at once (a backfill of years); 1 = one at a time with NSE\'s pause')
    args = ap.parse_args(argv)
    today = datetime.now(IST).date()
    streams = STREAMS if args.dataset == 'all' else (args.dataset,)
    if args.backfill_from and streams != ('meetings',):
        ap.error('--from needs --dataset meetings')
    r2 = r2_client()
    report = run(r2, NSEClient(), today, args.days, streams, args.max_xbrl,
                 raw=RawStore(r2, bucket=BUCKET, collector='nse_events'), backfill_from=args.backfill_from,
                 max_issue_xbrl=args.max_issue_xbrl, max_results_xbrl=args.max_results_xbrl,
                 results_workers=args.results_workers,
                 results_window=(args.results_from, args.results_to or today) if args.results_from else None)
    Path('nse_events_report.json').write_text(json.dumps(report, default=str))  # read by the workflow's continue step
    for name, s in report['streams'].items():
        print(f'  {name}: {s}')
    if 'promoter_group' in report:
        print(f'  promoter_group: {report["promoter_group"]}')
    for n in report['notes']:
        print(f'  note: {n}')
    print(f'  NSE calls: {report["nse_calls"]}; bucket {"set" if BUCKET else "MISSING"}')


if __name__ == '__main__':
    main()
