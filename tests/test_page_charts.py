"""The charts on Insiders, Deals and Stakes (streamlit_app/screens/page_charts.py and ui/charts.split_rows / flow_strip):
the arithmetic on small frames, and that each builder draws nothing for nothing."""
from __future__ import annotations

import sys

import pandas as pd

from conftest import ROOT

sys.path.insert(0, str(ROOT / 'streamlit_app'))

from screens import page_charts as P  # noqa: E402
from ui import charts  # noqa: E402

REF = pd.Timestamp('2026-11-19')


def eligible(rows):
    """(role, side, value, days before REF, token)."""
    return pd.DataFrame([{'person_role': r, 'side': s, 'value': v, 'seen': REF - pd.Timedelta(days=d), 'is_token': t}
                         for r, s, v, d, t in rows])


# ---- Insiders

def test_daily_net_counts_decision_makers_only_and_leaves_empty_days_empty():
    e = eligible([('promoter', 'BUY', 5e7, 0, False), ('director', 'SELL', 2e7, 0, False),
                  ('kmp', 'SELL', 1e7, 2, False), ('designated_person', 'BUY', 9e9, 1, False),   # not a decision-maker
                  ('director', 'BUY', 9e9, 1, True),                                             # a token buy
                  ('promoter', 'BUY', 4e7, 10, False)])                                          # before the range
    out = P.insider_daily_net(e, REF - pd.Timedelta(days=3), REF)
    assert list(out['day']) == list(pd.date_range(REF - pd.Timedelta(days=3), REF))
    net = dict(zip(out['day'], out['net']))
    assert net[REF] == 3e7 and net[REF - pd.Timedelta(days=2)] == -1e7
    assert pd.isna(net[REF - pd.Timedelta(days=1)]) and pd.isna(net[REF - pd.Timedelta(days=3)])
    assert P.insider_daily_net(pd.DataFrame(), REF, REF).empty


def test_net_by_company_nets_buys_against_sales_and_names_who():
    d = pd.DataFrame([
        {'isin': 'A', 'company': 'Alpha', 'side': 'BUY', 'pct_of_company': 0.6, 'value': 6e7, 'promoter_group': True},
        {'isin': 'A', 'company': 'Alpha', 'side': 'SELL', 'pct_of_company': 0.2, 'value': 2e7, 'promoter_group': False},
        {'isin': 'B', 'company': 'Beta', 'side': 'SELL', 'pct_of_company': 1.5, 'value': 9e7, 'promoter_group': True},
        {'isin': 'C', 'company': 'Gamma', 'side': 'BUY', 'pct_of_company': 0.1, 'value': 1e7, 'promoter_group': False}])
    out = P.insider_net_by_company(d, {'B': 'Beta Industries'})
    assert list(out['company']) == ['Alpha', 'Gamma', 'Beta Industries']
    a = out.set_index('isin')
    assert abs(a.loc['A', 'net_pct'] - 0.4) < 1e-9 and a.loc['A', 'net_value'] == 4e7 and a.loc['A', 'tag'] == 'bought and sold'
    assert a.loc['B', 'net_pct'] == -1.5 and a.loc['B', 'tag'] == 'promoter' and a.loc['C', 'tag'] == 'director / KMP'
    html = charts.diverging_bar(out, 'company', 'net_pct', fmt=P.pct_arrow, tag='tag')
    assert '▲ 0.40%' in html and '▼ 1.50%' in html and html.index('Alpha') < html.index('Beta Industries')
    assert P.insider_net_by_company(pd.DataFrame(), {}).empty


# ---- Deals

def deals(rows):
    """(isin, client, side, value, type, promoter, market maker)."""
    return pd.DataFrame([{'isin': i, 'company': f'Co {i}', 'client_name': c, 'side': s, 'value': v, 'client_type': t,
                          'client_is_promoter': p, 'client_is_market_maker': m} for i, c, s, v, t, p, m in rows])


def test_buyer_groups_put_promoters_first_and_leave_market_makers_out():
    d = deals([('A', 'SBI MUTUAL FUND', 'BUY', 5e8, 'mutual_fund', False, False),
               ('A', 'HDFC MUTUAL FUND', 'SELL', 1e8, 'mutual_fund', False, False),
               ('A', 'PROMOTER HOLDCO', 'SELL', 4e8, 'corporate', True, False),
               ('B', 'LIC OF INDIA LIFE INSURANCE', 'BUY', 2e8, 'insurer', False, False),
               ('B', 'GOLDMAN SACHS FUND', 'BUY', 3e8, 'fpi', False, False),
               ('B', 'SOME PROP DESK', 'BUY', 9e9, 'prop_hft', False, True),
               ('B', 'RAM KUMAR', 'SELL', 1e7, 'individual', False, False)])
    g = P.deals_by_buyer_group(d).set_index('group')
    assert list(g.index) == ['Mutual funds', 'Insurers', 'Foreign investors', 'Promoters', 'Others']
    assert g.loc['Mutual funds', 'buy'] == 5e8 and g.loc['Mutual funds', 'sell'] == 1e8 and g.loc['Mutual funds', 'net'] == 4e8
    assert g.loc['Promoters', 'sell'] == 4e8 and g.loc['Others', 'sell'] == 1e7 and g['buy'].sum() == 10e8   # market maker out


def test_buyer_group_falls_back_to_the_name_when_the_type_column_is_missing():
    d = deals([('A', 'NIPPON INDIA MUTUAL FUND', 'BUY', 1e8, None, False, False)]).drop(columns='client_type')
    assert P.deals_by_buyer_group(d)['group'].tolist() == ['Mutual funds']
    assert P.buyer_group('mutual_fund', True) == 'Promoters' and P.buyer_group('bank', None) == 'Others'


