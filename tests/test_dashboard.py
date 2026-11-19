"""The Dashboard (streamlit_app/screens/dashboard.py): each tile's arithmetic on small frames, and the page on the
real-data fixture with market flows, fund month-ends and FPI sector flows added."""
from __future__ import annotations

import shutil
import sys

import pandas as pd
import pytest
from conftest import ROOT
from streamlit.testing.v1 import AppTest
from test_ui_pages import APP_PATHS, data_dir  # noqa: F401

sys.path.insert(0, str(ROOT / 'streamlit_app'))

from screens import dashboard as D  # noqa: E402

REF = pd.Timestamp('2026-11-19')


def trades(rows):
    """Eligible insider rows: (isin, role, side, value, days before REF, promoter_group_id)."""
    return pd.DataFrame([{'isin': i, 'company': f'Co {i}', 'nse_symbol': i, 'person_role': r, 'side': s, 'value': v,
                          'seen': REF - pd.Timedelta(days=d), 'is_token': False, 'promoter_group_id': g, 'person_id': f'p{i}{r}'}
                         for i, r, s, v, d, g in rows])


def test_insider_kpi_nets_buying_against_selling_and_counts_promoter_companies():
    t = trades([('A', 'promoter', 'BUY', 5e7, 3, None), ('B', 'director', 'BUY', 2e7, 10, None),
                ('C', 'kmp', 'SELL', 1e7, 5, None), ('D', 'designated_person', 'BUY', 9e9, 2, None),   # not a decision-maker
                ('E', 'other', 'BUY', 3e7, 4, 'grp-e'),             # in the promoter group by the shareholding pattern
                ('A', 'promoter', 'BUY', 4e7, 45, None),             # the 30 days before
                ('F', 'director', 'BUY', 1e7, 75, None)])            # older: the data reaches back past both periods
    k = D.insider_kpi(t, REF, 30)
    assert k['net'] == pytest.approx(5e7 + 2e7 - 1e7)
    assert k['promoter_companies'] == 1          # 'E' is role other: insider_breadth leaves it out, so does the count
    assert k['net_before'] == pytest.approx(4e7) and k['promoter_companies_before'] == 1
    assert len(k['spark']) == D.SPARK_WEEKS and sum(k['spark']) == pytest.approx(5e7 + 2e7 - 1e7 + 4e7 + 1e7)


def test_insider_kpi_says_nothing_without_data():
    assert D.insider_kpi(pd.DataFrame(), REF) is None


def flows():
    rows = []
    for d, v in (('2026-10-03', 100.0), ('2026-10-20', -40.0), ('2026-11-04', -10.0), ('2026-11-18', -25.0)):
        rows.append({'date': d, 'source': 'nsdl', 'segment': 'equity', 'category': 'fpi', 'net_cr': v})
    rows.append({'date': '2026-11-18', 'source': 'nsdl', 'segment': 'debt_general', 'category': 'fpi', 'net_cr': 999.0})
    for d, f, i in (('2026-11-18', -500.0, 300.0), ('2026-11-19', 200.0, -100.0)):
        rows += [{'date': d, 'source': 'nse', 'segment': 'cash_nse_bse_msei', 'category': 'fpi', 'net_cr': f},
                 {'date': d, 'source': 'nse', 'segment': 'cash_nse_bse_msei', 'category': 'dii', 'net_cr': i},
                 {'date': d, 'source': 'nse', 'segment': 'cash_nse', 'category': 'dii', 'net_cr': 7.0}]
    rows.append({'date': '2026-11-04', 'source': 'sebi', 'segment': 'equity', 'category': 'mf', 'net_cr': 55.0})
    return pd.DataFrame(rows)


def test_fpi_month_to_date_from_nsdl_equity_and_the_latest_nse_day():
    k = D.fpi_kpi(flows())
    assert k['month'] == '2026-11' and k['mtd'] == pytest.approx(-35.0) and k['mtd_days'] == 2
    assert k['prev'] == pytest.approx(60.0) and k['prev_month'] == '2026-10'
    assert k['nse_net'] == pytest.approx(200.0) and k['nse_day'] == pd.Timestamp('2026-11-19')


