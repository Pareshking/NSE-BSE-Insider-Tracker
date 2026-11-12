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


def mcap_gap(r2) -> int:
    """For the rows with no NSE symbol still on `latest` or `none`: how many have shares in issue on file for a quarter on or before
    the trade, how many have a BSE close within 10 days before the trade, and what the BSE price layer and shareholding hold."""
    import pandas as pd

    from clean_writer import get
    from insiders_clean import day_range, market_cap
    shares = market_cap.shares_frame(read_parquet(r2, 'clean/current/bse_shareholding.parquet'),
                                     read_parquet(r2, 'clean/current/shareholding.parquet'))
    from datetime import date
    closes, info = market_cap.load_bse_closes(lambda k: get(r2, k), day_range.months_between(date(2025, 10, 8), date.today()))
    print('BSE price layer:', {k: v for k, v in info.items() if k != 'months_unreadable'}, 'unreadable:', list(info['months_unreadable']))
    print(f'shares in issue: {len(shares)} rows, {shares["isin"].nunique()} ISINs; BSE closes: {len(closes)} rows, {closes["isin"].nunique()} ISINs, '
          f'{closes["date"].min().date()} to {closes["date"].max().date()}')
    for name, date_col in (('insider_trades', 'trade_date_to'), ('deals', 'date')):
        t = read_parquet(r2, f'clean/current/{name}.parquet')
        x = t[t['nse_symbol'].isna() & t['market_cap_basis'].isin(['latest', 'none'])].copy()
        x['_day'] = pd.to_datetime(x[date_col], errors='coerce').dt.normalize()
        has_isin = x['isin'].notna()
        sh_ok = x.merge(shares.assign(_q=shares['quarter_end']), on='isin', how='left').assign(_ok=lambda d: d['_q'].notna() & (d['_q'] <= d['_day']))
        sh_any = set(shares['isin'])
        cl_any = set(closes['isin'])
        have_sh = sh_ok.groupby(level=0).size().index if False else None
        got_sh = set(sh_ok.loc[sh_ok['_ok'], 'isin'])
        print(f'--- {name}: {len(x)} rows still on latest/none; no ISIN: {int((~has_isin).sum())}; ISIN has any shares: '
              f'{int(x["isin"].isin(sh_any).sum())}; any shares dated on or before the trade: {int(x["isin"].isin(got_sh).sum())}; ISIN has any BSE close: '
              f'{int(x["isin"].isin(cl_any).sum())}; distinct ISINs: {x["isin"].nunique()}, with shares: {len(set(x["isin"]) & sh_any)}, '
              f'with closes: {len(set(x["isin"]) & cl_any)}')
        print('    trade months of those rows:', x['_day'].dt.to_period('M').astype(str).value_counts().sort_index().to_dict())
    return 0


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


def results_quarters(r2) -> int:
    """Rows of clean/current/results per quarter end, consolidated or standalone, with XBRL status ok; and the companies
    whose Sep 2026 quarter has a Sep 2025 quarter in the table (what the Results page's year-ago column needs)."""
    r = read_parquet(r2, 'clean/current/results.parquet')
    if r is None or r.empty:
        print('clean/current/results.parquet: empty or missing')
        return 0
    r = r.assign(_end=pd.to_datetime(r['period_end'], errors='coerce'),
                 _basis=r['consolidated'].astype(str).str.strip().str.lower().str.startswith('consolidated').map({True: 'cons', False: 'stand'}),
                 _ok=r['xbrl_status'].fillna('ok').eq('ok') if 'xbrl_status' in r else True)
    print(f'results rows: {len(r)}; xbrl ok: {int(r["_ok"].sum())}; broadcast from {r["broadcast_at"].min()} to {r["broadcast_at"].max()}')
    q = r[r['_ok']].groupby([r['_end'].dt.to_period('Q'), '_basis']).size().unstack(fill_value=0)
    print(q.tail(12).to_string())
    now = set(r.loc[r['_ok'] & (r['_end'] == '2026-09-30'), 'isin'].dropna())
    ago = set(r.loc[r['_ok'] & (r['_end'] == '2025-09-30'), 'isin'].dropna())
    print(f'companies with a Sep 2026 quarter: {len(now)}; of them with Sep 2025 too: {len(now & ago)}')
    return 0


def deal_days(r2, start: str = '2026-09-28', end: str = '2026-10-16') -> int:
    """TODO item 18: were the 07 and 08 Oct 2026 NSE block deals (blocked that night) written later? Counts per day,
    feed and exchange in the clean deals table, primary rows, market makers included and apart."""
    d = read_parquet(r2, 'clean/current/deals.parquet')
    if d is None or d.empty:
        print('clean/current/deals.parquet: empty or missing')
        return 0
    d = d.assign(_day=pd.to_datetime(d['date'], errors='coerce').dt.normalize())
    w = d[(d['_day'] >= start) & (d['_day'] <= end)]
    print(f'deals {start} to {end}: {len(w)} rows of {len(d)}; columns feeds/exchange/is_primary present:',
          {c: c in d for c in ('feeds', 'exchange', 'is_primary', 'client_is_market_maker')})
    if w.empty:
        return 0
    g = w.assign(primary=w['is_primary'].astype('boolean').fillna(False)).groupby(
        ['_day', 'exchange', 'feeds', 'primary'], dropna=False).size().unstack(['exchange', 'feeds', 'primary'], fill_value=0)
    print(g.to_string())
    return 0


def main() -> int:
    r2 = r2_client()
    syms = [x.strip().upper() for x in os.environ.get('SYMBOLS', '').split(',') if x.strip()]
    if syms == ['MCAP_GAP']:     # why a BSE-only row is still on the latest market cap: no shares, or no BSE close
        return mcap_gap(r2)
    if syms == ['MCAP_BASIS']:   # how each row's market cap was dated, and BSE-only examples of the new basis
        return mcap_basis(r2)
    if syms == ['RESULTS_QUARTERS']:   # results rows per quarter end and basis: how far back the backfill reached
        return results_quarters(r2)
    if syms == ['DEAL_DAYS']:    # TODO 18: bulk and block deals per day and exchange around 07-08 Oct 2026
        return deal_days(r2)
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
