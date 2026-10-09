"""Nightly cleaning step: canonical/ in R2 -> archive/ and clean/ in R2.

Runs after r2_writer.py in the R2 Storage Write workflow.

1. Archive. For each (exchange, category), today's canonical Parquet is
   merged into archive/canonical/{exchange}/{category}.parquet, which holds
   each source record once (insiders_clean/archive.py). The first run builds
   the archive from every dated canonical file already in the bucket.
2. Clean. The clean tables are rebuilt from the whole archive, with:
   * NSE's equity lists (main board + SME), fetched now; a copy is kept at
     reference/security_lists/{date}/ so a failed fetch falls back to the
     last good copy;
   * BSE's securities list from the market-cap reference file the writer
     stores (reference/market_cap/{date}/data.json);
   * the trading calendar at reference/nse_calendar.json (kept current by
     scripts/update_calendar.py, which runs just before this);
   * that day's traded range from our own price layer
     (prices/daily/{nse|bse}/YYYY-MM.parquet, the months of the product
     window) for the price checks. Missing or unreadable months are noted;
     with no prices at all the clean step runs and the checks say so.
3. Write clean/current/{insider_trades,deals,securities}.parquet (the full
   history the site reads), clean/reports/{date}.json, and last
   clean/latest.json -- so a reader never follows the pointer to a
   half-written run.
"""
from __future__ import annotations

import io
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

from r2_writer import BUCKET, SECURITY_MASTER_PATH, TARGET_DATE, r2_client

from insiders_clean import archive, day_range
from insiders_clean.calendar import seed_state
from insiders_clean.pipeline import PRODUCT_START, run

CATEGORIES = ('insider_trading', 'bulk_deals', 'block_deals')
LOOKBACK_DAYS = 10
NSE_LISTS = {
    'nse_equity.csv': 'https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv',
    'nse_sme_equity.csv': 'https://nsearchives.nseindia.com/emerge/corporates/content/SME_EQUITY_L.csv',
}
CALENDAR_KEY = 'reference/nse_calendar.json'


def archive_prefix(exchange, category):
    return f'archive/canonical/{exchange}/{category}/'


def archive_state_key(exchange, category):
    return archive_prefix(exchange, category) + '_state.json'


def get(client, key) -> bytes | None:
    try:
        return client.get_object(Bucket=BUCKET, Key=key)['Body'].read()
    except client.exceptions.NoSuchKey:
        return None


def put(client, key, body: bytes, content_type: str):
    client.put_object(Bucket=BUCKET, Key=key, Body=body, ContentType=content_type)


def put_parquet(client, key, df: pd.DataFrame):
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    put(client, key, buf.getvalue(), 'application/octet-stream')


def list_keys(client, prefix):
    keys, token = [], None
    while True:
        kw = {'Bucket': BUCKET, 'Prefix': prefix}
        if token:
            kw['ContinuationToken'] = token
        resp = client.list_objects_v2(**kw)
        keys += [o['Key'] for o in resp.get('Contents', [])]
        if not resp.get('IsTruncated'):
            return keys
        token = resp['NextContinuationToken']


def dated_canonical(client, exchange, category):
    """[(date, key)] of every dated canonical file for this dataset."""
    prefix = f'canonical/{exchange}/{category}/'
    out = []
    for key in list_keys(client, prefix):
        parts = key[len(prefix):].split('/')
        if len(parts) == 2 and parts[1] == 'data.parquet':
            out.append((parts[0], key))
    return sorted(out)


def read_parquet(client, key):
    body = get(client, key)
    return pd.read_parquet(io.BytesIO(body)) if body is not None else None


