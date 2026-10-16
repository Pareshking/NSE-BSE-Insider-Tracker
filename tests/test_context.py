import pandas as pd

from insiders_clean import context


def frame():
    return pd.DataFrame([
        {'isin': 'INE1', 'period_end': '2026-03-31', 'consolidated': 'Standalone', 'ytd_revenue': 4.0e9, 'ytd_total_income': 4.1e9, 'ytd_profit': 1.0e8, 'broadcast_at': '2026-05-10'},
        {'isin': 'INE1', 'period_end': '2026-03-31', 'consolidated': 'Consolidated', 'ytd_revenue': 6.0e9, 'ytd_total_income': 6.2e9, 'ytd_profit': 2.0e8, 'broadcast_at': '2026-05-10'},
        {'isin': 'INE1', 'period_end': '2025-03-31', 'consolidated': 'Consolidated', 'ytd_revenue': 5.0e9, 'ytd_total_income': 5.1e9, 'ytd_profit': 1.5e8, 'broadcast_at': '2025-05-10'},
        {'isin': 'INE1', 'period_end': '2026-06-30', 'consolidated': 'Consolidated', 'ytd_revenue': None, 'ytd_total_income': None, 'ytd_profit': None, 'broadcast_at': '2026-08-10'},
        {'isin': 'INE2', 'period_end': '2026-03-31', 'consolidated': 'Consolidated', 'ytd_revenue': 0.0, 'ytd_total_income': 6.8e7, 'ytd_profit': 2.5e7, 'broadcast_at': '2026-05-12'},
    ])


def test_last_year_is_the_latest_march_filing_consolidated_first():
    out = context.last_year(frame(), 'INE1', '2026-10-16')
    assert out == {'fy': 'FY26', 'revenue': 6.0e9, 'profit': 2.0e8, 'basis': 'consolidated', 'period_end': '2026-03-31'}


def test_as_of_date_is_respected_and_zero_revenue_falls_back_to_total_income():
    assert context.last_year(frame(), 'INE1', '2025-10-01')['fy'] == 'FY25'
    assert context.last_year(frame(), 'INE2', '2026-10-16')['revenue'] == 6.8e7


def test_nothing_when_the_company_or_year_is_missing():
    assert context.last_year(frame(), 'INE9', '2026-10-16') is None
    assert context.last_year(frame(), 'INE1', '2024-01-01') is None
    assert context.last_year(None, 'INE1', '2026-10-16') is None
