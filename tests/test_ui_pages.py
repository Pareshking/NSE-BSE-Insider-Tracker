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
    for name, df in tables.items():
        df.to_parquet(cur / f'{name}.parquet')
    ev = FIXTURES / 'nse_events'
    load = lambda n: json.loads((ev / n).read_text(encoding='utf-8'))
    parsers.parse_sast(load('sast_reg29.json')).to_parquet(cur / 'sast.parquet')
    parsers.parse_corporate_actions(load('corporate_actions.json'))[0].to_parquet(cur / 'actions.parquet')
    parsers.parse_board_meetings(load('board_meetings.json'))[0].to_parquet(cur / 'meetings.parquet')
    sh = parsers.parse_shareholding_listing(load('shareholding_ZEEL.json'))
    sh['promoter_pledge_pct'] = 5.38
    sh.to_parquet(cur / 'shareholding.parquet')
    (root / 'clean' / 'report_local.json').write_text(json.dumps(report, default=str))
    (root / 'clean' / 'latest.json').write_text(json.dumps({'date': RUN_DATE, 'report': 'local'}))
    return root


PAGES = [('today', {}), ('screener', {}), ('insider_trades', {}), ('deals', {}), ('capital_raises', {}),
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
