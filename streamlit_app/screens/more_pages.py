"""More pages from data already collected, no AI (owner, 12 Nov 2026: "whatever possible without requiring AI API, do
it; all the pages one by one first, design we park"). Same shape as screens/pages.py (ui/ds.py).

Watchlist  what happened on my stocks (the list lives in the address, ?watch=A,B, or Streamlit secrets: never committed)
Screener   companies that line up several signals, from the nightly company snapshot, with ready-made filters
Red flags  one row per company with every flag counted (on the Risks page), and who lends against promoter shares
Sectors    where insiders and funds put money, by sector
Results    the latest quarterly results filed (XBRL, from 15 Oct 2026), insiders around them, buys after the window opened
"""
from __future__ import annotations

import pandas as pd
import streamlit as st
from data import store
from ui import ds, kit
from ui.kit import esc

from insiders_clean import ideas, signals
from screens import moves, pages
from screens.ctx import load, need_data, with_flags

LATE_FLAG = 3          # late insider filings in 12 months that make a red flag
WATCH_MAX = 30
STAKE_MIN_PTS = 0.5   # 'Promoters raising their stake': 181 companies at > 0 on real data, many by 0.01 point (12 Nov)


def _ctx():
    ctx = load()
    return ctx if need_data(ctx) else None


def _co(name, sym) -> str:
    return (f'<a href="{esc(kit.company_href(sym), quote=True)}" target="_self">{esc(str(name))}</a>' if isinstance(sym, str) and sym
            else esc(str(name)))


def _names(ctx) -> dict:
    sec = ctx.securities
    return dict(zip(sec['isin'], sec['display_name'])) if sec is not None and not sec.empty and {'isin', 'display_name'} <= set(sec) else {}


# ---- Watchlist -----------------------------------------------------------------------------------------------------

def _watch_symbols() -> list[str]:
    raw = st.query_params.get('watch') or ''
    if not raw:
        try:
            raw = st.secrets.get('watchlist', '') or ''
        except Exception:  # noqa: BLE001 -- no secrets file locally
            raw = ''
    if isinstance(raw, (list, tuple)):
        raw = ','.join(raw)
    return [s.strip().upper() for s in str(raw).replace(' ', ',').split(',') if s.strip()][:WATCH_MAX]


def watchlist():
    ctx = _ctx()
    if ctx is None:
        return
    top, ctl = st.columns([4, 1.4], vertical_alignment='bottom')
    with ctl:
        p, days = pages._period('pg_watch')
    syms = _watch_symbols()
    with top:
        ds.head(f'Watchlist · {esc(pages._span(p, ctx.ref))}', f'{kit.plural(len(syms), "company", "companies")} on your list' if syms
                else 'Your watchlist', ['Kept in the page address (bookmark it) or in the app\'s secrets; never stored by the site.'])
    typed = st.text_input('Symbols', value=','.join(syms), placeholder='NSE symbols, comma separated: HAVELLS, JSL, TITAN',
                          key='watch_in', label_visibility='collapsed')
    new = [s.strip().upper() for s in typed.replace(' ', ',').split(',') if s.strip()][:WATCH_MAX]
    if new != syms:
        st.query_params['watch'] = ','.join(new)
        syms = new
    if not syms:
        ds.empty('Type the NSE symbols of the companies you follow. The address then holds the list: bookmark it.')
        return
    sec = ctx.securities
    by_sym = sec.dropna(subset=['nse_symbol']).drop_duplicates('nse_symbol').set_index('nse_symbol') if sec is not None and not sec.empty else pd.DataFrame()
    key = str(ctx.ref)
    ev = moves.events(ctx, key, days)
    summary = store.artifact('artifacts/track_summary.parquet')
    cal = {}
    for d, items in moves.upcoming(ctx, 30):
        for x in items:
            cal.setdefault(d, []).append(x)
    quiet = []
    for sym in syms:
        if sym not in by_sym.index:
            quiet.append(f'{esc(sym)}: not a symbol in our data')
            continue
        isin = by_sym.loc[sym, 'isin']
        name = by_sym.loc[sym, 'display_name'] if 'display_name' in by_sym else sym
        items = []
        for side in ('BUY', 'SELL'):
            items += moves.insiders(ctx, key, side, days, isin)[0]
        items += moves.deals(ctx, key, days, isin)[0]
        items += moves.event_stories(ctx, ev[ev['isin'] == isin] if not ev.empty else ev,
                                     pages.RAISE_KINDS | pages.RISK_KINDS | pages.RELEASE_KINDS | pages.STAKE_KINDS | pages.HOLDER_KINDS, summary)
        ahead = [x for d, xs in cal.items() for x in xs if f'symbol={sym}"' in x or f'symbol={sym}&' in x]
        if not items and not ahead:
            quiet.append(_co(name, sym))
            continue
        ds.section(str(name), f'{sym} · ' + (kit.plural(len(items), 'filing') + ' past the bar' if items else 'nothing past the bar')
                   + (f' · {kit.plural(len(ahead), "event")} in the next 30 days' if ahead else ''), kit.company_href(sym), 'Company page')
        import copy
        items = [copy.copy(x) for x in items]
        for x in items:
            x.company, x.market = '', ''
        ds.stories(items)
        if ahead:
            ds.html(ds.sub('Coming up, 30 days') + '<div class="ds-rows">' + ''.join(f'<div class="ds-ev"><div class="who">{x}</div></div>' for x in ahead) + '</div>')
    if quiet:
        ds.club('Nothing past the bar in this period', [', '.join(quiet)])


