"""Screener: which companies show insider accumulation (or distribution)
right now. One row per company, factor badges instead of a score."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from ui import kit

from insiders_clean import signals
from screens.ctx import load, need_data

PRESETS = ['All with activity', 'Spotlight', 'Float absorber', 'Cluster', 'Promoter selling', 'High pledge']


def render():
    ctx = load()
    kit.head('Screener', 'Companies ranked by promoter open-market buying as a share of market cap over 90 days. '
                         'Badges mark the signals; ESOPs, gifts, transfers and token buys never count.')
    if not need_data(ctx):
        return
    board = signals.company_board(ctx.eligible, ctx.deals, ctx.shareholding, ctx.ref)
    if board.empty:
        kit.empty('No insider activity in the last 90 days.')
        return
    pick = st.pills('Preset', PRESETS, default='All with activity', key='scr_preset', label_visibility='collapsed')
    rows = board
    if pick and pick != 'All with activity':
        key = 'High pledge' if pick == 'High pledge' else pick
        rows = board[board['badges'].map(lambda b: any(x.startswith(key) for x in b))]
    q = st.text_input('Search', placeholder='Company or symbol', key='scr_q', label_visibility='collapsed')
    if q:
        m = rows['company'].str.contains(q, case=False, na=False) | rows['nse_symbol'].astype(str).str.contains(q, case=False)
        rows = rows[m]
    with kit.card(f'{len(rows)} companies', 'screener', f'as of {kit.day(ctx.ref)}'):
        def num(c):  # numeric, so a missing value shows blank, not 'None'
            return pd.to_numeric(rows[c], errors='coerce')

        show = rows.assign(link=rows['nse_symbol'].map(kit.company_href), signals=rows['badges'].map(', '.join),
                           mcap_cr=num('market_cap') / 1e7, promoter_net=num('promoter_net') / 1e7,
                           officer_net=num('officer_net') / 1e7, deals_net=num('deals_net') / 1e7,
                           pledge_pct=num('pledge_pct'))
        st.dataframe(show[['link', 'company', 'signals', 'promoter_net', 'promoter_net_pct', 'officer_net', 'deals_net',
                           'insiders', 'pledge_pct', 'mcap_cr', 'last_seen']],
                     hide_index=True, width='stretch', height=620, column_config={
                         'link': st.column_config.LinkColumn('', display_text='Open', width='small', pinned=True),
                         'company': st.column_config.TextColumn('Company', pinned=True),
                         'signals': 'Signals',
                         'promoter_net': st.column_config.NumberColumn('Promoter net (₹ Cr)', format='%+,.2f'),
                         'promoter_net_pct': st.column_config.NumberColumn('Promoter net % mcap', format='%+.3f%%'),
                         'officer_net': st.column_config.NumberColumn('Directors/KMP net (₹ Cr)', format='%+,.2f'),
                         'deals_net': st.column_config.NumberColumn('Deals net (₹ Cr)', format='%+,.2f',
                                                                    help='Bulk/block, market makers excluded'),
                         'insiders': st.column_config.NumberColumn('Insiders', format='%d'),
                         'pledge_pct': st.column_config.NumberColumn('Promoter pledge', format='%.1f%%',
                                                                     help='% of promoter shares, latest quarter'),
                         'mcap_cr': st.column_config.NumberColumn('Mkt cap (₹ Cr)', format='%,.0f'),
                         'last_seen': st.column_config.DateColumn('Last filing', format='DD MMM YYYY')})
        kit.caption('Distance from the 52-week high and 200-day average arrives with the price join. '
                    'How each signal performed afterwards is on Track record once measured.')
