"""Investors (design V3, owner 23 Oct): what mutual funds, foreign investors, insurers, AIFs and other large investors
bought and sold in bulk and block deals, per investor, per type and per company.

* Real deals only: primary legs (NSE and BSE legs are separate executions, both counted), market makers and trading
  firms out, an unmatched security out. The type of an investor comes from its name only (participants.py), so each
  row carries the confidence of that reading.
* One investor is one `investor_group` of the curated alias list (the same investor under different spellings), never a
  fund family: nine funds of one manager are nine investors here and one manager in `by_manager`.
* Net is buying minus selling in rupees over the period; the largest position is the company with the largest net
  either way and its share of the company (the deals' % of market cap at the trade date, summed). A row is listed at
  FLOOR_NET rupees net or FLOOR_PCT of a company (Today's gates). Gross buying and selling are shown beside the net:
  a Rs 500 Cr in and Rs 495 Cr out is not a Rs 5 Cr net. Bulk and block deals are a small part of fund flows: every
  table says so.
"""
from __future__ import annotations

import pandas as pd

from . import signals

FLOOR_NET = 25e7         # Rs 25 crore net: the gate of Today's insider rows (a Rs 5 Cr floor let FPI noise in large caps through)
FLOOR_PCT = 0.25         # % of one company, as ideas.FUND_NET_PCT
CONFIDENCE_RANK = {'high': 2, 'medium': 1, 'low': 0}
COLUMNS = ['investor_id', 'investor', 'type', 'confidence', 'names', 'n_names', 'buy', 'sell', 'net', 'companies',
           'largest_company', 'largest_symbol', 'largest_net', 'largest_pct', 'last']


def real_deals(deals: pd.DataFrame | None, ref: pd.Timestamp | None, days: int, types=None) -> pd.DataFrame:
    """The deals of the period that count: primary, not a market maker, a security we know, an institution of one of
    `types` (default signals.FUND_TYPES; None keeps every type when `types` is the string 'all')."""
    if deals is None or deals.empty:
        return pd.DataFrame()
    d = deals
    d = d[d['is_primary'].astype('boolean').fillna(False)]
    if 'client_is_market_maker' in d:
        d = d[~d['client_is_market_maker'].astype('boolean').fillna(False)]
    d = d.assign(date=pd.to_datetime(d['date'], errors='coerce')).dropna(subset=['date', 'isin'])
    if d.empty:
        return d
    ref = ref if ref is not None else d['date'].max()
    d = d[(d['date'] <= ref + pd.Timedelta(days=1)) & (d['date'] > ref - pd.Timedelta(days=days))]
    if types != 'all' and 'client_type' in d:
        d = d[d['client_type'].isin(signals.FUND_TYPES if types is None else types)]
    return d


def _investor_key(d: pd.DataFrame) -> pd.Series:
    own = d['investor_group_id'] if 'investor_group_id' in d else pd.Series(None, index=d.index, dtype=object)
    return own.where(own.notna(), d['client_id'])


