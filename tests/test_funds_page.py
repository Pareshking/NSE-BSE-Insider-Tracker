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
