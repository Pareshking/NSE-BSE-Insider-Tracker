"""Results dates and the trading window (TODO 25), buyback price and route
(TODO 12). Parsers on real NSE payloads fetched 12 Oct 2026
(tests/fixtures/nse_events/: board_meetings_past.json from the
corporate-board-meetings API with Oct 2025 and Feb 2026 ranges;
tender_offers_*.json from liveTenderPast-issues / liveTenderActive-issues;
daily_buybacks.json from corporates-daily-buyback)."""
from __future__ import annotations

import io
import json
from datetime import date

import pandas as pd
from conftest import FIXTURES
from test_nse_events import FakeNSE, frame
from test_raw_store import OnceR2

from collectors.nse_events import parsers
from collectors.nse_events.client import NSEClient
from insiders_clean import buybacks, trading_window
from insiders_clean.calendar import Calendar
from insiders_clean.raw_store import RawStore

EV = FIXTURES / 'nse_events'


def load(name):
    return json.loads((EV / name).read_text(encoding='utf-8'))


def tenders():
    return parsers.parse_tender_offers(load('tender_offers_past.json')['data'], load('tender_offers_active.json'))


def cal():
    return Calendar([d.date() for d in pd.bdate_range('2025-06-01', '2026-10-31')])


# --- tender offers and daily buyback reports ---------------------------------------

def test_tender_offers_read_price_size_and_kind():
    t = tenders()
    assert t['event_id'].is_unique
    infy = t[t['symbol'] == 'INFY'].iloc[0]  # Infosys buyback, Nov 2025
    assert infy['offer_type'] == 'buyback' and infy['offer_price'] == 1800 and infy['shares_sought'] == 100_000_000
    assert infy['offer_open'] == date(2025, 11, 20) and infy['offer_close'] == date(2025, 11, 26)
    assert set(t['offer_type']) <= {'buyback', 'takeover', 'delisting', 'other'}
    # NSE writes the type several ways ('Buy back', 'BuyBack', 'Buyback'); one kind here
    assert t.loc[t['offer_type_raw'].isin(['Buy back', 'BuyBack', 'Buyback']), 'offer_type'].eq('buyback').all()
    active = t[t['status'] == 'active'].iloc[0]
    assert active['symbol'] == 'HITECHCORP' and active['offer_type'] == 'delisting' and active['offer_price'] == 252


def test_daily_buyback_reports_keep_the_text_not_a_guessed_number():
    d = parsers.parse_daily_buybacks(load('daily_buybacks.json')['data'])
    assert d['event_id'].is_unique and d['report_date'].notna().all()
    assert {'ADVENZYMES', 'MANINFRA'} <= set(d['symbol'])
    assert 'shares' not in ' '.join(d.columns)


def test_buybacks_attach_tender_price_to_the_corporate_action_and_keep_unknown_routes_empty():
    actions, _ = parsers.parse_corporate_actions(load('corporate_actions.json'))
    daily = parsers.parse_daily_buybacks(load('daily_buybacks.json')['data'])
    bb, rep = buybacks.build(tenders(), daily, actions)
    rolex = bb[bb['symbol'] == 'ROLEXRINGS'].iloc[0]  # record date 03 Jul 2026, tender 09-15 Jul at Rs 180
    assert rolex['route'] == 'tender offer' and rolex['offer_price'] == 180
    assert rolex['record_date'] == pd.Timestamp('2026-07-03') and rolex['offer_open'] == pd.Timestamp('2026-07-09')
    assert rolex['offer_value'] == 180 * 10_000_000
    team = bb[bb['symbol'] == 'TEAMLEASE'].iloc[0]  # a 'Buy Back' action with no NSE tender record
    assert pd.isna(team['route']) and pd.isna(team['offer_price'])
    om = bb[bb['symbol'] == 'ADVENZYMES'].iloc[0]
    assert om['route'] == 'open market' and pd.isna(om['offer_price']) and om['daily_reports'] >= 1
    assert (bb['symbol'] == 'ROLEXRINGS').sum() == 1  # the matched tender is not listed twice
    assert bb['buyback_id'].is_unique
    assert rep['actions_matched'] >= 2 and rep['no_route'] >= 1


# --- results dates and the trading window ------------------------------------------

def meetings():
    m, _ = parsers.parse_board_meetings(load('board_meetings_past.json'))
    return m


def test_results_dates_skip_postponed_meetings():
    rd = trading_window.results_dates(meetings())
    ador = rd[rd['symbol'] == 'ADOR']
    assert pd.Timestamp('2025-10-15') in set(ador['results_date'])
    # Vivimed's 13 Feb 2026 results meeting was postponed (NSE: 'Board meeting Rescheduled')
    assert pd.Timestamp('2026-02-13') not in set(rd.loc[rd['symbol'] == 'VIVIMEDLAB', 'results_date'])


def trade(sym, day, side='BUY', market=True):
    return {'nse_symbol': sym, 'trade_date_from': day, 'trade_date_to': day, 'side': side, 'is_market': market}


