"""Today (home, redesign of 21 Oct 2026): two short lists across the whole market, from
insiders_clean/ideas.py. Worth a look: at most 10 companies where promoters, directors,
big investors or funds put money in at a size that matters, promoters paid up for new
shares, a pledge was released or a buyback is priced well above the market. Watch out: at
most 5 where promoters sold, pledged more or took cheap shares, or a big investor or the
funds left. One row per company: one sentence, three numbers, the reasons as chips; it
opens to the facts and links. Everything else is in Filings."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from data import store
from ui import kit
from ui.kit import esc

from insiders_clean import ideas, signals
from screens import buybacks
from screens.ctx import issue_rows, load, need_data, split_since

READ = {'leaning_positive': 'ahead', 'drag': 'behind', 'no_edge': 'no edge', 'few': 'few cases', 'not_measured': 'not measured'}
WARN_KINDS = {'Promoter selling', 'Pledge created', 'Pledge rising', 'Cheap shares to promoters', 'Big investor out', 'Funds selling'}


def _num(label: str, value: str) -> str:
    return f'<div class="kv"><span>{esc(label)}</span><b>{esc(value)}</b></div>'


def _chips(kinds, reads) -> str:
    out = []
    for k in kinds:
        tone = 'sell' if k in WARN_KINDS else 'mute' if k == 'Steady accumulation' else 'acc'
        read = READ.get((reads or {}).get(k, ''), '')
        out.append(f'<span class="chip {tone}">{esc(k)}' + (f' · {esc(read)}' if read else '') + '</span>')
    return ''.join(out)


def _row(ctx, r, holding) -> str:
    isin = r['isin']
    pr = ctx.prices[ctx.prices['isin'] == isin] if not ctx.prices.empty else ctx.prices
    pr = pr.iloc[0] if len(pr) else None
    now = pr['latest_close'] if pr is not None and pd.notna(pr.get('latest_close')) else None
    s = holding.get(isin)
    href = kit.company_href(r['nse_symbol'])
    pct = r.get('pct_of_company')
    nums = [_num('Of the company', f'{pct:.2f}%' if pd.notna(pct) and pct else '—'),
            _num('Value', kit.rupees(r['value']) if pd.notna(r.get('value')) and r.get('value') else '—'),
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
    if pr is not None and pd.notna(pr.get('market_cap')):
        facts.append(('Market cap', kit.rupees(pr['market_cap'])))
    grid = ''.join(f'<div><b>{esc(k)}</b><span>{esc(v)}</span></div>' for k, v in facts if v)
    also = ''.join(f'<li>{esc(x)}</li>' for x in (r.get('others') or []))
    return (f'<details class="idea"><summary>'
            f'<div class="idea-co"><a href="{esc(href, quote=True)}" target="_self">{esc(str(r["company"]))}</a>'
            f'<p>{esc(r["sentence"])}</p><div class="idea-chips">{_chips(r["kinds"], r.get("reads"))}</div></div>'
            f'{"".join(nums)}</summary>'
            f'<div class="idea-more">' + (f'<ul class="idea-also">{also}</ul>' if also else '')
            + f'<div class="idea-grid">{grid}</div><a href="{esc(href, quote=True)}" target="_self">Company page →</a></div></details>')


def render():
    ctx = load()
    kit.head('Today', 'What people with skin in the game did that matters, across every listed company.')
    if not need_data(ctx):
        return
    summary = store.artifact('artifacts/track_summary.parquet')
    ref, sh = ctx.ref, ctx.shareholding
    issues = issue_rows(ctx.preferential, ctx.prices) if ctx.preferential is not None and not ctx.preferential.empty else None
    bb = buybacks.rows(store.table('buybacks'), ctx.prices)
    look, warn = ideas.today([
        ideas.insider_events(ctx.eligible, ref, sh, summary), ideas.pledge_events(ctx.trades, ref, sh),
        ideas.stake_events(ctx.sast, ref), ideas.fund_events(ctx.deals, ctx.trades, ref),
        ideas.issue_events(issues, ref, sh), ideas.buyback_events(bb, ref, sh)], summary)
    latest = signals.latest_shareholding(sh)
    holding = ({i: r for i, r in zip(latest['isin'], latest.to_dict('records'))} if not latest.empty else {})

    with kit.card('Worth a look', 'td_look', f'{ideas.WINDOW} days to {kit.day(ref)} · top {ideas.MAX_IDEAS} by share of the company'):
        if look.empty:
            kit.empty('Nothing has passed the bar in the last 90 days.')
        else:
            st.html('<div class="ideas">' + ''.join(_row(ctx, r, holding) for r in look.to_dict('records')) + '</div>')
    with kit.card('Watch out', 'td_warn', f'top {ideas.MAX_WARNINGS} by share of the company'):
        if warn.empty:
            kit.empty('No promoter selling, pledging or cheap shares past the bar.')
        else:
            st.html('<div class="ideas">' + ''.join(_row(ctx, r, holding) for r in warn.to_dict('records')) + '</div>')
    st.html(f'<p class="quiet">The bar: per decision-maker over {ideas.WINDOW} days, ₹{ideas.MIN_VALUE / 1e5:.0f} L and '
            f'{ideas.MIN_PCT:g}% of the company, or {ideas.ALONE_PCT:g}% alone, or buying on {ideas.STEADY_DAYS}+ days; '
            f'stakes of {ideas.BIG_STAKE:g}% or changes of {ideas.BIG_CHANGE:g}%+; funds net {ideas.FUND_NET_PCT:g}%+ in 30 days. '
            '<a href="/filings-all" target="_self">Every filing →</a></p>')
