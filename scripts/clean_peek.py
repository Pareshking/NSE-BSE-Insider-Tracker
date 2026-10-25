"""The clean rows behind a few companies (read-only), for audits: SYMBOLS=comma list of NSE symbols.

For each symbol: its securities and universe rows, every shareholding quarter (holding, pledge, XBRL status,
ISIN), and its pledge filings in insider_trades of the last 120 days with the fields that decide netting.
Prints only; writes nothing to R2, calls no exchange.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from r2_writer import r2_client  # noqa: E402
from clean_writer import read_parquet  # noqa: E402

pd.set_option('display.width', 250)
pd.set_option('display.max_columns', 40)
pd.set_option('display.max_colwidth', 28)


def show(title: str, df: pd.DataFrame, cols: list[str]) -> None:
    print(f'--- {title}: {len(df)} rows')
    if len(df):
        print(df[[c for c in cols if c in df]].to_string(index=False))


def mcap_basis(r2) -> int:
    """market_cap_basis counts of the clean insider and deal tables, with a few BSE-only rows on `shares_x_close`. Read only."""
    for name, date_col in (('insider_trades', 'trade_date_to'), ('deals', 'date')):
        t = read_parquet(r2, f'clean/current/{name}.parquet')
        print(f'--- {name}: {len(t)} rows; market_cap_basis:', t['market_cap_basis'].value_counts(dropna=False).to_dict())
        x = t[t['market_cap_basis'].eq('shares_x_close')]
        print(f'    BSE-only rows on shares_x_close: {len(x)}; with no NSE symbol: {int(x["nse_symbol"].isna().sum())}')
        left = t[t['nse_symbol'].isna()]
        print(f'    rows with no NSE symbol: {len(left)}; of them by basis:', left['market_cap_basis'].value_counts(dropna=False).to_dict())
        cols = [c for c in ('company', date_col, 'value', 'market_cap', 'market_cap_at_trade', 'market_cap_date', 'pct_of_mcap') if c in x]
        if len(x):
            print(x.sort_values('value', ascending=False)[cols].head(8).to_string(index=False))
    return 0


def fund_names(r2) -> int:
    """Institutional client names of the primary, non-market-maker deals, largest total value first, with the manager
    line (if any) each already has: where the next `fund_managers.csv` lines are worth writing. Names only; no write."""
    from insiders_clean import fund_managers
    deals = read_parquet(r2, 'clean/current/deals.parquet')
    d = deals[deals['is_primary'].astype(bool) & ~deals['client_is_market_maker'].astype(bool)]
    d = d[d['client_type'].isin(['mutual_fund', 'fpi', 'insurer', 'pension', 'bank', 'pms_aif', 'fund_other'])]
    g = d.groupby('client_name').agg(value=('value', 'sum'), legs=('value', 'size'), type=('client_type', 'first'))
    g = g.sort_values('value', ascending=False).head(400)
    g['manager'] = [fund_managers.manager_of(n)[0] or '' for n in g.index]
    print(f'--- {len(g)} largest institutional names (Rs Cr total, legs, type, manager line)')
    for n, r in g.iterrows():
        print(f'{r["value"] / 1e7:10.1f} | {int(r["legs"]):4d} | {r["type"]:11s} | {r["manager"]:14s} | {n}')
    return 0


def main() -> int:
    r2 = r2_client()
    syms = [x.strip().upper() for x in os.environ.get('SYMBOLS', '').split(',') if x.strip()]
    if syms == ['MCAP_BASIS']:   # how each row's market cap was dated, and BSE-only examples of the new basis
        return mcap_basis(r2)
    if syms == ['FUND_NAMES']:   # the fund names in the deals with no manager line yet (insiders_clean/fund_managers.csv)
        return fund_names(r2)
    sec = read_parquet(r2, 'clean/current/securities.parquet')
    uni = read_parquet(r2, 'clean/current/universe.parquet')
    sh = read_parquet(r2, 'clean/current/shareholding.parquet')
    tr = read_parquet(r2, 'clean/current/insider_trades.parquet')
    print('shareholding columns:', [c for c in sh.columns if not c.endswith(('_shares', '_pct')) or c.startswith('promoter')])
    print('insider_trades columns:', list(tr.columns))
    for sym in syms:
        print(f'\n===== {sym}')
        s = sec[sec['nse_symbol'].astype(str).str.upper() == sym]
        show('securities', s, ['isin', 'nse_symbol', 'bse_code', 'display_name', 'market_cap'])
        isins = set(s['isin'].dropna())
        if uni is not None and 'isin' in uni:
            show('universe', uni[uni['isin'].isin(isins)], list(uni.columns)[:8])
        q = sh[(sh['symbol'].astype(str).str.upper() == sym) | sh['isin'].isin(isins)]
        show('shareholding', q.sort_values('quarter_end'),
             ['isin', 'symbol', 'quarter_end', 'submission_date', 'promoter_holding_pct', 'promoter_shares', 'total_shares',
              'promoter_pledged_shares', 'promoter_pledge_pct', 'xbrl_status', 'shareholding_stale', 'categories_status'])
        t = tr[tr['isin'].isin(isins) | (tr['nse_symbol'].astype(str).str.upper() == sym)] if 'nse_symbol' in tr else tr[tr['isin'].isin(isins)]
        t = t[t['kind'].astype(str).str.startswith('pledge')] if 'kind' in t else t.iloc[0:0]
        show('pledge filings', t.sort_values('broadcast_date') if 'broadcast_date' in t else t,
             ['broadcast_date', 'exchange', 'is_primary', 'primary_id', 'person_id', 'kind', 'side', 'quantity', 'value',
              'holding_before', 'holding_after', 'trade_date_from', 'trade_date_to', 'app_id', 'source_id', 'mode_raw',
              'transaction_type_raw', 'listed_on'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
