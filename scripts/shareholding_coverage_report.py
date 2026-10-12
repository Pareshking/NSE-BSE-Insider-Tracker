"""Read-only: how complete the shareholding table is (TODO item F).

    python scripts/shareholding_coverage_report.py

Reads clean/current/shareholding.parquet and clean/current/securities.parquet
from R2 and prints: companies in the table, each company's latest quarter,
pledge-file status, and how many listed securities have no shareholding row or
no row for the latest completed quarter. Writes nothing.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

from clean_writer import read_parquet  # noqa: E402
from r2_writer import r2_client  # noqa: E402

from collectors.nse_events.run_daily import shareholding_coverage  # noqa: E402


def latest_completed_quarter(today: pd.Timestamp) -> pd.Timestamp:
    """Latest quarter end whose filing deadline (21 days after quarter end) has passed."""
    q = (today - pd.Timedelta(days=21)) - pd.offsets.QuarterEnd(0)
    return q if q <= today - pd.Timedelta(days=21) else q - pd.offsets.QuarterEnd(1)


def main():
    client = r2_client()
    sh = read_parquet(client, 'clean/current/shareholding.parquet')
    sec = read_parquet(client, 'clean/current/securities.parquet')
    if sh is None or sh.empty:
        print('no shareholding table in R2')
        return
    sh['quarter_end'] = pd.to_datetime(sh['quarter_end'], errors='coerce')
    cov = shareholding_coverage(sh)
    print('table:', {k: v for k, v in cov.items()})
    print(f'rows {len(sh)}; quarters {sh["quarter_end"].min():%Y-%m-%d} to {sh["quarter_end"].max():%Y-%m-%d}')
    target = latest_completed_quarter(pd.Timestamp.now().normalize())
    print(f'latest completed quarter (filing deadline passed): {target:%Y-%m-%d}')
    latest = sh.sort_values('quarter_end').groupby('symbol').tail(1)
    print(f'companies whose latest filing is for that quarter: {(latest["quarter_end"] >= target).sum()} of {len(latest)}')
    print('latest filing quarter, all companies:',
          latest['quarter_end'].dt.strftime('%Y-%m-%d').value_counts().sort_index(ascending=False).head(6).to_dict())
    if sec is not None and not sec.empty and 'isin' in sec.columns:
        isins = set(sec['isin'].dropna().astype(str))
        have = set(sh['isin'].dropna().astype(str))
        have_latest = set(sh.loc[sh['quarter_end'] >= target, 'isin'].dropna().astype(str))
        print(f'securities in the clean securities table: {len(isins)}')
        print(f'  with any shareholding row: {len(isins & have)}; with a row for {target:%Y-%m-%d}: {len(isins & have_latest)}')
        print(f'  without any shareholding row: {len(isins - have)}')
    else:
        print('no securities table to compare against')


if __name__ == '__main__':
    main()
