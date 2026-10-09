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
from screens.ctx import load, need_data, with_prices, with_sparks


def render():
    ctx = load()
    kit.head('Deals & big stakes', 'Who sold, who absorbed it, and where real funds are accumulating. Market '
                                   'makers, who buy and sell in equal measure, are left out.')
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
            kit.table(with_sparks(h.assign(who=h['seller_is_promoter'].map({True: ['Promoter'], False: []}),
                                           size=h['large'].map({True: ['Large'], False: []})), ctx), [
                kit.Col('company', 'Company', 'co'), kit.Col('date', 'Date', 'date'),
                kit.Col('sellers', 'Sold by', sub=''), kit.Col('who', 'Seller', 'tags'),
                kit.Col('buyers', 'Absorbed by'), kit.Col('matched_value', 'Matched', 'money'),
                kit.Col('pct_of_mcap_sold', '% of mcap sold', 'bar'), kit.Col('size', '', 'tags', phone=False),
                kit.Col('spark', '1Y price · insider trades', 'spark', phone=False)], limit=100, download='handshakes')
            kit.caption('A promoter seller is recognised when the same name filed as promoter or promoter group for that '
                        'company. "Absorbed by" lists the real buyers on the other side that day.')

    with tabs[1]:
        acc = signals.small_cap_accumulation(d)
        if acc.empty:
            kit.empty('No small caps net-bought by real funds in the last 30 days.')
        else:
            kit.table(with_sparks(with_prices(acc, ctx.prices), ctx), [
                kit.Col('company', 'Company', 'co'), kit.Col('net_buyers', 'Net buyers', phone=False),
                kit.Col('net_value', 'Net bought', 'money'), kit.Col('net_pct', '% of mcap', 'bar'),
                kit.Col('market_cap', 'Mkt cap', 'money', phone=False), kit.Col('last', 'Last deal', 'date'),
                kit.Col('range', '52W range · CMP', 'range', phone=False),
                kit.Col('spark', '1Y price · insider trades', 'spark', phone=False)], limit=100, download='accumulation')
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
            kit.table(rows, [
                kit.Col('company', 'Company', 'co'), kit.Col('date', 'Date', 'date'),
                kit.Col('client_name', 'Client', 'client', sub='counterparties'), kit.Col('side', 'Side', 'side'),
                kit.Col('quantity', 'Shares', 'shares', phone=False), kit.Col('price', 'Price', 'price', phone=False),
                kit.Col('value', 'Value', 'money'), kit.Col('pct_of_mcap', '% of mcap', 'bar'),
                kit.Col('feeds', 'Feed', phone=False)], limit=200, download='deals')
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
            kit.table(s.assign(nse_symbol=s['symbol']), [
                kit.Col('company', 'Company', 'co'), kit.Col('transaction_date', 'Date', 'date'),
                kit.Col('acquirer_name', 'Acquirer / seller', sub='mode'), kit.Col('action_type', 'Action'),
                kit.Col('shares_traded', 'Shares', 'shares', phone=False),
                kit.Col('percent_equity_traded', '% traded', 'spct'), kit.Col('post_stake_pct', 'Stake after', 'pct'),
                kit.Col('regulation', 'Rule', phone=False)], limit=200, download='sast')
