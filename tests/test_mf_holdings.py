"""Mutual fund month-end portfolios (insiders_clean/mf_holdings.py, collectors/mf_portfolios/find.py)."""
from __future__ import annotations

import io
import zipfile

import openpyxl
import pandas as pd

from collectors.mf_portfolios import find
from insiders_clean import mf_holdings as m


def _book(sheets: dict) -> bytes:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for r in rows:
            ws.append(r)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


SCHEME = [['SBI Mutual Fund', '007'], ['SCHEME NAME :', 'SBI Large Cap Fund'], ['PORTFOLIO STATEMENT AS ON :', '31-10-2026'], [],
          ['Name of the Instrument / Issuer', 'ISIN', 'Rating / Industry^', 'Quantity', 'Market value\n(Rs. in Lakhs)', '% to AUM'],
          ['EQUITY & EQUITY RELATED'],
          ['ICICI Bank Ltd.', 'INE090A01021', 'Banks', 3114000, 43533.72, 8.69],
          ['HDFC Bank Ltd.', 'INE040A01034', 'Banks', 5389800, 37340.53, 7.45],
          ['7.32% GOI 2030', 'IN0020230135', 'SOV', 100000, 101.2, 0.1],
          ['Total', None, None, None, 80975.45, 16.24]]
INDEX = [['SCHEME NAME :', 'SBI Nifty Index Fund'], [],
         ['Name of the Instrument', 'ISIN', 'Industry', 'Quantity', 'Market value', '% to AUM'],
         ['ICICI Bank Ltd.', 'INE090A01021', 'Banks', 1000, 14.0, 9.0]]


def test_reads_sebi_format_and_counts_skipped_sheets():
    df, rep = m.parse_workbook(_book({'Index': [['Back to index']], 'SLCF': SCHEME, 'SNIF': INDEX}), 'x.xlsx')
    assert rep['sheets'] == 3 and rep['sheets_read'] == 2 and rep['skipped'] == {'no ISIN and Quantity header': 1}
    assert rep['lines'] == 4 and rep['equity_lines'] == 3                # the GOI bond is a line, not equity
    assert set(df['scheme']) == {'SBI Large Cap Fund', 'SBI Nifty Index Fund'}
    assert df.loc[df['isin'] == 'INE040A01034', 'quantity'].iloc[0] == 5389800


def test_zipped_workbook_is_read():
    z = io.BytesIO()
    with zipfile.ZipFile(z, 'w') as f:
        f.writestr('31102026_monthly.xlsx', _book({'S1': SCHEME}))
    df, rep = m.parse_workbook(z.getvalue(), 'portfolio.zip')
    assert rep['workbooks'] == 1 and len(df) == 3


def test_holdings_keep_index_funds_apart():
    df, _ = m.parse_workbook(_book({'SLCF': SCHEME, 'SNIF': INDEX}), 'x.xlsx')
    h = m.holdings(df, 'sbi', '2026-10').set_index('isin')
    assert h.loc['INE090A01021', 'shares'] == 3115000 and h.loc['INE090A01021', 'active_shares'] == 3114000
    assert h.loc['INE090A01021', 'schemes'] == 2 and h.loc['INE090A01021', 'active_schemes'] == 1
    assert 'IN0020230135' not in h.index


def _h(amc, month, rows):
    return pd.DataFrame([{'amc': amc, 'month': month, 'isin': i, 'name': i, 'shares': s, 'active_shares': a, 'value_lakh': 1.0}
                         for i, s, a in rows])


