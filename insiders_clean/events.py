"""Turn clean tables into research events (docs/RESEARCH.md section E). One event = one security, one disclosure
day, one direction; tranches filed the same day are combined. Only the primary copy of a filing counts."""
from __future__ import annotations

import pandas as pd

DEV_END = pd.Timestamp('2026-06-30')     # development period ends here; later events are the hold-out
PRODUCT_START = pd.Timestamp('2026-01-01')
PROMOTER_ROLES = ('promoter', 'promoter_group')


def _flag(s: pd.Series) -> pd.Series:
    return s.astype(str).str.lower().isin(['true', '1', 'yes'])


def insider_events(trades: pd.DataFrame, side: str, market_only: bool = True) -> pd.DataFrame:
    d = trades.copy()
    d = d[_flag(d['is_primary'])] if 'is_primary' in d else d
    d = d[d['side'] == side]
    if market_only:
        d = d[_flag(d['is_market'])]
    d = d.dropna(subset=['isin', 'broadcast_date'])
    d = d[d['isin'].astype(str) != '']
    d['broadcast_date'] = pd.to_datetime(d['broadcast_date'], errors='coerce').dt.normalize()
    if 'broadcast_ts' not in d:
        d['broadcast_ts'] = pd.NaT
    d['broadcast_ts'] = pd.to_datetime(d['broadcast_ts'], errors='coerce')
    d = d.dropna(subset=['broadcast_date'])
    g = d.groupby(['isin', 'broadcast_date'], as_index=False).agg(
        broadcast_ts=('broadcast_ts', 'max'), value=('value', 'sum'), n_filings=('trade_id', 'nunique') if 'trade_id' in d else ('isin', 'size'),
        n_people=('person_id', 'nunique') if 'person_id' in d else ('isin', 'size'),
        pct_of_mcap=('pct_of_mcap', 'sum') if 'pct_of_mcap' in d else ('isin', 'size'),
        promoter=('person_role', lambda s: bool(s.isin(PROMOTER_ROLES).any())) if 'person_role' in d else ('isin', lambda s: False))
    g['side'] = side
    return g


def deal_events(deals: pd.DataFrame, min_value: float = 0.0) -> pd.DataFrame:
    """Net direction per security and day across clients (market makers and round trips excluded upstream/here)."""
    d = deals.copy()
    d = d[_flag(d['is_primary'])] if 'is_primary' in d else d
    if 'client_is_market_maker' in d:
        d = d[~_flag(d['client_is_market_maker'])]
    d = d.dropna(subset=['isin', 'date'])
    d = d[d['isin'].astype(str) != '']
    d['broadcast_date'] = pd.to_datetime(d['date'], errors='coerce').dt.normalize()
    g = d.groupby(['isin', 'broadcast_date'], as_index=False).agg(net_value=('signed_value', 'sum'), gross=('value', 'sum'))
    g = g[g['gross'] > min_value]
    g['side'] = g['net_value'].map(lambda v: 'BUY' if v > 0 else 'SELL' if v < 0 else None)
    g['broadcast_ts'] = pd.NaT       # deals are public after the close: entry is the next session's open
    return g.dropna(subset=['side'])


def split(events: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(development, hold-out) by disclosure date; the hold-out is not read until the final evaluation."""
    day = pd.to_datetime(events['broadcast_date'])
    dev = events[(day >= PRODUCT_START) & (day <= DEV_END)]
    hold = events[day > DEV_END]
    return dev, hold


def prior_buys(events: pd.DataFrame, days: int = 30) -> pd.Series:
    """Number of other buy events for the same security in the `days` calendar days before each event (past only).
    The clean layer starts on 1 Jan 2026, so events in early January see a shorter look-back."""
    day = pd.to_datetime(events['broadcast_date']).dt.normalize()
    out = pd.Series(0, index=events.index, dtype=int)
    for _, g in events.assign(_d=day).groupby('isin'):
        d = g['_d'].to_numpy()
        for i, di in zip(g.index, d):
            out.at[i] = int(((d < di) & (d >= di - pd.Timedelta(days=days).to_timedelta64())).sum())
    return out


def drawdown_at_signal(events: pd.DataFrame, close: pd.DataFrame, window: int = 252, min_hist: int = 250) -> pd.Series:
    """Close at the last session on or before the disclosure date, relative to its trailing `window`-session high
    (split/bonus-adjusted closes). NaN with fewer than `min_hist` sessions of history."""
    dd = close / close.rolling(window, min_periods=min_hist).max() - 1
    day = pd.to_datetime(events['broadcast_date']).dt.normalize().to_numpy(dtype='datetime64[ns]')
    pos = close.index.searchsorted(day, side='right') - 1
    cols = {c: i for i, c in enumerate(close.columns)}
    v = dd.to_numpy()
    out = [v[p, cols[i]] if p >= 0 and i in cols else float('nan') for p, i in zip(pos, events['isin'])]
    return pd.Series(out, index=events.index, dtype=float)
