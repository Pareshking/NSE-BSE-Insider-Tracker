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
                   initial_sidebar_state='collapsed')   # the phone menu opened over every page (audit 22 Oct)

from screens import (
    coming,
    company,
    data_status,
    entity,
    filings_all,
    home,
    track_record,
)
from screens.ctx import load
from data import store
from ui import kit, theme

theme.inject()

M = lambda name: f':material/{name}:'  # noqa: E731 -- Material icon shortcode
# Redesign of 21 Oct 2026 (docs/REVAMP_PLAN.md): one page per question, each piece shown once. Market replaces
# Actions, Morning brief, Latest session, Screener and Shareholding & pledges; the filing pages follow into one
# Filings page next.
SECTIONS = {
    '': [
        st.Page(home.render, title='Today', icon=M('today'), url_path='today', default=True),
        st.Page(company.render, title='Companies', icon=M('apartment'), url_path='company'),
        st.Page(track_record.render, title='Evidence', icon=M('query_stats'), url_path='track-record'),
        st.Page(filings_all.render, title='Filings', icon=M('list'), url_path='filings-all'),
    ],
}
def _search_picked():
    """The top search: remember the company, clear the box (so the next page does not jump again)."""
    pick = st.session_state.get('top_search')
    if pick:
        st.session_state['_go_symbol'] = pick.rsplit(' · ', 1)[1]
    st.session_state['top_search'] = None


COMPANY_PAGE = next(p for p in SECTIONS[''] if p.url_path == 'company')
# Reachable by address and from the footer, not in the menu: they are about the data, not a signal.
DATA_PAGE = st.Page(data_status.render, title='Data quality', icon=M('fact_check'), url_path='data', visibility='hidden')
HIDDEN = [DATA_PAGE, st.Page(entity.render, title='People & funds', icon=M('person_search'), url_path='entity', visibility='hidden'), st.Page(coming.render, title='Coming next', icon=M('hourglass_top'), url_path='coming', visibility='hidden')]
ALL = [p for ps in SECTIONS.values() for p in ps] + HIDDEN
# Old addresses keep working.
MOVED = {'confluence_screener': 'Today', 'entity_tracker': 'People & funds', 'transactions': 'Filings', 'promoter_activity': 'Filings',
         'bulk_block_concentration': 'Filings', 'data_quality': 'Data quality', 'sast': 'Filings', 'transfers': 'Filings',
         'filings': 'Today',   # AI filing cards off the site (owner, 21 Oct); the reader code is kept
         'market': 'Today', 'actions': 'Today', 'brief': 'Today', 'screener': 'Today', 'shareholding': 'Today',
         'insider-trades': 'Filings', 'deals': 'Filings', 'other-filings': 'Filings', 'capital-raises': 'Filings'}


def _redirect(path: str, target: str):
    def go():
        st.switch_page(next(p for p in ALL if p.title == target))
    go.__name__ = f'moved_{path}'
    return st.Page(go, title=f'moved {path}', url_path=path, visibility='hidden')


st.logo(str(HERE / 'ui' / 'logo.svg'), size='large', link=None)
nav = st.navigation(SECTIONS[''] + HIDDEN + [_redirect(p, t) for p, t in MOVED.items()], position='top')   # top bar, no side menu (owner, 21 Oct)

ctx = load()

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
    parts.insert(0, f'<b>Filings to {kit.day(ctx.ref)}</b>' if ctx.ref is not None else 'No clean data yet')
    # One row under the top bar, as on screener.in: the market line on the left, a company search on the right.
    left, right = st.columns([5, 2], vertical_alignment='center', gap='small')
    with left:
        kit.strip(parts)
    with right:
        sec = ctx.securities.dropna(subset=['nse_symbol']).drop_duplicates('nse_symbol') if not ctx.securities.empty else ctx.securities
        names = sec['display_name'] if 'display_name' in sec else sec.get('company', sec['nse_symbol'])
        options = sorted(f'{n} · {s}' for n, s in zip(names, sec['nse_symbol'])) if len(sec) else []
        st.selectbox('Search a company', options, index=None, placeholder='Search a company',
                     key='top_search', label_visibility='collapsed', on_change=_search_picked)
    go = st.session_state.pop('_go_symbol', None)
    if go:
        st.switch_page(COMPANY_PAGE, query_params={'symbol': go})

nav.run()

st.html('<p class="foot">NSE and BSE disclosures, cleaned nightly · prices from the NSE and BSE daily bhavcopy, '
        'split and bonus adjusted · check the exchange filing before acting.</p>')
st.page_link(DATA_PAGE, label='How clean is the data?', icon=':material/fact_check:')
