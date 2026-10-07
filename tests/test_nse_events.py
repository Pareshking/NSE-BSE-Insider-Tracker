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

class FakeNSE:
    def __init__(self, block_xbrl=False):
        self.calls = 0
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

    def xbrl(self, url):
        self.calls += 1
        if self.block_xbrl and self.calls > 6:
            raise Blocked('HTTP 403')
        return self.xml


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
        assert f'clean/current/{stream}.parquet' in r2.objects, stream
        assert any(k.startswith(f'archive/nse_events/{stream}/year=') for k in r2.objects), stream
    sh = frame(r2, 'clean/current/shareholding.parquet')
    assert set(sh['xbrl_status']) == {'ok'} and round(float(sh['promoter_pledge_pct'].iloc[0]), 2) == 5.38
    assert rep['xbrl_fetched'] == 5
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
