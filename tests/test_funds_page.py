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
    assert 'Where did houses open a new position?' in html
    assert 'This month so far: what did funds buy and sell in bulk and block deals?' in html
    assert 'How is each house positioning?' in html
    assert 'Is this complete?' in html and 'ICICI Prudential Mutual Fund (its file service' in html
    assert '2 fund houses compared' in html


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


def test_funds_page_over_three_months_with_positioning_and_first_held(data_dir, tmp_path, monkeypatch):  # noqa: F811
    root = tmp_path / 'site'
    shutil.copytree(data_dir, root)
    cur = root / 'clean' / 'current'
    sec = pd.read_parquet(cur / 'securities.parquet').dropna(subset=['isin']).head(4)
    a, b, c, d = sec['isin'].tolist()
    rows = lambda month, vals: pd.DataFrame([{'amc': h, 'month': month, 'isin': i, 'name': f'Co {i}', 'shares': s, 'active_shares': s,  # noqa: E731
                                               'value_lakh': s * 500 / 1e5, 'kind': 'mf'} for h, i, s in vals])
    hs = [rows('2026-08', [('sbi', a, 1_000_000), ('hdfc', b, 500_000)]),
          rows('2026-09', [('sbi', a, 1_200_000), ('hdfc', b, 400_000), ('hdfc', c, 100_000)]),
          rows('2026-10', [('sbi', a, 1_300_000), ('hdfc', c, 300_000), ('sbi', d, 900_000), ('hdfc', d, 900_000)])]
    ch = m.tag_house_kind(pd.concat([m.changes(x, p) for p, x in zip(hs, hs[1:])], ignore_index=True), pd.concat(hs))
    ch.to_parquet(cur / 'mf_changes.parquet')
    m.stock_months(ch).to_parquet(cur / 'mf_stock_month.parquet')
    monkeypatch.setenv('INSIDERS_LOCAL_DATA', str(root))
    at = AppTest.from_string(APP_PATHS + """
import streamlit as st
st.cache_data.clear(); st.cache_resource.clear()
from screens import funds
funds.render()
""", default_timeout=90)
    at.run()
    assert not at.exception, at.exception[0].value
    html = ' '.join(e.proto.body for e in at.get('html'))
    assert 'What did houses take that no house held before?' in html and 'first held' in html   # d: nobody held it before
    assert 'How is each house positioning?' in html and 'Net active buying as a % of each house' in html
    assert 'Large, mid, small or micro' in html or 'Where did funds buy the largest share of the company?' in html
    at.segmented_control(key='fd_range').set_value('3 months').run()
    assert not at.exception, at.exception[0].value
    assert 'Sep 2026 to Oct 2026 (2 month-ends)' in ' '.join(e.proto.body for e in at.get('html'))


# ---- screens/funds_logic.py: the explorer's arithmetic, without Streamlit -------------------------------------------

def _fl():
    import sys

    from conftest import ROOT
    sys.path.insert(0, str(ROOT / 'streamlit_app'))
    from screens import funds_logic
    return funds_logic


def _h(month, vals, kind='mf'):
    """Holdings rows: (house, isin, shares) at a price of 100."""
    return pd.DataFrame([{'amc': h, 'month': month, 'isin': i, 'name': i, 'shares': s, 'active_shares': s,
                          'value_lakh': s * 100 / 1e5, 'kind': kind} for h, i, s in vals])


def _tables(*months_vals):
    """mf_changes and mf_stock_month from consecutive month-ends, as scripts/mf_portfolios.py builds them."""
    hs = [_h(mo, v) for mo, v in months_vals]
    ch = pd.concat([m.changes(c, p) for p, c in zip(hs, hs[1:])], ignore_index=True)
    ch = m.tag_house_kind(ch, pd.concat(hs))
    return ch, m.stock_months(ch)


A, B, C, J = 'INEA00001011', 'INEB00001011', 'INEC00001011', 'INEJ00001011'


