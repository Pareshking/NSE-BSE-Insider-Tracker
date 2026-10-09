"""Person / fund page (/entity?id=...): what one promoter, officer or fund
has done across all companies."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from ui import kit

from screens.ctx import load, need_data


def render():
    ctx = load()
    if not need_data(ctx):
        return
    eid = st.query_params.get('id')
    if not eid:
        kit.head('Person or fund', 'Open a person or fund from any table, or search below.')
        q = st.text_input('Search', placeholder='Name', key='en_q')
        if q:
            people = pd.concat([ctx.trades[['person_id', 'person_name']].rename(columns={'person_id': 'id', 'person_name': 'name'}),
                                ctx.deals[['client_id', 'client_name']].rename(columns={'client_id': 'id', 'client_name': 'name'})
                                if not ctx.deals.empty else pd.DataFrame(columns=['id', 'name'])]).dropna().drop_duplicates('id')
            hits = people[people['name'].str.contains(q, case=False, na=False)].head(30)
            st.dataframe(hits.assign(link=hits['id'].map(kit.entity_href))[['link', 'name']], hide_index=True, width='stretch',
                         column_config={'link': st.column_config.LinkColumn('', display_text='Open', width='small'), 'name': 'Name'})
        return
    t = ctx.trades[ctx.trades['person_id'] == eid]
    d = ctx.deals[ctx.deals['client_id'] == eid] if not ctx.deals.empty else pd.DataFrame()
    name = (t['person_name'].dropna().iloc[0] if len(t) else d['client_name'].dropna().iloc[0] if len(d) else eid)
    kit.head(str(name), 'Every filing and deal under this name, across companies.')
    if not d.empty and d['client_is_market_maker'].astype('boolean').fillna(False).any():
        kit.note('Market maker.', 'This client buys and sells in near-equal amounts at high volume; its deals are '
                                  'liquidity, not positions, and are left out of signals.')
    mk = t[t['is_market'].astype('boolean').fillna(False)]
    # Owner's spec: capital deployed in 12 months, active tickers; win rate and
    # holding period come with the signal lab (docs/DATA_TO_PAGES.md S21).
    seen = pd.to_datetime(mk['broadcast_date'], errors='coerce')
    yr = mk[seen > seen.max() - pd.Timedelta(days=365)] if len(mk) else mk
    bought_ins = pd.to_numeric(yr.loc[yr['side'] == 'BUY', 'value'], errors='coerce').sum() if len(yr) else 0.0
    dy = d[d['date'] > d['date'].max() - pd.Timedelta(days=365)] if len(d) else d
    bought_deals = pd.to_numeric(dy.loc[dy['side'] == 'BUY', 'value'], errors='coerce').sum() if len(dy) else 0.0
    active = pd.concat([yr['isin'] if len(yr) else pd.Series(dtype=object),
                        dy['isin'] if len(dy) else pd.Series(dtype=object)]).dropna().nunique()
    kit.tiles([
        kit.Tile('Capital deployed, 12 months', kit.rupees(bought_ins + bought_deals),
                 f'open-market insider buys {kit.rupees(bought_ins)} · deal buys {kit.rupees(bought_deals)}'),
        kit.Tile('Active companies, 12 months', kit.count(active), 'with an open-market buy, sale or deal'),
        kit.Tile('Net, all data', kit.rupees((mk['signed_value'].sum() if len(mk) else 0) + (d['signed_value'].sum() if len(d) else 0),
                                              signed=True), f'{kit.count(len(t))} insider filings · {kit.count(len(d))} deals'),
        kit.Tile('Win rate · holding period', 'Pending', 'measured by the signal lab'),
    ])
    if len(t):
        with kit.card('Insider filings', 'en_it'):
            s = t.sort_values('broadcast_date', ascending=False)
            st.dataframe(s.assign(link=s['nse_symbol'].map(kit.company_href), person_role=s['person_role'].map(kit.role))[
                ['link', 'company', 'person_role', 'side', 'mode_raw', 'value_cr', 'pct_of_mcap', 'trade_date_to']],
                hide_index=True, width='stretch', column_config={
                    'link': st.column_config.LinkColumn('', display_text='Open', width='small'), 'company': 'Company',
                    'person_role': 'Role', 'side': 'Side', 'mode_raw': 'Mode as filed',
                    'value_cr': st.column_config.NumberColumn('Value (₹ Cr)', format='%,.2f'),
                    'pct_of_mcap': st.column_config.NumberColumn('% of mcap', format='%.3f%%'),
                    'trade_date_to': st.column_config.DateColumn('Traded', format='DD MMM YYYY')})
    if len(d):
        with kit.card('Deals', 'en_dl'):
            s = d.sort_values('date', ascending=False)
            st.dataframe(s.assign(link=s['nse_symbol'].map(kit.company_href))[
                ['link', 'date', 'company', 'side', 'quantity', 'price', 'value_cr', 'feeds']], hide_index=True, width='stretch',
                column_config={'link': st.column_config.LinkColumn('', display_text='Open', width='small'),
                               'date': st.column_config.DateColumn('Date', format='DD MMM YYYY'), 'company': 'Company', 'side': 'Side',
                               'quantity': st.column_config.NumberColumn('Shares', format='%,.0f'),
                               'price': st.column_config.NumberColumn('Price', format='%.2f'),
                               'value_cr': st.column_config.NumberColumn('Value (₹ Cr)', format='%,.2f'), 'feeds': 'Feed'})
    kit.caption('What happened after this person\'s or fund\'s past buys arrives with the signal lab.')
