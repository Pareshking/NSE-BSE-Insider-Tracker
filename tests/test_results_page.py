"""The Results page (streamlit_app/screens/results.py, 19 Nov 2026): financial-year quarters, the size and industry
filters, the KPI arithmetic, and the page drawn on the site's own data folder."""
from __future__ import annotations

import shutil
import sys
from types import SimpleNamespace

import pandas as pd
import pytest
from conftest import ROOT
from streamlit.testing.v1 import AppTest
from test_ui_pages import APP_PATHS, data_dir  # noqa: F401 -- the site's data folder, built from the real fixtures

sys.path.insert(0, str(ROOT / 'streamlit_app'))

from screens import more_pages  # noqa: E402
from screens import results as rp  # noqa: E402


# ---- financial-year quarters ----------------------------------------------------------------------------------------

@pytest.mark.parametrize(('end', 'want'), [
    ('2026-06-30', (2027, 1)), ('2026-09-30', (2027, 2)), ('2026-12-31', (2027, 3)), ('2027-03-31', (2027, 4)),
    ('2026-03-31', (2026, 4)), ('2025-06-30', (2026, 1)), ('2025-12-31', (2026, 3)),
    ('2026-10-02', (2027, 2)),   # a 52-week year closing in the first days of a month: the month before
    ('2026-04-01', (2026, 4)),
])
def test_fy_quarter_of_an_indian_financial_year(end, want):
    assert rp.fy_quarter(end) == want


def test_fy_quarter_labels():
    assert rp.fy_quarter('not a date') is None and rp.fy_quarter(None) is None
    assert rp.period_label(2027, 2) == 'Q2 FY27' and rp.fy_long(2027) == 'FY27 (Apr 2026 – Mar 2027)'
    assert rp.quarter_months(2027, 1) == 'Apr–Jun 2026' and rp.quarter_months(2027, 4) == 'Jan–Mar 2027'
    assert rp.quarter_months(2027, 3) == 'Oct–Dec 2026'


def test_default_period_is_the_latest_quarter_with_meaningful_data():
    # December's first 40 filers are not "the latest quarter" while September has 1,900
    assert rp.default_period({(2027, 1): 1800, (2027, 2): 1900, (2027, 3): 40}) == (2027, 2)
    assert rp.default_period({(2027, 1): 1800, (2027, 2): 1900, (2027, 3): 700}) == (2027, 3)
    assert rp.default_period({}) is None


# ---- rows, filters, KPIs --------------------------------------------------------------------------------------------

def _res(rows):
    """Clean results rows: (isin, period end, revenue, profit), consolidated, each filed 40 days after its quarter."""
    df = pd.DataFrame(rows, columns=['isin', 'period_end', 'quarter_revenue', 'quarter_profit'])
    end = pd.to_datetime(df['period_end'])
    return df.assign(symbol=df['isin'], company=df['isin'] + ' Ltd', consolidated='Consolidated', superseded=False,
                     broadcast_at=(end + pd.Timedelta(days=40)).dt.strftime('%Y-%m-%dT10:00:00+05:30'))


CR = 1e7
RESULTS = _res([
    # A: revenue +20%, profit +50%                       B: revenue -10%, back to profit
    ('A', '2025-09-30', 100 * CR, 10 * CR), ('A', '2026-09-30', 120 * CR, 15 * CR),
    ('B', '2025-09-30', 200 * CR, -5 * CR), ('B', '2026-09-30', 180 * CR, 8 * CR),
    # C: revenue +5%, into loss                          D: no year-ago quarter in our history
    ('C', '2025-09-30', 50 * CR, 2 * CR), ('C', '2026-09-30', 52.5 * CR, -1 * CR),
    ('D', '2026-09-30', 30 * CR, 3 * CR),
    # E: a profit 10x its revenue: held back             F: a tiny base, +400%
    ('E', '2025-09-30', 20 * CR, 1 * CR), ('E', '2026-09-30', 25 * CR, 250 * CR),
    ('F', '2025-09-30', 1 * CR, 0.1 * CR), ('F', '2026-09-30', 5 * CR, 0.5 * CR),
    # A in the June quarter (another FY quarter)
    ('A', '2026-06-30', 110 * CR, 12 * CR),
])
PRICES = pd.DataFrame({'isin': list('ABCDEF'), 'market_cap': [9e12, 5e11, 2e11, 4e10, 1e10, 5e9],
                       'mcap_rank': [10, 200, 300, 700, 900, 1500],
                       'mcap_bucket': ['Large', 'Mid', 'Small', 'Micro', 'Micro', 'Micro']})