def test_buy_in_first_sessions_after_the_window_opens_is_marked():
    # ADOR results meeting Wed 15 Oct 2025: the window opens Fri 17 Oct (48 hours).
    t = pd.DataFrame([trade('ADOR', '2025-10-17'), trade('ADOR', '2025-10-23'), trade('ADOR', '2025-11-20'),
                      trade('ADOR', '2025-10-17', side='SELL'), trade('ADOR', '2025-10-16'),
                      trade('ADOR', '2025-10-20', market=False), trade('NOSUCH', '2025-10-20')])
    out, rep = trading_window.attach(t, meetings(), cal(), n=5)
    assert out.loc[0, 'sessions_since_window_open'] == 0 and out.loc[0, 'window_open_buy']
    assert out.loc[0, 'results_date'] == date(2025, 10, 15) and out.loc[0, 'window_open_date'] == date(2025, 10, 17)
    assert out.loc[1, 'sessions_since_window_open'] == 4 and out.loc[1, 'window_open_buy']  # 17, 20, 21, 22, 23 Oct
    assert out.loc[2, 'sessions_since_window_open'] > 5 and not out.loc[2, 'window_open_buy']
    assert not out.loc[3, 'window_open_buy']  # a sale is not marked
    assert out.loc[4, 'results_date'] != date(2025, 10, 15)  # inside the 48 hours: not this quarter's opening
    assert not out.loc[5, 'window_open_buy']  # not open market
    assert pd.isna(out.loc[6, 'results_date']) and not out.loc[6, 'window_open_buy']
    assert rep['window_open_buys'] == 2


def test_no_meetings_leaves_the_columns_empty():
    out, rep = trading_window.attach(pd.DataFrame([trade('ADOR', '2025-10-17')]), None, cal())
    assert out['results_date'].isna().all() and not out['window_open_buy'].any() and rep['window_open_buys'] == 0


# --- collection: meetings backfill and raw ---------------------------------------

class Session:
    """requests.Session stand-in that answers NSE URLs from the fixtures."""

    def __init__(self):
        self.headers, self.urls = {}, []

    def get(self, url, timeout=None):
        self.urls.append(url)
        body = (json.dumps(load('board_meetings_past.json')) if 'board-meetings' in url else '[]').encode()

        class R:
            status_code, content, headers = 200, body, {'Content-Type': 'application/json'}

            def json(self):
                return json.loads(body)
        return R()


def test_meetings_backfill_goes_month_by_month_and_keeps_the_raw_bytes(monkeypatch):
    import clean_writer

    from collectors.nse_events import run_daily

    class Resp:
        status_code = 200

        def __init__(self, path):
            self.content = path.read_bytes()
    monkeypatch.setattr(clean_writer.requests, 'get', lambda url, **kw: Resp(
        FIXTURES / ('nse_sme_sample.csv' if 'SME' in url else 'nse_equity_sample.csv')))
    r2, s = OnceR2(), Session()
    nse = NSEClient(session=s, sleep=lambda x: None)
    rep = run_daily.run(r2, nse, date(2026, 10, 12), 10, streams=('meetings',),
                        raw=RawStore(r2, bucket='b', collector='test'), backfill_from=date(2025, 7, 1))
    calls = [u for u in s.urls if 'board-meetings' in u]
    assert len(calls) == 18  # Jul 2025 .. Dec 2026 (today + 60 days), one month each
    assert 'from_date=01-07-2025&to_date=31-07-2025' in calls[0]
    blobs = [k for k in r2.objects if k.startswith('raw_v2/nse/meetings/blobs/')]
    assert len(blobs) == 1  # same bytes every call: one blob, one fetch record per call
    assert len([k for k in r2.objects if k.startswith('raw_v2/nse/meetings/fetches/')]) == 18
    m = frame(r2, 'clean/current/meetings.parquet')
    assert m['event_id'].is_unique and rep['meetings_backfill_from'] == '2025-07-01'


def test_nightly_writes_buybacks(monkeypatch):
    import clean_writer

    from collectors.nse_events import run_daily

    class Resp:
        status_code = 200

        def __init__(self, path):
            self.content = path.read_bytes()
    monkeypatch.setattr(clean_writer.requests, 'get', lambda url, **kw: Resp(
        FIXTURES / ('nse_sme_sample.csv' if 'SME' in url else 'nse_equity_sample.csv')))
    r2 = OnceR2()
    rep = run_daily.run(r2, FakeNSE(), date(2026, 10, 12), 10)
    bb = pd.read_parquet(io.BytesIO(r2.objects['clean/current/buybacks.parquet']))
    assert {'tender offer', 'open market'} <= set(bb['route'].dropna())
    assert 'isin' in bb and rep['buybacks']['rows'] == len(bb)


def test_a_quarter_above_its_own_year_to_date_is_flagged_not_fixed():
    """Repro India's Sep 2025 revision: Rs 107.8 Cr for the quarter, Rs 22.5 Cr for the six months. A loss
    larger in the quarter than the year (negative revenue) is no contradiction; nor is a quarter that is its year."""
    from insiders_clean import results
    df = pd.DataFrame({'quarter_revenue': [1.0778e9, -4.1e8, 5e8, 5e8, 9e8],
                       'ytd_revenue': [2.245e8, -1.5e8, 9e8, 5e8, None],
                       'ytd_start': ['2025-04-01', '2025-04-01', '2025-04-01', '2025-07-01', '2025-04-01'],
                       'period_end': ['2025-09-30', '2026-03-31', '2025-09-30', '2025-09-30', '2025-09-30']})
    assert results.ytd_disagrees(df).tolist() == [True, False, False, False, False]