def test_net_by_company_marks_a_promoter_sale():
    d = deals([('A', 'FUND ONE', 'BUY', 3e8, 'fpi', False, False), ('A', 'PROMOTER', 'SELL', 5e8, 'corporate', True, False),
               ('B', 'FUND TWO', 'BUY', 1e8, 'mutual_fund', False, False)])
    out = P.deals_net_by_company(d, {'A': 'Alpha Ltd'}).set_index('isin')
    assert out.loc['A', 'net'] == -2e8 and out.loc['A', 'tag'] == 'promoter sold' and out.loc['A', 'company'] == 'Alpha Ltd'
    assert out.loc['B', 'net'] == 1e8 and out.loc['B', 'tag'] == ''
    assert P.deals_net_by_company(None).empty and P.deals_by_buyer_group(pd.DataFrame()).empty


def test_split_rows_scale_each_group_to_the_largest_and_skip_empty_groups():
    html = charts.split_rows([('Mutual funds', 300, 100), ('Insurers', 100, 100), ('Nobody', 0, 0)], fmt=lambda v: f'{v:.0f}')
    assert html.count('cg-srows-r') == 2 and 'Nobody' not in html
    assert 'width:75.00%' in html and html.count('width:25.00%') == 3   # 400 is the largest
    assert charts.split_rows([('x', 0, 0)]) == '' and charts.split_rows([]) == ''


def test_flow_strip_draws_up_and_down_columns_and_nothing_for_one_day():
    days = list(pd.date_range('2026-11-01', periods=4))
    html = charts.flow_strip(days, [5e7, None, -2e7, 0])
    assert html.count('class="p"') == 1 and html.count('class="n"') == 1   # an empty and a zero day draw no column
    assert '01 Nov' in html and '04 Nov 2026' in html and 'title="03 Nov 2026: ' in html
    assert charts.flow_strip(days[:1], [1e7]) == '' and charts.flow_strip(days, [None] * 4) == ''


# ---- Stakes

def test_crossings_name_every_threshold_gone_through():
    assert P.crossings(4, 12, (5, 10, 25)) == [(5, 'up'), (10, 'up')]
    assert P.crossings(26, 24.5, (5, 10, 25)) == [(25, 'down')]
    assert P.crossings(5, 5, (5,)) == [] and P.crossings(None, 6, (5,)) == []
    mv = pd.DataFrame({'before': [4, 26, 9.5, None], 'after': [12, 24.5, 10.2, 7]})
    c = P.crossing_counts(mv, (5, 10, 25, 50)).set_index('threshold')
    assert c.loc[5, 'up'] == 1 and c.loc[10, 'up'] == 2 and c.loc[25, 'down'] == 1 and c.loc[50].sum() == 0


def test_stake_moves_leave_out_inter_se_small_and_held_back_rows():
    sa = pd.DataFrame([
        {'isin': 'A', 'company': 'Alpha', 'acquirer_name': 'Big Fund', 'percent_equity_traded': 2.5, 'post_stake_pct': 7.5,
         'mode': 'Market Purchase', 'held_back_reason': None, 'is_promoter': False},
        {'isin': 'B', 'company': 'Beta', 'acquirer_name': 'Promoter Co', 'percent_equity_traded': -3.0, 'post_stake_pct': 48.0,
         'mode': 'Market Sale', 'held_back_reason': None, 'is_promoter': True},
        {'isin': 'C', 'company': 'Gamma', 'acquirer_name': 'Family', 'percent_equity_traded': 5.0, 'post_stake_pct': 30.0,
         'mode': 'Inter-se transfer', 'held_back_reason': None, 'is_promoter': True},
        {'isin': 'D', 'company': 'Delta', 'acquirer_name': 'Tiny', 'percent_equity_traded': 0.05, 'post_stake_pct': 5.01,
         'mode': 'Market Purchase', 'held_back_reason': None, 'is_promoter': False},
        {'isin': 'E', 'company': 'Eps', 'acquirer_name': 'Law Firm', 'percent_equity_traded': 9.0, 'post_stake_pct': 9.0,
         'mode': 'Others', 'held_back_reason': 'filed_by_law_firm', 'is_promoter': False}])
    mv = P.stake_moves(sa, {'A': 'Alpha Ltd'})
    assert mv['company'].tolist() == ['Alpha Ltd', 'Beta']
    assert mv['before'].tolist() == [5.0, 51.0] and mv['promoter'].tolist() == [False, True]
    c = P.crossing_counts(mv, (5, 10, 50)).set_index('threshold')
    assert c.loc[5, 'up'] == 0 and c.loc[50, 'down'] == 1   # 5.0 -> 7.5 starts at the line, it does not go through it


def test_flow_strip_names_each_day_in_a_short_range_only():
    week = list(pd.date_range('2026-11-12', periods=7))   # Thu to Wed: 14 and 15 Nov are the weekend
    html = charts.flow_strip(week, [1e7] * 7)
    assert 'cg-fdays' in html and '<span class="we">14</span>' in html and '<span class="">12</span>' in html
    year = list(pd.date_range('2026-01-01', periods=60))
    assert 'cg-fdays' not in charts.flow_strip(year, [1e7] * 60)
    assert 'cg-srows tight' in charts.split_rows([('5%', 3, 1)], fmt=str, tight=True)
