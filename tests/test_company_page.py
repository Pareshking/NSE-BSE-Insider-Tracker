"""The Company page at a glance (owner, 19 Nov 2026: "Completely useless design and not glance-worthy to take even a
decision"): the verdict, its chips, the ownership mix, the fund houses' trend and the business, from
streamlit_app/screens/company_glance.py. Nothing is filled: missing data is a chip that says so and never counts."""
from __future__ import annotations

import sys

import pandas as pd
from conftest import ROOT

sys.path.insert(0, str(ROOT / 'streamlit_app'))

from screens import company_glance as cg  # noqa: E402
from ui import charts  # noqa: E402

REF = pd.Timestamp('2026-11-18')


def trades(*rows):
    return pd.DataFrame([{'seen': REF - pd.Timedelta(days=d), 'side': s, 'value': v, 'person_role': r, 'person_id': p,
                          'is_token': tok} for d, s, v, r, p, tok in rows])


def test_insider_flow_counts_decision_makers_in_90_days_only():
    e = trades((5, 'BUY', 5e7, 'promoter', 'a', False), (40, 'BUY', 2e7, 'director', 'b', False),
               (10, 'SELL', 1e7, 'kmp', 'c', False),
               (20, 'SELL', 9e8, 'designated_person', 'd', False),   # staff: not a decision-maker
               (120, 'BUY', 9e8, 'promoter', 'a', False),            # outside 90 days
               (3, 'BUY', 1e6, 'promoter', 'e', True))               # a token buy is not buying
    f = cg.insider_flow(e, REF)
    assert (f['buy'], f['sell'], f['net']) == (7e7, 1e7, 6e7)
    assert (f['buyers'], f['sellers'], f['promoter_net']) == (2, 1, 5e7)
    assert cg.insider_flow(pd.DataFrame(), REF)['rows'] == 0


def shp(q, check='match', **pct):
    base = {'promoter': 60.0, 'mf': 9.0, 'insurance': 8.0, 'fpi': 15.0, 'banks_fi': 0.2, 'aif': 0.3, 'other_dii': 0.5,
            'retail': 3.0, 'hni': 0.5, 'corporate': 0.5, 'other_foreign': 0.0, 'govt': 0.0, 'other_public': 3.0,
            'non_public_other': 0.0}
    base.update(pct)
    return {'quarter_end': pd.Timestamp(q), 'categories_check': check, **{f'{k}_pct': v for k, v in base.items()}}


def test_ownership_mix_groups_add_up_and_skips_quarters_that_do_not():
    rows = pd.DataFrame([shp('2026-03-31'), shp('2026-06-30', check='mismatch'), shp('2026-09-30', fpi=15.5, retail=2.5)])
    mix = cg.ownership_mix(rows)
    assert sorted(mix['quarter'].unique()) == [pd.Timestamp('2026-03-31'), pd.Timestamp('2026-09-30')]   # Jun not drawn
    sep = mix[mix['quarter'] == pd.Timestamp('2026-09-30')].set_index('group')['pct']
    assert list(sep.index) == cg.MIX_ORDER
    assert round(sep.sum(), 6) == 100.0
    assert sep['Other DII'] == 1.0 and sep['Retail'] == 3.0     # banks + AIF + other DII; retail + HNI
    # a skipped quarter (Jun not parsed) is not "last quarter": Mar to Sep is 183 days, so no change is drawn
    assert cg.mix_delta(mix).empty


def test_mix_delta_is_this_quarter_against_the_last():
    mix = cg.ownership_mix(pd.DataFrame([shp('2026-06-30'), shp('2026-09-30', fpi=15.43, retail=2.65)]))
    d = cg.mix_delta(mix).set_index('group')
    assert round(d.loc['FPI', 'pts'], 2) == 0.43 and round(d.loc['Retail', 'pts'], 2) == -0.35
    assert d.loc['Promoter', 'pts'] == 0


