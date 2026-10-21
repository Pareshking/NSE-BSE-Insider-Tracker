"""Preferential and rights issues from NSE's two stage records (insiders_clean/issues.py).
Column names and value shapes are the ones in the stored data (09 Oct 2026)."""
from __future__ import annotations

from datetime import date

import pandas as pd
from insiders_clean import issues


def pref(stage, app_id, isin='INE0V9N01017', posted='09-OCT-2026', snapshot='2026-10-10T02:01:08+00:00', **kw):
    row = {'canonical_event_id': f'e{app_id}{stage[:2]}{snapshot[:10]}', 'appId': str(app_id), 'canonical_stage': stage,
           'canonical_isin': isin, 'canonical_symbol': 'PRIZOR', 'canonical_company': 'PRIZOR VIZTECH LIMITED',
           'systemDate': posted, 'dateOfSubmission': '01-SEP-2026', 'xmlFileName': 'https://x/y.xml',
           'ingested_at': snapshot}
    row.update(kw)
    return row


def frame(*rows):
    return pd.DataFrame(rows)


IN_P = dict(dateBrdResoln='27-AUG-2026', canonical_allottee_category='PROMOTER', considerationBy='Cash',
            totalAmtRaised='1325914000')
LIST = dict(offerPricePerSecurity='12.5', totalNumOfSharesAllotted='1,000,000', numberOfEquitySharesListed='1000000',
            dateOfAllotmentOfShares='05-OCT-2026', dateOfListing='12-OCT-2026', dateOfTradingApproval='10-OCT-2026',
            amountRaised='12500000')


def test_preferential_stage_records_are_read_by_shape():
    df = issues.normalise(frame(pref('In-Principle', 1, **IN_P), pref('Listing Stage', 2, posted='12-OCT-2026', **LIST)),
                          'preferential')
    ip = df[df['stage'] == 'in_principle'].iloc[0]
    assert ip['board_date'] == date(2026, 8, 27) and ip['amount_total'] == 1325914000
    assert ip['allottee_category'] == 'PROMOTER' and ip['posted_on'] == date(2026, 10, 9)
    ls = df[df['stage'] == 'listing'].iloc[0]
    assert ls['offer_price'] == 12.5 and ls['shares_allotted'] == 1_000_000
    assert ls['trading_approval_date'] == date(2026, 10, 10) and ls['allotment_date'] == date(2026, 10, 5)


def test_newest_snapshot_of_a_record_wins():
    df = issues.normalise(frame(
        pref('Listing Stage', 2, snapshot='2026-10-09T02:00:00+00:00', offerPricePerSecurity='10'),
        pref('Listing Stage', 2, snapshot='2026-10-10T02:00:00+00:00', offerPricePerSecurity='11')), 'preferential')
    assert len(df) == 1 and df['offer_price'].iloc[0] == 11


def test_absurd_amount_is_dropped_and_flagged():
    df = issues.normalise(frame(pref('In-Principle', 1, totalAmtRaised='3.64E+16')), 'preferential')
    assert pd.isna(df['amount_total'].iloc[0]) and bool(df['amount_unreliable'].iloc[0])


def linked(*rows, window=issues.LINK_WINDOW_DAYS):
    return issues.link_stages(issues.normalise(frame(*rows), 'preferential'), window)


def test_one_in_principle_record_links_and_carries_the_allottee_category():
    df = linked(pref('In-Principle', 1, posted='02-SEP-2026', **IN_P), pref('Listing Stage', 2, posted='12-OCT-2026', **LIST))
    ls = df[df['stage'] == 'listing'].iloc[0]
    assert ls['link_status'] == 'linked' and ls['linked_app_id'] == '1' and ls['allottee_category'] == 'PROMOTER'
    assert ls['board_date'] == date(2026, 8, 27)


def test_two_candidates_are_ambiguous_and_nothing_is_carried():
    df = linked(pref('In-Principle', 1, posted='02-SEP-2026', **IN_P), pref('In-Principle', 3, posted='20-SEP-2026', **IN_P),
                pref('Listing Stage', 2, posted='12-OCT-2026', **LIST))
    ls = df[df['stage'] == 'listing'].iloc[0]
    assert ls['link_status'] == 'ambiguous' and pd.isna(ls['allottee_category']) and ls['linked_app_id'] is None


