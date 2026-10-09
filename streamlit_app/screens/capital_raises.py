"""Capital raises: dilution risk and promoter funding terms.

Sections from docs/DATA_TO_PAGES.md: S14 upcoming capital moves (board
meetings) and S15 corporate actions are in. S16 preferential pipeline, S17
price vs the SEBI ICDR minimum and market, and S18 lock-in expiry calendar
need the preferential/rights data cleaned (docs/TODO.md #11) and prices
(#6); they are listed as pending, not replaced."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from ui import kit

from screens.ctx import load

PURPOSES = {'buyback': 'Buyback', 'rights': 'Rights', 'bonus': 'Bonus', 'split': 'Split', 'dividend': 'Dividend'}
MEETING_FOCUS = ['fund_raising', 'preferential', 'buyback', 'rights', 'bonus', 'split', 'dividend', 'results']


def render():
    ctx = load()
    kit.head('Capital raises', 'Who is about to raise money or buy back shares, and on what terms: dilution risk and '
                               'promoter funding in one place.')
    pending = ctx.__dict__.get('preferential')
    if pending is None or getattr(pending, 'empty', True):
        kit.note('Preferential issue pipeline, price vs the SEBI minimum and the lock-in calendar are pending.',
                 'The data is collected (offer price, shares allotted, allotment and trading-approval dates) and is '
                 'being cleaned; these sections appear when it is.')

    with kit.card('Upcoming board meetings on capital moves', 'cr_meet', 'from NSE board-meeting intimations'):
        m = ctx.meetings
        if m.empty:
            kit.empty('Board meetings arrive with the daily NSE events collection.')
        else:
            m = m.copy()
            m['meeting_date'] = pd.to_datetime(m['meeting_date'], errors='coerce')
            focus = st.pills('Considering', MEETING_FOCUS, default=['fund_raising', 'preferential', 'buyback'],
                             selection_mode='multi', format_func=lambda x: x.replace('_', ' ').capitalize(), key='cr_focus')
            cols = [c for c in (focus or []) if c in m]
            rows = m[m[cols].astype('boolean').fillna(False).any(axis=1)] if cols else m
            rows = rows[rows['meeting_date'] >= pd.Timestamp.now().normalize() - pd.Timedelta(days=7)].sort_values('meeting_date')
            if rows.empty:
                kit.empty('No meetings for these purposes from last week onwards.')
            else:
                kit.table(rows.assign(nse_symbol=rows['symbol'], what=rows['purposes'].str.replace('_', ' ').str.replace(',', ', ').str.capitalize()), [
                    kit.Col('meeting_date', 'Meeting', 'date'), kit.Col('company', 'Company', 'co'),
                    kit.Col('what', 'To consider'), kit.Col('description', 'As filed', phone=False)], limit=100)

    with kit.card('Corporate actions', 'cr_actions', 'buybacks, rights, bonuses, splits, dividends'):
        a = ctx.actions
        if a.empty:
            kit.empty('Corporate actions arrive with the daily NSE events collection.')
        else:
            a = a.copy()
            a['ex_date'] = pd.to_datetime(a['ex_date'], errors='coerce')
            kinds = st.pills('Type', list(PURPOSES), default=['buyback', 'rights', 'bonus', 'split'],
                             selection_mode='multi', format_func=PURPOSES.get, key='cr_kinds')
            rows = a[a['purpose'].isin(kinds)] if kinds else a
            rows = rows.sort_values('ex_date', ascending=False)
            kit.table(rows.assign(nse_symbol=rows['symbol'], kind=rows['purpose'].map(PURPOSES)), [
                kit.Col('ex_date', 'Ex-date', 'date'), kit.Col('company', 'Company', 'co'), kit.Col('kind', 'Type'),
                kit.Col('subject', 'As filed', phone=False), kit.Col('ratio', 'Ratio'),
                kit.Col('rights_issue_price', 'Rights price', 'price', phone=False),
                kit.Col('dividend_per_share', 'Dividend/share', 'price', phone=False),
                kit.Col('record_date', 'Record date', 'date', phone=False)], limit=150, download='corporate_actions')
            kit.caption("Rights price = face value + the premium NSE lists. Buyback price and route (tender or open "
                        "market) are not in NSE's corporate-actions feed; they come from the offer documents later.")
