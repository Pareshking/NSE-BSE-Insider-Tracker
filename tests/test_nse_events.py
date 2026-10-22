"""NSE corporate events: parsers on real payloads fetched 07 Oct 2026
(tests/fixtures/nse_events/), and the nightly job against an in-memory R2."""
from __future__ import annotations

import io
import json
from datetime import date

import pandas as pd
import pytest
from conftest import FIXTURES
from test_archive_and_writer import FakeR2

from collectors.nse_events import parsers
from collectors.nse_events.client import Blocked

EV = FIXTURES / 'nse_events'


def load(name):
    return json.loads((EV / name).read_text(encoding='utf-8'))


# --- parsers ---------------------------------------------------------------------

def test_sast_rows():
    df = parsers.parse_sast(load('sast_reg29.json'))
    k = df[df['symbol'] == 'KRONOX'].iloc[0]
    assert (k['action_type'], k['mode'], k['regulation']) == ('Sale', 'Others', 'Reg29(2)')
    assert k['shares_traded'] == -8566400 and k['percent_equity_traded'] == -23.08
    assert k['post_stake_pct'] == 3.32 and k['transaction_date'] == date(2026, 9, 29)
    assert k['is_promoter'] and not k['is_market']
    assert df.loc[df['symbol'] == 'ORICONENT', 'is_market'].iloc[0]  # 'Open Market'
    assert df['event_id'].is_unique


def test_sast_missing_figures_stay_empty_but_filed_zero_stays_zero():
    rows = load('sast_reg29.json')
    goodluck = parsers.parse_sast([r for r in rows if r['symbol'] == 'GOODLUCK']).iloc[0]
    assert goodluck['shares_traded'] == 0  # the filing itself says 0 (inter-se transfer)
    blank = dict(rows[0], noOfShareAcq=None, noOfShareSale=None, totAcqShare=None, totSaleShare=None)
    b = parsers.parse_sast([blank]).iloc[0]
    assert pd.isna(b['shares_traded']) and pd.isna(b['percent_equity_traded'])


def test_corporate_actions_keep_five_purposes_and_read_details():
    df, dropped = parsers.parse_corporate_actions(load('corporate_actions.json'))
    assert set(df['purpose']) == {'buyback', 'bonus', 'split', 'rights', 'dividend'}
    assert dropped > 0  # demergers, interest payments, unit distributions
    r = df[df['subject'] == 'Rights 3:5 @ Premium Rs 45/-'].iloc[0]
    assert (r['ratio'], r['face_value'], r['rights_premium'], r['rights_issue_price']) == ('3:5', 5.0, 45.0, 50.0)
    assert r['needs_price_gap']
    s = df[df['purpose'] == 'split'].iloc[0]
    assert s['face_value_from'] == 10 and s['face_value_to'] in (1, 2, 5)
    assert df.loc[df['purpose'] == 'bonus', 'ratio'].notna().all()
    special = df[df['subject'] == 'Dividend - Rs 14 Per Share/Special Dividend - Rs 6 Per Share'].iloc[0]
    assert special['dividend_per_share'] == 20
    assert df.loc[df['purpose'] == 'buyback', 'needs_price_gap'].all()


def test_board_meetings_drop_routine_and_combine_notices():
    raw = load('board_meetings.json')
    df, dropped = parsers.parse_board_meetings(raw)
    assert len(df) < len(raw) and dropped >= 1
    assert df.duplicated(['symbol', 'meeting_date']).sum() == 0  # one row per meeting
    afil = df[df['symbol'] == 'AFIL'].iloc[0]
    assert afil['fund_raising'] and afil['purposes'] == 'fund_raising'
    assert df.loc[df['symbol'] == 'DMART', 'results'].iloc[0]


def test_shareholding_listing_and_pledge_from_xbrl():
    listing = parsers.parse_shareholding_listing(load('shareholding_listing.json'))
    assert listing['promoter_holding_pct'].notna().all() and listing['xbrl_url'].notna().any()
    facts = parsers.parse_shp_xbrl((EV / 'shp_ZEEL_2026Q2.xml').read_text(encoding='utf-8'))
    assert facts['promoter_shares'] == 38316284 and facts['total_shares'] == 960519420
    assert facts['promoter_pledged_shares'] == 2060000
    assert round(facts['promoter_pledge_pct'], 2) == 5.38      # % of promoter shares
    assert round(facts['promoter_holding_pct_xbrl'], 2) == 3.99


def test_xbrl_without_totals_is_refused():
    with pytest.raises(ValueError):
        parsers.parse_shp_xbrl('<xbrl></xbrl>')


# --- nightly job -----------------------------------------------------------------