# ---- Screener ------------------------------------------------------------------------------------------------------

def _num(d: pd.DataFrame, c: str) -> pd.Series:
    return pd.to_numeric(d[c], errors='coerce') if c in d else pd.Series(float('nan'), index=d.index)


PRESETS = {
    'Promoters buying, funds adding': (
        'Promoters bought on the market in 90 days, and mutual funds or foreign investors added last quarter; no pledge',
        lambda d: (_num(d, 'promoter_buy_90d') > 0) & ((_num(d, 'mf_change_pts') > 0) | (_num(d, 'fpi_change_pts') > 0))
        & (_num(d, 'pledge').fillna(0) == 0)),
    'Insiders buying near the low': (
        'Promoters, directors or KMP bought on the market in 90 days, and the price is in the lowest quarter of its 52-week range',
        lambda d: (_num(d, 'insider_buy_90d') > 0) & (_num(d, 'range_pos') <= 25)),
    'Funds piling in': ('Mutual funds or foreign investors added 1 point or more of the company last quarter',
                        lambda d: (_num(d, 'mf_change_pts') >= 1) | (_num(d, 'fpi_change_pts') >= 1)),
    'Promoters raising their stake': (f'The promoter holding rose {STAKE_MIN_PTS:g} point or more last quarter, with no pledge',
                                      lambda d: (_num(d, 'promoter_change_pts') >= STAKE_MIN_PTS) & (_num(d, 'pledge').fillna(0) == 0)),
    'Trap: selling and pledging': ('Promoters sold on the market in 90 days and promoter shares are pledged, or the pledge rose',
                                   lambda d: (_num(d, 'promoter_sell_90d') > 0) & ((_num(d, 'pledge') > 0) | (_num(d, 'pledge_change_pts') > 0))),
    'All companies': ('Every company of the study universe (₹100 Cr and up)', lambda d: pd.Series(True, index=d.index)),
}


