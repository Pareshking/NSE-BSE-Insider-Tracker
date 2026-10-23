"""Today (home), the money board (owner, 21 and 23 Oct 2026): across every listed company, for one of four
periods (today, 7, 30 or 90 days), where real money moved: "Money in" (insiders and big investors buying,
promoters paying up, buybacks, capital raised), "Money out" (insiders and big investors selling) and
"Risk changes" (pledges, cheap shares to promoters), in groups, from insiders_clean/ideas.py. Tiles and a
trend panel count companies per group in each period; filters by size, sector and name. One row per
company: its size and price, one sentence, three numbers, the reasons as chips with their measured read;
it opens to the facts and links. "Coming up" lists the money events of the next ten days. Everything else
is in Filings (docs/DESIGN_V3.md)."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from data import store
from ui import kit, lwchart
from ui.kit import Tile, esc

from insiders_clean import ideas
from screens import buybacks, filings_all
from screens.ctx import issue_rows, load, need_data, qip_rows, rights_rows, split_since
from ui import table as tbl

READ = {'leaning_positive': 'Ahead', 'drag': 'Behind', 'no_edge': 'No edge', 'few': 'Few cases', 'not_measured': 'Not measured'}
WARN_KINDS = {k for _, ks in ideas.GROUPS['warn'] for k in ks}
RAISE_KINDS = {k for n, ks in ideas.GROUPS['look'] if n == 'Raises' for k in ks}   # shares issued: dilution, a neutral chip
# The panels (docs/DESIGN_V3.md): (title, key, side, [(list, group)]). Pledges released is de-risking, so it sits with the pledges.
PANELS = [
    ('Money in', 'td_in', 'left', [('look', g) for g in ('Insiders buying', 'Promoters pay up', 'Big investors and funds in',
                                                         'Buybacks at a premium', 'Raises')]),
    ('Money out', 'td_out', 'right', [('warn', 'Insiders selling'), ('warn', 'Big investors and funds out')]),
    ('Risk changes', 'td_risk', 'right', [('warn', 'Pledges'), ('look', 'Pledges released'), ('warn', 'Cheap shares to promoters')]),
]
COMING_DAYS = 10
DEFAULT_PERIOD = 'Last 30 days'
SIZES = ['All sizes', 'Large', 'Mid', 'Small', 'Micro']
# Sort inside each group: (column, the list's subtitle)
SORTS = {'Share of the company': ('pct_of_company', 'largest share of the company first'),
         'Value': ('_val', 'largest value first'), 'Latest': ('last', 'newest first')}
DEFAULT_SORT = 'Share of the company'
# Short names where space is tight (the group pills, the trend panel); the list headings keep the full ones.
SHORT = {'Insiders buying': 'Insiders buying', 'Promoters pay up': 'Promoters pay up', 'Pledges released': 'Pledges released',
         'Big investors and funds in': 'Investors in', 'Buybacks at a premium': 'Buybacks', 'Insiders selling': 'Insiders selling', 'Raises': 'Raises',
         'Pledges': 'Pledges up', 'Cheap shares to promoters': 'Cheap to promoters', 'Big investors and funds out': 'Investors out'}


@st.cache_data(ttl=3600, show_spinner=False, max_entries=2)
def _inputs(_ctx, ref_key: str) -> tuple:
    """What every period shares: the track summary, the issues and the buybacks on today's prices, and the
    cluster and spotlight companies (their own 30-day windows)."""
    ctx = _ctx
    summary = store.artifact('artifacts/track_summary.parquet')
    issues = issue_rows(ctx.preferential, ctx.prices) if ctx.preferential is not None and not ctx.preferential.empty else None
    qip, rights = qip_rows(store.table('qip'), ctx.prices), rights_rows(ctx.rights, ctx.prices)
    return (summary, issues, buybacks.rows(store.table('buybacks'), ctx.prices, ctx.meetings), ideas.marked(ctx.eligible, ctx.ref),
            qip, rights, _funds_named())


def _funds_named() -> dict:
    """app_id -> True where the filing names a mutual fund among the allottees (preferential: by name; QIP: by category)."""
    out = {}
    pa, qa = store.table('preferential_allottees'), store.table('qip_allottees')
    if pa is not None and not pa.empty and {'app_id', 'allottee'} <= set(pa.columns):
        out |= {str(a): True for a in pa.loc[pa['allottee'].astype(str).str.contains(r'mutual fund|\bMF\b', case=False, regex=True), 'app_id']}
    if qa is not None and not qa.empty and {'app_id', 'category'} <= set(qa.columns):
        out |= {str(a): True for a in qa.loc[qa['category'].astype(str).str.contains('mutual', case=False), 'app_id']}
    return out


@st.cache_data(ttl=3600, show_spinner=False, max_entries=8)
def _lists(_ctx, ref_key: str, days: int) -> tuple:
    """(look, warn) for one period; `ref_key` (the data's as-of day) keys the cache."""
    ctx, ref, sh = _ctx, _ctx.ref, _ctx.shareholding
    summary, issues, bb, marks, qip, rights, named = _inputs(ctx, ref_key)
    return ideas.today([
        ideas.insider_events(ctx.eligible, ref, sh, summary, days=days, marks=marks), ideas.pledge_events(ctx.trades, ref, sh, days=days, enc=ctx.encumbrances),
        ideas.stake_events(ctx.sast, ref, days=days), ideas.fund_events(ctx.deals, ctx.trades, ref, days=days, sh=sh),
        ideas.promoter_deal_events(ctx.deals, ctx.trades, ref, days=days, sh=sh),
        ideas.issue_events(issues, ref, sh, days=days, allottees=store.table('preferential_allottees')), ideas.buyback_events(bb, ref, sh, days=days),
        ideas.raise_events(issues, qip, rights, ref, sh, days=days, named=named),
        ideas.holder_events(store.snapshot(), ref, days=days)], summary)


def _num(label: str, value: str, tip: str = '') -> str:
    t = f' title="{esc(tip, quote=True)}"' if tip else ''
    return f'<div class="kv"{t}><span>{esc(label)}</span><b>{esc(value)}</b></div>'


def _chips(kinds, reads, big: bool = False) -> str:
    out = []
    for k in kinds:
        tone = 'sell' if k in WARN_KINDS else 'mute' if k == 'Steady accumulation' or k in RAISE_KINDS else 'acc'
        read = '' if k in RAISE_KINDS else READ.get((reads or {}).get(k, ''), '')
        out.append(f'<span class="chip {tone}">{esc(k)}' + (f'<i>{esc(read)}</i>' if read else '') + '</span>')
    if big:   # one decision-maker, Rs 25 Cr and up, whatever its share of the company (owner, 23 Oct)
        crore = f'₹{ideas.BIG_VALUE / 1e7:.0f} Cr'
        out.insert(0, f'<span class="chip mute" title="One decision-maker, {crore} or more in the period, whatever its share of the company">{crore}+</span>')
    return ''.join(out)


def _row(ctx, r, holding, px) -> str:
    isin = r['isin']
    pr = px.get(isin)
    now = pr['latest_close'] if pr is not None and pd.notna(pr.get('latest_close')) else None
    mcap = pr['market_cap'] if pr is not None and pd.notna(pr.get('market_cap')) else None
    s = holding.get(isin) or holding.get(('sym', r.get('nse_symbol')))
    href = kit.company_href(r['nse_symbol'])
    pct = r.get('pct_of_company')
    pct = pct if pd.notna(pct) and pct else None
    if pd.notna(r.get('value')) and r.get('value'):
        worth, tip = kit.rupees(r['value']), 'As filed'
    elif pct and mcap:
        worth, tip = '≈ ' + kit.rupees(pct / 100 * mcap), "The shares at today's market cap"
    else:
        worth, tip = '—', ''
    third = (_num(r['kv3_label'], r['kv3']) if isinstance(r.get('kv3_label'), str) and isinstance(r.get('kv3'), str)
             else _num('Promoters', kit.pct(s['promoter_holding_pct'], 1) if s is not None and pd.notna(s.get('promoter_holding_pct')) else '—'))
    nums = [_num('Of company' if r.get('kind') not in RAISE_KINDS else 'New shares', f'{pct:.2f}%' if pct else '—'), _num('Value', worth, tip), third]
    mk = tbl.market_line({'mk_bucket': pr.get('mcap_bucket') if pr is not None else None, 'mk_cap': mcap, 'mk_px': now,
                          'mk_lo': pr.get('low_52w') if pr is not None else None, 'mk_hi': pr.get('high_52w') if pr is not None else None})
    sym_line = (f'<div class="sub"><span class="sym">{esc(str(r.get("nse_symbol") or ""))}</span>{mk}</div>')
    facts = [('Made public', kit.day(r['last']) if pd.notna(r.get('last')) else '')]
    # A filing made public weeks after the trade (239 open-market rows over 30 sessions late, audit 23 Oct): the
    # period counts it on the day it was made public, so the card says how old the trade already was.
    late = (pd.Timestamp(r['last']) - pd.Timestamp(r['trade_to'])).days if pd.notna(r.get('last')) and pd.notna(r.get('trade_to')) else 0
    if late > 14:
        facts.append(('Filed late', f'last traded {kit.day(r["trade_to"])}, made public {late} days later'))
    if pd.notna(r.get('avg_price')) and r.get('avg_price'):
        f = float(split_since(pd.DataFrame({'isin': [isin], 'trade_date_to': [r.get('trade_to')]}), ctx.prices).iloc[0])
        if f == f and now:
            paid = r['avg_price'] * f
            facts.append(('Paid · now', f'{kit.price(paid)} · {kit.price(now)} ({(now / paid - 1) * 100:+.1f}%)'))
    if pd.notna(r.get('decision_makers')) and r.get('decision_makers'):
        facts.append(('Decision-makers', str(int(r['decision_makers']))))
    if s is not None and pd.notna(s.get('promoter_holding_pct')) and r.get('kv3_label') == 'Own stake':
        facts.append(('Promoters hold', kit.pct(s['promoter_holding_pct'], 1)))   # the number the third slot gave way to
    if s is not None and pd.notna(s.get('promoter_pledge_pct')):
        facts.append(('Pledged', f'{kit.pct(s["promoter_pledge_pct"], 1)} of promoter shares'))
    if pr is not None and pd.notna(pr.get('pct_off_high')):
        facts.append(('From 52W high', kit.pct(pr['pct_off_high'] * 100, 1, signed=True)))
    if mcap:
        facts.append(('Market cap', kit.rupees(mcap)))
    grid = ''.join(f'<div><b>{esc(k)}</b><span>{esc(v)}</span></div>' for k, v in facts if v)
    also = ''.join(f'<li>{esc(x)}</li>' for x in (r.get('others') or []))
    return (f'<details class="idea"><summary>'
            f'<div class="idea-co"><a href="{esc(href, quote=True)}" target="_self">{esc(str(r["company"]))}</a>'
            f'{sym_line}<p>{esc(r["sentence"])}</p><div class="idea-chips">{_chips(r["kinds"], r.get("reads"), bool(r.get("big")) and r.get("kind") not in RAISE_KINDS)}</div></div>'
            f'{"".join(nums)}</summary>'
            f'<div class="idea-more">' + (f'<ul class="idea-also">{also}</ul>' if also else '')
            + f'<div class="idea-grid">{grid}</div><a href="{esc(href, quote=True)}" target="_self">Company page →</a></div></details>')


def _filter(df: pd.DataFrame, size: str, sector: str, text: str, px: dict, sectors: dict) -> pd.DataFrame:
    if df.empty:
        return df
    keep = pd.Series(True, index=df.index)
    if size != SIZES[0]:
        keep &= df['isin'].map(lambda i: (px.get(i) or {}).get('mcap_bucket') == size)
    if sector:
        keep &= df['isin'].map(sectors).eq(sector)
    if text:
        q = text.strip().lower()
        keep &= (df['company'].fillna('').str.lower().str.contains(q, regex=False)
                 | df['nse_symbol'].fillna('').str.lower().str.contains(q, regex=False))
    return df[keep]


def _sorted(df: pd.DataFrame, order: str, px: dict) -> pd.DataFrame:
    """Each group's rows in the chosen order (the groups keep theirs). Value is as filed, else the shares at
    today's market cap, as the Value column shows it."""
    if df.empty or order == DEFAULT_SORT:
        return df
    col = SORTS[order][0]
    if col == '_val':
        mcap = pd.to_numeric(df['isin'].map(lambda i: (px.get(i) or {}).get('market_cap')), errors='coerce')
        est = pd.to_numeric(df['pct_of_company'], errors='coerce') / 100 * mcap
        filed = pd.to_numeric(df['value'], errors='coerce')
        df = df.assign(_val=filed.where(filed > 0, est))
    return df.sort_values(['group_order', col], ascending=[True, False], na_position='last', kind='stable')


def _counts(df: pd.DataFrame) -> dict:
    return df['group'].value_counts().to_dict() if not df.empty else {}


def _value(df: pd.DataFrame, group: str) -> float:
    x = df[df['group'] == group] if not df.empty else df
    return float(pd.to_numeric(x['value'], errors='coerce').sum()) if len(x) else 0.0


def _list(ctx, frames: dict, groups: list, pick: str, holding, px) -> None:
    """The groups of one panel, each its company rows (up to PER_GROUP); `frames` is {'look': ..., 'warn': ...}."""
    shown = 0
    for lst, name in groups:
        if pick not in ('All', name):
            continue
        df = frames[lst]
        g = df[df['group'] == name] if not df.empty else df
        if g.empty:
            continue
        shown += 1
        more = len(g) - ideas.PER_GROUP
        st.html(f'<div class="grp"><h3>{esc(name)}</h3><span>{kit.plural(len(g), "company", "companies")}</span></div>'
                '<div class="ideas">' + ''.join(_row(ctx, r, holding, px) for r in g.head(ideas.PER_GROUP).to_dict('records'))
                + '</div>' + (f'<p class="grp-more"><a href="/filings-all" target="_self">{more} more in Filings →</a></p>'
                              if more > 0 else ''))
    if not shown:
        kit.empty('Nothing passed the bar in this period.' if pick == 'All' else f'No {pick.lower()} in this period.')


def _coming(ctx) -> pd.DataFrame:
    """The money events of the next COMING_DAYS days: meetings on fund raising or a buyback, tender closes, lock-ins ending."""
    _, up = filings_all._upcoming(ctx, ctx.ref, filings_all._names(ctx))
    if up.empty:
        return up
    day = pd.Timestamp(ctx.ref).normalize()
    up = up[(pd.to_datetime(up['made_public']) <= day + pd.Timedelta(days=COMING_DAYS))].sort_values('made_public', kind='stable')
    return filings_all._market(up, ctx)


def _breadth_tile(ctx, days: int) -> Tile:
    """The whole market's insider buying against selling, with the period before it (not the page's size or sector filters)."""
    b = ideas.insider_breadth(ctx.eligible, ctx.ref, max(days, 7))
    if not b or b['buy_share'] is None:
        return Tile('Insider buying share', '—', 'no decision-makers traded in this period')
    before = b['before']
    prev = f' · {before["buy_share"]:.0f}% the period before' if before and before['buy_share'] is not None else ''
    return Tile('Insider buying share', f'{b["buy_share"]:.0f}%',
                f'of rupees traded by decision-makers · {b["buy_companies"]} companies buying, {b["sell_companies"]} selling{prev}',
                'up' if b['buy_share'] >= 50 else 'down')


def render():
    ctx = load()
    if not need_data(ctx):
        return
    key = str(ctx.ref)
    # The headline is the page's first line, the period beside it (no title repeating the menu).
    top, right = st.columns([2.2, 1.8], vertical_alignment='center')
    with right:
        period = st.segmented_control('Period', list(ideas.PERIODS), default=DEFAULT_PERIOD, key='td_period',
                                       label_visibility='collapsed', width='content') or DEFAULT_PERIOD
    every = {p: _lists(ctx, key, d) for p, d in ideas.PERIODS.items()}

    # The lookups below hold only the columns a row reads: a dict of every column of every price and
    # shareholding row took most of each rerun (22 Oct).
    pcols = [c for c in ('isin', 'latest_close', 'market_cap', 'pct_off_high', 'mcap_bucket', 'low_52w', 'high_52w') if c in ctx.prices]
    px = ({i: r for i, r in zip(ctx.prices['isin'], ctx.prices[pcols].to_dict('records'))} if not ctx.prices.empty else {})
    sec = ctx.securities
    sectors = (dict(zip(sec['isin'], sec['sector'])) if sec is not None and not sec.empty and {'isin', 'sector'} <= set(sec.columns)
               else {})
    # Each company's latest quarter that has the promoter holding (a newer row can still be waiting for it).
    shd, latest = ctx.shareholding, pd.DataFrame()
    if shd is not None and not shd.empty:
        s = shd[[c for c in ('isin', 'symbol', 'quarter_end', 'promoter_holding_pct', 'promoter_pledge_pct') if c in shd]]
        s = s.assign(quarter_end=pd.to_datetime(shd['quarter_end'], errors='coerce'),
                     promoter_holding_pct=pd.to_numeric(shd['promoter_holding_pct'], errors='coerce'))
        latest = s.dropna(subset=['promoter_holding_pct']).sort_values('quarter_end')
    holding = {}
    if not latest.empty:
        # By ISIN, and by NSE symbol for a filing whose row carries no ISIN (Electrosteel showed a dash).
        for r in latest.to_dict('records'):
            for k in (r.get('isin'), ('sym', r.get('symbol'))):
                if isinstance(k, str) or (isinstance(k, tuple) and isinstance(k[1], str)):
                    holding[k] = r

    head = st.container()
    # One bar under the tiles (as the owner's screener): search, the groups, and the rest in "Filters & sort".
    with st.container(key='td_bar', horizontal=True, vertical_alignment='center', gap='small'):
        text = st.text_input('Company', key='td_text', placeholder='Search company or symbol', label_visibility='collapsed',
                             width=280)
        pills = st.container(width='stretch')
        with st.popover('Filters & sort', icon=':material/tune:', width='content'):
            size = st.segmented_control('Size', SIZES, default=SIZES[0], key='td_size', required=True) or SIZES[0]
            names = sorted({v for v in sectors.values() if isinstance(v, str) and v})
            sector = st.selectbox('Sector', ['All sectors'] + names, key='td_sector')
            order = st.segmented_control('Sort by', list(SORTS), default=DEFAULT_SORT, key='td_sort', required=True) or DEFAULT_SORT
    sector = '' if sector == 'All sectors' else sector

    # One name per company, the security master's, whichever filing the row came from (audit 22 Oct:
    # "RHI MAGNESITA INDIA LTD" beside "Rhi Magnesita India", "PENNAR INDUSTRIES LIMTIED" as filed).
    disp = (dict(zip(sec['isin'], sec['display_name'])) if sec is not None and not sec.empty
            and {'isin', 'display_name'} <= set(sec.columns) else {})
    named = {p: tuple(x.assign(company=x['isin'].map(disp).fillna(x['company'])) if not x.empty else x for x in lw)
             for p, lw in every.items()}
    view = {p: tuple(_filter(x, size, sector, text, px, sectors) for x in lw) for p, lw in named.items()}
    look, warn = (_sorted(x, order, px) for x in view[period])
    span = 'today' if ideas.PERIODS[period] == 1 else period.lower()
    cl, cw = _counts(look), _counts(warn)
    bought, sold, raised = _value(look, 'Insiders buying'), _value(warn, 'Insiders selling'), _value(look, 'Raises')
    have = {**cl, **cw}
    count = {title: sum(have.get(g, 0) for _, g in groups) for title, _, _, groups in PANELS}
    with top:
        st.html(f'<div class="head"><h1 class="headline"><b class="up">{count["Money in"]}</b> '
                f'{"company" if count["Money in"] == 1 else "companies"} with money in, <b class="down">{count["Money out"]}</b> with '
                f'money out, <b>{count["Risk changes"]}</b> risk {"change" if count["Risk changes"] == 1 else "changes"} '
                f'<span>{esc(kit.sentence(span))} to {kit.day(ctx.ref)}</span></h1></div>')
    n = lambda d, k: d.get(k, 0)   # noqa: E731
    with head:
        kit.tiles([
            Tile('Insiders buying', str(n(cl, 'Insiders buying')), f'{kit.rupees(bought)} bought' if bought else 'companies', 'up'),
            Tile('Insiders selling', str(n(cw, 'Insiders selling')), f'{kit.rupees(sold)} sold' if sold else 'companies', 'down'),
            Tile('Capital raised', str(n(cl, 'Raises')), f'{kit.rupees(raised)} in QIPs, issues and rights' if raised else 'companies'),
            Tile('Big investors in', str(n(cl, 'Big investors and funds in')), f'{n(cw, "Big investors and funds out")} out, with funds', 'up'),
            Tile('Pledges up', str(n(cw, 'Pledges')), f'{n(cl, "Pledges released")} released', 'down' if n(cw, 'Pledges') else ''),
            _breadth_tile(ctx, ideas.PERIODS[period]),
        ])

    groups = [g for _, _, _, gs in PANELS for _, g in gs]
    with pills:
        pick = st.pills('Group', ['All'] + [g for g in groups if have.get(g)], default='All', key='td_group',
                        format_func=lambda g: g if g == 'All' else f'{SHORT.get(g, g)} · {have.get(g, 0)}',
                        label_visibility='collapsed') or 'All'

    # Money in on the left, Money out above Risk changes on the right on a wide screen (one under the other on a phone).
    frames = {'look': look, 'warn': warn}
    shown_panels = [p for p in PANELS if pick == 'All' or any(pick == g for _, g in p[3])]
    sides = [side for side in ('left', 'right') if any(p[2] == side for p in shown_panels)]
    holders = st.columns(len(sides), gap='medium') if len(sides) > 1 else [st.container()]
    for col, side in zip(holders, sides):
        with col:
            for title, key, _, groups in (p for p in shown_panels if p[2] == side):
                with kit.card(title, key, SORTS[order][1]):
                    _list(ctx, frames, groups, pick, holding, px)

    # What is next: meetings on fund raising or a buyback, tender closes, lock-ins ending (a meeting is not a raise
    # until its outcome is filed).
    coming = _coming(ctx)
    with kit.card('Coming up', 'td_up', f'money events in the next {COMING_DAYS} days · a meeting is not a raise until its outcome is filed'):
        if coming.empty:
            kit.empty(f'No money events in the next {COMING_DAYS} days.')
        else:
            kit.table(coming, [kit.Col('made_public', 'Date', 'date'), kit.Col('company', 'Company', 'co2'),
                               kit.Col('what', 'What', wrap=True), kit.Col('what_sub', 'Detail', wrap=True, phone=False),
                               kit.Col('value', 'Size', 'money', phone=False)], limit=12, height=420, keep_empty=True)

    # The trend at the foot of the page, its full width: companies made public each week over 90 days, Worth a
    # look above the line, Watch out below (TradingView Lightweight Charts, owner 22 Oct); the group pills apply.
    wide = view['Last 90 days']
    grp = (lambda x: x if pick == 'All' or x.empty else x[x['group'] == pick])
    with kit.card('Trend', 'td_trend', 'companies each week, 90 days · ▲ worth a look ▼ watch out' + ('' if pick == 'All' else f' · {pick}')):
        chart = lwchart.weekly_bars(grp(wide[0]), grp(wide[1]), key=f'td_{pick}')
        if chart is None:
            kit.empty('Nothing in the last 90 days.')
        else:
            st.html(chart, unsafe_allow_javascript=True)
    with st.expander('How a filing makes the list'):
        st.html('<ul class="bar-rules">'
                f'<li>Insiders: per decision-maker in the period, ₹{ideas.MIN_VALUE / 1e5:.0f} L and {ideas.MIN_PCT:g}% '
                f'of the company, or {ideas.ALONE_PCT:g}% alone, or buying on {ideas.STEADY_DAYS}+ days, or ₹{ideas.BIG_VALUE / 1e7:.0f} Cr '
                'and up whatever the share (those rows go first). A director or KMP selling counts only at that size</li>'
                f'<li>Raises: QIPs, preferential issues to others and rights issues, allotted; ₹{ideas.RAISE_MIN_AMOUNT / 1e7:.0f} Cr and up, '
                f'or {ideas.RAISE_MIN_DILUTION:g}% of the shares outstanding. Shares issued are dilution: neutral, not a verdict</li>'
                f'<li>Big investors: crossing {ideas.BIG_STAKE:g}% or moving {ideas.BIG_CHANGE:g}%+ (SAST); trustees for lenders left out</li>'
                f'<li>Funds: net {ideas.FUND_NET_PCT:g}%+ of the company in bulk/block deals</li>'
                f'<li>Holdings: mutual funds or foreign investors moving {ideas.HOLDER_MIN_PTS:g}+ point of the company in the latest '
                f'quarter filed, worth ₹{ideas.HOLDER_MIN_VALUE / 1e7:.0f} Cr+ at today\'s market cap (30 and 90 day views)</li>'
                f'<li>Pledges: net of releases; or {ideas.PLEDGE_RISE_PTS:g}+ points in a quarter</li>'
                '<li>Evidence is a tag, never a filter</li>'
                '</ul><a class="bar-all" href="/filings-all" target="_self">Every filing &rarr;</a>')
