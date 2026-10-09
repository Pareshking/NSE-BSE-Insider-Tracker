"""Today's pulse: the two-minute morning check. Did smart money take a
high-conviction position in the latest session?

Built to the owner's page spec (07-08 Oct 2026): four tiles (net promoter
flow, highest-conviction buy, cluster formations, institutional handshakes),
high-conviction buy cards, a session feed grouped by company with chips, and
the "needs a look" quarantine."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from ui import kit
from ui.kit import esc

from insiders_clean import signals
from screens.ctx import load, need_data, with_prices, with_sparks

CHIPS = ['All', 'Promoter buys only', 'Bulk deals', 'Large handshakes']
REASONS = {'value_over_25pct_of_mcap': "value is over 25% of the company's market cap",
           'holding_jump_on_market_trade': 'holding multiplied 20x+ on a market trade',
           'holding_change_differs_from_quantity': "holding change doesn't match the quantity",
           'missing_or_zero_value': 'market trade with no value',
           'mode_contradicts_side': 'mode says buy, type says sell (or the reverse)',
           'dates_out_of_order': 'dates out of order', 'trade_date_in_future': 'trade date in the future',
           'unmatched_security': 'company not found in NSE/BSE lists',
           'unrecognised_mode': 'mode of acquisition not stated'}


def _size(ctx, isin) -> str:
    s = ctx.securities
    if s.empty or 'mcap_category' not in s:
        return ''
    hit = s.loc[s['isin'] == isin, 'mcap_category']
    return str(hit.iloc[0]) if len(hit) and pd.notna(hit.iloc[0]) else ''


def _card(r, ctx, day) -> str:
    sym, company = r.get('nse_symbol') or '', r.get('company') or r.get('nse_symbol') or ''
    head_bits = [b for b in (_size(ctx, r['isin']),
                             f'{kit.rupees(r["market_cap"])} mcap' if pd.notna(r['market_cap']) else '') if b]
    if pd.notna(r.get('pct_of_float')):
        share = f'{kit.pct(r["pct_of_float"])} of float'
    else:
        share = f'{kit.pct(r["pct_of_mcap"])} of market cap; float not loaded'
    price = r['value'] / r['qty'] if pd.notna(r.get('qty')) and r.get('qty') else None
    nth = signals.buys_in_days(ctx.eligible, r['isin'], r['person_id'], day + pd.Timedelta(days=1), 14)
    pledge = signals.pledge_by_isin(ctx.shareholding).get(r['isin'])
    if pledge is None or pd.isna(pledge):
        pledge_txt, tone = 'Pledge not loaded yet', 'mute'
    elif pledge == 0:
        pledge_txt, tone = 'Zero promoter pledge', 'buy'
    else:
        pledge_txt, tone = f'Promoter pledge {pledge:.1f}%', 'warn' if pledge > signals.HIGH_PLEDGE_PCT else 'mute'
    who = f'{kit.role(r["person_role"]).capitalize()} {r["person_name"]}'
    tranches = f' across {int(r["trades"])} tranches' if r['trades'] > 1 else ''
    pr = ctx.prices[ctx.prices['isin'] == r['isin']] if not ctx.prices.empty else ctx.prices
    cmp_ = pr['latest_close'].iloc[0] if len(pr) else None
    if price and cmp_ is not None and pd.notna(cmp_):
        move = (cmp_ / price - 1) * 100
        price_line = (f'Paid <b class="num">₹{price:,.2f}</b> · now <b class="num">₹{cmp_:,.2f}</b> '
                      f'<span class="{"up" if move >= 0 else "down"}">({move:+.1f}%)</span>')
    else:
        price_line = f'Paid <b class="num">₹{price:,.2f}</b>' if price else 'Price paid not in the filing'
    if len(pr):
        price_line += kit.range_bar(cmp_, pr['low_52w'].iloc[0], pr['high_52w'].iloc[0])
    context = kit.tag(f'Buy #{nth} in 14 days', 'info') if nth > 1 else kit.tag('First buy in 14 days', 'mute')
    return (f'<div class="spot"><div class="spot-h"><a href="{kit.company_href(sym)}" target="_self">{esc(str(company))}</a>'
            f'<span class="spot-sym">{esc(sym)}</span></div>'
            + (f'<div class="cap">{esc(" · ".join(head_bits))}</div>' if head_bits else '')
            + f'<div class="spot-line"><b>{esc(who)}</b> bought <b class="num">{kit.rupees(r["value"])}</b> '
            f'({esc(share)}) in the open market{tranches}.</div>'
            f'<div class="spot-line">{price_line}</div>'
            f'<div class="spot-badges">{context} {kit.tag(pledge_txt, tone)}</div></div>')


def _session(ctx):
    e = ctx.eligible
    day = e['seen'].max().normalize()
    sess = signals.session_by_company(e, day, ctx.shareholding)
    if not sess.empty:
        qty = (e[e['seen'].dt.normalize() == day].assign(q=pd.to_numeric(e['quantity'], errors='coerce'))
               .groupby(['isin', 'person_id', 'side'])['q'].sum())
        sess['qty'] = [qty.get((i, p, s)) for i, p, s in zip(sess['isin'], sess['person_id'], sess['side'])]
    return sess, day


CATALYSTS = ['fund_raising', 'preferential', 'buyback', 'bonus', 'split', 'rights']


def _outside_holders(ctx):
    """S12 for the latest day with SAST filings: funds and individuals
    outside the promoter group crossing 5% or moving 2%+ (docs/DATA_TO_PAGES.md)."""
    s = ctx.sast
    with kit.card('Outside investors crossing 5% or moving 2%+', 'today_sast', 'SAST Regulation 29, latest filing day'):
        if s.empty:
            kit.empty('SAST filings arrive with the daily NSE events collection.')
            return
        s = s.copy()
        s['seen'] = pd.to_datetime(s['broadcast_ts'], errors='coerce', format='mixed', dayfirst=True).dt.normalize()
        s = s[~s['is_promoter'].astype('boolean').fillna(False)]
        latest = s['seen'].max()
        s = s[s['seen'] == latest].sort_values('percent_equity_traded', key=lambda x: x.abs(), ascending=False)
        if s.empty:
            kit.empty('No SAST filings by outside investors on the latest filing day.')
            return
        kit.table(s.assign(nse_symbol=s['symbol']), [
            kit.Col('company', 'Company', 'co'), kit.Col('acquirer_name', 'Investor', 'text', sub='mode'),
            kit.Col('action_type', 'Action'), kit.Col('percent_equity_traded', '% traded', 'spct'),
            kit.Col('post_stake_pct', 'Stake after', 'pct')], limit=15)
        kit.caption(f'Filed {kit.day(latest)}. Promoters are left out here: their trades are in the insider filings above.')


def _coming_up(ctx):
    """S14: board meetings in the next 10 days that will consider fund raising,
    a preferential issue, buyback, bonus, split or rights issue."""
    m = ctx.meetings
    with kit.card('Coming up: boards considering capital moves', 'today_cat', 'next 10 days'):
        if m.empty:
            kit.empty('Board meetings arrive with the daily NSE events collection.')
            return
        m = m.copy()
        m['meeting_date'] = pd.to_datetime(m['meeting_date'], errors='coerce')
        today = pd.Timestamp.now().normalize()
        cols = [c for c in CATALYSTS if c in m]
        rows = m[(m['meeting_date'] >= today) & (m['meeting_date'] <= today + pd.Timedelta(days=10))
                 & m[cols].astype('boolean').fillna(False).any(axis=1)].sort_values('meeting_date')
        if rows.empty:
            kit.empty('No board meetings on fund raising, preferential issues, buybacks, bonuses, splits or rights '
                      'in the next 10 days.')
            return
        kit.table(rows.assign(nse_symbol=rows['symbol'], what=rows['purposes'].str.replace('_', ' ').str.replace(',', ', ')), [
            kit.Col('meeting_date', 'Meeting', 'date'), kit.Col('company', 'Company', 'co'),
            kit.Col('what', 'To consider')], limit=20)

def render():
    ctx = load()
    kit.head("Today's pulse", 'Open-market insider trades and big-money deals in the latest session. ESOPs, gifts, '
                              'pledges and token buys are left out.')
    if not need_data(ctx):
        return
    sess, day = _session(ctx)
    end = day + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    prom = sess[sess['person_role'].isin(signals.PROMOTER_ROLES)] if not sess.empty else sess
    net = (prom['value'] * prom['side'].map({'BUY': 1, 'SELL': -1})).sum() if not prom.empty else 0.0

    # A buy filed today by someone whose open-market buying in that company
    # over 30 days reaches the spotlight line (docs/SIGNALS.md).
    spot = signals.spotlight(ctx.eligible, end)
    buys = sess[(sess['side'] == 'BUY') & ~sess['is_token']] if not sess.empty else sess
    hc = buys.merge(spot[['isin', 'person_id', 'pct_30d']], on=['isin', 'person_id']) if not buys.empty else buys
    hc = hc.assign(impact=hc['pct_of_float'].fillna(hc['pct_of_mcap'])).sort_values('impact', ascending=False) \
        if not hc.empty else hc
    clus = signals.clusters(ctx.eligible, end)
    clus_today = clus[pd.to_datetime(clus['last_seen']).dt.normalize() == day] if not clus.empty else clus
    hs = signals.handshakes(ctx.deals, ctx.trades, days=1)
    hs_day = hs['date'].max() if not hs.empty else None

    if not hc.empty:
        b = hc.iloc[0]
        share = (kit.pct(b['pct_of_float']) + ' of float') if pd.notna(b['pct_of_float']) else \
            (kit.pct(b['pct_of_mcap']) + ' of mcap')
        best = kit.Tile('Highest-conviction buy today', str(b['nse_symbol']), f'{kit.rupees(b["value"])} · {share}')
    else:
        best = kit.Tile('Highest-conviction buy today', '—', 'No buy crossed the spotlight line today')
    kit.tiles([
        kit.Tile('Net open-market promoter flow', kit.rupees(net, signed=True),
                 f'{prom["isin"].nunique() if not prom.empty else 0} companies, filed {kit.day(day)}',
                 'up' if net > 0 else 'down' if net < 0 else ''),
        best,
        kit.Tile('Cluster formations', kit.count(len(clus_today)), '2+ insiders buying within 30 days, crossed today'),
        kit.Tile('Institutional handshakes', kit.rupees(hs['matched_value'].sum() if not hs.empty else None),
                 f'{len(hs)} buyer-seller matches on {kit.day(hs_day)}, market makers excluded' if hs_day is not None
                 else 'No matched deals'),
    ])

    with kit.card('High-conviction buys today', 'spot',
                  f'filed {kit.day(day)} · {signals.SPOTLIGHT_PCT_30D}%+ of market cap by one person over 30 days'):
        if hc.empty:
            kit.empty('No open-market buy filed today reaches the high-conviction line.')
        else:
            st.html('<div class="spot-grid">' + ''.join(_card(r, ctx, day) for _, r in hc.head(4).iterrows()) + '</div>')

    with kit.card('Session feed', 'feed', f'{kit.day(day)} · tranches combined · largest float impact first'):
        chip = st.segmented_control('Show', CHIPS, default='All', label_visibility='collapsed', key='today_chip')
        if chip in ('All', 'Promoter buys only', None):
            rows = sess[~sess['is_token']] if not sess.empty else sess
            if chip == 'Promoter buys only' and not rows.empty:
                rows = rows[(rows['side'] == 'BUY') & rows['person_role'].isin(signals.PROMOTER_ROLES)]
            if rows.empty:
                kit.empty('No open-market insider trades in this session.')
            else:
                rows = rows.assign(impact=rows['pct_of_float'].fillna(rows['pct_of_mcap'])).sort_values('impact', ascending=False)
                kit.table(with_sparks(with_prices(rows, ctx.prices), ctx), [
                    kit.Col('company', 'Company', 'co'), kit.Col('person_name', 'Person', 'person'),
                    kit.Col('side', 'Side', 'side'), kit.Col('value', 'Value', 'money'),
                    kit.Col('pct_of_mcap', '% of mcap', 'bar'), kit.Col('pct_of_float', '% of float', 'pct'),
                    kit.Col('trades', 'Tranches', 'num', phone=False), kit.Col('range', '52W range · CMP', 'range'),
                    kit.Col('spark', '1Y price · insider trades', 'spark', phone=False)], limit=40)
        elif chip == 'Bulk deals':
            d = ctx.deals
            d = d[~d['client_is_market_maker'].astype('boolean').fillna(False) & (d['date'] == d['date'].max())] \
                if not d.empty else d
            if d.empty:
                kit.empty('No bulk or block deals by real buyers or sellers in the latest session.')
            else:
                d = d.sort_values('value', ascending=False)
                kit.table(d, [
                    kit.Col('company', 'Company', 'co'), kit.Col('client_name', 'Client', 'client', sub='counterparties'),
                    kit.Col('side', 'Side', 'side'), kit.Col('value', 'Value', 'money'),
                    kit.Col('pct_of_mcap', '% of mcap', 'bar'), kit.Col('price', 'Price', 'price')], limit=40)
        else:
            h = hs[hs['large']] if not hs.empty else hs
            if h.empty:
                kit.empty('No large handshakes (₹10 Cr+ or 0.5%+ of market cap) in the latest deal session.')
            else:
                kit.table(h.assign(who=h['seller_is_promoter'].map({True: ['Promoter'], False: []})), [
                    kit.Col('company', 'Company', 'co'), kit.Col('sellers', 'Sold by'), kit.Col('who', '', 'tags'),
                    kit.Col('buyers', 'Absorbed by'), kit.Col('matched_value', 'Matched', 'money'),
                    kit.Col('pct_of_mcap_sold', '% of mcap sold', 'pct')], limit=40)
        kit.caption("Token buys (under ₹25 L in companies above ₹5,000 Cr) and market makers are left out. "
                    "% of float needs the company's shareholding pattern; where it isn't loaded yet the column is blank.")

    _outside_holders(ctx)
    _coming_up(ctx)

    held = ctx.trades.copy()
    held['seen'] = pd.to_datetime(held['broadcast_date'], errors='coerce')
    held = held[held['needs_review'].astype('boolean').fillna(False) & (held['seen'] > day - pd.Timedelta(days=10))]
    with st.expander(f'Needs a look · {len(held)} filings held back in the last 10 days'):
        if held.empty:
            kit.empty('Nothing held back.')
        for _, r in held.head(40).iterrows():
            why = '; '.join(REASONS.get(f, f) for f in str(r['flags']).split(',') if f)
            st.html(f'<div class="q-row"><b>{esc(str(r["company"]))}</b> · {esc(str(r["person_name"]))} · '
                    f'{kit.rupees(r["value"])}, held back because {esc(why)}</div>')
        kit.caption('Held back from every ranking and total until checked against the exchange filing.')
