"""Filings: "Real money only" and the headline sentence (streamlit_app/screens/filings_rules.py)."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'streamlit_app'))
from screens import filings_rules  # noqa: E402


def row(**kw):
    base = {'_src': 'insider', 'group': 'Insider market', 'role': 'Promoter', 'side': 'BUY', 'value': 1e7, 'pct_of_mcap': 0.1,
            'is_mm': False, 'also_filed': False, 'who': 'Asha Rao', 'who_sub': 'promoter group', 'company': 'Alpha Ltd',
            'what': 'Open market', 'what_sub': ''}
    return {**base, **kw}


def mask(*rows):
    return filings_rules.real_money(pd.DataFrame(rows)).tolist()


def test_insider_buys_need_the_floors_or_the_big_value_and_a_decision_maker():
    assert mask(row(value=30e5, pct_of_mcap=0.06),                       # Rs 30 L and 0.06%
                row(value=30e5, pct_of_mcap=0.04),                       # under 0.05%
                row(value=5e5, pct_of_mcap=0.3),                         # 0.25% alone
                row(value=30e7, pct_of_mcap=0.001),                      # Rs 30 Cr whatever the share
                row(role='Others', value=90e7, pct_of_mcap=1.0),         # an employee never counts
                row(role='Director/KMP', value=30e5, pct_of_mcap=0.06)) == [True, False, True, True, False, True]


def test_sales_a_promoter_by_the_floors_a_director_or_kmp_only_at_25_crore():
    assert mask(row(side='SELL', value=30e5, pct_of_mcap=0.06),
                row(side='SELL', role='Director/KMP', value=30e5, pct_of_mcap=0.06),
                row(side='SELL', role='Director/KMP', value=30e7, pct_of_mcap=0.01)) == [True, False, True]


def test_deals_stake_changes_issues_and_buybacks():
    deal = dict(_src='deal', group='Deals', role='Others')
    assert mask(row(**deal, value=30e7, pct_of_mcap=0.01),
                row(**deal, value=1e7, pct_of_mcap=0.3),
                row(**deal, value=1e7, pct_of_mcap=0.1),
                row(**deal, value=30e7, is_mm=True),
                row(**deal, value=30e7, also_filed=True)) == [True, True, False, False, False]
    sast = dict(_src='sast', group='SAST', value=np.nan, pct_of_mcap=np.nan, role='Others')
    assert mask(row(**sast, who='Fund X'), row(**sast, who='Catalyst Trusteeship Limited as debenture trustee')) == [True, False]
    assert mask(row(_src='qip', group='Capital raises', value=150e7, role=None),
                row(_src='qip', group='Capital raises', value=50e7, role=None),
                row(_src='pref', group='Capital raises', value=np.nan, role=None),
                row(_src='buyback', group='Corporate actions', value=np.nan, role=None)) == [True, False, False, True]


def test_pledges_other_filings_and_dates_ahead_are_never_real_money():
    assert mask(row(group='Pledges', value=900e7), row(group='Insider other', value=900e7),
                row(_src='action', group='Corporate actions', value=np.nan), row(_src='upcoming', group='Upcoming')) == [False] * 4
    assert filings_rules.real_money(pd.DataFrame()).empty


def test_headline_is_built_from_the_row_fields_and_leaves_out_what_it_lacks():
    h = filings_rules.headline(row(value=10.33e7, pct_of_mcap=0.12))
    assert h == 'Asha Rao (promoter group) bought ₹10.33 Cr of Alpha Ltd, 0.12% of the company, on the open market.'
    sold = filings_rules.headline(row(side='SELL', value=np.nan, pct_of_mcap=np.nan))
    assert '₹' not in sold and '%' not in sold and sold.startswith('Asha Rao (promoter group) sold')
    deal = filings_rules.headline(row(_src='deal', group='Deals', who='SBI Mutual Fund', who_sub='Mutual fund', what='Bulk deal',
                                      value=809.46e7, pct_of_mcap=0.9))
    assert deal == 'SBI Mutual Fund (Mutual fund) bought ₹809.46 Cr of Alpha Ltd, 0.90% of the company, in a bulk deal.'
    qip = filings_rules.headline(row(_src='qip', group='Capital raises', who='', what='QIP', what_sub='Allotted', value=500e7))
    assert qip == 'Alpha Ltd: QIP of ₹500.00 Cr, Allotted.'
    assert filings_rules.headline(row(_src='action', group='Corporate actions', who='', what='Split', what_sub='')) == 'Alpha Ltd: split.'
