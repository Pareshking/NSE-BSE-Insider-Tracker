"""Company page (/company?symbol=XYZ): everything about one company -- insider
trades, deals, SAST stakes, corporate actions, shareholding and pledge."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from data import store
from ui import charts, kit
from ui.timeline import timeline
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
        kit.Tile('Directors & KMP net', kit.rupees(off['signed_value'].sum(), signed=True), kit.plural(off['person_id'].nunique(), 'person', 'people')),
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

    # Timeline: each event with what an investor needs on one line: when it
    # was traded and made public, how late, price paid, and the move since.
    px_then = None
    if hist:
        hd = pd.Series(hist[1], index=pd.DatetimeIndex(hist[0]))
        px_then = lambda day: hd.asof(pd.Timestamp(day)) if pd.notna(day) and pd.Timestamp(day) >= hd.index[0] else None  # noqa: E731
    cmp_now = pr['latest_close'] if pr is not None else None
    show_all = st.toggle('Include ESOPs, gifts, transfers and pledges', value=False, key='co_tl_all')
    events = []
    tp = t[t['is_primary'].astype('boolean').fillna(False)]  # one event per trade, not one per exchange copy
    for r in tp.assign(seen=pd.to_datetime(tp['broadcast_date'], errors='coerce')).to_dict('records'):
        market = bool(r.get('is_market'))
        if not market and not show_all:
            continue
        kind = ('buy' if r['side'] == 'BUY' else 'sell') if market else 'other'
        verb = ('bought' if r['side'] == 'BUY' else 'sold') if market else esc(str(r.get('mode_raw') or r.get('kind') or 'filed'))
        paid = r.get('price')
        then = px_then(r['seen']) if px_then else None
        since = (cmp_now / then - 1) * 100 if then and cmp_now and pd.notna(then) else None
        frm, to = pd.to_datetime(r.get('trade_date_from'), errors='coerce'), pd.to_datetime(r.get('trade_date_to'), errors='coerce')
        traded = (kit.day(to) if pd.isna(frm) or frm == to else f'{frm:%d %b}–{kit.day(to)}') if pd.notna(to) else ''
        lag = kit.sessions_text(r.get('trade_to_public_sessions'))
        late = r.get('insider_filed_late') is True or r.get('company_filed_late') is True
        meta = [f'Traded {traded}' if traded else '',
                f'made public {kit.day(r["seen"])}' + (f' ({lag} later)' if lag and lag != 'same day' else ''),
                kit.tag('Filed late', 'warn') if late else '',
                f'{kit.shares(r.get("quantity"))} sh @ {kit.price(paid)}' if kit._finite(paid) else '',
                (f'own holding {kit.pct(r.get("holding_change_pct"), 1, signed=True)}' if kit._finite(r.get('holding_change_pct')) is not None else ''),
                (f'<span class="{"up" if since > 0 else "down" if since < 0 else ""}">{kit.pct(since, 1, signed=True)} since</span>'
                 if since is not None else '')]
        events.append({'date': r['seen'], 'kind': kind, 'amount': kit.rupees(r.get('value')), 'meta': meta,
                       'link': r.get('source_url') if isinstance(r.get('source_url'), str) and r['source_url'].startswith('http') else None,
                       'title': f'<b>{esc(str(r["person_name"]))}</b> <span class="tlx-role">{esc(kit.role(r["person_role"]))}</span> {verb}'})
    if not d.empty:
        for r in d.to_dict('records'):
            buy = r['side'] == 'BUY'
            events.append({'date': r['date'], 'kind': 'deal_buy' if buy else 'deal_sell', 'amount': kit.rupees(r.get('value')),
                           'title': f'<b>{esc(str(r["client_name"]))}</b> {"bought" if buy else "sold"} in a {esc(str(r.get("feeds") or "bulk"))} deal',
                           'meta': [f'{kit.shares(r.get("quantity"))} sh @ {kit.price(r.get("price"))}',
                                    f'{kit.pct(r.get("pct_of_mcap"))} of market cap' if kit._finite(r.get('pct_of_mcap')) is not None else '']})
    own = lambda f: f[f['symbol'].astype(str).str.upper() == sym] if f is not None and not f.empty else pd.DataFrame()  # noqa: E731
    for r in own(ctx.sast).to_dict('records'):
        events.append({'date': pd.to_datetime(r.get('transaction_date'), errors='coerce'), 'kind': 'sast',
                       'title': f'<b>{esc(str(r["acquirer_name"]))}</b> {esc(str(r.get("action_type") or "").lower())}',
                       'amount': kit.pct(r.get('percent_equity_traded'), 2, signed=True),
                       'meta': [f'stake now {kit.pct(r.get("post_stake_pct"))}', esc(str(r.get('mode') or ''))]})
    for r in own(ctx.actions).to_dict('records'):
        events.append({'date': pd.to_datetime(r.get('ex_date'), errors='coerce'), 'kind': 'action',
                       'title': esc(str(r.get('subject') or 'Corporate action')),
                       'meta': [f'record date {kit.day(r.get("record_date"))}' if pd.notna(pd.to_datetime(r.get('record_date'), errors='coerce')) else '']})
    for r in own(ctx.meetings).to_dict('records'):
        events.append({'date': pd.to_datetime(r.get('meeting_date'), errors='coerce'), 'kind': 'meeting',
                       'title': 'Board meeting to consider ' + esc(str(r.get('purposes') or '').replace('_', ' ').replace(',', ', '))})
    with kit.card('Timeline', 'co_tl', f'{len(events)} events · newest first · open-market trades only unless switched on'):
        timeline(events)
    q = sym.replace('&', '%26')
    st.html('<p class="cap">Exchange filings: '
            f'<a href="https://www.nseindia.com/companies-listing/corporate-filings-insider-trading?symbol={q}" target="_blank">NSE insider trading</a> · '
            f'<a href="https://www.nseindia.com/companies-listing/corporate-filings-sast-regulation-29?symbol={q}" target="_blank">NSE SAST</a> · '
            f'<a href="https://www.nseindia.com/get-quotes/equity?symbol={q}" target="_blank">NSE quote</a>. '
            '</p>')