def screener():
    ctx = _ctx()
    if ctx is None:
        return
    from screens import companies_list
    snap = store.snapshot()
    if snap.empty:
        ds.head('Screener', 'Not built yet', ['The nightly run writes the company snapshot; the screener fills in after its first run.'])
        return
    pick = st.segmented_control('Filter', list(PRESETS), default=list(PRESETS)[0], key='sc_pick', label_visibility='collapsed') or list(PRESETS)[0]
    note, rule = PRESETS[pick]
    d = snap[rule(snap).fillna(False)].copy()
    ds.head(f'Screener · data to {kit.day(ctx.ref)}', f'{kit.plural(len(d), "company", "companies")}: {esc(pick.lower())}', [note + '.'])
    with st.container(key='sc_bar', horizontal=True, vertical_alignment='center', gap='small'):
        q = st.text_input('Search', placeholder='Company or symbol', key='sc_q', type='search', label_visibility='collapsed', width=260)
        sizes = st.pills('Size', companies_list.SIZES, selection_mode='multi', key='sc_size', label_visibility='collapsed')
        sort = st.selectbox('Sort', list(companies_list.SORTS), key='sc_sort', label_visibility='collapsed')
    if q:
        hit = lambda c: d[c].astype(str).str.contains(q, case=False, na=False, regex=False)  # noqa: E731
        d = d[hit('company') | hit('symbol')]
    if sizes:
        d = d[d['mcap_bucket'].isin(sizes)]
    col, asc = companies_list.SORTS[sort]
    d = d.sort_values(col, ascending=asc, na_position='last', kind='stable')
    d['nse_symbol'] = d['symbol']
    d['mk_bucket'], d['mk_cap'], d['mk_px'], d['mk_lo'], d['mk_hi'] = (d['mcap_bucket'], d['market_cap'], d['latest_close'], d['low_52w'], d['high_52w'])
    ds.stats([(k, int(PRESETS[k][1](snap).fillna(False).sum()), 'companies') for k in PRESETS if k != 'All companies'])
    kit.table(d, companies_list.COLS, limit=200, height=4000, key='sc_t', keep_empty=True, empty_text='No company matches.')


# ---- Red flags and lenders (on the Risks page) ---------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False, max_entries=2)
def red_flags(_ctx, ref_key: str) -> pd.DataFrame:
    """One row per company with two or more flags: surveillance today, pledge over the high mark, promoters selling in
    90 days, shares to promoters below market in 12 months, late insider filings in 12 months."""
    ctx, ref = _ctx, _ctx.ref
    snap = store.snapshot()
    if snap.empty:
        return pd.DataFrame()
    d = snap[['isin', 'symbol', 'company', 'market_cap', 'mcap_bucket', 'pledge', 'promoter_sell_90d']].copy()
    fl = with_flags(d[['isin']])
    d['_flags'] = fl['trade_flags'].to_numpy() if 'trade_flags' in fl else None
    ev = moves.events(ctx, ref_key, 365)
    cheap = set(ev.loc[ev['kind'] == 'Cheap shares to promoters', 'isin']) if not ev.empty else set()
    t = ctx.trades
    late = pd.Series(dtype=int)
    if not t.empty:
        seen = pd.to_datetime(t['broadcast_date'], errors='coerce')
        lt = t[t['is_primary'].astype('boolean').fillna(False) & (seen > ref - pd.Timedelta(days=365))
               & ((t['insider_filed_late'] == True) | (t['company_filed_late'] == True))]  # noqa: E712
        late = lt.groupby('isin').size()
    rows = []
    for r in d.to_dict('records'):
        f = []
        if isinstance(r['_flags'], list) and r['_flags']:
            f.append(', '.join(r['_flags']))
        if pd.notna(r['pledge']) and r['pledge'] > signals.HIGH_PLEDGE_PCT:
            f.append(f'{r["pledge"]:.0f}% of promoter shares pledged')
        if pd.notna(r['promoter_sell_90d']) and r['promoter_sell_90d'] > 0:
            f.append(f'promoters sold {kit.rupees(r["promoter_sell_90d"])} in 90 days')
        if r['isin'] in cheap:
            f.append('shares to promoters below market')
        n = int(late.get(r['isin'], 0))
        if n >= LATE_FLAG:
            f.append(f'{n} late insider filings')
        if len(f) >= 2:
            rows.append({**r, 'flags': f, 'n': len(f)})
    out = pd.DataFrame(rows)
    return out.sort_values(['n', 'market_cap'], ascending=[False, False]) if not out.empty else out


