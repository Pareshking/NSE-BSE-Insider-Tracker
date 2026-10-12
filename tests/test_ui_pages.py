"""Every page renders without an exception on real cleaned data.

The data folder is built here from the real fixtures through the production
pipeline (insiders_clean.pipeline.run and the NSE events parsers), in the
same layout the site reads from R2."""
from __future__ import annotations

import json

import pandas as pd
import pytest
from conftest import BSE_ROWS, FIXTURES, ROOT, RUN_DATE, canonical
from streamlit.testing.v1 import AppTest

from collectors.nse_events import parsers
from insiders_clean.calendar import seed_state
from insiders_clean.pipeline import run

APP_PATHS = f"""
import sys
sys.path.insert(0, r'{ROOT / "streamlit_app"}')
sys.path.insert(0, r'{ROOT}')
"""


@pytest.fixture(scope='module')
def data_dir(tmp_path_factory, real_nse_rows):
    root = tmp_path_factory.mktemp('site')
    cur = root / 'clean' / 'current'
    cur.mkdir(parents=True)
    deals = [{'event_date': '01/10/2026', 'security_code': '544717', 'security_name': 'CLEANMAX', 'company': 'CLEANMAX',
              'person': p, 'side': s, 'quantity': '100000', 'price': '1000', 'raw': []}
             for p, s in (('BIG BUYER FUND', 'BUY'), ('PROMOTER HOLDCO', 'SELL'))]
    vr = pd.read_csv(ROOT / 'reference_data' / 'security_master_20260901.csv', dtype=str, keep_default_na=False)
    tables, report = run({('nse', 'insider_trading'): canonical('nse', 'insider_trading', real_nse_rows),
                          ('bse', 'bulk_deals'): canonical('bse', 'bulk_deals', deals)},
                         RUN_DATE, seed_state(), vr_master=vr,
                         nse_lists=[pd.read_csv(FIXTURES / 'nse_equity_sample.csv', dtype=str)],
                         market_cap_rows=BSE_ROWS + [{'symbol': 'HCLTECH', 'market_cap': 4.0e12, 'source': 'pr_zip'},
                                                     {'symbol': 'ZEEL', 'market_cap': 6.9e10, 'source': 'pr_zip'}])
    ev = FIXTURES / 'nse_events'
    load = lambda n: json.loads((ev / n).read_text(encoding='utf-8'))
    # Trading window: a results meeting three days before the first open-market buy, through the real join.
    from insiders_clean import buybacks, trading_window
    from insiders_clean.calendar import Calendar
    t = tables['insider_trades']
    b = t[t['is_market'].astype(bool) & t['side'].eq('BUY') & t['nse_symbol'].notna()].iloc[0]
    meet = pd.DataFrame({'symbol': [b['nse_symbol']], 'results': [True], 'raw_json': ['[]'],
                         'meeting_date': [pd.Timestamp(b['trade_date_from'] or b['trade_date_to']) - pd.Timedelta(days=3)]})
    tables['insider_trades'] = trading_window.attach(
        t, meet, Calendar([d.date() for d in pd.bdate_range('2024-01-01', '2026-12-31')]))[0]
    for name, df in tables.items():
        if name != 'universe':   # fixture market caps cover few companies; the cutoff is tested in test_universe_filter_on_pages
            df.to_parquet(cur / f'{name}.parquet')
    acts = parsers.parse_corporate_actions(load('corporate_actions.json'))[0]
    tenders = parsers.parse_tender_offers(load('tender_offers_past.json')['data'], load('tender_offers_active.json'))
    bb = buybacks.build(tenders, parsers.parse_daily_buybacks(load('daily_buybacks.json')['data']), acts)[0]
    bb.loc[bb['symbol'] == 'INFY', 'isin'] = 'INE009A01021'
    bb.to_parquet(cur / 'buybacks.parquet')
    parsers.parse_sast(load('sast_reg29.json')).to_parquet(cur / 'sast.parquet')
    parsers.parse_corporate_actions(load('corporate_actions.json'))[0].to_parquet(cur / 'actions.parquet')
    parsers.parse_board_meetings(load('board_meetings.json'))[0].to_parquet(cur / 'meetings.parquet')
    sh = parsers.parse_shareholding_listing(load('shareholding_ZEEL.json'))
    sh['promoter_pledge_pct'] = 5.38
    sh.to_parquet(cur / 'shareholding.parquet')
    from test_issues import IN_P, LIST, frame as issue_frame, pref as issue_row

    from insiders_clean import issues as issue_clean
    pref_raw = issue_frame(issue_row('In-Principle', 1, isin='INE0V9N01017', posted='02-MAR-2026', **IN_P),
                           issue_row('Listing Stage', 2, isin='INE0V9N01017', posted='12-MAR-2026', **LIST),
                           issue_row('In-Principle', 5, isin='INE000000009', posted='09-OCT-2026', **IN_P))
    issue_clean.clean_issues(pref_raw, 'preferential')[0].to_parquet(cur / 'preferential.parquet')
    rights_raw = pd.DataFrame([{'canonical_event_id': 'r1', 'appId': '9', 'canonical_stage': 'Listing Stage',
                                'canonical_isin': 'INE0LXG01040', 'canonical_symbol': 'OLAELEC',
                                'canonical_company': 'OLA ELECTRIC MOBILITY LIMITED', 'sysDateTime': '09-OCT-2026',
                                'dtOfSubmission': '08-OCT-2026', 'offerPrice': '40', 'rightRatio': '1:5',
                                'ingested_at': '2026-10-10T02:01:03+00:00'},
                               {'canonical_event_id': 'r2', 'appId': '10', 'canonical_stage': 'Listing Stage',
                                'canonical_isin': 'INE860A01027', 'canonical_symbol': 'HCLTECH',
                                'canonical_company': 'HCL TECHNOLOGIES LIMITED', 'sysDateTime': '09-OCT-2026',
                                'dtOfSubmission': '08-OCT-2026', 'offerPrice': '1500', 'rightRatio': '1:10',
                                'ingested_at': '2026-10-10T02:01:03+00:00'}])
    issue_clean.clean_issues(rights_raw, 'rights')[0].to_parquet(cur / 'rights.parquet')
    # QIPs, allottees and filed lock-ins from the real further-issue fixtures, as scripts/clean_writer.py builds them
    import clean_writer
    from test_archive_and_writer import FakeR2, parquet
    from test_issue_filings import filings
    r2 = FakeR2()
    r2.objects['archive/nse_events/issues/year=2026.parquet'] = parquet(filings())
    extra, _ = clean_writer.issue_tables(r2)
    for name in ('preferential_lockins', 'preferential_allottees', 'qip', 'qip_allottees'):
        extra[name].to_parquet(cur / f'{name}.parquet')
    (root / 'clean' / 'report_local.json').write_text(json.dumps(report, default=str))
    (root / 'clean' / 'latest.json').write_text(json.dumps({'date': RUN_DATE, 'report': 'local'}))
    return root


