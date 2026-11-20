"""Banks, NBFCs and insurers on the Results page (20 Nov 2026): their results XBRL names revenue and profit in its own
layout (insiders_clean/results.TOP_LINE); the page showed "No revenue line" for HDFC Bank, SBI, LIC and others. The
fixtures are a few facts of each company's Sep 2026 filing as filed (tests/fixtures/nse_events/results_xbrl)."""
from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pandas as pd
import pytest
from conftest import FIXTURES, ROOT

from insiders_clean import results

sys.path.insert(0, str(ROOT / 'streamlit_app'))

from screens import more_pages  # noqa: E402
from screens import results as rp  # noqa: E402

XB = FIXTURES / 'nse_events' / 'results_xbrl'
CR = 1e7


def _summary(name, kind):
    return results.summary(results.parse_xbrl((XB / name).read_text()), kind)


@pytest.mark.parametrize(('name', 'kind', 'basis', 'revenue', 'profit'), [
    # a bank's total income = interest earned + other income (83,426.60 + 13,831.02 Cr)
    ('BANKING_HDFCBANK_1740912.xml', 'BANKING', 'bank_total_income', 972576200000.0, 195099600000.0),
    # consolidated: profit before minority interest, as ProfitLossForPeriod is for companies
    ('BANKING_SBIN_1751754.xml', 'BANKING', 'bank_total_income', 1877561900000.0, 257414700000.0),
    # NBFCs file under Ind AS Division III: revenue from operations was always read
    ('NBFC_INDAS_BAJFINANCE_1742038.xml', 'NBFC_INDAS', 'ind_as_revenue', 208906600000.0, 55361000000.0),
    # a life insurer's net premium, not its income with the market's investment gains in it
    ('LI_LICI_1753945.xml', 'LI', 'insurer_net_premium', 1470181800000.0, 120760200000.0),
    ('GI_ICICIGI_1740432.xml', 'GI', 'insurer_premium_earned', 66518700000.0, 9464000000.0),
])
def test_each_layout_gives_its_revenue_line_and_net_profit(name, kind, basis, revenue, profit):
    s = _summary(name, kind)
    assert s['revenue_basis'] == basis
    assert s['quarter_revenue'] == revenue and s['quarter_profit'] == profit
    assert s['ytd_revenue'] is None   # a first-half filing's quarter only here: no year to date in the fragment


def test_bank_owners_profit_is_after_minority_interest_and_associates():
    s = _summary('BANKING_SBIN_1751754.xml', 'BANKING')
    assert s['quarter_profit_owners'] == 253611600000.0   # 2,57,414.7 - 8,564.3 + 4,761.2 Cr (x 1e7)
    assert s['quarter_total_income'] == 1877561900000.0 and s['quarter_tax'] == 78139400000.0


def test_read_as_a_company_a_bank_has_no_revenue_line():
    """Under the Ind AS names (the layout not known) the bank's filing has no revenue: blank, and no basis."""
    s = _summary('BANKING_HDFCBANK_1740912.xml', None)
    assert s['quarter_revenue'] is None and s['revenue_basis'] is None and s['quarter_profit'] is None


def test_clean_reads_the_layout_from_the_filing():
    xml = (XB / 'LI_LICI_1753945.xml').read_text()
    rows = pd.DataFrame([{'event_id': 'nse:result:1', 'seq_id': '1', 'symbol': 'LICI', 'company': 'LIC', 'period_end': '2026-09-30',
                          'consolidated': 'Non-Consolidated', 'broadcast_at': '2026-11-05T18:00:00+05:30', 'kind': 'LI',
                          'xbrl_status': 'ok', 'xbrl_json': json.dumps(results.parse_xbrl(xml))}])
    c = results.clean(rows).iloc[0]
    assert c['revenue_basis'] == 'insurer_net_premium' and c['quarter_revenue'] == 1470181800000.0
    assert results.basis_label(c['revenue_basis']) == 'Net premium (life insurer)'
    assert results.basis_label('ind_as_revenue') == 'Revenue' and results.basis_label(None) == 'Revenue'


# ---- like with like on the page ---------------------------------------------------------------------------------------

def _res(rows):
    df = pd.DataFrame(rows, columns=['isin', 'period_end', 'quarter_revenue', 'quarter_profit', 'revenue_basis'])
    end = pd.to_datetime(df['period_end'])
    return df.assign(symbol=df['isin'], company=df['isin'] + ' Ltd', consolidated='Non-Consolidated', superseded=False,
                     broadcast_at=(end + pd.Timedelta(days=30)).dt.strftime('%Y-%m-%dT10:00:00+05:30'))


def test_year_ago_comparison_never_mixes_revenue_lines():
    r = _res([
        # BANK: both quarters on total income: compared
        ('BANK', '2025-09-30', 900 * CR, 180 * CR, 'bank_total_income'), ('BANK', '2026-09-30', 990 * CR, 198 * CR, 'bank_total_income'),
        # MIX: a year-ago row on another line (never set against total income): no growth rate, no profit growth either
        ('MIX', '2025-09-30', 100 * CR, 10 * CR, 'ind_as_revenue'), ('MIX', '2026-09-30', 990 * CR, 12 * CR, 'bank_total_income'),
    ])
    out = more_pages._latest_results(SimpleNamespace(results=r, ref=pd.Timestamp('2026-11-19')), 100_000)
    out = out[out['_end'] == '2026-09-30'].set_index('isin')
    assert round(out.loc['BANK', 'rev_yoy'], 6) == 10 and out.loc['BANK', 'profit_year'] == 180 * CR
    assert pd.isna(out.loc['MIX', 'rev_yoy']) and pd.isna(out.loc['MIX', 'profit_year'])


def test_results_page_names_the_bank_line_and_drops_no_revenue_tag():
    r = _res([('BANK', '2025-09-30', 900 * CR, 180 * CR, 'bank_total_income'),
              ('BANK', '2026-09-30', 990 * CR, 198 * CR, 'bank_total_income'),
              ('CO', '2026-09-30', None, 5 * CR, None)])
    rows = rp.prepare(more_pages._latest_results(SimpleNamespace(results=r, ref=pd.Timestamp('2026-11-19')), 100_000), None, None)
    t = rp._table_rows(rows[rows['fy'] == 2027], {}, []).set_index('isin')
    assert t.loc['BANK', 'period'].endswith('· standalone · Total income (bank)')
    assert 'No revenue line' not in t.loc['BANK', 'notes'] and round(t.loc['BANK', 'rev_yoy_'], 6) == 10
    assert 'No revenue line' in t.loc['CO', 'notes'] and 'Total income' not in t.loc['CO', 'period']