def test_fpi_leads_with_the_secondary_market_and_names_the_primary_part():
    # NSDL's November 2026 to the 18th as published: Stock Exchange 1,00,365.32, primary market & others 5,863.52, equity 1,06,228.84
    rows = [{'date': '2026-10-31', 'source': 'nsdl', 'category': 'fpi', 'segment': s, 'net_cr': v}
            for s, v in (('equity', -34843.0), ('equity_exchange', -48082.0), ('equity_primary', 13239.0))]
    rows += [{'date': '2026-11-18', 'source': 'nsdl', 'category': 'fpi', 'segment': s, 'net_cr': v}
             for s, v in (('equity', 106228.84), ('equity_exchange', 100365.32), ('equity_primary', 5863.52))]
    k = D.fpi_kpi(pd.DataFrame(rows))
    assert k['secondary'] and k['mtd'] == pytest.approx(100365.32) and k['prev'] == pytest.approx(-48082.0)
    assert k['primary'] == pytest.approx(5863.52) and k['total'] == pytest.approx(106228.84)
    assert 'in the market this month' in D.headline(None, k, None)
    assert not D.fpi_kpi(flows())['secondary']   # no routes held: the equity total, as before


def test_dii_is_the_latest_nse_day_on_all_exchanges_and_says_how_many_days_are_kept():
    k = D.dii_kpi(flows())
    assert k['net'] == pytest.approx(-100.0) and k['before'] == pytest.approx(300.0)
    assert k['days_kept'] == 2 and k['month_net'] == pytest.approx(200.0)
    assert D.dii_kpi(flows()[lambda f: f['source'] != 'nse']) is None
    assert D.fpi_kpi(pd.DataFrame()) is None


def stock():
    return pd.DataFrame([
        {'month': '2026-09', 'house_kind': 'mf', 'isin': 'A', 'name': 'Co A', 'active_net_cr': 10.0, 'houses_adding': 2, 'houses_cutting': 0},
        {'month': '2026-10', 'house_kind': 'mf', 'isin': 'A', 'name': 'Co A', 'active_net_cr': 30.0, 'houses_adding': 4, 'houses_cutting': 1},
        {'month': '2026-10', 'house_kind': 'mf', 'isin': 'B', 'name': 'Co B', 'active_net_cr': -12.0, 'houses_adding': 0, 'houses_cutting': 3},
        {'month': '2026-10', 'house_kind': 'mf', 'isin': 'C', 'name': 'Co C', 'active_net_cr': 0.4, 'houses_adding': 1, 'houses_cutting': 0},
        {'month': '2026-10', 'house_kind': 'pension', 'isin': 'B', 'name': 'Co B', 'active_net_cr': 500.0, 'houses_adding': 5, 'houses_cutting': 0}])


def test_mf_kpi_is_active_mutual_funds_only_latest_month_against_the_one_before():
    k = D.mf_kpi(stock())
    assert k['month'] == '2026-10' and k['net'] == pytest.approx(18.4) and k['before'] == pytest.approx(10.0)
    assert (k['bought'], k['sold']) == (1, 1) and k['spark'] == pytest.approx([10.0, 18.4])
    b, s = D.mf_month_lists(stock())
    assert b['isin'].tolist() == ['A'] and s['isin'].tolist() == ['B']   # C under Rs 1 Cr; pension never mixed in


def test_mf_by_sector_prefers_the_industry_table_and_says_what_is_unplaced():
    smap, src = D.sector_map(pd.DataFrame({'isin': ['A'], 'sector': ['Banks']}),
                             pd.DataFrame({'isin': ['A', 'B'], 'sector': ['Finance', 'IT']}))
    assert src == 'industry' and smap == {'A': 'Banks'}
    smap, src = D.sector_map(pd.DataFrame(), pd.DataFrame({'isin': ['A', 'B'], 'sector': ['Finance', 'IT']}))
    assert src == 'securities'
    g, unplaced = D.mf_by_sector(stock(), {'A': 'Finance'})
    assert g.to_dict('records') == [{'sector': 'Finance', 'net_cr': 30.0}]
    assert unplaced == pytest.approx(12.4 / 42.4)