PAGES = [('actions', {}), ('other_filings', {}), ('today', {}), ('screener', {}), ('insider_trades', {}), ('deals', {}), ('capital_raises', {}),
         ('track_record', {}), ('data_status', {}), ('company', {'symbol': 'HCLTECH'}), ('company', {}),
         ('entity', {'id': 'vama-sundari-investments-delh'}), ('entity', {}), ('sast', {}), ('transfers', {}),
         ('shareholding', {}), ('coming', {})]


@pytest.mark.parametrize(('screen', 'params'), PAGES, ids=[f'{s}-{bool(p)}' for s, p in PAGES])
def test_page_renders(data_dir, monkeypatch, screen, params):
    monkeypatch.setenv('INSIDERS_LOCAL_DATA', str(data_dir))
    code = APP_PATHS + f"""
import streamlit as st
for k, v in {params!r}.items():
    st.query_params[k] = v
from ui import theme
theme.inject()
import importlib
importlib.import_module('screens.{screen}').render()
"""
    at = AppTest.from_string(code, default_timeout=60)
    at.run()
    assert not at.exception, at.exception[0].value


def test_whole_app_renders_with_bar(data_dir, monkeypatch):
    monkeypatch.setenv('INSIDERS_LOCAL_DATA', str(data_dir))
    at = AppTest.from_file(str(ROOT / 'streamlit_app' / 'app.py'), default_timeout=60)
    at.run()
    assert not at.exception, at.exception[0].value