def test_changes_kinds_and_a_bonus_is_not_buying():
    prev = _h('sbi', '2026-09', [('INEAAAA01011', 100, 100), ('INEBBBB01011', 50, 50), ('INECCCC01011', 10, 0),
                                 ('INEDDDD01011', 40, 40)])
    cur = _h('sbi', '2026-10', [('INEAAAA01011', 150, 150), ('INEBBBB01011', 0, 0), ('INECCCC01011', 20, 0),
                                ('INEEEEE01011', 5, 5), ('INEDDDD01011', 80, 80)])
    ch = m.changes(cur, prev, factors=pd.DataFrame({'isin': ['INEDDDD01011'], 'factor': [2.0]})).set_index('isin')
    assert ch.loc['INEAAAA01011', 'kind'] == 'added' and ch.loc['INEAAAA01011', 'active_change'] == 50
    assert ch.loc['INEBBBB01011', 'kind'] == 'exit'
    assert ch.loc['INECCCC01011', 'kind'] == 'passive'          # only index funds hold it
    assert ch.loc['INEEEEE01011', 'kind'] == 'new'
    assert ch.loc['INEDDDD01011', 'kind'] == 'held' and ch.loc['INEDDDD01011', 'active_change'] == 0   # 1:1 bonus


def test_a_house_seen_in_one_month_only_is_not_compared():
    prev = _h('sbi', '2026-09', [('INEAAAA01011', 100, 100)])
    cur = pd.concat([_h('sbi', '2026-10', [('INEAAAA01011', 100, 100)]), _h('hdfc', '2026-10', [('INEAAAA01011', 999, 999)])])
    ch = m.changes(cur, prev)
    assert set(ch['amc']) == {'sbi'}
    s = m.by_stock(ch)
    assert s['houses_adding'].iloc[0] == 0 and s['active_net'].iloc[0] == 0


def test_share_factors_from_filed_actions():
    acts = pd.DataFrame({'isin': ['INEDDDD01011', 'INEDDDD01011', 'INEFFFF01011'], 'purpose': ['bonus', 'dividend', 'split'],
                         'ex_date': ['2026-10-15', '2026-10-15', '2026-09-20'], 'ratio': ['1:1', None, None],
                         'face_value_from': [None, None, 10], 'face_value_to': [None, None, 2]})
    f = m.share_factors(acts, '2026-09', '2026-10').set_index('isin')['factor']
    assert round(f['INEDDDD01011'], 6) == 2.0
    assert 'INEFFFF01011' not in f.index                  # its split was before the earlier month-end


def test_coverage_is_measured_not_claimed():
    h = _h('sbi', '2026-09', [('INEAAAA01011', 40, 40), ('INEBBBB01011', 10, 10)])
    filed = pd.DataFrame({'isin': ['INEAAAA01011', 'INEBBBB01011', 'INECCCC01011'], 'mf_shares': [100, 20, 5]})
    c = m.coverage(h, filed)
    assert c['companies'] == 2 and round(c['weighted_ratio'], 3) == round(50 / 120, 3)


def test_month_tokens_and_candidates():
    links = [('Download', 'https://x.in/docs/all-schemes-monthly-portfolio---as-on-31st-october-2026.xlsx?v=2'),
             ('Download', 'https://x.in/docs/all-schemes-monthly-portfolio---as-on-30th-september-2026.xlsx'),
             ('Fortnightly', 'https://x.in/FactsheetsDocuments/NIMF-FORTNIGHTLY-PORTFOLIO-31-Oct-26.xls'),
             ('Download', 'https://x.in/FactsheetsDocuments/NIMF-MONTHLY-PORTFOLIO-31-Oct-26.xls'),
             ('Risk', 'https://x.in/FactsheetsDocuments/RiskParameter-Oct-2026.xls'),
             ('', 'https://x.in/2026/31102026_abslmf_monthlydisclosure.zip'),
             ('Oct 2025', 'https://x.in/monthly-portfolio-october-2025.xlsx')]
    h = find.House('t', 'T', 'https://x.in', mode='all')
    got = find.candidates(links, '2026-10', h)
    assert 'https://x.in/FactsheetsDocuments/NIMF-MONTHLY-PORTFOLIO-31-Oct-26.xls' in got   # folder "Factsheets" is fine
    assert 'https://x.in/2026/31102026_abslmf_monthlydisclosure.zip' in got
    assert not any('FORTNIGHTLY' in u or 'Risk' in u or 'september' in u or '2025' in u for u in got)
    one = find.candidates(links, '2026-10', find.House('t', 'T', 'x', must=r'all[ -]schemes'))
    assert one == ['https://x.in/docs/all-schemes-monthly-portfolio---as-on-31st-october-2026.xlsx?v=2']


