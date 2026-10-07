"""Today: the two-minute morning check. What did insiders and big money do in
the latest session, and what was held back for a look."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from ui import kit
from ui.kit import esc

from insiders_clean import signals
from screens.ctx import load, need_data


def _session(ctx) -> tuple[pd.DataFrame, pd.Timestamp]:
    """The latest day with open-market filings (a day with only ESOPs and
    pledges, or a holiday, says nothing about buying)."""
    e = ctx.eligible
    day = e['seen'].max().normalize() if not e.empty else ctx.ref
    return e[e['seen'].dt.normalize() == day], day


def _spot_card(r, ctx) -> str:
    sym = r.get('nse_symbol') or ''
    company = r.get('company') or sym
    who = esc(str(r.get('person_name') or 'An insider'))
    role = kit.role(r.get('person_role'))
    badges = [kit.tag('Spotlight', 'info')]
    if r.get('pct_90d', 0) >= signals.FLOAT_ABSORBER_PCT_90D:
        badges.append(kit.tag('Float absorber', 'info'))
    sh = signals.latest_shareholding(ctx.shareholding)
    pledge = sh.loc[sh['isin'] == r.get('isin'), 'promoter_pledge_pct'] if not sh.empty else pd.Series(dtype=float)
    if len(pledge) and pd.notna(pledge.iloc[0]):
        p = float(pledge.iloc[0])
        badges.append(kit.tag(f'Pledge {p:.0f}%', 'warn' if p > signals.HIGH_PLEDGE_PCT else 'mute'))
    return (f'<div class="spot"><div class="spot-h"><a href="{kit.company_href(sym)}" target="_self">{esc(company)}</a>'
            f'<span class="spot-sym">{esc(sym)}</span></div>'
            f'<div class="spot-line"><b>{who}</b> ({esc(role)}) bought <b class="num">{kit.rupees(r["value_30d"])}</b>'
            f' in the open market over 30 days, <b class="num">{kit.pct(r["pct_30d"])}</b> of market cap'
            f' across {int(r["trades_30d"])} trade{"s" if r["trades_30d"] != 1 else ""}.</div>'
            f'<div class="spot-line">Last filing {kit.day(r["last_seen"])}.</div>'
            f'<div class="spot-badges">{" ".join(badges)}</div></div>')


def render():
    ctx = load()
    kit.head('Today', 'What promoters, directors and large investors did in the latest session, '
                      'with ESOPs, gifts, pledges and transfers left out.')
    if not need_data(ctx):
        return
    ref = ctx.ref
    sess, sess_day = _session(ctx)
    prom = sess[sess['person_role'].isin(signals.PROMOTER_ROLES)]
    spot = signals.spotlight(ctx.eligible, ref)
    clus = signals.clusters(ctx.eligible, ref)
    deals_day = pd.DataFrame()
    if not ctx.deals.empty:
        d = ctx.deals
        mm = d['client_is_market_maker'].astype('boolean').fillna(False) if 'client_is_market_maker' in d else False
        deals_day = d[(~mm) & (d['date'] == d['date'].max())]
    net = prom['signed_value'].sum()
    kit.tiles([
        kit.Tile('Promoter net, open market', kit.rupees(net, signed=True),
                 f'{prom["isin"].nunique()} companies, filed {kit.day(sess_day)}', 'up' if net > 0 else 'down' if net < 0 else ''),
        kit.Tile('Spotlight buys', kit.count(len(spot)), f'{signals.SPOTLIGHT_PCT_30D}%+ of market cap by one person in 30 days'),
        kit.Tile('Clusters', kit.count(len(clus)), '2+ buyers in 30 days incl. an officer or separate families'),
        kit.Tile('Deals, real buyers', kit.rupees(deals_day['value'].sum() if not deals_day.empty else None),
                 f'{len(deals_day)} legs on {kit.day(deals_day["date"].max()) if not deals_day.empty else "—"}, market makers excluded'),
    ])

    with kit.card('High-conviction buys', 'spot', f'one person, {signals.SPOTLIGHT_PCT_30D}%+ of market cap in 30 days'):
        if spot.empty:
            kit.empty('No insider crossed the spotlight line in the last 30 days.')
        else:
            st.html('<div class="spot-grid">' + ''.join(_spot_card(r, ctx) for _, r in spot.head(6).iterrows()) + '</div>')

    with kit.card('Session feed', 'feed', f'filed on {kit.day(sess_day)}, largest share of market cap first'):
        view = st.segmented_control('Show', ['Insider buys', 'Insider sells', 'Big deals'], default='Insider buys',
                                    label_visibility='collapsed', key='today_view')
        if view == 'Big deals':
            rows = deals_day.sort_values('value', ascending=False) if not deals_day.empty else deals_day
            if rows.empty:
                kit.empty('No bulk or block deals by real buyers or sellers in the latest session.')
            else:
                st.dataframe(rows.assign(link=rows['nse_symbol'].map(kit.company_href))[
                    ['link', 'company', 'client_name', 'side', 'value_cr', 'price', 'pct_of_mcap', 'counterparties', 'feeds']],
                    hide_index=True, width='stretch', column_config={
                        'link': st.column_config.LinkColumn('', display_text='Open', width='small'),
                        'company': 'Company', 'client_name': 'Client', 'side': 'Side',
                        'value_cr': st.column_config.NumberColumn('Value (₹ Cr)', format='%,.2f'),
                        'price': st.column_config.NumberColumn('Price', format='%.2f'),
                        'pct_of_mcap': st.column_config.NumberColumn('% of mcap', format='%.2f%%'),
                        'counterparties': 'Other side', 'feeds': 'Feed'})
        else:
            side = 'BUY' if view == 'Insider buys' else 'SELL'
            rows = sess[(sess['side'] == side) & ~sess['is_token']].sort_values('pct_of_mcap', ascending=False)
            if rows.empty:
                kit.empty(f'No open-market insider {"buys" if side == "BUY" else "sales"} in the latest session.')
            else:
                show = rows.assign(link=rows['nse_symbol'].map(kit.company_href),
                                   role=rows['person_role'].map(kit.role))
                st.dataframe(show[['link', 'company', 'person_name', 'role', 'value_cr', 'pct_of_mcap', 'holding_change_pct',
                                   'trade_date_to', 'listed_on']], hide_index=True, width='stretch', column_config={
                    'link': st.column_config.LinkColumn('', display_text='Open', width='small'),
                    'company': 'Company', 'person_name': 'Person', 'role': 'Role',
                    'value_cr': st.column_config.NumberColumn('Value (₹ Cr)', format='%,.2f'),
                    'pct_of_mcap': st.column_config.NumberColumn('% of mcap', format='%.3f%%'),
                    'holding_change_pct': st.column_config.NumberColumn('Own holding Δ', format='%+.1f%%'),
                    'trade_date_to': st.column_config.DateColumn('Traded', format='DD MMM YYYY'), 'listed_on': 'Exchange'})
        kit.caption('Token buys (under ₹25 L in companies above ₹5,000 Cr) are not listed. '
                    'Company links open the full history.')

    held = ctx.trades.copy()
    held['seen'] = pd.to_datetime(held['broadcast_date'], errors='coerce')
    held = held[held['needs_review'].astype('boolean').fillna(False) & (held['seen'] > ref - pd.Timedelta(days=10))]
    with st.expander(f'Needs a look · {len(held)} filings held back in the last 10 days'):
        if held.empty:
            kit.empty('Nothing held back.')
        for _, r in held.head(40).iterrows():
            st.html(f'<div class="q-row"><b>{esc(str(r["company"]))}</b> · {esc(str(r["person_name"]))} · '
                    f'{kit.rupees(r["value"])} · <span class="mono">{esc(str(r["flags"]).replace(",", ", "))}</span></div>')
        kit.caption('Held back from every ranking until checked against the exchange filing.')
