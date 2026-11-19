"""The Funds page (streamlit_app/screens/funds.py) on the real-data fixture plus month-end fund tables."""
from __future__ import annotations

import shutil

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest
from test_ui_pages import APP_PATHS, data_dir  # noqa: F401

from insiders_clean import mf_holdings as m


@pytest.fixture(scope='module')
def site(data_dir, tmp_path_factory):  # noqa: F811
    root = tmp_path_factory.mktemp('funds') / 'site'
    shutil.copytree(data_dir, root)
    cur = root / 'clean' / 'current'
    sec = pd.read_parquet(cur / 'securities.parquet').dropna(subset=['isin']).head(3)
    a, b, c = sec['isin'].tolist()
    rows = lambda month, vals: pd.DataFrame([{'amc': h, 'month': month, 'isin': i, 'name': f'Co {i}', 'shares': s, 'active_shares': s,  # noqa: E731
                                               'value_lakh': s * 500 / 1e5} for h, i, s in vals])
    prev = rows('2026-09', [('sbi', a, 1_000_000), ('nippon', a, 500_000), ('sbi', b, 2_000_000)])
    now = rows('2026-10', [('sbi', a, 1_400_000), ('nippon', a, 900_000), ('sbi', b, 1_000_000), ('sbi', c, 300_000),
                           ('nippon', c, 200_000)])
    ch = m.changes(now, prev)
    ch.to_parquet(cur / 'mf_changes.parquet')
    m.by_stock(ch).assign(month='2026-10').to_parquet(cur / 'mf_stock_month.parquet')
    pd.DataFrame([{'month': '2026-09', 'houses': 2, 'companies': 2, 'median_ratio': 0.3, 'weighted_ratio': 0.42}]).to_parquet(
        cur / 'mf_coverage.parquet')
    return root, (a, b, c)


def test_funds_page_lists_buying_selling_and_new_positions(site, monkeypatch):
    root, (a, b, c) = site
    monkeypatch.setenv('INSIDERS_LOCAL_DATA', str(root))
    at = AppTest.from_string(APP_PATHS + """
import streamlit as st
st.cache_data.clear(); st.cache_resource.clear()
from ui import theme
theme.inject()
from screens import funds
funds.render()
""", default_timeout=90)
    at.run()
    assert not at.exception, at.exception[0].value
    html = ' '.join(e.proto.body for e in at.get('html'))
    assert 'What did fund managers buy most in October 2026?' in html
    assert '2 adding · 0 cutting' in html            # a: both houses added
    assert '0 adding · 1 cutting' in html            # b: sbi cut
    assert 'held 42% of the shares mutual funds held' in html
    assert 'Where did 2 or more houses start a position?' in html


def test_mutual_fund_lists_have_no_pension_section_without_pension_rows(site, monkeypatch):
    root, _ = site
    monkeypatch.setenv('INSIDERS_LOCAL_DATA', str(root))
    at = AppTest.from_string(APP_PATHS + """
import streamlit as st
st.cache_data.clear(); st.cache_resource.clear()
from screens import funds
funds.render()
""", default_timeout=90)
    at.run()
    assert not at.exception, at.exception[0].value
    assert 'NPS pension funds' not in ' '.join(e.proto.body for e in at.get('html'))


@pytest.fixture(scope='module')
def site_nps(data_dir, tmp_path_factory):  # noqa: F811
    """Two mutual fund houses and two NPS pension fund managers, tables built as scripts/mf_portfolios.py builds them."""
    root = tmp_path_factory.mktemp('funds_nps') / 'site'
    shutil.copytree(data_dir, root)
    cur = root / 'clean' / 'current'
    sec = pd.read_parquet(cur / 'securities.parquet').dropna(subset=['isin']).head(3)
    a, b, c = sec['isin'].tolist()
    kind = {'sbi': 'mf', 'nippon': 'mf', 'nps_sbi': 'pension', 'nps_lic': 'pension'}
    rows = lambda month, vals: pd.DataFrame([{'amc': h, 'month': month, 'isin': i, 'name': f'Co {i}', 'shares': s, 'active_shares': s,  # noqa: E731
                                               'value_lakh': s * 500 / 1e5, 'kind': kind[h]} for h, i, s in vals])
    prev = rows('2026-09', [('sbi', a, 1_000_000), ('nippon', a, 500_000), ('nps_sbi', b, 9_000_000), ('nps_lic', b, 4_000_000),
                            ('nps_sbi', c, 1_000_000)])
    now = rows('2026-10', [('sbi', a, 1_400_000), ('nippon', a, 900_000), ('nps_sbi', b, 12_000_000), ('nps_lic', b, 5_000_000),
                           ('nps_sbi', c, 200_000)])
    ch = m.tag_house_kind(m.changes(now, prev), pd.concat([prev, now]))
    ch.to_parquet(cur / 'mf_changes.parquet')
    m.stock_months(ch).to_parquet(cur / 'mf_stock_month.parquet')
    pd.DataFrame([{'month': '2026-09', 'houses': 2, 'companies': 2, 'median_ratio': 0.3, 'weighted_ratio': 0.42}]).to_parquet(
        cur / 'mf_coverage.parquet')
    return root


def test_funds_page_shows_nps_pension_funds_apart(site_nps, monkeypatch):
    monkeypatch.setenv('INSIDERS_LOCAL_DATA', str(site_nps))
    at = AppTest.from_string(APP_PATHS + """
import streamlit as st
st.cache_data.clear(); st.cache_resource.clear()
from screens import funds
funds.render()
""", default_timeout=90)
    at.run()
    assert not at.exception, at.exception[0].value
    html = ' '.join(e.proto.body for e in at.get('html'))
    assert '2 fund houses' in html                          # the head counts mutual fund houses only
    assert 'What did NPS pension funds add and cut?' in html
    assert '2 NPS pension fund managers' in html and 'not as stock picks' in html
    assert '2 adding · 0 cutting' in html                   # a by the two mutual funds; b by the two pension managers
    assert '0 adding · 1 cutting' in html                   # c: nps_sbi cut
    assert 'held 42% of the shares mutual funds held' in html
    mf_part = html.split('What did NPS pension funds add and cut?')[0]
    assert '0 adding · 1 cutting' not in mf_part            # the pension cut is not in the mutual fund lists


def test_funds_page_waits_for_its_data(data_dir, monkeypatch):  # noqa: F811
    monkeypatch.setenv('INSIDERS_LOCAL_DATA', str(data_dir))
    at = AppTest.from_string(APP_PATHS + """
import streamlit as st
st.cache_data.clear(); st.cache_resource.clear()
from screens import funds
funds.render()
""", default_timeout=90)
    at.run()
    assert not at.exception, at.exception[0].value
    assert 'not collected yet' in ' '.join(e.proto.body for e in at.get('html'))
