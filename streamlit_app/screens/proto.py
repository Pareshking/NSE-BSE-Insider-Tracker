"""Prototype renders of the new design (owner, 13 Nov 2026: "Dense table: show rendering first", "Situations: render
first"). Hidden pages, real data, built from the clean tables only (the site never cleans). Not in the menu: the
current pages stay as they are until the owner has seen these.

Design (scratchpad brief SYNTHESIS, agreed by all three briefs): dense tables, one primary number per row, the
context number beside it, evidence on every row, a freshness strip on top, noise counted in one line.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st
from data import store

from insiders_clean import ideas
from screens import moves
from screens.ctx import load, need_data
from ui import kit
from ui.kit import esc

DAYS = 7
SAST_LATE_DAYS = 30   # on Today a SAST filing this late after its trade is counted, not listed (13 Nov 2026)
TODAY_DEAL_MCAP = 500e7   # ₹500 Cr: smaller companies' deals stay on the Deals page, not on Today (13 Nov 2026)


def _strip(ctx, parts: list[str]) -> None:
    ref = pd.Timestamp(ctx.ref) if ctx.ref is not None else None
    lead = f'Data to <b>{ref:%d %b %Y}</b>' if ref is not None else 'Data date unknown'
    st.html('<div class="dt-strip">' + ' <span class="sep">·</span> '.join([lead] + parts) + '</div>')


def _table(cols: list[tuple[str, str, str]], rows: list[dict], cls: str = '') -> str:
    """cols: (key, label, align 'l'|'r'). Cell values are trusted HTML built here (names escaped)."""
    head = ''.join(f'<th class="{a}">{esc(lbl)}</th>' for _, lbl, a in cols)
    body = ''.join('<tr>' + ''.join(f'<td class="{a}">{r.get(k, "") or ""}</td>' for k, _, a in cols) + '</tr>' for r in rows)
    return f'<div class="dt-wrap"><table class="dt {cls}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def _num(v, fmt='{:,.2f}', dash='–'):
    return fmt.format(v) if kit._finite(v) is not None else f'<span class="mute">{dash}</span>'


def _chip(text: str, tone: str = '') -> str:
    return f'<span class="dt-chip {tone}">{esc(text)}</span>'


def _company(name, sym) -> str:
    href = kit.company_href(sym)
    nm = esc(str(name or sym or ''))
    return (f'<a href="{esc(href, quote=True)}" target="_self">{nm}</a>' if href else nm) + \
        (f'<span class="sym">{esc(str(sym))}</span>' if isinstance(sym, str) and sym else '')


# ---- Today: one dense table ------------------------------------------------------------------------------------------

def _more(path: str, text: str) -> str:
    return f'<p class="dt-foot"><a href="/{path}" target="_self">{esc(text)} →</a></p>'


def today():
    """The top of every page, last 7 days (synthesis, 12 Nov: Today shows each page's head, ranked by % of the company)."""
    ctx = load()
    if not need_data(ctx):
        return
    ref = pd.Timestamp(ctx.ref)
    px, _, names = moves.lookups(ctx)
    d, clubbed = _decisions(ctx, DAYS)
    dl = ctx.deals
    dl = dl[(dl['date'] > ref - pd.Timedelta(days=DAYS)) & (dl['date'] <= ref)] if not dl.empty else dl
    # Today ranks deals by % of the company, which puts small SME names on top (investor check 13 Nov 2026: three of
    # the top four were SME stocks traded between the same two funds); on Today only companies of TODAY_DEAL_MCAP and
    # up, the rest counted and on the Deals page.
    mc = pd.to_numeric(dl['market_cap'], errors='coerce') if 'market_cap' in dl else pd.Series(float('nan'), index=dl.index)
    tiny = mc.lt(TODAY_DEAL_MCAP)
    n_tiny = int(dl.loc[tiny, 'isin'].nunique()) if not dl.empty else 0
    drows, churn, small = _deal_rows(dl[~tiny]) if not dl.empty else ([], 0, 0)
    drows.sort(key=lambda x: -(kit._finite(x['pct']) or 0))
    sa = ctx.sast
    srows, inter, tiny, n_late = [], 0, 0, 0
    if sa is not None and not sa.empty:
        sa = sa.assign(_f=pd.to_datetime(sa['broadcast_ts'], errors='coerce', format='mixed'))
        sa = sa[(sa['_f'] > ref - pd.Timedelta(days=DAYS)) & (sa['_f'] <= ref + pd.Timedelta(days=1))]
        # a filing made a month or more after the trade is old news on Today (13 Nov 2026: both "crossings" shown were
        # filed 85 and 97 days late, mode "Others"): counted, and on the Stakes page
        lag = (sa['_f'].dt.tz_localize(None) if getattr(sa['_f'].dt, 'tz', None) is not None else sa['_f']) \
            - pd.to_datetime(sa.get('trade_date_to'), errors='coerce')
        late = lag.dt.days.gt(SAST_LATE_DAYS)
        n_late = int(late.sum())
        sa = sa[~late]
        if not sa.empty:
            srows, inter, tiny = _sast_rows(sa, names)
            srows = [r for r in srows if r['cross']]   # on Today: only holders crossing a threshold
    v_buy = d.loc[d['side'] == 'BUY', 'value'].sum() if not d.empty else 0
    v_sell = d.loc[d['side'] == 'SELL', 'value'].sum() if not d.empty else 0
    _strip(ctx, ['last 7 days', 'NSE + BSE copies merged', 'noise counted, not listed'])
    st.html('<div class="head ds-head dt-head"><h1>Today</h1>'
            f'<div class="dt-kpis"><div><span>Insider buying</span><b class="up">{esc(kit.rupees(v_buy))}</b><em>{int((d["side"] == "BUY").sum()) if not d.empty else 0} decisions</em></div>'
            f'<div><span>Insider selling</span><b class="dn">{esc(kit.rupees(v_sell))}</b><em>{int((d["side"] == "SELL").sum()) if not d.empty else 0} decisions</em></div>'
            f'<div><span>Deals</span><b>{len(drows)}</b><em>₹1 Cr and over</em></div>'
            f'<div><span>Thresholds</span><b>{len(srows)}</b><em>SAST crossings</em></div></div></div>')
    top = d.sort_values('pct_of_company', ascending=False).head(15) if not d.empty else d
    st.html('<h2 class="dt-h2">Insider decisions <span>largest first by % of the company</span></h2>')
    st.html(_insider_table(ctx, top, px, names) if not top.empty else '<p class="dt-empty">No insider decision past the bar in 7 days.</p>')
    st.html(_more('insiders', f'All {len(d)} decisions, {clubbed} smaller clubbed'))
    st.html('<h2 class="dt-h2">Bulk and block deals <span>largest first by % of the company</span></h2>')
    st.html(_deal_table(drows, names, limit=10))
    st.html(_more('deals', f'All deals; here {churn} market-maker legs and {small} under ₹1 Cr clubbed, '
                           f'{n_tiny} companies under ₹{TODAY_DEAL_MCAP / 1e7:,.0f} Cr left to the Deals page'))
    st.html('<h2 class="dt-h2">Holders crossing a threshold <span>SAST Reg 29 · 5, 10, 15, 20, 25, 50, 75%</span></h2>')
    st.html(_table(SAST_COLS, srows[:10]) if srows else '<p class="dt-empty">No holder crossed a threshold in 7 days.</p>')
    st.html(_more('stakes', 'All stake changes and pledges' + (f'; {n_late} filed over {SAST_LATE_DAYS} days after the trade are there, not here'
                                                                  if n_late else '')))
    st.html(_more('situations', 'Open offers, buybacks, rights and raises'))


def _decisions(ctx, days: int):
    """Insider decisions past the bar in the window (buys: ideas._qualifies; sells: promoters past it, others from
    ideas.BIG_VALUE), and how many were clubbed below it."""
    ref = ctx.ref
    frames, clubbed = [], 0
    for side in ('BUY', 'SELL'):
        d = ideas.decisions(ctx.eligible, ref, side, ctx.shareholding, days)
        if d.empty:
            continue
        pg = d['promoter_group'].astype(bool)
        keep = ideas._qualifies(d) if side == 'BUY' else (pg & ideas._qualifies(d)) | (~pg & (d['value'] >= ideas.BIG_VALUE))
        clubbed += int((~keep).sum())
        frames.append(d[keep].assign(side=side))
    d = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()), clubbed


