"""Compact trade-hub tables (one row per filing or deal), in the column order institutional users expect from
Screener.in's trade pages: Date | Symbol & Name | Traded By | Category | Mode | Qty | Avg Price | Value (Rs Cr) | % equity.

The clean data carries no post-transaction shareholding percentage (only share counts), so the equity column is the
ESTIMATED value / market cap on the disclosure day, and the holding change is the relative change in the filer's own
holding. Nothing is invented where a field is missing."""
from __future__ import annotations

import pandas as pd

CATEGORY = {'promoter': 'Promoter', 'promoter_group': 'Promoter Group', 'director': 'Director', 'kmp': 'KMP',
            'designated_person': 'Designated Person', 'immediate_relative': 'Relative', 'employee': 'Employee',
            'other': 'Other', 'missing': 'Unclassified'}
CR = 1e7


def _flag(s: pd.Series) -> pd.Series:
    return s.astype(str).str.lower().isin(['true', '1', 'yes'])


def side_label(side, market: bool) -> str:
    s = str(side).upper()
    if s == 'BUY':
        return '🟢 Market Buy' if market else '🟢 Buy'
    if s == 'SELL':
        return '🔴 Market Sell' if market else '🔴 Sell'
    return '-'


def insider_rows(trades: pd.DataFrame, isin: str | None = None) -> pd.DataFrame:
    """Primary-copy insider filings, newest first then largest value."""
    d = trades[_flag(trades['is_primary'])] if 'is_primary' in trades else trades
    if isin is not None:
        d = d[d['isin'] == isin]
    cols = ['Date', 'Symbol', 'Company', 'Traded By', 'Category', 'Mode', 'Side', 'Qty', 'Avg Price', 'Value (₹ Cr)',
            '% of mcap (est.)', 'Holding Δ %', 'File']
    if d.empty:
        return pd.DataFrame(columns=cols)
    out = pd.DataFrame({
        'Date': pd.to_datetime(d['broadcast_date']),
        'Symbol': d.get('symbol', d.get('nse_symbol')), 'Company': d['company'] if 'company' in d else d['isin'],
        'Traded By': d.get('person_name'), 'Category': d['person_role'].map(CATEGORY).fillna('Unclassified'),
        'Mode': d.get('mode_raw'),
        'Side': [side_label(s, bool(m)) for s, m in zip(d['side'], _flag(d['is_market']))],
        'Qty': d['quantity'], 'Avg Price': d.get('price'), 'Value (₹ Cr)': d['value'] / CR,
        '% of mcap (est.)': d.get('pct_of_mcap'), 'Holding Δ %': d.get('holding_change_pct'),
        'File': d['source_url'] if 'source_url' in d else None})
    return out.sort_values(['Date', 'Value (₹ Cr)'], ascending=False).reset_index(drop=True)[cols]


def deal_rows(deals: pd.DataFrame, isin: str | None = None) -> pd.DataFrame:
    d = deals[_flag(deals['is_primary'])] if 'is_primary' in deals else deals
    if isin is not None:
        d = d[d['isin'] == isin]
    cols = ['Date', 'Symbol', 'Company', 'Client', 'Feed', 'Side', 'Qty', 'Avg Price', 'Value (₹ Cr)', '% of mcap (est.)']
    if d.empty:
        return pd.DataFrame(columns=cols)
    out = pd.DataFrame({
        'Date': pd.to_datetime(d['date']), 'Symbol': d.get('symbol'), 'Company': d['company'] if 'company' in d else d['isin'], 'Client': d.get('client_name'),
        'Feed': d.get('feeds', pd.Series('', index=d.index)).astype(str).str.title(),
        'Side': [side_label(s, False) for s in d['side']], 'Qty': d['quantity'], 'Avg Price': d.get('price'),
        'Value (₹ Cr)': d['value'] / CR, '% of mcap (est.)': d.get('pct_of_mcap')})
    return out.sort_values(['Date', 'Value (₹ Cr)'], ascending=False).reset_index(drop=True)[cols]
