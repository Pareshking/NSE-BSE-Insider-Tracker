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

def today():
    ctx = load()
    if not need_data(ctx):
        return
    ref = ctx.ref
    px, hold, names = moves.lookups(ctx)
    frames, clubbed = [], 0
    for side in ('BUY', 'SELL'):
        d = ideas.decisions(ctx.eligible, ref, side, ctx.shareholding, DAYS)
        if d.empty:
            continue
        pg = d['promoter_group'].astype(bool)
        keep = ideas._qualifies(d) if side == 'BUY' else (pg & ideas._qualifies(d)) | (~pg & (d['value'] >= ideas.BIG_VALUE))
        clubbed += int((~keep).sum())
        frames.append(d[keep].assign(side=side))
    d = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    n_buy = int((d['side'] == 'BUY').sum()) if not d.empty else 0
    n_sell = int((d['side'] == 'SELL').sum()) if not d.empty else 0
    v_buy = d.loc[d['side'] == 'BUY', 'value'].sum() if not d.empty else 0
    v_sell = d.loc[d['side'] == 'SELL', 'value'].sum() if not d.empty else 0
    _strip(ctx, [f'insider filings, last {DAYS} days', 'NSE + BSE copies merged', 'open-market trades only'])
    st.html('<div class="head ds-head dt-head"><h1>Insiders · last 7 days</h1>'
            f'<div class="dt-kpis"><div><span>Buying</span><b class="up">{esc(kit.rupees(v_buy))}</b><em>{n_buy} decisions</em></div>'
            f'<div><span>Selling</span><b class="dn">{esc(kit.rupees(v_sell))}</b><em>{n_sell} decisions</em></div>'
            f'<div><span>Clubbed</span><b>{clubbed}</b><em>below the size bar</em></div></div></div>')
    if d.empty:
        st.html('<p class="dt-empty">No open-market insider decisions above the bar in the last 7 days.</p>')
        return
    # % of company first (the comparable size), then rupees
    d = d.sort_values(['side', 'pct_of_company'], ascending=[True, False], kind='stable')
    rows = []
    for r in d.to_dict('records'):
        p = px.get(r['isin']) or {}
        _, move = moves._paid_now(ctx, r['isin'], r['avg_price'], r['trade_to'], p.get('latest_close'))
        lag = (pd.Timestamp(r['last']).normalize() - pd.Timestamp(r['trade_to']).normalize()).days if pd.notna(r['trade_to']) else None
        buy = r['side'] == 'BUY'
        sig = ('Promoter' if r['promoter_group'] else 'Director/KMP') + (' buy' if buy else ' sell')
        own = r.get('own_change')
        rows.append({
            'co': _company(names.get(r['isin']) or r['company'], r['nse_symbol']),
            'sig': _chip(sig, 'up' if buy else 'dn'),
            'who': esc(moves._short_who(r)) + (f' <span class="mute">+{len(r["people"]) - 1}</span>' if len(r['people']) > 1 else ''),
            'val': esc(kit.rupees(r['value'])),
            'pct': _num(r['pct_of_company'], '{:.2f}%'),
            'own': _num(own, '{:+.1f}%') if buy else _num(own, '{:.1f}%'),
            'avg': _num(r['avg_price'], '₹{:,.1f}'),
            'since': (f'<span class="{"up" if move > 0 else "dn" if move < 0 else ""}">{move:+.1f}%</span>' if move is not None else '<span class="mute">–</span>'),
            'days': str(r['days']),
            'when': esc(kit.day(r['trade_to'], with_year=False)) if pd.notna(r['trade_to']) else '–',
            'filed': esc(kit.day(r['last'], with_year=False)) + (' ' + _chip(f'{lag}d late', 'wn') if lag is not None and lag >= moves.LATE_DAYS else ''),
            'ev': f'<span class="ev">Filed · {r["filings"]} filing{"s" if r["filings"] != 1 else ""}</span>',
        })
    cols = [('co', 'Company', 'l'), ('sig', 'Signal', 'l'), ('who', 'Who', 'l'), ('val', '₹ value', 'r'),
            ('pct', '% of co.', 'r'), ('own', 'Own holding Δ', 'r'), ('avg', 'Avg price', 'r'), ('since', 'Since', 'r'),
            ('days', 'Days', 'r'), ('when', 'Last trade', 'r'), ('filed', 'Filed', 'r'), ('ev', 'Evidence', 'l')]
    st.html(_table(cols, rows))
    st.html(f'<p class="dt-foot">Clubbed: <b>{clubbed}</b> smaller decisions under ₹{ideas.MIN_VALUE / 1e5:.0f} L or '
            f'{ideas.MIN_PCT:g}% of the company. Pledges, inter-se transfers, ESOP and gifts are not trades and are not counted here. '
            '"Since" = last close against the average price paid, adjusted for splits.</p>')


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
        acc = min(1.0, 1 / times) * 100 if kit._finite(times) and times > 0 else None
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
            dil = new / (base + new) * 100 if kit._finite(base) and kit._finite(new) and base > 0 else None
            rrows.append({'co': _company(names.get(r['isin']) or r['company'], r.get('symbol')), 'ratio': esc(str(r.get('ratio') or '–')),
                          'price': _num(offer, '₹{:,.2f}'), 'close': _num(close, '₹{:,.2f}'),
                          'disc': _num(disc, '{:+.1f}%'), 'dil': _num(dil, '{:.1f}%'),
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