def _period(key: str, default: str = '7 days') -> int:
    opts = {'7 days': 7, '30 days': 30, '90 days': 90}
    pick = st.segmented_control('Period', list(opts), default=default, key=key, label_visibility='collapsed') or default
    return opts[pick]


def insiders():
    days = _period('dt_ins_period')
    _insider_page(days, f'Insider trades · last {days} days')


def _insider_page(days: int, title: str):
    ctx = load()
    if not need_data(ctx):
        return
    px, hold, names = moves.lookups(ctx)
    d, clubbed = _decisions(ctx, days)
    n_buy = int((d['side'] == 'BUY').sum()) if not d.empty else 0
    n_sell = int((d['side'] == 'SELL').sum()) if not d.empty else 0
    v_buy = d.loc[d['side'] == 'BUY', 'value'].sum() if not d.empty else 0
    v_sell = d.loc[d['side'] == 'SELL', 'value'].sum() if not d.empty else 0
    _strip(ctx, [f'insider filings, last {days} days', 'NSE + BSE copies merged', 'open-market trades only'])
    st.html(f'<div class="head ds-head dt-head"><h1>{esc(title)}</h1>'
            f'<div class="dt-kpis"><div><span>Buying</span><b class="up">{esc(kit.rupees(v_buy))}</b><em>{n_buy} decisions</em></div>'
            f'<div><span>Selling</span><b class="dn">{esc(kit.rupees(v_sell))}</b><em>{n_sell} decisions</em></div>'
            f'<div><span>Clubbed</span><b>{clubbed}</b><em>below the size bar</em></div></div></div>')
    if d.empty:
        st.html(f'<p class="dt-empty">No open-market insider decisions above the bar in the last {days} days.</p>')
        return
    st.html(_insider_table(ctx, d, px, names))
    st.html(f'<p class="dt-foot">Clubbed: <b>{clubbed}</b> smaller decisions under ₹{ideas.MIN_VALUE / 1e5:.0f} L or '
            f'{ideas.MIN_PCT:g}% of the company. Pledges, inter-se transfers, ESOP and gifts are not trades and are not counted here. '
            '"Since" = last close against the average price paid, adjusted for splits. "First in 12 months": these people did not trade this company on this side in the 12 months before; "routine": in 6 or more of them. An amber "to / from" names the other side when the trade '
            'was one side of a matched bulk or block deal: a negotiated sale or purchase, not the open market. Holding Δ = shares traded against the promoter group\'s '
            'stake in the latest shareholding pattern (promoters), or the person\'s own holding before (directors, KMP).</p>')


def _insider_table(ctx, d, px, names, company_col=True) -> str:
    # % of company first (the comparable size), then rupees
    d = d.sort_values(['side', 'pct_of_company'], ascending=[True, False], kind='stable')
    rows = []
    for r in d.to_dict('records'):
        p = px.get(r['isin']) or {}
        _, move = moves._paid_now(ctx, r['isin'], r['avg_price'], r['trade_to'], p.get('latest_close'))
        lag = (pd.Timestamp(r['last']).normalize() - pd.Timestamp(r['trade_to']).normalize()).days if pd.notna(r['trade_to']) else None
        buy = r['side'] == 'BUY'
        who_kind = 'Promoter' if r['promoter_group'] else 'Director/KMP'
        own = r.get('group_change') if r['promoter_group'] and kit._finite(r.get('group_change')) is not None else (
            None if r['promoter_group'] else r.get('own_change'))
        rows.append({
            'co': _company(names.get(r['isin']) or r['company'], r['nse_symbol']),
            # on a phone only the side shows (the role word is .ph), so the value and "since" fit
            'sig': f'<span class="dt-chip {"up" if buy else "dn"}"><span class="ph">{esc(who_kind)} </span>{"buy" if buy else "sell"}</span>',
            'who': esc(moves._short_who(r)) + (f' <span class="mute">+{len(r["people"]) - 1}</span>' if len(r['people']) > 1 else ''),
            # a trade that is one side of a matched bulk/block deal: the other side, as the exchange named it (13 Nov 2026)
            # routine (traded in most of the 12 months before) or the first in 12 months; the product window starts 8 Oct 2025
            'hist': (' ' + _chip(f'routine · {r["prior_months"]} of 12 months', '') if r.get('prior_months', 0) >= ideas.ROUTINE_MONTHS
                     else ' ' + _chip('first in 12 months', 'up' if buy else 'dn') if r.get('prior_months') == 0 else ''),
            'cross': ((' ' + _chip(('to ' if not buy else 'from ') + str(r['cross_with'][0])[:40] + (' +' + str(len(r['cross_with']) - 1)
                                    if len(r['cross_with']) > 1 else ''), 'wn')) if isinstance(r.get('cross_with'), list) and r['cross_with'] else ''),
            'val': esc(kit.rupees(r['value'])),
            'pct': _num(r['pct_of_company'], '{:.2f}%'),
            # the promoter group's stake is the base for a promoter decision, the person's own for a director (13 Nov)
            'own': _num(own, '{:+.1f}%') if buy else _num(-own if kit._finite(own) is not None else own, '{:+.1f}%'),
            'avg': _num(r['avg_price'], '₹{:,.1f}'),
            'since': (f'<span class="{("up" if move > 0 else "dn" if move < 0 else "") if buy else ""}">{move:+.1f}%</span>' if move is not None else '<span class="mute">–</span>'),
            'days': str(r['days']),
            'when': esc(kit.day(r['trade_to'], with_year=False)) if pd.notna(r['trade_to']) else '–',
            'filed': esc(kit.day(r['last'], with_year=False)) + (' ' + _chip(f'{lag}d late', 'wn') if lag is not None and lag >= moves.LATE_DAYS else ''),
            'ev': f'<span class="ev" title="{r["filings"]} exchange filing(s), NSE and BSE copies merged">×{r["filings"]}</span>',
        })
    # ' ph': off at phone width (dt.css), so a phone shows who, how much, how big and what since without scrolling
    for x in rows:   # history and the counterparty ride with the signal and who
        x['sig'] += x.pop('hist', '')
        x['who'] += x.pop('cross', '')
    cols = [('co', 'Company', 'l'), ('sig', 'Signal', 'l'), ('who', 'Who', 'l ph'), ('val', '₹ value', 'r'),
            ('pct', '% of co.', 'r'), ('own', 'Holding Δ', 'r ph'), ('avg', 'Avg price', 'r ph'), ('since', 'Since', 'r'),
            ('days', 'Days', 'r ph'), ('when', 'Last trade', 'r ph'), ('filed', 'Filed', 'r ph'), ('ev', 'Filings', 'l ph')]
    if not company_col:
        cols = [c for c in cols if c[0] != 'co']
    return _table(cols, rows)


