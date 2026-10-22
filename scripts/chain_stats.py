"""What is really in each clean table (read-only), for the data chain audit of 22 Oct 2026.

For every table: rows, the blank rate of its key columns, and the value counts of the columns that decide
how a row is read (kind, mode as filed, side, role, client type, instrument, status, checks). Prints only;
writes nothing to R2, calls no exchange.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from r2_writer import r2_client  # noqa: E402
from clean_writer import read_parquet  # noqa: E402

pd.set_option('display.width', 220)
pd.set_option('display.max_colwidth', 60)

TABLES = {
    'insider_trades': (['isin', 'person_id', 'person_role', 'side', 'kind', 'quantity', 'value', 'price', 'trade_date_to',
                        'broadcast_date', 'holding_before', 'holding_after', 'market_cap_at_trade', 'pct_of_mcap'],
                       ['exchange', 'is_primary', 'kind', 'side', 'person_role', 'mode_raw', 'transaction_type_raw', 'person_category_raw',
                        'price_check', 'holding_check', 'flags', 'marks', 'needs_review', 'market_cap_basis', 'is_market', 'insider_filed_late']),
    'deals': (['isin', 'client_id', 'side', 'quantity', 'price', 'value', 'pct_of_mcap'],
              ['exchange', 'deal_type', 'side', 'client_type', 'client_is_market_maker', 'is_primary', 'flags']),
    'sast': (['isin', 'acquirer_name', 'pct_acquired', 'pct_sold', 'post_stake_pct'],
             ['is_promoter', 'regulation', 'action_type', 'mode', 'instrument']),
    'bse_sast': (['isin', 'acquirer_name'], ['is_promoter', 'regulation', 'mode']),
    'shareholding': (['isin', 'promoter_holding_pct', 'promoter_shares', 'total_shares', 'promoter_pledge_pct'],
                     ['xbrl_status', 'members_status', 'members_check', 'categories_status', 'categories_check', 'no_promoter_group',
                      'shareholding_stale']),
    'bse_shareholding': (['isin', 'promoter_holding_pct', 'total_shares'], ['xbrl_status', 'categories_check']),
    'preferential': (['isin', 'amount_total', 'amount_raised', 'offer_price', 'shares_allotted'],
                     ['stage', 'status', 'allottee_category', 'link_status', 'amount_unreliable', 'instruments']),
    'rights': (['isin', 'offer_price', 'amount_raised'], ['stage', 'amount_unreliable']),
    'qip': (['isin', 'issue_price', 'amount_raised'], ['stage', 'amount_unreliable']),
    'actions': (['isin', 'ex_date', 'ratio'], ['purpose', 'needs_price_gap']),
    'meetings': (['isin', 'meeting_date'], ['results', 'dividend', 'buyback', 'fund_raising']),
    'results': (['isin', 'period_end', 'quarter_revenue', 'quarter_profit', 'ytd_revenue'],
                ['xbrl_status', 'consolidated', 'period_type', 'audited', 'rounding']),
    'buybacks': (['isin', 'offer_price', 'offer_value'], ['route', 'status']),
    'tradability': (['isin'], ['series', 'asm_stage', 'gsm_stage', 'esm_stage', 'is_t2t', 'band']),
    'securities': (['isin', 'nse_symbol', 'bse_code', 'market_cap', 'sector'], ['mcap_category', 'is_sme', 'bse_group']),
    'universe': (['isin', 'market_cap'], ['in_universe', 'why']),
}


def main() -> int:
    r2 = r2_client()
    for name, (keys, cats) in TABLES.items():
        df = read_parquet(r2, f'clean/current/{name}.parquet')
        print(f'\n################ {name}')
        if df is None or df.empty:
            print('  (missing or empty)')
            continue
        print(f'  rows {len(df):,}  columns {len(df.columns)}')
        blank = {c: f'{df[c].isna().mean() * 100:.1f}%' for c in keys if c in df}
        print('  blank:', blank)
        for c in cats:
            if c not in df:
                continue
            vc = df[c].astype(str).value_counts(dropna=False).head(25)
            print(f'  -- {c} ({df[c].nunique(dropna=False)} values)')
            print('     ' + vc.to_string().replace('\n', '\n     '))
        if name == 'insider_trades':
            prim = df[df['is_primary'].astype('boolean').fillna(False)]
            print('  -- kind x side (primary rows)')
            print('     ' + pd.crosstab(prim['kind'].astype(str), prim['side'].astype(str)).to_string().replace('\n', '\n     '))
            v = pd.to_numeric(prim['value'], errors='coerce')
            print('  -- value quantiles (primary):', v.quantile([.01, .1, .5, .9, .99, .999]).round(0).to_dict(), 'max', v.max())
            p = pd.to_numeric(prim['pct_of_mcap'], errors='coerce')
            print('  -- pct_of_mcap > 5%:', int((p > 5).sum()), '  > 25%:', int((p > 25).sum()))
            print('  -- market buys by role (primary, market):')
            mk = prim[prim['is_market'].astype('boolean').fillna(False)]
            print('     ' + pd.crosstab(mk['person_role'].astype(str), mk['side'].astype(str)).to_string().replace('\n', '\n     '))
            big = prim.assign(_v=v).sort_values('_v', ascending=False).head(15)
            print('  -- 15 largest values (primary)')
            print('     ' + big[[c for c in ('company', 'person_name', 'person_role', 'kind', 'side', 'mode_raw', 'quantity', 'price', 'value',
                                            'pct_of_mcap', 'trade_date_to') if c in big]].to_string(index=False).replace('\n', '\n     '))
        if name == 'deals':
            v = pd.to_numeric(df['value'], errors='coerce')
            print('  -- value quantiles:', v.quantile([.01, .5, .99, .999]).round(0).to_dict())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
