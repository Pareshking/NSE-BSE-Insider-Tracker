"""Further-issue filings by date window, their XBRL, and QIPs (insiders_clean/issues.py).

Fixtures in tests/fixtures/capital/ are real NSE responses: rows of
/api/corporate-further-issues-pref, -ri and -qip (both stages, fetched 09 Oct
2026 for 08-10-2025 to 09-10-2026) and the XBRL files those rows link to
(nsearchives.nseindia.com/corporate/xbrl/); qip_ls_72568.xml and
pref_ip_71199.xml were fetched 12 Oct 2026.
"""
from __future__ import annotations

import io
import json
from datetime import date

import pandas as pd
import pytest
from conftest import FIXTURES

from insiders_clean import archive, issues

CAP = FIXTURES / 'capital'
LISTS = {('preferential', 'in_principle'): 'pref_in_principle.json', ('preferential', 'listing'): 'pref_listing.json',
         ('rights', 'in_principle'): 'rights_in_principle.json', ('rights', 'listing'): 'rights_listing.json',
         ('qip', 'in_principle'): 'qip_in_principle.json', ('qip', 'listing'): 'qip_listing.json'}
PREFIX = {'preferential': 'pref', 'rights': 'rights', 'qip': 'qip'}


def load(name):
    return json.loads((CAP / name).read_text(encoding='utf-8'))


def xbrl_file(kind, stage, app):
    return CAP / f"{PREFIX[kind]}_{'ip' if stage == 'in_principle' else 'ls'}_{app}.xml"


def filings(run_date='2026-10-09'):
    """Archive rows as the nightly job stores them: list rows plus the parsed
    XBRL where the fixture has the file, read back through archive.merge."""
    frames = []
    for (kind, stage), name in LISTS.items():
        df = issues.filing_rows(kind, stage, load(name))
        status, facts = [], []
        for a in df['app_id']:
            f = xbrl_file(kind, stage, a)
            wanted = (kind, stage) in issues.XBRL_WANTED
            status.append('ok' if wanted and f.exists() else 'pending' if wanted else 'not_needed')
            facts.append(json.dumps(issues.parse_xbrl(f.read_bytes())) if wanted and f.exists() else None)
        frames.append(df.assign(xbrl_status=status, xbrl_json=facts))
    merged, _ = archive.merge(None, pd.concat(frames, ignore_index=True), run_date, key='event_id')
    return merged


@pytest.fixture(scope='module')
def pref():
    f = filings()
    df, rep = issues.clean_issues(None, 'preferential', f)
    return df, rep, issues.xbrl_facts(f)


def one(df, **kw):
    m = pd.Series(True, index=df.index)
    for k, v in kw.items():
        m &= df[k] == v
    assert m.sum() == 1, (kw, int(m.sum()))
    return df[m].iloc[0]


def test_window_rows_become_one_archive_row_per_filing_with_nse_posting_date():
    df = issues.filing_rows('preferential', 'listing', load('pref_listing.json'))
    assert df['event_id'].is_unique and len(df) == 11
    r = one(df, app_id='72089')
    assert (r['symbol'], r['isin'], r['posted_on']) == ('SPECTRUM', 'INE01EO01010', '2026-10-06')
    assert json.loads(r['raw_json'])['appId'] == '72089'
    q = issues.filing_rows('qip', 'listing', load('qip_listing.json'))   # QIP: boardResolutionDate is the posting date
    assert one(q, app_id='72568')['posted_on'] == '2026-10-01' and one(q, app_id='72568')['symbol'] == 'INOXGREEN'


