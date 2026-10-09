"""Insiders: NSE + BSE insider, deal and corporate-event disclosures, cleaned.

    streamlit run streamlit_app/app.py

Reads the clean tables from R2 (clean/current/, written nightly). For local
work, point INSIDERS_LOCAL_DATA at a folder with the same layout.
"""
import sys
from pathlib import Path

import streamlit as st

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))  # insiders_clean, shared with the pipeline

st.set_page_config(page_title='Insiders', page_icon='\U0001f4c8', layout='wide',
                   initial_sidebar_state='expanded')

from screens import (
    capital_raises,
    coming,
    company,
    data_status,
    deals,
    entity,
    insider_trades,
    sast,
    screener,
    shareholding,
    today,
    track_record,
    transfers,
)
from screens.ctx import load
from data import store
from ui import kit, theme

theme.inject()

M = lambda name: f':material/{name}:'  # noqa: E731 -- Material icon shortcode
SECTIONS = {
    'Overview': [
        st.Page(today.render, title='Dashboard', icon=M('space_dashboard'), url_path='today', default=True),
        st.Page(screener.render, title='Screener', icon=M('filter_alt'), url_path='screener'),
    ],
    'Transactions': [
        st.Page(insider_trades.render, title='Insider & promoter trades', icon=M('swap_vert'), url_path='insider-trades'),
        st.Page(deals.render, title='Bulk & block deals', icon=M('handshake'), url_path='deals'),
        st.Page(sast.render, title='Substantial acquisitions', icon=M('account_tree'), url_path='sast'),
        st.Page(transfers.render, title='Inter-se & off-market', icon=M('sync_alt'), url_path='transfers'),
    ],
    'Ownership': [
        st.Page(shareholding.render, title='Shareholding & pledges', icon=M('pie_chart'), url_path='shareholding'),
    ],
    'Corporate events': [
        st.Page(capital_raises.render, title='Capital raises & actions', icon=M('event'), url_path='capital-raises'),
        st.Page(coming.render, title='Preferential title='Preferential, rights, warrants' rights', icon=M('hourglass_top'), url_path='coming'),
    ],
    'Analytics': [
        st.Page(track_record.render, title='Track record', icon=M('query_stats'), url_path='track-record'),
        st.Page(data_status.render, title='Data quality', icon=M('fact_check'), url_path='data'),
    ],
    'Look up': [
        st.Page(company.render, title='Company', icon=M('apartment'), url_path='company'),
        st.Page(entity.render, title='Person or fund', icon=M('person_search'), url_path='entity'),
    ],
}
ALL = [p for ps in SECTIONS.values() for p in ps]
# Old addresses keep working.
MOVED = {'confluence_screener': 'Screener', 'entity_tracker': 'Person or fund', 'transactions': 'Insider & promoter trades',
         'promoter_activity': 'Insider & promoter trades', 'bulk_block_concentration': 'Bulk & block deals',
         'data_quality': 'Data quality'}


def _redirect(path: str, target: str):
    def go():
        st.switch_page(next(p for p in ALL if p.title == target))
    go.__name__ = f'moved_{path}'
    return st.Page(go, title=f'moved {path}', url_path=path, visibility='hidden')


st.logo(str(HERE / 'ui' / 'logo.svg'), size='large', link=None)
nav = st.navigation({**SECTIONS, '': [_redirect(p, t) for p, t in MOVED.items()]}, position='sidebar', expanded=True)

ctx = load()
with st.sidebar:
    st.html(f'<div class="sb-foot"><span class="pill{"" if ctx.ref is not None else " warn"}"><i></i>'
            + (f'Filings to {kit.day(ctx.ref)}' if ctx.ref is not None else 'No clean data yet') + '</span>'
            '<p>NSE + BSE disclosures, cleaned nightly</p></div>')

if not ctx.trades.empty:
    e = ctx.eligible
    parts = []
    for m in store.market_strip()[:3]:
        vs = m.get('vs_200d')
        tone = 'up' if vs is not None and vs >= 0 else 'down'
        parts.append(f'{kit.esc(m["index"].replace("Nifty Smallcap", "Smallcap").replace("Nifty Microcap", "Microcap"))} <b>{m["close"]:,.0f}</b>'
                     + (f' <em class="{tone}">{vs * 100:+.1f}% vs 200D</em>' if vs is not None else ''))
    parts += [f'<span class="opt"><b>{len(ctx.trades):,}</b> filings</span>',
              f'<span class="opt"><b>{int(e["is_market"].sum()):,}</b> open-market</span>',
              f'<span class="opt"><b>{len(ctx.deals):,}</b> deals</span>']
    kit.strip(parts)

nav.run()

st.html('<p class="foot">NSE and BSE disclosures, cleaned nightly · prices from the NSE and BSE daily bhavcopy, '
        'split and bonus adjusted · check the exchange filing before acting.</p>')