def mf_rows():
    rows = []
    for month, house, before, after, kind in (('2026-09', 'sbi', 100.0, 120.0, 'added'), ('2026-10', 'sbi', 120.0, 150.0, 'added'),
                                              ('2026-10', 'hdfc', 80.0, 60.0, 'cut'), ('2026-10', 'axis', 10.0, 0.0, 'exit'),
                                              ('2026-10', 'nps_sbi', 0.0, 500.0, 'new')):
        rows.append({'amc': house, 'month': month, 'isin': 'X', 'shares': after, 'shares_before': before, 'change': after - before,
                     'kind': kind, 'house_kind': 'pension' if house.startswith('nps') else 'mf'})
    return pd.DataFrame(rows)


def test_fund_houses_holdings_and_trend_from_month_ends():
    houses, trend = cg.fund_houses(mf_rows(), 'X', total_shares=1000, names={'sbi': 'SBI'})
    assert list(houses['house']) == ['SBI', 'hdfc', 'axis']           # pension managers apart; a house that sold out last
    assert houses.loc[0, 'pct'] == 15.0 and houses.loc[0, 'change'] == 30.0
    sbi = trend[trend['house'] == 'SBI']
    assert list(sbi['month']) == ['2026-08', '2026-09', '2026-10'] and list(sbi['shares']) == [100.0, 120.0, 150.0]
    assert 'axis' not in set(trend['house'])                           # no line for a house that holds none
    assert cg.fund_houses(mf_rows(), 'NOPE')[0].empty


def test_fund_month_reads_the_stocks_latest_month():
    sm = pd.DataFrame([{'month': '2026-10', 'house_kind': 'mf', 'isin': 'X', 'active_net_cr': -12.5, 'houses_adding': 1,
                        'houses_cutting': 3, 'houses_new': 0, 'houses_exit': 1, 'houses_holding': 9},
                       {'month': '2026-10', 'house_kind': 'pension', 'isin': 'X', 'active_net_cr': 99.0, 'houses_adding': 5,
                        'houses_cutting': 0, 'houses_new': 0, 'houses_exit': 0, 'houses_holding': 5}])
    f = cg.fund_month(sm, 'X')
    assert f['net_cr'] == -12.5 and f['cutting'] == 3 and f['latest']
    assert cg.fund_month(sm, 'Y') is None


def test_growth_year_on_year_and_margin_on_one_basis():
    rows = []
    for i, pe in enumerate(pd.date_range('2025-06-30', periods=6, freq='QE')):
        for basis, scale in (('Consolidated', 1.0), ('Non-Consolidated', 0.5)):
            rows.append({'isin': 'X', 'period_end': pe, 'consolidated': basis, 'quarter_revenue': 100.0 * (1 + 0.1 * i) * scale,
                         'quarter_profit': 10.0 * scale, 'broadcast_at': pe + pd.Timedelta(days=20), 'superseded': False,
                         'ytd_disagrees': False})
    rows.append({**rows[-2], 'ytd_disagrees': True, 'quarter_revenue': 9e9})   # contradicts itself: not used
    g, basis = cg.growth(pd.DataFrame(rows), 'X')
    assert basis == 'consolidated' and len(g) == 6
    last = g.iloc[-1]
    assert round(last['rev_yoy'], 6) == round((150 / 110 - 1) * 100, 6)      # Dec 2026 against Dec 2025
    assert round(last['margin'], 4) == round(10 / 150 * 100, 4) and last['profit_yoy'] == 0
    assert pd.isna(g.iloc[0]['rev_yoy'])                                     # no year-ago quarter held
    assert cg.results_doubts(pd.DataFrame(rows), 'X') == 1


def test_red_flags_levels():
    f = {x.name: x for x in cg.red_flags(pledge=34.0, trade_flags=['ST-ASM 1'], trade_notes=['Short-term ASM, stage 1'], late=2,
                                          cheap=['Allotted 12% below the price'], doubts=0, promoter_sold=5e7)}
    assert f['Pledge'].level == 'fail' and 'Kalia' in f['Pledge'].evidence
    assert f['Surveillance'].level == 'fail'
    assert f['Late filings'].level == 'warn' and f['Cheap issues'].level == 'warn' and f['Promoter selling'].level == 'warn'
    assert f['Results filings'].level == 'pass'
    g = {x.name: x for x in cg.red_flags(pledge=None, trade_flags=None)}
    assert g['Pledge'].level == 'na' and g['Surveillance'].level == 'na'   # not known is not "clean"
    assert {x.name: x for x in cg.red_flags(pledge=0.0, trade_flags=['T2T'])}['Surveillance'].level == 'warn'