def lenders(ctx, days: int) -> pd.DataFrame:
    """Who lends against promoter shares: SAST Reg 31 events by lender in the period (collected from 22 Oct 2026)."""
    enc = ctx.encumbrances
    if enc is None or enc.empty or 'lender' not in enc:
        return pd.DataFrame()
    when = pd.to_datetime(enc['broadcast_date'], errors='coerce')
    e = enc[(when <= ctx.ref + pd.Timedelta(days=1)) & (when > ctx.ref - pd.Timedelta(days=days))].copy()
    if e.empty:
        return e
    e['lender'] = e['lender'].fillna('not named').astype(str).str.strip().replace('', 'not named')
    e['_t'] = (e['event_type'] if 'event_type' in e else pd.Series('', index=e.index)).astype(str).str.lower()
    # The company key: the real table may carry the symbol only (site preview 12 Nov: no `isin` column).
    e['_co'] = e['isin'] if 'isin' in e else e['symbol'] if 'symbol' in e else e.index.astype(str)
    if 'symbol' not in e:
        e['symbol'] = e['_co']
    g = e.groupby('lender').agg(events=('lender', 'size'), companies=('_co', 'nunique'),
                                created=('_t', lambda s: int(s.str.startswith('creat').sum())),
                                released=('_t', lambda s: int(s.str.startswith('releas').sum())),
                                invoked=('_t', lambda s: int(s.str.startswith('invo').sum())),
                                names=('symbol', lambda s: ', '.join(list(dict.fromkeys(s.dropna().astype(str)))[:4])))
    return g.reset_index().sort_values(['events', 'companies'], ascending=False)


def red_flags_section(ctx, days: int) -> None:
    flags = red_flags(ctx, str(ctx.ref))
    ds.section('Red flags', f'Companies with two or more: NSE surveillance today, pledge over {signals.HIGH_PLEDGE_PCT:.0f}%, promoter sales in 90 days, '
               f'shares to promoters below market in 12 months, {LATE_FLAG}+ late insider filings in 12 months')
    if flags.empty:
        ds.empty('No company has two or more flags.')
    else:
        rows = [{'c': _co(r['company'], r['symbol']) + f'<span class="s">{esc(str(r["symbol"]))} · {esc(str(r["mcap_bucket"] or ""))} · {kit.rupees(r["market_cap"]) if kit._finite(r["market_cap"]) else ""}</span>',
                 'n': str(r['n']), 'f': esc(' · '.join(r['flags']))} for r in flags.head(150).to_dict('records')]
        ds.html(ds.list_html(rows, [ds.Col('c', 'Company'), ds.Col('n', 'Flags', True), ds.Col('f', 'What')]))
        if len(flags) > 150:
            ds.club('Not listed', [f'<b>{len(flags) - 150:,}</b> more companies with two or more flags, smaller first'])
    lend = lenders(ctx, max(days, 30))
    ds.section('Who lends against promoter shares?', 'Pledge and other encumbrance filings (SAST Reg 31) by lender, the last '
               f'{max(days, 30)} days; collected from 22 Oct 2026')
    if lend.empty:
        ds.empty('No encumbrance filing in this period.')
    else:
        rows = [{'l': esc(r['lender']), 'e': f'{r["events"]:,}', 'c': f'{r["companies"]:,}', 'cr': f'{r["created"]:,}', 'rl': f'{r["released"]:,}',
                 'iv': f'<b class="down">{r["invoked"]:,}</b>' if r['invoked'] else '0', 'n': esc(r['names'])} for r in lend.head(40).to_dict('records')]
        ds.html(ds.list_html(rows, [ds.Col('l', 'Lender'), ds.Col('e', 'Filings', True), ds.Col('c', 'Companies', True),
                                    ds.Col('cr', 'Created', True, phone=False), ds.Col('rl', 'Released', True, phone=False),
                                    ds.Col('iv', 'Invoked', True), ds.Col('n', 'For example', phone=False)]))


