"""The Actions page draws every section that has rows, each with its evidence
line, and says nothing for a section without rows. Synthetic data shaped to
trigger every section and every verdict (the real measurements, 12 Oct 2026)."""
from __future__ import annotations

from streamlit.testing.v1 import AppTest
from test_ui_pages import APP_PATHS

BUILD = r'''
import pandas as pd
import streamlit as st
from screens import actions, ctx as ctxmod
from insiders_clean import issues

REF = pd.Timestamp('2026-10-09')

def t(person, role, side, value, pct, day, isin, company):
    return {'isin': isin, 'person_id': person.lower(), 'person_name': person, 'person_role': role, 'side': side,
            'value': value, 'pct_of_mcap': pct, 'seen': pd.Timestamp(day), 'company': company,
            'nse_symbol': company.upper(), 'is_token': False, 'is_market': True, 'is_primary': True}

elig = pd.DataFrame([
    t('Raj Shah', 'promoter', 'BUY', 5e7, 0.30, '2026-10-05', 'I1', 'Alpha'),
    t('Mina Rao', 'director', 'BUY', 3e7, 0.10, '2026-10-06', 'I1', 'Alpha'),      # with Raj: a cluster at Alpha
    t('Dev Jain', 'promoter', 'BUY', 4e7, 0.20, '2026-10-02', 'I2', 'Beta'),
    t('Sam Iyer', 'kmp', 'BUY', 2e7, 0.05, '2026-10-03', 'I3', 'Gamma'),
    t('Oma Das', 'promoter', 'SELL', 9e7, 0.40, '2026-10-01', 'I4', 'Delta'),
])
deals = pd.DataFrame([{'date': pd.Timestamp('2026-10-05'), 'isin': 'I5', 'exchange': 'nse', 'symbol': 'EPS', 'nse_symbol': 'EPS',
                       'company': 'Epsilon', 'market_cap': 1e10, 'is_primary': True, 'client_is_market_maker': False,
                       'client_id': 'fund', 'client_name': 'Fund A', 'side': 'BUY', 'signed_value': 5e7, 'pct_of_mcap': 0.5}])
sh = pd.DataFrame({'symbol': ['ZETA'], 'isin': ['I6'], 'quarter_end': ['2026-06-30'], 'promoter_pledge_pct': [42.0],
                   'promoter_holding_pct': [55.0], 'shareholding_stale': [False]})
sec = pd.DataFrame({'isin': ['I6'], 'company': ['Zeta Ltd'], 'nse_symbol': ['ZETA']})

def pref(stage, app, posted, **kw):
    r = {'canonical_event_id': f'e{app}', 'appId': str(app), 'canonical_stage': stage, 'canonical_isin': 'I7',
         'canonical_symbol': 'ETA', 'canonical_company': 'Eta Ltd', 'systemDate': posted, 'dateOfSubmission': posted,
         'xmlFileName': 'x', 'ingested_at': '2026-10-09T02:00:00+00:00'}
    r.update(kw)
    return r

records = issues.clean_issues(pd.DataFrame([
    pref('In-Principle', 1, '10-APR-2025', canonical_allottee_category='PROMOTER', totalAmtRaised='100000000', dateBrdResoln='01-APR-2025'),
    pref('Listing Stage', 2, '18-APR-2025', offerPricePerSecurity='10', totalNumOfSharesAllotted='1000000',
         dateOfAllotmentOfShares='15-APR-2025', dateOfListing='21-APR-2025', dateOfTradingApproval='20-APR-2025')]), 'preferential')[0]
meet = pd.DataFrame({'meeting_date': ['2026-10-12'], 'symbol': ['THETA'], 'company': ['Theta Ltd'], 'purposes': ['fund_raising,results'],
                     'fund_raising': [True], 'preferential': [False], 'buyback': [False], 'rights': [False], 'description': ['x']})
prices = pd.DataFrame({'isin': ['I1', 'I7'], 'latest_close': [100.0, 25.0], 'low_52w': [60.0, 10.0], 'high_52w': [120.0, 30.0],
                       'pct_off_high': [-16.0, -16.0], 'mcap_bucket': ['Small', 'Small']})
S = []
for sig, rows in {'cluster': {'3M': (128, 2.99, 57.0), '6M': (115, 5.62, 61.7)}, 'promoter_buy': {'3M': (323, 1.77, 54.2), '6M': (272, 2.96, 54.8)},
                  'officer_buy': {'3M': (26, 5.28, 69.2), '6M': (24, 25.4, 66.7)}, 'promoter_sell': {'3M': (148, -4.64, 38.5), '6M': (106, -2.64, 48.1)},
                  'fund_deal_buy': {'3M': (666, -5.25, 41.6), '6M': (444, -6.45, 39.0)}}.items():
    for h, (n, m, b) in rows.items():
        S.append({'signal': sig, 'horizon': h, 'cases': n, 'median_excess': m, 'beat_index': b})
summary = pd.DataFrame(S)

empty = pd.DataFrame()
fake = ctxmod.Ctx(trades=elig, eligible=elig, deals=deals, securities=sec, sast=empty, actions=empty, meetings=meet,
                  shareholding=sh, preferential=records, rights=empty, prices=prices, ref=REF, latest={})
actions.load = lambda: fake
actions.store.artifact = lambda key: summary if 'track_summary' in key else empty
%s
actions.render()
'''


def run(extra=''):
    at = AppTest.from_string(APP_PATHS + BUILD % extra, default_timeout=60)
    at.run()
    assert not at.exception, at.exception[0].value
    return ' '.join(str(e.value) for e in at.get('html'))


def test_every_section_with_rows_is_drawn_with_its_evidence_line():
    blob = run()
    for title in ('Several insiders buying together', 'Promoters buying', 'Directors and KMP buying', 'Promoters selling',
                  'Heavily pledged promoters', 'Funds net buying small caps', 'Shares about to come off lock-in',
                  'Boards meeting on fund raising or a buyback'):
        assert title in blob, title
    assert 'Beat the index so far' in blob and 'Lagged the index' in blob and 'Too few cases' in blob
    assert '57% of 128 cases beat it' in blob and '38% of 148 cases beat it' in blob
    assert 'Not measured on our data' in blob and 'lead, not proof' in blob


def test_sections_without_rows_are_not_drawn_and_an_empty_page_says_so():
    blob = run("fake.eligible = elig.iloc[0:0]; fake.deals = empty; fake.shareholding = empty; fake.preferential = empty; fake.meetings = empty")
    assert 'Nothing to act on in the data yet.' in blob
    assert 'Several insiders buying together' not in blob and 'Promoters buying' not in blob