def test_xbrl_groups_securities_allottees_and_lock_ins():
    ip = issues.parse_xbrl((CAP / 'pref_ip_63339.xml').read_bytes())
    assert [s['SecurityType'] for s in issues.groups_of(ip, 'IssuedSecurity')] == ['Equity Shares', 'Warrants']
    assert len(issues.groups_of(ip, 'Allottees')) == 17 and ip['main']['CategoryOfAllottee'] == 'Promoter & Non Promoter'
    ls = issues.parse_xbrl((CAP / 'pref_ls_65108.xml').read_bytes())
    assert [(o['PeriodOfLockInShares'], o['NumberOfLockInShares']) for o in issues.groups_of(ls, 'Option')] == [
        ('Equity shares for 18 months', '315000'), ('Equity shares for 6 months', '137000')]
    new = issues.parse_xbrl((CAP / 'pref_ip_71199.xml').read_bytes())   # the 2026 taxonomy version reads the same
    assert issues.groups_of(new, 'IssuedSecurity')[0]['MinimumIssuePricePerUnit'] == '565.96'
    with pytest.raises(ValueError):
        issues.parse_xbrl('<xbrl></xbrl>')
    assert issues.lock_in_months('Equity shares for 18 months') == 18 and issues.lock_in_months('1 year') == 12
    assert issues.lock_in_months('90 trading days') is None


def test_window_filings_and_snapshots_clean_the_same_way(pref):
    df, rep, _ = pref
    assert rep['window_filings'] == 18 and rep['records'] == 18
    snap = issues.as_canonical(filings(), 'preferential')
    again, _ = issues.clean_issues(snap, 'preferential', filings())   # the same filing in both sources is one record
    assert len(again) == 18


def test_filed_icdr_minimum_and_relevant_date_reach_the_matched_allotment(pref):
    df, rep, _ = pref
    ip = one(df, app_id='70500')
    assert ip['icdr_min_price'] == 2001.04 and ip['relevant_date'] == date(2026, 7, 21)
    assert ip['instruments'] == 'Equity Shares; Warrants'
    ls = one(df, app_id='72089')
    assert ls['link_status'] == 'linked' and ls['linked_app_id'] == '70500'
    assert ls['icdr_min_price'] == 2001.04 and ls['offer_price'] == 2002
    assert ls['vs_icdr_min'] == pytest.approx((2002 / 2001.04 - 1) * 100)
    assert rep['icdr_min_filed'] >= 2


def test_two_instruments_with_one_minimum_price_keep_it(pref):
    df, _, _ = pref
    t = one(df, app_id='63339')
    assert t['icdr_min_price'] == 215.1 and t['securities_proposed'] == 611112 + 7997000


def test_an_approval_for_fewer_shares_than_allotted_is_not_linked(pref):
    df, rep, _ = pref
    k = one(df, app_id='65108')   # 452,000 allotted at Rs 130; the only approval was a 333,700-share swap at Rs 202.61
    assert k['link_status'] == 'more_shares_than_approved'
    assert k['linked_app_id'] is None and k['allottee_category'] is None and pd.isna(k['icdr_min_price'])
    lloyds = one(df, app_id='65487')   # 15,268,950 allotted at Rs 740 against 1,957,458 proposed at a Rs 1,460.50 minimum
    assert lloyds['link_status'] == 'more_shares_than_approved' and lloyds['lock_in_other_until'] is None
    assert rep['link_status']['more_shares_than_approved'] == 2


def test_filed_lock_in_lines_win_and_the_rule_fills_in_without_them(pref):
    df, _, facts = pref
    lines = issues.lock_in_lines(df, facts)
    k = lines[lines['app_id'] == '65108'].set_index('months')
    assert set(k['basis']) == {'filed'}                  # filed lines need no link to the approval
    assert k.loc[18, 'shares'] == 315000 and k.loc[18, 'expires'] == date(2027, 9, 5)
    assert k.loc[6, 'shares'] == 137000 and k.loc[6, 'expires'] == date(2026, 9, 5)
    ambey = lines[lines['app_id'] == '69322'].set_index('months')   # an older 36-month lock-in, shown as filed
    assert ambey.loc[36, 'shares'] == 4989364
    assert '65487' not in set(lines['app_id'])          # listing XBRL not parsed and no certain approval: no date
    based = issues.with_lock_in_basis(df, lines)
    assert one(based, app_id='65108')['lock_in_basis'] == 'filed' and pd.isna(one(based, app_id='70500')['lock_in_basis'])


