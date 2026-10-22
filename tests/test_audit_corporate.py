"""Data chain audit of 22 Oct 2026, corporate data (docs/DATA_CHAIN_AUDIT.md section 3, C-findings): fixtures shaped
like the real rows of the exchanges' files."""
from __future__ import annotations

import json

import pandas as pd
import pytest

from insiders_clean import adjust, issues, slim


def _p(rows):
    return pd.DataFrame(rows, columns=['date', 'exchange', 'isin', 'symbol', 'series', 'close', 'prev_close', 'value'])\
        .assign(date=lambda d: pd.to_datetime(d['date']))


# --- C1: bonuses and splits were not adjusted: the bhavcopy keeps the old base price, a split has a new ISIN --------

HDFCAMC = [('2025-11-24', 'NSE', 'INE127D01025', 'HDFCAMC', 'EQ', 5371.0, 5360.0, 9e8),
           ('2025-11-25', 'NSE', 'INE127D01025', 'HDFCAMC', 'EQ', 5336.5, 5371.0, 9e8),
           # NSE's UDiFF file of 26 Nov 2025: PrvsClsgPric 5336.5 (not reset), close 2679 on the 1:1 bonus ex-date
           ('2025-11-26', 'NSE', 'INE127D01025', 'HDFCAMC', 'EQ', 2679.0, 5336.5, 9e8),
           ('2025-11-27', 'NSE', 'INE127D01025', 'HDFCAMC', 'EQ', 2690.0, 2679.0, 9e8)]
BONUS = pd.DataFrame([{'isin': 'INE127D01025', 'purpose': 'bonus', 'ex_date': '2025-11-26', 'ratio': '1:1'}])


def test_filed_bonus_is_applied_when_the_bhavcopy_keeps_the_old_base_price():
    before = adjust.implied_factors(_p(HDFCAMC))
    assert before['kind'].iloc[2] == 'none'                      # what the site had: a false 50% fall
    fac = adjust.implied_factors(_p(HDFCAMC), actions=BONUS)
    day = fac.iloc[2]
    assert (day['kind'], day['kind_basis'], day['factor']) == ('split_bonus', 'action_price', 0.5)
    adj = adjust.adjust_as_of(fac, _p(HDFCAMC)[['date', 'exchange', 'isin', 'close']], '2025-11-27')
    assert adj['adj_close'].round(2).tolist() == [2685.5, 2668.25, 2679.0, 2690.0]


def test_filed_bonus_is_not_applied_when_the_price_did_not_move_by_it():
    rows = [r if r[0] != '2025-11-26' else (*r[:5], 5300.0, 5336.5, 9e8) for r in HDFCAMC]   # no halving that day
    fac = adjust.implied_factors(_p(rows), actions=BONUS)
    assert fac['kind'].iloc[2] == 'none' and fac['factor'].iloc[2] == pytest.approx(1.0)


BLSE = [('2026-10-01', 'NSE', 'INE0NLT01010', 'BLSE', 'EQ', 321.0, 318.0, 5e7),
        ('2026-10-03', 'NSE', 'INE0NLT01010', 'BLSE', 'EQ', 319.15, 321.0, 5e7),
        # 06 Oct 2026, split from Rs 10 to Rs 5: a new ISIN, PrvsClsgPric the old close, close 160.90
        ('2026-10-06', 'NSE', 'INE0NLT01028', 'BLSE', 'EQ', 160.9, 319.15, 5e7),
        ('2026-10-07', 'NSE', 'INE0NLT01028', 'BLSE', 'EQ', 162.0, 160.9, 5e7)]
SPLIT = pd.DataFrame([{'isin': 'INE0NLT01028', 'purpose': 'split', 'ex_date': '2026-10-06', 'face_value_from': 10.0,
                       'face_value_to': 5.0}])