CAP = FIXTURES / 'capital'
ISSUE_LISTS = {('preferential', 'in_principle'): 'pref_in_principle.json', ('preferential', 'listing'): 'pref_listing.json',
               ('rights', 'in_principle'): 'rights_in_principle.json', ('rights', 'listing'): 'rights_listing.json',
               ('qip', 'in_principle'): 'qip_in_principle.json', ('qip', 'listing'): 'qip_listing.json'}


def _issue_xml():
    """XBRL URL in the further-issue fixtures -> the fixture file holding it."""
    out = {}
    for (kind, stage), name in ISSUE_LISTS.items():
        for row in json.loads((CAP / name).read_text(encoding='utf-8')):
            f = CAP / f"{dict(preferential='pref', rights='rights', qip='qip')[kind]}_{'ip' if stage == 'in_principle' else 'ls'}_{row['appId']}.xml"
            if f.exists():
                out[row['xmlFileName']] = f
    return out


ISSUE_XML = _issue_xml()


class FakeNSE:
    def __init__(self, block_xbrl=False):
        self.calls = 0
        self.issue_xbrl = []
        self.block_xbrl = block_xbrl
        self.xml = (EV / 'shp_ZEEL_2026Q2.xml').read_text(encoding='utf-8')

    def _n(self, payload):
        self.calls += 1
        return payload

    def sast_reg29(self, s, e):
        return self._n(load('sast_reg29.json'))

    def corporate_actions(self, s, e):
        return self._n(load('corporate_actions.json'))

    def board_meetings(self, s, e):
        return self._n(load('board_meetings.json'))

    def shareholding_filings(self, s, e):
        return self._n(load('shareholding_listing.json')[:5])

    def tender_offers_past(self):
        return self._n(load('tender_offers_past.json')['data'])

    def tender_offers_active(self):
        return self._n(load('tender_offers_active.json'))

    def daily_buybacks(self, s, e):
        return self._n(load('daily_buybacks.json')['data'])

    def xbrl(self, url):
        self.calls += 1
        if self.block_xbrl and self.calls > 6:
            raise Blocked('HTTP 403')
        if 'INTEGRATED_FILING' in url:   # a results XBRL
            from test_results import XBRL
            return XBRL
        if '_ISSUE_' in url or '/QIP_' in url:   # a further-issue XBRL
            self.issue_xbrl.append(url)
            if url not in ISSUE_XML:
                raise RuntimeError('HTTP 404')
            return ISSUE_XML[url].read_text(encoding='utf-8')
        return self.xml

    # further issues: the list text for one kind and stage, as NSE sends it
    issue_xbrl: list = []

    def further_issues_url(self, kind, stage, s, e):
        return f'further:{kind}:{stage}'

    def integrated_results_url(self, s, e, page=1, size=100):   # financial results (tests/test_results.py shapes)
        return f'results:{page}'

    def get(self, url, as_json=True):
        self.calls += 1
        if url.startswith('results:'):
            from test_results import ROW
            return json.dumps({'data': [ROW] if url == 'results:1' else [], 'totalCount': 1})
        _, kind, stage = url.split(':')
        return (CAP / ISSUE_LISTS[(kind, stage)]).read_text(encoding='utf-8')


@pytest.fixture()
def events(monkeypatch):
    import clean_writer

    from collectors.nse_events import run_daily

    class Resp:
        status_code = 200

        def __init__(self, path):
            self.content = path.read_bytes()

    monkeypatch.setattr(clean_writer.requests, 'get', lambda url, **kw: Resp(
        FIXTURES / ('nse_sme_sample.csv' if 'SME' in url else 'nse_equity_sample.csv')))
    return FakeR2(), run_daily


def frame(r2, key):
    return pd.read_parquet(io.BytesIO(r2.objects[key]))


def test_nightly_run_writes_archive_clean_and_report(events):
    r2, run_daily = events
    rep = run_daily.run(r2, FakeNSE(), date(2026, 10, 7), 10)
    for stream in run_daily.STREAMS:
        if stream != run_daily.ISSUES:   # issues are cleaned by scripts/clean_writer.py
            assert f'clean/current/{stream}.parquet' in r2.objects, stream
        assert any(k.startswith(f'archive/nse_events/{stream}/year=') for k in r2.objects), stream
    sh = frame(r2, 'clean/current/shareholding.parquet')
    assert set(sh['xbrl_status']) == {'ok'} and round(float(sh['promoter_pledge_pct'].iloc[0]), 2) == 5.38
    assert rep['xbrl_fetched'] == 5
    res = frame(r2, 'clean/current/results.parquet')
    assert res['quarter_revenue'].tolist() == [67883400000.0] and res['isin'].tolist() == ['INE239A01024']
    assert json.loads(r2.objects['clean/reports/nse_events/2026-10-07.json'])['window'] == ['2026-09-27', '2026-10-07']


