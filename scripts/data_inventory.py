"""Read-only inventory of the R2 bucket, plus sample-size and power numbers.

    python scripts/data_inventory.py --out inventory/ [--prices PATH_OR_URL]

Output is AGGREGATE ONLY (counts, date bounds, column names, null rates); it
never prints a person's name or a row. It reads R2 and (optionally) one price
table, and writes inventory.json and inventory.md. Run by
.github/workflows/data-inventory.yml, which has `contents: read` and no write
access to R2 from this script (it only calls get/list).

Forward-return windows: signal time = the filing's broadcast date; entry = the
first session AFTER it (the conservative entry of the research design); a window
of h sessions is complete if the price table has entry + h. Prices are a proxy
(Paresh's public adjusted-close table, NSE symbols only); the real price layer
is a later task, so coverage here is a lower bound for the real thing.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

import clean_writer  # noqa: E402

from insiders_clean.dates import parse_dates  # noqa: E402
from insiders_clean.missing import as_flag  # noqa: E402

PRODUCT_START = date(2026, 1, 1)
HORIZONS = (5, 20, 60, 120, 250)
DATE_COLS = {'insider_trading': ('canonical_transaction_date', 'canonical_transaction_date_to',
                                 'canonical_broadcast_date'),
             'bulk_deals': ('canonical_event_date',), 'block_deals': ('canonical_event_date',)}
KEY_COLS = ('canonical_symbol', 'canonical_isin', 'canonical_company', 'canonical_side',
            'canonical_quantity', 'canonical_price', 'canonical_value', 'canonical_client',
            'canonical_person', 'canonical_mode')
Z_ALPHA, Z_POWER = 1.959964, 0.841621  # two-sided 5%, 80% power


def _dates(frame, cols):
    for c in cols:
        if c in frame.columns:
            d = parse_dates(frame[c])
            if d.notna().any():
                return c, d
    return None, None


def describe_frame(frame: pd.DataFrame, category: str | None) -> dict:
    out = {'rows': int(len(frame)), 'columns': int(frame.shape[1]), 'column_names': sorted(map(str, frame.columns))}
    nulls = {}
    for c in KEY_COLS:
        if c in frame.columns:
            s = frame[c]
            nulls[c] = round(float((s.isna() | (s.astype(str).str.strip() == '')).mean()), 4)
    out['blank_share'] = nulls
    col, d = _dates(frame, DATE_COLS.get(category, ()))
    if d is not None:
        ok = d.dropna()
        out['date_column'] = col
        out['date_min'] = min(ok).isoformat() if len(ok) else None
        out['date_max'] = max(ok).isoformat() if len(ok) else None
        out['unreadable_dates'] = int(d.isna().sum())
        out['rows_before_2026'] = int(sum(x < PRODUCT_START for x in ok))
        out['rows_2026_onward'] = int(sum(x >= PRODUCT_START for x in ok))
        out['rows_by_month'] = {k: int(v) for k, v in
                                pd.Series([x.strftime('%Y-%m') for x in ok]).value_counts().sort_index().tail(24).items()}
    if 'intraday_round_trip' in frame.columns:
        out['intraday_round_trip_flagged'] = int(as_flag(frame['intraday_round_trip']).sum())
        out['rows_with_round_trip_flag_set_or_false'] = int(frame['intraday_round_trip'].notna().sum())
    else:
        out['intraday_round_trip_flagged'] = None  # column absent: written before flags existed
    for c in ('first_seen', 'last_seen'):
        if c in frame.columns:
            out[f'{c}_min'] = str(frame[c].min())
            out[f'{c}_max'] = str(frame[c].max())
    return out


def bucket_listing(client, bucket) -> dict:
    tops, token = {}, None
    while True:
        kw = {'Bucket': bucket, 'Prefix': ''}
        if token:
            kw['ContinuationToken'] = token
        r = client.list_objects_v2(**kw)
        for o in r.get('Contents', []):
            top = o['Key'].split('/', 1)[0]
            t = tops.setdefault(top, {'objects': 0, 'bytes': 0})
            t['objects'] += 1
            t['bytes'] += int(o.get('Size', 0))
        if not r.get('IsTruncated'):
            return tops
        token = r['NextContinuationToken']


# --- forward windows and power -------------------------------------------------

def forward_windows(events: pd.DataFrame, prices: pd.DataFrame) -> dict:
    """events: symbol, signal_date (date). prices: sessions x symbols (adjusted close)."""
    sessions = pd.DatetimeIndex(prices.index)
    last = len(sessions) - 1
    ev = events.dropna(subset=['symbol', 'signal_date']).copy()
    ev['covered'] = ev['symbol'].isin(prices.columns)
    sig = pd.to_datetime(ev['signal_date'])
    entry = sessions.searchsorted(sig.to_numpy(), side='right')  # first session strictly after the signal date
    ev['entry_pos'] = entry
    res = {'events': int(len(ev)), 'with_price_history': int(ev['covered'].sum()),
           'price_last_date': sessions[-1].date().isoformat(), 'horizons': {}}
    for h in HORIZONS:
        ok = ev['covered'] & (ev['entry_pos'] + h <= last)
        sub = ev[ok]
        row = {'complete_events': int(ok.sum()), 'distinct_companies': int(sub['symbol'].nunique()),
               'distinct_company_months': int(sub.assign(m=pd.to_datetime(sub['signal_date']).dt.to_period('M'))
                                              [['symbol', 'm']].drop_duplicates().shape[0])}
        if len(sub) >= 30:
            rets = []
            for sym, pos in zip(sub['symbol'], sub['entry_pos']):
                p0, p1 = prices[sym].iloc[pos], prices[sym].iloc[pos + h]
                if p0 > 0 and p1 > 0 and not (np.isnan(p0) or np.isnan(p1)):
                    bench = (prices.iloc[pos + h] / prices.iloc[pos]).replace([np.inf, -np.inf], np.nan)
                    b = np.log(bench).median()  # median stock = a crude market proxy
                    rets.append(math.log(p1 / p0) - b)
            if len(rets) >= 30:
                sd = float(np.std(rets, ddof=1))
                row['abnormal_sd'] = round(sd, 4)
                for label, n in (('events', len(rets)), ('company_months', row['distinct_company_months'])):
                    row[f'mde_{label}'] = round(float((Z_ALPHA + Z_POWER) * sd / math.sqrt(max(n, 1))), 4)
        res['horizons'][str(h)] = row
    return res


def load_prices(src: str) -> pd.DataFrame | None:
    try:
        if src.startswith('http'):
            import requests
            body = requests.get(src, timeout=180).content
            df = pd.read_parquet(io.BytesIO(body))
        else:
            df = pd.read_parquet(src)
    except Exception as e:  # noqa: BLE001
        print(f'prices unavailable: {type(e).__name__}: {e}')
        return None
    df.index = pd.to_datetime(df.index)
    return df.sort_index()


# --- main ------------------------------------------------------------------------

def inventory(client, bucket, prices: pd.DataFrame | None, run_date: str) -> dict:
    clean_writer.BUCKET = bucket
    inv = {'run_date': run_date, 'bucket_prefixes': bucket_listing(client, bucket), 'archive': {}, 'clean': {}}
    for ex in ('nse', 'bse'):
        for cat in clean_writer.CATEGORIES:
            f = clean_writer.read_archive(client, ex, cat)
            inv['archive'][f'{ex}/{cat}'] = describe_frame(f, cat) if f is not None else None
            st = clean_writer.get(client, clean_writer.archive_state_key(ex, cat))
            if st and inv['archive'][f'{ex}/{cat}'] is not None:
                inv['archive'][f'{ex}/{cat}']['state'] = json.loads(st)
    tables = {}
    for name in ('insider_trades', 'deals', 'securities'):
        t = clean_writer.read_parquet(client, f'clean/current/{name}.parquet')
        tables[name] = t
        if t is None:
            inv['clean'][name] = None
            continue
        d = {'rows': int(len(t)), 'columns': sorted(map(str, t.columns))}
        dc = {'insider_trades': 'trade_date_to', 'deals': 'date'}.get(name)
        if dc and dc in t.columns:
            dd = pd.to_datetime(t[dc], errors='coerce').dropna()
            d['date_min'], d['date_max'] = str(dd.min().date()), str(dd.max().date())
            d['rows_before_2026'] = int((dd < pd.Timestamp(PRODUCT_START)).sum())
        for flag in ('is_market', 'is_primary', 'needs_review'):
            if flag in t.columns:
                d[flag] = int(t[flag].fillna(False).astype(bool).sum())
        inv['clean'][name] = d
    latest = clean_writer.get(client, 'clean/latest.json')
    if latest:
        ptr = json.loads(latest)
        inv['clean_latest_pointer'] = {k: ptr.get(k) for k in ('date', 'report') if k in ptr}
        rk = ptr.get('report')
        rep = clean_writer.get(client, rk) if isinstance(rk, str) else None
        if rep:
            r = json.loads(rep)
            inv['clean_report'] = {t: {k: v for k, v in tb.items() if k in ('input_rows', 'output_rows')} |
                                   {'removed': {a: b.get('count') if isinstance(b, dict) else b
                                                for a, b in tb.get('removed', {}).items()}}
                                   for t, tb in r.get('tables', {}).items()}
    ins = tables.get('insider_trades')
    if ins is not None and prices is not None and not ins.empty:
        need = {'is_market', 'is_primary', 'needs_review', 'broadcast_date', 'nse_symbol', 'side', 'trade_date_to'}
        if need <= set(ins.columns):
            m = ins[ins['is_market'].fillna(False).astype(bool) & ins['is_primary'].fillna(False).astype(bool)
                    & ~ins['needs_review'].fillna(False).astype(bool)]
            m = m[pd.to_datetime(m['trade_date_to'], errors='coerce') >= pd.Timestamp(PRODUCT_START)]
            inv['forward_windows'] = {}
            for side in ('BUY', 'SELL'):
                sub = m[m['side'].astype(str).str.upper() == side]
                ev = pd.DataFrame({'symbol': sub['nse_symbol'].astype('string').str.upper(),
                                   'signal_date': pd.to_datetime(sub['broadcast_date'], errors='coerce').dt.date})
                inv['forward_windows'][f'insider_open_market_{side.lower()}'] = forward_windows(ev, prices)
            inv['forward_windows']['note'] = ('proxy prices: public adjusted-close table; NSE symbols only; '
                                              'benchmark = median stock; MDE = (1.96+0.84)*sd/sqrt(n), 5% two-sided, 80% power')
    return inv


def to_markdown(inv: dict) -> str:
    L = [f'# Data inventory {inv["run_date"]}', '', '## Bucket', '| prefix | objects | MB |', '|---|---:|---:|']
    for k, v in sorted(inv['bucket_prefixes'].items()):
        L.append(f'| {k} | {v["objects"]:,} | {v["bytes"] / 1e6:,.1f} |')
    L += ['', '## Archive (raw-ish canonical rows)', '| dataset | rows | cols | date min | date max | <2026 | >=2026 | unreadable | RT flagged |',
          '|---|---:|---:|---|---|---:|---:|---:|---:|']
    for k, v in inv['archive'].items():
        if v is None:
            L.append(f'| {k} | none | | | | | | | |')
            continue
        L.append(f'| {k} | {v["rows"]:,} | {v["columns"]} | {v.get("date_min")} | {v.get("date_max")} | '
                 f'{v.get("rows_before_2026", "")} | {v.get("rows_2026_onward", "")} | {v.get("unreadable_dates", "")} | '
                 f'{v.get("intraday_round_trip_flagged")} |')
    L += ['', '## Clean tables', '| table | rows | date min | date max | before 2026 | market | primary | needs_review |',
          '|---|---:|---|---|---:|---:|---:|---:|']
    for k, v in inv['clean'].items():
        if v is None:
            L.append(f'| {k} | none | | | | | | |')
            continue
        L.append(f'| {k} | {v["rows"]:,} | {v.get("date_min", "")} | {v.get("date_max", "")} | {v.get("rows_before_2026", "")} | '
                 f'{v.get("is_market", "")} | {v.get("is_primary", "")} | {v.get("needs_review", "")} |')
    for name, fw in inv.get('forward_windows', {}).items():
        if name == 'note':
            L += ['', f'_{fw}_']
            continue
        L += ['', f'## Forward windows: {name}', f'events {fw["events"]:,}; with price history {fw["with_price_history"]:,}; '
              f'prices to {fw["price_last_date"]}', '', '| horizon (sessions) | complete events | companies | company-months | abnormal sd | MDE (events) | MDE (company-months) |',
              '|---:|---:|---:|---:|---:|---:|---:|']
        for h, r in fw['horizons'].items():
            L.append(f'| {h} | {r["complete_events"]:,} | {r["distinct_companies"]:,} | {r["distinct_company_months"]:,} | '
                     f'{r.get("abnormal_sd", "n/a")} | {r.get("mde_events", "n/a")} | {r.get("mde_company_months", "n/a")} |')
    return '\n'.join(L) + '\n'


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='inventory')
    ap.add_argument('--prices', default='https://github.com/Pareshking/paresh/releases/download/data-latest/nse_long_close.parquet')
    args = ap.parse_args(argv)
    import r2_writer
    client = r2_writer.r2_client()
    prices = load_prices(args.prices) if args.prices else None
    inv = inventory(client, r2_writer.BUCKET, prices, date.today().isoformat())
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'inventory.json').write_text(json.dumps(inv, indent=2, default=str))
    md = to_markdown(inv)
    (out / 'inventory.md').write_text(md)
    print(md)


if __name__ == '__main__':
    main()
