"""Batch job: write artifacts/prices_summary_slim.parquet to R2 (one row per ISIN, see insiders_clean/slim.py), so
the site never loads the full price table. Derived and rewritten each run."""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from insiders_clean import slim  # noqa: E402
from price_coverage import load_prefix  # noqa: E402

SUMMARY_KEY = 'artifacts/prices_summary_slim.parquet'


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
    return 0


if __name__ == '__main__':
    sys.exit(main())
