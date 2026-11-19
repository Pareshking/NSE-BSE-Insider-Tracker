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