def read_archive(client, exchange, category) -> pd.DataFrame | None:
    """Every partition of one dataset's archive, concatenated."""
    keys = [k for k in list_keys(client, archive_prefix(exchange, category)) if k.endswith('.parquet')]
    frames = [read_parquet(client, k) for k in sorted(keys)]
    frames = [f for f in frames if f is not None and not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else None


def update_archive(client, exchange, category, notes, report_archive):
    """Merge today's canonical file (or, on the first run, every dated file)
    into the partitioned archive. Returns the whole archive as one frame."""
    prefix = archive_prefix(exchange, category)
    state_body = get(client, archive_state_key(exchange, category))
    state = json.loads(state_body) if state_body else None
    touched, added = {}, 0

    def load(part):
        if part in touched:
            return touched[part]
        return read_parquet(client, f'{prefix}{part}.parquet')

    if state is None:
        files = dated_canonical(client, exchange, category)
        for day, k in files:
            parts, n = archive.merge_partitioned(load, read_parquet(client, k), day, category)
            touched.update(parts)
            added += n
        if files:
            notes.append(f'{exchange}/{category}: archive built from {len(files)} dated files')
    today = read_parquet(client, f'canonical/{exchange}/{category}/{TARGET_DATE}/data.parquet')
    written_today = today is not None
    if written_today:
        parts, n = archive.merge_partitioned(load, today, TARGET_DATE, category)
        touched.update(parts)
        added += n
    elif state is not None:
        notes.append(f'{exchange}/{category}: nothing written today; archive unchanged')

    for part, frame in touched.items():
        put_parquet(client, f'{prefix}{part}.parquet', frame)
    arch = read_archive(client, exchange, category)
    if arch is not None:
        # last_merged says which dated snapshots the archive has absorbed
        # (r2_retention). Backfilled rows carry the backfill's run date as
        # last_seen, so they never count here; other keys in the state (the
        # backfill's own entry) are kept.
        nightly = arch[~archive.from_history(arch)]
        if written_today:
            last = TARGET_DATE
        elif state is not None:
            last = state.get('last_merged', '')
        else:
            last = str(nightly['last_seen'].max()) if not nightly.empty else ''
        new_state = {**(state or {}), 'last_merged': max(last, (state or {}).get('last_merged', '')),
                     'records': len(arch), 'partitions_written_today': sorted(touched)}
        put(client, archive_state_key(exchange, category), json.dumps(new_state).encode(), 'application/json')
    withdrawn = int(archive.possibly_withdrawn(arch, TARGET_DATE).sum()) if written_today and arch is not None else None
    report_archive[f'{exchange}/{category}'] = {
        'records': 0 if arch is None else len(arch), 'new_today': added,
        'partitions_written': sorted(touched), 'written_today': written_today,
        'possibly_withdrawn_at_source': withdrawn}
    return arch


def nse_lists(client, run_day: str, notes: list):
    frames = []
    for name, url in NSE_LISTS.items():
        body = None
        try:
            resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30)
            if resp.status_code == 200 and resp.content.startswith(b'SYMBOL'):
                body = resp.content
                put(client, f'reference/security_lists/{run_day}/{name}', body, 'text/csv')
        except requests.RequestException:
            pass
        if body is None:
            body = last_good(client, f'reference/security_lists/{{day}}/{name}', date.fromisoformat(run_day))
            notes.append(f'{name}: fetch failed, used last stored copy' if body
                         else f'{name}: fetch failed and no stored copy; NSE identity from other sources only')
        if body:
            frames.append(pd.read_csv(io.BytesIO(body), dtype=str, keep_default_na=False))
    return frames


def last_good(client, pattern, run_day: date, include_today=False):
    start = 0 if include_today else 1
    for back in range(start, LOOKBACK_DAYS + 1):
        body = get(client, pattern.format(day=(run_day - timedelta(days=back)).isoformat()))
        if body:
            return body
    return None