def test_window_sums_months_and_status_compares_the_ends():
    fl = _fl()
    ch, st_ = _tables(('2026-08', [('sbi', A, 100), ('sbi', B, 50)]),
                      ('2026-09', [('sbi', A, 150), ('sbi', B, 50), ('sbi', C, 10)]),
                      ('2026-10', [('sbi', A, 120), ('sbi', C, 40)]))
    one = fl.house_rows(ch, st_, ['2026-10']).set_index('isin')
    assert one.loc[A, 'status'] == 'cut' and one.loc[A, 'net'] == -30
    assert one.loc[B, 'status'] == 'exit' and one.loc[C, 'status'] == 'added'
    # B was sold out by every house in October: valued at September's price, not left blank
    assert one.loc[B, 'net_cr'] == pytest.approx(-50 * 100 / 1e7)
    two = fl.house_rows(ch, st_, ['2026-09', '2026-10']).set_index('isin')
    assert two.loc[A, 'net'] == 20 and two.loc[A, 'status'] == 'added'      # 100 at the end of Aug -> 120
    assert two.loc[C, 'status'] == 'new' and two.loc[B, 'status'] == 'exit'


def test_default_month_skips_a_month_still_coming_in():
    fl = _fl()
    ch = pd.DataFrame({'amc': ['a', 'b', 'c', 'a'], 'month': ['2026-09'] * 3 + ['2026-10']})
    assert fl.default_month(ch) == '2026-09'
    assert fl.window(['2026-10', '2026-09', '2026-08'], '2026-10', 6) == ['2026-08', '2026-09', '2026-10']


def test_lists_rank_by_rupees_and_by_share_of_company():
    fl = _fl()
    sw = pd.DataFrame({'isin': ['L', 'S', 'X'], 'name': ['Large', 'Small', 'Sold'], 'houses_adding': [3, 1, 0],
                       'houses_cutting': [0, 0, 2], 'houses_new': [0, 1, 0], 'houses_exit': [0, 0, 1], 'houses_holding': [3, 1, 1],
                       'net': [1e6, 5e5, -1e5], 'net_cr': [500.0, 5.0, -2.0], 'new_cr': [None, 5.0, None],
                       'exit_cr': [None, None, -1.0], 'pct_of_company': [0.01, 2.5, -0.3]})
    v = fl.lists(sw)
    assert v['bought']['isin'].tolist() == ['L', 'S'] and v['sold']['isin'].tolist() == ['X']
    assert fl.by_pct(sw, 'buy')['isin'].tolist() == ['S', 'L']          # the small cap first by share of the company
    br = fl.bucket_rollup(sw, {'L': 'Large', 'S': 'Small'}).set_index('bucket')
    assert br.loc['Small', 'bought'] == 1 and br.loc['No size', 'sold'] == 1
    assert br.index.tolist() == ['Large', 'Small', 'No size']


def test_industry_cascade_falls_back_and_hides_empty_levels():
    fl = _fl()
    sec = pd.DataFrame({'isin': ['A', 'B', 'C'], 'sector': ['Fin', 'Fin', 'IT'], 'industry': ['Bank', 'NBFC', 'Software']})
    ind = fl.industry_frame(pd.DataFrame(), sec)
    assert fl.levels_with_data(ind) == ['sector', 'industry']             # macro and basic industry have no data
    assert fl.cascade_options(ind, {'sector': 'Fin'})['industry'] == ['Bank', 'NBFC']
    assert fl.filter_isins(ind, {'sector': 'Fin', 'industry': 'Bank'}) == {'A'}
    assert fl.filter_isins(ind, {'sector': None}) is None
    assert fl.next_level(ind, {'sector': 'Fin'}) == 'industry'
    four = pd.DataFrame({'isin': ['A'], 'macro': ['M'], 'sector': ['S'], 'industry': ['I'], 'basic_industry': ['B']})
    assert fl.levels_with_data(fl.industry_frame(four, sec)) == list(fl.LEVELS)
    r = fl.rollup(pd.DataFrame({'isin': ['A', 'C', 'Z'], 'net_cr': [5.0, -3.0, 1.0]}), ind, 'sector')
    assert r['label'].tolist() == ['Fin', fl.UNCLASSIFIED, 'IT']


def test_first_held_marks_stocks_no_house_held_before():
    fl = _fl()
    ch, st_ = _tables(('2026-09', [('sbi', A, 100)]), ('2026-10', [('sbi', A, 100)]),
                      ('2026-11', [('sbi', A, 100), ('sbi', J, 500), ('hdfc', J, 10)]))
    assert fl.first_held(st_, ['2026-11']) == {J}
    assert fl.first_held(st_, ['2026-10']) == set()                     # the table's first month: nothing is "first"