def test_latest_months_follow_the_tenth():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
    from datetime import date
    import mf_portfolios
    assert mf_portfolios.latest_months(2, date(2026, 11, 19)) == ['2026-10', '2026-09']
    assert mf_portfolios.latest_months(1, date(2026, 11, 5)) == ['2026-09']
    assert mf_portfolios.latest_months(1, date(2026, 1, 12)) == ['2025-12']


def test_an_isin_change_is_one_holding_not_an_exit_and_a_start():
    prev = pd.DataFrame([{'amc': 'sbi', 'month': '2026-09', 'isin': 'INEOLD001011', 'name': 'Akzo JSW Dulux Ltd.', 'shares': 100,
                          'active_shares': 100, 'value_lakh': 1.0}])
    prev.loc[0, 'name'] = 'JSW Dulux Ltd.'
    cur = pd.DataFrame([{'amc': 'sbi', 'month': '2026-10', 'isin': 'INENEW001011', 'name': 'JSW Dulux Limited', 'shares': 120,
                         'active_shares': 120, 'value_lakh': 1.0}])
    ch = m.changes(cur, prev)
    assert len(ch) == 1 and ch['kind'].iloc[0] == 'added' and ch['active_change'].iloc[0] == 20
    assert ch['isin_before'].iloc[0] == 'INEOLD001011'


# The PFRDA form NPS pension fund managers file: a sheet per scheme, 'Name of the scheme' then its name in the next
# cell (ICICI, Axis) or after a colon (SBI, LIC), 'Particulars' for the name, 'Isin No.' / 'ISIN No.', 'Quantity' or
# 'No of Units', 'Mkt_Value' / 'Market Value' in rupees ("Amount in Rs."), '% of Portfolio' as a fraction.
NPS_E1 = [['Name of the Pension Fund', 'Example Pension Fund Management Limited'], ['Name of the scheme', 'Scheme E - Tier I'],
          ['Portfolio Statement as on', '30-10-2026'], [], ["(Amount in 'Rs.')"],
          ['Particulars', 'ISIN No.', 'Industry', 'Quantity', 'Market Value', '% of Portfolio', 'Ratings'],
          ['Equity Instruments'], ['Shares'],
          ['HDFC Bank Limited.', 'INE040A01034', 'Banks', 28553145, 19781618856, 0.061],
          ['ICICI Bank Limited.', 'INE090A01021', 'Banks', 14095124, 19704983352, 0.0607],
          ['Subtotal', None, None, None, 39486602208, 0.1217]]
NPS_E2 = [['Name of the Pension Fund', 'Example Pension Fund Management Limited'], ['Name of the scheme', 'Scheme E - Tier II'],
          [], ['Particulars', 'ISIN No.', 'Industry', 'No of Units', 'Market Value', '% of Portfolio', 'Rating (if rated)'],
          ['ICICI Bank Limited.', 'INE090A01021', 'Banks', 383838, 536605524, 0.064]]
NPS_CG = [[], ['Pension Fund Manager Name : EXAMPLE PENSION FUNDS PVT.LTD.'],
          ['Name Of Scheme : NPS TRUST- A/C EXAMPLE PENSION FUND SCHEME - CENTRAL GOVT'],
          ['Portfolio Statements as on: 30-10-2026'], ['Equities and Related Investments'],
          ['Name of Instruments', 'Isin No.', 'Industry', 'Quantity', 'Mkt_Value', '% of Portfolio'],
          ['HDFC BANK LTD.', 'INE040A01034', 'Banks - Private Sector', 26016408, 18024167462.4, 1.4581],
          ['7.30% GS 2053 (19.06.2053)', 'IN0020230051', 'GOVERNMENT SECURITIES', 336875000, 31531634750, 2.64]]


