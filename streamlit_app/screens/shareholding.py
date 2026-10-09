"""Shareholding and pledges: each company's latest quarterly shareholding
pattern -- promoter, public and employee-trust holdings, pledged and
encumbered promoter shares -- with the change from the quarter before."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from ui import kit

from insiders_clean import signals
from screens.ctx import load, need_data, with_prices, with_sparks


def render():
    ctx = load()
    kit.head('Shareholding and pledges', "Each company's latest quarterly pattern: promoter and public holding, and how "
                                         'much of the promoters\' stake is pledged.')
    if not need_data(ctx):
        return
    sh = ctx.shareholding
    if sh.empty:
        kit.empty('Shareholding patterns arrive with the daily NSE events collection.')
        return
    s = sh.copy()
    s['quarter_end'] = pd.to_datetime(s['quarter_end'], errors='coerce')
    for c in ('promoter_holding_pct', 'public_holding_pct', 'promoter_pledge_pct', 'promoter_encumbered_pct'):
        s[c] = pd.to_numeric(s.get(c), errors='coerce')
    s = s.sort_values('quarter_end')
    last = s.drop_duplicates('symbol', keep='last').set_index('symbol')
    prev = s[~s.index.isin(s.drop_duplicates('symbol', keep='last').index)].drop_duplicates('symbol', keep='last').set_index('symbol')
    last['promoter_chg'] = last['promoter_holding_pct'] - prev['promoter_holding_pct'].reindex(last.index)
    last['pledge_chg'] = last['promoter_pledge_pct'] - prev['promoter_pledge_pct'].reindex(last.index)
    rows = last.reset_index().rename(columns={'symbol': 'nse_symbol'})
    high = rows['promoter_pledge_pct'] > signals.HIGH_PLEDGE_PCT
    kit.tiles([
        kit.Tile('Companies covered', kit.count(len(rows)), f'latest quarter {kit.day(rows["quarter_end"].max())}'),
        kit.Tile('With promoter pledge', kit.count(int((rows['promoter_pledge_pct'] > 0).sum())), 'any pledged promoter shares'),
        kit.Tile(f'Pledge above {signals.HIGH_PLEDGE_PCT:.0f}%', kit.count(int(high.sum())), 'of the promoters\' own shares',
                 'down' if high.any() else ''),
        kit.Tile('Promoter stake up', kit.count(int((rows['promoter_chg'] > 0).sum())),
                 f'{kit.plural(int((rows["promoter_chg"] < 0).sum()), "company", "companies")} down, vs the quarter before'),
    ])
    view = st.segmented_control('Show', ['All', 'Pledged', 'Promoter stake changed'], default='All', key='sh_view',
                                label_visibility='collapsed') or 'All'
    if view == 'Pledged':
        rows = rows[rows['promoter_pledge_pct'] > 0].sort_values('promoter_pledge_pct', ascending=False)
    elif view == 'Promoter stake changed':
        rows = rows[rows['promoter_chg'].fillna(0) != 0].sort_values('promoter_chg', key=lambda x: x.abs(), ascending=False)
    else:
        rows = rows.sort_values('promoter_pledge_pct', ascending=False, na_position='last')
    with kit.card(kit.plural(len(rows), 'company', 'companies'), 'sh_tbl', 'latest quarter filed on NSE'):
        kit.table(with_sparks(with_prices(rows, ctx.prices), ctx), [
            kit.Col('company', 'Company', 'co'), kit.Col('quarter_end', 'Quarter', 'date'),
            kit.Col('promoter_holding_pct', 'Promoter', 'pct'), kit.Col('promoter_chg', 'Δ QoQ', 'spct'),
            kit.Col('public_holding_pct', 'Public', 'pct', phone=False),
            kit.Col('promoter_pledge_pct', 'Pledged', 'pct', help="% of the promoters' own shares"),
            kit.Col('pledge_chg', 'Δ pledge', 'spct', phone=False),
            kit.Col('promoter_encumbered_pct', 'Encumbered', 'pct', phone=False, help='Pledge plus other encumbrances'),
            kit.Col('spark', '1Y price · insider trades', 'spark', phone=False)], limit=300, download='shareholding')
    kit.caption('Coverage grows nightly as more companies file and their XBRL is read (at most 300 a night). '
                'Δ QoQ is in percentage points against the same company\'s previous filed quarter.')
