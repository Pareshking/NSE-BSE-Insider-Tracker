"""The site's pages, redesign of 12 Nov 2026 (owner: "redesign it from blank ... 5W-2H, insights clearly there ... no
mental calculation ... club what is not worth showing ... reduce clicks"; free to add pages).

Every page is one question, in the same order: a masthead whose headline is the news, a strip of numbers, the stories
(each with who, what, when, where, how, how much, price, why it matters and what to watch in sight), and a "left out"
box that counts and sums the noise. The front page (Today) shows the top of every topic page, each with "See all".
Content comes from screens/moves.py; looks from ui/ds.py and ui/theme.py.
"""
from __future__ import annotations

import streamlit as st
from data import store
from ui import ds, kit
from ui.kit import esc

from insiders_clean import evidence, ideas
from screens import moves
from screens.ctx import load, need_data

PERIODS = {'Today': 1, '7 days': 7, '30 days': 30, '90 days': 90}
DEFAULT = '30 days'
PREVIEW = 3       # stories per topic on the front page
SHORTLIST = 6     # Worth a look now

RAISE_KINDS = {'QIP', 'Preferential to others', 'Rights issue', 'Promoters pay up', 'Buyback at a premium'}
RISK_KINDS = {'Pledge created', 'Pledge rising', 'Pledge invoked', 'Cheap shares to promoters'}
RELEASE_KINDS = {'Pledge released'}
HOLDER_KINDS = {'Mutual funds adding', 'Foreign investors adding', 'Mutual funds trimming', 'Foreign investors trimming'}
STAKE_KINDS = {'Big investor in', 'Big investor out'}


def _period(key: str) -> tuple[str, int]:
    with st.container(key='ds_ctl', horizontal=True):
        p = st.segmented_control('Period', list(PERIODS), default=DEFAULT, key=key, label_visibility='collapsed') or DEFAULT
    return p, PERIODS[p]


def _span(p: str, ref) -> str:
    return ('the latest session' if p == 'Today' else f'the last {p}') + f', to {kit.day(ref)}'


def _ctx():
    ctx = load()
    return ctx if need_data(ctx) else None


def _record_line(kinds: list[str], summary) -> str:
    out = []
    for k in kinds:
        txt, kind = moves.record(k, summary)
        if txt:
            out.append(f'<b>{esc(k)}:</b> {esc(txt)}')
    return '<br>'.join(out)


# ---- Today: the front page, the top of every topic ---------------------------------------------------------------