def test_reads_the_nps_pension_form_with_values_in_rupees():
    df, rep = m.parse_workbook(_book({'Scheme E - Tier I': NPS_E1, 'Scheme E - Tier II': NPS_E2, 'Scheme CG': NPS_CG}),
                               'monthly-website-forms-oct-26.xlsx', value_unit='rupee')
    assert rep['sheets_read'] == 3 and rep['equity_lines'] == 4 and rep['value_unit'] == 'rupee'
    assert set(df['scheme']) == {'Scheme E - Tier I', 'Scheme E - Tier II',
                                 'NPS TRUST- A/C EXAMPLE PENSION FUND SCHEME - CENTRAL GOVT'}
    hdfc = df[(df['isin'] == 'INE040A01034') & (df['scheme'] == 'Scheme E - Tier I')].iloc[0]
    assert hdfc['name'] == 'HDFC Bank Limited.' and hdfc['quantity'] == 28553145
    assert abs(hdfc['value_lakh'] - 197816.18856) < 1e-6                  # Rs 19,781,618,856 = Rs 1,97,816 lakh
    h = m.holdings(df, 'nps_x', '2026-10').set_index('isin')
    assert h.loc['INE090A01021', 'shares'] == 14095124 + 383838 and h.loc['INE090A01021', 'schemes'] == 2
    assert h.loc['INE040A01034', 'active_shares'] == 28553145 + 26016408   # no index funds among NPS schemes by name
    assert 'IN0020230051' not in h.index


def test_the_same_workbook_in_lakh_is_unchanged_by_default():
    df, rep = m.parse_workbook(_book({'SLCF': SCHEME}), 'x.xlsx')
    assert rep['value_unit'] == 'lakh' and df.loc[df['isin'] == 'INE090A01021', 'value_lakh'].iloc[0] == 43533.72


def test_mutual_funds_and_pension_funds_are_counted_apart():
    prev = pd.concat([_h('sbi', '2026-09', [('INE090A01021', 100, 100)]), _h('nps_sbi', '2026-09', [('INE090A01021', 50, 50)])])
    cur = pd.concat([_h('sbi', '2026-10', [('INE090A01021', 150, 150)]), _h('nps_sbi', '2026-10', [('INE090A01021', 20, 20)])])
    h = pd.concat([prev, cur]).assign(kind=lambda d: d['amc'].map({'sbi': 'mf', 'nps_sbi': 'pension'}))
    ch = m.tag_house_kind(m.changes(cur, prev), h)
    st = m.stock_months(ch).set_index('house_kind')
    assert st.loc['mf', 'active_net'] == 50 and st.loc['mf', 'houses_adding'] == 1
    assert st.loc['pension', 'active_net'] == -30 and st.loc['pension', 'houses_cutting'] == 1
    assert m.tag_house_kind(ch.drop(columns='house_kind'), h.drop(columns='kind'))['house_kind'].eq('mf').all()


def test_pension_houses_are_kept_apart_by_kind():
    from collectors.mf_portfolios.houses import BY_KEY, HOUSES
    pension = [h for h in HOUSES if h.kind == 'pension']
    assert pension and all(h.key.startswith('nps_') and h.value_unit == 'rupee' for h in pension)
    assert all(h.kind == 'mf' and h.value_unit == 'lakh' for h in HOUSES if not h.key.startswith('nps_'))
    assert BY_KEY['sbi'].kind == 'mf' and BY_KEY['nps_sbi'].kind == 'pension'