def glance(ins_net=0.0, mf=None, fpi=0.0, dii=0.0, deal_net=0.0, flags=None, deal_pct=None):
    ins = {'buy': max(ins_net, 0), 'sell': max(-ins_net, 0), 'net': ins_net, 'buyers': 1, 'sellers': 0, 'promoter_net': ins_net,
           'rows': 1 if ins_net else 0, 'days': 90}
    fm = None if mf is None else {'month': '2026-10', 'latest': True, 'net_cr': mf, 'adding': 3, 'cutting': 1, 'new': 0, 'exit': 0,
                                  'holding': 9}
    q, p = pd.Timestamp('2026-09-30'), pd.Timestamp('2026-06-30')
    delta = pd.DataFrame([{'group': 'FPI', 'pts': fpi, 'now': 15.0, 'before': 15.0 - fpi, 'quarter': q, 'prev_quarter': p},
                          {'group': 'Mutual funds', 'pts': dii, 'now': 9.0, 'before': 9.0, 'quarter': q, 'prev_quarter': p}])
    deals = {'buy': max(deal_net, 0), 'sell': max(-deal_net, 0), 'net': deal_net, 'n': 1 if deal_net else 0,
             'top_buyer': '', 'top_seller': '', 'days': 90, 'net_pct': deal_pct}
    fl = flags if flags is not None else cg.red_flags(pledge=0.0, trade_flags=[])
    cs = cg.chips(ins, fm, delta, deals, fl, 'Promoter buys: measured ahead')
    return cs, cg.verdict(cs, fl, deals)


def test_verdict_buying_with_no_red_flags():
    cs, (s, lean) = glance(ins_net=6e7, mf=22.5, fpi=0.43)
    assert s == 'Insiders, mutual funds and foreign investors are buying; no red flags' and lean == 'accumulating'
    assert [c.key for c in cs] == ['insiders', 'mf', 'fpi', 'dii', 'deals', 'flags']
    assert next(c for c in cs if c.key == 'insiders').evidence == 'Promoter buys: measured ahead'   # rule 4
    assert next(c for c in cs if c.key == 'mf').evidence.startswith('Exploratory')


def test_verdict_selling_and_a_red_flag():
    _, (s, lean) = glance(ins_net=-3e7, fpi=-0.5, flags=cg.red_flags(pledge=40.0, trade_flags=[]))
    assert s == 'Insiders and foreign investors are selling; red flag: 40.0% of promoter shares pledged' and lean == 'leaving'


def test_verdict_mixed_small_moves_do_not_count_and_deals_only_when_alone():
    _, (s, lean) = glance(ins_net=1e6, mf=-5.0, fpi=0.1, dii=0.6)   # ₹10 L of insiders, 0.1 pts of FPI: not moving
    assert s == 'Domestic institutions buying, mutual funds selling; no red flags' and lean == 'mixed'
    _, (s, lean) = glance(deal_net=-5e9, deal_pct=-0.4)
    assert s == '₹500 Cr net sold in bulk and block deals (0.4% of the company); no red flags' and lean == 'leaving'
    _, (s, lean) = glance(fpi=0.5, deal_net=-5e9, deal_pct=-0.4)   # under 1% of the company: the others lead alone
    assert s == 'Foreign investors are buying; no red flags'
    _, (s, lean) = glance()
    assert s == 'No clear move by insiders or funds; no red flags' and lean == 'quiet'


def test_a_block_of_a_big_share_of_the_company_is_named_beside_the_quarter():
    """IIFL Finance, 18 Nov 2026: FIH Mauritius sold about 24% of the company in a block while the September quarter showed
    foreign investors adding; the block is news and is said, and the lean is mixed."""
    _, (s, lean) = glance(fpi=1.77, deal_net=-3.288e10, deal_pct=-11.6)
    assert s == ('Foreign investors are buying; ₹3,288 Cr net sold in bulk and block deals (11.6% of the company); '
                 'no red flags') and lean == 'mixed'