def test_without_filed_lines_the_rule_dates_a_matched_allotment():
    f = filings()
    f.loc[f['app_id'] == '72089', ['xbrl_status', 'xbrl_json']] = ['pending', None]   # listing XBRL not parsed yet
    df, _ = issues.clean_issues(None, 'preferential', f)
    lines = issues.lock_in_lines(df, issues.xbrl_facts(f)).set_index('who')
    spectrum = lines[lines['app_id'] == '72089']       # approval 70500 is to promoters and others: both dates, no shares
    assert set(spectrum['basis']) == {'rule'} and spectrum['shares'].isna().all()
    assert spectrum.loc['Promoters', 'expires'] == date(2028, 4, 7) and spectrum.loc['Others', 'expires'] == date(2027, 4, 7)


def test_allottees_carry_the_issue_category_never_a_guessed_promoter_flag(pref):
    df, _, facts = pref
    a = issues.allottee_rows(df, facts)
    t = a[a['app_id'] == '63339']
    assert len(t) == 17 and t['promoter'].isna().all()          # mixed issue: no per-allottee status
    assert one(t, allottee='Prakash Shah')['securities'] == 409723
    k = one(a, app_id='61185')
    assert (k['allottee'], k['promoter'], k['securities']) == ('Manoj Agarwal', True, 333700)


def test_our_icdr_estimate_is_the_higher_vwap_on_the_busier_exchange_and_needs_90_sessions():
    days = pd.bdate_range('2026-03-02', periods=100)
    nse = pd.DataFrame({'date': days, 'exchange': 'NSE', 'isin': 'I1', 'volume': 1000.0,
                        'value': [1000.0 * (100 if i < 90 else 120) for i in range(100)]})
    bse = nse.assign(exchange='BSE', volume=10.0, value=nse['value'] / 100)
    daily = pd.concat([nse, bse])
    relevant = days[-1] + pd.Timedelta(days=1)
    price, ex = issues.icdr_floor_estimate(daily, 'I1', relevant)
    assert ex == 'NSE' and price == 120.0                         # last 10 sessions at 120 beat the 90-session average
    price90, _ = issues.icdr_floor_estimate(daily, 'I1', days[90])   # before the rise: 90 sessions at 100
    assert price90 == 100.0
    assert issues.icdr_floor_estimate(daily, 'I1', days[50]) == (None, 'under_90_sessions')
    assert issues.icdr_floor_estimate(daily, 'I1', relevant, [days[95]]) == (None, 'split_or_bonus_in_window')
    assert issues.icdr_floor_estimate(daily, 'I2', relevant) == (None, 'no_prices')


def test_icdr_estimate_lands_on_records_with_a_filed_relevant_date():
    f = filings()
    rel = pd.Timestamp('2026-07-21')
    days = pd.bdate_range(end=rel - pd.Timedelta(days=1), periods=95)
    daily = pd.DataFrame({'date': days, 'exchange': 'NSE', 'isin': 'INE01EO01010', 'volume': 10.0, 'value': 19000.0})
    df, rep = issues.clean_issues(None, 'preferential', f, daily, {})
    for app in ('70500', '72089'):
        r = one(df, app_id=app)
        assert r['icdr_min_ours'] == 1900.0 and r['icdr_ours_exchange'] == 'NSE'
    assert one(df, app_id='63339')['icdr_ours_note'] == 'no_prices' and rep['icdr_min_ours'] == 2
    assert issues.price_months(f)[0] <= '2025-03' and '2026-07' in issues.price_months(f)


