"""Investors: what mutual funds, foreign investors, insurers and other large investors bought and sold.

Bulk and block deals only (a small part of what funds do; most fund buying is not disclosed this way), with the type of
each investor read from its name. The reading lives in insiders_clean/investors.py; this page draws it."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from data import store
from ui import kit
from ui.kit import Col, Tile

from insiders_clean import investors, participants, signals
from screens.ctx import load

PERIODS = {7: '7 days', 30: '30 days', 90: '90 days'}
WHO = ['Funds and institutions', 'Include unclear types']
STANDING = ('Bulk and block deals only: most fund buying is not disclosed this way. The type of an investor is read from its '
            'name, never confirmed.')
LIMIT = 10


def _label(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df['type_label'] = df['type'].map(participants.TYPES).fillna('Unknown')
    df['type_sub'] = df['type_label'] + df['confidence'].map({'low': ' (unclear)', 'medium': ''}).fillna('')
    df['position'] = df['largest_symbol'].fillna('')
    return df


INVESTOR_COLS = [
    Col('investor', 'Investor', 'text', sub='type_sub', wrap=True),
    Col('net', 'Net', 'smoney', help='Bought minus sold in bulk and block deals over the period'),
    Col('buy', 'Bought', 'money', phone=False),
    Col('sell', 'Sold', 'money', phone=False),
    Col('companies', 'Companies', 'num', phone=False),
    Col('largest_company', 'Largest position', 'co', sub='', help='The company with the largest net either way'),
    Col('largest_pct', 'Share of company', 'spct', help='Net bought or sold, as a share of the company, at the trade date'),
]
MANAGER_COLS = [
    Col('manager', 'Fund manager (from fund name)', 'text', wrap=True),
    Col('net', 'Net', 'smoney'), Col('buy', 'Bought', 'money', phone=False), Col('sell', 'Sold', 'money', phone=False),
    Col('funds', 'Funds', 'num'), Col('sub_note', 'Sub-advised', 'text', phone=False, wrap=True),
]


def _panel(df: pd.DataFrame, key: str, empty: str) -> None:
    if df.empty:
        kit.empty(empty)
        return
    d = _label(df)
    d['nse_symbol'] = d['largest_symbol']
    kit.table(d, INVESTOR_COLS, limit=LIMIT, key=key, keep_empty=True)


def _holders(ctx) -> None:
    snap = store.snapshot()
    if snap.empty or not {'mf', 'fpi'} <= set(snap.columns):
        return
    s = snap.copy()
    s['move'] = s[['mf_change_pts', 'fpi_change_pts']].abs().max(axis=1)
    s = s[s['move'].notna()].sort_values('move', ascending=False).head(LIMIT)
    if s.empty:
        return
    s['nse_symbol'] = s['symbol']
    with kit.card('Funds in each company', 'inv_holders', 'latest quarter filed, change from the quarter before, in points of the company'):
        cols = [Col('company', 'Company', 'co'), Col('mf', 'Mutual funds', 'pct'), Col('mf_change_pts', 'Change', 'spct'),
                Col('fpi', 'Foreign investors', 'pct'), Col('fpi_change_pts', 'Change', 'spct'),
                Col('mf_quarter', 'As of', 'date', phone=False)]
        kit.table(s, cols, limit=LIMIT, key='inv_holders_t', keep_empty=True)


def _raises(ctx) -> None:
    q = store.table('qip_allottees')
    if q.empty or 'allottee' not in q:
        return
    d = q.assign(posted_on=pd.to_datetime(q['posted_on'], errors='coerce')).dropna(subset=['posted_on'])
    d = d[d['posted_on'] > d['posted_on'].max() - pd.Timedelta(days=90)]
    if d.empty:
        return
    g = d.groupby(['isin', 'company', 'symbol'], as_index=False).agg(
        named=('allottee', 'nunique'), top=('allottee', 'first'), last=('posted_on', 'max'),
        share=('pct_of_issue', 'sum'))
    g['named_text'] = [f'{n} named allottees; total not stated' for n in g['named']]
    g['nse_symbol'] = g['symbol']
    g = g.sort_values('last', ascending=False)
    with kit.card('Who bought the raises', 'inv_raises', 'qualified placements of the last 90 days, allottees as the company named them'):
        cols = [Col('company', 'Company', 'co'), Col('top', 'First named allottee', 'text', wrap=True),
                Col('named_text', 'Named', 'text', wrap=True), Col('last', 'Posted', 'date')]
        kit.table(g, cols, limit=LIMIT, key='inv_raises_t', keep_empty=True)


def render():
    ctx = load()
    kit.head('Investors', 'What mutual funds, foreign investors, insurers and other large investors bought and sold.')
    if ctx.deals.empty:
        kit.note('No deals yet.', 'Bulk and block deals fill this page after the nightly run.')
        return
    days = st.segmented_control('Period', list(PERIODS), default=30, format_func=PERIODS.get, required=True,
                                key='inv_days', label_visibility='collapsed') or 30
    who = st.segmented_control('Who', WHO, default=WHO[0], required=True, key='inv_who', label_visibility='collapsed') or WHO[0]
    ref = pd.Timestamp(ctx.deals['date'].max())
    inv = investors.floored(investors.net_by_investor(ctx.deals, ref, int(days)))
    inv, left_out = investors.split_confidence(inv, include_low=who != WHO[0])
    types = investors.by_type(ctx.deals, ref, int(days))
    if types.empty:
        kit.empty('No fund deals in this period.')
        return
    kit.tiles([Tile(participants.TYPES.get(r.type, r.type), kit.rupees(r.net, signed=True), f'{r.investors} investors',
                    'up' if r.net > 0 else 'down') for r in types.head(4).itertuples()])
    kit.caption(STANDING + (f' {left_out} investors with an unclear type are left out.' if left_out else ''))
    buy, sell = investors.buyers_sellers(inv, LIMIT, by='value')
    with kit.card('Biggest net buyers', 'inv_buy', f'last {days} days'):
        _panel(buy, 'inv_buy_t', 'No net buyers above the floor in this period.')
    with kit.card('Biggest net sellers', 'inv_sell', f'last {days} days'):
        _panel(sell, 'inv_sell_t', 'No net sellers above the floor in this period.')
    mgr = investors.by_manager(ctx.deals, ref, int(days))
    if not mgr.empty:
        mgr['sub_note'] = [f'{n} of {f} funds, likely sub-advised' if n else '' for n, f in zip(mgr['sub_advised'], mgr['funds'])]
        with st.expander('By fund manager (named in the fund name)'):
            kit.table(mgr, MANAGER_COLS, limit=LIMIT, key='inv_mgr_t', keep_empty=True)
    hs = signals.handshakes(ctx.deals, ctx.trades, days=int(days), ref=ref)
    if not hs.empty:
        hs = hs.head(LIMIT)
        with kit.card('Who sold, who absorbed it', 'inv_hs', 'the seller and the buyers of the same security on the same day'):
            cols = [Col('company', 'Company', 'co'), Col('date', 'Day', 'date'), Col('sellers', 'Sold', 'text', wrap=True),
                    Col('buyers', 'Bought', 'text', wrap=True), Col('matched_value', 'Matched', 'money')]
            kit.table(hs, cols, limit=LIMIT, key='inv_hs_t', keep_empty=True)
    _holders(ctx)
    _raises(ctx)
