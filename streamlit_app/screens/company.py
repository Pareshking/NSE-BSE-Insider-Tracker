"""Company page (/company?symbol=XYZ): everything about one company -- insider
trades, deals, SAST stakes, corporate actions, shareholding and pledge."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from data import store
from ui import charts, kit
from ui.kit import esc

from insiders_clean import signals
from screens.ctx import load, need_data


def _pick_symbol(ctx) -> str | None:
    sym = st.query_params.get('symbol')
    if sym:
        return sym.upper()
    names = ctx.eligible.dropna(subset=['nse_symbol']).drop_duplicates('nse_symbol')
    options = sorted(f'{c} · {s}' for c, s in zip(names['company'], names['nse_symbol']))
    choice = st.selectbox('Company', options, index=None, placeholder='Search a company', key='co_pick')
    if choice:
        st.query_params['symbol'] = choice.rsplit(' · ', 1)[1]
        st.rerun()
    return None


def render():
    ctx = load()
    if not need_data(ctx):
        return
    sym = _pick_symbol(ctx)
    if not sym:
        kit.head('Company', 'Pick a company, or open one from any table on the site.')
        return
    t = ctx.trades[ctx.trades['nse_symbol'].astype(str).str.upper() == sym].copy()
    sec = ctx.securities[ctx.securities['nse_symbol'].astype(str).str.upper() == sym] if not ctx.securities.empty else pd.DataFrame()
    rec = sec.iloc[0] if len(sec) else (t.iloc[0] if len(t) else None)
    name = (rec.get('display_name') if rec is not None and 'display_name' in rec else None) or \
           (t['company'].iloc[0] if len(t) else sym)
    kit.head(str(name), '')
    if rec is not None:
        parts = [f'<span class="mono">{esc(sym)}</span>']
        for k, label in (('bse_code', 'BSE'), ('isin', '')):
            if k in rec and pd.notna(rec.get(k)):
                parts.append(f'{label} <span class="mono">{esc(str(rec.get(k)))}</span>'.strip())
        for k in ('sector', 'industry'):
            if k in rec and pd.notna(rec.get(k)):
                parts.append(esc(str(rec.get(k))))
        if 'market_cap' in rec and pd.notna(rec.get('market_cap')):
            parts.append(f'Mkt cap {kit.rupees(rec.get("market_cap"))}')
        st.html(f'<div class="ident">{" · ".join(parts)}</div>')

    e = ctx.eligible[ctx.eligible['nse_symbol'].astype(str).str.upper() == sym]
    win = e[e['seen'] > ctx.ref - pd.Timedelta(days=365)]
    prom = win[win['person_role'].isin(signals.PROMOTER_ROLES)]
    off = win[win['person_role'].isin(['director', 'kmp'])]
    d = ctx.deals[ctx.deals['nse_symbol'].astype(str).str.upper() == sym] if not ctx.deals.empty else pd.DataFrame()
    if not d.empty:
        d = d[~d['client_is_market_maker'].astype('boolean').fillna(False) & d['is_primary'].astype('boolean').fillna(False)]
        d = d[d['date'] > ctx.deals['date'].max() - pd.Timedelta(days=365)]  # same 12 months as the insider flow
    sh = signals.latest_shareholding(ctx.shareholding)
    shr = sh[sh['symbol'].astype(str).str.upper() == sym] if not sh.empty else pd.DataFrame()
    pledge = shr['promoter_pledge_pct'].iloc[0] if len(shr) else None
    signed = prom['pct_of_mcap'] * prom['side'].map({'BUY': 1, 'SELL': -1})
    isin = (rec.get('isin') if rec is not None else None) or (t['isin'].dropna().iloc[0] if t['isin'].notna().any() else None)
    pr = ctx.prices[ctx.prices['isin'] == isin].iloc[0] if isin and not ctx.prices.empty and (ctx.prices['isin'] == isin).any() else None
    price_tile = (kit.Tile('Price', f'₹{pr["latest_close"]:,.2f}',
                           f'{pr["pct_off_high"] * 100:+.0f}% from 52W high ₹{pr["high_52w"]:,.0f} · low ₹{pr["low_52w"]:,.0f}',
                           'up' if pr['pct_off_high'] > -0.05 else '')
                  if pr is not None and pd.notna(pr.get('latest_close')) else kit.Tile('Price', '—', 'not in our NSE/BSE price files'))
    kit.tiles([
        price_tile,
        kit.Tile('Promoter net, 12 months', kit.rupees(prom['signed_value'].sum(), signed=True),
                 f'{kit.pct(signed.sum(), 3, signed=True)} of market cap, open market only',
                 'up' if prom['signed_value'].sum() > 0 else 'down' if prom['signed_value'].sum() < 0 else ''),
        kit.Tile('Directors & KMP net', kit.rupees(off['signed_value'].sum(), signed=True), f'{off["person_id"].nunique()} people'),
        kit.Tile('Deals net, 12 months', kit.rupees(d['signed_value'].sum() if not d.empty else None, signed=True),
                 'bulk/block, market makers excluded'),
        kit.Tile('Promoter holding · pledge',
                 f'{kit.pct(shr["promoter_holding_pct"].iloc[0], 1) if len(shr) else "—"} · {kit.pct(pledge, 1) if pledge is not None else "—"}',
                 (f'free float {kit.pct(shr["public_holding_pct"].iloc[0], 1)} · ' if len(shr) else '')
                 + 'pledge as % of promoter shares, latest quarter'),
    ])

    hist = store.price_history().get(isin) if isin else None
    with kit.card('Price and insider trades', 'co_px', '12 months · ▲ bought ▼ sold, sized by value, on the day made public'):
        chart = charts.price_with_trades(*hist, e.assign(role=e['person_role'].map(kit.role))) if hist else None
        if chart is None:
            kit.empty('No price history for this stock in our NSE/BSE price files yet.')
        else:
            st.altair_chart(chart, width='stretch')

    # Net open-market flow by who, 12 months (owner's spec: promoters vs
    # directors/KMP vs other insiders vs institutional deal buyers).
    other = win[~win['person_role'].isin(list(signals.PROMOTER_ROLES) + ['director', 'kmp'])]
    flows = [('Promoters', prom['signed_value'].sum()), ('Directors & KMP', off['signed_value'].sum()),
             ('Other insiders', other['signed_value'].sum()),
             ('Bulk/block buyers (no market makers)', d['signed_value'].sum() if not d.empty else 0.0)]
    scale = max([abs(v) for _, v in flows] + [1.0])
    bars = ''.join(
        f'<div class="fl-row"><span class="fl-l">{esc(label)}</span><span class="fl-track">'
        f'<i class="{"pos" if v >= 0 else "neg"}" style="width:{abs(v) / scale * 50:.1f}%"></i></span>'
        f'<span class="fl-v num">{kit.rupees(v, signed=True)}</span></div>' for label, v in flows)
    with kit.card('Net open-market flow by who', 'co_flow', '12 months, ₹'):
        st.html(f'<div class="fl">{bars}</div>')

    own = ctx.deals[ctx.deals['nse_symbol'].astype(str).str.upper() == sym] if not ctx.deals.empty else ctx.deals
    hs = signals.handshakes(own, ctx.trades, days=365, ref=ctx.deals['date'].max() if not ctx.deals.empty else None)
    if not hs.empty:
        with kit.card('Handshakes in this stock', 'co_hs', 'who sold, who absorbed it'):
            kit.table(hs.assign(who=hs['seller_is_promoter'].map({True: ['Promoter'], False: []})), [
                kit.Col('date', 'Date', 'date'), kit.Col('sellers', 'Sold by'), kit.Col('who', 'Seller', 'tags'),
                kit.Col('buyers', 'Absorbed by'), kit.Col('matched_value', 'Matched', 'money'),
                kit.Col('pct_of_mcap_sold', '% of mcap sold', 'bar')], limit=30)

    events = []
    for _, r in t.assign(seen=pd.to_datetime(t['broadcast_date'], errors='coerce')).sort_values('seen', ascending=False).head(60).iterrows():
        market = bool(r['is_market'])
        dot = ('buy' if r['side'] == 'BUY' else 'sell') if market else 'warn' if r.get('needs_review') else ''
        what = f'{r["mode_raw"] or r["kind"]!s}' if not market else ('bought' if r['side'] == 'BUY' else 'sold')
        events.append((r['seen'], dot, f'<b>{esc(str(r["person_name"]))}</b> ({esc(kit.role(r["person_role"]))}) '
                                       f'{esc(what)} {kit.rupees(r["value"])}' + ('' if market else ' · not an open-market trade')))
    if not d.empty:
        for _, r in d.sort_values('date', ascending=False).head(30).iterrows():
            verb = 'bought' if r['side'] == 'BUY' else 'sold'
            text = (f'<b>{esc(str(r["client_name"]))}</b> {verb} '
                    f'{kit.rupees(r["value"])} in a {esc(str(r["feeds"]))} deal')
            events.append((r['date'], 'buy' if r['side'] == 'BUY' else 'sell', text))
    for frame, date_col, text in ((ctx.actions, 'ex_date', lambda r: f'Corporate action: {esc(str(r["subject"]))}'),
                                  (ctx.sast, 'transaction_date', lambda r: f'SAST: <b>{esc(str(r["acquirer_name"]))}</b> '
                                   f'{esc(str(r["action_type"]).lower())}, stake now {kit.pct(r["post_stake_pct"])}'),
                                  (ctx.meetings, 'meeting_date', lambda r: f'Board meeting to consider {esc(str(r["purposes"]).replace("_", " "))}')):
        if frame is not None and not frame.empty:
            for _, r in frame[frame['symbol'].astype(str).str.upper() == sym].iterrows():
                events.append((pd.to_datetime(r[date_col], errors='coerce'), 'event', text(r)))
    events = sorted([x for x in events if pd.notna(x[0])], key=lambda x: x[0], reverse=True)
    with kit.card('Timeline', 'co_tl', 'every event, newest first'):
        if not events:
            kit.empty('No filings for this company in the data.')
        else:
            st.html('<div class="tl">' + ''.join(
                f'<div class="tl-row"><span class="tl-d">{pd.Timestamp(dt).strftime("%d %b %y")}</span>'
                f'<span class="tl-dot {dot}"></span><span class="tl-t">{txt}</span></div>' for dt, dot, txt in events[:80]) + '</div>')
    q = sym.replace('&', '%26')
    st.html('<p class="cap">Exchange filings: '
            f'<a href="https://www.nseindia.com/companies-listing/corporate-filings-insider-trading?symbol={q}" target="_blank">NSE insider trading</a> · '
            f'<a href="https://www.nseindia.com/companies-listing/corporate-filings-sast-regulation-29?symbol={q}" target="_blank">NSE SAST</a> · '
            f'<a href="https://www.nseindia.com/get-quotes/equity?symbol={q}" target="_blank">NSE quote</a>. '
            '</p>')
