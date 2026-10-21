"""Company page (/company?symbol=XYZ): everything about one company -- insider
trades, deals, SAST stakes, corporate actions, shareholding and pledge."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from data import store
from ui import charts, kit
from ui.timeline import timeline
from ui.kit import esc
from ui.table import facts

from insiders_clean import signals
from screens.capital_raises import issue_rows, qip_rows, rights_rows
from screens.buybacks import events as buyback_events
from screens.ctx import load, need_data, with_flags


def _headroom(ctx, e, shr, sym):
    """Room to the 75% promoter ceiling (SCRR 19A) and creeping-acquisition room this financial year (SAST
    Reg 3(2): holders of 25% to under 75% may add 5% a year, gross, without an open offer), in one tile.
    The year's use is shares bought by promoters on the market over the company's total shares in the latest
    shareholding XBRL (audit D2); allotments and off-market moves are not in it."""
    if not len(shr) or pd.isna(shr['promoter_holding_pct'].iloc[0]):
        return None
    ph = float(shr['promoter_holding_pct'].iloc[0])
    fy = pd.Timestamp(year=ctx.ref.year if ctx.ref.month >= 4 else ctx.ref.year - 1, month=4, day=1)
    fy_buys = e[(e['seen'] >= fy) & (e['side'] == 'BUY') & e['person_role'].isin(signals.PROMOTER_ROLES)]
    mine = ctx.shareholding[ctx.shareholding['symbol'].astype(str).str.upper() == sym] if not ctx.shareholding.empty else pd.DataFrame()
    tot = pd.to_numeric(mine.sort_values('quarter_end')['total_shares'], errors='coerce').dropna() if 'total_shares' in mine else pd.Series(dtype=float)
    used = (pd.to_numeric(fy_buys['quantity'], errors='coerce').sum() / tot.iloc[-1] * 100 if len(tot) and tot.iloc[-1]
            else pd.to_numeric(fy_buys['pct_of_mcap'], errors='coerce').sum())
    creep = (f'{kit.pct(max(0.0, min(5.0 - used, 75 - ph)), 2)} creeping room left this FY · {kit.pct(used, 2)} bought since {kit.day(fy, with_year=False)}'
             if 25 <= ph < 75 else 'no creeping room: holding under 25%' if ph < 25 else f'{ph - 75:.2f} pts over: must sell down')
    return kit.Tile('Room to 75%', f'{75 - ph:.2f} pts' if ph < 75 else 'Over 75%', creep, '' if ph < 75 else 'down')


def _trade_detail(r) -> str:
    """One filing's facts, opened from its row."""
    hb, ha = r.get('holding_before'), r.get('holding_after')
    flags = ', '.join(x.replace('_', ' ') for x in str(r.get('flags') or '').split(',') if x)
    frm, to = pd.to_datetime(r.get('trade_date_from'), errors='coerce'), pd.to_datetime(r.get('trade_date_to'), errors='coerce')
    when = lambda k: kit.day(r.get(k)) if pd.notna(pd.to_datetime(r.get(k), errors='coerce')) else ''  # noqa: E731
    return facts([
        ('Traded', (kit.day(to) if pd.isna(frm) or frm == to else f'{kit.day(frm)} to {kit.day(to)}') if pd.notna(to) else ''),
        ('Told the company', when('intimation_date')),
        ('Made public', when('broadcast_date')),
        ('Held before', kit.shares(hb) if kit._finite(hb) is not None else ''),
        ('Held after', kit.shares(ha) if kit._finite(ha) is not None else ''),
        ('Own holding change', kit.pct(r.get('holding_change_pct'), 1, signed=True) if kit._finite(r.get('holding_change_pct')) is not None else ''),
        ('% of market cap', kit.pct(r.get('pct_of_mcap'), 3) if kit._finite(r.get('pct_of_mcap')) is not None else ''),
        ('Mode as filed', str(r.get('mode_raw') or '')),
        ('Filed late', 'yes' if r.get('insider_filed_late') is True or r.get('company_filed_late') is True else ''),
        ('Held back because', flags),
    ], [('The filing', r.get('source_url') if isinstance(r.get('source_url'), str) and r['source_url'].startswith('http') else '')])


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
    if rec is None:
        kit.head('Company', '')
        kit.empty(f'No company with the symbol {sym} in our data. Open one from any table, or check the spelling.')
        return
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
        q = sym.replace('&', '%26')
        parts.append(f'<a href="https://www.nseindia.com/get-quotes/equity?symbol={q}" target="_blank" rel="noopener">NSE</a>'
                     f' <a href="https://www.nseindia.com/companies-listing/corporate-filings-insider-trading?symbol={q}" '
                     f'target="_blank" rel="noopener">filings</a>')
        st.html(f'<div class="ident">{" · ".join(parts)}</div>')
        fl = with_flags(pd.DataFrame({'isin': [rec.get('isin')]})) if pd.notna(rec.get('isin')) else pd.DataFrame()
        if 'trade_flags' in fl and fl['trade_flags'].iloc[0]:  # NSE surveillance, T2T, SME, band, circuit days
            f, n = fl['trade_flags'].iloc[0], fl['trade_flag_notes'].iloc[0]
            st.html(f'<div class="flags">{kit.flag_tags(f, n)}<p class="cap">{esc(" · ".join(n))}</p></div>')

    e = ctx.eligible[ctx.eligible['nse_symbol'].astype(str).str.upper() == sym]
    win = e[e['seen'] > ctx.ref - pd.Timedelta(days=365)]
    prom = win[win['person_role'].isin(signals.PROMOTER_ROLES)]
    off = win[win['person_role'].isin(['director', 'kmp'])]
    d = ctx.deals[ctx.deals['nse_symbol'].astype(str).str.upper() == sym] if not ctx.deals.empty else pd.DataFrame()
    if not d.empty:
        d = d[~d['client_is_market_maker'].astype('boolean').fillna(False) & d['is_primary'].astype('boolean').fillna(False)]
        d = d[d['date'] > ctx.deals['date'].max() - pd.Timedelta(days=365)]  # same 12 months as the insider flow
        d = d.assign(also_filed=signals.deals_also_filed(d, ctx.trades))
    sh = signals.latest_shareholding(ctx.shareholding)
    shr = sh[sh['symbol'].astype(str).str.upper() == sym] if not sh.empty else pd.DataFrame()
    pledge = shr['promoter_pledge_pct'].iloc[0] if len(shr) else None
    signed = prom['pct_of_mcap'] * prom['side'].map({'BUY': 1, 'SELL': -1})
    isin = (rec.get('isin') if rec is not None else None) or (t['isin'].dropna().iloc[0] if t['isin'].notna().any() else None)
    pr = ctx.prices[ctx.prices['isin'] == isin].iloc[0] if isin and not ctx.prices.empty and (ctx.prices['isin'] == isin).any() else None
    hist = store.price_history().get(isin) if isin else None
    if pr is not None and pd.notna(pr.get('latest_close')):
        day_txt = ''
        if hist and len(hist[1]) >= 2:
            c0, c1 = float(hist[1][-2]), float(hist[1][-1])
            day_txt = f'{c1 - c0:+,.2f} ({(c1 / c0 - 1) * 100:+.2f}%) on {kit.day(hist[0][-1])} · '
        price_tile = kit.Tile('Price', kit.price(pr['latest_close']),
                              f'{day_txt}{pr["pct_off_high"] * 100:+.1f}% from 52W high {kit.price(pr["high_52w"])}',
                              'up' if pr['pct_off_high'] > -0.05 else '')
    else:
        price_tile = kit.Tile('Price', '—', 'not in our NSE/BSE price files')
    headroom = _headroom(ctx, e, shr, sym)
    kit.tiles([
        price_tile,
        kit.Tile('Promoters hold', kit.pct(shr['promoter_holding_pct'].iloc[0], 1) if len(shr) else '—',
                 (f'{kit.pct(pledge, 1)} of it pledged · ' if pledge is not None and pd.notna(pledge) else '')
                 + (f'quarter to {kit.day(shr["quarter_end"].iloc[0])}' if len(shr) and 'quarter_end' in shr else 'no shareholding pattern yet'),
                 'down' if pledge is not None and pd.notna(pledge) and pledge > signals.HIGH_PLEDGE_PCT else ''),
        *([headroom] if headroom else []),
    ])

    # Preferential and rights issues for this company; the tab appears only when there are some.
    raises = {}
    for label, recs, build in (('Preferential issues', ctx.preferential, issue_rows), ('Rights issues', ctx.rights, rights_rows)):
        if recs is not None and not recs.empty and 'symbol' in recs:
            mine = recs[recs['symbol'].astype(str).str.upper() == sym]
            if not mine.empty:
                raises[label] = build(mine, ctx.prices)
    qips = store.table('qip')
    if not qips.empty and 'symbol' in qips:
        mine = qips[qips['symbol'].astype(str).str.upper() == sym]
        if not mine.empty:
            raises['QIPs'] = qip_rows(mine, ctx.prices).assign(offer_price=lambda r: r.get('issue_price'))
    names = ['Overview', 'Timeline', f'Insider trades · {kit.indian(int(t["is_primary"].astype("boolean").fillna(False).sum()))}', f'Deals · {kit.indian(len(d))}', 'Shareholding']
    if raises:
        names.append('Capital raises')
    tabs = st.tabs(names)
    with tabs[0]:
        left, right = st.columns([3, 2], gap='medium')
        with left, kit.card('Price and insider trades', 'co_px', '12 months · ▲ bought ▼ sold, on the day made public'):
            chart = charts.price_with_trades(*hist, e.assign(role=e['person_role'].map(kit.role))) if hist else None
            if chart is None:
                kit.empty('No price history for this stock in our NSE/BSE price files yet.')
            else:
                st.altair_chart(chart, width='stretch')
        # Net open-market money by who, 12 months, each rupee once: a bulk/block deal that is an insider's own
        # filed trade counts under the insider, not again under deals (audit D3, D6).
        other = win[~win['person_role'].isin(list(signals.PROMOTER_ROLES) + ['director', 'kmp'])]
        rest = d[~d['also_filed']] if not d.empty else d
        flows = [('Promoters', prom['signed_value'].sum(), f'{kit.pct(signed.sum(), 2, signed=True)} of mcap'),
                 ('Directors & KMP', off['signed_value'].sum(), kit.plural(off['person_id'].nunique(), 'person', 'people')),
                 ('Other insiders', other['signed_value'].sum(), ''),
                 ('Other deal buyers & sellers', rest['signed_value'].sum() if not rest.empty else 0.0, 'bulk/block, market makers out')]
        scale = max([abs(v) for _, v, _ in flows] + [1.0])
        bars = ''.join(
            f'<div class="fl-row"><span class="fl-l">{esc(label)}<em>{esc(note)}</em></span><span class="fl-track">'
            f'<i class="{"pos" if v >= 0 else "neg"}" style="width:{abs(v) / scale * 50:.1f}%"></i></span>'
            f'<span class="fl-v num">{kit.rupees(v, signed=True)}</span></div>' for label, v, note in flows)
        with right, kit.card('Money in and out', 'co_flow', '12 months, open market, each rupee once'):
            st.html(f'<div class="fl">{bars}</div>')

    with tabs[1]:
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
                    (f'{kit.sessions_text(r.get("sessions_since_window_open")).replace("same day", "first session")} after the trading window reopened'
                     if pd.notna(r.get('window_open_buy')) and bool(r.get('window_open_buy')) else ''),
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
        bb = own(store.table('buybacks'))  # buybacks carry their price and route (screens/buybacks.py)
        events += buyback_events(bb, ctx.prices)
        for r in own(ctx.actions).to_dict('records'):
            if r.get('purpose') == 'buyback' and not bb.empty:
                continue  # shown above, with price and route
            events.append({'date': pd.to_datetime(r.get('ex_date'), errors='coerce'), 'kind': 'action',
                           'title': esc(str(r.get('subject') or 'Corporate action')),
                           'meta': [f'record date {kit.day(r.get("record_date"))}' if pd.notna(pd.to_datetime(r.get('record_date'), errors='coerce')) else '']})
        for r in own(ctx.meetings).to_dict('records'):
            events.append({'date': pd.to_datetime(r.get('meeting_date'), errors='coerce'), 'kind': 'meeting',
                           'title': 'Board meeting to consider ' + esc(str(r.get('purposes') or '').replace('_', ' ').replace(',', ', '))})
        with kit.card('Timeline', 'co_tl', f'{len(events)} events · newest first · open-market trades only unless switched on'):
            timeline(events)
    with tabs[2]:
        rows = t[t['is_primary'].astype('boolean').fillna(False)].assign(
            seen=lambda x: pd.to_datetime(x['broadcast_date'], errors='coerce'), mode=lambda x: x['mode_raw'].fillna(x['kind']))
        kit.table(rows.sort_values('seen', ascending=False), [
            kit.Col('person_name', 'Person', 'person'), kit.Col('side', 'Side', 'side'), kit.Col('mode', 'Mode as filed'),
            kit.Col('quantity', 'Shares', 'shares', phone=False), kit.Col('price', 'Price', 'price', phone=False),
            kit.Col('value', 'Value', 'money'), kit.Col('holding_change_pct', 'Own holding Δ', 'spct', phone=False),
            kit.Col('trade_date_to', 'Traded', 'date', phone=False), kit.Col('seen', 'Made public', 'date')],
            limit=300, download=f'{sym}_insider', detail=_trade_detail, key=f'co_it_{sym}')
    with tabs[3]:
        kit.table(d.sort_values('date', ascending=False) if not d.empty else d, [
            kit.Col('date', 'Date', 'date'), kit.Col('client_name', 'Client', 'client', sub='counterparties'),
            kit.Col('side', 'Side', 'side'), kit.Col('quantity', 'Shares', 'shares', phone=False),
            kit.Col('price', 'Price', 'price'), kit.Col('value', 'Value', 'money'),
            kit.Col('pct_of_mcap', '% of mcap', 'bar'), kit.Col('feeds', 'Feed', phone=False)],
            limit=300, download=f'{sym}_deals', empty_text='No bulk or block deals by real buyers or sellers in 12 months.')
        own = ctx.deals[ctx.deals['nse_symbol'].astype(str).str.upper() == sym] if not ctx.deals.empty else ctx.deals
        hs = signals.handshakes(own, ctx.trades, days=365, ref=ctx.deals['date'].max() if not ctx.deals.empty else None)
        if not hs.empty:
            with kit.card('Handshakes', 'co_hs', 'who sold, who absorbed it, 12 months'):
                kit.table(hs.assign(who=hs['seller_is_promoter'].map({True: ['Promoter'], False: []})), [
                    kit.Col('date', 'Date', 'date'), kit.Col('sellers', 'Sold by'), kit.Col('who', 'Seller', 'tags'),
                    kit.Col('buyers', 'Absorbed by'), kit.Col('matched_value', 'Matched', 'money'),
                    kit.Col('pct_of_mcap_sold', '% of mcap sold', 'bar')], limit=30, key=f'co_hs_{sym}')
    with tabs[4]:
        q_rows = ctx.shareholding[ctx.shareholding['symbol'].astype(str).str.upper() == sym] if not ctx.shareholding.empty else pd.DataFrame()
        kit.table(q_rows.sort_values('quarter_end', ascending=False) if not q_rows.empty else q_rows, [
            kit.Col('quarter_end', 'Quarter', 'date'), kit.Col('promoter_holding_pct', 'Promoter', 'pct'),
            kit.Col('public_holding_pct', 'Public', 'pct'), kit.Col('promoter_pledge_pct', 'Pledged', 'pct'),
            kit.Col('promoter_encumbered_pct', 'Encumbered', 'pct', phone=False),
            kit.Col('submission_date', 'Filed', 'date', phone=False)], limit=20,
            empty_text='No shareholding pattern loaded for this company yet (coverage grows nightly).')
        # Promoter and promoter-group members as the latest filing names them (Table II of the XBRL):
        # the people and entities counted as one decision-maker in clusters.
        pg = store.table('promoter_group')
        if not pg.empty and 'symbol' in pg:
            pg = pg[pg['symbol'].astype(str).str.upper() == sym]
            if not pg.empty:
                last = pg['quarter_end'].max()
                pg = pg[pg['quarter_end'] == last].sort_values('shares', ascending=False)
                with kit.card('Promoter group', 'co_pg', f'{kit.plural(len(pg), "member")} named in the filing for the quarter ending '
                              f'{kit.day(last)}; counted as one decision-maker in clusters'):
                    kit.table(pg, [
                        kit.Col('member_name', 'Member'), kit.Col('sub_category', 'Category', phone=False),
                        kit.Col('shares', 'Shares', 'shares', phone=False), kit.Col('pct_of_company', '% of company', 'pct'),
                        kit.Col('pledged_shares', 'Pledged', 'shares', phone=False)], limit=60, download=f'{sym}_promoter_group')
    if raises:
        with tabs[5]:
            for label, rows in raises.items():
                st.html(f'<p class="cap"><b>{label}</b></p>')
                kit.table(rows, [
                    kit.Col('posted_on', 'Posted', 'date'), kit.Col('status', 'Stage'),
                    kit.Col('offer_price', 'Offer price', 'price'), kit.Col('amount', 'Amount', 'money'),
                    kit.Col('shares_allotted', 'Shares', 'shares', phone=False),
                    kit.Col('trading_approval_date', 'Trading approval', 'date', phone=False)], limit=20)
