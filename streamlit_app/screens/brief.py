"""Morning brief (docs/TODO.md item 9): what the last session's filings
brought, read before the 09:15 IST open, and warnings on a watchlist.

The nightly run (18:00 UTC, 23:30 IST) has cleaned the day's filings by the
morning. The watchlist is never in the repo (it is public): it comes from
Streamlit secrets (`watchlist = ["TCS", "INFY"]`) and/or the page address
(`?watch=TCS,INFY`, so a bookmark keeps it). A warning is raised when, in the
last WARN_DAYS days, an insider of a watched company sold on the open market,
pledged shares, or promoters were allotted shares below today's price."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from ui import kit

from insiders_clean import actions, signals
from data import store
from screens.capital_raises import issue_rows, lock_in_calendar
from screens.ctx import load, need_data, with_flags, with_prices

WARN_DAYS = 7
SOON_DAYS = 7


def _watchlist() -> list[str]:
    names = []
    try:
        w = st.secrets.get('watchlist', [])
        names += [w] if isinstance(w, str) else list(w)
    except Exception:  # noqa: BLE001 -- no secrets file at all
        pass
    names += str(st.query_params.get('watch', '')).split(',')
    out = []
    for n in names:
        for part in str(n).split(','):
            s = part.strip().upper()
            if s and s not in out:
                out.append(s)
    return out


def _warnings(ctx, watch: list[str], since: pd.Timestamp) -> pd.DataFrame:
    """One row per warning: company, what, who, value, day."""
    sym = lambda df, col='nse_symbol': df[col].astype(str).str.upper().isin(watch) if col in df else False  # noqa: E731
    rows = []
    t = ctx.trades
    if not t.empty:
        t = t[sym(t) & t['is_primary'].astype('boolean').fillna(False)]
        seen = pd.to_datetime(t['broadcast_date'], errors='coerce')
        t = t.assign(seen=seen)[seen >= since]
        sold = t[t['is_market'].astype('boolean').fillna(False) & (t['side'] == 'SELL')]
        for r in sold.itertuples():
            rows.append({'nse_symbol': r.nse_symbol, 'company': r.company, 'what': f'{kit.role(r.person_role)} sold on the market',
                         'who': r.person_name, 'value': r.value, 'day': r.seen})
        pl = t[t['kind'] == 'pledge_create']
        for r in pl.itertuples():
            rows.append({'nse_symbol': r.nse_symbol, 'company': r.company, 'what': 'Shares pledged',
                         'who': r.person_name, 'value': r.value, 'day': r.seen})
    p = ctx.preferential
    if p is not None and not p.empty and 'symbol' in p:
        iss = issue_rows(p[sym(p, 'symbol')], ctx.prices)
        if not iss.empty:
            when = pd.to_datetime(iss['posted_on'], errors='coerce')
            cheap = iss[(when >= since) & iss['allottee_category'].isin(['PROMOTER', 'MIXED'])
                        & pd.to_numeric(iss['vs_market'], errors='coerce').lt(0)]
            for r in cheap.itertuples():
                rows.append({'nse_symbol': r.nse_symbol, 'company': getattr(r, 'company', r.nse_symbol),
                             'what': f'Preferential shares to {r.to.lower()} at {r.vs_market:+.1f}% vs today\'s price',
                             'who': r.status, 'value': r.amount, 'day': when[r.Index]})
    out = pd.DataFrame(rows, columns=['nse_symbol', 'company', 'what', 'who', 'value', 'day'])
    return out.sort_values('day', ascending=False) if len(out) else out


def render():
    ctx = load()
    kit.head('Morning brief', 'What the last session brought, before the 09:15 open, and anything touching your watchlist.')
    if not need_data(ctx):
        return
    ref = ctx.ref
    day = ref.normalize()
    e = ctx.eligible
    new = e[e['seen'].dt.normalize() == day] if not e.empty else e
    d = ctx.deals
    dnew = d[(pd.to_datetime(d['date']) == day) & d['is_primary'].astype('boolean').fillna(False)
             & ~d['client_is_market_maker'].astype('boolean').fillna(False)] if not d.empty else d
    buys, sells = new[new['side'] == 'BUY'], new[new['side'] == 'SELL']
    kit.caption(f'From the filings made public on {kit.day(day)}, cleaned overnight.')
    kit.tiles([
        kit.Tile('Open-market buys', kit.rupees(buys['value'].sum()), f'{kit.plural(buys["person_id"].nunique(), "insider")} · '
                 f'{kit.plural(buys["isin"].nunique(), "company", "companies")}', 'up' if len(buys) else ''),
        kit.Tile('Open-market sales', kit.rupees(sells['value'].sum()), f'{kit.plural(sells["person_id"].nunique(), "insider")} · '
                 f'{kit.plural(sells["isin"].nunique(), "company", "companies")}', 'down' if len(sells) else ''),
        kit.Tile('Bulk and block deals', kit.count(len(dnew)), 'market makers left out'),
    ])

    # --- watchlist -----------------------------------------------------------------------------
    watch = _watchlist()
    with kit.card('Your watchlist', 'br_watch', f'warnings from the last {WARN_DAYS} days: insider sales, pledges, '
                  'preferential shares to promoters below today\'s price'):
        typed = st.text_input('Watchlist', value=','.join(watch), placeholder='NSE symbols, e.g. TCS, INFY',
                              key='br_watch_in', label_visibility='collapsed')
        if typed.strip().upper() != ','.join(watch):
            st.query_params['watch'] = ','.join(s.strip().upper() for s in typed.split(',') if s.strip())
            st.rerun()
        if not watch:
            st.html('<p class="evl">Add NSE symbols above; the page address keeps them, so bookmark it. '
                    'Or set <code>watchlist</code> in the app\'s Streamlit secrets.</p>')
        else:
            warn = _warnings(ctx, watch, day - pd.Timedelta(days=WARN_DAYS))
            if warn.empty:
                kit.empty(f'Nothing on {", ".join(watch)} in the last {WARN_DAYS} days.')
            else:
                kit.table(with_flags(with_prices(warn.assign(isin=warn['nse_symbol'].map(
                    ctx.securities.drop_duplicates('nse_symbol').set_index('nse_symbol')['isin'])
                    if not ctx.securities.empty else None), ctx.prices)), [
                    kit.Col('company', 'Company', 'co'), kit.Col('what', 'What'), kit.Col('who', 'Who', phone=False),
                    kit.Col('value', 'Value', 'money'), kit.Col('day', 'Made public', 'date')], limit=50)

    # --- what came in --------------------------------------------------------------------------
    cl = signals.clusters(e, ref)
    cl = cl[pd.to_datetime(cl['last_seen']).dt.normalize() == day] if not cl.empty else cl
    if not cl.empty:
        with kit.card('Insiders buying together, joined last session', 'br_cl', 'clusters with a buy made public that day'):
            kit.table(with_flags(with_prices(cl, ctx.prices)), [
                kit.Col('company', 'Company', 'co', sub='who'),  # '4 buyers, 2 decision-makers: promoter group (3), director'
                kit.Col('decision_makers', 'Deciders', 'num', help='The promoter group counts once, each director or KMP once'),
                kit.Col('value', 'Bought, 30 days', 'money'), kit.Col('pct_of_mcap', '% of mcap', 'pct')], limit=10)
    big = new[new['value'] >= actions.MIN_SELL_VALUE].sort_values('pct_of_mcap', ascending=False)
    if not big.empty:
        with kit.card('Open-market trades of ₹25 L and up', 'br_big', 'made public last session, by % of market cap'):
            kit.table(with_flags(with_prices(big, ctx.prices)), [
                kit.Col('company', 'Company', 'co'), kit.Col('person_name', 'Person', 'person'), kit.Col('side', 'Side', 'side'),
                kit.Col('value', 'Value', 'money'), kit.Col('pct_of_mcap', '% of mcap', 'bar')], limit=15)
    if not dnew.empty:
        with kit.card('Bulk and block deals', 'br_deals', 'last session, largest first, market makers left out'):
            kit.table(with_flags(dnew.sort_values('value', ascending=False)), [
                kit.Col('company', 'Company', 'co'), kit.Col('client_name', 'Client', 'client'), kit.Col('side', 'Side', 'side'),
                kit.Col('value', 'Value', 'money'), kit.Col('pct_of_mcap', '% of mcap', 'bar')], limit=10)

    # --- coming up -----------------------------------------------------------------------------
    m = ctx.meetings
    if not m.empty:
        m = m.assign(meeting_date=pd.to_datetime(m['meeting_date'], errors='coerce'))
        soon = m[(m['meeting_date'] > day) & (m['meeting_date'] <= day + pd.Timedelta(days=SOON_DAYS))]
        if watch:
            soon = soon.assign(_w=soon['symbol'].astype(str).str.upper().isin(watch)).sort_values(['_w', 'meeting_date'], ascending=[False, True])
        if not soon.empty:
            with kit.card('Board meetings this week', 'br_meet', f'next {SOON_DAYS} days{", your watchlist first" if watch else ""}'):
                kit.table(soon.assign(nse_symbol=soon['symbol'], what=soon['purposes'].str.replace('_', ' ').str.replace(',', ', ')), [
                    kit.Col('company', 'Company', 'co'), kit.Col('meeting_date', 'Meeting', 'date'),
                    kit.Col('what', 'To consider')], limit=20)
    cal = lock_in_calendar(ctx.preferential, ctx.prices, ref, store.table('preferential_lockins'))   # filed lines, as on Actions (audit W6)
    if cal is not None and not cal.empty:
        cal = cal[(cal['days_left'] > 0) & (cal['days_left'] <= SOON_DAYS)]
        if not cal.empty:
            with kit.card('Shares coming off lock-in this week', 'br_lock', f'next {SOON_DAYS} days'):
                kit.table(with_flags(cal), [
                    kit.Col('expires', 'Free from', 'date'), kit.Col('company', 'Company', 'co'), kit.Col('who', 'Whose shares'),
                    kit.Col('shares', 'Shares', 'shares', phone=False),
                    kit.Col('at_market', 'At market now', 'money', phone=False)], limit=20)