def test_mahindra_reads_only_the_monthly_portfolio_category():
    from collectors.mf_portfolios.apis2 import mahindra_links
    from collectors.mf_portfolios.houses import BY_KEY
    listing = {'status': 1, 'message': 'Downloads fetched successfully', 'data': [
        {'categoryName': 'MANDATORY DISCLOSURES', 'files': [], 'subcategories': [
            {'categoryName': 'Portfolio Disclosure', 'files': [], 'subcategories': [
                {'categoryName': 'Fortnightly Debt Portfolio Disclosures', 'subcategories': [], 'files': [
                    {'title': 'Debt portfolio disclosure for the fortnight ended October 31, 2026',
                     'fileUrl': 'https://cms.example/f.xlsx'}]},
                {'categoryName': 'Monthly Portfolio Disclosure', 'files': [], 'subcategories': [
                    {'categoryName': '2026', 'subcategories': [], 'files': [
                        {'title': 'Monthly Portfolio Disclosure - October, 2026', 'fileUrl': 'https://cms.example/oct.xlsx'},
                        {'title': 'Monthly Portfolio Disclosure - September, 2026', 'fileUrl': 'https://cms.example/sep.xlsx'},
                        {'title': 'No file yet', 'fileUrl': None}]}]}]}]}]}
    links = mahindra_links(listing)
    assert links == [('Monthly Portfolio Disclosure - October, 2026', 'https://cms.example/oct.xlsx'),
                     ('Monthly Portfolio Disclosure - September, 2026', 'https://cms.example/sep.xlsx')]
    assert find.candidates(links, '2026-10', BY_KEY['mahindra']) == ['https://cms.example/oct.xlsx']


def test_helios_takes_every_scheme_and_its_misspelt_names_but_no_fortnightly_file():
    from collectors.mf_portfolios.houses import BY_KEY
    base = 'https://www.heliosmf.in/wp-content/uploads/2026/11/'
    links = [('October 2026', base + 'helios-flexi-cap-fund-monthly-portfolio-as-on-31st-october-2026.xlsx'),
             ('October 2026', base + 'helios-arbitrage-fund-monthly-portfolio-as-on-31-october-2026.xlsx'),
             ('October 2026', base + 'Helios-Overnight-Fund-Monthtly-Portfolio-as-on-31st-October-2026.xls'),
             ('', base + 'helios-overnight-fund-fortnightly-portfolio-as-on-31st-october-2026.xls'),
             ('', base + 'helios-flexi-cap-fund-monthly-portfolio-as-on-30th-september-2026.xlsx')]
    got = find.candidates(links, '2026-10', BY_KEY['helios'])
    assert len(got) == 3 and not any('fortnightly' in u or 'september' in u for u in got)


def test_not_collected_names_houses_that_are_not_collected():
    from collectors.mf_portfolios.houses import HOUSES, NOT_COLLECTED
    names = {h.name for h in HOUSES}
    assert NOT_COLLECTED and all(n not in names and why for n, why in NOT_COLLECTED)
    assert 'Mahindra Manulife Mutual Fund' in names


# ---- Scheme by scheme (19 Nov 2026) -------------------------------------------------------------------------------

def test_scheme_key_matches_one_scheme_across_spellings_and_sources():
    k = m.scheme_key
    same = ['SBI Large Cap Fund - Direct Plan - Growth', 'SBI LARGE CAP FUND (An open-ended equity scheme predominantly '
            'investing in large cap stocks)', 'SBI Large Cap Fund - Direct Plan - Income Distribution cum Capital Withdrawal '
            'Option (IDCW)', 'SBI Largecap Fund (formerly known as SBI Bluechip Fund)']
    assert {k(n, 'SBI Mutual Fund') for n in same} == {'largecap'}
    assert k('SBI Dividend Yield Fund - Direct Plan - Growth', 'SBI Mutual Fund') == 'dividend yield'   # not a plan word here
    assert k('Tata Value Fund - Regular Plan - Payout of IDCW-Option A(5%)', 'Tata Mutual Fund') == 'value'
    assert k('quant Small Cap Fund - Growth Option - Direct Plan', 'quant Mutual Fund') == 'smallcap'
    assert k('Nippon India ETF Nifty 50 BeES', 'Nippon India Mutual Fund') == 'etf nifty 50 bees'      # stays passive
    assert m.PASSIVE.search(k('Nippon India ETF Nifty 50 BeES', 'Nippon India Mutual Fund'))


