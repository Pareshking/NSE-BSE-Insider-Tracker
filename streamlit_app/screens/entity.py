"""Person / fund page (/entity?id=...): what one promoter, officer or fund
has done across all companies."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from data import store
from ui import charts, dates, kit

from insiders_clean import fund_managers, investors, participants, public_holders, signals
from screens.ctx import load, need_data, split_since, with_prices, with_sparks


def holdings(ph: pd.DataFrame, eid: str, name, securities: pd.DataFrame | None = None) -> pd.DataFrame:
    """The companies where this person or fund is named among the public shareholders over 1% at the company's latest
    quarter (public_holders.holdings_of), matched on holder_key of the page's id or of its name: identity only, as
    every other link on this page. With the company's display name and the change in words."""
    keys = {public_holders.holder_key(str(eid).replace('-', ' ')), public_holders.holder_key(name)}
    h = public_holders.holdings_of(ph, keys)
    if h.empty:
        return h
    if securities is not None and not securities.empty and {'isin', 'display_name'} <= set(securities.columns):
        h['company'] = h['isin'].map(securities.drop_duplicates('isin').set_index('isin')['display_name'])
    else:
        h['company'] = None
    h['company'] = h['company'].fillna(h['symbol'])
    h['nse_symbol'] = h['symbol']
    from screens.company import holder_change
    h['type_label'] = h['type'].map(public_holders.TYPE_LABELS).fillna(h['type'])
    h['since'] = [holder_change(r) for r in h.to_dict('records')]
    return h


def _keys(eid: str, name) -> set:
    return {k for k in (public_holders.holder_key(str(eid).replace('-', ' ')), public_holders.holder_key(name)) if k}


def exited(ph: pd.DataFrame, eid: str, name, securities: pd.DataFrame | None = None) -> pd.DataFrame:
    """The companies whose previous quarter named this holder over 1% and whose latest quarter does not: under 1% or sold
    out (public_holders.changes; the filing does not say which). Same columns as `holdings`."""
    keys = _keys(eid, name)
    if ph is None or ph.empty or not keys or 'holder_key' not in ph:
        return pd.DataFrame(columns=public_holders.CHANGE_COLUMNS)
    isins = set(ph.loc[ph['holder_key'].isin(keys), 'isin'].dropna())
    ch = public_holders.changes(ph[ph['isin'].isin(isins)])
    ch = ch[ch['holder_key'].isin(keys) & ch['change'].eq('exited')].reset_index(drop=True)
    if ch.empty:
        return ch
    names = (securities.drop_duplicates('isin').set_index('isin')['display_name']
             if securities is not None and not securities.empty and {'isin', 'display_name'} <= set(securities.columns) else pd.Series(dtype=object))
    ch['company'] = ch['isin'].map(names).fillna(ch['symbol'])
    ch['type_label'] = ch['type'].map(public_holders.TYPE_LABELS).fillna(ch['type'])
    return ch.sort_values('prev_pct', ascending=False).reset_index(drop=True)


def history(ph: pd.DataFrame, eid: str, name, companies: pd.DataFrame) -> pd.DataFrame:
    """% of each company this holder was named with, per quarter we have (one key filed twice in a list summed), for the
    companies in `companies` (isin -> company)."""
    keys = _keys(eid, name)
    if ph is None or ph.empty or not keys or companies is None or companies.empty:
        return pd.DataFrame(columns=['isin', 'company', 'quarter_end', 'pct_of_company'])
    h = ph[ph['holder_key'].isin(keys) & ph['isin'].isin(set(companies['isin']))]
    h = (h.assign(quarter_end=pd.to_datetime(h['quarter_end'], errors='coerce'),
                  pct_of_company=pd.to_numeric(h['pct_of_company'], errors='coerce'))
          .groupby(['isin', 'quarter_end'], as_index=False)['pct_of_company'].sum())
    return h.merge(companies[['isin', 'company']].drop_duplicates('isin'), on='isin', how='left')


