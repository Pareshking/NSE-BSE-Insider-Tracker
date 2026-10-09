"""Turn clean tables into research events (docs/RESEARCH.md section E). One event = one security, one disclosure
day, one direction; tranches filed the same day are combined. Only the primary copy of a filing counts."""
from __future__ import annotations

import pandas as pd

DEV_END = pd.Timestamp('2026-06-30')     # development period ends here; later events are the hold-out
PRODUCT_START = pd.Timestamp('2026-01-01')


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
        n_people=('person_id', 'nunique') if 'person_id' in d else ('isin', 'size'))
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