def _scheme_book():
    flexi = [['SCHEME NAME :', 'SBI Flexicap Fund'], [],
             ['Name of the Instrument', 'ISIN', 'Industry', 'Quantity', 'Market value', '% to AUM'],
             ['ICICI Bank Ltd.', 'INE090A01021', 'Banks', 2000, 28.0, 3.0],
             ['7.32% GOI 2030', 'IN0020230135', 'SOV', 100000, 101.2, 0.1]]
    liquid = [['SCHEME NAME :', 'SBI Liquid Fund'], [],
              ['Name of the Instrument', 'ISIN', 'Industry', 'Quantity', 'Market value', '% to AUM'],
              ['7.32% GOI 2030', 'IN0020230135', 'SOV', 100000, 101.2, 0.1]]
    return _book({'SLCF': SCHEME, 'SNIF': INDEX, 'SFCF': flexi, 'SLIQ': liquid})


def test_scheme_rows_add_up_to_the_house_rows():
    df, _ = m.parse_workbook(_scheme_book(), 'x.xlsx')
    sc = m.scheme_holdings(df, 'sbi', '2026-10', 'SBI Mutual Fund')
    h = m.holdings(df, 'sbi', '2026-10').set_index('isin')
    assert set(sc['scheme_key']) == {'largecap', 'nifty index', 'flexicap'}       # the liquid fund holds no equity
    tot = sc.groupby('isin')['shares'].sum()
    assert (tot == h['shares'].reindex(tot.index)).all()
    hs = m.house_from_schemes(sc).set_index('isin')
    assert hs.loc['INE090A01021', 'active_shares'] == h.loc['INE090A01021', 'active_shares'] == 3114000 + 2000
    lst = m.scheme_list(df, 'sbi', '2026-10', 'SBI Mutual Fund').set_index('scheme_key')
    assert len(lst) == 4 and lst.loc['liquid', 'equity_lines'] == 0 and bool(lst.loc['nifty index', 'passive'])


def _sc(month, rows):
    return pd.DataFrame([{'amc': a, 'month': month, 'scheme_key': k, 'scheme': k.title() + ' Fund', 'isin': i, 'name': n,
                          'shares': s, 'value_lakh': s * 100 / 1e5, 'passive': 'index' in k} for a, k, i, n, s in rows])


def test_scheme_changes_show_what_the_house_nets_out():
    """Within one house a scheme buys and another sells: the house reads a small net, the schemes say who did what; the
    rows add up to `changes` exactly, a bonus applied the same way."""
    a, b = 'INEAAAA01011', 'INEBBBB01011'
    prev = _sc('2026-09', [('sbi', 'largecap', a, 'A Ltd', 1000), ('sbi', 'smallcap', a, 'A Ltd', 500),
                           ('sbi', 'largecap', b, 'B Ltd', 100), ('sbi', 'gone', b, 'B Ltd', 50)])
    cur = _sc('2026-10', [('sbi', 'largecap', a, 'A Ltd', 1600), ('sbi', 'smallcap', a, 'A Ltd', 0),
                          ('sbi', 'largecap', b, 'B Ltd', 200), ('sbi', 'nifty index', b, 'B Ltd', 30)])
    cur = cur[cur['shares'] > 0]
    f = pd.DataFrame({'isin': [b], 'factor': [2.0]})        # a 1:1 bonus on B between the month-ends
    x = m.scheme_changes(cur, prev, f).set_index(['scheme_key', 'isin'])
    assert x.loc[('largecap', a), 'status'] == 'added' and x.loc[('largecap', a), 'change'] == 600
    assert x.loc[('smallcap', a), 'status'] == 'exit' and x.loc[('smallcap', a), 'change'] == -500
    assert x.loc[('largecap', b), 'status'] == 'held' and x.loc[('largecap', b), 'change'] == 0     # 100 x 2 = 200
    assert x.loc[('gone', b), 'scheme_seen'] == 'start_only' and x.loc[('nifty index', b), 'scheme_seen'] == 'end_only'
    assert bool(x.loc[('nifty index', b), 'passive']) and not bool(x.loc[('largecap', a), 'passive'])
    house = m.changes(m.house_from_schemes(cur).assign(value_lakh=1.0), m.house_from_schemes(prev), f).set_index('isin')
    got = x.reset_index().groupby('isin')['change'].sum()
    assert got[a] == house.loc[a, 'change'] == 100 and got[b] == house.loc[b, 'change']