# ---- Situations: offers, buybacks, delistings, raises -----------------------------------------------------------------

def _days_left(close, ref) -> int | None:
    c = pd.to_datetime(close, errors='coerce')
    return None if pd.isna(c) else int((c.normalize() - pd.Timestamp(ref).normalize()).days)


def situations():
    ctx = load()
    if not need_data(ctx):
        return
    ref = pd.Timestamp(ctx.ref)
    px, _, names = moves.lookups(ctx)
    _strip(ctx, ['NSE tender offers', 'rights, QIP and preferential listings', 'prices: last close'])
    st.html('<div class="head ds-head dt-head"><h1>Situations</h1><p class="dt-dek">Offers you can tender into, and capital raised, '
            'with the arithmetic done. Spread = offer price against the last close.</p></div>')

    # Tender offers: open, and closed in the last 60 days
    t = store.table('tenders')
    if not t.empty:
        t = t.assign(_close=pd.to_datetime(t['offer_close'], errors='coerce'), _open=pd.to_datetime(t['offer_open'], errors='coerce'))
        t = t[(t['status'] == 'active') | (t['_close'] >= ref - pd.Timedelta(days=60))].sort_values(['_close'], ascending=False)
    rows = []
    for r in t.to_dict('records') if not t.empty else []:
        p = px.get(r.get('isin')) or {}
        close = p.get('latest_close')
        offer = r.get('offer_price')
        spread = (offer / close - 1) * 100 if kit._finite(offer) is not None and kit._finite(close) else None
        times = r.get('times_tendered')
        acc = min(1.0, 1 / times) * 100 if kit._finite(times) and times > 0 and r.get('offer_type') != 'delisting' else None
        left = _days_left(r['_close'], ref)
        live = r.get('status') == 'active' and left is not None and left >= 0
        rows.append({
            'co': _company(names.get(r.get('isin')) or r.get('company_display') or r.get('company'), str(r.get('symbol') or '').upper()),
            'type': _chip(str(r.get('offer_type') or '').capitalize(), {'buyback': 'up', 'takeover': '', 'delisting': 'wn'}.get(r.get('offer_type'), '')),
            'price': _num(offer, '₹{:,.2f}'),
            'close': _num(close, '₹{:,.2f}'),
            'spread': (f'<b class="{"up" if spread > 0 else "dn"}">{spread:+.1f}%</b>' if spread is not None else '<span class="mute">–</span>'),
            'size': esc(kit.shares(r.get('shares_sought'))) if kit._finite(r.get('shares_sought')) is not None else '–',
            'times': _num(times, '{:.2f}×'),
            'acc': (_num(acc, '{:.0f}%') + ('' if not live else ' <span class="mute">so far</span>')) if acc is not None else '<span class="mute">–</span>',
            'win': esc(f'{kit.day(r["_open"], with_year=False)} – {kit.day(r["_close"], with_year=False)}') if pd.notna(r['_open']) else '–',
            'left': _chip(f'{left} days left', 'up') if live else _chip('Closed', ''),
        })
    st.html('<h2 class="dt-h2">Tender offers <span>buybacks, open offers, delistings · open and closed in the last 60 days</span></h2>')
    st.html(_table([('co', 'Company', 'l'), ('type', 'Type', 'l'), ('price', 'Offer', 'r'), ('close', 'Last close', 'r'),
                    ('spread', 'Spread', 'r'), ('size', 'Shares sought', 'r'), ('times', 'Tendered', 'r'),
                    ('acc', 'Acceptance', 'r'), ('win', 'Window', 'r'), ('left', 'Status', 'l')], rows)
            if rows else '<p class="dt-empty">No tender offers open or closed in the last 60 days (NSE tender list).</p>')

    # Rights issues (listing stage, last 120 days): shares_listed is the pre-issue base (ratio checks: Ola 2:25, Century 3:8)
    rt = store.table('rights')
    rrows = []
    if not rt.empty:
        rt = rt[(rt['stage'] == 'listing')].assign(_a=pd.to_datetime(rt['allotment_date'], errors='coerce'))
        rt = rt[rt['_a'] >= ref - pd.Timedelta(days=120)].sort_values('_a', ascending=False)
        for r in rt.to_dict('records'):
            p = px.get(r.get('isin')) or {}
            close, offer = p.get('latest_close'), r.get('offer_price')
            disc = (offer / close - 1) * 100 if kit._finite(offer) is not None and kit._finite(close) else None
            base, new = r.get('shares_listed'), r.get('shares_allotted')
            dil, est = None, False
            try:
                a, b = (float(x) for x in str(r.get('ratio') or '').split(':'))
            except ValueError:
                a = b = None
            if a and b and kit._finite(base) and kit._finite(new) and base > 0 and abs(new / base - a / b) <= 0.02 * a / b:
                dil = new / (base + new) * 100      # the filed base reconciles with the ratio
            elif a and b:
                dil, est = a / (a + b) * 100, True  # entitlement if fully taken up (the filed base does not reconcile)
            rrows.append({'co': _company(names.get(r['isin']) or r['company'], r.get('symbol')), 'ratio': esc(str(r.get('ratio') or '–')),
                          'price': _num(offer, '₹{:,.2f}'), 'close': _num(close, '₹{:,.2f}'),
                          'disc': _num(disc, '{:+.1f}%'), 'dil': _num(dil, '{:.1f}%') + (' <span class="mute" title="from the ratio, if fully taken up">ratio</span>' if est else ''),
                          'amt': esc(kit.rupees(r.get('amount_raised'))) if kit._finite(r.get('amount_raised')) is not None else '–',
                          'rec': esc(kit.day(r.get('record_date'), with_year=False)) if r.get('record_date') else '–',
                          'allot': esc(kit.day(r['_a'], with_year=False))})
    st.html('<h2 class="dt-h2">Rights issues <span>allotted in the last 120 days</span></h2>')
    st.html(_table([('co', 'Company', 'l'), ('ratio', 'Ratio', 'r'), ('price', 'Issue price', 'r'), ('close', 'Last close', 'r'),
                    ('disc', 'vs close', 'r'), ('dil', 'Dilution', 'r'), ('amt', 'Raised', 'r'), ('rec', 'Record date', 'r'),
                    ('allot', 'Allotted', 'r')], rrows) if rrows else '<p class="dt-empty">No rights issues allotted in the last 120 days.</p>')

    # QIPs (listing stage, last 120 days): issue price against the SEBI floor
    q = store.table('qip')
    qrows = []
    if not q.empty:
        q = q[q['stage'] == 'listing'].assign(_a=pd.to_datetime(q['allotment_date'], errors='coerce'))
        q = q[q['_a'] >= ref - pd.Timedelta(days=120)].sort_values('_a', ascending=False)
        for r in q.to_dict('records'):
            p = px.get(r.get('isin')) or {}
            close = p.get('latest_close')
            since = (close / r['issue_price'] - 1) * 100 if kit._finite(close) and kit._finite(r.get('issue_price')) else None
            qrows.append({'co': _company(names.get(r['isin']) or r['company'], r.get('symbol')),
                          'floor': _num(r.get('floor_price'), '₹{:,.2f}'), 'price': _num(r.get('issue_price'), '₹{:,.2f}'),
                          'vs': _num(r.get('issue_vs_floor'), '{:+.2f}%'), 'close': _num(close, '₹{:,.2f}'),
                          'since': (f'<span class="{"up" if since > 0 else "dn"}">{since:+.1f}%</span>' if since is not None else '–'),
                          'amt': esc(kit.rupees(r.get('amount_raised'))) if kit._finite(r.get('amount_raised')) is not None else '–',
                          'n': _num(r.get('allottees'), '{:,.0f}'), 'allot': esc(kit.day(r['_a'], with_year=False))})
    st.html('<h2 class="dt-h2">QIPs <span>allotted in the last 120 days · issue price against the SEBI floor</span></h2>')
    st.html(_table([('co', 'Company', 'l'), ('floor', 'SEBI floor', 'r'), ('price', 'Issue price', 'r'), ('vs', 'vs floor', 'r'),
                    ('close', 'Last close', 'r'), ('since', 'Since issue', 'r'), ('amt', 'Raised', 'r'), ('n', 'Allottees', 'r'),
                    ('allot', 'Allotted', 'r')], qrows) if qrows else '<p class="dt-empty">No QIPs allotted in the last 120 days.</p>')

    # Preferential (listing stage, last 60 days): price against the ICDR minimum where it is filed or computed
    pf = store.table('preferential')
    prows = []
    if not pf.empty:
        pf = pf[pf['stage'] == 'listing'].assign(_a=pd.to_datetime(pf['allotment_date'], errors='coerce'))
        pf = pf[pf['_a'] >= ref - pd.Timedelta(days=60)].sort_values('_a', ascending=False)
        for r in pf.to_dict('records'):
            p = px.get(r.get('isin')) or {}
            close = p.get('latest_close')
            price = r.get('offer_price')
            since = (close / price - 1) * 100 if kit._finite(close) and kit._finite(price) and price > 0 else None
            prows.append({'co': _company(names.get(r['isin']) or r['company'], r.get('symbol')),
                          'to': esc({'PROMOTER': 'Promoters', 'NON_PROMOTER': 'Non-promoters', 'MIXED': 'Both'}.get(r.get('allottee_category'), '–')),
                          'price': _num(price, '₹{:,.2f}'), 'vs': _num(r.get('vs_icdr_min'), '{:+.1f}%'),
                          'close': _num(close, '₹{:,.2f}'),
                          'since': (f'<span class="{"up" if since > 0 else "dn"}">{since:+.1f}%</span>' if since is not None else '–'),
                          'amt': esc(kit.rupees(r.get('amount_raised'))) if kit._finite(r.get('amount_raised')) is not None else '–',
                          'allot': esc(kit.day(r['_a'], with_year=False))})
    st.html('<h2 class="dt-h2">Preferential allotments <span>last 60 days · price against the SEBI (ICDR) minimum where known</span></h2>')
    st.html(_table([('co', 'Company', 'l'), ('to', 'Allotted to', 'l'), ('price', 'Issue price', 'r'), ('vs', 'vs ICDR min', 'r'),
                    ('close', 'Last close', 'r'), ('since', 'Since issue', 'r'), ('amt', 'Raised', 'r'), ('allot', 'Allotted', 'r')],
                   prows[:40]) if prows else '<p class="dt-empty">No preferential allotments listed in the last 60 days.</p>')
    if len(prows) > 40:
        st.html(f'<p class="dt-foot">{len(prows) - 40} more preferential allotments in the period.</p>')