def test_second_run_adds_nothing_and_skips_parsed_xbrl(events):
    r2, run_daily = events
    run_daily.run(r2, FakeNSE(), date(2026, 10, 7), 10)
    nse = FakeNSE()
    rep = run_daily.run(r2, nse, date(2026, 10, 8), 10)
    assert all(s['added'] == 0 for s in rep['streams'].values())
    assert rep['xbrl_fetched'] == 0          # already parsed last night
    sast = frame(r2, 'clean/current/sast.parquet')
    assert sast['event_id'].is_unique


def test_refusal_keeps_what_was_parsed_and_marks_rest_pending(events):
    r2, run_daily = events
    rep = run_daily.run(r2, FakeNSE(block_xbrl=True), date(2026, 10, 7), 10)
    sh = frame(r2, 'clean/current/shareholding.parquet')
    assert (sh['xbrl_status'] == 'ok').sum() >= 1 and (sh['xbrl_status'] == 'pending').sum() >= 1
    assert any('refused' in n for n in rep['notes'])


def test_failed_quarter_carries_previous_pledge_forward():
    from collectors.nse_events.run_daily import clean_shareholding
    arch = pd.DataFrame({
        'symbol': ['ABC', 'ABC'], 'quarter_end': ['2026-03-31', '2026-06-30'],
        'submission_date': ['2026-04-20', '2026-07-20'], 'xbrl_status': ['ok', 'failed: ValueError'],
        'promoter_pledge_pct': [42.0, None], 'promoter_encumbered_pct': [45.0, None]})
    out = clean_shareholding(arch).set_index('quarter_end')
    latest = out.loc[pd.Timestamp('2026-06-30')]
    assert latest['promoter_pledge_pct'] == 42.0 and latest['shareholding_stale']
    assert not out.loc[pd.Timestamp('2026-03-31'), 'shareholding_stale']


def test_batch_size_limits_the_pledge_files_and_the_report_counts_what_is_left(events):
    r2, run_daily = events
    rep = run_daily.run(r2, FakeNSE(), date(2026, 10, 7), 10, max_xbrl=2)
    assert rep['xbrl_fetched'] == 2
    cov = rep['streams']['shareholding']['coverage']
    assert cov['pending_xbrl'] == 3 and rep['pending_xbrl'] == 3
    assert cov['xbrl_status']['ok'] == 2 and cov['companies'] == 5
    # the next run picks up the rest and nothing is fetched twice
    rep2 = run_daily.run(r2, FakeNSE(), date(2026, 10, 8), 10, max_xbrl=10)
    assert rep2['xbrl_fetched'] == 3 and rep2['pending_xbrl'] == 0


def test_newest_quarter_is_fetched_first():
    from collectors.nse_events.run_daily import fetch_xbrl
    listing = pd.DataFrame({
        'event_id': ['old', 'new'], 'xbrl_url': ['u1', 'u2'],
        'quarter_end': pd.to_datetime(['2026-03-31', '2026-06-30'])})
    nse = FakeNSE()
    out = fetch_xbrl(nse, listing, None, {'notes': []}, max_xbrl=1).set_index('event_id')
    assert out.loc['new', 'xbrl_status'] == 'ok' and out.loc['old', 'xbrl_status'] == 'pending'


def test_coverage_counts_latest_quarter_per_company():
    from collectors.nse_events.run_daily import shareholding_coverage
    df = pd.DataFrame({
        'symbol': ['A', 'A', 'B'],
        'quarter_end': pd.to_datetime(['2026-03-31', '2026-06-30', '2026-06-30']),
        'xbrl_status': ['ok', 'pending', 'ok'],
        'promoter_pledge_pct': [1.0, 1.0, None]})
    c = shareholding_coverage(df)
    assert c['companies'] == 2 and c['pending_xbrl'] == 1 and c['pending_latest'] == 1
    assert c['latest_quarter_of_company'] == {'2026-06-30': 2} and c['latest_with_pledge'] == 1


def test_coverage_names_why_pledge_files_failed():
    from collectors.nse_events.run_daily import shareholding_coverage
    df = pd.DataFrame({
        'symbol': ['A', 'B', 'C', 'D'],
        'quarter_end': pd.to_datetime(['2026-06-30'] * 4),
        'xbrl_status': ['ok', 'failed: KeyError', 'failed: KeyError', 'failed: ParseError'],
        'promoter_pledge_pct': [1.0, None, None, None]})
    c = shareholding_coverage(df)
    assert c['xbrl_failure_types'] == {'failed: KeyError': 2, 'failed: ParseError': 1}


