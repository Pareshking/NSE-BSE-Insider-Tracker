"""Read-only: what the stored rights and preferential issue data really looks like.

    python scripts/sample_issue_data.py

For NSE and BSE, rights_issue and preferential_issue: the newest canonical file
in R2, its row count, every column with its type and how often it is filled,
the distinct values of short text columns (stages, allottee categories), and a
few example rows. Writes nothing. Used to decide the cleaning rules from the
data instead of from guesses (docs/TODO.md item H).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

from clean_writer import list_keys, read_parquet  # noqa: E402
from r2_writer import r2_client  # noqa: E402

CATEGORIES = ('rights_issue', 'preferential_issue')
EXCHANGES = ('nse', 'bse')
MAX_DISTINCT = 12


def newest_key(client, exchange, category):
    keys = [k for k in list_keys(client, f'canonical/{exchange}/{category}/') if k.endswith('data.parquet')]
    return max(keys) if keys else None


def describe(df: pd.DataFrame) -> list[str]:
    lines = []
    for col in df.columns:
        s = df[col]
        filled = s.notna() & s.astype(str).str.strip().ne('') & s.astype(str).ne('None')
        line = f'  {col:38s} {str(s.dtype):10s} filled {filled.mean() * 100:5.1f}%'
        vals = s[filled].astype(str)
        n = vals.nunique()
        if 0 < n <= MAX_DISTINCT and vals.str.len().max() <= 40:
            line += '  values: ' + ', '.join(f'{k} ({v})' for k, v in vals.value_counts().items())
        lines.append(line)
    return lines


def main():
    client = r2_client()
    for exchange in EXCHANGES:
        for category in CATEGORIES:
            print(f'\n===== {exchange} {category} =====')
            key = newest_key(client, exchange, category)
            if not key:
                print('  no canonical file in R2')
                continue
            df = read_parquet(client, key)
            print(f'  {key}: {len(df)} rows, {len(df.columns)} columns')
            for line in describe(df):
                print(line)
            sample = df.head(2).T
            print('  -- two example rows (column: value) --')
            for col, row in sample.iterrows():
                print(f'  {col}: ' + ' | '.join(str(v)[:90] for v in row.tolist()))


if __name__ == '__main__':
    main()
