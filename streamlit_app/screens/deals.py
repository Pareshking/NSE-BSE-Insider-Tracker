"""Deals: bulk and block deals by real buyers and sellers, the funds behind
them, and SAST Reg 29 stake changes."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from ui import kit

from screens.ctx import load, need_data


def render():
    ctx = load()
    kit.head('Deals & big stakes', 'Bulk and block deals with market makers set aside, the funds most active, and '
                                   'SAST filings by anyone crossing 5% or moving 2%.')
    if not need_data(ctx):
        return
    d = ctx.deals
    tabs = st.tabs(['Deals', 'Most active buyers', 'Big stakes (SAST)'])
    with tabs[0]:
        if d.empty:
            kit.empty('No deals yet.')
        else:
            c1, c2 = st.columns([1, 2])
            days = c1.selectbox('Period', [7, 30, 90], index=1, format_func=lambda x: f'Last {x} days', key='dl_days')
            show_mm = c2.toggle('Include market makers', value=False, key='dl_mm',
                                help='32 trading firms that buy and sell in equal measure; they supply liquidity')
            rows = d[d['date'] > d['date'].max() - pd.Timedelta(days=days)]
            if not show_mm:
                rows = rows[~rows['client_is_market_maker'].astype('boolean').fillna(False)]
            rows = rows[rows['is_primary'].astype('boolean').fillna(False)].sort_values(['date', 'value'], ascending=False)
            st.dataframe(rows.assign(link=rows['nse_symbol'].map(kit.company_href))[
                ['link', 'date', 'company', 'client_name', 'side', 'quantity', 'price', 'value_cr', 'pct_of_mcap',
                 'trades', 'counterparties', 'feeds', 'listed_on']], hide_index=True, width='stretch', height=600,
                column_config={'link': st.column_config.LinkColumn('', display_text='Open', width='small', pinned=True),
                               'date': st.column_config.DateColumn('Date', format='DD MMM YYYY'), 'company': 'Company', 'client_name': 'Client',
                               'side': 'Side', 'quantity': st.column_config.NumberColumn('Shares', format='%,.0f'),
                               'price': st.column_config.NumberColumn('Price', format='%.2f'),
                               'value_cr': st.column_config.NumberColumn('Value (₹ Cr)', format='%,.2f'),
                               'pct_of_mcap': st.column_config.NumberColumn('% of mcap', format='%.2f%%'),
                               'trades': st.column_config.NumberColumn('Trades', format='%d'),
                               'counterparties': 'Other side', 'feeds': 'Feed', 'listed_on': 'Exchange'})
            kit.caption('Same client, stock, day and side are one row. A trade printed in both the bulk and block feed '
                        'counts once.')
    with tabs[1]:
        if d.empty:
            kit.empty('No deals yet.')
        else:
            real = d[~d['client_is_market_maker'].astype('boolean').fillna(False) & d['is_primary'].astype('boolean').fillna(False)
                     & (d['date'] > d['date'].max() - pd.Timedelta(days=90))]
            g = real.groupby(['client_id', 'client_name']).agg(
                net=('signed_value', 'sum'), bought=('value', lambda s: s[real.loc[s.index, 'side'] == 'BUY'].sum()),
                companies=('isin', 'nunique'), legs=('deal_id', 'size'), last=('date', 'max')).reset_index()
            g = g[g['net'] > 0].sort_values('net', ascending=False).head(100)
            st.dataframe(g.assign(link=g['client_id'].map(kit.entity_href))[
                ['link', 'client_name', 'net', 'bought', 'companies', 'legs', 'last']], hide_index=True, width='stretch',
                height=560, column_config={'link': st.column_config.LinkColumn('', display_text='Open', width='small'),
                                           'client_name': 'Client', 'net': st.column_config.NumberColumn('Net bought (₹)', format='%,.0f'),
                                           'bought': st.column_config.NumberColumn('Bought (₹)', format='%,.0f'),
                                           'companies': 'Companies', 'legs': 'Deals', 'last': st.column_config.DateColumn('Last deal', format='DD MMM YYYY')})
            kit.caption('Net buyers over 90 days. Research finds prices often run up before a bulk buy and give back '
                        'from day two, so treat this as who is active, not a buy list.')
    with tabs[2]:
        s = ctx.sast
        if s.empty:
            kit.empty('SAST filings arrive with the daily NSE events collection.')
        else:
            s = s.copy()
            s['transaction_date'] = pd.to_datetime(s['transaction_date'], errors='coerce')
            s = s.sort_values('transaction_date', ascending=False)
            st.dataframe(s.assign(link=s['symbol'].map(kit.company_href))[
                ['link', 'transaction_date', 'company', 'acquirer_name', 'is_promoter', 'action_type', 'mode',
                 'shares_traded', 'percent_equity_traded', 'post_stake_pct', 'regulation']], hide_index=True,
                width='stretch', height=560, column_config={
                    'link': st.column_config.LinkColumn('', display_text='Open', width='small'),
                    'transaction_date': st.column_config.DateColumn('Date', format='DD MMM YYYY'), 'company': 'Company',
                    'acquirer_name': 'Acquirer / seller', 'is_promoter': st.column_config.CheckboxColumn('Promoter'),
                    'action_type': 'Action', 'mode': 'Mode',
                    'shares_traded': st.column_config.NumberColumn('Shares', format='%,.0f'),
                    'percent_equity_traded': st.column_config.NumberColumn('% traded', format='%+.2f%%'),
                    'post_stake_pct': st.column_config.NumberColumn('Stake after', format='%.2f%%'),
                    'regulation': 'Rule'})
