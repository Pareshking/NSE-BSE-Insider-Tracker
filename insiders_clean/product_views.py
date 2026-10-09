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
    return ev[(d <= pd.Timestamp(asof)) & (d > pd.Timestamp(asof) - pd.Timedelta(days=int(days)))]


BADGE_ACCUMULATION = 'Contextual Accumulation (No Proven Standalone Edge)'
MIN_PCT_OF_MCAP = 0.05      # percent of market cap (proxy for share of equity)


def promoter_accumulation(trades: pd.DataFrame, asof, days: int = 90, min_value: float = 25 * LAKH,
                          min_pct: float = MIN_PCT_OF_MCAP) -> pd.DataFrame:
    """Promoter / promoter-group open-market buys per security over the last `days`. Directors, KMP, designated persons
    and employees are excluded (token compliance trades). A security is material when its combined value is at least
    `min_value` or at least `min_pct` percent of market cap. `cluster` = two or more buy days within 30 days of each other."""
    ev = _window(evm.insider_events(trades, 'BUY', roles=evm.PROMOTER_ROLES), asof, days)
    cols = ['isin', 'company', 'value', 'pct_of_mcap', 'buy_days', 'first', 'last', 'cluster', 'badge']
    if ev.empty:
        return pd.DataFrame(columns=cols)
    names = trades.dropna(subset=['isin']).drop_duplicates('isin').set_index('isin')['company'] if 'company' in trades else None
    g = ev.groupby('isin').agg(value=('value', 'sum'), pct_of_mcap=('pct_of_mcap', 'sum'), buy_days=('broadcast_date', 'nunique'),
                               first=('broadcast_date', 'min'), last=('broadcast_date', 'max')).reset_index()
    d = ev.sort_values('broadcast_date').groupby('isin')['broadcast_date'].apply(
        lambda s: bool((s.diff().dt.days.dropna() <= 30).any()))
    g['cluster'] = g['isin'].map(d).fillna(False)
    g['company'] = g['isin'].map(names) if names is not None else g['isin']
    g['badge'] = BADGE_ACCUMULATION
    g = g[(g['value'] >= min_value) | (g['pct_of_mcap'] >= min_pct)].sort_values(['cluster', 'value'], ascending=False)
    return g[cols].reset_index(drop=True)


def block_bulk_accumulation(deals: pd.DataFrame, asof, days: int = 90, min_value: float = 1e7) -> pd.DataFrame:
    """Net-buy bulk/block deals per security (market makers excluded), by net value over the last `days`."""
    ev = _window(evm.deal_events(deals), asof, days)
    if ev.empty:
        return pd.DataFrame(columns=['isin', 'net_value', 'days'])
    g = ev.groupby('isin').agg(net_value=('net_value', 'sum'), days=('broadcast_date', 'nunique')).reset_index()
    return g[g['net_value'] >= min_value].sort_values('net_value', ascending=False).reset_index(drop=True)


def risk_flags(trades: pd.DataFrame, asof, days: int = 60, min_value: float = 25 * LAKH, rapid_days: int = 3) -> pd.DataFrame:
    """Caution flags from insider open-market SALES in the last `days`: `heavy` = combined value >= min_value;
    `rapid` = sales on `rapid_days` or more separate disclosure days; `promoter_selling` = a promoter / promoter-group
    filer is among the sellers. Sorted by value. A prompt to read the filings, not a trade signal."""
    ev = _window(evm.insider_events(trades, 'SELL'), asof, days)
    cols = ['isin', 'company', 'value', 'sell_days', 'people', 'promoter_selling', 'heavy', 'rapid']
    if ev.empty:
        return pd.DataFrame(columns=cols)
    names = trades.dropna(subset=['isin']).drop_duplicates('isin').set_index('isin')['company'] if 'company' in trades else None
    g = ev.groupby('isin').agg(value=('value', 'sum'), sell_days=('broadcast_date', 'nunique'),
                               people=('n_people', 'max'), promoter_selling=('promoter', 'any')).reset_index()
    g['company'] = g['isin'].map(names) if names is not None else g['isin']
    g['heavy'] = g['value'] >= min_value
    g['rapid'] = g['sell_days'] >= rapid_days
    return g[g['heavy'] | g['rapid']].sort_values('value', ascending=False)[cols].reset_index(drop=True)


def audit_table(trades: pd.DataFrame, deals: pd.DataFrame, isin: str) -> pd.DataFrame:
    """Chronological list of the filings and deals behind the chart for one security, newest first, with the
    exchange's own file link where the clean layer carries one (NSE insider filings)."""
    t = trades[trades['isin'] == isin]
    rows = pd.DataFrame({'date': pd.to_datetime(t['broadcast_date']), 'kind': 'Insider ' + t['side'].fillna('?').astype(str)
                         + t['is_market'].map(lambda v: '' if str(v).lower() in ('true', '1') else ' (non-market)'),
                         'who': t.get('person_role'), 'value': t['value'], 'quantity': t['quantity'], 'exchange': t['exchange'],
                         'link': t['source_url'] if 'source_url' in t else None, 'id': t['trade_id']})
    d = deals[deals['isin'] == isin]
    if len(d):
        dd = pd.DataFrame({'date': pd.to_datetime(d['date']), 'kind': 'Deal ' + d.get('feeds', pd.Series('', index=d.index)).astype(str)
                           + ' ' + d['side'].fillna('?').astype(str), 'who': d.get('client_name'), 'value': d['value'],
                           'quantity': d['quantity'], 'exchange': d['exchange'], 'link': None, 'id': d.get('deal_id')})
        rows = pd.concat([rows, dd], ignore_index=True)
    return rows.sort_values('date', ascending=False).reset_index(drop=True)


def freshness(frames: dict[str, tuple[pd.DataFrame, str]], today=None) -> pd.DataFrame:
    """name -> (frame, date column): rows, latest date and age in days."""
    today = pd.Timestamp(today or pd.Timestamp.now().normalize())
    rows = []
    for name, (df, col) in frames.items():
        last = pd.to_datetime(df[col], errors='coerce').max() if df is not None and len(df) and col in df else pd.NaT
        rows.append({'dataset': name, 'rows': 0 if df is None else int(len(df)),
                     'latest': last, 'age_days': None if pd.isna(last) else int((today - last).days)})
    return pd.DataFrame(rows)