def test_in_principle_outside_the_window_or_after_the_listing_does_not_count():
    old = linked(pref('In-Principle', 1, posted='01-JAN-2026', **IN_P), pref('Listing Stage', 2, posted='12-OCT-2026', **LIST))
    later = linked(pref('In-Principle', 1, posted='20-OCT-2026', **IN_P), pref('Listing Stage', 2, posted='12-OCT-2026', **LIST))
    other = linked(pref('In-Principle', 1, isin='INE000000001', posted='02-SEP-2026', **IN_P),
                   pref('Listing Stage', 2, posted='12-OCT-2026', **LIST))
    for df in (old, later, other):
        assert df[df['stage'] == 'listing']['link_status'].iloc[0] == 'no_in_principle_in_data'


def lock(category, approval='10-MAR-2026', link=True):
    ip = dict(IN_P, canonical_allottee_category=category)
    ls = dict(LIST, dateOfTradingApproval=approval)
    rows = [pref('Listing Stage', 2, posted='12-MAR-2026', **ls)]
    if link:
        rows.insert(0, pref('In-Principle', 1, posted='02-MAR-2026', **ip))
    df = issues.add_lock_in(issues.link_stages(issues.normalise(frame(*rows), 'preferential')))
    return df[df['stage'] == 'listing'].iloc[0]


def test_lock_in_is_18_months_for_promoters_and_6_for_others_from_trading_approval():
    p = lock('PROMOTER')
    assert p['lock_in_promoter_until'] == date(2027, 9, 10) and p['lock_in_other_until'] is None
    n = lock('NON_PROMOTER')
    assert n['lock_in_other_until'] == date(2026, 9, 10) and n['lock_in_promoter_until'] is None
    m = lock('MIXED')
    assert m['lock_in_promoter_until'] == date(2027, 9, 10) and m['lock_in_other_until'] == date(2026, 9, 10)


def test_no_lock_in_without_a_certain_link_or_a_trading_approval_date():
    unlinked = lock('PROMOTER', link=False)
    assert unlinked['lock_in_promoter_until'] is None and unlinked['lock_in_other_until'] is None
    no_date = lock('PROMOTER', approval=None)
    assert no_date['lock_in_promoter_until'] is None


def test_rights_records_keep_ratio_dates_and_price():
    raw = pd.DataFrame([
        {'canonical_event_id': 'a', 'appId': '72509', 'canonical_stage': 'In-Principle', 'canonical_isin': 'INE0LXG01040',
         'canonical_symbol': 'OLAELEC', 'canonical_company': 'OLA ELECTRIC MOBILITY LIMITED', 'sysDateTime': '06-OCT-2026',
         'dateOfSubmission': '05-OCT-2026', 'dateOfBrdResIssueApproving': '28-SEP-2026', 'considerationBy': 'Cash',
         'totalAmntRaised': '10000000000', 'ingested_at': '2026-10-10T02:01:03+00:00'},
        {'canonical_event_id': 'b', 'appId': '70001', 'canonical_stage': 'Listing Stage', 'canonical_isin': 'INE0LXG01040',
         'canonical_symbol': 'OLAELEC', 'canonical_company': 'OLA ELECTRIC MOBILITY LIMITED', 'sysDateTime': '09-OCT-2026',
         'dtOfSubmission': '08-OCT-2026', 'offerPrice': '40', 'rightRatio': '1:5', 'recordDate': '01-SEP-2026',
         'issueOpenDate': '10-SEP-2026', 'issueCloseDate': '24-SEP-2026', 'noOfSharesAlloted': '5000',
         'dtOfAllotmentsOfShare': '02-OCT-2026', 'dateOfListing': '07-OCT-2026', 'dateOfTradingApp': '06-OCT-2026',
         'ingested_at': '2026-10-10T02:01:03+00:00'}])
    df, report = issues.clean_issues(raw, 'rights')
    ls = df[df['stage'] == 'listing'].iloc[0]
    assert ls['ratio'] == '1:5' and ls['offer_price'] == 40 and ls['record_date'] == date(2026, 9, 1)
    assert ls['issue_close_date'] == date(2026, 9, 24) and ls['link_status'] == 'linked'
    assert ls['allotment_date'] == date(2026, 10, 2) and ls['trading_approval_date'] == date(2026, 10, 6)
    assert report['listing'] == 1 and report['in_principle'] == 1 and report['link_status'] == {'linked': 1}
    assert 'lock_in_promoter_until' not in df.columns  # rights carry no lock-in


