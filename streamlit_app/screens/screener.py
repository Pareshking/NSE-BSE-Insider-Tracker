"""High-conviction screener: which stocks show insider accumulation now?

Built to the owner's page spec (07-08 Oct 2026). Presets: Cluster buys,
Float absorbers, Breakout buyers (near 52W high), Turnaround accumulation,
Promoter warrants at premium. Columns: Company | Market cap / sector |
Signal badges | Net buy (Rs. Cr) | % of float | Insider details | CMP vs 52W
high. No conviction score (owner, 07 Oct 2026): factor badges only. Presets
and columns that need prices are shown as pending, never replaced."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from ui import kit

from insiders_clean import signals
from screens.ctx import load, need_data

PRESETS = {
    'All with insider buying': None,
    'Cluster buys': 'Cluster',
    'Float absorbers (0.5%+ in 90 days)': 'Float absorber',
    'Spotlight (0.15%+ in 30 days)': 'Spotlight',
    'Promoter selling': 'Promoter selling',
    'High pledge': 'High pledge',
}
PENDING = {
    'Breakout buyers (near 52W high)': 'needs the price join (docs/TODO.md #6)',
    'Turnaround accumulation': 'needs the price join (docs/TODO.md #6)',
    'Promoter warrants at premium': 'needs preferential issues cleaned and prices (TODO #6, #11)',
}


def render():
    ctx = load()
    kit.head('High-conviction screener', 'Stocks where promoters and officers are buying in the open market, ranked by '
                                         'net buying as a share of market cap over 90 days. ESOPs, gifts, transfers and '
                                         'token buys never count.')
    if not need_data(ctx):
        return
    board = signals.company_board(ctx.eligible, ctx.deals, ctx.shareholding, ctx.ref)
    if board.empty:
        kit.empty('No insider activity in the last 90 days.')
        return
    pick = st.pills('Preset', list(PRESETS) + list(PENDING), default='All with insider buying', key='scr_preset',
                    label_visibility='collapsed')
    if pick in PENDING:
        kit.note(f'{pick}: not available yet.', f'This preset {PENDING[pick]}.')
        return
    rows = board
    key = PRESETS.get(pick) if pick else None
    if key:
        rows = board[board['badges'].map(lambda b: any(x.startswith(key) for x in b))]
    elif pick == 'All with insider buying':
        rows = board[board['promoter_net'] > 0]
    q = st.text_input('Search', placeholder='Company or symbol', key='scr_q', label_visibility='collapsed')
    if q:
        rows = rows[rows['company'].str.contains(q, case=False, na=False)
                    | rows['nse_symbol'].astype(str).str.contains(q, case=False)]

    sec = ctx.securities.drop_duplicates('isin').set_index('isin') if not ctx.securities.empty else pd.DataFrame()
    pub = signals.public_pct_by_isin(ctx.shareholding)
    details = signals.insider_details(ctx.eligible, ctx.ref)
    mcap = pd.to_numeric(rows['market_cap'], errors='coerce')
    net = pd.to_numeric(rows['promoter_net'], errors='coerce')
    sector = rows['isin'].map(sec['sector']) if 'sector' in sec else pd.Series('', index=rows.index)
    show = rows.assign(
        link=rows['nse_symbol'].map(kit.company_href),
        cap_sector=[f'₹{m / 1e7:,.0f} Cr' + (f' · {s}' if isinstance(s, str) and s else '') if pd.notna(m) else (s or '')
                    for m, s in zip(mcap, sector)],
        signals=rows['badges'].map(', '.join),
        net_cr=net / 1e7,
        float_pct=pd.to_numeric(pd.Series([signals.float_pct(n, m, pub.get(i)) for n, m, i in zip(net, mcap, rows['isin'])],
                                          index=rows.index, dtype=object), errors='coerce'),
        who=rows['isin'].map(details),
        cmp_vs_high=None)
    with kit.card(f'{len(rows)} companies', 'screener', f'90 days to {kit.day(ctx.ref)}'):
        st.dataframe(show[['link', 'company', 'cap_sector', 'signals', 'net_cr', 'float_pct', 'promoter_net_pct',
                           'who', 'cmp_vs_high']],
                     hide_index=True, width='stretch', height=620, column_config={
                         'link': st.column_config.LinkColumn('', display_text='Open', width='small', pinned=True),
                         'company': st.column_config.TextColumn('Company', pinned=True),
                         'cap_sector': 'Market cap / sector',
                         'signals': 'Signal badges',
                         'net_cr': st.column_config.NumberColumn('Net buy (₹ Cr)', format='%+,.2f',
                                                                 help='Promoter and promoter group, open market, 90 days'),
                         'float_pct': st.column_config.NumberColumn('% of float', format='%.2f%%',
                                                                    help='Net buy / (market cap x public holding %)'),
                         'promoter_net_pct': st.column_config.NumberColumn('% of mcap', format='%+.3f%%'),
                         'who': 'Insider details',
                         'cmp_vs_high': st.column_config.TextColumn('CMP vs 52W high', help='Arrives with the price join')})
        kit.caption('% of float is blank where the shareholding pattern is not loaded yet. CMP vs 52W high arrives with the '
                    'price join. How each badge performed afterwards will be on Track record once measured.')