def _summary(held: pd.DataFrame, gone: pd.DataFrame, bought: float, sold: float, quarter) -> None:
    """At the top: how many holdings over 1% and what moved in them this quarter; then bought against sold in rupees."""
    if not len(held) and not len(gone) and bought <= 0 and sold <= 0:
        return
    with kit.card('Bought or sold?', 'en_sum'):
        if len(held) or len(gone):
            c = held['change'].value_counts() if len(held) else pd.Series(dtype=int)
            compared = len(held) - int(c.get('no_previous', 0))
            q = f' at {kit.day(quarter)}' if quarter is not None and pd.notna(quarter) else ''
            st.html(f'<p class="chart-cap"><b>{kit.plural(len(held), "holding")} over 1%</b>{q}'
                    + (f'; {kit.plural(int(c.get("no_previous", 0)), "company", "companies")} with one quarter only, nothing to compare'
                       if c.get('no_previous', 0) else '') + '</p>')
            if compared or len(gone):
                st.html(charts.count_strip(int(c.get('added', 0)), int(c.get('cut', 0)), int(c.get('new', 0)), len(gone)))
        split = charts.buy_sell_split(bought, sold)
        if split:
            st.html(split)
            st.html('<p class="chart-cap">Open-market insider trades and bulk or block deals of the last 12 months, in rupees; '
                    'a deal that is also this person\'s own filing counted once</p>')


def _holdings_card(held: pd.DataFrame, gone: pd.DataFrame, hist: pd.DataFrame) -> None:
    rows = pd.concat([held, gone], ignore_index=True) if len(gone) else held.copy()
    rows['nse_symbol'] = rows['symbol']
    rows['sub'] = [' · '.join(x for x in (str(t or ''), kit.day(q) if pd.notna(q) else '') if x)
                   for t, q in zip(rows['type_label'], pd.to_datetime(rows['quarter_end'], errors='coerce'))]
    with kit.card('Holdings over 1%', 'en_ph', "named in each company's latest shareholding pattern"):
        moved = rows[rows['change'].isin(['added', 'cut', 'new', 'exited'])].copy()
        moved['tag'] = moved['change'].map({'new': 'new: crossed 1%', 'exited': 'exited: under 1%'})
        bars = charts.diverging_bar(moved, 'company', 'pct_change', tag='tag', limit=20)
        if bars:
            st.html('<p class="chart-cap">Change since the quarter before, in points of the company'
                    + (f' · the 20 largest of {len(moved)}' if len(moved) > 20 else '') + '. '
                    + ('New and exited bars are the whole holding: below 1% a holder is not named, so that is the most it '
                       'can have moved.' if moved['tag'].notna().any() else '') + '</p>')
            st.html(bars)
        st.html(charts.change_rows(rows, sub='sub'))
    two = hist.groupby('isin')['quarter_end'].transform('nunique') >= 2 if len(hist) else pd.Series(dtype=bool)
    if len(hist) and two.any():
        with kit.card('Holding over the quarters', 'en_trend', '% of each company, the largest eight'):
            st.altair_chart(charts.holding_trend(hist[two]), width='content')
            st.html('<p class="chart-cap">The site keeps the last two quarters of each company\'s list. A quarter with no '
                    'point: not named (under 1%) or not filed yet.</p>')


