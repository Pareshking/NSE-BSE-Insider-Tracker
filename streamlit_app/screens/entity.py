"""Person / fund page (/entity?id=...): what one promoter, officer or fund
has done across all companies."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from ui import kit

from insiders_clean import fund_managers, investors, participants, signals
from screens.ctx import load, need_data, split_since, with_prices, with_sparks


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
            hits = people[people['name'].str.contains(q, case=False, na=False, regex=False)].head(30)
            st.html('<div class="q-list">' + ''.join(
                f'<div class="q-row"><a href="{kit.entity_href(i)}" target="_self"><b>{kit.esc(str(n))}</b></a></div>'
                for i, n in zip(hits['id'], hits['name'])) + '</div>' if len(hits) else '<p class="evl">No match. Try part of the name.</p>')
        return
    # One row per real trade: the NSE and BSE copies of a filing are the same trade.
    t = ctx.trades[(ctx.trades['person_id'] == eid) & ctx.trades['is_primary'].astype('boolean').fillna(False)]
    # An investor is every name of its investor group together (the same investor under different spellings).
    d, group_id = investors.profile_deals(ctx.deals, eid)
    shown = d['investor_group'].dropna().iloc[0] if len(d) and 'investor_group' in d and d['investor_group'].notna().any() else None
    name = (t['person_name'].dropna().iloc[0] if len(t) else shown or d['client_name'].dropna().iloc[0] if len(d) else eid)
    kit.head(str(name), 'Every filing and deal under this name, across companies.')
    if not d.empty and d['client_is_market_maker'].astype('boolean').fillna(False).any():
        st.html('<p class="evl">' + kit.tag('Market maker', 'mute') + ' buys and sells in near-equal amounts: '
                'liquidity, left out of signals</p>')
    if not d.empty and 'client_type' in d:
        # Type read from the name (insiders_clean/participants.py); the names this investor deals under; the fund manager
        # the name itself names (fund_managers.csv), with the other funds of that manager seen in the deals.
        big = d.sort_values('value', ascending=False).iloc[0]
        kind = participants.TYPES.get(big['client_type'], big['client_type'])
        names = sorted(set(d['client_name'].dropna()))
        manager, sub, why = fund_managers.manager_of(big['client_name'])
        st.html(f'<p class="evl">{kit.esc(kind)} · {big["client_type_confidence"]} confidence ({kit.esc(str(big["client_type_rule"]))})'
                + (f' · deals under {kit.plural(len(names), "name")}: {kit.esc("; ".join(names[:6]))}{" …" if len(names) > 6 else ""}'
                   if len(names) > 1 else '') + '</p>')
        if manager:
            mgr = fund_managers.add_manager_columns(ctx.deals)
            mates = mgr[mgr['manager'].eq(manager) & ~mgr['client_id'].isin(set(d['client_id']))].drop_duplicates('client_id')
            links = ', '.join(f'<a href="{kit.entity_href(i)}" target="_self">{kit.esc(str(n))}</a>'
                              for i, n in zip(mates['investor_group_id'].fillna(mates['client_id']).head(8), mates['client_name'].head(8)))
            st.html(f'<p class="evl">Fund manager named in the fund name: <b>{kit.esc(manager)}</b>'
                    + (' · likely sub-advised (another sponsor\'s name leads)' if sub else '')
                    + (f' · other funds of this manager: {links}' if links else '') + '</p>')
    mk = ctx.eligible[ctx.eligible['person_id'] == eid]
    # Owner's spec: capital deployed in 12 months, active tickers; win rate and
    # holding period come with the signal lab (docs/DATA_TO_PAGES.md S21).
    # 12 months back from the data's date, not this person's last trade (audit W8); a deal that is
    # the same trade as this person's own filing is counted once, under the filing (audit W7).
    seen = pd.to_datetime(mk['broadcast_date'], errors='coerce')
    yr = mk[seen > ctx.ref - pd.Timedelta(days=365)] if len(mk) and ctx.ref is not None else mk
    bought_ins = pd.to_numeric(yr.loc[yr['side'] == 'BUY', 'value'], errors='coerce').sum() if len(yr) else 0.0
    deals_end = ctx.deals['date'].max() if not ctx.deals.empty else None
    d_own = d[~signals.deals_also_filed(d, ctx.trades)] if len(d) else d
    dy = d_own[d_own['date'] > deals_end - pd.Timedelta(days=365)] if len(d_own) and deals_end is not None else d_own
    bought_deals = pd.to_numeric(dy.loc[dy['side'] == 'BUY', 'value'], errors='coerce').sum() if len(dy) else 0.0
    active = pd.concat([yr['isin'] if len(yr) else pd.Series(dtype=object),
                        dy['isin'] if len(dy) else pd.Series(dtype=object)]).dropna().nunique()
    # Every open-market buy valued at today's close, shares restated for any split or
    # bonus since; value-weighted, and the share of buys now above the price paid.
    buys = with_prices(mk[mk['side'] == 'BUY'], ctx.prices)
    f = split_since(buys, ctx.prices)
    paid = pd.to_numeric(buys['price'], errors='coerce') * f
    now = pd.to_numeric(buys['latest_close'], errors='coerce')
    shares = pd.to_numeric(buys['quantity'], errors='coerce') / f
    ok = shares.gt(0) & paid.gt(0) & now.gt(0)
    cost, worth = (shares * paid)[ok].sum(), (shares * now)[ok].sum()
    pnl = (kit.Tile('Open-market buys, P&L', kit.pct((worth / cost - 1) * 100, 1, signed=True),
                    f'{kit.rupees(cost)} paid, worth {kit.rupees(worth)} at the latest close · '
                    f'{(now[ok] > paid[ok]).mean() * 100:.0f}% of {kit.plural(int(ok.sum()), "buy")} in profit',
                    'up' if worth > cost else 'down')
           if cost > 0 else None)
    kit.tiles([
        kit.Tile('Capital deployed, 12 months', kit.rupees(bought_ins + bought_deals),
                 f'open-market insider buys {kit.rupees(bought_ins)} · other deal buys {kit.rupees(bought_deals)}'),
        kit.Tile('Active companies, 12 months', kit.count(active), 'with an open-market buy, sale or deal'),
        kit.Tile('Net, all data', kit.rupees((mk['signed_value'].sum() if len(mk) else 0) + (d_own['signed_value'].sum() if len(d_own) else 0),
                                              signed=True), f'{kit.count(len(t))} insider filings · {kit.count(len(d))} deals'),
        *([pnl] if pnl else []),
    ])
    if len(t):
        with kit.card('Insider filings', 'en_it'):
            s = t.sort_values('broadcast_date', ascending=False)
            kit.table(with_sparks(s.assign(seen=pd.to_datetime(s['broadcast_date'], errors='coerce'),
                                           mode=s['mode_raw'].fillna(s['kind'])), ctx), [
                kit.Col('company', 'Company', 'co'), kit.Col('side', 'Side', 'side'),
                kit.Col('value', 'Value', 'money'), kit.Col('pct_of_mcap', '% of mcap', 'bar'),
                kit.Col('seen', 'Made public', 'date'), kit.Col('mode', 'Mode as filed', phone=False),
                kit.Col('spark', '1Y price · insider trades', 'spark', phone=False)], limit=100)
    ref_deals = pd.Timestamp(ctx.deals['date'].max()) if not ctx.deals.empty else None
    per = investors.by_company(d, ref_deals, 90) if len(d) else pd.DataFrame()
    if len(per):
        with kit.card('Net by company', 'en_net', 'last 90 days, bulk and block deals'):
            kit.table(per, [kit.Col('company', 'Company', 'co'), kit.Col('net', 'Net', 'smoney'), kit.Col('buy', 'Bought', 'money', phone=False),
                            kit.Col('sell', 'Sold', 'money', phone=False), kit.Col('pct', 'Share of company', 'spct'),
                            kit.Col('last', 'Last deal', 'date', phone=False)], limit=30, key='en_net_t', keep_empty=True)
    if len(d):
        with kit.card('Deals', 'en_dl'):
            s = d.sort_values('date', ascending=False)
            kit.table(s, [
                kit.Col('company', 'Company', 'co'), kit.Col('date', 'Date', 'date'), kit.Col('side', 'Side', 'side'),
                kit.Col('quantity', 'Shares', 'shares', phone=False), kit.Col('price', 'Price', 'price', phone=False),
                kit.Col('value', 'Value', 'money'), kit.Col('pct_of_mcap', '% of mcap', 'bar'),
                kit.Col('counterparties', 'Other side that day', phone=False, wrap=True), kit.Col('feeds', 'Feed', phone=False)], limit=100)
