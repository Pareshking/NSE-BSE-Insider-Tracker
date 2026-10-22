"""Insiders: NSE + BSE insider, deal and corporate-event disclosures, cleaned.

    streamlit run streamlit_app/app.py

Reads the clean tables from R2 (clean/current/, written nightly). For local
work, point INSIDERS_LOCAL_DATA at a folder with the same layout.
"""
import sys
from pathlib import Path

import pandas as pd
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

from ui import nav as inapp  # noqa: E402
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
        st.Page(filings_all.render, title='Filings', icon=M('list'), url_path='filings-all'),
        st.Page(track_record.render, title='Evidence', icon=M('query_stats'), url_path='track-record'),   # last in the menu (owner, 22 Oct)
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
    parts = []   # the index line (Nifty 500, Smallcap 250, Microcap 250 vs 200D) is off the site (owner, 22 Oct)
    # The latest day only (owner, 22 Oct): what was made public that day, each filing and deal once (NSE and BSE
    # copies and market-maker legs are not counted, audit W1, W2). Deals carry their own last session.
    day = pd.Timestamp(ctx.ref).normalize() if ctx.ref is not None else None
    prim = ctx.trades['is_primary'].astype('boolean').fillna(False)
    on_day = pd.to_datetime(ctx.trades['broadcast_date'], errors='coerce').dt.normalize().eq(day)
    mkt = e['is_market'].astype('boolean').fillna(False) & pd.to_datetime(e['seen'], errors='coerce').dt.normalize().eq(day)
    dl = ctx.deals
    real = (dl['is_primary'].astype('boolean').fillna(False) & ~dl['client_is_market_maker'].astype('boolean').fillna(False)
            if not dl.empty else pd.Series(dtype=bool))
    when = pd.to_datetime(dl['date'], errors='coerce').dt.normalize() if not dl.empty else pd.Series(dtype='datetime64[ns]')
    deal_day = when[real].max() if real.any() else None
    n_deals = int((real & when.eq(deal_day)).sum()) if deal_day is not None and pd.notna(deal_day) else 0
    other_day = deal_day is not None and pd.notna(deal_day) and deal_day != day
    deals_word = 'deals' + (f' on {kit.day(deal_day, with_year=False)}' if other_day else '')
    parts += [f'<span><b>{int((prim & on_day).sum()):,}</b> filings</span>',   # short now: shown on a phone too
              f'<span><b>{int(mkt.sum()):,}</b> on the market</span>',
              f'<span><b>{n_deals:,}</b> {deals_word}</span>']
    parts.insert(0, f'<b>{kit.day(ctx.ref)}</b>' if ctx.ref is not None else 'No clean data yet')
    # One row under the top bar, as on screener.in: the data line on the left, a company search on the right.
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

# A link the pages draw (a company, a person, Filings) switches page in this session, with its own address.
inapp.links({**{p.url_path: p for p in ALL}, '': SECTIONS[''][0]})
inapp.apply_query()

nav.run()

# No footer line (owner, 22 Oct); the charts' credit, which their licence asks for, is on the Data quality page.
st.page_link(DATA_PAGE, label='How clean is the data?', icon=':material/fact_check:')
