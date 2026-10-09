"""Slim, precomputed summaries for the app (batch job only; the Streamlit pages never touch the full price table).

`prices_summary_slim`: one row per ISIN with the adjusted latest close, 52-week high / low, calendar returns and a
market-cap bucket. Prices are adjusted for splits and bonuses only.

Market-cap bucket is ESTIMATED: rank of NSE market cap on the latest stored day (top 100 Large, 101-250 Mid, 251-500
Small, the rest Micro). It follows the AMFI/Nifty rank cut-offs but is computed from NSE's file, not AMFI's list.
"""
from __future__ import annotations

import pandas as pd

from . import adjust

BUCKETS = ('Large', 'Mid', 'Small', 'Micro')
COLUMNS = ['isin', 'symbol', 'name', 'exchange', 'last_date', 'latest_close', 'high_52w', 'low_52w', 'pct_off_high',
           'ret_90d', 'ret_180d', 'last_split_date', 'last_split_factor', 'n_splits', 'market_cap', 'mcap_rank', 'mcap_bucket']


def price_panel(prices: pd.DataFrame, field: str) -> pd.DataFrame:
    """date x ISIN panel of `field`, NSE preferred, BSE filling the gaps."""
    p = prices.dropna(subset=['isin', field])
    p = p[p['isin'] != '']
    p = p.assign(_rank=(p['exchange'] != 'NSE').astype(int)).sort_values(['isin', 'date', '_rank', 'value'],
                                                                         ascending=[True, True, True, False])
    p = p.drop_duplicates(['isin', 'date'])
    return p.pivot(index='date', columns='isin', values=field).sort_index()


def adjusted_panels(px: pd.DataFrame):
    """(close, open) date x ISIN panels adjusted as of the last stored session."""
    f = adjust.inherit_nse(adjust.implied_factors(px))
    adj = adjust.adjust_as_of(f, px[['exchange', 'isin', 'date', 'close']].dropna(), px['date'].max())
    px = px.merge(adj[['exchange', 'isin', 'date', 'adj_close']], on=['exchange', 'isin', 'date'], how='left')
    ratio = (px['adj_close'] / px['close']).where(px['close'] > 0)
    px['open'] = px['open'] * ratio
    px['close'] = px['adj_close']
    return price_panel(px, 'close'), price_panel(px, 'open'), f


def bucket(rank: float) -> str | None:
    if pd.isna(rank):
        return None
    return 'Large' if rank <= 100 else 'Mid' if rank <= 250 else 'Small' if rank <= 500 else 'Micro'


def price_summary(close: pd.DataFrame, meta: pd.DataFrame, factors: pd.DataFrame, mcap: pd.DataFrame | None) -> pd.DataFrame:
    """`close`: adjusted date x ISIN panel. `meta`: isin, symbol, name, exchange. `factors`: implied factors with kind.
    `mcap`: symbol, market_cap for the latest day (or None)."""
    asof = close.index.max()
    last = close.apply(lambda s: s.last_valid_index())
    out = pd.DataFrame({'isin': close.columns, 'last_date': last.values})
    out['latest_close'] = [close.at[d, i] if pd.notna(d) else float('nan') for i, d in zip(out['isin'], out['last_date'])]
    year = close.loc[asof - pd.Timedelta(days=365):]
    out['high_52w'] = out['isin'].map(year.max())
    out['low_52w'] = out['isin'].map(year.min())
    out['pct_off_high'] = out['latest_close'] / out['high_52w'] - 1
    ff = close.ffill()
    for days in (90, 180):
        cut = ff.loc[:asof - pd.Timedelta(days=days)]
        out[f'ret_{days}d'] = out['isin'].map(out['latest_close'].set_axis(out['isin']) / cut.iloc[-1] - 1) if len(cut) else float('nan')
    out = out.merge(meta.drop_duplicates('isin'), on='isin', how='left')
    sf = factors[factors['kind'] == 'split_bonus'].dropna(subset=['factor']).sort_values('date')
    if len(sf):
        g = sf.groupby('isin').agg(last_split_date=('date', 'max'), last_split_factor=('factor', 'last'), n_splits=('date', 'nunique'))
        out = out.merge(g, left_on='isin', right_index=True, how='left')
    else:
        out['last_split_date'], out['last_split_factor'], out['n_splits'] = pd.NaT, float('nan'), 0
    out['n_splits'] = out['n_splits'].fillna(0).astype(int)
    out['market_cap'], out['mcap_rank'] = float('nan'), float('nan')
    if mcap is not None and len(mcap):
        m = mcap.dropna(subset=['market_cap']).sort_values('market_cap', ascending=False).drop_duplicates('symbol')
        m['mcap_rank'] = range(1, len(m) + 1)
        m = m.set_index('symbol')
        out['market_cap'] = out['symbol'].map(m['market_cap'])
        out['mcap_rank'] = out['symbol'].map(m['mcap_rank'])
    out['mcap_bucket'] = out['mcap_rank'].map(bucket)
    return out.reindex(columns=COLUMNS)


def price_history(close: pd.DataFrame, isins, days: int = 400) -> pd.DataFrame:
    """Long table (isin, date, close) of adjusted closes over the last `days`
    calendar days for the given ISINs: the price lines on the site's pages."""
    keep = [i for i in pd.unique(pd.Series(list(isins)).dropna()) if i in close.columns]
    if not keep:
        return pd.DataFrame(columns=['isin', 'date', 'close'])
    win = close.loc[close.index.max() - pd.Timedelta(days=days):, keep]
    out = win.reset_index().melt(id_vars=win.index.name or 'date', var_name='isin', value_name='close')
    out = out.rename(columns={win.index.name or 'date': 'date'}).dropna(subset=['close'])
    out['close'] = out['close'].astype('float32')
    return out[['isin', 'date', 'close']].sort_values(['isin', 'date']).reset_index(drop=True)


def market_strip(ix: pd.DataFrame, names=('Nifty 500', 'Nifty Smallcap 250', 'Nifty Microcap 250')) -> list[dict]:
    """Per broad index: last close and date, distance from the 200-session
    average, and the 1-month (21-session) change."""
    out = []
    for name in names:
        s = ix[ix['symbol'] == name].drop_duplicates('date').set_index('date')['close'].sort_index().dropna()
        if len(s) < 22:
            continue
        ma = s.tail(200).mean() if len(s) >= 200 else float('nan')
        out.append({'index': name, 'date': s.index[-1].strftime('%Y-%m-%d'), 'close': float(s.iloc[-1]),
                    'vs_200d': float(s.iloc[-1] / ma - 1) if ma == ma else None,
                    'chg_1m': float(s.iloc[-1] / s.iloc[-22] - 1)})
    return out
