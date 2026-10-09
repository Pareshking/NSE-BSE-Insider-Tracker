"""Insider trades deep dive: SEBI PIT filings with the noise filtered out.

Built to the owner's page spec (07-08 Oct 2026): a "Show pure open-market
trades only" toggle, on by default; tabs Open market buys / Open market
sells / ESOPs & off-market archive / Pledges; a "Filed late by X trading
days" tag counted on exchange trading sessions."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from ui import kit

from insiders_clean.calendar import DISCLOSURE_LIMIT_SESSIONS
from screens.ctx import load, need_data

ROLE_FILTER = ['promoter', 'promoter_group', 'director', 'kmp', 'designated_person', 'immediate_relative', 'other',
               'missing']


def late_text(r) -> str:
    """'Filed late by 3 trading days (insider to company)', or ''."""
    parts = []
    for col, step in (('insider_to_company_sessions', 'insider to company'),
                      ('company_to_exchange_sessions', 'company to exchange')):
        n = pd.to_numeric(r.get(col), errors='coerce')
        if pd.notna(n) and n > DISCLOSURE_LIMIT_SESSIONS:
            x = int(n - DISCLOSURE_LIMIT_SESSIONS)
            parts.append(f'Filed late by {x} trading day{"s" if x != 1 else ""} ({step})')
    return '; '.join(parts)


def _table(rows: pd.DataFrame):
    if rows.empty:
        kit.empty('Nothing here for these filters.')
        return
    rows = rows.sort_values('seen', ascending=False)
    show = rows.assign(link=rows['nse_symbol'].map(kit.company_href), role=rows['person_role'].map(kit.role),
                       late=[late_text(r) for _, r in rows.iterrows()])
    st.dataframe(show[['link', 'company', 'person_name', 'role', 'side', 'mode_raw', 'quantity', 'value_cr',
                       'pct_of_mcap', 'holding_change_pct', 'trade_date_to', 'broadcast_date', 'late', 'flags',
                       'listed_on']], hide_index=True, width='stretch', height=600, column_config={
        'link': st.column_config.LinkColumn('', display_text='Open', width='small', pinned=True),
        'company': st.column_config.TextColumn('Company', pinned=True), 'person_name': 'Person', 'role': 'Role',
        'side': 'Side', 'mode_raw': 'Mode as filed',
        'quantity': st.column_config.NumberColumn('Shares', format='%,.0f'),
        'value_cr': st.column_config.NumberColumn('Value (₹ Cr)', format='%,.2f'),
        'pct_of_mcap': st.column_config.NumberColumn('% of mcap', format='%.3f%%'),
        'holding_change_pct': st.column_config.NumberColumn('Own holding Δ', format='%+.1f%%'),
        'trade_date_to': st.column_config.DateColumn('Traded', format='DD MMM YYYY'),
        'broadcast_date': st.column_config.DateColumn('Made public', format='DD MMM YYYY'),
        'late': st.column_config.TextColumn('Disclosure', help='SEBI PIT Reg 7(2): 2 trading days for each step'),
        'flags': 'Held back because', 'listed_on': 'Exchange'})


def render():
    ctx = load()
    kit.head('Insider trades', 'SEBI PIT filings by promoters, directors and officers: one row per filing after '
                               'repeats and corrections are removed.')
    if not need_data(ctx):
        return
    t = ctx.trades.copy()
    t['seen'] = pd.to_datetime(t['broadcast_date'], errors='coerce')
    pure = st.toggle('Show pure open-market trades only', value=True, key='it_pure',
                     help='Leaves out ESOP allotments, gifts, inter-se transfers, schemes, preferential allotments and pledges')
    c1, c2, c3 = st.columns([1.2, 1.6, 2])
    days = c1.selectbox('Period', [7, 30, 90, 365, 3650], index=2, key='it_days',
                        format_func=lambda d: 'All' if d == 3650 else f'Last {d} days')
    roles = c2.multiselect('Who', ROLE_FILTER, format_func=lambda r: kit.role(r).capitalize(), key='it_roles',
                           placeholder='Everyone')
    q = c3.text_input('Search', placeholder='Company, symbol or person', key='it_q')
    t = t[t['seen'] > ctx.ref - pd.Timedelta(days=days)]
    if roles:
        t = t[t['person_role'].isin(roles)]
    if q:
        t = t[t['company'].str.contains(q, case=False, na=False) | t['person_name'].str.contains(q, case=False, na=False)
              | t['nse_symbol'].astype(str).str.contains(q, case=False)]
    market = t['is_market'].astype('boolean').fillna(False)
    review = t['needs_review'].astype('boolean').fillna(False)
    pledge = t['kind'].astype(str).str.startswith('pledge')
    groups = {'Open market buys': t[market & (t['side'] == 'BUY') & ~review],
              'Open market sells': t[market & (t['side'] == 'SELL') & ~review]}
    if not pure:
        groups['ESOPs & off-market archive'] = t[~market & ~pledge]
        groups['Pledges'] = t[pledge]
        groups['Held back'] = t[review]
    for tab, (_name, rows) in zip(st.tabs([f'{n} · {len(r):,}' for n, r in groups.items()]), groups.items()):
        with tab:
            _table(rows)
    kit.caption('Lateness counts NSE trading sessions, not calendar days: the insider has 2 sessions to tell the '
                'company, the company 2 more to tell the exchange (SEBI PIT Reg 7(2)). Turn the toggle off to see '
                'ESOPs, off-market transfers, pledges and filings held back for a look.')
