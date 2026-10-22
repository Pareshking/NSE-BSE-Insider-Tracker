"""Today (home), the dashboard (owner, 21 Oct 2026): across every listed company, for one of four periods
(today, 7, 30 or 90 days), "Worth a look" (people with skin in the game put money in at a size that
matters) and "Watch out" (they took it out, pledged, or took cheap shares), in groups, from
insiders_clean/ideas.py. Tiles and a trend panel count companies per group in each period; filters by
size, sector and name. One row per company: one sentence, three numbers, the reasons as chips with their
measured read; it opens to the facts and links. Everything else is in Filings."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from data import store
from ui import kit
from ui.kit import Tile, esc

from insiders_clean import ideas, signals
from screens import buybacks
from screens.ctx import issue_rows, load, need_data, split_since

READ = {'leaning_positive': 'ahead', 'drag': 'behind', 'no_edge': 'no edge', 'few': 'few cases', 'not_measured': 'not measured'}
WARN_KINDS = {k for _, ks in ideas.GROUPS['warn'] for k in ks}
DEFAULT_PERIOD = 'Last 30 days'
SIZES = ['All sizes', 'Large', 'Mid', 'Small', 'Micro']
# Short names where space is tight (the group pills, the trend panel); the list headings keep the full ones.
SHORT = {'Insiders buying': 'Insiders buying', 'Promoters pay up': 'Promoters pay up', 'Pledges released': 'Pledges released',
         'Big investors and funds in': 'Investors in', 'Buybacks at a premium': 'Buybacks', 'Promoters selling': 'Promoters selling',
         'Pledges': 'Pledges up', 'Cheap shares to promoters': 'Cheap to promoters', 'Big investors and funds out': 'Investors out'}


@st.cache_data(ttl=3600, show_spinner=False, max_entries=2)
def _inputs(_ctx, ref_key: str) -> tuple:
    """What every period shares: the track summary, the issues and the buybacks on today's prices."""
    ctx = _ctx
    summary = store.artifact('artifacts/track_summary.parquet')
    issues = issue_rows(ctx.preferential, ctx.prices) if ctx.preferential is not None and not ctx.preferential.empty else None
    return summary, issues, buybacks.rows(store.table('buybacks'), ctx.prices)


@st.cache_data(ttl=3600, show_spinner=False, max_entries=8)
def _lists(_ctx, ref_key: str, days: int) -> tuple:
    """(look, warn) for one period; `ref_key` (the data's as-of day) keys the cache."""
    ctx, ref, sh = _ctx, _ctx.ref, _ctx.shareholding
    summary, issues, bb = _inputs(ctx, ref_key)
    return ideas.today([
        ideas.insider_events(ctx.eligible, ref, sh, summary, days=days), ideas.pledge_events(ctx.trades, ref, sh, days=days),
        ideas.stake_events(ctx.sast, ref, days=days), ideas.fund_events(ctx.deals, ctx.trades, ref, days=days, sh=sh),
        ideas.issue_events(issues, ref, sh, days=days), ideas.buyback_events(bb, ref, sh, days=days)], summary)


def _num(label: str, value: str, tip: str = '') -> str:
    t = f' title="{esc(tip, quote=True)}"' if tip else ''
    return f'<div class="kv"{t}><span>{esc(label)}</span><b>{esc(value)}</b></div>'


def _chips(kinds, reads) -> str:
    out = []
    for k in kinds:
        tone = 'sell' if k in WARN_KINDS else 'mute' if k == 'Steady accumulation' else 'acc'
        read = READ.get((reads or {}).get(k, ''), '')
        out.append(f'<span class="chip {tone}">{esc(k)}' + (f'<i>{esc(read)}</i>' if read else '') + '</span>')
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
    nums = [_num('Of the company', f'{pct:.2f}%' if pct else '—'), _num('Value', worth, tip),
            _num('Promoters hold', kit.pct(s['promoter_holding_pct'], 1) if s is not None and pd.notna(s.get('promoter_holding_pct')) else '—')]
    facts = [('Made public', kit.day(r['last']) if pd.notna(r.get('last')) else '')]
    if pd.notna(r.get('avg_price')) and r.get('avg_price'):
        f = float(split_since(pd.DataFrame({'isin': [isin], 'trade_date_to': [r.get('trade_to')]}), ctx.prices).iloc[0])
        if f == f and now:
            paid = r['avg_price'] * f
            facts.append(('Paid · now', f'{kit.price(paid)} · {kit.price(now)} ({(now / paid - 1) * 100:+.1f}%)'))
    if pd.notna(r.get('decision_makers')) and r.get('decision_makers'):
        facts.append(('Decision-makers', str(int(r['decision_makers']))))
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
            f'<p>{esc(r["sentence"])}</p><div class="idea-chips">{_chips(r["kinds"], r.get("reads"))}</div></div>'
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


