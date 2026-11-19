"""Funds: what mutual fund managers bought and sold, from the fund houses' own month-end portfolios, as an explorer.

Owner, 19 Nov 2026: "I can't say anything what mutual funds or PMS etc buying this month or selling this month", then
"a page to show what mutual funds are buying by date, market cap, industries and so on", "no small or mid cap stocks
in what mutual funds bought or sold", "don't we have current month's deals for MF etc?" and "a fund house sometimes
trims or buys lots of positions on its view of the market or earnings; we don't have that".

Every fund house files its schemes' holdings as on the last day of each month by the 10th of the next
(scripts/mf_portfolios.py collects them; insiders_clean/mf_holdings.py reads them). A month's change per stock is what
active schemes held at this month-end less what they held at the last (index funds and ETFs, which buy by rule, kept
apart unless the reader asks for every scheme; a bonus or split between the two dates applied first). The arithmetic is
screens/funds_logic.py; this file only draws it.

The page: a month-end (the newest complete one by default) or the last 3, 6 or 12 added together; filters by company
size (the slim prices' bucket), industry (four levels from the `industry` table where it has rows, else the security
master's sector and industry; a level with no data is not offered) and fund house; the month so far from bulk and block
deals (portfolios arrive ten days after the month); lists by rupees, by share of the company and by size; new entries
and exits; sectors; how each house is positioning; one house; NPS pension funds apart; and whether it is complete.

PMS and AIFs file no holdings stock by stock; they appear only where they file a bulk or block deal or cross 5%.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st
from data import store

from insiders_clean import participants
from screens import funds_logic as fl
from screens import moves
from screens.ctx import load, need_data
from screens.proto import _company, _more, _names_list, _num, _qa, _strip, _table
from ui import charts, kit
from ui import ds
from ui.kit import esc

TOP = 15
SIZES = ['Large', 'Mid', 'Small', 'Micro']
MIN_NET_CR = fl.MIN_NET_CR
by_kind, months = fl.by_kind, fl.months   # kept for other pages and tests that import them from here
DEAL_COLS = [('co', 'Company', 'l'), ('net', 'Net, funds', 'r'), ('mutual_fund', 'Mutual funds', 'r'), ('insurer', 'Insurers', 'r'),
             ('fpi', 'Foreign', 'r'), ('other', 'Pension, AIF, other', 'r'), ('who', 'Largest buyers', 'l')]
FUND_COLS = [('fund', 'Fund', 'l'), ('type', 'Type', 'l'), ('bought', 'Bought', 'r'), ('sold', 'Sold', 'r'), ('net', 'Net', 'r'),
             ('co', 'Largest position', 'l')]
COLS = [('co', 'Company', 'l'), ('val', 'Net, ₹', 'r'), ('pct', '% of company', 'r'), ('houses', 'Fund houses', 'l'),
        ('held', 'Houses holding', 'r'), ('size', 'Size', 'l')]
PCT_COLS = [('co', 'Company', 'l'), ('pct', '% of company', 'r'), ('houses', 'Fund houses', 'l'), ('val', 'Net, ₹', 'r'),
            ('held', 'Houses holding', 'r'), ('size', 'Size', 'l')]
NEW_COLS = [('co', 'Company', 'l'), ('new', 'Houses', 'l'), ('val', 'Bought by new holders', 'r'), ('net', 'Net, all houses', 'r'),
            ('held', 'Houses holding', 'r'), ('size', 'Size', 'l')]
EXIT_COLS = [('co', 'Company', 'l'), ('exit', 'Houses', 'l'), ('val', 'Sold by leavers', 'r'), ('net', 'Net, all houses', 'r'),
             ('held', 'Houses still holding', 'r'), ('size', 'Size', 'l')]
HOUSE_COLS = [('co', 'Company', 'l'), ('val', 'Net, ₹', 'r'), ('st', 'Position', 'l'), ('pct', '% of company', 'r'),
              ('sh', 'Shares held at the end', 'r'), ('size', 'Size', 'l')]
POS_COLS = [('house', 'Fund house', 'l'), ('net', 'Net bought', 'r'), ('flow', '% of its equity', 'r'), ('moves', 'Positions', 'l'),
            ('trim', 'Trimmed', 'r'), ('flag', '', 'l'), ('mix', 'Size mix', 'l'), ('sec', 'Largest sector shifts', 'l'),
            ('top', 'Top 10 weight', 'r')]
BUCKET_COLS = [('b', 'Size', 'l'), ('net', 'Net, ₹', 'r'), ('n', 'Stocks bought · sold', 'r')]


def _house_names() -> tuple[dict, list]:
    """({house key: name} for every house the collector reads, [(name, why)] for the mutual fund houses it does not)."""
    try:
        from collectors.mf_portfolios.houses import HOUSES, NOT_COLLECTED
    except Exception:  # noqa: BLE001 -- the page still draws with keys for names
        return {}, []
    return {h.key: h.name for h in HOUSES}, list(NOT_COLLECTED)


def _label(month: str) -> str:
    return pd.Period(month, 'M').strftime('%B %Y')


def _short(month: str) -> str:
    return pd.Period(month, 'M').strftime('%b %Y')


def _period_label(ms: list[str]) -> str:
    return _label(ms[-1]) if len(ms) == 1 else f'{_short(ms[0])} to {_short(ms[-1])} ({len(ms)} month-ends)'


def _cr(v, signed=True) -> str:
    f = kit._finite(v)
    return kit.rupees(f * 1e7, signed=signed) if f is not None else '—'


def _rs(v, signed=True) -> str:
    f = kit._finite(v)
    return kit.rupees(f, signed=signed) if f is not None and f != 0 else '<span class="mute">–</span>'


def _nm(r: dict, names: dict) -> str:
    return str(names.get(r.get('isin')) or r.get('name') or r.get('isin') or '')


def _names(df: pd.DataFrame, names: dict, n: int) -> str:
    """The first `n` companies of a list, 'A, B and C', escaped."""
    return _names_list([_nm(r, names) for r in df.head(n).to_dict('records')], n)


def _empty(text: str) -> str:
    return f'<p class="dt-empty">{esc(text)}</p>'


def _rows(df: pd.DataFrame, syms: dict, names: dict, size: dict, kind: str = 'net', first: set | None = None) -> list[dict]:
    out = []
    for r in df.head(TOP).to_dict('records'):
        isin = r['isin']
        val = r['net_cr'] if kind == 'net' else r['new_cr'] if kind == 'new' else r['exit_cr']
        co = _company(_nm(r, names), syms.get(isin))
        if first and isin in first:
            co += ' <span class="dt-chip">first held</span>'
        out.append({
            'co': co,
            'val': f'<b>{esc(_cr(val))}</b>' if kit._finite(val) is not None else _num(None),
            'net': esc(_cr(r['net_cr'])) if kit._finite(r.get('net_cr')) is not None else _num(None),
            'pct': _num(r.get('pct_of_company'), '{:+.2f}%'),
            'houses': f'{int(r["houses_adding"])} adding · {int(r["houses_cutting"])} cutting',
            'new': f'{int(r["houses_new"])} new',
            'exit': f'{int(r["houses_exit"])} sold out',
            'held': f'{int(r["houses_holding"])}',
            'size': esc(size.get(isin) or '') or _num(None),
        })
    return out


def _house_table(hr: pd.DataFrame, syms, names, size, tot) -> str:
    rows = []
    for r in hr.head(TOP).to_dict('records'):
        t = pd.to_numeric(tot.get(r['isin']), errors='coerce')
        rows.append({'co': _company(_nm(r, names), syms.get(r['isin'])),
                     'val': f'<b>{esc(_cr(r["net_cr"]))}</b>' if kit._finite(r.get('net_cr')) is not None else _num(None),
                     'st': esc(fl.STATUS_WORD.get(r['status'], r['status'])),
                     'pct': _num(r['net'] / t * 100 if t and t > 0 else None, '{:+.2f}%'),
                     'sh': esc(kit.shares(r['end'])) if r['end'] > 0 else _num(None),
                     'size': esc(size.get(r['isin']) or '') or _num(None)})
    return _table(HOUSE_COLS, rows)


def _coverage_text(c: dict | None) -> tuple[str, str]:
    """(KPI value, the sentence): the share is stated only over MIN_COVERAGE_COMPANIES companies or more."""
    if not c:
        return '—', 'How much of the industry these houses are is measured at each quarter end against the companies\' own ' \
                    'shareholding filings; no quarter end with both is in the data yet.'
    q = _label(c['month'])
    if not c.get('companies'):
        return '—', (f'Not measured yet: none of the {c["held_companies"]:,} companies the houses held at the {q} quarter end '
                     'has its mutual-fund holding read from its shareholding filing so far.')
    pct = c['ratio'] * 100
    if c['companies'] < fl.MIN_COVERAGE_COMPANIES:
        return 'too early', (f'Too early to say what share of the industry this is. The {c["houses"]} houses compared at the {q} '
                             f'quarter end hold {c["held_companies"]:,} companies; the mutual-fund holding is read from the '
                             f'shareholding filing of only {c["companies"]:,} of them so far, where the houses held {pct:.0f}% of '
                             f'it by value. A share is stated once {fl.MIN_COVERAGE_COMPANIES} companies are read.')
    return f'{pct:.0f}%', (f'At the {q} quarter end the {c["houses"]} houses compared held {pct:.0f}% by value of what mutual '
                           f'funds held in the {c["companies"]:,} companies (of {c["held_companies"]:,} they hold) whose '
                           'shareholding filing has the mutual-fund line read; the median company '
                           f'{c["median_ratio"] * 100:.0f}%.')


def _pick_cascade(ind: pd.DataFrame) -> dict:
    """The industry selectboxes, each narrowed by the ones before it; a level with no data is not drawn."""
    picks: dict = {}
    for lv in fl.levels_with_data(ind):
        opts = fl.cascade_options(ind, picks).get(lv, [])
        key = f'fd_lv_{lv}'
        if st.session_state.get(key) not in (None, 'All', *opts):
            del st.session_state[key]          # a value from another branch of the cascade
        if not opts:
            continue
        v = st.selectbox(fl.LEVEL_LABEL[lv], ['All'] + opts, key=key, width=200,
                         format_func=lambda x, lv=lv: f'Every {fl.LEVEL_LABEL[lv].lower()}' if x == 'All' else x)
        picks[lv] = None if v == 'All' else v
    return picks


def _deals_section(ctx, win, keep, syms, names) -> None:
    """The month so far from bulk and block deals: portfolios arrive about ten days after the month ends."""
    ref = pd.Timestamp(ctx.ref) if ctx.ref is not None else pd.Timestamp.today().normalize()
    mtd = f'{ref:%B} so far (1 to {ref:%d %b})'
    picked = f'The period above ({_period_label(win)})'
    with st.container(key='fd_deal_bar'):
        span = st.segmented_control('Deals period', [mtd, picked], default=mtd, required=True, key='fd_deal_span',
                                    label_visibility='collapsed') or mtd
    if span == mtd:
        start, end = ref.replace(day=1), ref
    else:
        start, end = pd.Period(win[0], 'M').start_time, pd.Period(win[-1], 'M').end_time.normalize()
    d = fl.apply_isins(fl.deal_rows(ctx.deals, start, end), *keep)
    bs, bf = fl.deals_by_stock(d), fl.deals_by_fund(d)
    why = ('Bulk and block deals by mutual funds, insurers, pension funds, foreign investors, AIFs and other funds (the type read '
           'from the client\'s name), promoters and market makers out, '
           f'{start:%d %b} to {end:%d %b %Y}. Deals show only trades large enough to be disclosed: a bulk deal is one client '
           'trading 0.5% or more of a company\'s shares in a day, a block deal a single trade in the block window, each named. '
           'Most fund trading is neither, so this is not all fund buying; the month-end portfolios below are.')
    if bs.empty:
        _qa('This month so far: what did funds buy and sell in bulk and block deals?', 'No fund deal in this period', why, 'deals')
        return
    b = bs[bs['net'] > 0]
    s = bs[bs['net'] < 0]
    ans = (f'Bought most: {esc(str(b.iloc[0]["company"]))} ({esc(_rs(b.iloc[0]["net"]))}, {kit.plural(int(b.iloc[0]["buyers"]), "fund")})'
           if len(b) else 'No net buying')
    if len(s):
        ans += f'; sold most: {esc(str(s.sort_values("net").iloc[0]["company"]))}'
    _qa('This month so far: what did funds buy and sell in bulk and block deals?', ans, why, 'deals')
    rows = []
    for r in bs.head(TOP).to_dict('records'):
        rows.append({'co': _company(names.get(r['isin']) or r['company'], syms.get(r['isin'])),
                     'net': f'<b>{_rs(r["net"])}</b>', 'mutual_fund': _rs(r['mutual_fund']), 'insurer': _rs(r['insurer']),
                     'fpi': _rs(r['fpi']), 'other': _rs(r['pension'] + r['pms_aif'] + r['fund_other']),
                     'who': esc(', '.join(map(str, r['top_buyers'][:3]))) + (f' +{r["buyers"] - 3} more' if r['buyers'] > 3 else '')})
    st.html(_table(DEAL_COLS, rows))
    st.html('<p><b>The funds, by name</b></p>' + _table(FUND_COLS, [
        {'fund': esc(str(r['fund'])), 'type': esc(participants.TYPES.get(r['type'], r['type'])), 'bought': _rs(r['bought'], False),
         'sold': _rs(r['sold'], False), 'net': f'<b>{_rs(r["net"])}</b>',
         'co': _company(names.get(r['largest_isin']) or r['largest'], syms.get(r['largest_isin']))}
        for r in bf.head(TOP).to_dict('records')]))


def _positioning_section(ch, stock, win, month, hname, size, sector, mf_ms) -> None:
    pos = fl.house_positioning(ch, stock, size, sector, ms=[month])
    why = (f'One row per house, active schemes, {_label(month)} against the month-end before. Before and after are valued at '
           'the same month-end prices, so only share counts move them: a market fall does not read as selling. "% of its '
           'equity" is shares bought over shares held before, at those prices, so a large house is not ranked by size; SIP '
           'money put to work shows as a flow too, and is not told apart. "Broad trim" or "broad add": '
           f'{fl.BROAD_SHARE:.0%} or more of the positions it held moved the same way. The filings say what each house did, '
           'not why: earnings, a market view and redemptions all look the same here. Cash, TREPS and receivables are not read '
           '(the collector keeps equity lines only), so the change in a house\'s cash is not shown.')
    if pos.empty:
        _qa('How is each house positioning?', 'Not enough months to compare', why, 'positioning')
        return
    pos = pos.sort_values('flow_pct', ascending=False, na_position='last')
    up, dn = pos[pos['broad'].eq('broad add')], pos[pos['broad'].eq('broad trim')]
    ans = []
    if len(dn):
        ans.append(f'Broad trims: {esc(_names_list([hname(k) for k in dn["amc"]], 3))}')
    if len(up):
        ans.append(f'broad adds: {esc(_names_list([hname(k) for k in up["amc"]], 3))}')
    _qa('How is each house positioning?', '; '.join(ans) or f'No house moved {fl.BROAD_SHARE:.0%} of its positions the same way', why,
        'positioning')
    rows = []
    for r in pos.to_dict('records'):
        mix = sorted(((k, v) for k, v in r['mix_shift'].items() if abs(v) >= 0.05), key=lambda kv: -abs(kv[1]))[:2]
        rows.append({
            'house': esc(hname(r['amc'])), 'net': f'<b>{esc(_cr(r["net_cr"]))}</b>',
            'flow': _num(r['flow_pct'], '{:+.2f}%'),
            'moves': f'+{r["added"]} · −{r["cut"]} · {r["new"]} new · {r["exit"]} out',
            'trim': _num(r['trimmed_pct'], '{:.0f}%'),
            'flag': f'<span class="dt-chip {"dn" if r["broad"] == "broad trim" else "up"}">{esc(r["broad"])}</span>' if r['broad'] else '',
            'mix': esc(', '.join(f'{k} {v:+.1f} pts' for k, v in mix)) or _num(None),
            'sec': esc(', '.join(f'{k} {v:+.1f}' for k, v in r['sector_shift'] if abs(v) >= 0.05)) or _num(None),
            'top': (f'{r["top10_before"]:.0f} → {r["top10_after"]:.0f}%' if kit._finite(r['top10_before']) is not None
                    and kit._finite(r['top10_after']) is not None else _num(None))})
    st.html(_table(POS_COLS, rows))
    last12 = fl.window(mf_ms, month, 12)
    hm = fl.house_positioning(ch, stock, None, None, ms=last12)
    if len(last12) > 1 and not hm.empty:
        hm = hm.assign(house=hm['amc'].map(hname), month_label=hm['month'].map(_short))
        chart = charts.heatmap(hm, x_order=[_short(m) for m in last12])
        if chart is not None:
            st.html(f'<p><b>Net active buying as a % of each house\'s equity, {_short(last12[0])} to {_short(last12[-1])}</b></p>')
            st.altair_chart(chart, width='stretch')


def render():
    ctx = load()
    if not need_data(ctx):
        return
    stock_all, ch_all = store.table('mf_stock_month'), store.table('mf_changes')
    stock, ch = fl.by_kind(stock_all, 'mf'), fl.by_kind(ch_all, 'mf')        # the page's lists: mutual funds
    nps_stock, nps_ch = fl.by_kind(stock_all, 'pension'), fl.by_kind(ch_all, 'pension')
    ms = fl.months(stock_all)
    _strip(ctx, ['fund houses\' month-end portfolios', 'bulk and block deals for the month so far', 'PMS and AIFs file no holdings'])
    if not ms or ch_all is None or ch_all.empty:
        ds.head('Funds', 'What did fund managers buy and sell this month?',
                ['The fund houses\' month-end portfolios are not collected yet. Until they are, fund buying shows only in '
                 'bulk and block deals (Investor flows) and 5% crossings (Stakes).'])
        st.html(_more('investor-flows', 'Fund trades in bulk and block deals'))
        return
    mf_ms = fl.months(ch) or ms
    n_by = fl.houses_by_month(ch)
    dflt = fl.default_month(ch, mf_ms)
    top_n = max(n_by.values()) if n_by else 0

    def month_text(m):
        n = n_by.get(m, 0)
        return f'{_label(m)} · {n} houses' + (' · still coming in' if n < fl.COMPLETE_SHARE * top_n else '')

    with st.container(key='fd_bar', horizontal=True, vertical_alignment='bottom', gap='small'):
        month = st.selectbox('Month-end', mf_ms, index=mf_ms.index(dflt) if dflt in mf_ms else 0, format_func=month_text,
                             key='fd_month', width=280)
        span = st.segmented_control('Period', list(fl.RANGES), default='Month', required=True, key='fd_range') or 'Month'
        scope = st.segmented_control('Schemes', ['Active', 'Every scheme'], default='Active', required=True, key='fd_scope',
                                     help='Active leaves out index funds, ETFs and funds of funds, which buy what their index '
                                          'holds. Every scheme counts them too.') or 'Active'
    passive = scope == 'Every scheme'
    win = fl.window(mf_ms, month, fl.RANGES[span])

    names_by_key, not_collected = _house_names()
    house_keys = sorted(ch.loc[ch['month'].isin(win), 'amc'].unique()) if ch is not None and not ch.empty else []
    hname = lambda k: names_by_key.get(k, k)  # noqa: E731
    px, hold, names = moves.lookups(ctx)
    sec = ctx.securities
    syms = dict(zip(sec['isin'], sec['nse_symbol'])) if sec is not None and not sec.empty and 'nse_symbol' in sec else {}
    listed = set(sec['isin'].dropna()) if sec is not None and not sec.empty and 'isin' in sec else None
    tot = {i: r.get('total_shares') for i, r in hold.items()}
    size = {i: p.get('mcap_bucket') for i, p in px.items() if isinstance(p.get('mcap_bucket'), str)}
    ind = fl.industry_frame(store.table('industry'), sec)
    lv0 = 'sector' if 'sector' in fl.levels_with_data(ind) else (fl.levels_with_data(ind) or [None])[0]
    sector = dict(zip(ind['isin'], ind[lv0])) if lv0 else {}

    with st.container(key='fd_filters', horizontal=True, vertical_alignment='bottom', gap='small'):
        sizes = st.pills('Company size', SIZES, selection_mode='multi', key='fd_size',
                         help='By market cap rank on the latest day: top 100 Large, 101-250 Mid, 251-500 Small, the rest Micro')
        picks = _pick_cascade(ind)
        houses = st.multiselect('Fund houses', house_keys, format_func=hname, key='fd_houses', placeholder='Every house',
                                width=320)
    keep = (fl.mcap_isins(ctx.prices, sizes), fl.filter_isins(ind, picks))

    hr_all = fl.house_rows(ch, stock, win, houses or None, passive)
    hr = fl.apply_isins(hr_all, listed, *keep)            # listed equity in the security master only
    unlisted = int(hr_all.loc[~hr_all['isin'].isin(listed), 'isin'].nunique()) if listed is not None and not hr_all.empty else 0
    sw = fl.stock_window(hr, tot)
    first = fl.first_held(stock, win)
    v, k = fl.lists(sw), fl.kpis(sw[~sw['isin'].isin(first)], hr[~hr['isin'].isin(first)])
    new_listed = sw[sw['isin'].isin(first) & sw['net'].gt(0)].sort_values('net_cr', ascending=False, na_position='last')
    period = _period_label(win)
    n_houses = len(houses) if houses else n_by.get(month, 0)
    filt = [', '.join(sizes) + ' companies' if sizes else '', ' / '.join(x for x in picks.values() if x)]
    filt = [x for x in filt if x]
    tb, ts = k['top_bought'], k['top_sold']
    head = (f'Fund managers bought most of <b>{esc(_names(v["bought"][~v["bought"]["isin"].isin(first)], names, 3))}</b>'
            if tb else 'No net buying')
    head += f' and sold most of <b>{esc(_names(v["sold"], names, 2))}</b>' if ts else ''
    ds.head(f'Funds · {"month-end " if len(win) == 1 else ""}{period} · {n_houses} fund houses compared'
            + (f' · {"; ".join(filt)}' if filt else ''), head,
            ['A house is compared when it is collected at both month-ends; houses not in are named at the foot of the page.'])

    qm = fl.quarter_month(mf_ms, month)
    cov = fl.coverage_live(ch, stock, ctx.shareholding, qm)
    cov_v, cov_line = _coverage_text(cov)
    ds.stats([('Net buying' if k['net_cr'] >= 0 else 'Net selling', _cr(k['net_cr']),
               ('active schemes' if not passive else 'every scheme, index funds too') + ', listed before the period',
               'up' if k['net_cr'] >= 0 else 'down'),
              ('Stocks bought · sold', f'{k["bought"]:,} · {k["sold"]:,}', 'net, any amount'),
              ('New entries · exits', f'{k["new_positions"]:,} · {k["exit_positions"]:,}',
               f'positions, in {k["new_stocks"]:,} and {k["exit_stocks"]:,} stocks'),
              ('Coverage', cov_v, f'by value, {_short(cov["month"])} quarter end' if cov else 'measured at quarter ends')])
    ds.stats([('Most bought', _nm(tb, names) if tb else '—', _cr(tb['net_cr']) if tb else 'none', 'up' if tb else ''),
              ('Most sold', _nm(ts, names) if ts else '—', _cr(ts['net_cr']) if ts else 'none', 'down' if ts else ''),
              ('First held by any house', f'{len(new_listed):,}', _cr(new_listed['net_cr'].sum()) + ' (new listings and first buys)')])
    st.html('<div class="qa-toc"><a href="#deals">This month so far</a><a href="#bought">Bought most</a><a href="#sold">Sold most</a>'
            '<a href="#pct">By share of the company</a><a href="#size">By size</a><a href="#new">New entries</a>'
            '<a href="#exits">Complete exits</a><a href="#sectors">By sector</a><a href="#positioning">Each house</a>'
            '<a href="#house">One house</a>'
            + ('<a href="#nps">NPS pension funds</a>' if nps_ch is not None and not nps_ch.empty and nps_ch['month'].isin(win).any() else '')
            + '<a href="#complete">Is this complete?</a></div>')

    _deals_section(ctx, win, keep, syms, names)

    how = ('Shares active schemes held at the end less at the start, at each month-end\'s filed price'
           if not passive else 'Shares every scheme held, index funds and ETFs included, at each month-end\'s filed price')
    b = v['bought'][~v['bought']['isin'].isin(first)]
    s_ = v['sold']
    _qa(f'What did fund managers buy most in {period}?',
        _names(b, names, 3) if len(b) else f'No stock bought for ₹{MIN_NET_CR:.0f} Cr or more',
        f'{len(b):,} stocks bought for ₹{MIN_NET_CR:.0f} Cr or more, {_cr(b["net_cr"].sum())} in all. {how}. '
        'Stocks no house held before are apart, below.', 'bought')
    if len(b):
        st.html(_table(COLS, _rows(b, syms, names, size)))
    _qa('What did they sell most?', _names(s_, names, 3) if len(s_) else f'No stock sold for ₹{MIN_NET_CR:.0f} Cr or more',
        f'{len(s_):,} stocks sold for ₹{MIN_NET_CR:.0f} Cr or more, {_cr(s_["net_cr"].sum())} in all.', 'sold')
    if len(s_):
        st.html(_table(COLS, _rows(s_, syms, names, size)))
    if len(new_listed):
        _qa('What did houses take that no house held before?', _names(new_listed, names, 3),
            f'{len(new_listed):,} stocks no collected house held at any earlier month-end, {_cr(new_listed["net_cr"].sum())} '
            'in all: a new listing (shares allotted in its IPO, to anchor or other investors) or a first purchase of a stock '
            'listed earlier. Kept out of the lists and figures above, which are trading in listed stocks.', 'ipo')
        st.html(_table(COLS, _rows(new_listed, syms, names, size, first=first)))

    # By share of the company: where small and mid caps show
    pb, ps = fl.by_pct(sw, 'buy'), fl.by_pct(sw, 'sell')
    _qa('Where did funds buy the largest share of the company?', _names(pb, names, 3) if len(pb) else 'None',
        'Net shares bought as a % of the company\'s shares (its latest shareholding filing), then houses adding, then rupees. '
        'Rupees always put the largest companies first; this puts the bets that are large for the company first.', 'pct')
    if len(pb):
        st.html(_table(PCT_COLS, _rows(pb, syms, names, size, first=first)))
    if len(ps):
        st.html('<p><b>Sold the largest share of the company</b></p>' + _table(PCT_COLS, _rows(ps, syms, names, size, first=first)))

    # By size
    br = fl.bucket_rollup(sw, size)
    if not br.empty:
        bb = br[br['bucket'].isin(SIZES)]
        best = bb.sort_values('net_cr', ascending=False).iloc[0] if len(bb) else None
        _qa('Large, mid, small or micro: where did the money go?',
            f'Most into {esc(best["bucket"].lower())} caps ({esc(_cr(best["net_cr"]))})' if best is not None and best['net_cr'] > 0
            else 'Net selling in every size', 'Net rupees and stocks bought and sold per size (market cap rank on the latest '
            'day: top 100 Large, 101-250 Mid, 251-500 Small, the rest Micro). Each tab ranks by share of the company.', 'size')
        st.html(_table(BUCKET_COLS, [{'b': esc(r['bucket']), 'net': f'<b>{esc(_cr(r["net_cr"]))}</b>',
                                      'n': f'{r["bought"]:,} · {r["sold"]:,}'} for r in br.to_dict('records')]))
        tabs = st.tabs(SIZES)
        for t, bucket in zip(tabs, SIZES):
            with t:
                sub = sw[sw['isin'].map(size).eq(bucket)]
                tb_, ts_ = fl.by_pct(sub, 'buy'), fl.by_pct(sub, 'sell')
                st.html('<p><b>Bought</b></p>' + (_table(PCT_COLS, _rows(tb_, syms, names, size, first=first)) if len(tb_)
                        else _empty(f'No {bucket.lower()} cap bought.')))
                st.html('<p><b>Sold</b></p>' + (_table(PCT_COLS, _rows(ts_, syms, names, size, first=first)) if len(ts_)
                        else _empty(f'No {bucket.lower()} cap sold.')))

    nw, ex = v['new'], v['exits']
    _qa('Where did houses open a new position?', _names(nw, names, 3) if len(nw) else 'None in this period',
        f'{int(hr["status"].eq("new").sum()):,} new positions in {len(nw):,} stocks: a house that held none at the start'
        f'{" of the period" if len(win) > 1 else " (the month-end before)"} and holds some now. Most houses first.', 'new')
    if len(nw):
        st.html(_table(NEW_COLS, _rows(nw, syms, names, size, 'new', first=first)))
    _qa('Where did houses sell out completely?', _names(ex, names, 3) if len(ex) else 'None in this period',
        f'{k["exit_positions"]:,} positions closed in {len(ex):,} stocks: a house that held it at the start and holds none now. '
        'Most houses first.', 'exits')
    if len(ex):
        st.html(_table(EXIT_COLS, _rows(ex, syms, names, size, 'exit')))

    # Industry roll-up
    lvl = fl.next_level(ind, picks)
    ru = fl.rollup(sw, ind, lvl)
    if lvl is None or ru.empty:
        _qa('Where did the money go, by sector?', 'No classification to group by',
            'The industry table has no rows yet and the security master has no sector for these stocks.', 'sectors')
    else:
        word = fl.LEVEL_LABEL[lvl].lower()
        best, worst = ru.iloc[0], ru.iloc[-1]
        ans = (f'Most into <b>{esc(best["label"])}</b> ({esc(_cr(best["net_cr"]))})' if best['net_cr'] > 0 else 'No net buying in any ' + word)
        if worst['net_cr'] < 0:
            ans += f'; most out of <b>{esc(worst["label"])}</b> ({esc(_cr(worst["net_cr"]))})'
        uncl = ru.loc[ru['label'].eq(fl.UNCLASSIFIED), 'stocks']
        _qa(f'Where did the money go, by {word}?', ans,
            f'Net rupees per {word}, the filters above applied'
            + (f'; {int(uncl.iloc[0])} stocks have no {word} and are one bar, "{fl.UNCLASSIFIED}"' if len(uncl) else '') + '.',
            'sectors')
        chart = charts.diverging_bars(ru)
        if chart is not None:
            st.altair_chart(chart, width='stretch')

    _positioning_section(ch, stock, win, month, hname, size, sector, mf_ms)

    # One house
    _qa('What did one fund house do?', 'Pick a house', 'Every stock the house bought or sold in the period, by rupees, '
        'the size and industry filters applied.', 'house')
    if house_keys:
        one = st.selectbox('Fund house', house_keys, format_func=hname, key='fd_house', width=320,
                           index=house_keys.index('sbi') if 'sbi' in house_keys else 0)
        h1 = fl.apply_isins(fl.house_rows(ch, stock, win, [one], passive), listed, *keep)
        h1 = h1[h1['net'].ne(0)]
        hb = h1[h1['net'].gt(0)].sort_values('net_cr', ascending=False, na_position='last')
        hs = h1[h1['net'].lt(0)].sort_values('net_cr', na_position='last')
        st.html(f'<p class="qa-why"><b>{esc(hname(one))}</b>: bought {len(hb):,} stocks for {esc(_cr(hb["net_cr"].sum()))}, '
                f'sold {len(hs):,} for {esc(_cr(hs["net_cr"].sum()))}; '
                f'{int(h1["status"].eq("new").sum())} new positions, {int(h1["status"].eq("exit").sum())} sold out.</p>')
        st.html('<p><b>Bought</b></p>' + (_house_table(hb, syms, names, size, tot) if len(hb) else _empty('Nothing bought.')))
        st.html('<p><b>Sold</b></p>' + (_house_table(hs, syms, names, size, tot) if len(hs) else _empty('Nothing sold.')))

    # NPS pension funds, apart
    nps_win = [m for m in win if nps_ch is not None and not nps_ch.empty and (nps_ch['month'] == m).any()]
    if nps_win:
        nh = fl.apply_isins(fl.house_rows(nps_ch, nps_stock, nps_win, None, passive), listed, *keep)
        pv = fl.lists(fl.stock_window(nh, tot))
        mgrs = int(nps_ch.loc[nps_ch['month'].isin(nps_win), 'amc'].nunique())
        _qa('What did NPS pension funds add and cut?',
            f'Added most: {_names(pv["bought"], names, 2)}' if len(pv['bought']) else 'No stock added for ₹1 Cr or more',
            f'{mgrs} NPS pension fund managers, every scheme (E, C, G, government, APY ...), {_period_label(nps_win)}. '
            'PFRDA\'s investment rules keep NPS equity to large listed companies and the schemes largely follow '
            'the index: read this as where pension money went, not as stock picks. Not in the lists above.', 'nps')
        st.html('<p><b>Added most</b></p>' + (_table(COLS, _rows(pv['bought'], syms, names, size)) if len(pv['bought']) else
                _empty('No stock added for ₹1 Cr or more.')))
        st.html('<p><b>Cut most</b></p>' + (_table(COLS, _rows(pv['sold'], syms, names, size)) if len(pv['sold']) else
                _empty('No stock cut for ₹1 Cr or more.')))

    # Is this complete?
    in_month = set(ch.loc[ch['month'] == month, 'amc']) if ch is not None and not ch.empty else set()
    mf_cat = [(key, nm) for key, nm in names_by_key.items() if not key.startswith('nps_')]
    mh = fl.missing_houses(in_month, mf_cat, not_collected)
    gone = '; '.join(f'{nm} ({why})' for nm, why in mh['not_collected'])
    absent = ', '.join(nm for nm, _ in mh['absent'])
    _qa('Is this complete?', f'{len(in_month)} of {len(mf_cat)} mutual fund houses collected are compared for {_label(month)}',
        cov_line, 'complete')
    lines = []
    if gone:
        lines.append(f'<b>Not collected:</b> {esc(gone)}.')
    if absent:
        lines.append(f'<b>Collected, but not compared for {esc(_label(month))}</b> (not filed, not read yet, or the month-end '
                     f'before missing): {esc(absent)}.')
    if len(win) > 1:
        per = ', '.join(f'{_short(m)} {n_by.get(m, 0)}' for m in win)
        lines.append(f'<b>Houses compared each month-end:</b> {esc(per)}. A house missing a month adds nothing for it.')
    if unlisted:
        lines.append(f'{unlisted} ISINs the houses filed as equity are not listed equity in the security master (unlisted or '
                     'not yet listed shares) and are left out.')
    if k['unvalued']:
        lines.append(f'{k["unvalued"]} stocks moved with no filed price in the period and are left out of the rupee figures.')
    lines.append(f'{v["small"]:,} stocks with net moves under ₹{MIN_NET_CR:.0f} Cr counted, not listed. PMS and AIFs file no '
                 'holdings stock by stock; they show only in bulk and block deals and 5% crossings.')
    st.html(''.join(f'<p class="qa-why">{x}</p>' for x in lines))
    st.html(_more('investor-flows', 'Fund trades in bulk and block deals'))
    st.html(_more('ownership', 'Quarterly fund holdings, every fund (shareholding filings)'))
