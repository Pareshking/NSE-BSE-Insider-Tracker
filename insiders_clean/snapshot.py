"""The company snapshot: one row per company with what every list and page needs at a glance (design V3, owner 23 Oct).

Built by the nightly precompute (scripts/precompute_slim.py) into `artifacts/company_snapshot.parquet`, so a page joins
this one small table instead of the price summary, the shareholding table and the insider table on every rerun
(Streamlit Cloud's memory). Rules, all documented in docs/DATA_DICTIONARY.md:

* Market: the price summary's latest close, 52-week range, market cap and size bucket, plus where the close sits in the
  range (0 at the low, 100 at the high).
* Ownership: the latest quarter that has each figure (promoter holding, pledge, and the share held by mutual funds,
  foreign portfolio investors, insurers, AIFs and retail), and its change in points from the quarter before. A change
  is blank when the two quarters are more than CHANGE_MAX_DAYS apart: a year-old filing is not "last quarter".
* Insiders: open-market buys and sells by decision-makers (promoter, promoter group, director, KMP; never designated
  persons) made public in the last INSIDER_DAYS days, and the dates of the latest buy and sale. Token buys are left out
  of buying, as everywhere (signals.eligible).
* Only companies of the study universe when it is given; nothing is invented: a figure the data lacks is blank.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import signals

INSIDER_DAYS = 90
CHANGE_MAX_DAYS = 120           # two quarters further apart than this give no "change since last quarter"
HOLDERS = {'promoter_holding_pct': 'promoter', 'promoter_pledge_pct': 'pledge', 'mf_pct': 'mf', 'fpi_pct': 'fpi',
           'insurance_pct': 'insurance', 'aif_pct': 'aif', 'retail_pct': 'retail'}
COLUMNS = (['isin', 'symbol', 'company', 'price_date', 'latest_close', 'high_52w', 'low_52w', 'pct_off_high', 'range_pos',
            'ret_90d', 'market_cap', 'mcap_bucket']
           + [f'{n}{s}' for n in HOLDERS.values() for s in ('', '_change_pts', '_quarter')]
           + ['insider_buy_90d', 'insider_sell_90d', 'insider_net_90d', 'promoter_buy_90d', 'promoter_sell_90d',
              'last_insider_buy', 'last_insider_sell'])


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=COLUMNS)


def _holders(sh: pd.DataFrame | None) -> pd.DataFrame:
    """isin -> for each figure: the latest value, the quarter it is from and the change from the quarter before."""
    if sh is None or sh.empty or 'isin' not in sh or 'quarter_end' not in sh:
        return pd.DataFrame()
    base = sh.assign(quarter_end=pd.to_datetime(sh['quarter_end'], errors='coerce')).dropna(subset=['isin', 'quarter_end'])
    out = {}
    for col, name in HOLDERS.items():
        if col not in base:
            continue
        s = base[['isin', 'quarter_end', col]].assign(**{col: pd.to_numeric(base[col], errors='coerce')}).dropna(subset=[col])
        if s.empty:
            continue
        s = s.sort_values(['isin', 'quarter_end'], kind='stable').drop_duplicates(['isin', 'quarter_end'], keep='last')
        s['_k'] = s.groupby('isin').cumcount(ascending=False)
        last, prev = s[s['_k'] == 0].set_index('isin'), s[s['_k'] == 1].set_index('isin')
        gap = (last['quarter_end'] - prev['quarter_end'].reindex(last.index)).dt.days
        change = (last[col] - prev[col].reindex(last.index)).where(gap.le(CHANGE_MAX_DAYS))
        out[name] = last[col]
        out[f'{name}_change_pts'] = change
        out[f'{name}_quarter'] = last['quarter_end']
    return pd.DataFrame(out)


def _insiders(trades: pd.DataFrame | None, ref: pd.Timestamp | None, days: int) -> pd.DataFrame:
    if trades is None or trades.empty or ref is None:
        return pd.DataFrame()
    t = signals.eligible(trades)
    t = t[t['person_role'].isin(signals.DECISION_ROLES) & t['seen'].notna() & t['seen'].le(ref + pd.Timedelta(days=1))
          & t['isin'].notna()]
    if t.empty:
        return pd.DataFrame()
    buy = t[t['side'].eq('BUY') & ~t['is_token'].astype(bool)]
    sell = t[t['side'].eq('SELL')]
    win = lambda x: x[x['seen'] > ref - pd.Timedelta(days=days)]   # noqa: E731
    total = lambda x: x.groupby('isin')['value'].sum()             # noqa: E731
    promoter = lambda x: total(win(x)[win(x)['person_role'].isin(signals.PROMOTER_ROLES)])   # noqa: E731
    out = pd.DataFrame({'insider_buy_90d': total(win(buy)), 'insider_sell_90d': total(win(sell)),
                        'promoter_buy_90d': promoter(buy), 'promoter_sell_90d': promoter(sell),
                        'last_insider_buy': buy.groupby('isin')['seen'].max().dt.normalize(),
                        'last_insider_sell': sell.groupby('isin')['seen'].max().dt.normalize()})
    for c in ('insider_buy_90d', 'insider_sell_90d', 'promoter_buy_90d', 'promoter_sell_90d'):
        out[c] = out[c].fillna(0.0)
    out['insider_net_90d'] = out['insider_buy_90d'] - out['insider_sell_90d']
    return out


def build(summary: pd.DataFrame | None, shareholding: pd.DataFrame | None = None, trades: pd.DataFrame | None = None,
          universe: set | None = None, names: dict | None = None, ref: pd.Timestamp | None = None,
          days: int = INSIDER_DAYS) -> pd.DataFrame:
    """The snapshot, one row per ISIN of `summary` (the price summary), largest market cap first. `universe`: the ISINs
    of the study universe, or None for all; `names`: isin -> display name; `ref`: the data's as-of day (default: the
    latest broadcast date of `trades`, signals.as_of)."""
    if summary is None or summary.empty:
        return _empty()
    s = summary.drop_duplicates('isin')
    if universe is not None:
        s = s[s['isin'].isin(universe)]
    if s.empty:
        return _empty()
    ref = ref if ref is not None else signals.as_of(trades)
    out = s[['isin']].copy().set_index('isin')
    for col, src in (('symbol', 'symbol'), ('price_date', 'last_date'), ('latest_close', 'latest_close'),
                     ('high_52w', 'high_52w'), ('low_52w', 'low_52w'), ('pct_off_high', 'pct_off_high'),
                     ('ret_90d', 'ret_90d'), ('market_cap', 'market_cap'), ('mcap_bucket', 'mcap_bucket')):
        out[col] = s.set_index('isin')[src] if src in s else np.nan
    named = s.set_index('isin')['name'] if 'name' in s else pd.Series(index=out.index, dtype=object)
    out['company'] = pd.Series(names or {}).reindex(out.index).fillna(named)
    span = out['high_52w'] - out['low_52w']
    out['range_pos'] = ((out['latest_close'] - out['low_52w']) / span * 100).where(span.gt(0)).clip(0, 100)
    out = out.join(_holders(shareholding))
    ins = _insiders(trades, ref, days)
    if not ins.empty:   # the insider table covers every company: none in it is a true zero, not a blank
        flows = ['insider_buy_90d', 'insider_sell_90d', 'insider_net_90d', 'promoter_buy_90d', 'promoter_sell_90d']
        out = out.join(ins)
        out[flows] = out[flows].fillna(0.0)
    out = out.reset_index().reindex(columns=COLUMNS)
    return out.sort_values('market_cap', ascending=False, na_position='last', kind='stable').reset_index(drop=True)