def _counts(df: pd.DataFrame) -> dict:
    return df['group'].value_counts().to_dict() if not df.empty else {}


def _value(df: pd.DataFrame, group: str) -> float:
    x = df[df['group'] == group] if not df.empty else df
    return float(pd.to_numeric(x['value'], errors='coerce').sum()) if len(x) else 0.0


def _list(ctx, df: pd.DataFrame, lst: str, pick: str, holding, px) -> None:
    shown = 0
    for name, _ in ideas.GROUPS[lst]:
        if pick not in ('All', name):
            continue
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


def render():
    ctx = load()
    if not need_data(ctx):
        return
    key = str(ctx.ref)
    # The headline is the page's first line, the period beside it (no title repeating the menu).
    top, right = st.columns([3, 1.3], vertical_alignment='center')
    with right:
        period = st.segmented_control('Period', list(ideas.PERIODS), default=DEFAULT_PERIOD, key='td_period',
                                       label_visibility='collapsed', width='content') or DEFAULT_PERIOD
    every = {p: _lists(ctx, key, d) for p, d in ideas.PERIODS.items()}

    px = ({i: r for i, r in zip(ctx.prices['isin'], ctx.prices.to_dict('records'))} if not ctx.prices.empty else {})
    sec = ctx.securities
    sectors = (dict(zip(sec['isin'], sec['sector'])) if sec is not None and not sec.empty and {'isin', 'sector'} <= set(sec.columns)
               else {})
    # Each company's latest quarter that has the promoter holding (a newer row can still be waiting for it).
    latest = signals.latest_shareholding(ctx.shareholding)
    if not latest.empty:
        s = ctx.shareholding.assign(quarter_end=pd.to_datetime(ctx.shareholding['quarter_end'], errors='coerce'),
                                    promoter_holding_pct=pd.to_numeric(ctx.shareholding['promoter_holding_pct'], errors='coerce'))
        latest = s.dropna(subset=['promoter_holding_pct']).sort_values('quarter_end')
    holding = {}
    if not latest.empty:
        # By ISIN, and by NSE symbol for a filing whose row carries no ISIN (Electrosteel showed a dash).
        for r in latest.to_dict('records'):
            for k in (r.get('isin'), ('sym', r.get('symbol'))):
                if isinstance(k, str) or (isinstance(k, tuple) and isinstance(k[1], str)):
                    holding[k] = r

    head = st.container()
    c1, c2, c3 = st.columns([1, 1.4, 2], vertical_alignment='bottom')
    size = c1.selectbox('Size', SIZES, key='td_size', label_visibility='collapsed')
    names = sorted({v for v in sectors.values() if isinstance(v, str) and v})
    sector = c2.selectbox('Sector', ['All sectors'] + names, key='td_sector', label_visibility='collapsed')
    text = c3.text_input('Company', key='td_text', placeholder='Filter by company or symbol', label_visibility='collapsed')
    sector = '' if sector == 'All sectors' else sector

    # One name per company, the security master's, whichever filing the row came from (audit 22 Oct:
    # "RHI MAGNESITA INDIA LTD" beside "Rhi Magnesita India", "PENNAR INDUSTRIES LIMTIED" as filed).
    disp = (dict(zip(sec['isin'], sec['display_name'])) if sec is not None and not sec.empty
            and {'isin', 'display_name'} <= set(sec.columns) else {})
    named = {p: tuple(x.assign(company=x['isin'].map(disp).fillna(x['company'])) if not x.empty else x for x in lw)
             for p, lw in every.items()}
    view = {p: tuple(_filter(x, size, sector, text, px, sectors) for x in lw) for p, lw in named.items()}
    look, warn = view[period]
    span = 'today' if ideas.PERIODS[period] == 1 else period.lower()
    cl, cw = _counts(look), _counts(warn)
    bought, sold = _value(look, 'Insiders buying'), _value(warn, 'Promoters selling')
    with top:
        st.html(f'<h1 class="headline"><b class="up">{len(look)}</b> {"company" if len(look) == 1 else "companies"} '
                f'worth a look, <b class="down">{len(warn)}</b> to watch out <span>{esc(span)} to {kit.day(ctx.ref)}</span></h1>')
    n = lambda d, k: d.get(k, 0)   # noqa: E731
    with head:
        kit.tiles([
            Tile('Insiders buying', str(n(cl, 'Insiders buying')), f'{kit.rupees(bought)} bought' if bought else 'companies', 'up'),
            Tile('Promoters selling', str(n(cw, 'Promoters selling')), f'{kit.rupees(sold)} sold' if sold else 'companies', 'down'),
            Tile('Pledges up', str(n(cw, 'Pledges')), f'{n(cl, "Pledges released")} released', 'down' if n(cw, 'Pledges') else ''),
            Tile('Big investors in', str(n(cl, 'Big investors and funds in')), f'{n(cw, "Big investors and funds out")} out, with funds', 'up'),
            Tile('Promoters pay up', str(n(cl, 'Promoters pay up')), f'{n(cw, "Cheap shares to promoters")} took cheap shares'),
        ])

    groups = [n for lst in ('look', 'warn') for n, _ in ideas.GROUPS[lst]]
    have = {**cl, **cw}
    pick = st.pills('Group', ['All'] + [g for g in groups if have.get(g)], default='All', key='td_group',
                    format_func=lambda g: g if g == 'All' else f'{SHORT.get(g, g)} · {have.get(g, 0)}',
                    label_visibility='collapsed') or 'All'

    main, side = st.columns([2.7, 1], gap='medium')
    with main:
        if pick == 'All' or pick in dict(ideas.GROUPS['look']):
            with kit.card('Worth a look', 'td_look', 'largest share of the company first'):
                _list(ctx, look, 'look', pick, holding, px)
        if pick == 'All' or pick in dict(ideas.GROUPS['warn']):
            with kit.card('Watch out', 'td_warn', 'largest share of the company first'):
                _list(ctx, warn, 'warn', pick, holding, px)
    with side:
        with kit.card('Trend', 'td_trend', 'companies per period'):
            heads = ''.join(f'<th class="{"on" if p == period else ""}">{esc(h)}</th>'
                            for p, h in zip(ideas.PERIODS, ('1D', '7D', '30D', '90D')))
            body = ''
            for lst in ('look', 'warn'):
                for name, _ in ideas.GROUPS[lst]:
                    n = [_counts(view[p][0 if lst == 'look' else 1]).get(name, 0) for p in ideas.PERIODS]
                    cells = ''.join(f'<td class="{"on" if p == period else ""}">{v or "·"}</td>' for p, v in zip(ideas.PERIODS, n))
                    body += f'<tr class="{lst}"><th title="{esc(name, quote=True)}">{esc(SHORT.get(name, name))}</th>{cells}</tr>'
            st.html(f'<table class="trend"><thead><tr><th></th>{heads}</tr></thead><tbody>{body}</tbody></table>')
        with kit.card('The bar', 'td_bar'):
            st.html('<ul class="bar-rules">'
                    f'<li>Insiders: per decision-maker in the period, ₹{ideas.MIN_VALUE / 1e5:.0f} L and {ideas.MIN_PCT:g}% '
                    f'of the company, or {ideas.ALONE_PCT:g}% alone, or buying on {ideas.STEADY_DAYS}+ days</li>'
                    f'<li>Big investors: crossing {ideas.BIG_STAKE:g}% or moving {ideas.BIG_CHANGE:g}%+ (SAST); lenders\' trustees left out</li>'
                    f'<li>Funds: net {ideas.FUND_NET_PCT:g}%+ of the company in bulk/block deals</li>'
                    f'<li>Pledges: net of releases; or {ideas.PLEDGE_RISE_PTS:g}+ points in a quarter</li>'
                    '<li>Evidence is a tag, never a filter</li>'
                    '</ul><a class="bar-all" href="/filings-all" target="_self">Every filing →</a>')