def test_company_board_survives_two_symbols_on_one_isin(real_nse_rows, master, calendar, report):
    """Seen on real data: two shareholding rows with one ISIN broke the
    Screener (pandas InvalidIndexError on the pledge lookup)."""
    from insiders_clean import signals
    from insiders_clean.insider import clean_insider
    t = signals.eligible(clean_insider(canonical('nse', 'insider_trading', real_nse_rows), master, calendar, report, RUN_DATE))
    sh = pd.DataFrame({'symbol': ['ZEEL', 'ZEEL-BE'], 'isin': ['INE256A01028', 'INE256A01028'],
                       'quarter_end': ['2026-06-30', '2026-06-30'], 'promoter_holding_pct': [3.99, 3.99],
                       'public_holding_pct': [96.01, 96.01], 'promoter_pledge_pct': [5.38, 5.38]})
    board = signals.company_board(t, None, sh, signals.as_of(t))
    assert not board.empty


def test_company_page_shows_capital_raises_tab_only_when_the_company_has_them(data_dir, monkeypatch):
    monkeypatch.setenv('INSIDERS_LOCAL_DATA', str(data_dir))
    labels = {}
    for sym in ('HCLTECH', 'ZEEL'):
        code = APP_PATHS + f"""
import streamlit as st
st.query_params['symbol'] = {sym!r}
from ui import theme
theme.inject()
from screens import company
company.render()
"""
        at = AppTest.from_string(code, default_timeout=60)
        at.run()
        assert not at.exception, at.exception[0].value
        labels[sym] = [t.label for t in at.tabs]
    assert 'Capital raises' in labels['HCLTECH']
    assert 'Capital raises' not in labels['ZEEL']


def test_window_open_buy_is_marked_and_buybacks_show_price_and_route(data_dir, monkeypatch):
    monkeypatch.setenv('INSIDERS_LOCAL_DATA', str(data_dir))
    out = {}
    for screen in ('insider_trades', 'capital_raises'):
        at = AppTest.from_string(APP_PATHS + f"""
from ui import theme
theme.inject()
from screens import {screen}
{screen}.render()
""", default_timeout=60)
        at.run()
        assert not at.exception, at.exception[0].value
        out[screen] = ' '.join(e.proto.srcdoc for e in at.get('iframe'))  # tables are drawn in st.iframe
    assert 'after the trading window reopened' in out['insider_trades']
    assert 'Tender offer' in out['capital_raises'] and 'Open market' in out['capital_raises'] and '₹1,800' in out['capital_raises']


def test_universe_filter_on_pages(data_dir, monkeypatch, tmp_path):
    """With a universe table, every page drops companies under Rs 100 Cr (insiders_clean/universe.py)."""
    import shutil
    root = tmp_path / 'site'
    shutil.copytree(data_dir, root)
    cur = root / 'clean' / 'current'
    t = pd.read_parquet(cur / 'insider_trades.parquet')
    isins = list(t['isin'].dropna().unique())
    keep, drop = isins[0], isins[1:]
    pd.DataFrame({'isin': isins, 'market_cap': [500e7] + [10e7] * len(drop),
                  'in_universe': [True] + [False] * len(drop)}).to_parquet(cur / 'universe.parquet')
    monkeypatch.setenv('INSIDERS_LOCAL_DATA', str(root))
    at = AppTest.from_string(APP_PATHS + """
import streamlit as st
st.cache_data.clear()   # earlier tests cached tables from a folder without a universe
from data import store
st_t = store.table('insider_trades')
all_t = store.table('insider_trades', everything=True)
import streamlit as st
st.write(f'{st_t["isin"].nunique()}|{all_t["isin"].nunique()}')
""", default_timeout=60)
    at.run()
    assert not at.exception
    shown, everything = at.markdown[0].value.split('|')
    assert shown == '1' and int(everything) == len(isins) > 1
