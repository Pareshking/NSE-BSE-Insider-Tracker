"""Substantial acquisitions: SEBI SAST Regulation 29 disclosures -- anyone
crossing 5% of a company or moving 2%+ after that, promoters included."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from ui import kit

from screens.ctx import load, need_data


def render():
    ctx = load()
    kit.head('Substantial acquisitions', 'SAST Regulation 29: anyone crossing 5% of a company, or moving 2% or more '
                                         'after that.')
    if not need_data(ctx):
        return
    s = ctx.sast
    if s.empty:
        kit.empty('SAST filings arrive with the daily NSE events collection.')
        return
    s = s.copy()
    s['transaction_date'] = pd.to_datetime(s['transaction_date'], errors='coerce')
    s['seen'] = pd.to_datetime(s['broadcast_ts'], errors='coerce', format='mixed', dayfirst=True)
    prom = s['is_promoter'].astype('boolean').fillna(False)
    acq = s['action_type'].astype(str).str.lower().str.startswith('acq')
    kit.tiles([
        kit.Tile('Disclosures', kit.count(len(s)), f'{kit.day(s["seen"].min())} to {kit.day(s["seen"].max())}'),
        kit.Tile('Outside investors', kit.count(int((~prom).sum())), f'{kit.plural(int((~prom & acq).sum()), "acquisition")} · '
                 f'{kit.plural(int((~prom & ~acq).sum()), "sale")}'),
        kit.Tile('Promoter group', kit.count(int(prom.sum())), f'{kit.plural(int((prom & acq).sum()), "acquisition")} · '
                 f'{kit.plural(int((prom & ~acq).sum()), "sale")}'),
        kit.Tile('Crossed 5% or more', kit.count(int((pd.to_numeric(s['post_stake_pct'], errors='coerce') >= 5).sum())),
                 'stake after the transaction'),
    ])
    c1, c2 = st.columns([1, 2], vertical_alignment='center')
    who = c1.segmented_control('Who', ['Outside investors', 'Promoter group', 'All'], default='Outside investors',
                               key='sast_who', label_visibility='collapsed') or 'All'
    q = c2.text_input('Search', placeholder='Search company or acquirer', key='sast_q', label_visibility='collapsed')
    rows = s[~prom] if who == 'Outside investors' else s[prom] if who == 'Promoter group' else s
    if q:
        rows = rows[rows['company'].str.contains(q, case=False, na=False)
                    | rows['acquirer_name'].str.contains(q, case=False, na=False)]
    with kit.card(f'{kit.plural(len(rows), "disclosure")}', 'sast_tbl', 'newest first · % of share capital as filed'):
        kit.table(rows.sort_values('seen', ascending=False).assign(nse_symbol=rows['symbol']), [
            kit.Col('company', 'Company', 'co'), kit.Col('seen', 'Made public', 'date'),
            kit.Col('acquirer_name', 'Acquirer / seller', sub='mode'), kit.Col('action_type', 'Action'),
            kit.Col('transaction_date', 'Transaction', 'date', phone=False),
            kit.Col('shares_traded', 'Shares', 'shares', phone=False),
            kit.Col('percent_equity_traded', '% traded', 'spct'), kit.Col('post_stake_pct', 'Stake after', 'pct'),
            kit.Col('regulation', 'Rule', phone=False)], limit=300, download='sast')