def test_deals_kpi_counts_buy_legs_of_real_buyers_once():
    d = pd.DataFrame([
        {'date': REF - pd.Timedelta(days=2), 'isin': 'A', 'side': 'BUY', 'value': 5e8, 'is_primary': True, 'client_is_market_maker': False, 'client_type': 'mutual_fund'},
        {'date': REF - pd.Timedelta(days=2), 'isin': 'A', 'side': 'SELL', 'value': 5e8, 'is_primary': True, 'client_is_market_maker': False, 'client_type': 'corporate'},
        {'date': REF - pd.Timedelta(days=3), 'isin': 'B', 'side': 'BUY', 'value': 9e9, 'is_primary': True, 'client_is_market_maker': True, 'client_type': 'prop_hft'},
        {'date': REF - pd.Timedelta(days=3), 'isin': 'B', 'side': 'BUY', 'value': 9e9, 'is_primary': False, 'client_is_market_maker': False, 'client_type': 'individual'},
        {'date': REF - pd.Timedelta(days=4), 'isin': 'C', 'side': 'BUY', 'value': 1e8, 'is_primary': True, 'client_is_market_maker': False, 'client_type': 'individual'},
        {'date': REF - pd.Timedelta(days=70), 'isin': 'C', 'side': 'BUY', 'value': 2e8, 'is_primary': True, 'client_is_market_maker': False, 'client_type': 'individual'},
        {'date': REF - pd.Timedelta(days=40), 'isin': 'C', 'side': 'BUY', 'value': 3e8, 'is_primary': True, 'client_is_market_maker': False, 'client_type': 'individual'}])
    k = D.deals_kpi(d, REF, 30)
    assert k['value'] == pytest.approx(6e8) and k['funds'] == pytest.approx(5e8) and k['companies'] == 2
    assert k['before'] == pytest.approx(3e8)


def test_profit_growth_uses_quarters_with_a_year_ago_and_leaves_half_years_out():
    r = pd.DataFrame({'_at': [REF - pd.Timedelta(days=d) for d in (1, 2, 3, 4, 100)],
                      'quarter_profit': [10.0, 5.0, 8.0, None, 1.0], 'profit_year': [5.0, 6.0, None, 3.0, 0.5],
                      'half_year': [False, False, False, False, False]})
    g = D.profit_growth(r, REF - pd.Timedelta(days=45), REF + pd.Timedelta(days=1))
    assert (g['n'], g['up'], g['share']) == (2, 1, 50.0)
    k = D.results_kpi(r, REF)
    assert k['share'] == 50.0 and k['before'] is None   # one comparable filing a season back is too few


def sast():
    base = {'held_back_reason': None, 'mode': 'Open Market', 'is_promoter': False, 'acquirer_name': 'Big Fund', 'company': 'Co'}
    return pd.DataFrame([
        {**base, 'isin': 'A', 'symbol': 'A', 'broadcast_ts': '2026-11-15 10:00:00', 'percent_equity_traded': 1.0, 'post_stake_pct': 5.5},
        {**base, 'isin': 'B', 'symbol': 'B', 'broadcast_ts': '2026-11-14 10:00:00', 'percent_equity_traded': -2.0, 'post_stake_pct': 4.0},
        {**base, 'isin': 'C', 'symbol': 'C', 'broadcast_ts': '2026-11-13 10:00:00', 'percent_equity_traded': 2.0, 'post_stake_pct': 8.0},
        {**base, 'isin': 'D', 'symbol': 'D', 'broadcast_ts': '2026-11-13 10:00:00', 'percent_equity_traded': 3.0, 'post_stake_pct': 6.0,
         'held_back_reason': 'lender_or_trustee'},
        {**base, 'isin': 'E', 'symbol': 'E', 'broadcast_ts': '2026-11-12 10:00:00', 'percent_equity_traded': 3.0, 'post_stake_pct': 26.0,
         'mode': 'Inter-se transfer'},
        {**base, 'isin': 'F', 'symbol': 'F', 'broadcast_ts': '2026-10-05 10:00:00', 'percent_equity_traded': 6.0, 'post_stake_pct': 11.0}])


def test_sast_crossings_leave_out_held_back_and_inter_se_rows():
    m = D.sast_moves(sast(), REF, 30)
    assert set(m['isin']) == {'A', 'B', 'C'}
    assert dict(zip(m['isin'], m['cross'])) == {'A': '5%', 'B': '5%', 'C': ''}
    k = D.sast_kpi(sast(), REF, 30)
    assert (k['n'], k['in'], k['out'], k['before']) == (2, 1, 1, 1)