def net_by_investor(deals: pd.DataFrame | None, ref: pd.Timestamp | None = None, days: int = 30, types=None) -> pd.DataFrame:
    """One row per investor with its net buying or selling in the period (see the module note), largest absolute net
    first. Unfloored: the page applies `floored`."""
    d = real_deals(deals, ref, days, types)
    if d.empty:
        return pd.DataFrame(columns=COLUMNS)
    d = d.assign(_key=_investor_key(d), _v=pd.to_numeric(d['signed_value'], errors='coerce'),
                 _abs=pd.to_numeric(d['value'], errors='coerce'),
                 _p=pd.to_numeric(d['pct_of_mcap'], errors='coerce') * d['side'].map({'BUY': 1, 'SELL': -1}))
    d = d.dropna(subset=['_key', '_v'])
    shown = d['investor_group'] if 'investor_group' in d else d['client_name']
    d['_name'] = shown.where(shown.notna(), d['client_name'])
    per = d.groupby(['_key', 'isin'], sort=False).agg(company=('company', 'last'), symbol=('nse_symbol', 'last'),
                                                      net=('_v', 'sum'), pct=('_p', 'sum')).reset_index()
    top = per.loc[per.groupby('_key')['net'].apply(lambda s: s.abs().idxmax())].set_index('_key')
    g = d.groupby('_key', sort=False)
    big = d.sort_values('_abs', ascending=False).drop_duplicates('_key').set_index('_key')   # the largest deal sets the type
    out = pd.DataFrame({
        'investor': g['_name'].agg(lambda s: s.mode().iloc[0]),
        'type': big['client_type'] if 'client_type' in big else None,
        'confidence': big['client_type_confidence'] if 'client_type_confidence' in big else None,
        'names': g['client_name'].agg(lambda s: sorted(set(s.dropna()))),
        'buy': d[d['side'].eq('BUY')].groupby('_key')['_abs'].sum(),
        'sell': d[d['side'].eq('SELL')].groupby('_key')['_abs'].sum(),
        'companies': g['isin'].nunique(),
        'largest_company': top['company'], 'largest_symbol': top['symbol'], 'largest_net': top['net'],
        'largest_pct': top['pct'], 'last': g['date'].max().dt.normalize()})
    out[['buy', 'sell']] = out[['buy', 'sell']].fillna(0.0)
    out['net'] = out['buy'] - out['sell']
    out['n_names'] = out['names'].map(len)
    out = out.reset_index().rename(columns={'_key': 'investor_id'})[COLUMNS]
    return out.reindex(out['net'].abs().sort_values(ascending=False, kind='stable').index).reset_index(drop=True)


def floored(df: pd.DataFrame) -> pd.DataFrame:
    """The rows worth listing: Rs 25 crore net, or a quarter of a percent of one company."""
    if df.empty:
        return df
    return df[(df['net'].abs() >= FLOOR_NET) | (df['largest_pct'].abs() >= FLOOR_PCT)].reset_index(drop=True)


def split_confidence(df: pd.DataFrame, include_low: bool = False) -> tuple[pd.DataFrame, int]:
    """(rows, how many were left out): a type read from the name with LOW confidence stays out of the default view and is
    counted, so the page says what it did not list."""
    if df.empty or include_low or 'confidence' not in df:
        return df, 0
    keep = df['confidence'].map(CONFIDENCE_RANK).fillna(0).ge(CONFIDENCE_RANK['medium'])
    return df[keep].reset_index(drop=True), int((~keep).sum())


def buyers_sellers(df: pd.DataFrame, n: int = 10, by: str = 'value') -> tuple[pd.DataFrame, pd.DataFrame]:
    """(net buyers, net sellers), each at most `n` rows: by net rupees, or by the share of the largest company."""
    if df.empty:
        return df, df
    key = (lambda x: x['net'].abs()) if by == 'value' else (lambda x: x['largest_pct'].abs())
    buy, sell = df[df['net'] > 0], df[df['net'] < 0]
    pick = lambda x: x.reindex(key(x).sort_values(ascending=False, kind='stable').index).head(n).reset_index(drop=True)  # noqa: E731
    return pick(buy), pick(sell)


def by_type(deals: pd.DataFrame | None, ref: pd.Timestamp | None = None, days: int = 30) -> pd.DataFrame:
    """Net rupees and the number of investors per type, every institution type (not only the default ones)."""
    inv = net_by_investor(deals, ref, days, types=sorted(signals.FUND_TYPES))
    if inv.empty:
        return pd.DataFrame(columns=['type', 'net', 'investors', 'buy', 'sell'])
    g = inv.groupby('type')
    return pd.DataFrame({'net': g['net'].sum(), 'buy': g['buy'].sum(), 'sell': g['sell'].sum(), 'investors': g.size()}) \
        .reset_index().sort_values('net', ascending=False, kind='stable').reset_index(drop=True)


