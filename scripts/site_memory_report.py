"""How much memory the site's data takes (read-only: lists and reads R2, writes nothing).

For every object the site loads (clean/current/*.parquet, artifacts/*), prints
the stored size, rows, columns and in-memory size after pd.read_parquet, plus
the heaviest columns. Also sizes price_history() the way store.py builds it.
Markdown table to stdout and to $GITHUB_STEP_SUMMARY when set.
"""
from __future__ import annotations

import io
import os
import sys

import boto3
import numpy as np
import pandas as pd

PREFIXES = ('clean/current/', 'artifacts/', 'clean/latest.json')
MB = 1024 ** 2


def client():
    return boto3.client(
        's3',
        endpoint_url=f"https://{os.environ['CLOUDFLARE_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ['R2_ACCESS_KEY_ID'],
        aws_secret_access_key=os.environ['R2_SECRET_ACCESS_KEY'],
        region_name='auto',
    )


def objects(c, bucket):
    pages = c.get_paginator('list_objects_v2')
    for prefix in PREFIXES:
        for page in pages.paginate(Bucket=bucket, Prefix=prefix):
            for o in page.get('Contents', []):
                yield o['Key'], o['Size']


def price_history_mb(df: pd.DataFrame) -> float:
    """Same shape as store.price_history(): ISIN -> (dates, closes) arrays."""
    df = df.copy()
    df['date'] = pd.to_datetime(df['date'])
    total = 0
    for isin, g in df.groupby('isin', sort=False):
        total += g['date'].to_numpy().nbytes + g['close'].to_numpy(dtype='float64').nbytes
        total += sys.getsizeof(isin) + 2 * 112 + 64   # key, two ndarray headers, tuple
    return total / MB


def main() -> None:
    c, bucket = client(), os.environ['R2_BUCKET_NAME']
    rows, notes = [], []
    for key, size in sorted(objects(c, bucket)):
        if not key.endswith('.parquet'):
            rows.append((key, size / MB, None, None, None, ''))
            continue
        body = c.get_object(Bucket=bucket, Key=key)['Body'].read()
        df = pd.read_parquet(io.BytesIO(body))
        mem = df.memory_usage(deep=True, index=True)
        top = mem.drop('Index', errors='ignore').sort_values(ascending=False).head(4)
        heavy = ', '.join(f'{k} {v / MB:.1f}' for k, v in top.items())
        rows.append((key, size / MB, len(df), df.shape[1], mem.sum() / MB, heavy))
        if key == 'artifacts/price_history.parquet' and {'isin', 'date', 'close'} <= set(df.columns):
            notes.append(f'price_history() dict as built by store.py: about {price_history_mb(df):.1f} MB '
                         f'({df["isin"].nunique()} ISINs)')
        del df, body

    parquet = [r for r in rows if r[4] is not None]
    out = ['### Site data in R2 (read-only measurement)', '',
           '| object | stored MB | rows | cols | in memory MB | heaviest columns (MB) |',
           '|---|---:|---:|---:|---:|---|']
    for key, mb, n, cols, mem, heavy in sorted(rows, key=lambda r: -(r[4] or 0)):
        out.append(f'| `{key}` | {mb:.2f} | {n if n is not None else ""} | {cols if cols is not None else ""} | '
                   f'{f"{mem:.1f}" if mem is not None else ""} | {heavy} |')
    out += ['', f'**Total in memory (all parquet, one copy each): {sum(r[4] for r in parquet):.1f} MB** '
                f'from {sum(r[1] for r in parquet):.1f} MB stored, {len(parquet)} parquet objects.']
    out += [f'- {n}' for n in notes]
    text = '\n'.join(out) + '\n'
    print(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as f:
            f.write(text)


if __name__ == '__main__':
    main()
