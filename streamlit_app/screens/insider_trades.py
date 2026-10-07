"""Insider trades: every SEBI PIT filing, open-market trades by default."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from ui import kit

from screens.ctx import load, need_data

ROLES = {'promoter': 'Promoter', 'promoter_group': 'Promoter group', 'director': 'Director', 'kmp': 'KMP',
         'designated_person': 'Designated person', 'immediate_relative': 'Relative', 'employee': 'Employee',
         'other': 'Other', 'missing': 'Not stated'}
TABS = ['Open-market buys', 'Open-market sells', 'ESOP & off-market', 'Pledges', 'Held back']


def render():
    ctx = load()
    kit.head('Insider trades', 'SEBI PIT filings by promoters, directors and officers, one row per filing after '
                               'repeats and corrections are removed.')
    if not need_data(ctx):
        return
    t = ctx.trades.copy()
    t['seen'] = pd.to_datetime(t['broadcast_date'], errors='coerce')
    c1, c2, c3 = st.columns([1.2, 1.4, 2])
    days = c1.selectbox('Period', [7, 30, 90, 365, 3650], index=2, format_func=lambda d: 'All' if d == 3650 else f'Last {d} days',
                        key='it_days')
    roles = c2.multiselect('Who', list(ROLES), format_func=ROLES.get, key='it_roles', placeholder='Everyone')
    q = c3.text_input('Search', placeholder='Company, symbol or person', key='it_q')
    t = t[t['seen'] > ctx.ref - pd.Timedelta(days=days)]
    if roles:
        t = t[t['person_role'].isin(roles)]
    if q:
        t = t[t['company'].str.contains(q, case=False, na=False) | t['person_name'].str.contains(q, case=False, na=False)
              | t['nse_symbol'].astype(str).str.contains(q, case=False)]
    market = t['is_market'].astype('boolean').fillna(False)
    review = t['needs_review'].astype('boolean').fillna(False)
    groups = {
        TABS[0]: t[market & (t['side'] == 'BUY') & ~review],
        TABS[1]: t[market & (t['side'] == 'SELL') & ~review],
        TABS[2]: t[~market & ~t['kind'].str.startswith('pledge')],
        TABS[3]: t[t['kind'].str.startswith('pledge')],
        TABS[4]: t[review],
    }
    for tab, (name, rows) in zip(st.tabs([f'{n} · {len(r):,}' for n, r in groups.items()]), groups.items()):
        with tab:
            if rows.empty:
                kit.empty('Nothing here for these filters.')
                continue
            rows = rows.sort_values('seen', ascending=False)
            late = rows['insider_filed_late'].astype('boolean').fillna(False) | rows['company_filed_late'].astype('boolean').fillna(False)
            show = rows.assign(link=rows['nse_symbol'].map(kit.company_href), role=rows['person_role'].map(ROLES),
                               late=late.map({True: 'Late', False: ''}))
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
                'broadcast_date': st.column_config.DateColumn('Public', format='DD MMM YYYY'),
                'late': st.column_config.TextColumn('Deadline', help='SEBI PIT Reg 7(2): 2 trading days each step'),
                'flags': 'Why held back', 'listed_on': 'Exchange'})
    kit.caption('"Late" counts trading sessions, not calendar days: insider to company, then company to exchange, '
                'two sessions each.')
