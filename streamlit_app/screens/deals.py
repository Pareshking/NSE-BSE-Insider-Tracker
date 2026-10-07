"""Bulk & block deals and big stakes: track institutional money and the
"smart handshakes".

Built to the owner's page spec (07-08 Oct 2026): the handshake matcher (who
sold, who absorbed it, whether the seller is a promoter), the institutional
footprint ("which small caps are institutions accumulating this month?"),
all deals, and SAST Reg 29 stake changes. Market makers are left out unless
asked for. Named-investor alias tracking needs a curated alias list and is
pending (docs/TODO.md)."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from ui import kit

from insiders_clean import signals
from screens.ctx import load, need_data


def render():
    ctx = load()
    kit.head('Deals & big stakes', 'Who sold, who absorbed it, and which small caps real funds are accumulating. '
                                   'The 32 market-making firms that buy and sell in equal measure are left out.')
    if not need_data(ctx):
        return
    d = ctx.deals
    tabs = st.tabs(['Handshakes', 'Small caps being accumulated', 'All deals', 'Big stakes (SAST)'])

    with tabs[0]:
        days = st.selectbox('Period', [7, 30, 90], index=1, format_func=lambda x: f'Last {x} days', key='hs_days')
        h = signals.handshakes(d, ctx.trades, days=days)
        only_prom = st.toggle('Only where a promoter sold', value=False, key='hs_prom')
        if not h.empty and only_prom:
            h = h[h['seller_is_promoter']]
        if h.empty:
            kit.empty('No matched buyer-seller deals in this period.')
        else:
            st.dataframe(h.assign(link=h['nse_symbol'].map(kit.company_href), value_cr=h['matched_value'] / 1e7,
                                  who=h['seller_is_promoter'].map({True: 'Promoter', False: ''}),
                                  size=h['large'].map({True: 'Large', False: ''}))[
                ['link', 'date', 'company', 'sellers', 'who', 'pct_of_mcap_sold', 'buyers', 'value_cr', 'size']],
                hide_index=True, width='stretch', height=560, column_config={
                    'link': st.column_config.LinkColumn('', display_text='Open', width='small', pinned=True),
                    'date': st.column_config.DateColumn('Date', format='DD MMM YYYY'), 'company': 'Company',
                    'sellers': 'Sold by', 'who': 'Seller is',
                    'pct_of_mcap_sold': st.column_config.NumberColumn('% of mcap sold', format='%.2f%%'),
                    'buyers': 'Absorbed by', 'value_cr': st.column_config.NumberColumn('Matched (₹ Cr)', format='%,.2f'),
                    'size': st.column_config.TextColumn('', help='Large: ₹10 Cr+ or 0.5%+ of market cap')})
            kit.caption('A promoter seller is recognised when the same name filed as promoter or promoter group for that '
                        'company. "Absorbed by" lists the real buyers on the other side that day.')

    with tabs[1]:
        acc = signals.small_cap_accumulation(d)
        if acc.empty:
            kit.empty('No small caps net-bought by real funds in the last 30 days.')
        else:
            st.dataframe(acc.assign(link=acc['nse_symbol'].map(kit.company_href), value_cr=acc['net_value'] / 1e7,
                                    mcap_cr=pd.to_numeric(acc['market_cap'], errors='coerce') / 1e7)[
                ['link', 'company', 'net_buyers', 'value_cr', 'net_pct', 'mcap_cr', 'last']],
                hide_index=True, width='stretch', height=560, column_config={
                    'link': st.column_config.LinkColumn('', display_text='Open', width='small', pinned=True),
                    'company': 'Company', 'net_buyers': 'Net buyers',
                    'value_cr': st.column_config.NumberColumn('Net bought (₹ Cr)', format='%,.2f'),
                    'net_pct': st.column_config.NumberColumn('% of mcap', format='%.2f%%'),
                    'mcap_cr': st.column_config.NumberColumn('Mkt cap (₹ Cr)', format='%,.0f'),
                    'last': st.column_config.DateColumn('Last deal', format='DD MMM YYYY')})
            kit.caption('Companies under ₹5,000 Cr market cap, last 30 days of bulk and block deals, market makers '
                        'excluded. Studies find prices often run up before a bulk buy and give back from day two, so '
                        'read this as who is accumulating, not a buy list.')

    with tabs[2]:
        if d.empty:
            kit.empty('No deals yet.')
        else:
            c1, c2 = st.columns([1, 2])
            days = c1.selectbox('Period', [7, 30, 90], index=1, format_func=lambda x: f'Last {x} days', key='dl_days')
            show_mm = c2.toggle('Include market makers', value=False, key='dl_mm')
            rows = d[d['date'] > d['date'].max() - pd.Timedelta(days=days)]
            if not show_mm:
                rows = rows[~rows['client_is_market_maker'].astype('boolean').fillna(False)]
            rows = rows[rows['is_primary'].astype('boolean').fillna(False)].sort_values(['date', 'value'], ascending=False)
            st.dataframe(rows.assign(link=rows['nse_symbol'].map(kit.company_href))[
                ['link', 'date', 'company', 'client_name', 'side', 'quantity', 'price', 'value_cr', 'pct_of_mcap',
                 'trades', 'counterparties', 'feeds', 'listed_on']], hide_index=True, width='stretch', height=560,
                column_config={'link': st.column_config.LinkColumn('', display_text='Open', width='small', pinned=True),
                               'date': st.column_config.DateColumn('Date', format='DD MMM YYYY'), 'company': 'Company',
                               'client_name': 'Client', 'side': 'Side',
                               'quantity': st.column_config.NumberColumn('Shares', format='%,.0f'),
                               'price': st.column_config.NumberColumn('Price', format='%.2f'),
                               'value_cr': st.column_config.NumberColumn('Value (₹ Cr)', format='%,.2f'),
                               'pct_of_mcap': st.column_config.NumberColumn('% of mcap', format='%.2f%%'),
                               'trades': st.column_config.NumberColumn('Tranches', format='%d'),
                               'counterparties': 'Other side', 'feeds': 'Feed', 'listed_on': 'Exchange'})
            kit.caption('Same client, stock, day and side are one row; a trade printed in both the bulk and block feed '
                        'counts once.')

    with tabs[3]:
        s = ctx.sast
        if s.empty:
            kit.empty('SAST filings arrive with the daily NSE events collection.')
        else:
            s = s.copy()
            s['transaction_date'] = pd.to_datetime(s['transaction_date'], errors='coerce')
            outside = st.toggle('Only outside the promoter group', value=True, key='sast_out',
                                help='Funds and individuals crossing 5% or moving 2%+; insider filings already cover promoters')
            if outside:
                s = s[~s['is_promoter'].astype('boolean').fillna(False)]
            s = s.sort_values('transaction_date', ascending=False)
            st.dataframe(s.assign(link=s['symbol'].map(kit.company_href))[
                ['link', 'transaction_date', 'company', 'acquirer_name', 'action_type', 'mode', 'shares_traded',
                 'percent_equity_traded', 'post_stake_pct', 'regulation']], hide_index=True, width='stretch', height=560,
                column_config={'link': st.column_config.LinkColumn('', display_text='Open', width='small'),
                               'transaction_date': st.column_config.DateColumn('Date', format='DD MMM YYYY'),
                               'company': 'Company', 'acquirer_name': 'Acquirer / seller', 'action_type': 'Action',
                               'mode': 'Mode', 'shares_traded': st.column_config.NumberColumn('Shares', format='%,.0f'),
                               'percent_equity_traded': st.column_config.NumberColumn('% traded', format='%+.2f%%'),
                               'post_stake_pct': st.column_config.NumberColumn('Stake after', format='%.2f%%'),
                               'regulation': 'Rule'})