def test_split_with_a_new_isin_carries_the_old_prints_and_is_adjusted():
    px, links = adjust.bridge_isins(_p(BLSE))
    assert links == {'INE0NLT01010': 'INE0NLT01028'}
    assert (px['isin'] == 'INE0NLT01010').sum() == 2 and (px['isin'] == 'INE0NLT01028').sum() == 4   # the old ISIN keeps its own
    close, _, f = slim.adjusted_panels(_p(BLSE).assign(open=lambda d: d['close']), actions=SPLIT)
    new = close['INE0NLT01028'].dropna()
    assert new.round(3).tolist() == [160.5, 159.575, 160.9, 162.0]
    one = f[(f['isin'] == 'INE0NLT01028') & (f['date'] == pd.Timestamp('2026-10-06'))].iloc[0]
    assert (one['kind'], one['kind_basis']) == ('split_bonus', 'action_price')


def test_no_bridge_between_two_issuers_or_across_a_long_gap():
    other = [('2026-10-01', 'NSE', 'INE111A01011', 'XYZ', 'EQ', 100.0, 99.0, 1e6),
             ('2026-10-06', 'NSE', 'INE222B01012', 'XYZ', 'EQ', 50.0, 100.0, 1e6),     # another issuer under the symbol
             ('2026-01-01', 'NSE', 'INE333C01011', 'ABC', 'EQ', 10.0, 10.0, 1e6),
             ('2026-03-01', 'NSE', 'INE333C01029', 'ABC', 'EQ', 5.0, 10.0, 1e6)]       # two months apart
    _, links = adjust.bridge_isins(_p(other))
    assert links == {}


# --- C2: preferential approvals filed a power of ten off ---------------------------------------------------------

def _approval(app, sym, amount, n, minimum, kind='Warrants', terms='0.25'):
    """An archive row of NSE's preferential in-principle list with its parsed XBRL, as stored (archive/nse_events/issues/)."""
    row = {'appId': app, 'nseSymbol': sym, 'isin': f'INE{app}X01010', 'nameOfTheCompany': sym + ' LIMITED',
           'stage': 'In-Principle', 'systemDate': '05-JAN-2026', 'dateOfSubmission': '23-DEC-2025',
           'dateBrdResoln': '12-NOV-2025', 'categoryOfAllottee': 'Non Promoter', 'considerationBy': 'Cash',
           'totalAmtRaised': str(amount), 'xmlFileName': f'https://nsearchives.nseindia.com/corporate/xbrl/PREF_ISSUE_IP_{app}_WEB.xml'}
    x = {'main': {'AmountToBeRaised': str(amount), 'CategoryOfAllottee': 'Non Promoter'},
         'groups': {'IssuedSecurity1': {'SecurityType': kind, 'NumberOfSecurities': str(n), 'AmountToBeRaised': str(amount),
                                        'RecordDateOrFutureRelevantDate': '2025-11-12',
                                        'MinimumIssuePricePerUnit': str(minimum), 'TermsOfPaymentInPercentage': terms}}}
    return issues.filing_rows('preferential', 'in_principle', [row]).assign(xbrl_status='ok', xbrl_json=json.dumps(x))


def test_approved_amount_a_power_of_ten_off_is_held_back():
    f = pd.concat([_approval('63777', 'RKFORGE', 19992000, 3400000, 586.77),                      # a hundredth of Rs 199.92 Cr
                   _approval('67204', 'SANGINITA', 449400000, 3444436, 13.05, 'Equity Shares', '1'),  # ten times too much
                   _approval('69999', 'INNOMET', 250362000, 1192200, 208.79),                     # at the minimum: as filed
                   _approval('59198', 'RKFORGE', 2047500000, 975000, 712.34)],                    # priced well above it: kept
                  ignore_index=True)
    df, rep = issues.clean_issues(None, 'preferential', f)
    by = df.set_index('app_id')
    assert pd.isna(by.at['63777', 'amount_total']) and pd.isna(by.at['67204', 'amount_total'])
    assert by.at['69999', 'amount_total'] == 250362000 and by.at['59198', 'amount_total'] == 2047500000
    assert by['amount_unreliable'].to_dict() == {'63777': True, '67204': True, '69999': False, '59198': False}
    assert rep['amount_power_of_ten'] == 2