# ---- Deals: matched pairs as one line ---------------------------------------------------------------------------------

def _deal_rows(d):
    """Deal rows (matched pairs as one line), the market-maker legs and the legs under ₹1 Cr clubbed."""
    mm = d['client_is_market_maker'].astype('boolean').fillna(False) if 'client_is_market_maker' in d else pd.Series(False, index=d.index)
    churn, d = int(mm.sum()), d[~mm]
    rows, used = [], set()
    if 'matched_pair' in d and d['matched_pair'].notna().any():
        for pid, g in d[d['matched_pair'].notna()].groupby('matched_pair'):
            if len(g) != 2 or set(g['side']) != {'BUY', 'SELL'}:
                continue
            b, s_ = g[g['side'] == 'BUY'].iloc[0], g[g['side'] == 'SELL'].iloc[0]
            used.update(g.index)
            grp = bool(b.get('client_is_promoter')) and bool(s_.get('client_is_promoter'))
            rows.append(dict(_v=b['value'], date=b['date'], isin=b['isin'], company=b['company'], sym=b.get('nse_symbol') or b.get('symbol'),
                             kind=_chip('Group transfer', '') if grp else _chip('Negotiated cross', 'wn'),
                             who=f'{esc(str(s_["client_name"]))} <span class="mute">→</span> {esc(str(b["client_name"]))}',
                             qty=b['quantity'], price=b['price'], pct=b.get('pct_of_mcap'), feed=b.get('feeds'), ex=b.get('exchange'), n=b.get('trades')))
    rest = d.drop(index=list(used))
    small = rest['value'] < 1e7
    clubbed_small, rest = int(small.sum()), rest[~small]
    for r in rest.to_dict('records'):
        buy = r['side'] == 'BUY'
        cp = str(r.get('counterparties') or '').split('; ')[0]
        rows.append(dict(_v=r['value'], date=r['date'], isin=r['isin'], company=r['company'], sym=r.get('nse_symbol') or r.get('symbol'),
                         kind=_chip('Buy' if buy else 'Sell', 'up' if buy else 'dn') + (' ' + _chip('Promoter', '') if r.get('client_is_promoter') else ''),
                         who=esc(str(r['client_name'])) + (f' <span class="mute">· other side: {esc(cp)}</span>' if cp else ''),
                         qty=r['quantity'], price=r['price'], pct=r.get('pct_of_mcap'), feed=r.get('feeds'), ex=r.get('exchange'), n=r.get('trades')))
    return rows, churn, clubbed_small


def _deal_table(rows, names, limit=80, company_col=True, with_year=False) -> str:
    out = [{'date': esc(kit.day(r['date'], with_year=with_year)), 'co': _company(names.get(r['isin']) or r['company'], r['sym']),
            'kind': r['kind'], 'who': f'<span class="clip">{r["who"]}</span>', 'qty': esc(kit.shares(r['qty'])), 'price': _num(r['price'], '₹{:,.2f}'),
            'val': esc(kit.rupees(r['_v'])), 'pct': _num(r['pct'], '{:.2f}%'),
            # one line per client, day and side: the exchange rows it adds up are counted (C6: others list 2-4 rows a deal)
            'src': esc(f'{str(r.get("ex") or "").upper()} {r.get("feed") or ""}'.strip())
                   + (f' <span class="mute" title="exchange rows added into this line">· {int(r["n"])} rows</span>'
                      if kit._finite(r.get('n')) is not None and r['n'] > 1 else '')} for r in rows[:limit]]
    cols = [('date', 'Date', 'l ph'), ('co', 'Company', 'l'), ('kind', 'Type', 'l'), ('val', '₹ value', 'r'),
            ('pct', '% of co.', 'r'), ('qty', 'Shares', 'r ph'), ('price', 'Price', 'r ph'), ('who', 'Client', 'l ph'), ('src', 'Source', 'l ph')]
    if not company_col:
        cols = [c for c in cols if c[0] != 'co']
    return _table(cols, out) if out else '<p class="dt-empty">No deals of ₹1 Cr or more in the period.</p>'