def test_a_matched_block_is_its_size_and_its_seller_not_a_nil_net():
    """IIFL Finance, 18 Nov 2026 on real data: FIH Mauritius sold 12.35% of the company to 47 buyers, so bought = sold and
    the net was ₹0; the chip and the verdict say how much changed hands and who sold."""
    ins = {'buy': 0.0, 'sell': 0.0, 'net': 0.0, 'buyers': 0, 'sellers': 0, 'promoter_net': 0.0, 'rows': 0, 'days': 90}
    year = {**ins, 'rows': 2, 'net': 6.577e8}
    deals = {'buy': 3.488e10, 'sell': 3.488e10, 'net': 0.0, 'n': 49, 'top_buyer': 'SBI MUTUAL FUND',
             'top_seller': 'FIH MAURITIUS INVESTMENTS LTD', 'days': 90, 'net_pct': 0.0, 'buy_pct': 12.35, 'sell_pct': 12.35}
    fl = cg.red_flags(pledge=0.0, trade_flags=[])
    cs = cg.chips(ins, None, pd.DataFrame(), deals, fl, ins_year=year)
    by = {c.key: c for c in cs}
    assert by['deals'].value == '₹3,488 Cr traded' and by['deals'].moving == 0
    assert by['deals'].note == '12.3% of the company · sold by FIH Mauritius Investments LTD'
    assert by['insiders'].note == 'none in 90 days; 12 months: net +₹65.8 Cr'
    s, lean = cg.verdict(cs, fl, deals)
    assert s == 'No clear move by insiders or funds; 12.3% of the company changed hands in deals; no red flags' and lean == 'quiet'


def test_deal_flow_nets_value_and_share_of_the_company():
    d = pd.DataFrame({'date': [REF, REF, REF - pd.Timedelta(days=200)], 'side': ['SELL', 'BUY', 'BUY'],
                      'value': [6.776e10, 3.488e10, 1e9], 'pct_of_mcap': [23.98, 12.35, 0.4],
                      'client_name': ['FIH MAURITIUS', 'SBI MF', 'OLD BUYER']})
    f = cg.deal_flow(d, REF)
    assert f['net'] == 3.488e10 - 6.776e10 and round(f['net_pct'], 2) == -11.63 and f['n'] == 2
    assert (f['top_buyer'], f['top_seller']) == ('SBI MF', 'FIH MAURITIUS')


def test_missing_data_is_said_and_never_counts():
    ins = {'buy': 0.0, 'sell': 0.0, 'net': 0.0, 'buyers': 0, 'sellers': 0, 'promoter_net': 0.0, 'rows': 0, 'days': 90}
    deals = {'buy': 0.0, 'sell': 0.0, 'net': 0.0, 'n': 0, 'top_buyer': '', 'top_seller': '', 'days': 90}
    fl = cg.red_flags(pledge=None, trade_flags=None)
    cs = cg.chips(ins, None, pd.DataFrame(), deals, fl)
    by = {c.key: c for c in cs}
    assert by['mf'].tone == 'na' and by['fpi'].tone == 'na' and by['dii'].tone == 'na'
    assert all(c.moving == 0 for c in cs)
    assert by['flags'].note == 'some checks not known'
    assert cg.verdict(cs, fl)[0] == 'No clear move by insiders or funds; no red flags'


def test_glance_charts_draw_only_with_data():
    mix = cg.ownership_mix(pd.DataFrame([shp('2026-06-30'), shp('2026-09-30')]))
    html = charts.ownership_stack(mix, cg.MIX_ORDER)
    assert html.count('class="cg-srow"') == 2 and 'var(--own-fpi)' in html and 'Sep 26' in html
    assert charts.ownership_stack(pd.DataFrame(), cg.MIX_ORDER) == ''
    assert charts.split_bar(0, 0) == '' and 'width:75.00%' in charts.split_bar(3e7, 1e7)
    d = charts.delta_bars([('FPI', 0.43, ''), ('Retail', -0.35, '')])
    assert 'class="cg-dv num up">+0.43 pts' in d and 'class="cg-dv num down">-0.35 pts' in d
    assert charts.columns([{'label': 'Sep 26', 'value': None}]) == ''
    assert '<polyline' in charts.spark([1, 2, 3], tone='up') and '<polyline' not in charts.spark([1])