INDUSTRY = pd.DataFrame({'isin': list('ABCDE'), 'nse_symbol': list('ABCDE'),
                         'macro': ['Industrials', 'Industrials', 'Industrials', 'Financial Services', None],
                         'sector': ['Capital Goods', 'Capital Goods', 'Construction', 'Financial Services', None],
                         'industry': ['Electrical Equipment', 'Industrial Products', 'Construction', 'Finance', None],
                         'basic_industry': [None] * 5})


@pytest.fixture(scope='module')
def rows():
    r = more_pages._latest_results(SimpleNamespace(results=RESULTS, ref=pd.Timestamp('2026-11-19')), 100_000)
    ind, src = rp.industry_map(INDUSTRY, None)
    assert src == 'industry classification'
    return rp.prepare(r, PRICES, ind)


def test_rows_carry_the_quarter_the_comparisons_and_the_size(rows):
    a = rows[(rows['isin'] == 'A') & (rows['q'] == 2)].iloc[0]
    assert (a['fy'], a['q']) == (2027, 2) and round(a['rev_yoy_'], 6) == 20 and round(a['profit_yoy'], 6) == 50
    assert round(a['margin'], 4) == 12.5 and a['mcap_bucket'] == 'Large' and a['sector'] == 'Capital Goods'
    assert rows.loc[(rows['isin'] == 'A') & (rows['q'] == 1), 'fy'].tolist() == [2027]
    b = rows[(rows['isin'] == 'B') & (rows['fy'] == 2027)].iloc[0]
    assert bool(b['to_profit']) and pd.isna(b['profit_yoy'])   # a year-ago loss: a swing, not a growth rate
    assert rows.loc[(rows['isin'] == 'E') & (rows['fy'] == 2027), 'doubt'].iloc[0] == 'profit over 3x revenue'
    d = rows[rows['isin'] == 'D'].iloc[0]
    assert pd.isna(d['rev_yoy_']) and pd.isna(d['profit_yoy'])   # no history: blank, never a guess


def test_kpis_count_and_median_only_what_can_be_compared(rows):
    k = rp.kpis(rp.apply_filters(rows, 2027, 2))
    assert k['reported'] == 6 and k['held'] == 1                  # E held back
    # revenue compared: A +20, B -10, C +5, F +400 (D has no year ago, E is held back)
    assert (k['rev_n'], k['rev_up']) == (4, 3) and k['rev_median'] == pytest.approx(12.5)
    # profit compared where the year-ago profit is above zero: A +50, C -150, F +400 (B was a loss)
    assert (k['profit_n'], k['profit_up']) == (3, 2) and k['profit_median'] == pytest.approx(50)
    assert (k['to_profit'], k['to_loss']) == (1, 1)
    assert rp.kpis(pd.DataFrame())['reported'] == 0


def test_size_filter_keeps_one_bucket(rows):
    assert set(rp.apply_filters(rows, 2027, 2, 'Micro')['isin']) == {'D', 'E', 'F'}
    assert set(rp.apply_filters(rows, 2027, 2, 'Large')['isin']) == {'A'}
    assert set(rp.apply_filters(rows, 2027, 1)['isin']) == {'A'}
    assert rp.apply_filters(rows, 2026, 3).empty


def test_industry_filters_cascade(rows):
    period = rp.apply_filters(rows, 2027, 2)
    levels = ['macro', 'sector', 'industry']
    opts, left = rp.cascade(period, levels, {'macro': 'Industrials'})
    assert dict(opts)['macro'] == ['Financial Services', 'Industrials']
    assert dict(opts)['sector'] == ['Capital Goods', 'Construction']            # only Industrials' sectors
    assert set(left['isin']) == {'A', 'B', 'C'}
    opts, left = rp.cascade(period, levels, {'macro': 'Industrials', 'sector': 'Capital Goods'})
    assert dict(opts)['industry'] == ['Electrical Equipment', 'Industrial Products'] and set(left['isin']) == {'A', 'B'}
    # a pick that is no longer an option (its macro changed) counts as All
    _, left = rp.cascade(period, levels, {'macro': 'Financial Services', 'sector': 'Capital Goods'})
    assert set(left['isin']) == {'D'}
    assert set(rp.apply_filters(rows, 2027, 2, 'Mid', {'sector': 'Capital Goods'}, levels)['isin']) == {'B'}