def test_convergence_needs_insiders_and_one_more_group():
    t = trades([('A', 'promoter', 'BUY', 5e7, 3, None), ('B', 'director', 'BUY', 5e7, 3, None),
                ('C', 'director', 'BUY', 5e7, 3, None), ('G', 'director', 'BUY', 1e6, 3, None)])   # G under Rs 25 lakh
    d = pd.DataFrame([{'date': REF - pd.Timedelta(days=5), 'isin': 'C', 'side': 'BUY', 'value': 1e8, 'is_primary': True,
                       'client_is_market_maker': False, 'client_type': 'fpi', 'client_is_promoter': False, 'client_name': 'Global Fund'}])
    rows, win = D.convergence(t, REF, stock(), sast(), d, {'A': 'Alpha'})
    assert win['month'] == '2026-10' and win['start'] == pd.Timestamp('2026-10-01')
    assert rows['isin'].tolist() == ['A', 'C']   # A: funds and a holder crossing up; C: a fund's deal; B: insiders alone
    a = rows.iloc[0]
    assert a['groups'] == 3 and a['name'] == 'Alpha' and bool(a['mf']) and bool(a['holder']) and not a['deal']
    assert rows.iloc[1]['deal_name'] == 'Global Fund'


def test_fpi_sectors_latest_fortnight_without_the_grand_total():
    f = pd.DataFrame([{'fortnight_end': '2026-10-31', 'period_start': '2026-10-16', 'sector': s, 'net_equity_cr': v}
                      for s, v in (('Banks', -300), ('IT', 120), ('Grand Total', -180))]
                     + [{'fortnight_end': '2026-10-15', 'period_start': '2026-10-01', 'sector': 'Banks', 'net_equity_cr': 50}])
    end, x = D.fpi_sectors(f)
    assert end == pd.Timestamp('2026-10-31') and x['sector'].tolist() == ['IT', 'Banks']


def test_coming_up_lists_seven_days_and_counts_dividends_and_results_meetings():
    up = pd.DataFrame([{'kind': 'meeting', 'date': REF + pd.Timedelta(days=2), 'isin': 'A', 'symbol': 'A', 'company': 'Co A',
                        'what': 'Board meets: fund raising', 'value': None},
                       {'kind': 'lockin', 'date': REF + pd.Timedelta(days=20), 'isin': 'B', 'symbol': 'B', 'company': 'Co B',
                        'what': 'Lock-in ends', 'value': 1e8}])
    acts = pd.DataFrame([{'symbol': 'C', 'company': 'Co C', 'purpose': 'bonus', 'record_date': REF + pd.Timedelta(days=1), 'ex_date': None},
                         {'symbol': 'C', 'company': 'Co C', 'purpose': 'bonus', 'record_date': REF + pd.Timedelta(days=1), 'ex_date': None},
                         {'symbol': 'D', 'company': 'Co D', 'purpose': 'dividend', 'record_date': REF + pd.Timedelta(days=3), 'ex_date': None},
                         {'symbol': 'E', 'company': 'Co E', 'purpose': 'split', 'record_date': REF - pd.Timedelta(days=3), 'ex_date': None}])
    meet = pd.DataFrame({'symbol': ['X', 'Y'], 'results': [True, True], 'meeting_date': [REF + pd.Timedelta(days=1), REF + pd.Timedelta(days=9)]})
    rows, counts = D.coming_up(up, acts, meet, REF)
    assert rows['what'].tolist() == ['Record date: bonus', 'Board meets: fund raising']
    assert counts == {'dividends': 1, 'results_meetings': 1}


def test_coming_up_makes_a_companys_lock_ins_on_one_day_one_row_sized_in_all():
    day = REF + pd.Timedelta(days=1)
    up = pd.DataFrame([{'kind': 'lockin', 'date': day, 'isin': 'A', 'symbol': 'A', 'company': 'Co A', 'what': 'Lock-in ends', 'value': v}
                       for v in (1e7, 2e7, None)]
                      + [{'kind': 'lockin', 'date': day, 'isin': 'B', 'symbol': None, 'company': 'Co B', 'what': 'Lock-in ends', 'value': None}])
    rows, _ = D.coming_up(up, None, None, REF)
    assert rows['company'].tolist() == ['Co A', 'Co B'] and rows['n'].tolist() == [3, 1]
    assert rows['value'].iloc[0] == 3e7 and pd.isna(rows['value'].iloc[1])


def test_fpi_top_keeps_the_largest_buys_and_sales_only():
    x = pd.DataFrame({'sector': list('abcdefgh'), 'net_equity_cr': [50, 40, 30, 1, -1, -20, -30, -60]})
    t = D.fpi_top(x, n=2)
    assert t['sector'].tolist() == ['a', 'b', 'g', 'h']


def test_window_words_follow_its_length():
    w = D.Window('2026-11-18 15:00', 31)
    assert w.end == pd.Timestamp('2026-11-18') and w.short == '31 days' and w.before == 'vs the 31 days before'
    assert D.Window('2026-11-18', 1).span == 'in 1 day'