def load_price_ranges(client, run_day: date, notes: list):
    """Day ranges for every month of the product window, read-only.
    Returns (ranges or None, info for the report)."""
    try:
        ranges, info = day_range.load(lambda k: get(client, k), day_range.months_between(PRODUCT_START, run_day))
    except Exception as e:  # noqa: BLE001 -- prices are an input to checks, never a reason to fail the clean step
        notes.append(f'price layer not read ({type(e).__name__}: {e}); price checks not run')
        return None, {'error': f'{type(e).__name__}: {e}'}
    if ranges is None:
        notes.append('no price-layer months found; price checks not run')
    if info.get('months_unreadable'):
        notes.append(f'price layer: {len(info["months_unreadable"])} month file(s) unreadable, their days unchecked')
    return ranges, info


def main():
    client = r2_client()
    run_day = date.fromisoformat(TARGET_DATE)
    notes, archive_report = [], {}

    canonical = {}
    for ex in ('nse', 'bse'):
        for cat in CATEGORIES:
            arch = update_archive(client, ex, cat, notes, archive_report)
            if arch is not None and not arch.empty:
                canonical[(ex, cat)] = arch

    mcap_body = last_good(client, 'reference/market_cap/{day}/data.json', run_day, include_today=True)
    market_cap_rows = json.loads(mcap_body) if mcap_body else []
    if not mcap_body:
        notes.append('no market-cap file in the last 10 days: no BSE list, no % of market cap')

    cal_body = get(client, CALENDAR_KEY)
    calendar_state = json.loads(cal_body) if cal_body else seed_state()
    if not cal_body:
        notes.append('trading calendar not in R2 yet; used the seed in reference_data/')

    vr_path = ROOT / SECURITY_MASTER_PATH
    vr_master = pd.read_csv(vr_path, dtype=str, keep_default_na=False) if vr_path.exists() else None

    ranges, price_info = load_price_ranges(client, run_day, notes)
    tables, report = run(canonical, TARGET_DATE, calendar_state, vr_master=vr_master,
                         nse_lists=nse_lists(client, TARGET_DATE, notes), market_cap_rows=market_cap_rows,
                         price_ranges=ranges)
    report['archive'] = archive_report
    report['price_layer'] = price_info
    report['notes'] = notes + report['notes']

    written = {}
    for name, df in tables.items():
        key = f'clean/current/{name}.parquet'
        put_parquet(client, key, df)
        written[name] = {'key': key, 'rows': len(df)}
    report['written'] = written
    put(client, f'clean/reports/{TARGET_DATE}.json', json.dumps(report, indent=2, default=str).encode(),
        'application/json')
    put(client, 'clean/latest.json',
        json.dumps({'date': TARGET_DATE, 'tables': written, 'report': f'clean/reports/{TARGET_DATE}.json'}).encode(),
        'application/json')

    for name, a in archive_report.items():
        print(f'  archive {name}: {a["records"]} records, {a["new_today"]} new')
    for name, w in written.items():
        print(f'  WRITE clean/current/{name}: {w["rows"]} rows')
    for table, t in report['tables'].items():
        print(f'  {table}: {t["input_rows"]} in -> {t["output_rows"]} out; '
              f'removed {sum(r["count"] for r in t["removed"].values())}; flagged {t["flagged"]}')
    print(f'  unmatched securities: {len(report["unmatched_securities"])}')
    for table, t in report['tables'].items():
        if t.get('price_check'):
            print(f'  {table} price check: {t["price_check"]["all"]}')
        if t.get('holding_check'):
            print(f'  {table} holding check: {t["holding_check"]}')
    for table, t in report['tables'].items():
        for reason, r in t.get('removed', {}).items():
            print(f'  removed {table}/{reason}: {r["count"]}')
        b = t.get('removal_breakdown')
        if b:
            print(f'  {table} copies: by exchange {b["by_exchange"]}; same filing ID {b["same_filing_id"]}, '
                  f'different filing ID {b["different_filing_id"]}, no filing ID {b["no_filing_id"]}')
            print(f'  {table} fields that differ between kept and removed copies: {b["differing_fields"]}')
    for n in report['notes']:
        print(f'  note: {n}')


if __name__ == '__main__':
    main()