def test_house_positioning_normalises_by_prior_equity_and_flags_broad_moves():
    fl = _fl()
    # Big house: 10 positions of 1,000 shares, 10 more of each: 1% of its equity, every position up: broad add.
    # Small house: 5 positions of 100, halves 2 of them: -100 shares on 500 held, 40% of positions trimmed.
    big = [('big', f'INE{i:03d}A01011', 1000) for i in range(10)]
    small = [('small', f'INE{i:03d}A01011', 100) for i in range(5)]
    after = [(h, i, s + 10) for h, i, s in big] + [(h, i, s // 2 if n < 2 else s) for n, (h, i, s) in enumerate(small)]
    ch, st_ = _tables(('2026-09', big + small), ('2026-10', after))
    p = fl.house_positioning(ch, st_).set_index('amc')
    assert p.loc['big', 'flow_pct'] == pytest.approx(1.0)
    assert p.loc['big', 'net_cr'] == pytest.approx(100 * 100 / 1e7)
    assert p.loc['big', 'broad'] == 'broad add' and p.loc['big', 'added_pct'] == 100
    assert p.loc['small', 'flow_pct'] == pytest.approx(-20.0)
    assert p.loc['small', 'trimmed_pct'] == pytest.approx(40.0) and p.loc['small', 'broad'] == 'broad trim'
    assert fl.BROAD_SHARE == 0.40


def test_positioning_ignores_price_moves():
    """The same shares at both month-ends with one price halved: no flow, no shift in the size mix."""
    fl = _fl()
    a = _h('2026-09', [('h', A, 100), ('h', B, 100)])
    b = _h('2026-10', [('h', A, 100), ('h', B, 100)])
    b.loc[b['isin'] == A, 'value_lakh'] /= 2
    ch = m.tag_house_kind(m.changes(b, a), pd.concat([a, b]))
    p = fl.house_positioning(ch, m.stock_months(ch), size={A: 'Large', B: 'Small'}).iloc[0]
    assert p['flow_pct'] == 0 and p['broad'] == '' and all(abs(x) < 1e-9 for x in p['mix_shift'].values())


def test_deals_split_by_fund_type_and_name():
    """IIFL Finance, 18 Nov 2026: FIH Mauritius sold, mutual funds and insurers bought (values rounded for the test)."""
    fl = _fl()
    d = pd.DataFrame({'date': ['2026-11-18'] * 4 + ['2026-10-30'], 'isin': ['IIFL'] * 5, 'company': ['IIFL Finance'] * 5,
                      'is_primary': [True] * 5, 'client_is_market_maker': [False] * 5, 'client_is_promoter': [False] * 5,
                      'client_name': ['SBI MUTUAL FUND', 'NIPPON INDIA MUTUAL FUND', 'TATA AIG GENERAL INSURANCE', 'FIH MAURITIUS',
                                      'SBI MUTUAL FUND'],
                      'client_type': ['mutual_fund', 'mutual_fund', 'insurer', 'fpi', 'mutual_fund'],
                      'side': ['BUY', 'BUY', 'BUY', 'SELL', 'BUY'], 'signed_value': [50e7, 27e7, 10e7, -677e7, 1e7]})
    r = fl.deal_rows(d, '2026-11-01', '2026-11-18')
    assert len(r) == 4                                                  # October's deal is outside the month so far
    s = fl.deals_by_stock(r).iloc[0]
    assert s['mutual_fund'] == pytest.approx(77e7) and s['insurer'] == pytest.approx(10e7) and s['fpi'] == pytest.approx(-677e7)
    assert s['buyers'] == 3 and s['sellers'] == 1 and s['top_buyers'][0] == 'SBI MUTUAL FUND'
    f = fl.deals_by_fund(r).set_index('fund')
    assert f.loc['FIH MAURITIUS', 'net'] == pytest.approx(-677e7) and f.loc['SBI MUTUAL FUND', 'type'] == 'mutual_fund'


def test_coverage_is_by_value_over_every_company_filed():
    fl = _fl()
    a = _h('2026-08', [('h', A, 100), ('h', B, 100)])
    b = _h('2026-09', [('h', A, 100), ('h', B, 100)])
    b.loc[b['isin'] == A, 'value_lakh'] *= 9     # A at 900 a share, B at 100
    ch = m.tag_house_kind(m.changes(b, a), pd.concat([a, b]))
    sh = pd.DataFrame({'isin': [A, B], 'quarter_end': ['2026-09-30'] * 2, 'mf_shares': [200, 100]})
    c = fl.coverage_live(ch, m.stock_months(ch), sh, fl.quarter_month(['2026-09'], '2026-10'))
    # by value: (100 x 900 + 100 x 100) / (200 x 900 + 100 x 100)
    assert c['companies'] == 2 and c['held_companies'] == 2 and c['ratio'] == pytest.approx(100000 / 190000)


def test_missing_houses_names_the_ones_not_collected():
    fl = _fl()
    from collectors.mf_portfolios.houses import NOT_COLLECTED
    names = [n for n, _ in NOT_COLLECTED]
    assert 'ICICI Prudential Mutual Fund' in names and 'Kotak Mahindra Mutual Fund' in names
    mh = fl.missing_houses({'sbi'}, [('sbi', 'SBI'), ('hdfc', 'HDFC')], NOT_COLLECTED)
    assert mh['in'] == ['SBI'] and mh['absent'][0][0] == 'HDFC'


# ---- Scheme by scheme (19 Nov 2026) -------------------------------------------------------------------------------

def _scheme_frames(month, vals):
    return pd.DataFrame([{'amc': h, 'month': month, 'scheme_key': k, 'scheme': f'{h.upper()} {k.title()} Fund', 'isin': i,
                          'name': f'Co {i}', 'shares': s, 'value_lakh': s * 500 / 1e5, 'passive': False}
                         for h, k, i, s in vals])


@pytest.fixture(scope='module')
def site_schemes(data_dir, tmp_path_factory):  # noqa: F811
    """Two houses, three schemes, every table built as scripts/mf_portfolios.py builds it, from scheme rows."""
    root = tmp_path_factory.mktemp('funds_schemes') / 'site'
    shutil.copytree(data_dir, root)
    cur = root / 'clean' / 'current'
    sec = pd.read_parquet(cur / 'securities.parquet').dropna(subset=['isin']).head(3)
    a, b, c = sec['isin'].tolist()
    prev = _scheme_frames('2026-09', [('sbi', 'largecap', a, 600_000), ('sbi', 'smallcap', a, 400_000),
                                      ('nippon', 'flexicap', a, 500_000), ('sbi', 'largecap', b, 2_000_000)])
    now = _scheme_frames('2026-10', [('sbi', 'largecap', a, 1_100_000), ('sbi', 'smallcap', a, 300_000),
                                     ('nippon', 'flexicap', a, 900_000), ('sbi', 'largecap', b, 1_000_000),
                                     ('sbi', 'largecap', c, 300_000), ('nippon', 'flexicap', c, 200_000)])
    hp = m.house_from_schemes(prev).assign(value_lakh=1.0, kind='mf')
    hn = m.house_from_schemes(now).merge(now.groupby('isin', as_index=False)['value_lakh'].sum().rename(
        columns={'value_lakh': '_v'}), on='isin')
    hn = hn.assign(value_lakh=hn['shares'] * 500 / 1e5, kind='mf').drop(columns='_v')
    ch = m.tag_house_kind(m.changes(hn, hp), pd.concat([hp, hn]))
    ch.to_parquet(cur / 'mf_changes.parquet')
    stock = m.stock_months(ch).assign(total_shares=10_000_000.0)          # the company's shares on October's basis
    stock.to_parquet(cur / 'mf_stock_month.parquet')
    sc = m.value_scheme_changes(m.scheme_changes(now, prev).assign(house_kind='mf'), stock)
    m.scheme_month(sc).to_parquet(cur / 'mf_scheme_month.parquet')
    m.scheme_moves(sc).to_parquet(cur / 'mf_scheme_moves.parquet')
    lists = pd.concat([now.groupby(['amc', 'month', 'scheme_key'], as_index=False).agg(
        scheme=('scheme', 'first'), lines=('isin', 'size'), equity_lines=('isin', 'size'), passive=('passive', 'max'))])
    amfi = pd.DataFrame([{'amc': 'sbi', 'house': 'SBI Mutual Fund', 'scheme_key': k, 'scheme': f'SBI {k} Fund', 'category': 'equity',
                          'open_ended': True, 'plans': 4, 'date': '30-Oct-2026', 'month': '2026-10'}
                         for k in ('largecap', 'smallcap', 'midcap', 'contra', 'focused')])
    m.scheme_coverage(lists, amfi).to_parquet(cur / 'mf_scheme_coverage.parquet')
    return root, (a, b, c)


def _render(monkeypatch, root, extra=''):
    monkeypatch.setenv('INSIDERS_LOCAL_DATA', str(root))
    at = AppTest.from_string(APP_PATHS + """
import streamlit as st
st.cache_data.clear(); st.cache_resource.clear()
from screens import funds
funds.render()
""", default_timeout=90)
    at.run()
    assert not at.exception, at.exception[0].value
    return at


def test_funds_page_shows_which_schemes_bought_and_sold(site_schemes, monkeypatch):
    root, (a, b, c) = site_schemes
    at = _render(monkeypatch, root)
    html = ' '.join(e.proto.body for e in at.get('html'))
    assert 'Which schemes bought and sold?' in html
    assert 'SBI Largecap Fund' in html and 'NIPPON Flexicap Fund' in html and 'SBI Smallcap Fund' in html
    head = html.split('Which schemes bought and sold?')[1].split('Where did funds buy')[0]
    assert head.index('NIPPON Flexicap Fund') < head.index('Net sellers') < head.index('SBI Smallcap Fund')
    # Stock a: both houses added; inside SBI the large cap scheme added and the small cap scheme cut
    assert '2 houses · 2 schemes adding · 0 houses · 1 scheme cutting' in html
    # % of the company over the month-end basis count (mf_stock_month.total_shares), 800,000 of 10,000,000
    assert '+8.00%' in html


def test_one_house_view_picks_a_scheme(site_schemes, monkeypatch):
    root, (a, b, c) = site_schemes
    at = _render(monkeypatch, root)
    pick = next(s for s in at.selectbox if s.label.startswith('Scheme ('))
    assert pick.label == 'Scheme (2 that moved)'          # SBI: large cap and small cap
    pick.set_value('smallcap').run()
    assert not at.exception
    html = ' '.join(e.proto.body for e in at.get('html'))
    assert '<b>SBI Smallcap Fund</b>: added to 0 stocks' in html and 'cut 1 for' in html


def test_is_this_complete_shows_the_scheme_count_check(site_schemes, monkeypatch):
    root, _ = site_schemes
    html = ' '.join(e.proto.body for e in _render(monkeypatch, root).get('html'))
    part = html.split('id="complete"')[1]
    assert 'Schemes read, October 2026' in part and '1 flagged' in part
    assert 'fewer schemes read' in part and '2 of 5' in part   # SBI: 2 active equity read, AMFI lists 5


def test_scheme_rows_take_the_window_ends_from_rows_that_moved():
    fl = _fl()
    mv = pd.DataFrame([
        {'month': '2026-09', 'amc': 'sbi', 'house_kind': 'mf', 'scheme_key': 'largecap', 'isin': A, 'shares_start': 100.0,
         'shares_end': 150.0, 'change_cr': 5.0, 'scheme_seen': 'both'},
        {'month': '2026-10', 'amc': 'sbi', 'house_kind': 'mf', 'scheme_key': 'largecap', 'isin': A, 'shares_start': 150.0,
         'shares_end': 0.0, 'change_cr': -15.0, 'scheme_seen': 'both'},
        {'month': '2026-10', 'amc': 'sbi', 'house_kind': 'mf', 'scheme_key': 'newfund', 'isin': A, 'shares_start': 0.0,
         'shares_end': 70.0, 'change_cr': 7.0, 'scheme_seen': 'end_only'}])
    r = fl.scheme_rows(mv, ['2026-09', '2026-10']).set_index('scheme_key')
    assert r.loc['largecap', 'start'] == 100 and r.loc['largecap', 'end'] == 0 and r.loc['largecap', 'status'] == 'exit'
    assert r.loc['largecap', 'net_cr'] == -10 and bool(r.loc['newfund', 'one_end'])
    cnt = fl.scheme_counts(fl.scheme_rows(mv, ['2026-09', '2026-10'])).iloc[0]
    assert cnt['schemes_adding'] == 0 and cnt['schemes_cutting'] == 1   # the scheme new in the files is not counted
    t = fl.scheme_totals(fl.scheme_rows(mv, ['2026-10'])).set_index('scheme_key')
    assert t.loc['newfund', 'new'] == 1 and t.loc['largecap', 'exits'] == 1


def test_month_total_shares_prefers_the_month_end_basis():
    fl = _fl()
    st_ = pd.DataFrame({'month': ['2026-10'], 'isin': [A], 'total_shares': [455403140.0]})
    assert fl.month_total_shares(st_, '2026-10', {A: 45540314}) == {A: 455403140.0}
    assert fl.month_total_shares(st_.drop(columns='total_shares'), '2026-10', {A: 45540314}) == {A: 45540314}