def test_empty_input_gives_an_empty_table_and_a_report():
    df, report = issues.clean_issues(pd.DataFrame(), 'preferential')
    assert df.empty and report == {'input_rows': 0, 'records': 0}


def test_clean_tables_write_to_parquet():
    import io
    raw = frame(pref('In-Principle', 1, posted='02-SEP-2026', **IN_P), pref('Listing Stage', 2, posted='12-OCT-2026', **LIST),
                pref('Listing Stage', 4, isin='INE000000002', posted='12-OCT-2026'))
    df, _ = issues.clean_issues(raw, 'preferential')
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    back = pd.read_parquet(io.BytesIO(buf.getvalue()))
    assert len(back) == 3 and back['lock_in_promoter_until'].notna().sum() == 1


# --- the Capital raises page's row builders ----------------------------------------------

def _page():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'streamlit_app'))
    from screens import capital_raises
    return capital_raises


PRICES = pd.DataFrame({'isin': ['INE0V9N01017'], 'latest_close': [25.0], 'low_52w': [10.0], 'high_52w': [30.0],
                       'pct_off_high': [-16.0], 'mcap_bucket': ['Small']})


def _clean_pref(*rows):
    return issues.clean_issues(frame(*rows), 'preferential')[0]


def test_issue_rows_show_the_allotment_with_its_approvals_terms_and_open_approvals_apart():
    cr = _page()
    df = _clean_pref(pref('In-Principle', 1, posted='02-MAR-2026', **IN_P), pref('Listing Stage', 2, posted='12-MAR-2026', **LIST),
                     pref('In-Principle', 5, isin='INE000000009', posted='09-OCT-2026', **IN_P))
    rows = cr.issue_rows(df, PRICES)
    assert sorted(rows['status']) == ['Allotted or listed', 'Approved in principle']   # the linked approval is not listed twice
    listed = rows[rows['status'] == 'Allotted or listed'].iloc[0]
    assert listed['to'] == 'Promoters' and listed['amount'] == 12500000   # raised (10 lakh x Rs 12.50), not the approved size (audit W11)
    assert round(listed['vs_market'], 1) == -50.0 and listed['latest_close'] == 25.0   # offer 12.5 against 25


def test_lock_in_calendar_orders_by_expiry_and_gives_no_market_value_for_a_mixed_allotment():
    cr = _page()
    promoter = dict(IN_P, canonical_allottee_category='PROMOTER')
    mixed = dict(IN_P, canonical_allottee_category='MIXED')
    df = _clean_pref(
        pref('In-Principle', 1, posted='02-MAR-2026', **promoter),
        pref('Listing Stage', 2, posted='12-MAR-2026', **dict(LIST, dateOfTradingApproval='10-MAR-2026')),
        pref('In-Principle', 3, isin='INE000000009', posted='02-JUN-2026', **mixed),
        pref('Listing Stage', 4, isin='INE000000009', posted='12-JUN-2026', **dict(LIST, dateOfTradingApproval='10-JUN-2026')))
    cal = cr.lock_in_calendar(df, PRICES, pd.Timestamp('2026-10-12'))
    assert list(cal['expires'].dt.date) == [date(2026, 12, 10), date(2027, 9, 10), date(2027, 12, 10)]
    assert list(cal['who']) == ['Others', 'Promoters', 'Promoters']
    mixed_rows = cal[cal['note'] != '']
    assert len(mixed_rows) == 2 and mixed_rows['at_market'].isna().all()
    pure = cal[cal['note'] == ''].iloc[0]
    assert pure['at_market'] == 1_000_000 * 25.0 and pure['days_left'] == (date(2027, 9, 10) - date(2026, 10, 12)).days


def test_link_summary_counts_each_outcome():
    cr = _page()
    df = _clean_pref(pref('In-Principle', 1, posted='02-MAR-2026', **IN_P), pref('Listing Stage', 2, posted='12-MAR-2026', **LIST),
                     pref('Listing Stage', 4, isin='INE000000009', posted='12-MAR-2026', **LIST))
    text = cr.link_summary(df)
    assert '2 allotment records: 1 matched' in text and '1 whose approval is not in' in text
