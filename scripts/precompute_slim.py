"""Batch job: the site's price artifacts in R2, so pages never load the full price table. Derived, rewritten each run.

  artifacts/prices_summary_slim.parquet  one row per ISIN: latest close, 52-week range, size bucket
  artifacts/price_history.parquet        adjusted daily closes, last ~400 days, for every ISIN in our filings
  artifacts/market_strip.json            Nifty 500 / Smallcap 250 / Microcap 250: level, vs 200-day average, 1 month"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from insiders_clean import slim  # noqa: E402
from price_coverage import load_prefix  # noqa: E402

SUMMARY_KEY = 'artifacts/prices_summary_slim.parquet'
HISTORY_KEY, STRIP_KEY = 'artifacts/price_history.parquet', 'artifacts/market_strip.json'


def put(client, bucket, key, df):
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    client.put_object(Bucket=bucket, Key=key, Body=buf.getvalue())


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
    isins = set()
    for table in ('insider_trades', 'deals'):
        try:
            body = client.get_object(Bucket=bucket, Key=f'clean/current/{table}.parquet')['Body'].read()
            isins |= set(pd.read_parquet(io.BytesIO(body), columns=['isin'])['isin'].dropna())
        except Exception as e:  # noqa: BLE001 -- a missing clean table means no lines for it, not a failed run
            print(f'history: {table} not read ({e})')
    hist = slim.price_history(close, isins)
    put(client, bucket, HISTORY_KEY, hist)
    print(f'history: isins {hist["isin"].nunique()} of {len(isins)} in filings, rows {len(hist)}')
    ix = load_prefix(client, bucket, 'indices/daily/nse/')
    if len(ix):
        ix['date'] = pd.to_datetime(ix['date'])
        strip = slim.market_strip(ix)
        client.put_object(Bucket=bucket, Key=STRIP_KEY, Body=json.dumps(strip).encode())
        print(f'strip: {strip}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