def render():
    ctx = load()
    if not need_data(ctx):
        return
    eid = st.query_params.get('id')
    if not eid:
        kit.head('Person or fund', 'Open a person or fund from any table, or search below.')
        q = st.text_input('Search', placeholder='Name', key='en_q')
        if q:
            ph = store.table('public_holders')
            people = pd.concat([ctx.trades[['person_id', 'person_name']].rename(columns={'person_id': 'id', 'person_name': 'name'}),
                                ctx.deals[['client_id', 'client_name']].rename(columns={'client_id': 'id', 'client_name': 'name'})
                                if not ctx.deals.empty else pd.DataFrame(columns=['id', 'name']),
                                # public shareholders over 1% (shareholding pattern): their page lists their holdings
                                ph[['holder_key', 'holder_name']].rename(columns={'holder_key': 'id', 'holder_name': 'name'})
                                if not ph.empty and 'holder_key' in ph else pd.DataFrame(columns=['id', 'name'])
                                ]).dropna().drop_duplicates('id')
            hits = people[people['name'].str.contains(q, case=False, na=False, regex=False)].head(30)
            st.html('<div class="q-list">' + ''.join(
                f'<div class="q-row"><a href="{kit.entity_href(i)}" target="_self"><b>{kit.esc(str(n))}</b></a></div>'
                for i, n in zip(hits['id'], hits['name'])) + '</div>' if len(hits) else '<p class="evl">No match. Try part of the name.</p>')
        return
    # One row per real trade: the NSE and BSE copies of a filing are the same trade.
    t = ctx.trades[(ctx.trades['person_id'] == eid) & ctx.trades['is_primary'].astype('boolean').fillna(False)]
    # An investor is every name of its investor group together (the same investor under different spellings).
    d, group_id = investors.profile_deals(ctx.deals, eid)
    shown = d['investor_group'].dropna().iloc[0] if len(d) and 'investor_group' in d and d['investor_group'].notna().any() else None
    name = (t['person_name'].dropna().iloc[0] if len(t) else shown or d['client_name'].dropna().iloc[0] if len(d) else None)
    ph = store.table('public_holders')
    held = holdings(ph, eid, name, ctx.securities)
    name = name or (held['holder_name'].iloc[0] if len(held) else eid)
    gone = exited(ph, eid, name, ctx.securities)
    kit.head(str(name), 'Every filing and deal under this name, across companies.')
    if not d.empty and d['client_is_market_maker'].astype('boolean').fillna(False).any():
        st.html('<p class="evl">' + kit.tag('Market maker', 'mute') + ' buys and sells in near-equal amounts: '
                'liquidity, left out of signals</p>')
    if not d.empty and 'client_type' in d:
        # Type read from the name (insiders_clean/participants.py); the names this investor deals under; the fund manager
        # the name itself names (fund_managers.csv), with the other funds of that manager seen in the deals.
        big = d.sort_values('value', ascending=False).iloc[0]
        kind = participants.TYPES.get(big['client_type'], big['client_type'])
        names = sorted(set(d['client_name'].dropna()))
        manager, sub, why = fund_managers.manager_of(big['client_name'])
        st.html(f'<p class="evl">{kit.esc(kind)} · {big["client_type_confidence"]} confidence ({kit.esc(str(big["client_type_rule"]))})'
                + (f' · deals under {kit.plural(len(names), "name")}: {kit.esc("; ".join(names[:6]))}{" …" if len(names) > 6 else ""}'
                   if len(names) > 1 else '') + '</p>')
        if manager:
            mgr = fund_managers.add_manager_columns(ctx.deals)
            mates = mgr[mgr['manager'].eq(manager) & ~mgr['client_id'].isin(set(d['client_id']))].drop_duplicates('client_id')
            links = ', '.join(f'<a href="{kit.entity_href(i)}" target="_self">{kit.esc(str(n))}</a>'
                              for i, n in zip(mates['investor_group_id'].fillna(mates['client_id']).head(8), mates['client_name'].head(8)))
            st.html(f'<p class="evl">Fund manager named in the fund name: <b>{kit.esc(manager)}</b>'
                    + (' · likely sub-advised (another sponsor\'s name leads)' if sub else '')
                    + (f' · other funds of this manager: {links}' if links else '') + '</p>')
    mk = ctx.eligible[ctx.eligible['person_id'] == eid]
    # Owner's spec: capital deployed in 12 months, active tickers; win rate and
    # holding period come with the signal lab (docs/DATA_TO_PAGES.md S21).
    # 12 months back from the data's date, not this person's last trade (audit W8); a deal that is
    # the same trade as this person's own filing is counted once, under the filing (audit W7).
    seen = pd.to_datetime(mk['broadcast_date'], errors='coerce')
    yr = mk[seen > ctx.ref - pd.Timedelta(days=365)] if len(mk) and ctx.ref is not None else mk
    bought_ins = pd.to_numeric(yr.loc[yr['side'] == 'BUY', 'value'], errors='coerce').sum() if len(yr) else 0.0
    sold_ins = pd.to_numeric(yr.loc[yr['side'] == 'SELL', 'value'], errors='coerce').sum() if len(yr) else 0.0
    deals_end = ctx.deals['date'].max() if not ctx.deals.empty else None
    d_own = d[~signals.deals_also_filed(d, ctx.trades)] if len(d) else d
    dy = d_own[d_own['date'] > deals_end - pd.Timedelta(days=365)] if len(d_own) and deals_end is not None else d_own
    bought_deals = pd.to_numeric(dy.loc[dy['side'] == 'BUY', 'value'], errors='coerce').sum() if len(dy) else 0.0
    sold_deals = pd.to_numeric(dy.loc[dy['side'] == 'SELL', 'value'], errors='coerce').sum() if len(dy) else 0.0
    active = pd.concat([yr['isin'] if len(yr) else pd.Series(dtype=object),
                        dy['isin'] if len(dy) else pd.Series(dtype=object)]).dropna().nunique()
    # Every open-market buy valued at today's close, shares restated for any split or
    # bonus since; value-weighted, and the share of buys now above the price paid.
    buys = with_prices(mk[mk['side'] == 'BUY'], ctx.prices)
    f = split_since(buys, ctx.prices)
    paid = pd.to_numeric(buys['price'], errors='coerce') * f
    now = pd.to_numeric(buys['latest_close'], errors='coerce')
    shares = pd.to_numeric(buys['quantity'], errors='coerce') / f
    ok = shares.gt(0) & paid.gt(0) & now.gt(0)
    cost, worth = (shares * paid)[ok].sum(), (shares * now)[ok].sum()
    pnl = (kit.Tile('Open-market buys, P&L', kit.pct((worth / cost - 1) * 100, 1, signed=True),
                    f'{kit.rupees(cost)} paid, worth {kit.rupees(worth)} at the latest close · '
                    f'{(now[ok] > paid[ok]).mean() * 100:.0f}% of {kit.plural(int(ok.sum()), "buy")} in profit',
                    'up' if worth > cost else 'down')
           if cost > 0 else None)
    quarter = pd.to_datetime(held['quarter_end'], errors='coerce').max() if len(held) else None
    _summary(held, gone, bought_ins + bought_deals, sold_ins + sold_deals, quarter)
    kit.tiles([
        kit.Tile('Capital deployed, 12 months', kit.rupees(bought_ins + bought_deals),
                 f'open-market insider buys {kit.rupees(bought_ins)} · other deal buys {kit.rupees(bought_deals)}'),
        kit.Tile('Active companies, 12 months', kit.count(active), 'with an open-market buy, sale or deal'),
        kit.Tile('Net, all data', kit.rupees((mk['signed_value'].sum() if len(mk) else 0) + (d_own['signed_value'].sum() if len(d_own) else 0),
                                              signed=True), f'{kit.count(len(t))} insider filings · {kit.count(len(d))} deals'),
        *([pnl] if pnl else []),
    ])
    if len(held) or len(gone):
        both = pd.concat([held[['isin', 'company']], gone[['isin', 'company']]]) if len(gone) else held[['isin', 'company']]
        _holdings_card(held, gone, history(ph, eid, name, both))
    # the lists below over the page's dates (owner, 19 Nov 2026: "a date selector ... must be present"); the tiles above
    # keep their own 12 months and all data, as labelled
    rng = dates.range_picker('entity', *dates.bounds(t['broadcast_date'] if len(t) else None, d['date'] if len(d) else None,
                                                     hi=ctx.ref), default='all', caption=True)
    had = len(t) + len(d)
    t = t[rng.mask(t['broadcast_date'])] if len(t) else t
    d_list = d[rng.mask(d['date'])] if len(d) else d
    if had and not len(t) and not len(d_list):
        kit.empty(f'No insider filing or deal under this name, {dates.describe(rng)}.')
    if len(t):
        with kit.card('Insider filings', 'en_it', dates.describe(rng)):
            s = t.sort_values('broadcast_date', ascending=False)
            kit.table(with_sparks(s.assign(seen=pd.to_datetime(s['broadcast_date'], errors='coerce'),
                                           mode=s['mode_raw'].fillna(s['kind'])), ctx), [
                kit.Col('company', 'Company', 'co'), kit.Col('side', 'Side', 'side'),
                kit.Col('value', 'Value', 'money'), kit.Col('pct_of_mcap', '% of mcap', 'bar'),
                kit.Col('seen', 'Made public', 'date'), kit.Col('mode', 'Mode as filed', phone=False),
                kit.Col('spark', '1Y price · insider trades', 'spark', phone=False)], limit=100)
    ref_deals = pd.Timestamp(ctx.deals['date'].max()) if not ctx.deals.empty else None
    per = investors.by_company(d, ref_deals, 90) if len(d) else pd.DataFrame()
    if len(per):
        with kit.card('Net by company', 'en_net', 'last 90 days, bulk and block deals'):
            bars = charts.diverging_bar(per, 'company', 'net', fmt=lambda v: kit.rupees(v, signed=True))
            if bars:
                st.html(bars)
            kit.table(per, [kit.Col('company', 'Company', 'co'), kit.Col('net', 'Net', 'smoney'), kit.Col('buy', 'Bought', 'money', phone=False),
                            kit.Col('sell', 'Sold', 'money', phone=False), kit.Col('pct', 'Share of company', 'spct'),
                            kit.Col('last', 'Last deal', 'date', phone=False)], limit=30, key='en_net_t', keep_empty=True)
    if len(d_list):
        with kit.card('Deals', 'en_dl', dates.describe(rng)):
            s = d_list.sort_values('date', ascending=False)
            kit.table(s, [
                kit.Col('company', 'Company', 'co'), kit.Col('date', 'Date', 'date'), kit.Col('side', 'Side', 'side'),
                kit.Col('quantity', 'Shares', 'shares', phone=False), kit.Col('price', 'Price', 'price', phone=False),
                kit.Col('value', 'Value', 'money'), kit.Col('pct_of_mcap', '% of mcap', 'bar'),
                kit.Col('counterparties', 'Other side that day', phone=False, wrap=True), kit.Col('feeds', 'Feed', phone=False)], limit=100)