def test_scheme_changes_bridge_an_isin_change_like_the_house_table():
    prev = _sc('2026-09', [('sbi', 'largecap', 'INEOLD001011', 'JSW Dulux Ltd.', 100)])
    cur = _sc('2026-10', [('sbi', 'largecap', 'INENEW001011', 'JSW Dulux Limited', 1200)])
    x = m.scheme_changes(cur, prev, pd.DataFrame({'isin': ['INENEW001011'], 'factor': [10.0]}))
    assert len(x) == 1 and x['status'].iloc[0] == 'added' and x['change'].iloc[0] == 200
    assert x['isin_before'].iloc[0] == 'INEOLD001011'


def test_scheme_month_and_the_site_cut():
    a = 'INEAAAA01011'
    prev = _sc('2026-09', [('sbi', 'largecap', a, 'A', 1000), ('sbi', 'smallcap', a, 'A', 500), ('sbi', 'nifty index', a, 'A', 10)])
    cur = _sc('2026-10', [('sbi', 'largecap', a, 'A', 1600), ('sbi', 'smallcap', a, 'A', 500), ('sbi', 'nifty index', a, 'A', 20)])
    x = m.scheme_changes(cur, prev).assign(house_kind='mf')
    stock = pd.DataFrame({'month': ['2026-10'], 'house_kind': ['mf'], 'isin': [a], 'price': [100.0]})
    v = m.value_scheme_changes(x, stock)
    sm = m.scheme_month(v).set_index('scheme_key')
    assert sm.loc['largecap', 'net_cr'] == 600 * 100 / 1e7 and sm.loc['largecap', 'adding'] == 1
    mv = m.scheme_moves(v)
    assert list(mv['scheme_key'].astype(str)) == ['largecap']     # the index fund and the unmoved scheme left out


def test_company_shares_apply_a_split_since_the_last_filing():
    """JSW Dulux, Nov 2026: the Sep 2026 filing's 45,540,314 shares of Rs 10; split into Re 1 shares (new ISIN) on
    22 Oct 2026. The houses' October counts are post-split, so the October basis is ten times the filing."""
    isin = 'INE133A01029'
    sh = pd.DataFrame({'isin': [isin, isin], 'quarter_end': ['2026-06-30', '2026-09-30'], 'total_shares': [45540314, 45540314]})
    acts = pd.DataFrame({'isin': [isin], 'purpose': ['split'], 'ex_date': ['2026-10-22'], 'face_value_from': [10],
                         'face_value_to': [1]})
    t = m.company_shares(sh, acts, ['2026-09', '2026-10']).set_index('month')
    assert t.loc['2026-09', 'total_shares'] == 45540314 and t.loc['2026-10', 'total_shares'] == 455403140
    assert t.loc['2026-10', 'total_shares_quarter'] == '2026-09-30' and t.loc['2026-10', 'total_shares_factor'] == 10
    # The page's "% of the company": 1,438,463 shares bought by active schemes in October
    net = 1438463
    assert round(net / t.loc['2026-10', 'total_shares'] * 100, 3) == 0.316
    assert m.company_shares(sh, acts, ['2026-05']).empty      # no filing at or before the month-end: no share stated


AMFI = """Scheme Code;NAV Name;Plan;Option;ISIN Div Payout/ISIN Growth;ISIN Div Reinvestment;Net Asset Value;Date

Open Ended Schemes ( Equity Scheme - Large Cap Fund )

SBI Mutual Fund
1;SBI Large Cap Fund - Direct Plan - Growth;Direct Plan;Growth;INF1;;10;30-Oct-2026
2;SBI Large Cap Fund - Regular Plan - Growth;Regular Plan;Growth;INF2;;10;30-Oct-2026

Open Ended Schemes ( Equity Scheme - Small Cap Fund )

SBI Mutual Fund
3;SBI Small Cap Fund - Direct Plan - Growth;Direct Plan;Growth;INF3;;10;30-Oct-2026
4;SBI Mid Cap Fund - Direct Plan - Growth;Direct Plan;Growth;INF4;;10;30-Oct-2026
5;SBI Contra Fund - Direct Plan - Growth;Direct Plan;Growth;INF5;;10;30-Oct-2026

Open Ended Schemes ( Other Scheme - Index Funds )

SBI Mutual Fund
6;SBI Nifty Index Fund - Direct Plan - Growth;Direct Plan;Growth;INF6;;10;30-Oct-2026

Close Ended Schemes ( ELSS )

SBI Mutual Fund
7;SBI Long Term Advantage Fund Series V - Regular Plan - Growth;Regular Plan;Growth;INF7;;10;30-Oct-2026
"""