# ---- Sectors -------------------------------------------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False, max_entries=8)
def by_sector(_ctx, ref_key: str, days: int) -> pd.DataFrame:
    ctx, ref = _ctx, _ctx.ref
    sec = ctx.securities
    if sec is None or sec.empty or 'sector' not in sec:
        return pd.DataFrame()
    smap = dict(zip(sec['isin'], sec['sector']))
    parts = []
    for side, col in (('BUY', 'bought'), ('SELL', 'sold')):
        d = ideas.decisions(ctx.eligible, ref, side, ctx.shareholding, days)
        if not d.empty:
            pg = d['promoter_group'].astype(bool)
            d = d[ideas._qualifies(d)] if side == 'BUY' else d[(pg & ideas._qualifies(d)) | (~pg & (d['value'] >= ideas.BIG_VALUE))]
            parts.append(d.assign(sector=d['isin'].map(smap), side=col)[['sector', 'isin', 'company', 'side', 'value']])
    ins = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=['sector', 'isin', 'company', 'side', 'value'])
    dl = ctx.deals
    fund = pd.Series(dtype=float)
    if dl is not None and not dl.empty:
        when = pd.to_datetime(dl['date'], errors='coerce')
        x = dl[dl['is_primary'].astype('boolean').fillna(False) & ~dl['client_is_market_maker'].astype('boolean').fillna(False)
               & ~dl['client_is_promoter'].astype('boolean').fillna(False) & (when <= ref) & (when > ref - pd.Timedelta(days=days))]
        fund = pd.to_numeric(x['signed_value'], errors='coerce').groupby(x['isin'].map(smap)).sum()
    if ins.empty and fund.empty:
        return pd.DataFrame()
    g = ins.pivot_table(index='sector', columns='side', values='value', aggfunc='sum', fill_value=0.0) if not ins.empty else pd.DataFrame()
    for c in ('bought', 'sold'):
        if c not in g:
            g[c] = 0.0
    cos = ins.groupby('sector')['isin'].nunique() if not ins.empty else pd.Series(dtype=int)
    top = (ins[ins['side'] == 'bought'].sort_values('value', ascending=False).drop_duplicates('sector').set_index('sector')['company']
           if not ins.empty else pd.Series(dtype=object))
    out = g.join(cos.rename('companies'), how='outer').join(fund.rename('funds'), how='outer').join(top.rename('top'), how='left').fillna(
        {'bought': 0.0, 'sold': 0.0, 'companies': 0, 'funds': 0.0})
    out['net'] = out['bought'] - out['sold']
    out.index.name = 'sector'   # the joins can drop the name (an empty insider side, the deals' own key)
    out = out.reset_index()
    return out[out['sector'].notna() & out['sector'].astype(str).str.strip().ne('')].sort_values('net', ascending=False)


def sectors():
    ctx = _ctx()
    if ctx is None:
        return
    top, ctl = st.columns([4, 1.4], vertical_alignment='bottom')
    with ctl:
        p, days = pages._period('pg_sec')
    d = by_sector(ctx, str(ctx.ref), days)
    with top:
        if d.empty:
            ds.head(f'Sectors · {esc(pages._span(p, ctx.ref))}', 'No sector money past the bar', [])
        else:
            best, worst = d.iloc[0], d.iloc[-1]
            ds.head(f'Sectors · {esc(pages._span(p, ctx.ref))}',
                    f'Insiders put most into <b class="up">{esc(str(best["sector"]))}</b>, took most out of <b class="down">{esc(str(worst["sector"]))}</b>',
                    ['Open-market decisions by promoters, directors and KMP past the bar, and funds\' net bulk and block deals '
                     '(market makers and promoters left out), added up by sector.'])
    if d.empty:
        return
    scale = max(d['net'].abs().max(), 1.0)
    rows = []
    for r in d.to_dict('records'):
        w = abs(r['net']) / scale * 100
        bar = f'<span class="sec-bar"><i class="{"pos" if r["net"] >= 0 else "neg"}" style="width:{w:.0f}%"></i></span>'
        rows.append({'s': esc(str(r['sector'])) + (f'<span class="s">largest buy: {esc(str(r["top"]))}</span>' if isinstance(r.get('top'), str) else ''),
                     'b': kit.rupees(r['bought']) if r['bought'] else '—', 'so': kit.rupees(r['sold']) if r['sold'] else '—',
                     'n': f'<b class="{"up" if r["net"] > 0 else "down" if r["net"] < 0 else ""}">{kit.rupees(r["net"], signed=True)}</b>{bar}',
                     'c': f'{int(r["companies"]):,}', 'f': kit.rupees(r['funds'], signed=True) if r['funds'] else '—'})
    ds.section('Where are insiders putting money?', 'Net = bought minus sold on the market; funds = net in bulk and block deals')
    ds.html(ds.list_html(rows, [ds.Col('s', 'Sector'), ds.Col('n', 'Insiders net', True), ds.Col('b', 'Bought', True, phone=False),
                                ds.Col('so', 'Sold', True, phone=False), ds.Col('c', 'Companies', True, phone=False),
                                ds.Col('f', 'Funds net, deals', True)]))