# --- further issues -------------------------------------------------------------------

def test_further_issues_are_archived_with_their_xbrl_and_raw_bytes(events):
    r2, run_daily = events
    nse = FakeNSE()
    rep = run_daily.run(r2, nse, date(2026, 10, 9), 10, streams=(run_daily.ISSUES,))
    arch = run_daily.merge_into_archive(r2, run_daily.ISSUES, None, '')[0]
    assert arch['event_id'].is_unique and set(arch['kind']) == {'preferential', 'rights', 'qip'}
    status = dict(zip(arch['event_id'], arch['xbrl_status']))
    assert status['preferential:listing:65108'] == 'ok' and status['qip:listing:72568'] == 'ok'
    assert status['rights:listing:72319'] == 'not_needed'                 # its XBRL adds nothing to the list
    assert status['preferential:listing:65487'] == 'failed: RuntimeError'  # no fixture file: counted, not fatal
    assert not any('/RIGHT' in u for u in nse.issue_xbrl)
    cov = rep['streams']['issues']['coverage']
    assert cov['filings']['preferential/listing'] == 11 and cov['xbrl_status']['ok'] >= 15
    assert sum(k.startswith('raw_v2/nse/further_issues/blobs/') for k in r2.objects) == 6
    assert any(k.startswith('raw_v2/nse/further_issue_xbrl/blobs/') for k in r2.objects)
    assert 'clean/current/issues.parquet' not in r2.objects
    again = FakeNSE()
    rep2 = run_daily.run(r2, again, date(2026, 10, 10), 10, streams=(run_daily.ISSUES,))
    failed = sum(str(v).startswith('failed') for v in status.values())
    assert rep2['issue_xbrl_fetched'] == failed == len(again.issue_xbrl)   # parsed files are not fetched again


def test_issue_xbrl_cap_leaves_the_rest_pending_and_retries_them(events):
    r2, run_daily = events
    rep = run_daily.run(r2, FakeNSE(), date(2026, 10, 9), 10, streams=(run_daily.ISSUES,), max_issue_xbrl=3)
    arch = run_daily.merge_into_archive(r2, run_daily.ISSUES, None, '')[0]
    assert rep['issue_xbrl_fetched'] == 3 and (arch['xbrl_status'] == 'pending').sum() > 0
    newest = arch[arch['xbrl_status'].isin(['ok', 'failed: RuntimeError'])]['posted_on'].min()
    assert newest >= arch.loc[arch['xbrl_status'] == 'pending', 'posted_on'].max()   # newest filings first
    run_daily.run(r2, FakeNSE(), date(2026, 10, 10), 10, streams=(run_daily.ISSUES,))
    arch = run_daily.merge_into_archive(r2, run_daily.ISSUES, None, '')[0]
    assert (arch['xbrl_status'] == 'pending').sum() == 0


class _Master:
    """The two lookups add_identity uses: Electrosteel's current ISIN only (audit 22 Oct)."""
    recs = {'INE086A01029': {'display_name': 'Electrosteel Castings'}, 'INE467B01029': {'display_name': 'TCS'},
            'INE133A01011': {'display_name': 'Akzo Nobel India'}, 'INE133A01029': {'display_name': 'JSW Dulux'}}
    syms = {'ELECTCAST': 'INE086A01029', 'TCS': 'INE467B01029', 'JSWDULUX': 'INE133A01029'}

    def resolve(self, exchange, symbol=None, isin=None):
        return (self.syms[symbol], 'symbol') if symbol in self.syms else (None, 'unmatched')

    def record(self, isin):
        return self.recs.get(isin)


def test_a_retired_isin_filed_with_the_shareholding_gives_way_to_the_current_one():
    from collectors.nse_events.run_daily import add_identity
    df = pd.DataFrame({'symbol': ['ELECTCAST', 'TCS', 'NEWCO', 'JSWDULUX'],
                       'company': ['Electrosteel Castings Limited', 'TCS', 'New Co', 'JSW Dulux'],
                       'isin': ['INE086A01011', 'INE467B01029', 'INE999X01019', 'INE133A01011']})
    out = add_identity(df, _Master())
    # the symbol's current ISIN wins, even over a retired one the master still knows (JSW Dulux, Akzo's old ISIN);
    # a symbol not in today's list keeps its filed ISIN
    assert list(out['isin']) == ['INE086A01029', 'INE467B01029', 'INE999X01019', 'INE133A01029']
    assert list(out['isin_filed'].fillna('')) == ['INE086A01011', '', '', 'INE133A01011']
    assert out.loc[0, 'company_display'] == 'Electrosteel Castings' and not out['unmatched_security'].any()
