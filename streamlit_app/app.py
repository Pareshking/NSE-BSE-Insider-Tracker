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


def _reload_changed_pipeline_modules():
    """Streamlit Cloud re-runs the changed files under streamlit_app/ after a
    push but keeps modules imported from the repo root (insiders_clean) as
    first loaded, so a page calling a function added in the same push fails
    until the app restarts (12 Oct 2026: signals.with_tradability on every
    page with badges). Reload each one this process has not checked yet or
    whose file changed since; the dates live on `sys`, which outlives reruns."""
    import importlib
    import os
    seen = sys.__dict__.setdefault('_insiders_clean_mtimes', {})
    for name in sorted(n for n in list(sys.modules) if n == 'insiders_clean' or n.startswith('insiders_clean.')):
        path = getattr(sys.modules.get(name), '__file__', None)
        if not path or not os.path.exists(path) or seen.get(name) == os.path.getmtime(path):
            continue
        try:
            importlib.reload(sys.modules[name])
        except Exception:  # noqa: BLE001 -- a file mid-update: tried again on the next run
            continue
        seen[name] = os.path.getmtime(path)


_reload_changed_pipeline_modules()

st.set_page_config(page_title='Insiders', page_icon='\U0001f4c8', layout='wide',
                   initial_sidebar_state='expanded')

from screens import (
    actions,
    brief,
    capital_raises,
    coming,
    company,
    data_status,
    deals,
    entity,
    insider_trades,
    other_filings,
    screener,
    shareholding,
    today,
    track_record,
)
from screens.ctx import load
from data import store
from ui import kit, theme

theme.inject()

M = lambda name: f':material/{name}:'  # noqa: E731 -- Material icon shortcode
SECTIONS = {
    'Signals': [
        st.Page(actions.render, title='Actions', icon=M('bolt'), url_path='actions', default=True),
        st.Page(brief.render, title='Morning brief', icon=M('wb_sunny'), url_path='brief'),
        st.Page(screener.render, title='Screener', icon=M('filter_alt'), url_path='screener'),
        st.Page(track_record.render, title='Track record', icon=M('query_stats'), url_path='track-record'),
    ],
    'Filings': [
        st.Page(today.render, title='Latest session', icon=M('space_dashboard'), url_path='today'),
        st.Page(insider_trades.render, title='Insider & promoter trades', icon=M('swap_vert'), url_path='insider-trades'),
        st.Page(deals.render, title='Bulk & block deals', icon=M('handshake'), url_path='deals'),
        st.Page(other_filings.render, title='Other filings', icon=M('account_tree'), url_path='other-filings'),
    ],
    'Companies': [
        st.Page(company.render, title='Company', icon=M('apartment'), url_path='company'),
        st.Page(entity.render, title='Person or fund', icon=M('person_search'), url_path='entity'),
        st.Page(capital_raises.render, title='Capital raises & actions', icon=M('event'), url_path='capital-raises'),
        st.Page(shareholding.render, title='Shareholding & pledges', icon=M('pie_chart'), url_path='shareholding'),
    ],
}
# Reachable by address and from the footer, not in the menu: they are about the data, not a signal.
DATA_PAGE = st.Page(data_status.render, title='Data quality', icon=M('fact_check'), url_path='data', visibility='hidden')
HIDDEN = [DATA_PAGE, st.Page(coming.render, title='Coming next', icon=M('hourglass_top'), url_path='coming', visibility='hidden')]
ALL = [p for ps in SECTIONS.values() for p in ps] + HIDDEN
# Old addresses keep working.
MOVED = {'confluence_screener': 'Screener', 'entity_tracker': 'Person or fund', 'transactions': 'Insider & promoter trades',
         'promoter_activity': 'Insider & promoter trades', 'bulk_block_concentration': 'Bulk & block deals',
         'data_quality': 'Data quality', 'sast': 'Other filings', 'transfers': 'Other filings',
         'filings': 'Latest session'}   # AI filing cards off the site (owner, 21 Oct); the reader code is kept


def _redirect(path: str, target: str):
    def go():
        st.switch_page(next(p for p in ALL if p.title == target))
    go.__name__ = f'moved_{path}'
    return st.Page(go, title=f'moved {path}', url_path=path, visibility='hidden')


st.logo(str(HERE / 'ui' / 'logo.svg'), size='large', link=None)
nav = st.navigation({**SECTIONS, '': HIDDEN + [_redirect(p, t) for p, t in MOVED.items()]}, position='sidebar', expanded=True)

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
    # Each filing and deal once: NSE and BSE copies and market-maker legs are not counted (audit W1, W2).
    prim = ctx.trades['is_primary'].astype('boolean').fillna(False)
    dl = ctx.deals
    n_deals = int((dl['is_primary'].astype('boolean').fillna(False)
                   & ~dl['client_is_market_maker'].astype('boolean').fillna(False)).sum()) if not dl.empty else 0
    parts += [f'<span class="opt"><b>{int(prim.sum()):,}</b> filings</span>',
              f'<span class="opt"><b>{int(e["is_market"].sum()):,}</b> open-market</span>',
              f'<span class="opt"><b>{n_deals:,}</b> deals</span>']
    kit.strip(parts)

nav.run()

st.html('<p class="foot">NSE and BSE disclosures, cleaned nightly · prices from the NSE and BSE daily bhavcopy, '
        'split and bonus adjusted · check the exchange filing before acting.</p>')
st.page_link(DATA_PAGE, label='How clean is the data?', icon=':material/fact_check:')