# ---- Results -------------------------------------------------------------------------------------------------------

def _latest_results(ctx, days: int) -> pd.DataFrame:
    res = ctx.results
    if res is None or res.empty:
        return pd.DataFrame()
    r = res.copy()
    if 'superseded' in r:
        r = r[~r['superseded'].astype('boolean').fillna(False)]
    if 'xbrl_status' in r:
        r = r[r['xbrl_status'].fillna('ok') == 'ok']
    r['_at'] = pd.to_datetime(r['broadcast_at'], errors='coerce', utc=True).dt.tz_convert('Asia/Kolkata').dt.tz_localize(None)
    r['_end'] = pd.to_datetime(r['period_end'], errors='coerce')
    r['_cons'] = r['consolidated'].astype(str).str.strip().str.lower().str.startswith('consolidated')
    # one basis per company: consolidated where it files both
    r = r.sort_values(['_cons', '_at']).drop_duplicates(['isin', '_end'], keep='last')
    for c in ('quarter_revenue', 'quarter_profit'):
        r[c] = pd.to_numeric(r[c], errors='coerce')
    r = r.sort_values(['isin', '_end'])
    prev = r.groupby('isin')[['_end', 'quarter_revenue', 'quarter_profit']].shift(1)
    gap = (r['_end'] - prev['_end']).dt.days
    near = gap.between(80, 100)    # the quarter before, not an older one
    r['rev_qoq'] = ((r['quarter_revenue'] / prev['quarter_revenue'] - 1) * 100).where(near & prev['quarter_revenue'].gt(0))
    r['profit_prev'] = prev['quarter_profit'].where(near)
    win = (r['_at'] <= ctx.ref + pd.Timedelta(days=1)) & (r['_at'] > ctx.ref - pd.Timedelta(days=days))
    return r[win].sort_values('_at', ascending=False)


