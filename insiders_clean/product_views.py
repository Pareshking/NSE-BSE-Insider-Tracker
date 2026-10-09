"""Pure functions behind the Phase 3 pages (no Streamlit, no I/O) so they can be tested.

Labels follow docs/RESEARCH.md: no insider-buy or deal signal has a proven edge (section J.3), so these are
review lists, not alerts. Insider sells are a caution flag, not a trade signal.
"""
from __future__ import annotations

import pandas as pd

from . import events as evm

LAKH = 1e5
NO_EDGE_NOTE = ('No proven edge: in the Jan-Jun 2026 development sample promoter buys beat Nifty 500, but so did insider '
                'sells and most events are micro caps, so this is not evidence of insider information '
                '(docs/RESEARCH.md J.3). This is a review list, not a buy signal.')


def _window(ev: pd.DataFrame, asof, days: int) -> pd.DataFrame:
    d = pd.to_datetime(ev['broadcast_date'])
    return ev[(d <= pd.Timestamp(asof)) & (d > pd.Timestamp(asof) - pd.Timedelta(days=days))]


def promoter_accumulation(trades: pd.DataFrame, asof, days: int = 90, min_value: float = 25 * LAKH) -> pd.DataFrame:
    """Promoter / promoter-group open-market buys per security over the last `days`: total value, buy days, filers.
    `cluster` = two or more buy days within the window of 30 days (repeat accumulation)."""
    ev = _window(evm.insider_events(trades, 'BUY', roles=evm.PROMOTER_ROLES), asof, days)
    if ev.empty:
        return pd.DataFrame(columns=['isin', 'company', 'value', 'buy_days', 'first', 'last', 'cluster'])
    names = trades.dropna(subset=['isin']).drop_duplicates('isin').set_index('isin')['company'] if 'company' in trades else None
    g = ev.groupby('isin').agg(value=('value', 'sum'), buy_days=('broadcast_date', 'nunique'),
                               first=('broadcast_date', 'min'), last=('broadcast_date', 'max')).reset_index()
    d = ev.sort_values('broadcast_date').groupby('isin')['broadcast_date'].apply(
        lambda s: bool((s.diff().dt.days.dropna() <= 30).any()))
    g['cluster'] = g['isin'].map(d).fillna(False)
    g['company'] = g['isin'].map(names) if names is not None else g['isin']
    g = g[g['value'] >= min_value].sort_values(['cluster', 'value'], ascending=False)
    return g[['isin', 'company', 'value', 'buy_days', 'first', 'last', 'cluster']].reset_index(drop=True)


def block_bulk_accumulation(deals: pd.DataFrame, asof, days: int = 90, min_value: float = 1e7) -> pd.DataFrame:
    """Net-buy bulk/block deals per security (market makers excluded), by net value over the last `days`."""
    ev = _window(evm.deal_events(deals), asof, days)
    if ev.empty:
        return pd.DataFrame(columns=['isin', 'net_value', 'days'])
    g = ev.groupby('isin').agg(net_value=('net_value', 'sum'), days=('broadcast_date', 'nunique')).reset_index()
    return g[g['net_value'] >= min_value].sort_values('net_value', ascending=False).reset_index(drop=True)


def heavy_selling(trades: pd.DataFrame, asof, days: int = 60, min_value: float = 25 * LAKH) -> pd.DataFrame:
    """Securities with insider open-market sales above `min_value` in the last `days` (caution flag)."""
    ev = _window(evm.insider_events(trades, 'SELL'), asof, days)
    if ev.empty:
        return pd.DataFrame(columns=['isin', 'value', 'sell_days', 'people', 'promoter'])
    g = ev.groupby('isin').agg(value=('value', 'sum'), sell_days=('broadcast_date', 'nunique'),
                               people=('n_people', 'max'), promoter=('promoter', 'any')).reset_index()
    return g[g['value'] >= min_value].sort_values('value', ascending=False).reset_index(drop=True)


def freshness(frames: dict[str, tuple[pd.DataFrame, str]], today=None) -> pd.DataFrame:
    """name -> (frame, date column): rows, latest date and age in days."""
    today = pd.Timestamp(today or pd.Timestamp.now().normalize())
    rows = []
    for name, (df, col) in frames.items():
        last = pd.to_datetime(df[col], errors='coerce').max() if df is not None and len(df) and col in df else pd.NaT
        rows.append({'dataset': name, 'rows': 0 if df is None else int(len(df)),
                     'latest': last, 'age_days': None if pd.isna(last) else int((today - last).days)})
    return pd.DataFrame(rows)