def deals():
    ctx = load()
    if not need_data(ctx):
        return
    days = _period('dt_deals_period')
    ref = pd.Timestamp(ctx.ref)
    _, _, names = moves.lookups(ctx)
    d = ctx.deals
    d = d[(d['date'] > ref - pd.Timedelta(days=days)) & (d['date'] <= ref)] if not d.empty else d
    rows, churn, clubbed_small = _deal_rows(d)
    rows.sort(key=lambda x: -(x['_v'] or 0))
    _strip(ctx, [f'bulk and block deals, last {days} days', 'NSE and BSE', 'market makers clubbed'])
    st.html(f'<div class="head ds-head dt-head"><h1>Bulk and block deals · last {days} days</h1>'
            f'<div class="dt-kpis"><div><span>Deals shown</span><b>{len(rows)}</b><em>₹1 Cr and over</em></div>'
            f'<div><span>Market makers</span><b>{churn}</b><em>legs clubbed</em></div>'
            f'<div><span>Small</span><b>{clubbed_small}</b><em>legs under ₹1 Cr</em></div></div></div>')
    st.html(_deal_table(rows, names))
    note = '' if 'matched_pair' in ctx.deals else ' Matched pairs show as one line once the nightly clean has run with the new rule.'
    st.html(f'<p class="dt-foot">A group transfer is a matched buyer and seller who are both the company\'s promoters; a negotiated cross is '
            f'a matched pair that is not. {len(rows) - 80 if len(rows) > 80 else 0} more deals not shown.{note}</p>')


# ---- Stakes: SAST crossings and pledges ---------------------------------------------------------------------------------

THRESHOLDS = (5, 10, 15, 20, 25, 50, 75)
SAST_COLS = [('co', 'Company', 'l'), ('who', 'Holder', 'l ph'), ('act', '', 'l ph'), ('moved', 'Moved', 'r'), ('stake', 'Stake', 'r'),
             ('cross', 'Threshold', 'l ph'), ('mode', 'Mode · Reg', 'l ph'), ('when', 'Trade', 'r ph'), ('filed', 'Filed', 'r ph'), ('ev', 'Evidence', 'l ph')]


def _crossed(before, after) -> str:
    if not (kit._finite(before) is not None and kit._finite(after) is not None):
        return ''
    lo, hi = sorted((before, after))
    hit = [t for t in THRESHOLDS if lo < t <= hi]
    if not hit:
        return ''
    span = f'{hit[0]}%' if len(hit) == 1 else f'{hit[0]}–{hit[-1]}%'   # a range keeps the column narrow (5–20%, not 5%, 10%, 15%, 20%)
    return ('crossed ' if after > before else 'fell below ') + span


def _sast_rows(sa, names, with_year=False):
    """SAST Reg 29 rows, newest first; inter-se transfers and moves under 0.1% counted, not listed. `sa` has _f (filed)."""
    rows = []
    inter_m = sa['mode'].astype(str).str.lower().str.contains('inter')
    tiny_m = pd.to_numeric(sa['percent_equity_traded'], errors='coerce').abs() < 0.1
    inter, tiny = int(inter_m.sum()), int((tiny_m & ~inter_m).sum())
    for r in sa[~inter_m & ~tiny_m].sort_values('_f', ascending=False).to_dict('records'):
        moved = r.get('percent_equity_traded')
        after = r.get('post_stake_pct')
        before = after - moved if kit._finite(after) is not None and kit._finite(moved) is not None else None
        lag = (pd.Timestamp(r['_f']).normalize() - pd.to_datetime(r.get('trade_date_to'), errors='coerce')).days \
            if pd.notna(pd.to_datetime(r.get('trade_date_to'), errors='coerce')) else None
        up = (moved or 0) > 0
        att = r.get('attachment')
        rows.append({'co': _company(names.get(r.get('isin')) or r.get('company_display') or r.get('company'), r.get('symbol')),
                     'who': '<span class="clip" style="max-width:220px">' + esc(str(r.get('acquirer_name') or '')) + '</span>' + (' ' + _chip('Promoter', '') if r.get('is_promoter') else ''),
                     'act': _chip('Bought' if up else 'Sold', 'up' if up else 'dn'),
                     'moved': _num(moved, '{:+.2f}%'), 'stake': (f'<span title="Derived: stake after less the move; NSE files the after and the move only">{_num(before, "{:.2f}%")}</span>'
                               + ' → ' + _num(after, '{:.2f}%')),
                     'cross': esc(_crossed(before, after)), 'mode': esc(str(r.get('mode') or '')) + f' <span class="mute">{esc(str(r.get("regulation") or "").replace("Reg", ""))}</span>', 'reg': '',
                     'when': esc(kit.day(r.get('trade_date_to'), with_year=with_year)) if r.get('trade_date_to') else '–',
                     'filed': esc(kit.day(r['_f'], with_year=with_year)) + (' ' + _chip(f'{lag}d late', 'wn') if lag is not None and lag > 14 else ''),
                     'ev': f'<a class="ev" href="{esc(att, quote=True)}" target="_blank">Filing</a>' if isinstance(att, str) and att.startswith('http') else ''})
    return rows, inter, tiny


def stakes():
    ctx = load()
    if not need_data(ctx):
        return
    days = _period('dt_stakes_period', '30 days')
    ref = pd.Timestamp(ctx.ref)
    _, _, names = moves.lookups(ctx)
    _strip(ctx, [f'SAST Reg 29 and Reg 31 filings, last {days} days', 'NSE and BSE'])
    st.html(f'<div class="head ds-head dt-head"><h1>Stakes and pledges · last {days} days</h1>'
            '<p class="dt-dek">Holders crossing 5%, 10%, 25% or moving 2% or more, and promoter pledges netted per day.</p></div>')
    sa = ctx.sast
    rows, inter, tiny = [], 0, 0
    if sa is not None and not sa.empty:
        sa = sa.assign(_f=pd.to_datetime(sa['broadcast_ts'], errors='coerce', format='mixed'))
        sa = sa[(sa['_f'] > ref - pd.Timedelta(days=days)) & (sa['_f'] <= ref + pd.Timedelta(days=1))]
        rows, inter, tiny = _sast_rows(sa, names)
    st.html('<h2 class="dt-h2">Stake changes <span>SAST Reg 29 · inter-se transfers and moves under 0.1% clubbed</span></h2>')
    st.html(_table(SAST_COLS, rows[:80]) if rows else '<p class="dt-empty">No SAST Reg 29 filings in the period.</p>')
    st.html(f'<p class="dt-foot">Clubbed: <b>{inter}</b> inter-se transfers within promoter groups, <b>{tiny}</b> moves under 0.1% of the company. '
            'Stake: the figure before the arrow is derived (after less the move); NSE files the stake after and the move.</p>')

    try:
        _pledges(ctx, ref, days, names)
    except Exception as exc:   # say what failed instead of breaking the page; shown, not hidden
        st.html(f'<p class="dt-empty">Pledges could not be drawn: {esc(type(exc).__name__)}: {esc(str(exc)[:200])}</p>')


