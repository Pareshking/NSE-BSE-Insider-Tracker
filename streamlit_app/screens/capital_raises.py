"""Capital raises & corporate actions: buybacks, rights, bonus, splits,
dividends, and board meetings that will consider them."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from ui import kit

from screens.ctx import load

PURPOSES = {'buyback': 'Buyback', 'rights': 'Rights', 'bonus': 'Bonus', 'split': 'Split', 'dividend': 'Dividend'}


def render():
    ctx = load()
    kit.head('Capital raises & actions', 'Buybacks, rights issues, bonuses, splits and dividends, and the board '
                                         'meetings coming up that will consider fund raising or a buyback.')
    a, m = ctx.actions, ctx.meetings
    tabs = st.tabs(['Upcoming meetings', 'Corporate actions'])
    with tabs[0]:
        if m.empty:
            kit.empty('Board meetings arrive with the daily NSE events collection.')
        else:
            m = m.copy()
            m['meeting_date'] = pd.to_datetime(m['meeting_date'], errors='coerce')
            focus = st.pills('Considering', ['fund_raising', 'preferential', 'buyback', 'bonus', 'rights', 'split',
                                             'dividend', 'results'], default=['fund_raising', 'preferential', 'buyback'],
                             selection_mode='multi', format_func=lambda x: x.replace('_', ' ').capitalize(), key='cr_focus')
            rows = m[m[list(focus)].any(axis=1)] if focus else m
            rows = rows.sort_values('meeting_date')
            st.dataframe(rows.assign(link=rows['symbol'].map(kit.company_href), what=rows['purposes'].str.replace('_', ' '))[
                ['link', 'meeting_date', 'company', 'what', 'description']], hide_index=True, width='stretch', height=520,
                column_config={'link': st.column_config.LinkColumn('', display_text='Open', width='small'),
                               'meeting_date': st.column_config.DateColumn('Meeting', format='DD MMM YYYY'), 'company': 'Company',
                               'what': 'To consider', 'description': 'As filed'})
    with tabs[1]:
        if a.empty:
            kit.empty('Corporate actions arrive with the daily NSE events collection.')
        else:
            a = a.copy()
            a['ex_date'] = pd.to_datetime(a['ex_date'], errors='coerce')
            kinds = st.pills('Type', list(PURPOSES), default=['buyback', 'rights', 'bonus', 'split'], selection_mode='multi',
                             format_func=PURPOSES.get, key='cr_kinds')
            rows = a[a['purpose'].isin(kinds)] if kinds else a
            rows = rows.sort_values('ex_date', ascending=False)
            st.dataframe(rows.assign(link=rows['symbol'].map(kit.company_href), kind=rows['purpose'].map(PURPOSES))[
                ['link', 'ex_date', 'company', 'kind', 'subject', 'ratio', 'rights_issue_price', 'dividend_per_share',
                 'record_date']], hide_index=True, width='stretch', height=520, column_config={
                    'link': st.column_config.LinkColumn('', display_text='Open', width='small'),
                    'ex_date': st.column_config.DateColumn('Ex-date', format='DD MMM YYYY'), 'company': 'Company', 'kind': 'Type',
                    'subject': 'As filed', 'ratio': 'Ratio',
                    'rights_issue_price': st.column_config.NumberColumn('Rights price (₹)', format='%.2f'),
                    'dividend_per_share': st.column_config.NumberColumn('Dividend (₹/sh)', format='%.2f'),
                    'record_date': st.column_config.DateColumn('Record date', format='DD MMM YYYY')})
            kit.caption('Buyback price and route (tender or open market) are not in NSE\'s corporate-actions feed; '
                        'they come from the offer documents in a later step.')