def test_a_change_that_rounds_to_nothing_is_unchanged():
    assert 'Unchanged vs before' in D.delta_html(69.2, 69.4, lambda d: f'{d:+.0f} pts', 'vs before')


def test_sparkline_is_html_columns_with_no_colour_of_its_own():
    from ui import charts
    h = charts.spark([1, -2, 3], signed=True)
    assert h.startswith('<span class="cg-spark flat signed"') and '<svg' not in h and '#' not in h   # st.html strips SVG
    assert h.count('class="p') == 2 and h.count('class="n') == 1 and 'class="p last"' in h and 'class="z"' in h
    assert charts.spark([]) == '' and 'class="q' in charts.spark([1, 2, 3])
    assert charts.spark([None, 2, 3]).count('class="q') == 2   # a missing value keeps its slot empty
    assert 'dash-delta-up' in D.delta_html(5, 3, str, 'vs before') and 'dash-delta-down' in D.delta_html(1, 3, str, 'x')
    assert 'No earlier period' in D.delta_html(1, None, str, 'x')


def test_headline_says_only_what_the_data_holds():
    assert D.headline(None, None, None).startswith('The market picture fills in')
    h = D.headline({'net': -3e8}, {'mtd': 1200.0}, None)
    assert 'net sellers of <b>₹30.00 Cr</b>' in h and 'FPIs have bought <b>₹1,200 Cr</b>' in h and 'mutual' not in h


def test_evidence_tag_reads_the_track_record_or_names_its_status():
    assert D.evidence_tag(None, 'promoter_buy', 'Not measured') == ('Not measured', '')
    s = pd.DataFrame([{'signal': 'promoter_buy', 'horizon': '3M', 'cases': 80, 'median_excess': 2.0, 'beat_index': 60.0}])
    assert D.evidence_tag(s, 'promoter_buy', 'Not measured') == ('Early read: ahead', 'up')


@pytest.fixture(scope='module')
def site(data_dir, tmp_path_factory):  # noqa: F811
    root = tmp_path_factory.mktemp('dash') / 'site'
    shutil.copytree(data_dir, root)
    cur = root / 'clean' / 'current'
    sec = pd.read_parquet(cur / 'securities.parquet').dropna(subset=['isin']).head(2)
    a, b = sec['isin'].tolist()
    flows().assign(date=lambda f: pd.to_datetime(f['date'])).to_parquet(cur / 'market_flows.parquet')
    stock().replace({'isin': {'A': a, 'B': b}}).to_parquet(cur / 'mf_stock_month.parquet')
    pd.DataFrame([{'fortnight_end': '2026-10-31', 'period_start': '2026-10-16', 'sector': s, 'net_equity_cr': v}
                  for s, v in (('Banks', -300.0), ('IT', 120.0), ('Grand Total', -180.0))]).to_parquet(cur / 'fpi_sector_flows.parquet')
    return root


def _run(monkeypatch, root):
    import streamlit as st
    st.cache_data.clear()   # the readers cache by table name: one test's folder must not leak into the next
    st.cache_resource.clear()
    monkeypatch.setenv('INSIDERS_LOCAL_DATA', str(root))
    at = AppTest.from_string(APP_PATHS + """
from ui import theme
theme.inject()
from screens import dashboard
dashboard.render()
""", default_timeout=90)
    at.run()
    assert not at.exception, at.exception[0].value
    return ' '.join(str(getattr(e, 'body', '')) for e in at.get('html')) + ' '.join(m.value for m in at.markdown)


def test_dashboard_renders_every_tile_on_real_data(site, monkeypatch):
    h = _run(monkeypatch, site)
    for text in ('dash-grid', 'Insider net buying', 'FPI net, equity', 'DII net, cash market', 'Mutual funds, net active buying',
                 'Bulk and block deals', 'Holders crossing a threshold', 'Is foreign or domestic money coming in?',
                 'Where does the smart money agree?', 'What are fund managers buying?', 'Where are foreign investors putting money?',
                 'What is coming up this week?', 'dash-ev'):
        assert text in h, text
    assert 'could not be drawn' not in h


def test_dashboard_says_what_is_missing(data_dir, monkeypatch):  # noqa: F811
    h = _run(monkeypatch, data_dir)
    assert 'Market flows (NSE, NSDL) are not collected yet' in h
    assert 'month-end portfolios are not collected yet' in h or 'Not collected yet' in h
    assert 'could not be drawn' not in h
