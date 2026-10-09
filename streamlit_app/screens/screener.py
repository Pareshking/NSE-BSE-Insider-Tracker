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
from screens.ctx import load, need_data, with_prices, with_sparks

PRESETS = {
    'All with insider buying': None,
    'Cluster buys': 'Cluster',
    'Float absorbers (0.5%+ in 90 days)': 'Float absorber',
    'Spotlight (0.15%+ in 30 days)': 'Spotlight',
    'Promoter selling': 'Promoter selling',
    'High pledge': 'High pledge',
}
# Price presets (exploratory, docs/SIGNALS.md): promoter net buying with the
# latest close within 5% of its 52-week high, or 30%+ below it.
NEAR_HIGH, FAR_BELOW_HIGH = -0.05, -0.30
PRICE_PRESETS = {'Breakout buyers (near 52W high)': lambda off: off >= NEAR_HIGH,
                 'Turnaround accumulation (30%+ below high)': lambda off: off <= FAR_BELOW_HIGH}
PENDING = {
    'Promoter warrants at premium': 'needs preferential issues cleaned (docs/TODO.md H)',
}


def render():
    ctx = load()
    kit.head('Screener', 'Where promoters are buying with their own money: 90 days, open market only, ranked by '
                         'net buying as a share of market cap.')
    if not need_data(ctx):
        return
    board = signals.company_board(ctx.eligible, ctx.deals, ctx.shareholding, ctx.ref)
    if board.empty:
        kit.empty('No insider activity in the last 90 days.')
        return
    pick = st.pills('Preset', list(PRESETS) + list(PRICE_PRESETS) + list(PENDING), default='All with insider buying', key='scr_preset',
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
    elif pick in PRICE_PRESETS:
        off = pd.to_numeric(with_prices(board, ctx.prices)['pct_off_high'], errors='coerce')
        rows = board[(board['promoter_net'] > 0) & off.map(lambda v: pd.notna(v) and PRICE_PRESETS[pick](v))]
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
    show = with_sparks(with_prices(rows, ctx.prices), ctx).assign(
        cap_sector=[f'₹{m / 1e7:,.0f} Cr' + (f' · {s}' if isinstance(s, str) and s else '') if pd.notna(m) else (s or '')
                    for m, s in zip(mcap, sector)],
        float_pct=[signals.float_pct(n, m, pub.get(i)) for n, m, i in zip(net, mcap, rows['isin'])],
        who=rows['isin'].map(details))
    with kit.card(f'{len(rows)} companies', 'screener', f'90 days to {kit.day(ctx.ref)} · by net buying as % of market cap'):
        kit.table(show, [
            kit.Col('company', 'Company', 'co'),
            kit.Col('badges', 'Signals', 'tags', phone=False),
            kit.Col('promoter_net', 'Promoter net', 'smoney', help='Promoter and promoter group, open market, 90 days'),
            kit.Col('promoter_net_pct', '% of mcap', 'bar'),
            kit.Col('float_pct', '% of float', 'pct', phone=False, help='Net buy / (market cap x public holding %)'),
            kit.Col('range', '52W range · CMP', 'range', help='Latest close between the 52-week low and high (split and bonus adjusted)'),
            kit.Col('spark', '1Y price · insider trades', 'spark', phone=False, help='Green dots: open-market insider buys; red: sells, on the day made public'),
            kit.Col('who', 'Who bought', 'text', sub='cap_sector', phone=False),
        ], limit=80, download='screener')
        kit.caption('% of float is blank where the shareholding pattern is not loaded yet; the range is blank where the '
                    'stock has no price in our NSE/BSE price files. How each badge performed afterwards will be on '
                    'Track record once measured.')