def by_manager(deals: pd.DataFrame | None, ref: pd.Timestamp | None = None, days: int = 30, rules=None) -> pd.DataFrame:
    """Net buying or selling per fund manager named in the fund names (fund_managers.py), beside the investor table and
    never merged into it: manager, number of fund names, how many of them are sub-advised, buy, sell, net, companies."""
    from . import fund_managers
    d = real_deals(deals, ref, days, types='all')
    if d.empty:
        return pd.DataFrame(columns=['manager', 'funds', 'sub_advised', 'buy', 'sell', 'net', 'companies', 'names'])
    d = fund_managers.add_manager_columns(d, rules)
    d = d[d['manager'].notna()].assign(_v=lambda x: pd.to_numeric(x['signed_value'], errors='coerce'),
                                       _abs=lambda x: pd.to_numeric(x['value'], errors='coerce'))
    if d.empty:
        return pd.DataFrame(columns=['manager', 'funds', 'sub_advised', 'buy', 'sell', 'net', 'companies', 'names'])
    g = d.groupby('manager', sort=False)
    out = pd.DataFrame({'funds': g['client_name'].nunique(),
                        'sub_advised': d[d['manager_sub_advised']].groupby('manager')['client_name'].nunique(),
                        'buy': d[d['side'].eq('BUY')].groupby('manager')['_abs'].sum(),
                        'sell': d[d['side'].eq('SELL')].groupby('manager')['_abs'].sum(),
                        'companies': g['isin'].nunique(), 'names': g['client_name'].agg(lambda s: sorted(set(s)))})
    out[['sub_advised', 'buy', 'sell']] = out[['sub_advised', 'buy', 'sell']].fillna(0)
    out['net'] = out['buy'] - out['sell']
    out['sub_advised'] = out['sub_advised'].astype(int)
    return out.reset_index().reindex(columns=['manager', 'funds', 'sub_advised', 'buy', 'sell', 'net', 'companies', 'names']) \
        .sort_values('net', key=lambda s: s.abs(), ascending=False, kind='stable').reset_index(drop=True)


def profile_deals(deals: pd.DataFrame | None, eid: str) -> tuple[pd.DataFrame, str | None]:
    """Every deal leg of the investor behind `eid` (a client id or an investor-group id): all the names of one
    `investor_group` together, the id of that group (None when the name has no alias line), primary legs only."""
    if deals is None or deals.empty or not eid:
        return pd.DataFrame(), None
    own = deals['investor_group_id'] if 'investor_group_id' in deals else pd.Series(None, index=deals.index, dtype=object)
    hit = deals[deals['client_id'].eq(eid) | own.eq(eid)]
    gid = hit['investor_group_id'].dropna().iloc[0] if len(hit) and 'investor_group_id' in hit and hit['investor_group_id'].notna().any() else None
    d = deals[own.eq(gid)] if gid else hit
    return d[d['is_primary'].astype('boolean').fillna(False)], gid


def by_company(deals: pd.DataFrame | None, ref: pd.Timestamp | None = None, days: int = 90) -> pd.DataFrame:
    """One investor's deals per company over the period: bought, sold, net and the net share of the company, largest
    absolute net first. Market makers' legs are not netted (a market maker's churn says nothing)."""
    d = real_deals(deals, ref, days, types='all')
    if d.empty:
        return pd.DataFrame(columns=['isin', 'company', 'nse_symbol', 'buy', 'sell', 'net', 'pct', 'last'])
    d = d.assign(_v=pd.to_numeric(d['signed_value'], errors='coerce'), _abs=pd.to_numeric(d['value'], errors='coerce'),
                 _p=pd.to_numeric(d['pct_of_mcap'], errors='coerce') * d['side'].map({'BUY': 1, 'SELL': -1}))
    g = d.groupby('isin')
    out = pd.DataFrame({'company': g['company'].last(), 'nse_symbol': g['nse_symbol'].last(),
                        'buy': d[d['side'].eq('BUY')].groupby('isin')['_abs'].sum(),
                        'sell': d[d['side'].eq('SELL')].groupby('isin')['_abs'].sum(),
                        'net': g['_v'].sum(), 'pct': g['_p'].sum(), 'last': g['date'].max().dt.normalize()})
    out[['buy', 'sell']] = out[['buy', 'sell']].fillna(0.0)
    return out.loc[out['net'].abs().sort_values(ascending=False, kind='stable').index].reset_index()
