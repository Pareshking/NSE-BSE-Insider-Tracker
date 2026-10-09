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
                   initial_sidebar_state='collapsed')

from screens import (
    capital_raises,
    company,
    data_status,
    deals,
    entity,
    insider_trades,
    screener,
    today,
    track_record,
)
from screens.ctx import load
from data import store
from ui import kit, theme

theme.inject()

PAGES = [
    st.Page(today.render, title='Today', url_path='today', default=True),
    st.Page(screener.render, title='Screener', url_path='screener'),
    st.Page(insider_trades.render, title='Insider trades', url_path='insider-trades'),
    st.Page(deals.render, title='Deals', url_path='deals'),
    st.Page(capital_raises.render, title='Capital raises', url_path='capital-raises'),
    st.Page(track_record.render, title='Track record', url_path='track-record'),
    st.Page(data_status.render, title='Data', url_path='data'),
]
# Reached by links (?symbol= / ?id=), not shown in the bar.
DETAIL = [
    st.Page(company.render, title='Company', url_path='company'),
    st.Page(entity.render, title='Person or fund', url_path='entity'),
]
# Old addresses keep working.
MOVED = {'confluence_screener': 'Screener', 'entity_tracker': 'Person or fund', 'transactions': 'Insider trades',
         'promoter_activity': 'Insider trades', 'bulk_block_concentration': 'Deals', 'data_quality': 'Data'}


def _redirect(path: str, target: str):
    def go():
        st.switch_page(next(p for p in PAGES + DETAIL if p.title == target))
    go.__name__ = f'moved_{path}'
    return st.Page(go, title=f'moved {path}', url_path=path)


nav = st.navigation(PAGES + DETAIL + [_redirect(p, t) for p, t in MOVED.items()], position='hidden')

ctx = load()
if ctx.ref is not None:
    pill, warn = f'Filings to {kit.day(ctx.ref)}', False
else:
    pill, warn = 'No clean data yet', True
active = nav if nav in PAGES else None
kit.topbar(PAGES, active, pill, warn)

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