def _encumbered_after(g):
    """% of the company encumbered after the day's events, over the holders who filed: each holder's last
    `post_event_holding_pct`. NSE's `encumbPerc` (our `encumbered_pct`) is the encumbrance BEFORE the event: Themis
    Medicare 4.89% before + 2.71% created = 7.60% after; Paisalo 3.17 + 1.10 = 4.27 (raw sample, 13 Nov 2026)."""
    if 'post_event_holding_pct' not in g:
        return None
    v = pd.to_numeric(g['post_event_holding_pct'].astype(str).str.strip(), errors='coerce')
    who = g['promoter_id'] if 'promoter_id' in g else pd.Series(0, index=g.index)
    last = v.groupby(who.to_numpy()).last()
    return float(last.sum()) if last.notna().any() else None


def _pledges(ctx, ref, days, names):
    en = ctx.encumbrances
    prow = []
    if en is not None and not en.empty:
        en = en.assign(_d=pd.to_datetime(en['broadcast_date'], errors='coerce'))
        en = en[(en['_d'] > ref - pd.Timedelta(days=days)) & (en['_d'] <= ref)]
        sign = en['event_type'].map({'Creation': 1, 'Release': -1, 'Invocation': -1}).fillna(0)
        en = en.assign(_net=pd.to_numeric(en['shares'], errors='coerce') * sign)
        key = 'isin' if 'isin' in en else 'symbol'   # the site's encumbrances table has no ISIN (DATA_DICTIONARY)
        for (isin, day), g in en.groupby([key, '_d']):
            made = g.loc[g['event_type'] == 'Creation', 'shares'].sum()
            freed = g.loc[g['event_type'] != 'Creation', 'shares'].sum()
            net = made - freed
            inv = (g['event_type'] == 'Invocation').any()
            roll = made > 0 and freed > 0 and abs(net) < 0.05 * max(made, freed)
            pctc = (g['pct_of_company'] * g['event_type'].map({'Creation': 1, 'Release': -1, 'Invocation': -1}).fillna(0)).sum()
            r0 = g.iloc[0]
            att = r0.get('attachment')
            prow.append({'_k': (0 if inv else 1, -abs(pctc)), 'co': _company((names.get(isin) if key == 'isin' else None) or r0.get('company_display') or r0.get('company'), r0.get('symbol')),
                         'ev': (_chip('Invoked', 'dn') if inv else _chip('Rollover', '') if roll else _chip('Pledged more', 'wn') if net > 0 else _chip('Released', 'up')),
                         'net': esc(kit.shares(net)) if net else '0', 'pct': _num(pctc, '{:+.2f}%'),
                         'enc': _num(_encumbered_after(g), '{:.2f}%'),
                         'lender': esc(', '.join(sorted(set(str(x) for x in g['lender'].dropna())))[:60]),
                         'rows': str(len(g)), 'filed': esc(kit.day(day, with_year=False)),
                         'src': f'<a class="ev" href="{esc(att, quote=True)}" target="_blank">Filing</a>' if isinstance(att, str) and att.startswith('http') else ''})
        prow.sort(key=lambda x: x['_k'])
    st.html('<h2 class="dt-h2">Pledges <span>SAST Reg 31 · netted per company and day · invocations first</span></h2>')
    st.html(_table([('co', 'Company', 'l'), ('ev', 'What happened', 'l'), ('net', 'Net shares', 'r'), ('pct', 'Net % of co.', 'r'),
                    ('enc', 'Encumbered after', 'r'), ('lender', 'Lender', 'l'), ('rows', 'Filings', 'r'), ('filed', 'Filed', 'r'),
                    ('src', 'Evidence', 'l')], prow[:60]) if prow else
            '<p class="dt-empty">No pledge filings in the period (NSE Reg 31 feed; filings arrive a median 8 days after the event).</p>')


# ---- Data health: can I trust today's numbers? -------------------------------------------------------------------------

SOURCES = [   # (label, clean table, date column, what the date is)
    ('Insider trades (SEBI PIT, NSE + BSE)', 'insider_trades', 'broadcast_date', 'filed'),
    ('Bulk and block deals (NSE + BSE)', 'deals', 'date', 'deal day'),
    ('Stake changes (SAST Reg 29)', 'sast', 'broadcast_ts', 'filed'),
    ('Pledges (SAST Reg 31, NSE)', 'encumbrances', 'broadcast_date', 'filed'),
    ('Shareholding patterns', 'shareholding', 'quarter_end', 'quarter or event'),
    ('Results (integrated filing XBRL)', 'results', ('broadcast_date', 'broadcast_at'), 'filed'),
    ('Tender offers (buyback, open offer, delisting)', 'tenders', 'last_seen', 'last listed'),
    ('Preferential issues', 'preferential', 'posted_on', 'posted'),
    ('Rights issues', 'rights', 'posted_on', 'posted'),
    ('QIPs', 'qip', 'posted_on', 'posted'),
    ('Board meetings', 'meetings', 'intimation_ts', 'intimated'),
    ('Corporate actions', 'actions', None, ''),
]
KNOWN = {   # what the raw data showed on 12 Nov 2026 (docs/TODO.md, the design synthesis)
    'encumbrances': 'NSE posts Reg 31 pledges a median 8 days (up to 56) after the event: the last week is always thin.',
    'sast': 'BSE\'s SAST feed returned no rows for 6-12 Nov while NSE had 30: BSE rows are unconfirmed until it answers again.',
    'results': 'Year-ago quarters loaded back to Apr 2025 filings (93% of Sep 2026 companies).',
}


