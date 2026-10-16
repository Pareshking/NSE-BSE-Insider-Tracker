"""Small real sample before the context engine is built (read-only): what clean/current/results.parquet holds and whether
the last four quarters' revenue and profit of a company can be summed from it. Prints the columns, the rows per company, and
for ten companies the four quarters it would use. Reads R2 only; no model, no exchange, no write."""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from r2_writer import BUCKET, r2_client  # noqa: E402


def main():
    r2 = r2_client()
    df = pd.read_parquet(io.BytesIO(r2.get_object(Bucket=BUCKET, Key='clean/current/results.parquet')['Body'].read()))
    print(f'## results.parquet: {len(df):,} rows, {df["isin"].nunique():,} companies\n')
    print('columns:', ', '.join(f'{c}:{df[c].dtype}' for c in df.columns[:60]), '\n')
    for c in ('xbrl_status', 'kind', 'consolidated', 'period_type', 'reporting_quarter', 'revision'):
        if c in df:
            print(f'{c}:', df[c].astype(str).value_counts().head(8).to_dict())
    ok = df[df['xbrl_status'].astype(str).eq('ok')] if 'xbrl_status' in df else df
    ok = ok.assign(period_end=pd.to_datetime(ok['period_end'], errors='coerce'))
    print(f'\nrows with xbrl ok: {len(ok):,}; period_end from {ok["period_end"].min()} to {ok["period_end"].max()}')
    per = ok.groupby('isin')['period_end'].nunique()
    print('quarters per company (distinct period_end):', per.describe().round(1).to_dict(), '; with 4 or more:', int((per >= 4).sum()))
    cols = [c for c in ('quarter_revenue', 'quarter_total_income', 'quarter_profit', 'ytd_revenue', 'ytd_profit') if c in ok]
    sample = ok[ok['isin'].isin(per[per >= 4].index[:10])].sort_values(['isin', 'period_end'])
    for isin, g in sample.groupby('isin'):
        print(f'\n{isin} {g["symbol"].iloc[-1]}')
        print(g[['period_end', 'consolidated', 'period_type', 'revision'] + cols].tail(8).to_string(index=False))


if __name__ == '__main__':
    main()
