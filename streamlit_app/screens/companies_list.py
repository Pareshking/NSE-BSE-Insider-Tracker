"""Companies: a list to screen, read from the nightly company snapshot (insiders_clean/snapshot.py).

One row per company: who owns it (promoters, funds, foreign investors), what changed since the last quarter filed,
the pledge, and what the decision-makers did in the last 90 days. The row opens the company's page."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from data import store
from ui import kit
from ui.kit import Col

LIMIT = 100
SIZES = ['Large', 'Mid', 'Small', 'Micro']
SORTS = {'Market cap': ('market_cap', False), 'Insiders net, 90 days': ('insider_net_90d', False),
         'Funds adding (points)': ('mf_change_pts', False), 'Foreign investors adding (points)': ('fpi_change_pts', False),
         'Promoter pledge': ('pledge', False)}
COLS = [
    Col('company', 'Company', 'co2', wrap=True),
    Col('promoter', 'Promoters', 'pct', help='Share held by promoters, latest quarter filed'),
    Col('promoter_change_pts', 'Change', 'spct', phone=False, help='Points since the quarter before'),
    Col('pledge', 'Pledged', 'pct', help='Share of promoter holding pledged, latest filed'),
    Col('mf', 'Mutual funds', 'pct'),
    Col('mf_change_pts', 'Change', 'spct', phone=False),
    Col('fpi', 'Foreign investors', 'pct'),
    Col('fpi_change_pts', 'Change', 'spct', phone=False),
    Col('insider_net_90d', 'Insiders net, 90 days', 'smoney', help='Open-market buys minus sells by promoters, directors and KMP'),
    Col('last_insider_buy', 'Last insider buy', 'date', phone=False),
]


def render_list() -> None:
    snap = store.snapshot()
    kit.head('Companies', 'Who owns each company, what changed last quarter, and what its insiders did.')
    if snap.empty:
        kit.note('Not built yet.', 'The nightly run writes the company snapshot; this list fills in after its first run.')
        return
    with st.container(key='co_filters', horizontal=True, vertical_alignment='center', gap='small'):
        q = st.text_input('Search', placeholder='Company or symbol', key='cl_q', type='search', label_visibility='collapsed', width=260)
        sizes = st.pills('Size', SIZES, selection_mode='multi', key='cl_size', label_visibility='collapsed')
        sort = st.selectbox('Sort', list(SORTS), key='cl_sort', label_visibility='collapsed')
    d = snap.copy()
    if q:
        hit = lambda c: d[c].astype(str).str.contains(q, case=False, na=False, regex=False)  # noqa: E731
        d = d[hit('company') | hit('symbol')]
    if sizes:
        d = d[d['mcap_bucket'].isin(sizes)]
    col, asc = SORTS[sort]
    d = d.sort_values(col, ascending=asc, na_position='last', kind='stable')
    d['nse_symbol'] = d['symbol']
    d['mk_bucket'], d['mk_cap'], d['mk_px'], d['mk_lo'], d['mk_hi'] = (
        d['mcap_bucket'], d['market_cap'], d['latest_close'], d['low_52w'], d['high_52w'])
    kit.caption(f'{kit.count(len(d))} companies. A figure is the latest quarter the company filed; a dash means none filed.')
    kit.table(d, COLS, limit=LIMIT, key='cl_t', keep_empty=True, empty_text='No company matches.')


def strip(sym: str) -> None:
    """The ratios strip under a company's quote: ownership and what changed, from the snapshot."""
    snap = store.snapshot()
    if snap.empty:
        return
    row = snap[snap['symbol'].astype(str).str.upper() == sym.upper()]
    if row.empty:
        return
    r = row.iloc[0]

    def tile(label, val, chg=None, quarter=None):
        if val is None or pd.isna(val):
            return None
        delta = '' if chg is None or pd.isna(chg) else f' <span class="{"up" if chg > 0 else "down" if chg < 0 else ""}">{chg:+.2f} pts</span>'
        when = '' if quarter is None or pd.isna(quarter) else f' <span class="q-k">{pd.Timestamp(quarter):%b %Y}</span>'
        return f'<span class="q-k">{label}</span><b class="num">{val:.2f}%</b>{delta}{when}'
    bits = [tile('Promoters', r.get('promoter'), r.get('promoter_change_pts'), r.get('promoter_quarter')),
            tile('Pledged', r.get('pledge'), r.get('pledge_change_pts'), r.get('pledge_quarter')),
            tile('Funds', r.get('mf'), r.get('mf_change_pts'), r.get('mf_quarter')),
            tile('Foreign', r.get('fpi'), r.get('fpi_change_pts'), r.get('fpi_quarter'))]
    net = r.get('insider_net_90d')
    if pd.notna(net):
        bits.append(f'<span class="q-k">Insiders net, 90 days</span><b class="num {"up" if net > 0 else "down" if net < 0 else ""}">'
                    f'{kit.rupees(net, signed=True)}</b>')
    bits = [b for b in bits if b]
    if bits:
        st.html('<div class="quote">' + ''.join(bits) + '</div>')