def test_scheme_count_check_against_amfi():
    nav = m.parse_amfi_nav(AMFI)
    assert len(nav) == 7 and nav['category'].value_counts()['equity'] == 6
    a = m.amfi_schemes(nav, {'sbi': 'SBI Mutual Fund'}).assign(month='2026-10')
    eq = a[a['open_ended'] & a['category'].eq('equity')]
    assert set(eq['scheme_key']) == {'largecap', 'smallcap', 'midcap', 'contra'} and set(eq['amc']) == {'sbi'}
    df, _ = m.parse_workbook(_scheme_book(), 'x.xlsx')
    lists = m.scheme_list(df, 'sbi', '2026-10', 'SBI Mutual Fund')
    cov = m.scheme_coverage(lists, a).iloc[0]
    assert cov['schemes_read'] == 4 and cov['equity_schemes_read'] == 3 and cov['active_equity_read'] == 2
    assert cov['amfi_equity'] == 4 and cov['amfi_matched'] == 1                  # large cap matched; flexicap is not on it
    assert cov['flag'] == 'fewer schemes read'                                  # 2 active read < 80% of AMFI's 4
    assert 'SBI Contra' in cov['amfi_not_matched']
    none = m.scheme_coverage(lists, None).iloc[0]
    assert pd.isna(none['amfi_equity']) and none['flag'] == ''                  # no AMFI list: only what we read


def test_rebuild_scheme_tables_add_up_and_name_houses_not_read_by_scheme():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
    import mf_portfolios as mp
    a = 'INEAAAA01011'
    prev = _sc('2026-09', [('sbi', 'largecap', a, 'A', 1000), ('sbi', 'smallcap', a, 'A', 500)])
    cur = _sc('2026-10', [('sbi', 'largecap', a, 'A', 1600), ('sbi', 'smallcap', a, 'A', 100)])
    sc = pd.concat([prev, cur], ignore_index=True)
    hold = pd.concat([m.house_from_schemes(prev), m.house_from_schemes(cur), _h('hdfc', '2026-10', [(a, 5, 5)]),
                      _h('hdfc', '2026-09', [(a, 5, 5)])], ignore_index=True).assign(value_lakh=1.0, kind='mf')
    chg = m.tag_house_kind(m.changes(hold[hold['month'] == '2026-10'], hold[hold['month'] == '2026-09']), hold)
    stock = m.stock_months(chg)
    lists = pd.concat([m.scheme_list(pd.DataFrame({'scheme': ['Largecap', 'Smallcap'], 'isin': [a, a], 'quantity': [1, 1]}),
                                     'sbi', mth) for mth in ('2026-09', '2026-10')], ignore_index=True)
    t = mp.scheme_tables(hold, chg, stock, sc, lists, pd.DataFrame(), {})
    assert t['checks'] == {'2026-10': 0}                 # the schemes add up to the house table
    assert t['scheme_month'].set_index('scheme_key').loc['smallcap', 'cutting'] == 1
    cov = t['scheme_coverage'].set_index(['month', 'amc'])
    assert cov.loc[('2026-10', 'hdfc'), 'flag'] == 'not read scheme by scheme'
    assert cov.loc[('2026-10', 'sbi'), 'schemes_read'] == 2
    assert mp.add_up(cur, m.house_from_schemes(cur)) == 0
    assert mp.add_up(cur, m.house_from_schemes(cur).assign(shares=1.0)) == 1