def today():
    ctx = _ctx()
    if ctx is None:
        return
    key = str(ctx.ref)
    top, ctl = st.columns([4, 1.4], vertical_alignment='bottom')
    with ctl:
        p, days = _period('pg_today')
    buys, _, bs = moves.insiders(ctx, key, 'BUY', days)
    sells, _, ss = moves.insiders(ctx, key, 'SELL', days)
    dls, _, ds_ = moves.deals(ctx, key, days)
    ev = moves.events(ctx, key, days)
    summary = store.artifact('artifacts/track_summary.parquet')
    raises = moves.event_stories(ctx, ev, RAISE_KINDS, summary)
    risks = moves.event_stories(ctx, ev, RISK_KINDS, summary)
    owners = moves.event_stories(ctx, ev, STAKE_KINDS | HOLDER_KINDS, summary)
    b = ideas.insider_breadth(ctx.eligible, ctx.ref, max(days, 7))
    with top:
        if bs['n'] or ss['n']:
            title = (f'Insiders bought <b class="up">{esc(kit.rupees(bs["value"]))}</b> in {kit.plural(bs["companies"], "company", "companies")}'
                     f' and sold <b class="down">{esc(kit.rupees(ss["value"]))}</b> in {ss["companies"]}')
        else:
            title = 'No promoter, director or KMP traded past the bar'
        dek = []
        if b and b.get('buy_share') is not None:
            prev = (b.get('before') or {}).get('buy_share')
            dek.append(f'Buying was {b["buy_share"]:.0f}% of the rupees they traded on the market'
                       + (f', against {prev:.0f}% in the period before.' if prev is not None else '.'))
        firm = [s for s in buys if getattr(s, 'verdict', '') == 'leaning_positive']
        if firm:
            dek.append(f'{kit.plural(len(firm), "buy")} of a kind that has beaten Nifty 500 on our history; the largest: {firm[0].company}, {firm[0].big}.')
        ds.head(f'{esc(_span(p, ctx.ref))} · open-market trades, deals, raises and filings', title, dek)
    ds.stats([('Insiders buying', bs['n'], kit.rupees(bs['value']), 'up', '/insiders'),
              ('Insiders selling', ss['n'], kit.rupees(ss['value']), 'down', '/insiders'),
              ('Big deals', ds_['n'], kit.rupees(ds_['value']), '', '/deals'),
              ('Raises · buybacks', len(raises), 'allotted, listed or open', '', '/raises'),
              ('Risks', len(risks), 'pledges and cheap issues', '', '/risks'),
              ('Big holders', len(owners), '5% holders and funds', '', '/ownership')])

    ds.section('Worth a look now', 'Insider buys of a kind that has beaten Nifty 500 on our own history, largest first', '/insiders', 'Every insider trade')
    kinds = ['Promoter buying', 'Director or KMP buying']
    ds.record(_record_line([k for k in kinds if any(getattr(s, 'verdict', '') == 'leaning_positive' for s in firm)], summary)
              + ('<br>' if firm else '') + 'Costs deducted; the clock starts when the exchange made the filing public.' if firm else '')
    ds.stories(firm[:SHORTLIST], 'No insider buy of a kind with a measured edge in this period. The lists below are facts to read, not picks.')

    for title, sub_, items, href in (
            ('Who is selling?', 'Promoters, and directors or KMP at ₹25 Cr and up: the catch to know, not a sell signal', sells, '/insiders'),
            ('Who sold, who took it?', 'Bulk and block deals, both sides as one deal; market makers left out', dls, '/deals'),
            ('Who is raising or returning money?', 'Preferential issues, QIPs, rights, buybacks', raises, '/raises'),
            ('What could go wrong?', 'Pledges up or invoked, cheap shares to promoters', risks, '/risks'),
            ('Who are the big holders moving?', '5% holders (SAST) and quarterly fund moves', owners, '/ownership')):
        ds.section(title, sub_, href, f'All {len(items)}' if len(items) > PREVIEW else 'Open the page')
        ds.stories(items[:PREVIEW], 'Nothing past the bar in this period.')
    ds.section('What is coming up?', 'The next 10 days: fund-raising and buyback meetings, tender closes, lock-ins ending', '/calendar', '60 days')
    cal = moves.upcoming(ctx, 10)
    if cal:
        ds.calendar(cal)
    else:
        ds.empty('No money events in the next 10 days.')


# ---- Topic pages ----------------------------------------------------------------------------------------------------

def insiders():
    ctx = _ctx()
    if ctx is None:
        return
    key = str(ctx.ref)
    top, ctl = st.columns([4, 1.4], vertical_alignment='bottom')
    with ctl:
        p, days = _period('pg_ins')
    buys, club_b, bs = moves.insiders(ctx, key, 'BUY', days)
    sells, club_s, ss = moves.insiders(ctx, key, 'SELL', days)
    summary = store.artifact('artifacts/track_summary.parquet')
    with top:
        ds.head(f'Insider trades · {esc(_span(p, ctx.ref))}',
                (f'{kit.plural(bs["n"], "decision")} to buy, <b class="up">{esc(kit.rupees(bs["value"]))}</b>; '
                 f'{kit.plural(ss["n"], "decision")} to sell, <b class="down">{esc(kit.rupees(ss["value"]))}</b>')
                if bs['n'] or ss['n'] else 'No promoter, director or KMP traded past the bar',
                ['One line per promoter group, director or KMP and company: their open-market trades in the period added up. '
                 'Staff trades, ESOPs, gifts and transfers are counted at the foot, not listed.'])
    ds.stats([('Buyers', bs['companies'], 'companies', 'up'), ('Bought', kit.rupees(bs['value']), 'on the market', 'up'),
              ('Sellers', ss['companies'], 'companies', 'down'), ('Sold', kit.rupees(ss['value']), 'on the market', 'down'),
              ('Measured ahead', sum(1 for s in buys if getattr(s, 'verdict', '') == 'leaning_positive'), 'of the buys')])
    ds.section('Who is buying?', 'Largest first')
    ds.record(_record_line(['Promoter buying', 'Director or KMP buying'], summary))
    ds.stories(buys, 'No insider bought past the bar in this period.')
    ds.club('Left out as noise', club_b)
    ds.section('Who is selling?', 'Promoters past the same bar; directors and KMP at ₹25 Cr and up')
    ds.record(_record_line(['Promoter selling'], summary))
    ds.stories(sells, 'No insider sold past the bar in this period.')
    ds.club('Left out as noise', club_s)