def results():
    ctx = _ctx()
    if ctx is None:
        return
    top, ctl = st.columns([4, 1.4], vertical_alignment='bottom')
    with ctl:
        p, days = pages._period('pg_res')
    r = _latest_results(ctx, days)
    names = _names(ctx)
    e = ctx.eligible
    dec = e[e['person_role'].isin(signals.DECISION_ROLES)] if not e.empty else e
    rows, after = [], []
    for x in r.head(300).to_dict('records'):
        isin = x.get('isin')
        rev, pr = x.get('quarter_revenue'), x.get('quarter_profit')
        margin = pr / rev * 100 if kit._finite(rev) and rev and kit._finite(pr) is not None else None
        w = dec[(dec['isin'] == isin) & (dec['seen'] >= x['_at'].normalize()) & (dec['seen'] <= x['_at'] + pd.Timedelta(days=30))] if isin else dec.iloc[0:0]
        net = (pd.to_numeric(w['signed_value'], errors='coerce').sum() if len(w) else 0.0)
        sym = x.get('symbol')
        rows.append({'c': _co(names.get(isin) or x.get('company') or sym, sym) + f'<span class="s">{esc(str(sym or ""))} · quarter to {kit.day(x["_end"])}'
                          + (' · consolidated' if x['_cons'] else ' · standalone') + '</span>',
                     'd': kit.day(x['_at'], with_year=False),
                     'r': kit.rupees(rev) if kit._finite(rev) else '—',
                     'q': (f'<b class="{"up" if x["rev_qoq"] > 0 else "down"}">{x["rev_qoq"]:+.1f}%</b>' if pd.notna(x.get('rev_qoq')) else '<span class="muted">—</span>'),
                     'p': (f'<b class="{"down" if pr < 0 else ""}">{kit.rupees(pr, signed=pr < 0)}</b>' if kit._finite(pr) is not None else '—')
                          + (f'<span class="s">was {kit.rupees(x["profit_prev"], signed=x["profit_prev"] < 0)}</span>' if kit._finite(x.get('profit_prev')) is not None else ''),
                     'm': f'{margin:.1f}%' if margin is not None else '—',
                     'i': (f'<b class="{"up" if net > 0 else "down"}">{kit.rupees(net, signed=True)}</b><span class="s">{kit.plural(len(w), "trade")}</span>' if len(w) else '—')})
    if not e.empty and 'window_open_buy' in e:
        wb = e[e['window_open_buy'].astype('boolean').fillna(False) & e['person_role'].isin(signals.DECISION_ROLES)
               & (e['seen'] <= ctx.ref) & (e['seen'] > ctx.ref - pd.Timedelta(days=max(days, 30)))]
        for x in wb.sort_values('value', ascending=False).head(60).to_dict('records'):
            after.append({'c': _co(names.get(x['isin']) or x['company'], x['nse_symbol']),
                          'w': esc(str(x.get('person_name') or '')) + f'<span class="s">{esc(kit.role(x.get("person_role")))}</span>',
                          'v': kit.rupees(x['value']), 's': esc(kit.sessions_text(x.get('sessions_since_window_open')).replace('same day', 'first session')),
                          'd': kit.day(x.get('results_date'), with_year=False) if pd.notna(x.get('results_date')) else '—'})
    with top:
        ds.head(f'Results · {esc(pages._span(p, ctx.ref))}', f'{kit.plural(len(r), "quarterly result")} filed',
                ['From NSE\'s results XBRL (collected from 15 Oct 2026; banks, NBFCs and insurers partly). Revenue against the '
                 'quarter before only where we hold it; the filing has no year-ago quarter, so no year-on-year growth yet.'])
    up = int((r['rev_qoq'] > 0).sum()) if not r.empty else 0
    dn = int((r['rev_qoq'] < 0).sum()) if not r.empty else 0
    ds.stats([('Results filed', len(r), 'in the period'), ('Revenue up', up, 'on the quarter before', 'up'), ('Revenue down', dn, 'on the quarter before', 'down'),
              ('Losses', int((r['quarter_profit'] < 0).sum()) if not r.empty else 0, 'quarterly loss', 'down'),
              ('Bought after results', len(after), 'insider buys, window just reopened', 'up')])
    ds.section('Who reported, and what did insiders do next?', 'Newest first; insiders = open-market net by promoters, directors and KMP '
               'in the 30 days after the filing')
    if rows:
        ds.html(ds.list_html(rows, [ds.Col('c', 'Company'), ds.Col('d', 'Filed', phone=False), ds.Col('r', 'Revenue', True),
                                    ds.Col('q', 'vs quarter before', True), ds.Col('p', 'Profit', True), ds.Col('m', 'Margin', True, phone=False),
                                    ds.Col('i', 'Insiders next 30 days', True)]))
        if len(r) > 300:
            ds.club('Not listed', [f'<b>{len(r) - 300:,}</b> older results in the period'])
    else:
        ds.empty('No results filed in this period.')
    ds.section('Who bought right after their own results?', 'Promoters, directors and KMP buying in the first sessions after the trading '
               'window reopened. Exploratory: not yet measured on our data')
    if after:
        ds.html(ds.list_html(after, [ds.Col('c', 'Company'), ds.Col('w', 'Who'), ds.Col('v', 'Value', True),
                                     ds.Col('s', 'After the window opened', phone=False), ds.Col('d', 'Results', phone=False)]))
    else:
        ds.empty('No insider bought in the first sessions after results in this period.')

