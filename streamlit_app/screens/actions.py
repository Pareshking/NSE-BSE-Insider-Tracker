"""Actions: what deserves a look now, pulled from every filing we read.

Short lists, strongest first, and only the ones that have rows. Each list says
in one line how that kind of signal has done against Nifty 500 in our own data
(insiders_clean/evidence.py, from the measured track record), so a reader can
weigh it. Nothing here is a forecast or a recommendation."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from data import store
from ui import kit
from ui.kit import esc

from insiders_clean import actions, evidence, signals
from screens.capital_raises import lock_in_calendar
from screens.ctx import load, need_data, with_flags, with_prices

ROWS = 6
LOCK_AHEAD_DAYS = 60
MEETING_AHEAD_DAYS = 14
MEETING_FLAGS = ['fund_raising', 'preferential', 'buyback', 'rights']


def _evidence_line(summ: pd.DataFrame, signal: str, extra: str = '') -> None:
    v = evidence.verdict(summ, signal)
    st.html(f'<p class="evl">{kit.tag(v["tag"], v["tone"])} {esc(v["text"])}{" " + esc(extra) if extra else ""}</p>')


def _section(title: str, key: str, aside: str, rows: pd.DataFrame, cols: list, summ: pd.DataFrame,
             signal: str | None = None, extra: str = '', note: str = '') -> bool:
    """One card, drawn only when it has rows. True when drawn."""
    if rows is None or rows.empty:
        return False
    with kit.card(title, key, aside):
        if signal:
            _evidence_line(summ, signal, extra)
        elif note:
            st.html(f'<p class="evl">{esc(note)}</p>')
        kit.table(with_flags(rows.head(ROWS)), cols, limit=ROWS, height=ROWS * 56 + 52)
    return True


def _prices(rows: pd.DataFrame, ctx) -> pd.DataFrame:
    return with_prices(rows, ctx.prices) if not rows.empty else rows


def _meetings(ctx, ref: pd.Timestamp) -> pd.DataFrame:
    m = ctx.meetings
    if m.empty:
        return pd.DataFrame()
    m = m.copy()
    m['meeting_date'] = pd.to_datetime(m['meeting_date'], errors='coerce')
    flags = [c for c in MEETING_FLAGS if c in m]
    if not flags:
        return pd.DataFrame()
    soon = m[(m['meeting_date'] >= ref.normalize()) & (m['meeting_date'] <= ref.normalize() + pd.Timedelta(days=MEETING_AHEAD_DAYS))]
    soon = soon[soon[flags].astype('boolean').fillna(False).any(axis=1)]
    soon = soon.assign(nse_symbol=soon['symbol'],
                       what=soon['purposes'].str.replace('_', ' ').str.replace(',', ', ').str.capitalize())
    return soon.sort_values('meeting_date')


def render():
    ctx = load()
    kit.head('Actions', 'What deserves a look now, from every filing we read. Each list gives the reason it matters, and '
                        'an early read of how that kind of filing has done against Nifty 500.')
    if not need_data(ctx):
        return
    ref = ctx.ref
    summ = store.artifact('artifacts/track_summary.parquet')
    kit.caption(f'Filings up to {kit.day(ref)}. Lists show the last 30 days unless they say otherwise.')
    drawn = []

    # --- worth a look: buying with real money -------------------------------------------------
    cl = signals.clusters(ctx.eligible, ref)
    cl = _prices(cl.head(ROWS), ctx)
    # Under the company: e.g. '4 buyers, 2 decision-makers: promoter group (3), director'.
    drawn.append(_section('Several insiders buying together', 'act_cluster', 'last 30 days · a promoter group counts once', cl, [
        kit.Col('company', 'Company', 'co', sub='who'),
        kit.Col('decision_makers', 'Deciders', 'num', help='Distinct decision-makers: the promoter group counts once '
                '(linked through the shareholding pattern), each director or KMP once'),
        kit.Col('value', 'Bought', 'money'), kit.Col('pct_of_mcap', '% of mcap', 'pct'),
        kit.Col('last_seen', 'Last filed', 'date'), kit.Col('range', '52W range · price', 'range', phone=False)],
        summ, 'cluster'))

    who = [kit.Col('company', 'Company', 'co'), kit.Col('person_name', 'Who', 'person'),
           kit.Col('value_30d', 'Bought', 'money'), kit.Col('pct_30d', '% of mcap', 'pct'),
           kit.Col('last_seen', 'Last filed', 'date'), kit.Col('range', '52W range · price', 'range', phone=False)]
    prom = _prices(actions.buying(ctx.eligible, ref, signals.PROMOTER_ROLES, ROWS), ctx)
    drawn.append(_section('Promoters buying', 'act_prom', 'open market, ₹25 L and up counted as real buying',
                          prom, who, summ, 'promoter_buy'))
    off = _prices(actions.buying(ctx.eligible, ref, ('director', 'kmp'), ROWS), ctx)
    drawn.append(_section('Directors and KMP buying', 'act_off', 'open market', off, who, summ, 'officer_buy'))

    allbuy = actions.buying(ctx.eligible, ref, signals.PROMOTER_ROLES + ('director', 'kmp'), 60)
    if not allbuy.empty and not ctx.prices.empty:
        allbuy = _prices(allbuy, ctx)
        off = pd.to_numeric(allbuy['pct_off_high'], errors='coerce')
        allbuy = allbuy[off <= -0.25].head(ROWS)
    else:
        allbuy = pd.DataFrame()
    drawn.append(_section('Insiders buying after a big fall', 'act_dip', 'price 25% or more below its 52-week high', allbuy, who, summ,
                          note='People who know the business paying up while the price is down is the case worth a closer look. '
                               'It can also mean the business is in trouble: read the filings first. Not measured on our data.'))

    # --- caution ---------------------------------------------------------------------------------
    sold = actions.selling(ctx.eligible, ref, signals.PROMOTER_ROLES, limit=ROWS)
    drawn.append(_section('Promoters selling', 'act_sell', 'open market, ₹25 L and up', sold, [
        kit.Col('company', 'Company', 'co'), kit.Col('person_name', 'Who', 'person'),
        kit.Col('value', 'Sold', 'money'), kit.Col('pct_of_mcap', '% of mcap', 'pct'),
        kit.Col('last_seen', 'Last filed', 'date')], summ, 'promoter_sell'))

    pl = actions.pledged(ctx.shareholding, ctx.securities, limit=ROWS)
    drawn.append(_section('Heavily pledged promoters', 'act_pledge', f'more than {signals.HIGH_PLEDGE_PCT:.0f}% of their shares', pl, [
        kit.Col('company', 'Company', 'co'), kit.Col('promoter_pledge_pct', 'Pledged', 'pct', help="% of the promoters' own shares"),
        kit.Col('promoter_holding_pct', 'Promoters hold', 'pct'), kit.Col('quarter_end', 'Quarter', 'date', phone=False)],
        summ, note='Not measured on our data. Published studies treat heavy pledging as a crash-risk warning.'))

    funds = signals.small_cap_accumulation(ctx.deals, ref, 30)
    funds = funds.head(ROWS) if not funds.empty else funds
    drawn.append(_section('Funds net buying small caps', 'act_funds', 'bulk and block deals, companies under ₹5,000 Cr', funds, [
        kit.Col('company', 'Company', 'co'), kit.Col('net_buyers', 'Buyers', phone=False),
        kit.Col('net_value', 'Net bought', 'money'), kit.Col('net_pct', '% of mcap', 'pct'), kit.Col('last', 'Last deal', 'date')],
        summ, 'fund_deal_buy', 'Shown so you can see where the crowd went, not as a buy list.'))

    # --- dates ahead -----------------------------------------------------------------------------
    cal = lock_in_calendar(ctx.preferential, ctx.prices, ref, store.table('preferential_lockins'))
    if not cal.empty:
        cal = cal[(cal['days_left'] >= 0) & (cal['days_left'] <= LOCK_AHEAD_DAYS)]
    drawn.append(_section('Shares about to come off lock-in', 'act_lock', f'next {LOCK_AHEAD_DAYS} days', cal, [
        kit.Col('expires', 'Free from', 'date'), kit.Col('days_left', 'Days', 'num'), kit.Col('company', 'Company', 'co'),
        kit.Col('what', 'Lock-in'), kit.Col('shares', 'Shares', 'shares', phone=False),
        kit.Col('at_market', 'At market now', 'money', phone=False)],
        summ, note='Lock-in lines as the company filed them, else the rule: 18 months for promoters, 6 for others. Not measured on our data.'))

    mt = _meetings(ctx, ref)
    drawn.append(_section('Boards meeting on fund raising or a buyback', 'act_meet', f'next {MEETING_AHEAD_DAYS} days', mt, [
        kit.Col('meeting_date', 'Meeting', 'date'), kit.Col('company', 'Company', 'co'), kit.Col('what', 'To consider')],
        summ, note='A meeting is not a decision. Not measured on our data.'))

    if not any(drawn):
        kit.empty('Nothing to act on in the data yet.')
        return
    kit.caption('The evidence line is what happened to stocks after this kind of filing in our own one year of data: median '
                'return over Nifty 500 after costs, with the number of cases. Windows overlap and one year is one market, '
                'so read it as a hint, not proof. Weigh the size of the buy against the company, who is buying, and that filings reach you about two days after the trade. The full table is on Track record.')