def test_qip_records_link_stages_check_amounts_and_name_the_allottees():
    q, allottees, rep = issues.clean_qip(filings())
    inox = one(q, app_id='72568')
    assert (inox['issue_price'], inox['floor_price'], inox['discount_per_share'], inox['allottees']) == (165.65, 165.65, 8.71, 20)
    assert inox['amount_raised'] == 3_000_000_000 and inox['trading_approval_date'] == date(2026, 10, 5)
    assert inox['relevant_date'] == date(2026, 9, 24) and not inox['amount_unreliable']
    wheels = one(q, app_id='72449')
    assert wheels['link_status'] == 'linked' and wheels['linked_app_id'] == '72364'
    ip = one(q, app_id='72679')
    assert ip['amount_total'] == 6_000_000_000 and ip['shareholder_approval_date'] == date(2026, 9, 10)
    a = allottees[allottees['app_id'] == '72568']
    assert len(a) == 20 and rep['listings_with_allottees'] == 1
    elm = one(a, allottee='Elm Park Fund Limited')
    assert (elm['category'], elm['shares'], elm['pct_of_issue']) == ('Foreign Portfolio Investor', 1811047, 10.0)


def test_qip_amount_far_from_shares_times_price_is_held_back():
    rows = load('qip_listing.json')
    bad = dict(rows[0], appId='99999', finalAmountOfIssueSize='300000000000000')
    f = issues.filing_rows('qip', 'listing', [rows[0], bad])
    q, _, rep = issues.clean_qip(f.assign(xbrl_status='pending'))
    assert pd.isna(one(q, app_id='99999')['amount_raised']) and one(q, app_id='99999')['amount_unreliable']
    assert rep['amount_unreliable'] == 1


def test_rights_take_window_filings_too():
    r, rep = issues.clean_issues(None, 'rights', filings())
    jk = one(r, app_id='72319')
    assert (jk['ratio'], jk['offer_price'], jk['link_status']) == ('3:19', 75, 'linked')
    assert rep['window_filings'] == 8 and 'icdr_min_price' not in r.columns


def test_clean_writer_builds_every_issue_table_from_the_archive():
    import clean_writer
    from test_archive_and_writer import FakeR2, parquet
    r2 = FakeR2()
    r2.objects['archive/nse_events/issues/year=2026.parquet'] = parquet(filings())
    tables, rep = clean_writer.issue_tables(r2)
    assert set(tables) == {'preferential', 'rights', 'preferential_lockins', 'preferential_allottees', 'qip', 'qip_allottees'}
    assert rep['preferential']['lock_in_lines']['filed'] >= 10 and rep['qip']['listing'] == 4
    for name, df in tables.items():   # every table writes to parquet
        buf = io.BytesIO()
        df.to_parquet(buf, index=False)
        assert len(pd.read_parquet(io.BytesIO(buf.getvalue()))) == len(df), name


# --- the Capital raises page's builders ---------------------------------------------------

def _page():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'streamlit_app'))
    from screens import capital_raises
    return capital_raises


def test_lock_in_calendar_reads_filed_lines_and_values_them(pref):
    cr = _page()
    df, _, facts = pref
    lines = issues.lock_in_lines(df, facts)
    prices = pd.DataFrame({'isin': ['INE694E01014'], 'latest_close': [200.0], 'low_52w': [1.0], 'high_52w': [2.0],
                           'pct_off_high': [0.0], 'mcap_bucket': ['Micro']})
    cal = cr.lock_in_calendar(df, prices, pd.Timestamp('2026-09-01'), lines)
    k = cal[cal['symbol'] == 'KANPRPLA'].set_index('months')
    assert k.loc[18, 'what'] == '18 months, as filed' and k.loc[18, 'at_market'] == 315000 * 200.0
    assert set(cal['basis']) == {'filed'}
    assert cal['expires'].is_monotonic_increasing and (cal['expires'] >= pd.Timestamp('2026-08-02')).all()


def test_qip_rows_show_allotments_and_open_approvals_once():
    cr = _page()
    q, allottees, _ = issues.clean_qip(filings())
    rows = cr.qip_rows(q, pd.DataFrame())
    assert '72364' not in set(rows['app_id'])                  # WHEELS approval is shown through its allotment
    assert set(rows['status']) == {'Allotted or listed', 'Approved in principle'}
    buyers = cr.allottee_rows(allottees, {'elm-park-fund-limited'})
    assert one(buyers, allottee='Elm Park Fund Limited')['client_id'] == 'elm-park-fund-limited'
    assert buyers['client_id'].notna().sum() == 1             # names with no page of their own stay plain text