def data_health():
    ctx = load()
    if not need_data(ctx):
        return
    ref = pd.Timestamp(ctx.ref)
    rep = store.report() or {}
    tabs = rep.get('tables', {})
    _strip(ctx, [f'cleaning run of {kit.day(rep.get("run_date"))}' if rep.get('run_date') else 'no cleaning report'])
    st.html('<div class="head ds-head dt-head"><h1>Data health</h1><p class="dt-dek">Each source: how many rows we hold, '
            'the latest date in it, and what the cleaning removed or held back. Amber: older than 3 days; red: older than 10.</p></div>')
    rows = []
    for label, name, col, what in SOURCES:
        try:
            t = store.table(name)
        except Exception:   # a table not published yet: say so, don't fail the page
            t = pd.DataFrame()
        last = None
        cols = [c for c in ((col,) if isinstance(col, str) else (col or ())) if not t.empty and c in t]
        if cols:
            v = pd.to_datetime(t[cols[0]], errors='coerce', format='mixed', utc=cols[0].endswith('_at'))
            last = (v.dt.tz_convert('Asia/Kolkata').dt.tz_localize(None) if cols[0].endswith('_at') else v).max()
        age = max(0, (ref.normalize() - last.normalize()).days) if last is not None and pd.notna(last) and what != 'quarter or event' else None
        tone = '' if age is None else ('up' if age <= 3 else 'wn' if age <= 10 else 'dn')
        tr = tabs.get(name, {})
        removed = sum(v.get('count', 0) for v in tr.get('removed', {}).values()) if isinstance(tr.get('removed'), dict) else None
        flagged = sum(tr.get('flagged', {}).values()) if isinstance(tr.get('flagged'), dict) else None
        rows.append({'src': esc(label), 'rows': f'{len(t):,}' if not t.empty else '<span class="mute">none</span>',
                     'last': (esc(kit.day(last)) + (f' <span class="mute">({what})</span>' if what else '')) if last is not None and pd.notna(last) else '<span class="mute">–</span>',
                     'age': _chip(f'{age} days old' if age else 'current', tone) if age is not None else '<span class="mute">–</span>',
                     'rem': f'{removed:,}' if removed else '<span class="mute">–</span>',
                     'flag': f'{flagged:,}' if flagged else '<span class="mute">–</span>',
                     'note': f'<span class="wrap">{esc(KNOWN.get(name, ""))}</span>'})
    st.html(_table([('src', 'Source', 'l'), ('rows', 'Rows', 'r'), ('last', 'Latest', 'r'), ('age', 'Age', 'l'),
                    ('rem', 'Removed', 'r'), ('flag', 'Held back', 'r'), ('note', 'Known limits', 'l')], rows))
    st.html('<p class="dt-foot">Removed: exact copies, revisions replaced and rows outside the product window, each counted by reason. '
            'Held back: kept but out of rankings until checked. Raw exchange responses are kept byte for byte under raw_v2/.</p>')
    _events_run(store.events_report())


def _events_run(ev: dict) -> None:
    """The last nightly NSE events run: rows fetched per stream, NSE's own results count against what we listed, and
    the night's notes (a short listing, a refusal), as the collector wrote them (run_daily.publish_report)."""
    st.html('<h2 class="dt-h2">Last NSE events run <span>as the collector reported it</span></h2>')
    if not ev:
        st.html('<p class="dt-empty">Not published yet: the nightly run writes its report from 13 Nov 2026.</p>')
        return
    rows = []
    for name, e in (ev.get('streams') or {}).items():
        if not isinstance(e, dict):
            continue
        listed = ''
        if name == 'results' and ev.get('results_total'):
            got, tot = int(ev.get('results_listed') or 0), int(ev['results_total'])
            listed = _chip(f'{got:,} of {tot:,} NSE lists', 'up' if got >= tot else 'dn')
        rows.append({'s': esc(name), 'f': _num(e.get('fetched'), '{:,.0f}'), 'c': _num(e.get('clean_rows'), '{:,.0f}'), 'x': listed})
    w = ev.get('window') or ['', '']
    st.html(f'<p class="dt-foot">Run of {esc(str(ev.get("run_date") or "?"))}, window {esc(str(w[0]))} to {esc(str(w[-1]))}.</p>')
    st.html(_table([('s', 'Stream', 'l'), ('f', 'Fetched', 'r'), ('c', 'Rows kept', 'r'), ('x', 'Against the exchange', 'l')], rows)
            if rows else '<p class="dt-empty">The report has no streams.</p>')
    notes = [str(n) for n in ev.get('notes') or []]
    st.html('<p class="dt-foot">' + ('<b>Notes:</b> ' + ' · '.join(esc(n) for n in notes[:12]) if notes else 'No failures or short listings noted.') + '</p>')


# ---- Results: latest quarter per filing, with the comparisons done --------------------------------------------------

def _pct_cell(v, colour=True):
    if kit._finite(v) is None:
        return '<span class="mute">–</span>'
    cls = ('up' if v > 0 else 'dn' if v < 0 else '') if colour else ''
    return f'<span class="{cls}">{v:+.1f}%</span>'


def results():
    from screens import more_pages
    ctx = load()
    if not need_data(ctx):
        return
    days = _period('dt_results_period')
    _, _, names = moves.lookups(ctx)
    r = more_pages._latest_results(ctx, days)
    _strip(ctx, [f'results filed in the last {days} days', 'NSE integrated filing XBRL', 'year-ago from our own history (from Apr 2025 filings)'])
    n_up = int((r['rev_yoy'] > 0).sum()) if not r.empty else 0
    n_dn = int((r['rev_yoy'] < 0).sum()) if not r.empty else 0
    st.html(f'<div class="head ds-head dt-head"><h1>Results · last {days} days</h1>'
            f'<div class="dt-kpis"><div><span>Filings</span><b>{len(r)}</b><em>quarterly results</em></div>'
            f'<div><span>Revenue up YoY</span><b class="up">{n_up}</b><em>companies</em></div>'
            f'<div><span>Revenue down YoY</span><b class="dn">{n_dn}</b><em>companies</em></div></div></div>')
    if r.empty:
        st.html(f'<p class="dt-empty">No results filed in the last {days} days.</p>')
        return
    # Rank by the size of the change only where the year-ago quarter is at least Rs 10 Cr: a tiny base makes +1,775%
    # (Tarc, 12 Nov) and hides the companies that matter; smaller bases follow, then filings with no comparison.
    base = r['quarter_revenue'] / (1 + r['rev_yoy'] / 100)
    r = r.assign(_abs=r['rev_yoy'].abs(), _big=(base >= 1e8).fillna(False)).sort_values(['_big', '_abs'], ascending=[False, False], na_position='last')
    rows = []
    for x in r.head(120).to_dict('records'):
        prof, prev_y = x.get('quarter_profit'), x.get('profit_year')
        turn = ''
        if kit._finite(prof) is not None and kit._finite(prev_y) is not None:
            if prev_y < 0 <= prof:
                turn = _chip('Back to profit', 'up')
            elif prev_y >= 0 > prof:
                turn = _chip('Into loss', 'dn')
        rows.append({'co': _company(names.get(x.get('isin')) or x.get('company'), x.get('symbol')),
                     'q': esc(kit.day(x['_end'], with_year=True)) if pd.notna(x['_end']) else '–',
                     'basis': esc('Cons.' if x['_cons'] else 'Stand.'),
                     'rev': esc(kit.rupees(x.get('quarter_revenue'))) if kit._finite(x.get('quarter_revenue')) is not None else '–',
                     'yoy': _pct_cell(x.get('rev_yoy')), 'qoq': _pct_cell(x.get('rev_qoq')),
                     'prof': esc(kit.rupees(prof)) if kit._finite(prof) is not None else '–',
                     'profy': esc(kit.rupees(prev_y)) if kit._finite(prev_y) is not None else '<span class="mute">–</span>',
                     'turn': turn + (' ' + _chip('Derived', '') if x.get('quarter_derived') == True else ''),   # noqa: E712 -- results.derive_quarters
                     'filed': esc(kit.day(x['_at'], with_year=False)) if pd.notna(x['_at']) else '–'})
    st.html(_table([('co', 'Company', 'l'), ('q', 'Quarter', 'r'), ('basis', 'Basis', 'l'), ('rev', 'Revenue', 'r'),
                    ('yoy', 'YoY', 'r'), ('qoq', 'QoQ', 'r'), ('prof', 'Profit', 'r'), ('profy', 'Year ago', 'r'),
                    ('turn', '', 'l'), ('filed', 'Filed', 'r')], rows))
    st.html(f'<p class="dt-foot">Ranked by the size of the revenue change against the same quarter a year ago, where that quarter was ₹10 Cr or more; smaller bases after; '
            f'{max(0, len(r) - 120)} more filings not shown. A dash: the comparison quarter is not in our history. '
            '"Derived": the filing gives only its half year; the quarter is that less the June quarter filed before.</p>')


