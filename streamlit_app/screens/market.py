"""Market (home, 21 Oct 2026 redesign): the companies where insiders and funds
are putting money in or taking it out, one ranked board, and what is due in the
next two weeks. Replaces Actions, Morning brief, Latest session, Screener and
Shareholding & pledges: each signal is defined once (insiders_clean/signals.py)
and shown once, as a badge on its company, with its evidence status beside it."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from data import store
from ui import kit
from ui.kit import esc
from ui.table import facts

from insiders_clean import evidence, signals
from screens.brief import _warnings, _watchlist
from screens.capital_raises import lock_in_calendar
from screens.ctx import load, need_data, split_since, with_flags, with_prices, with_sparks

DAYS = 90            # the board's window
AHEAD = 14           # the calendar's window, from today
MEETING_FLAGS = ['fund_raising', 'preferential', 'buyback', 'rights', 'bonus', 'split']
# Badge -> its signal in the track record (insiders_clean/track.py), for the evidence tag.
BADGE_SIGNAL = {'Promoter buying': 'promoter_buy', 'Cluster': 'cluster', 'Spotlight': 'spotlight',
                'Promoter selling': 'promoter_sell', 'Fund buying': 'fund_deal_buy'}
BADGE_RULE = {'Promoter buying': 'promoters net bought on the market, 90 days',
              'Cluster': '2+ decision-makers bought, 30 days (a promoter group counts once)',
              'Spotlight': 'one person bought 0.15%+ of market cap, 30 days',
              'Float absorber': 'one person bought 0.5%+ of market cap, 90 days',
              'Promoter selling': 'promoters net sold 0.15%+ of market cap, 90 days',
              'High pledge': f'over {signals.HIGH_PLEDGE_PCT:.0f}% of promoter shares pledged, latest quarter',
              'Fund buying': 'funds net bought in bulk/block deals, small caps, 30 days'}
FILTERS = ['All', 'Promoter buying', 'Cluster', 'Spotlight', 'Float absorber', 'Fund buying', 'Promoter selling', 'High pledge']


def _today() -> pd.Timestamp:
    return pd.Timestamp.now(tz='Asia/Kolkata').tz_localize(None).normalize()


def _board(ctx) -> pd.DataFrame:
    board = signals.company_board(ctx.eligible, ctx.deals, ctx.shareholding, ctx.ref, days=DAYS)
    if board.empty:
        return board
    funds = signals.small_cap_accumulation(ctx.deals, ctx.ref, 30)
    fund_isins = set(funds['isin']) if not funds.empty and 'isin' in funds else set()
    day = ctx.ref.normalize()
    board['badges'] = [(['Promoter buying'] if net > 0 else []) + list(b) + (['Fund buying'] if i in fund_isins else [])
                       for i, net, b in zip(board['isin'], board['promoter_net'], board['badges'])]
    board['new'] = pd.to_datetime(board['last_seen']).dt.normalize() >= day
    return board[board['badges'].map(len) > 0].reset_index(drop=True)


def _paid(ctx) -> tuple[pd.Series, pd.Series]:
    """ISIN -> value-weighted average price promoters paid in the window (today's split basis), last buy."""
    e = ctx.eligible
    w = e[(e['side'] == 'BUY') & e['person_role'].isin(signals.PROMOTER_ROLES) & ~e['is_token']
          & (e['seen'] > ctx.ref - pd.Timedelta(days=DAYS)) & (e['seen'] <= ctx.ref)]
    q = pd.to_numeric(w['quantity'], errors='coerce') / split_since(w, ctx.prices)
    paid = w['value'].where(q > 0).groupby(w['isin']).sum() / q.where(q > 0).groupby(w['isin']).sum()
    return paid, w.groupby('isin')['seen'].max()


def _ahead(ctx) -> pd.DataFrame:
    """Board meetings on capital (fund raising, preferential, buyback, rights, bonus, split) and lock-in
    expiries in the next AHEAD days from today: date, company, what."""
    today = _today()
    parts = []
    m = ctx.meetings
    if m is not None and not m.empty:
        m = m.assign(when=pd.to_datetime(m['meeting_date'], errors='coerce'))
        flags = [c for c in MEETING_FLAGS if c in m]
        if flags:
            soon = m[(m['when'] >= today) & (m['when'] <= today + pd.Timedelta(days=AHEAD))
                     & m[flags].astype('boolean').fillna(False).any(axis=1)]
            parts.append(soon.assign(nse_symbol=soon['symbol'], kind='Board meeting',
                                     what=soon['purposes'].str.replace('_', ' ').str.replace(',', ', ').str.capitalize()))
    cal = lock_in_calendar(ctx.preferential, ctx.prices, today, store.table('preferential_lockins'))
    if cal is not None and not cal.empty:
        cal = cal[(cal['expires'] >= today) & (cal['expires'] <= today + pd.Timedelta(days=AHEAD))]
        parts.append(cal.assign(when=cal['expires'], kind='Lock-in ends',
                                what=[f'{w} · {kit.shares(s)} shares' if pd.notna(s) else str(w)
                                      for w, s in zip(cal['who'], cal['shares'])]))
    parts = [p for p in parts if not p.empty]
    if not parts:
        return pd.DataFrame()
    cols = ['when', 'kind', 'company', 'nse_symbol', 'isin', 'what']
    return pd.concat([p[[c for c in cols if c in p]] for p in parts], ignore_index=True).sort_values('when')


def _detail(r) -> str:
    items = [('Who', r.get('who') or ''),
             ('Promoters hold', kit.pct(r.get('promoter_holding_pct'), 1) if pd.notna(r.get('promoter_holding_pct')) else ''),
             ('Pledged', kit.pct(r.get('pledge_pct'), 1) + " of promoters' shares" if pd.notna(r.get('pledge_pct')) else ''),
             ('Avg paid, 90 days', kit.price(r.get('avg_paid')) if pd.notna(r.get('avg_paid')) else ''),
             ('Last promoter buy', kit.day(r.get('last_buy')) if pd.notna(r.get('last_buy')) else ''),
             ('Deals net, 90 days', kit.rupees(r.get('deals_net'), signed=True) if pd.notna(r.get('deals_net')) and r.get('deals_net') else ''),
             ('Market cap', kit.rupees(r.get('market_cap')) if pd.notna(r.get('market_cap')) else ''),
             ('Sector', r.get('sector') or '')]
    for b in r.get('badges') or []:
        name = 'High pledge' if b.startswith('High pledge') else b
        items.append((name, BADGE_RULE.get(name, '')))
    sym = r.get('nse_symbol') or ''
    return facts(items, [('Company page', kit.company_href(sym)),
                         ('NSE insider filings', f'https://www.nseindia.com/companies-listing/corporate-filings-insider-trading?symbol={sym}' if sym else '')])


def _evidence_line(summ: pd.DataFrame) -> None:
    bits = []
    for badge, sig in BADGE_SIGNAL.items():
        v = evidence.verdict(summ, sig)
        bits.append(f'<span class="ev-i" title="{esc(v["text"], quote=True)}"><b>{esc(badge)}</b>{kit.tag(v["tag"], v["tone"])}</span>')
    st.html('<div class="ev-line">' + ''.join(bits) + '<a href="/track-record" target="_self">Evidence →</a></div>')


def render():
    ctx = load()
    kit.head('Market', f'Where insiders and funds put money in or took it out, {DAYS} days, and what is due next.')
    if not need_data(ctx):
        return
    day = ctx.ref.normalize()

    watch = _watchlist()
    if watch:
        warn = _warnings(ctx, watch, day - pd.Timedelta(days=7))
        if not warn.empty:
            with kit.card('Watchlist', 'mk_watch', f'{", ".join(watch)} · last 7 days'):
                kit.table(warn, [kit.Col('company', 'Company', 'co'), kit.Col('what', 'What'), kit.Col('who', 'Who', phone=False),
                                 kit.Col('value', 'Value', 'money'), kit.Col('day', 'Made public', 'date')], limit=30, key='mk_watch')

    e = ctx.eligible
    last = e[e['seen'].dt.normalize() == day]
    board = _board(ctx)
    buys, sells = last[last['side'] == 'BUY'], last[last['side'] == 'SELL']
    n_clus = int(board['badges'].map(lambda b: 'Cluster' in b).sum()) if not board.empty else 0
    kit.tiles([
        kit.Tile(f'Bought, {kit.day(day, with_year=False)}', kit.rupees(buys['value'].sum()),
                 f'{kit.plural(buys["isin"].nunique(), "company", "companies")} · open market', 'up' if len(buys) else ''),
        kit.Tile(f'Sold, {kit.day(day, with_year=False)}', kit.rupees(sells['value'].sum()),
                 f'{kit.plural(sells["isin"].nunique(), "company", "companies")} · open market', 'down' if len(sells) else ''),
        kit.Tile('Promoter buying, 90 days', kit.count(int((board['promoter_net'] > 0).sum()) if not board.empty else 0), 'companies, net'),
        kit.Tile('Clusters, 30 days', kit.count(n_clus), '2+ decision-makers buying'),
    ])

    summ = store.artifact('artifacts/track_summary.parquet')
    with kit.card('Companies', 'mk_board', f'{DAYS} days to {kit.day(day)} · ranked by promoter net buying as % of market cap'):
        _evidence_line(summ)
        c1, c2 = st.columns([4, 1.4], vertical_alignment='center')
        pick = c1.pills('Signal', FILTERS, default='All', key='mk_pick', label_visibility='collapsed') or 'All'
        q = c2.text_input('Search', placeholder='Company or symbol', key='mk_q', label_visibility='collapsed')
        rows = board
        if pick != 'All' and not rows.empty:
            rows = rows[rows['badges'].map(lambda b: any(x.startswith(pick) for x in b))]
        if q and not rows.empty:
            rows = rows[rows['company'].str.contains(q, case=False, na=False, regex=False)
                        | rows['nse_symbol'].astype(str).str.contains(q, case=False, regex=False)]
        if rows.empty:
            kit.empty('No company with this signal in the window.')
        else:
            paid, last_buy = _paid(ctx)
            sec = ctx.securities.drop_duplicates('isin').set_index('isin') if not ctx.securities.empty else pd.DataFrame()
            shl = signals.latest_shareholding(ctx.shareholding).dropna(subset=['isin']).drop_duplicates('isin', keep='last').set_index('isin') \
                if not ctx.shareholding.empty else pd.DataFrame()
            show = with_flags(with_sparks(with_prices(rows, ctx.prices), ctx))
            show = show.assign(
                avg_paid=show['isin'].map(paid), last_buy=show['isin'].map(last_buy),
                who=show['isin'].map(signals.insider_details(ctx.eligible, ctx.ref)),
                sector=show['isin'].map(sec['sector']) if 'sector' in sec else None,
                promoter_holding_pct=show['isin'].map(shl['promoter_holding_pct']) if 'promoter_holding_pct' in shl else None,
                tags=[(['New'] if n else []) + list(b) for n, b in zip(show['new'], show['badges'])])
            show['vs_paid'] = (pd.to_numeric(show['latest_close'], errors='coerce') / show['avg_paid'] - 1) * 100
            kit.table(show, [
                kit.Col('company', 'Company', 'co'),
                kit.Col('tags', 'Signals', 'tags', phone=False),
                kit.Col('promoter_net', 'Promoter net', 'smoney', help='Promoter and promoter group, open market, 90 days, token buys out'),
                kit.Col('promoter_net_pct', '% of mcap', 'bar'),
                kit.Col('decision_makers', 'Deciders', 'num', phone=False, help='Distinct decision-makers buying or selling; a promoter group counts once'),
                kit.Col('vs_paid', 'CMP vs paid', 'spct', help='Latest close against the average price promoters paid, 90 days'),
                kit.Col('range', '52W range · CMP', 'range', phone=False),
                kit.Col('spark', '1Y · insider trades', 'spark', phone=False),
            ], limit=100, download='market', detail=_detail, key='mk_board')

    ahead = _ahead(ctx)
    if not ahead.empty:
        with kit.card('Next two weeks', 'mk_ahead', f'from {kit.day(_today())} · capital meetings and lock-in ends'):
            kit.table(with_flags(ahead), [kit.Col('when', 'Date', 'date'), kit.Col('company', 'Company', 'co'),
                                          kit.Col('kind', 'What'), kit.Col('what', 'Detail', phone=False)], limit=60, key='mk_ahead')