def test_industry_falls_back_to_the_security_master_and_hides_empty_levels():
    sec = pd.DataFrame({'isin': ['A', 'B'], 'nse_symbol': ['A', 'B'], 'sector': ['Materials', ''], 'industry': ['Cement', None]})
    ind, src = rp.industry_map(pd.DataFrame(), sec)
    assert src.startswith('security master') and [c for c in ind if c in dict(rp.LEVELS)] == ['sector', 'industry']
    assert ind['isin'].tolist() == ['A']                               # B has no classification: not a blank one
    empty = pd.DataFrame({'isin': ['A'], 'macro': [None], 'sector': [None], 'industry': [None], 'basic_industry': [None]})
    assert rp.industry_map(empty, sec)[1].startswith('security master')   # an empty four-level table is not used
    assert rp.industry_map(None, None)[0].empty


def test_movers_and_rollup(rows):
    group = rp.apply_filters(rows, 2027, 2)
    up, down = rp.movers(group)
    assert up['isin'].tolist() == ['A', 'C'] and down['isin'].tolist() == ['B']   # F's ₹1 Cr base is not ranked
    ru = rp.rollup(group, 'macro')
    assert ru['group'].tolist() == ['Industrials'] and ru.iloc[0]['rev_median'] == pytest.approx(5)
    assert ru.iloc[0]['rev_up'] == '2 of 3'                            # Financial Services: one company, left out


# ---- the page ------------------------------------------------------------------------------------------------------

@pytest.fixture(scope='module')
def results_dir(data_dir, tmp_path_factory):  # noqa: F811
    root = tmp_path_factory.mktemp('results_site')
    shutil.copytree(data_dir, root, dirs_exist_ok=True)
    # filed before the fixture's data date (Oct 2026): the June quarters of 2025 and 2026
    res = RESULTS[RESULTS['period_end'].str.endswith('-09-30')].copy()
    res['period_end'] = res['period_end'].str.replace('-09-30', '-06-30')
    res['broadcast_at'] = (pd.to_datetime(res['period_end']) + pd.Timedelta(days=40)).dt.strftime('%Y-%m-%dT10:00:00+05:30')
    res.to_parquet(root / 'clean' / 'current' / 'results.parquet')
    INDUSTRY.to_parquet(root / 'clean' / 'current' / 'industry.parquet')
    (root / 'artifacts').mkdir(exist_ok=True)
    PRICES.to_parquet(root / 'artifacts' / 'prices_summary_slim.parquet')
    return root


def _page(folder, monkeypatch, state=None):
    monkeypatch.setenv('INSIDERS_LOCAL_DATA', str(folder))
    at = AppTest.from_string(APP_PATHS + """
import streamlit as st
st.cache_data.clear(); st.cache_resource.clear()
from ui import theme
theme.inject()
from screens import proto
proto.results()
""", default_timeout=60)
    for k, v in (state or {}).items():
        at.session_state[k] = v
    at.run()
    assert not at.exception, at.exception[0].value
    return at, ' '.join(e.proto.body for e in at.get('html'))


def test_results_page_draws_kpis_filters_and_table(results_dir, monkeypatch):
    at, h = _page(results_dir, monkeypatch)
    assert 'Q1 FY27' in h and 'Apr–Jun 2026' in h
    assert '>Reported<' in h and '>Held back<' in h and '>Median revenue YoY<' in h and '>Swung<' in h
    assert 'Who grew most, and who shrank most?' in h and 'profit over 3x revenue' in h
    assert '/company?symbol=A' in h and 'Electrical Equipment' in h
    labels = [s.label for s in at.selectbox]
    assert labels[:1] == ['Financial year'] and 'Macro sector' in labels and 'Basic industry' not in labels   # empty level hidden


def test_results_page_filters_by_size(results_dir, monkeypatch):
    _, h = _page(results_dir, monkeypatch, {'rs_size': 'Large'})
    assert '/company?symbol=A' in h and '/company?symbol=B' not in h


def test_results_page_without_results_says_so(data_dir, monkeypatch):  # noqa: F811
    _, h = _page(data_dir, monkeypatch)
    assert 'No quarterly results in the data' in h