# ---- Calendar: what is coming, day by day ------------------------------------------------------------------------------

def calendar():
    from screens import filings_all
    ctx = load()
    if not need_data(ctx):
        return
    ref = pd.Timestamp(ctx.ref).normalize()
    _strip(ctx, ['board meetings on fund raising or buybacks', 'tender windows closing', 'lock-ins ending', 'record dates'])
    st.html('<div class="head ds-head dt-head"><h1>Calendar · next 30 days</h1>'
            '<p class="dt-dek">Events that can move a stock, from the filings: meetings on fund raising or a buyback, offers closing, '
            'lock-ins ending, and record dates for buybacks, bonuses, splits and rights.</p></div>')
    rows = []
    _, up = filings_all._upcoming(ctx, ctx.ref, filings_all._names(ctx))
    if up is not None and not up.empty:
        up = up.assign(_d=pd.to_datetime(up['made_public'], errors='coerce').dt.normalize())
        up = up[(up['_d'] >= ref) & (up['_d'] <= ref + pd.Timedelta(days=30))]
        lock = up['what'].astype(str).str.lower().str.contains('lock-in')
        for (d, sym, co), g in up[lock].groupby(['_d', 'nse_symbol', 'company'], dropna=False):
            n, val = len(g), pd.to_numeric(g['value'], errors='coerce').sum()
            rows.append({'_d': d, 'co': _company(co, sym), 'what': 'Lock-in ends',
                         'detail': f'<span class="wrap">{n} allotment{"s" if n > 1 else ""} free to trade</span>' if n > 1 else
                                   f'<span class="wrap">{esc(str(g["what_sub"].iloc[0] or "")[:120])}</span>',
                         'size': esc(kit.rupees(val)) if val > 0 else ''})
        for r in up[~lock].to_dict('records'):
            rows.append({'_d': r['_d'], 'co': _company(r.get('company'), r.get('nse_symbol')), 'what': esc(str(r.get('what') or '')),
                         'detail': f'<span class="wrap">{esc(str(r.get("what_sub") or "")[:120])}</span>',
                         'size': esc(kit.rupees(r['value'])) if kit._finite(r.get('value')) is not None else ''})
    a = ctx.actions
    if a is not None and not a.empty and 'ex_date' in a:
        a = a.assign(_d=pd.to_datetime(a['ex_date'], errors='coerce').dt.normalize())
        keep = a['purpose'].astype(str).str.lower().isin(['buyback', 'bonus', 'split', 'rights', 'consolidation'])
        for r in a[keep & (a['_d'] >= ref) & (a['_d'] <= ref + pd.Timedelta(days=30))].to_dict('records'):
            rows.append({'_d': r['_d'], 'co': _company(r.get('company'), r.get('symbol')),
                         'what': esc(f'Ex-date: {str(r.get("purpose") or "").capitalize()}'),
                         'detail': f'<span class="wrap">{esc(str(r.get("subject") or "")[:120])}</span>', 'size': ''})
    rows.sort(key=lambda x: x['_d'])
    out = [dict(r, day=esc(pd.Timestamp(r['_d']).strftime('%a %d %b')),
                away=_chip('today', 'wn') if r['_d'] == ref else esc('tomorrow' if (r['_d'] - ref).days == 1 else f'in {(r["_d"] - ref).days} days')) for r in rows]
    st.html(_table([('day', 'Date', 'l'), ('away', '', 'l'), ('co', 'Company', 'l'), ('what', 'Event', 'l'),
                    ('detail', 'Detail', 'l'), ('size', 'Size', 'r')], out[:150]) if out else
            '<p class="dt-empty">Nothing on the calendar in the next 30 days.</p>')
    st.html('<p class="dt-foot">An ex-date is the first day a buyer no longer gets the benefit: buy before it. Dividends are left out.</p>')


# ---- Company: the same dense tables, one company, 12 months (R8) ------------------------------------------------------

def company_tables(ctx, isin: str | None, sym: str, days: int = 365) -> None:
    """Insider decisions, deals and SAST stake changes of one company, as on the topic pages. Every decision is listed
    (no size bar: on its own page a company's small decisions are the story); market makers, inter-se transfers and
    moves under 0.1% stay counted, not listed."""
    ref = pd.Timestamp(ctx.ref)
    px, _, names = moves.lookups(ctx)
    frames = []
    elig = ctx.eligible[ctx.eligible['isin'] == isin] if isin and not ctx.eligible.empty else ctx.eligible.iloc[0:0]
    for side in ('BUY', 'SELL'):
        d = ideas.decisions(elig, ref, side, ctx.shareholding, days) if not elig.empty else pd.DataFrame()
        if not d.empty:
            frames.append(d.assign(side=side))
    d = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    st.html('<h2 class="dt-h2">Insider decisions <span>promoters, directors and KMP · open market · 12 months · each decision added up</span></h2>')
    st.html(_insider_table(ctx, d, px, names, company_col=False) if not d.empty
            else '<p class="dt-empty">No promoter, director or KMP traded on the market in 12 months.</p>')

    dl = ctx.deals[ctx.deals['isin'] == isin] if isin and not ctx.deals.empty else ctx.deals.iloc[0:0]
    dl = dl[(dl['date'] > ref - pd.Timedelta(days=days)) & (dl['date'] <= ref)] if not dl.empty else dl
    rows, churn, small = _deal_rows(dl) if not dl.empty else ([], 0, 0)
    rows.sort(key=lambda x: x['date'], reverse=True)
    st.html('<h2 class="dt-h2">Bulk and block deals <span>12 months · matched buyer and seller on one line</span></h2>')
    st.html(_deal_table(rows, names, limit=60, company_col=False, with_year=True))
    if churn or small or len(rows) > 60:
        st.html(f'<p class="dt-foot">Clubbed: <b>{churn}</b> market-maker legs, <b>{small}</b> legs under ₹1 Cr'
                + (f'; {len(rows) - 60} older deals not shown' if len(rows) > 60 else '') + '.</p>')

    sa = ctx.sast
    srows, inter, tiny = [], 0, 0
    if sa is not None and not sa.empty and 'symbol' in sa:
        sa = sa[sa['symbol'].astype(str).str.upper() == sym]
        sa = sa.assign(_f=pd.to_datetime(sa['broadcast_ts'], errors='coerce', format='mixed'))
        sa = sa[(sa['_f'] > ref - pd.Timedelta(days=days)) & (sa['_f'] <= ref + pd.Timedelta(days=1))]
        if not sa.empty:
            srows, inter, tiny = _sast_rows(sa, names, with_year=True)
    st.html('<h2 class="dt-h2">Stake changes <span>SAST Reg 29 · 12 months</span></h2>')
    st.html(_table([c for c in SAST_COLS if c[0] != 'co'], srows[:60]) if srows
            else '<p class="dt-empty">No SAST Reg 29 filing for this company in 12 months.</p>')
    if inter or tiny:
        st.html(f'<p class="dt-foot">Clubbed: <b>{inter}</b> inter-se transfers, <b>{tiny}</b> moves under 0.1% of the company.</p>')