def deals():
    ctx = _ctx()
    if ctx is None:
        return
    top, ctl = st.columns([4, 1.4], vertical_alignment='bottom')
    with ctl:
        p, days = _period('pg_deals')
    items, club, s = moves.deals(ctx, str(ctx.ref), days)
    with top:
        ds.head(f'Bulk and block deals · {esc(_span(p, ctx.ref))}',
                f'{kit.plural(s["n"], "big deal")} in {kit.plural(s["companies"], "company", "companies")}, <b>{esc(kit.rupees(s["value"]))}</b>',
                ['Each deal once, with who sold and who took it. Shown at 0.25% of the company or ₹25 Cr and up.'])
    prom = sum(1 for x in items if any(t == 'Promoter sold' for t, _ in x.tags))
    ds.stats([('Deals', s['n'], 'past the bar'), ('Value', kit.rupees(s['value']), 'the larger side of each'),
              ('Promoters sold', prom, 'of these deals', 'down' if prom else '')])
    ds.section('Who sold, who took it?', 'Largest first; a fund manager filing under many fund names is listed under each name')
    ds.stories(items, 'No deal past the bar in this period.')
    ds.club('Left out as noise', club)


def _events_page(key: str, title: str, question: str, kinds: set, note: str, extra: list | None = None):
    ctx = _ctx()
    if ctx is None:
        return
    top, ctl = st.columns([4, 1.4], vertical_alignment='bottom')
    with ctl:
        p, days = _period(key)
    ev = moves.events(ctx, str(ctx.ref), days)
    summary = store.artifact('artifacts/track_summary.parquet')
    items = moves.event_stories(ctx, ev, kinds, summary)
    counts = ev['kind'].value_counts().to_dict() if not ev.empty else {}
    with top:
        ds.head(f'{title} · {esc(_span(p, ctx.ref))}', f'{kit.plural(len(items), "filing")} past the bar', [note])
    ds.stats([(k, counts.get(k, 0), '') for k in sorted(kinds) if counts.get(k)] or [('Filings', 0, 'in this period')])
    ds.section(question, 'Largest share of the company first')
    ds.stories(items, 'Nothing past the bar in this period.')
    for t, q, ks in extra or []:
        more = moves.event_stories(ctx, ev, ks, summary)
        ds.section(q, t)
        ds.stories(more, 'Nothing in this period.')


def raises():
    _events_page('pg_raise', 'Raises and buybacks', 'Who is raising or returning money?', RAISE_KINDS,
                 'Promoters paying up, cheap issues, QIPs, preferential issues to others, rights issues and tender buybacks, '
                 'allotted or listed (an approval is not a raise). Shares issued are dilution: neutral unless the price says otherwise.')


def risks():
    _events_page('pg_risk', 'Risks', 'What could go wrong?', RISK_KINDS,
                 'Promoter pledges created, rising or invoked, and shares issued to promoters below the market price.',
                 [('Pledges reduced in the period', 'What got safer?', RELEASE_KINDS)])


def ownership():
    _events_page('pg_own', 'Big holders', 'Who crossed 5% or moved 2%?', STAKE_KINDS,
                 'Outside holders crossing 5% or moving 2% or more (SAST filings), and mutual funds and foreign investors moving 1 point '
                 'or more of a company in the latest quarter (shareholding filings, dated by the quarter).',
                 [('Quarter-end shareholding filings, not trades this period', 'How did funds change their holdings?', HOLDER_KINDS)])


def calendar():
    ctx = _ctx()
    if ctx is None:
        return
    cal = moves.upcoming(ctx, 60)
    n = sum(len(i) for _, i in cal)
    ds.head(f'Calendar · from {kit.day(ctx.ref)}', f'{kit.plural(n, "money event")} in the next 60 days',
            ['Board meetings that will consider fund raising or a buyback, tender offers closing, and lock-ins ending. '
             'A meeting is not a raise until its outcome is filed.'])
    ds.section('What is coming up?', 'By day')
    if cal:
        ds.calendar(cal)
    else:
        ds.empty('No money events in the next 60 days.')


def evidence_note(summary) -> str:   # kept small: the Evidence page has the full record
    return evidence.CAVEAT
