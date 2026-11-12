"""Today (home): where real money moved across every listed company, for one of four periods (today, 7, 30 or 90 days),
from insiders_clean/ideas.py (rules in docs/DESIGN_V3.md).

Redesign of 12 Nov 2026 (owner: "lots of data, not presented the right way"; benchmark tipsheet.markets): the first line
is the news in rupees (what insiders bought and sold), a one-line reading strip, then one column of questions in the order
the measured record supports: insiders buying, insiders selling, what could go wrong, raises and buybacks, funds and big
investors (in and out side by side; the quarterly holding changes folded apart, as they are dated by the quarter), and a
calendar of what is coming up. Each group is a table: five rows, "Show more" up to eight, the rest in Filings. Evidence
reads are quiet text tags; red and green are for selling and buying only."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from data import store
from ui import kit
from ui.kit import esc

from insiders_clean import ideas
from screens import buybacks, filings_all
from screens.ctx import issue_rows, load, need_data, qip_rows, rights_rows, split_since
from ui import table as tbl

READ = {'leaning_positive': 'Ahead', 'drag': 'Behind', 'no_edge': 'No edge', 'few': 'Few cases', 'not_measured': 'Not measured'}
WARN_KINDS = {k for _, ks in ideas.GROUPS['warn'] for k in ks}
RAISE_KINDS = {k for n, ks in ideas.GROUPS['look'] if n == 'Raises' for k in ks}   # shares issued: dilution, a neutral chip
COMING_DAYS = 10
CAL_DAYS, CAL_PER_DAY = 6, 6   # Coming up: day columns, events per day
SHOW = 5   # rows per group before "Show more" (the rest up to ideas.PER_GROUP)
# Quarterly shareholding moves (ideas.holder_events): dated by the quarter, so folded apart on Today.
HOLDER_KINDS = {'Mutual funds adding', 'Foreign investors adding', 'Mutual funds trimming', 'Foreign investors trimming'}
DEFAULT_PERIOD = 'Last 30 days'
SIZES = ['All sizes', 'Large', 'Mid', 'Small', 'Micro']
# Sort inside each group: (column, the list's subtitle)
SORTS = {'Share of the company': ('pct_of_company', 'largest share of the company first'),
         'Value': ('_val', 'largest value first'), 'Latest': ('last', 'newest first')}
DEFAULT_SORT = 'Share of the company'


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


def _num(label: str, value: str, tip: str = '', cls: str = '') -> str:
    t = f' title="{esc(tip, quote=True)}"' if tip else ''
    c = f' {cls}' if cls else ''
    return f'<div class="kv{c}"{t}><span>{esc(label)}</span><b>{esc(value)}</b></div>'


def _chips(kinds, reads, big: bool = False) -> str:
    """The row's kinds as quiet tags, and the measured read once, as text (Redesign 12 Nov: red and green are for
    buying and selling only; "Not measured" is not a verdict, so it is the faintest tag, not a red pill)."""
    out = []
    for k in kinds:
        tone = 'sell' if k in WARN_KINDS else 'mute' if k == 'Steady accumulation' or k in RAISE_KINDS else 'acc'
        read = '' if k in RAISE_KINDS else READ.get((reads or {}).get(k, ''), '')
        rcls = {'Ahead': 'ahead', 'Not measured': 'none'}.get(read, 'flat')
        out.append(f'<span class="chip {tone}">{esc(k)}' + (f'<i class="rd-{rcls}">{esc(read)}</i>' if read else '') + '</span>')
    if big:   # one decision-maker, Rs 25 Cr and up, whatever its share of the company (owner, 23 Oct)
        crore = f'₹{ideas.BIG_VALUE / 1e7:.0f} Cr'
        out.insert(0, f'<span class="chip mute" title="One decision-maker, {crore} or more in the period, whatever its share of the company">{crore}+</span>')
    return ''.join(out)


def _row(ctx, r, holding, px) -> str:
    """One company as one table line: company and its market line, what happened (one sentence and its tags), value,
    share of the company, and a third number with its own label; a tap opens the facts."""
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
        worth, tip = '≈ ' + kit.rupees(pct / 100 * mcap), "Not filed: the shares at today's market cap"
    else:
        worth, tip = '—', ''
    third = (_num(r['kv3_label'], r['kv3'], cls='k3') if isinstance(r.get('kv3_label'), str) and isinstance(r.get('kv3'), str)
             else _num('Promoters', kit.pct(s['promoter_holding_pct'], 1) if s is not None and pd.notna(s.get('promoter_holding_pct')) else '—',
                       'Promoter holding, latest quarter filed', cls='k3'))
    nums = [_num('Value', worth, tip, cls='k1'),
            _num('Of company' if r.get('kind') not in RAISE_KINDS else 'New shares', f'{pct:.2f}%' if pct else '—', cls='k2'), third]
    mk = tbl.market_line({'mk_bucket': pr.get('mcap_bucket') if pr is not None else None, 'mk_cap': mcap, 'mk_px': now,
                          'mk_lo': pr.get('low_52w') if pr is not None else None, 'mk_hi': pr.get('high_52w') if pr is not None else None})
    sym_line = (f'<div class="sub"><span class="sym">{esc(str(r.get("nse_symbol") or ""))}</span>{mk}</div>')
    facts = [('Made public', kit.day(r['last']) if pd.notna(r.get('last')) else '')]
    # A filing made public weeks after the trade (239 open-market rows over 30 sessions late, audit 23 Oct): the
    # period counts it on the day it was made public, so the row says how old the trade already was (on the row, not
    # only when opened: an investor reading "bought" must see that it is old news).
    late = (pd.Timestamp(r['last']) - pd.Timestamp(r['trade_to'])).days if pd.notna(r.get('last')) and pd.notna(r.get('trade_to')) else 0
    if late > 14:
        facts.append(('Filed late', f'last traded {kit.day(r["trade_to"])}, made public {late} days later'))
    move = ''
    if pd.notna(r.get('avg_price')) and r.get('avg_price'):
        f = float(split_since(pd.DataFrame({'isin': [isin], 'trade_date_to': [r.get('trade_to')]}), ctx.prices).iloc[0])
        if f == f and now:
            paid = r['avg_price'] * f
            facts.append(('Paid · now', f'{kit.price(paid)} · {kit.price(now)} ({(now / paid - 1) * 100:+.1f}%)'))
            move = f'{(now / paid - 1) * 100:+.1f}% since'
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
    when = kit.day(r['last'], with_year=False) if pd.notna(r.get('last')) else ''
    meta = ' · '.join(x for x in (when and f'public {when}', f'traded {late} days earlier' if late > 14 else '', move) if x)
    return (f'<details class="idea mv"><summary>'
            f'<div class="idea-co"><a href="{esc(href, quote=True)}" target="_self">{esc(str(r["company"]))}</a>{sym_line}</div>'
            f'<div class="mv-what"><p>{esc(r["sentence"])}</p>'
            + (f'<div class="mv-meta{" late" if late > 14 else ""}">{esc(meta)}</div>' if meta else '')
            + f'<div class="idea-chips">{_chips(r["kinds"], r.get("reads"), bool(r.get("big")) and r.get("kind") not in RAISE_KINDS)}</div></div>'
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


def _section_rows(ctx, g: pd.DataFrame, holding, px, more_href: str = '/filings-all') -> str:
    """A group as a table: the column heads once, SHOW rows, the rest up to PER_GROUP behind "Show more", then a link."""
    if g.empty:
        return ''
    recs = g.head(ideas.PER_GROUP).to_dict('records')
    first, rest = recs[:SHOW], recs[SHOW:]
    raise_kind = recs[0].get('kind') in RAISE_KINDS
    # The third column's head: the rows' own label when they share one (Own stake, Issue vs now), else "Context",
    # each cell then keeping its own small label (the label drifted row to row under one head, critique 12 Nov).
    labels = {r.get('kv3_label') if isinstance(r.get('kv3_label'), str) else 'Promoters' for r in recs}
    third = labels.pop() if len(labels) == 1 else 'Context'
    head = ('<div class="mv-h" aria-hidden="true"><span>Company</span><span>What happened</span><span>Value</span>'
            f'<span>{"New shares" if raise_kind else "Of company"}</span><span>{esc(third)}</span></div>')
    body = ''.join(_row(ctx, r, holding, px) for r in first)
    if rest:
        body += (f'<details class="mv-more"><summary>Show {len(rest)} more</summary>'
                 + ''.join(_row(ctx, r, holding, px) for r in rest) + '</details>')
    left = len(g) - len(recs)
    tail = (f'<p class="grp-more"><a href="{more_href}" target="_self">{left} more in Filings →</a></p>' if left > 0 else '')
    return f'<div class="ideas mv-t{" k3s" if third != "Context" else ""}">{head}{body}</div>{tail}'


def _group(df: pd.DataFrame, name: str, kinds: set | None = None, drop: set | None = None) -> pd.DataFrame:
    g = df[df['group'] == name] if not df.empty else df
    if g.empty:
        return g
    if kinds is not None:
        g = g[g['kind'].isin(kinds)]
    if drop is not None:
        g = g[~g['kind'].isin(drop)]
    return g


def _block(ctx, frames: dict, parts: list, holding, px, empty: str) -> int:
    """Groups under one question, each with its own small heading and count; returns how many groups had rows."""
    shown = 0
    for lst, name, label in parts:
        g = _group(frames[lst], name, drop=HOLDER_KINDS)
        if g.empty:
            continue
        shown += 1
        st.html(f'<div class="grp"><h3>{esc(label)}</h3><span>{kit.plural(len(g), "company", "companies")}</span></div>'
                + _section_rows(ctx, g, holding, px))
    if not shown and empty:
        kit.empty(empty)
    return shown


def _coming(ctx) -> pd.DataFrame:
    """The money events of the next COMING_DAYS days: meetings on fund raising or a buyback, tender closes, lock-ins ending."""
    _, up = filings_all._upcoming(ctx, ctx.ref, filings_all._names(ctx))
    if up.empty:
        return up
    day = pd.Timestamp(ctx.ref).normalize()
    up = up[(pd.to_datetime(up['made_public']) <= day + pd.Timedelta(days=COMING_DAYS))].sort_values('made_public', kind='stable')
    return filings_all._market(up, ctx)


def _calendar(coming: pd.DataFrame) -> str:
    """Coming up as a calendar: one column per day (at most CAL_DAYS), each event a line (company, what, size)."""
    if coming.empty:
        return ''
    coming = coming.assign(_d=pd.to_datetime(coming['made_public'], errors='coerce').dt.normalize()).dropna(subset=['_d'])
    cols = []
    for d, g in list(coming.groupby('_d', sort=True))[:CAL_DAYS]:
        items = []
        for r in g.head(CAL_PER_DAY).to_dict('records'):
            sym = r.get('nse_symbol')
            name = esc(str(r.get('company') or sym or ''))
            link = (f'<a href="{esc(kit.company_href(sym), quote=True)}" target="_self">{name}</a>' if isinstance(sym, str) and sym else f'<b>{name}</b>')
            size = kit.rupees(r['value']) if pd.notna(r.get('value')) and r.get('value') else ''
            items.append(f'<li>{link}<span>{esc(str(r.get("what") or ""))}' + (f' · {esc(size)}' if size else '') + '</span></li>')
        more = len(g) - CAL_PER_DAY
        if more > 0:
            items.append(f'<li class="cal-more"><a href="/filings-all" target="_self">{more} more →</a></li>')
        cols.append(f'<div class="cal-d"><h4>{esc(pd.Timestamp(d).strftime("%a %d %b"))}</h4><ul>{"".join(items)}</ul></div>')
    return f'<div class="cal">{"".join(cols)}</div>'


def _headline(look: pd.DataFrame, warn: pd.DataFrame, breadth: dict | None, span: str, ref) -> str:
    """The page's first line is the news, in rupees (Redesign 12 Nov, after tipsheet.markets' "The Nifty 50 rose
    0.8%"): what insiders bought and sold, in how many companies, then the buying share against the period before.
    Counts of companies across every kind of filing (372 with money in) said nothing a reader could act on."""
    nb, ns = len(_group(look, 'Insiders buying')), len(_group(warn, 'Insiders selling'))
    bought, sold = _value(look, 'Insiders buying'), _value(warn, 'Insiders selling')
    if not nb and not ns:
        lead = 'No insider bought or sold past the bar'
    else:
        b = (f'Insiders bought <b class="up">{esc(kit.rupees(bought))}</b> in {kit.plural(nb, "company", "companies")}' if nb
             else 'No insider bought past the bar')
        x = (f'sold <b class="down">{esc(kit.rupees(sold))}</b> in {ns}' if ns else 'none sold past the bar')
        lead = f'{b}; {x}'
    sub = []
    if breadth and breadth.get('buy_share') is not None:
        before = breadth.get('before') or {}
        prev = f', against {before["buy_share"]:.0f}% the period before' if before.get('buy_share') is not None else ''
        sub.append(f'Buying was {breadth["buy_share"]:.0f}% of the rupees decision-makers traded on the market{prev}.')
    top = _group(look, 'Insiders buying')
    if not top.empty:
        lead_row = top.iloc[0]
        if isinstance(lead_row['sentence'], str) and lead_row['sentence']:
            sub.append(f'First on the list, {lead_row["company"]}: {lead_row["sentence"].rstrip(".")}.')
    return (f'<div class="mast"><div class="kicker">{esc(kit.sentence(span))} to {kit.day(ref)} · open-market trades by promoters, '
            f'directors and key staff</div><h1 class="news">{lead}</h1>'
            + ''.join(f'<p class="dek">{esc(x)}</p>' for x in sub if x) + '</div>')


def render():
    ctx = load()
    if not need_data(ctx):
        return
    key = str(ctx.ref)
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

    # The masthead: the news on the left; the period and one "Filters & sort" on the right (the company search is the
    # top bar's; a second search box and eleven group pills sat above the first company, critique 12 Nov).
    mast, ctl = st.columns([3, 1.3], vertical_alignment='top')
    with ctl:
        period = st.segmented_control('Period', list(ideas.PERIODS), default=DEFAULT_PERIOD, key='td_period',
                                       label_visibility='collapsed', width='content') or DEFAULT_PERIOD
        with st.popover('Filters & sort', icon=':material/tune:', width='content'):
            text = st.text_input('Company or symbol', key='td_text', placeholder='Search company or symbol')
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
    days = ideas.PERIODS[period]
    span = 'today' if days == 1 else period.lower()
    breadth = ideas.insider_breadth(ctx.eligible, ctx.ref, max(days, 7))
    with mast:
        st.html(_headline(look, warn, breadth, span, ctx.ref))

    # The reading line: one small number per question, in the order the page answers them (no six tall tiles).
    cl, cw = _counts(look), _counts(warn)
    n = lambda d, k: d.get(k, 0)   # noqa: E731
    deals_in, deals_out = len(_group(look, 'Big investors and funds in', drop=HOLDER_KINDS)), len(_group(warn, 'Big investors and funds out', drop=HOLDER_KINDS))
    cells = [('Insiders buying', n(cl, 'Insiders buying'), 'up', 'companies'), ('Insiders selling', n(cw, 'Insiders selling'), 'down', 'companies'),
             ('Promoters pay up', n(cl, 'Promoters pay up'), '', f'{n(cw, "Cheap shares to promoters")} below market'),
             ('Pledges up', n(cw, 'Pledges'), '', f'{n(cl, "Pledges released")} released'),
             ('Raises · buybacks', n(cl, 'Raises') + n(cl, 'Buybacks at a premium'), '', 'allotted or open'),
             ('Funds in · out', f'{deals_in} · {deals_out}', '', 'bulk/block deals, 5% holders')]
    st.html('<div class="reads">' + ''.join(
        f'<div><span class="k">{esc(k)}</span><b class="{t}">{esc(str(v))}</b><span class="s">{esc(sub)}</span></div>'
        for k, v, t, sub in cells) + '</div>')

    frames = {'look': look, 'warn': warn}
    # One column, in the order the evidence supports (docs/SIGNALS.md: insider buying is the only measured edge; sales
    # are the catch, not a short signal; pledges and cheap issues are avoid flags; funds' deals lagged the index).
    with kit.card('Who among insiders is putting money in?', 'td_in', SORTS[order][1] + ' · open-market only, ESOPs and gifts left out'):
        _block(ctx, frames, [('look', 'Insiders buying', 'Insiders buying'), ('look', 'Promoters pay up', 'Promoters paying cash for new shares')],
               holding, px, 'No insider bought past the bar in this period.')
    with kit.card('Who is taking money out?', 'td_out', 'sales are the catch to know, not a signal to sell (no edge measured)'):
        _block(ctx, frames, [('warn', 'Insiders selling', 'Insiders selling')], holding, px, 'No insider sold past the bar in this period.')
    with kit.card('What could go wrong?', 'td_risk', 'pledges and cheap shares to promoters are avoid flags in published studies'):
        _block(ctx, frames, [('warn', 'Pledges', 'Pledges up or invoked'), ('warn', 'Cheap shares to promoters', 'Cheap shares to promoters'),
                             ('look', 'Pledges released', 'Pledges released')], holding, px, 'No new pledges or cheap issues in this period.')
    if n(cl, 'Raises') or n(cl, 'Buybacks at a premium'):
        with kit.card('Who is raising or returning money?', 'td_raise', 'shares issued are dilution: neutral, not a verdict'):
            _block(ctx, frames, [('look', 'Raises', 'Capital raised'), ('look', 'Buybacks at a premium', 'Buybacks at a premium')], holding, px, '')

    # Funds and big holders: in and out side by side (two things compared). Their deals lagged the index in our data,
    # so they come after the insiders. The quarterly holding changes are dated by the quarter, not the day: kept, but
    # apart and folded, so a 30 Sep shareholding filing does not read as this week's news (346 "in" were mostly these).
    with kit.card('What are funds and big investors doing?', 'td_funds', 'bulk and block deals (market makers left out) and 5% holders'):
        cin, cout = st.columns(2, gap='medium')
        with cin:
            _block(ctx, frames, [('look', 'Big investors and funds in', 'Buying')], holding, px, 'No fund or big investor bought past the bar.')
        with cout:
            _block(ctx, frames, [('warn', 'Big investors and funds out', 'Selling')], holding, px, 'No fund or big investor sold past the bar.')
        hin = _group(look, 'Big investors and funds in', kinds=HOLDER_KINDS)
        hout = _group(warn, 'Big investors and funds out', kinds=HOLDER_KINDS)
        if len(hin) or len(hout):
            with st.expander(f'Quarterly holding changes by mutual funds and foreign investors · {len(hin)} up, {len(hout)} down '
                             '(dated by the quarter, not the day)'):
                a, b = st.columns(2, gap='medium')
                with a:
                    st.html('<div class="grp"><h3>Adding</h3></div>' + _section_rows(ctx, hin, holding, px, '/investors'))
                with b:
                    st.html('<div class="grp"><h3>Trimming</h3></div>' + _section_rows(ctx, hout, holding, px, '/investors'))
        st.html('<p class="grp-more"><a href="/investors" target="_self">Every fund and big investor →</a></p>')

    # What is next: meetings on fund raising or a buyback, tender closes, lock-ins ending (a meeting is not a raise
    # until its outcome is filed), as a calendar, one column a day.
    coming = _coming(ctx)
    with kit.card('What is coming up?', 'td_up', f'the next {COMING_DAYS} days · a meeting is not a raise until its outcome is filed'):
        if coming.empty:
            kit.empty(f'No money events in the next {COMING_DAYS} days.')
        else:
            st.html(_calendar(coming))

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
                '<li>Each tag carries its measured read on our history (Evidence page): Ahead, Behind, No edge, Few cases or '
                'Not measured. Evidence is a tag, never a filter</li>'
                '</ul><a class="bar-all" href="/filings-all" target="_self">Every filing &rarr;</a>')
