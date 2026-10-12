"""Batch job: the site's price artifacts in R2, so pages never load the full price table. Derived, rewritten each run.

  artifacts/prices_summary_slim.parquet  one row per ISIN: latest close, 52-week range, size bucket
  artifacts/price_history.parquet        adjusted daily closes, last ~400 days, for every ISIN in our filings
  artifacts/market_strip.json            Nifty 500 / Smallcap 250 / Microcap 250: level, vs 200-day average, 1 month
  artifacts/track_events.parquet         every signal event with its forward returns (insiders_clean/track.py)
  artifacts/track_summary.parquet        per signal and horizon: cases, median excess vs Nifty 500, share that beat it
  ledger/forward/<run time>.parquet      forward record: events that fired since the last run, write-once, never edited
  artifacts/forward_outcomes.parquet     every forward-record row with its returns so far (derived, rewritten each run)"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from insiders_clean import slim, track  # noqa: E402
from price_coverage import load_prefix  # noqa: E402

SUMMARY_KEY = 'artifacts/prices_summary_slim.parquet'
HISTORY_KEY, STRIP_KEY = 'artifacts/price_history.parquet', 'artifacts/market_strip.json'
EVENTS_KEY, TRACK_KEY = 'artifacts/track_events.parquet', 'artifacts/track_summary.parquet'
FORWARD_KEY = 'artifacts/forward_outcomes.parquet'


def put(client, bucket, key, df):
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    client.put_object(Bucket=bucket, Key=key, Body=buf.getvalue())


def forward(client, bucket, ev, close, nifty, sized, size_of):
    """Append the events that fired since the last run to the forward record
    (a new write-once file per run), then rewrite the outcomes of every row."""
    ledger = load_prefix(client, bucket, track.LEDGER_PREFIX)
    run_at = pd.Timestamp.now(tz='UTC').tz_localize(None).floor('s')
    new = track.new_ledger_rows(ev, ledger, close, run_at)
    if len(new):
        key = f'{track.LEDGER_PREFIX}{run_at:%Y-%m-%dT%H%M%S}.parquet'
        try:
            client.head_object(Bucket=bucket, Key=key)
            print(f'forward: {key} exists, not overwritten')
            return
        except Exception:  # noqa: BLE001 -- absent: write it
            put(client, bucket, key, new)
        ledger = pd.concat([ledger, new], ignore_index=True)
    print(f'forward: {len(new)} new rows, {len(ledger)} in the record')
    if len(ledger):
        ledger['day'] = pd.to_datetime(ledger['day'])
        put(client, bucket, FORWARD_KEY, track.forward_returns(ledger, close, nifty, sized, size_of))


def main() -> int:
    import r2_writer
    client, bucket = r2_writer.r2_client(), r2_writer.BUCKET
    px = load_prefix(client, bucket, 'prices/daily/')
    px['date'] = pd.to_datetime(px['date'])
    close, _, factors = slim.adjusted_panels(px)
    meta = (px.dropna(subset=['isin']).assign(_nse=lambda d: d['exchange'].eq('NSE')).sort_values(['_nse', 'date'])
            .drop_duplicates('isin', keep='last')[['isin', 'symbol', 'name', 'exchange']])
    mc = load_prefix(client, bucket, 'marketcap/daily/')
    if len(mc):
        mc['date'] = pd.to_datetime(mc['date'])
        mc = mc[mc['date'] == mc['date'].max()]
    summary = slim.price_summary(close, meta, factors, mc if len(mc) else None)
    put(client, bucket, SUMMARY_KEY, summary)
    print(f'slim: isins {len(summary)}, with bucket {int(summary["mcap_bucket"].notna().sum())}, last session {close.index.max():%Y-%m-%d}')
    clean = {}
    for table in ('insider_trades', 'deals'):
        try:
            clean[table] = pd.read_parquet(io.BytesIO(
                client.get_object(Bucket=bucket, Key=f'clean/current/{table}.parquet')['Body'].read()))
        except Exception as e:  # noqa: BLE001 -- a missing clean table means no lines for it, not a failed run
            print(f'history: {table} not read ({e})')
    isins = set().union(*(set(t['isin'].dropna()) for t in clean.values())) if clean else set()
    hist = slim.price_history(close, isins)
    put(client, bucket, HISTORY_KEY, hist)
    print(f'history: isins {hist["isin"].nunique()} of {len(isins)} in filings, rows {len(hist)}')
    ix = load_prefix(client, bucket, 'indices/daily/nse/')
    if len(ix):
        ix['date'] = pd.to_datetime(ix['date'])
        strip = slim.market_strip(ix)
        client.put_object(Bucket=bucket, Key=STRIP_KEY, Body=json.dumps(strip).encode())
        print(f'strip: {strip}')
        nifty = ix[ix['symbol'] == 'Nifty 500'].drop_duplicates('date').set_index('date')['close'].sort_index()
        if 'insider_trades' in clean and len(nifty):
            ev = track.events(clean['insider_trades'], clean.get('deals'), close)
            sized = {name: ix[ix['symbol'] == name].drop_duplicates('date').set_index('date')['close'].sort_index()
                     for name in track.SIZE_INDEX.values()}
            sized = {k: v for k, v in sized.items() if len(v)}
            print(f'track: size-matched indices found {sorted(sized)}; missing {sorted(set(track.SIZE_INDEX.values()) - set(sized))}')
            size_of = summary.dropna(subset=['mcap_bucket']).set_index('isin')['mcap_bucket'].to_dict()
            fr = track.forward_returns(ev, close, nifty, sized, size_of)
            put(client, bucket, EVENTS_KEY, fr)
            summ = track.summary(fr)
            put(client, bucket, TRACK_KEY, summ)
            forward(client, bucket, ev, close, nifty, sized, size_of)
            print(f'track: events {len(fr)}; ' + '; '.join(
                f"{r.signal} {r.horizon} n={r.cases} med={r.median_excess:+.2f}" for r in summ.itertuples() if r.horizon == '1M'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
