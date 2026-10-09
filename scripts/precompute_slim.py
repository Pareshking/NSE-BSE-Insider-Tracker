"""Batch job: write the slim app artifacts to R2 so Streamlit pages never load the full price table.

  artifacts/prices_summary_slim.parquet  one row per ISIN (see insiders_clean/slim.py)
  ledger/ledger_marks.parquet            the forward ledger marked to the latest session (insiders_clean.ledger.mark)

Both are derived and rewritten each run; the append-only ledger itself (ledger/forward_ledger.parquet) is only read.
Aggregate output only (public repo)."""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from insiders_clean import ledger as lg, slim  # noqa: E402
from insiders_clean.index_close import BASELINE  # noqa: E402
from price_coverage import load_prefix  # noqa: E402

SUMMARY_KEY, MARKS_KEY = 'artifacts/prices_summary_slim.parquet', 'ledger/ledger_marks.parquet'


def put(client, bucket, key, df):
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    client.put_object(Bucket=bucket, Key=key, Body=buf.getvalue())


def main() -> int:
    import r2_writer
    client, bucket = r2_writer.r2_client(), r2_writer.BUCKET
    px = load_prefix(client, bucket, 'prices/daily/')
    px['date'] = pd.to_datetime(px['date'])
    close, open_, factors = slim.adjusted_panels(px)
    meta = (px.dropna(subset=['isin']).assign(_nse=lambda d: d['exchange'].eq('NSE')).sort_values(['_nse', 'date'])
            .drop_duplicates('isin', keep='last')[['isin', 'symbol', 'name', 'exchange']])
    mc = load_prefix(client, bucket, 'marketcap/daily/')
    if len(mc):
        mc['date'] = pd.to_datetime(mc['date'])
        mc = mc[mc['date'] == mc['date'].max()]
    summary = slim.price_summary(close, meta, factors, mc if len(mc) else None)
    put(client, bucket, SUMMARY_KEY, summary)
    print(f'slim: isins {len(summary)}, with bucket {int(summary["mcap_bucket"].notna().sum())}, last session {close.index.max():%Y-%m-%d}')
    try:
        led = pd.read_parquet(io.BytesIO(client.get_object(Bucket=bucket, Key='ledger/forward_ledger.parquet')['Body'].read()))
    except Exception as e:  # noqa: BLE001
        if 'NoSuchKey' not in str(e) and '404' not in str(e):
            raise
        print('marks: no ledger yet, nothing written')
        return 0
    ix = pd.concat([pd.read_parquet(io.BytesIO(client.get_object(Bucket=bucket, Key=k)['Body'].read()))
                    for k in sorted(o['Key'] for p in client.get_paginator('list_objects_v2').paginate(Bucket=bucket, Prefix='indices/daily/nse/')
                                    for o in p.get('Contents', []))])
    ix['date'] = pd.to_datetime(ix['date'])
    nifty = ix[ix['symbol'] == BASELINE].drop_duplicates('date').set_index('date')['close'].sort_index()
    marks = lg.mark(led, close, open_, nifty)
    put(client, bucket, MARKS_KEY, marks)
    print(f'marks: signals {len(marks)}, matured at 60 sessions {int(marks["ret_60"].notna().sum())}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
