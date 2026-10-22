"""BSE history and events: client, parsers, backfill, events runner, the
two-feed insider link and the NSE link.

Fixtures in tests/fixtures/bse/ are real BSE answers of 12 Oct 2026, trimmed
(insider JSON rows without the filer's PAN, address and phone): the insider
CSV for 01-10 Oct 2026 and three JSON rows of the same Avenue Supermarts
filing; bulk deals of 09 Oct and block deals of 08 Oct 2026 in both the
nightly (BulkDeal_Beta) and history (BulkDealData_ng) forms; SAST for Nov 2025;
corporate actions with ex-dates 08-15 Oct 2025.
"""
from __future__ import annotations

import importlib
import io
import json
from datetime import date

import bse_history_backfill as bf
import pandas as pd
import pytest
import requests
from conftest import FIXTURES, canonical
from test_archive_and_writer import FakeR2, parquet

from collectors.bse import events, parsers
from collectors.bse.client import BSEClient, Blocked, Failed
from insiders_clean import archive, bse_events
from insiders_clean.insider import clean_insider

BSE = FIXTURES / 'bse'
RUN = '2026-10-12'


def js(name):
    return json.loads((BSE / name).read_text(encoding='utf-8'))


def csv_body():
    return (BSE / 'insider_20261001_20261010.csv').read_bytes()


@pytest.fixture()
def nightly(tmp_path, monkeypatch):
    """The nightly BSE parser and normaliser themselves (they create their
    artifacts/ folders on import, so they are imported in a scratch folder)."""
    monkeypatch.chdir(tmp_path)
    pytest.importorskip('selenium')
    cap = importlib.import_module('bse_raw_capture_v2')
    val = importlib.import_module('bse_validate')
    return cap, val


# --- parsers -----------------------------------------------------------------

def test_deal_history_maps_to_exactly_the_nightly_row(nightly):
    cap, val = nightly
    for beta, hist, cat in (('bulk_beta_20261009.json', 'bulk_history_20261009.json', 'bulk_deals'),
                            ('block_beta_20261008.json', 'block_history_20261008.json', 'block_deals')):
        # nightly: row list -> JSON file -> normalize, as bse_validate reads it
        lists = json.loads(json.dumps([cap.bulk_block_row(r) for r in js(beta)['Table']]))
        night = [val.normalize(cat, r) for r in lists]
        hist_rows = parsers.deal_rows(js(hist)['Table'])
        key = lambda rows: sorted(json.dumps(r, sort_keys=True) for r in rows)  # noqa: E731
        assert key(hist_rows) == key(night)
        ids = lambda rows: set(canonical('bse', cat, rows)['canonical_event_id'])  # noqa: E731
        assert ids(hist_rows) == ids(night)
    assert {r['side'] for r in parsers.deal_rows(js('bulk_history_20261009.json')['Table'])} == {'BUY', 'SELL'}


def test_insider_csv_rows_and_canonical_fields():
    rows = parsers.insider_rows(csv_body())
    assert len(rows) == 18
    r = next(x for x in rows if x['person'] == 'ALLAN NOTT')
    assert (r['security_code'], r['quantity'], r['transaction_value'], r['transaction_type']) == \
        ('540376', '4500', '15075000.00', 'ACQUISITION')
    assert (r['transaction_date'], r['intimation_date'], r['broadcast_date']) == ('07 Oct 2026', '07 Oct 2026', '09 Oct 2026')
    assert r['security_type_post'] == ''  # '-' is empty
    assert {x['transaction_type'] for x in rows} >= {'ACQUISITION', 'DISPOSAL'}
    df = canonical('bse', 'insider_trading', [dict(x, source=parsers.INSIDER_SOURCE) for x in rows])
    assert df['canonical_quantity'].gt(0).all()
    span = df[df['transaction_date'] != df['transaction_date_to']]
    assert len(span) and (span['canonical_transaction_date_to'] == span['transaction_date_to']).all()
    assert span['canonical_transaction_date_is_range'].all()
    assert (archive.partitions(df, 'insider_trading') == 'year=2026/quarter=4').all()


def test_insider_csv_without_its_columns_is_refused():
    with pytest.raises(ValueError):
        parsers.insider_rows(b'Security Code,Something else\n500001,x\n')


def test_sast_keeps_reg29_counts_the_rest_and_reads_ranges():
    df, extra = parsers.parse_sast(js('sast_202511.json'))
    assert extra['dropped_other_regulations'] == {'10(5)': 2, '10(6)': 2}
    assert set(df['regulation']) == {'Reg29(1)', 'Reg29(2)'} and df['event_id'].is_unique
    assert (df['exchange'] == 'BSE').all() and df['bse_code'].str.fullmatch(r'\d{6}').all()
    rng = df[df['trade_date_from'] != df['trade_date_to']]
    assert len(rng) and (pd.to_datetime(rng['trade_date_to']) > pd.to_datetime(rng['trade_date_from'])).all()
    assert not df['company'].str.endswith('-$').any()
    sale = df[df['action_type'] == 'Sale'].iloc[0]
    assert sale['shares_traded'] == -sale['shares_sold'] and pd.isna(sale['shares_acquired'])
    assert df['broadcast_ts'].str.match(r'\d{2} \w{3} 20\d{2}').all()


def test_actions_purposes_dividend_split_bonus():
    df, dropped = parsers.parse_actions(js('actions_20251008_20251015.json'))
    raw = js('actions_20251008_20251015.json')
    assert dropped + len(df) == len(raw) and dropped >= 3  # spin-offs, income distribution
    assert set(df['purpose']) <= {'buyback', 'bonus', 'split', 'rights', 'dividend'}
    bonus = df[df['subject'] == 'Bonus issue 1:2'].iloc[0]
    assert bonus['ratio'] == '1:2' and bonus['bse_code'] == '540829' and str(bonus['ex_date']) == '2025-10-09'
    split = df[df['purpose'] == 'split'].iloc[0]
    assert (split['face_value_from'], split['face_value_to']) == (5.0, 1.0)
    div = df[df['purpose'] == 'dividend']
    assert len(div) and div['dividend_per_share'].gt(0).all()
    assert df[df['purpose'] == 'rights']['rights_issue_price'].isna().all()  # BSE gives no price


# --- client --------------------------------------------------------------------

class Resp:
    def __init__(self, status=200, body=b'[]', ctype='application/json'):
        self.status_code, self.content, self.headers = status, body, {'Content-Type': ctype}


class FakeHTTP:
    def __init__(self, script=None, body=b'[]'):
        self.headers, self.calls, self.script, self.body = {}, [], script or {}, body

    def get(self, url, params=None, timeout=None):
        n = len(self.calls)
        self.calls.append((url, dict(params or {})))
        r = self.script.get(n, Resp(200, self.body))
        if isinstance(r, Exception):
            raise r
        return r


class FakeInPage:
    def __init__(self, status=200, body=b'[]'):
        self.urls, self.status, self.body = [], status, body

    def get(self, url):
        self.urls.append(url)
        return self.status, 'application/json', self.body

    def close(self):
        pass


class FakeRaw:
    def __init__(self):
        self.puts = []

    def put(self, source, dataset, body, **kw):
        self.puts.append((source, dataset, kw))


def client(http, **kw):
    return BSEClient(session=http, sleep=lambda s: None, **kw)


def test_endpoints_and_parameters():
    http = FakeHTTP(body=csv_body())
    raw = FakeRaw()
    c = client(http, raw=raw)
    assert c.insider_csv(date(2026, 10, 1), date(2026, 10, 10)).startswith(b'Security Code')
    http.body = b'{"Table": []}'
    c.deals('block', date(2026, 10, 1), date(2026, 10, 12))
    http.body = b'[]'
    c.sast(date(2025, 11, 1), date(2025, 11, 30))
    c.actions(date(2025, 10, 8), date(2025, 10, 15))
    (u0, p0), (u1, p1), (u2, p2), (u3, p3) = http.calls
    assert u0.endswith('Corp_Regulation_DownloadCSV_ng/w') and p0 == {
        'scripCode': '', 'Regulation': '', 'fromDT': '20261001', 'ToDate': '20261010', 'Isdefault': '2'}
    assert u1.endswith('BulkDealData_ng/w') and p1 == {'DealType': '2', 'sc_code': '', 'FDate': '01/10/2026', 'TDate': '12/10/2026'}
    assert u2.endswith('Corporatesast/w') and p2 == {'scripcode': '', 'ddlregul': 'ALL', 'fromdate': '20251101', 'todate': '20251130'}
    assert u3.endswith('DefaultData/w') and (p3['strSearch'], p3['Fdate'], p3['TDate']) == ('S', '20251008', '20251015')
    assert [d for _, d, _ in raw.puts] == ['insider_csv', 'block_deals_history', 'sast', 'corporate_actions']
    assert raw.puts[0][2]['covers'] == {'from': '2026-10-01', 'to': '2026-10-10', 'via': 'requests'}
    assert http.headers['Origin'] == 'https://www.bseindia.com' and http.headers['Referer'] == 'https://www.bseindia.com/'


def test_pacing_retries_and_give_up():
    waits = []
    http = FakeHTTP(script={0: requests.ConnectionError('reset'), 1: Resp(503)})
    c = BSEClient(session=http, sleep=waits.append)
    assert c.sast(date(2025, 11, 1), date(2025, 11, 2)) == []
    assert len(http.calls) == 3 and len(waits) == 2 and all(4 <= w <= 6 for w in waits)
    with pytest.raises(Failed):
        client(FakeHTTP(script={i: Resp(500) for i in range(9)})).sast(date(2025, 11, 1), date(2025, 11, 2))


@pytest.mark.parametrize('status', [401, 403, 429])
def test_refusal_stops_without_a_browser(status):
    http = FakeHTTP(script={0: Resp(status, b'Access Denied', 'text/html')})
    with pytest.raises(Blocked):
        client(http, allow_in_page=False).sast(date(2025, 11, 1), date(2025, 11, 2))
    assert len(http.calls) == 1


def test_refusal_moves_to_the_in_page_fetch_for_the_rest_of_the_run():
    http = FakeHTTP(script={0: Resp(403, b'Access Denied', 'text/html')})
    page, raw = FakeInPage(body=b'[{"scrip_code": "500209"}]'), FakeRaw()
    c = client(http, in_page=None, raw=raw)
    c.in_page = page  # what InPage() would open
    assert c.sast(date(2025, 11, 1), date(2025, 11, 2)) == [{'scrip_code': '500209'}]
    c.sast(date(2025, 11, 3), date(2025, 11, 4))
    assert len(http.calls) == 1 and len(page.urls) == 2 and c.via == 'in_page_xhr'
    assert 'Corporatesast/w?scripcode=&ddlregul=ALL&fromdate=20251101' in page.urls[0]
    assert raw.puts[0][2]['covers']['via'] == 'in_page_xhr'
    page.status = 429
    with pytest.raises(Blocked):
        c.sast(date(2025, 11, 5), date(2025, 11, 6))


def test_not_data_stops():
    with pytest.raises(Blocked):
        client(FakeHTTP(body=b'<html>error</html>')).insider_csv(date(2026, 10, 1), date(2026, 10, 2))
    with pytest.raises(Blocked):
        client(FakeHTTP(body=b'<html>error</html>')).sast(date(2026, 10, 1), date(2026, 10, 2))


# --- SAST tiling ------------------------------------------------------------------

class FakeSast:
    """Answers [] for any window that holds 03 Nov whole or starts on 08 Nov
    (as BSE does for some windows), else the rows inside the window."""

    def __init__(self, rows):
        self.rows, self.calls, self.via = rows, [], 'requests'

    def sast(self, a, b):
        self.calls.append((a, b))
        if a == date(2025, 11, 8) or (a < date(2025, 11, 3) < b):
            return []
        day = lambda r: pd.to_datetime(r['Acquisition_date'][:10], format='%d/%m/%Y').date()  # noqa: E731
        return [r for r in self.rows if a <= day(r) <= b]


def test_sast_window_unites_three_tilings_and_splits_empty_pieces():
    rows = js('sast_202511.json')
    bse, stats = FakeSast(rows), {}
    got = events.sast_window(bse, date(2025, 11, 1), date(2025, 11, 30), stats)
    want = {parsers.sast_event_id(r) for r in rows}
    assert {parsers.sast_event_id(r) for r in got} == want
    assert stats['split_on_empty'] >= 1 and stats['calls'] == len(bse.calls)
    assert all(date.fromisoformat(d).weekday() < 5 for d in stats['weekdays_without_rows'])


# --- NSE link ----------------------------------------------------------------------

def test_link_to_nse_and_pages_show_each_once(master):
    df, _ = parsers.parse_sast(js('sast_202511.json'))
    df = bse_events.add_identity(df, master)
    infy = df[df['bse_code'] == '506590']  # PCBL, on both exchanges
    assert len(infy) and (infy['isin'] == 'INE602A01031').all() and (infy['symbol'] == 'PCBL').all()
    one = infy.iloc[0]
    nse = pd.DataFrame([{'event_id': 'nse1', 'isin': one['isin'], 'symbol': 'PCBL', 'action_type': one['action_type'],
                         'trade_date_to': one['trade_date_to'], 'shares_acquired': one['shares_acquired'],
                         'shares_sold': (one['shares_sold'] or 0) + 1}])
    linked = bse_events.link_to_nse(df, nse, 'sast')
    assert linked.loc[one.name, 'on_nse'] and linked.loc[one.name, 'nse_event_id'] == 'nse1'
    assert linked['on_nse'].sum() == 1 and set(linked['listed_on']) == {'bse', 'bse,nse'}
    shown = bse_events.with_bse(nse, linked)
    assert len(shown) == len(linked) and (shown['listed_on'] == 'nse').sum() == 1
    assert bse_events.with_bse(nse, pd.DataFrame()).equals(nse.assign(listed_on='nse'))



def test_with_bse_no_dtype_warning_and_keeps_every_column():
    import warnings
    # 'shares' has numbers on NSE and is all empty (object) on BSE: the case pandas warns about
    nse = pd.DataFrame({'event_id': ['n1'], 'isin': ['INE1'], 'shares': [1.5], 'remarks': [None]})
    bse = pd.DataFrame({'event_id': ['b1'], 'isin': ['INE2'], 'shares': [None], 'remarks': [None],
                        'bse_code': [None], 'on_nse': [False], 'listed_on': ['bse']}).astype({'shares': object})
    with warnings.catch_warnings():
        warnings.simplefilter('error', FutureWarning)
        shown = bse_events.with_bse(nse, bse)
    assert list(shown.columns) == ['event_id', 'isin', 'shares', 'remarks', 'listed_on', 'bse_code', 'on_nse']
    assert shown['shares'].dtype == 'float64' and shown['shares'].iloc[0] == 1.5 and pd.isna(shown['shares'].iloc[1])
    assert list(shown['event_id']) == ['n1', 'b1'] and list(shown['listed_on']) == ['nse', 'bse']
    assert shown['remarks'].isna().all() and shown['bse_code'].isna().all()

def test_actions_link_on_isin_purpose_and_ex_date(master):
    df, _ = parsers.parse_actions(js('actions_20251008_20251015.json'))
    df = bse_events.add_identity(df, master)
    hit = df[df['isin'].notna()].iloc[0]
    nse = pd.DataFrame([{'event_id': 'n1', 'isin': hit['isin'], 'purpose': hit['purpose'], 'ex_date': hit['ex_date']},
                        {'event_id': 'n2', 'isin': hit['isin'], 'purpose': 'bonus' if hit['purpose'] != 'bonus' else 'split',
                         'ex_date': hit['ex_date']}])
    linked = bse_events.link_to_nse(df, nse, 'actions')
    assert linked['on_nse'].sum() == 1 and linked.loc[hit.name, 'nse_event_id'] == 'n1'


# --- the two BSE insider feeds in the clean step ---------------------------------

def test_one_filing_in_both_bse_feeds_is_one_row(nightly, master, calendar, report):
    cap, val = nightly
    night_rows = [val.normalize('insider_trading', json.loads(json.dumps(cap.insider_row(r))))
                  for r in js('insider_json_20261009.json')['Table']]
    csv_rows = [r for r in parsers.insider_rows(csv_body()) if r['security_code'] == '540376'
                and r['person'] in {x['person'] for x in night_rows}]
    assert len(night_rows) == len(csv_rows) == 3
    raw = pd.concat([canonical('bse', 'insider_trading', night_rows),
                     canonical('bse', 'insider_trading', csv_rows).assign(source=parsers.INSIDER_SOURCE)],
                    ignore_index=True)
    out = clean_insider(raw, master, calendar, report, RUN)
    assert len(out) == 3 and out['intimation_date'].notna().all()  # the CSV's rows are kept
    t = report.data['tables']['insider_trades']
    assert t['removed']['bse_same_filing_two_feeds']['count'] == 3
    assert 'corrected_refiling' not in t['removed'] and 'repeat_filing' not in t['removed']
    assert t['bse_rows_by_feed'] == {'csv': 3, 'nightly_json': 3}


# --- backfill runner -----------------------------------------------------------------

class FakeBSE:
    def __init__(self, deals=None, csv=None, script=None):
        self.deal_rows, self.csv, self.script, self.calls, self.via = deals or [], csv, script or {}, [], 'requests'

    def _step(self):
        n = len(self.calls) - 1
        if n in self.script:
            raise self.script[n]

    def deals(self, kind, a, b):
        self.calls.append((kind, a, b))
        self._step()
        return self.deal_rows

    def insider_csv(self, a, b):
        self.calls.append(('insider', a, b))
        self._step()
        return self.csv

    def close(self):
        pass


def test_deals_backfill_skips_rows_the_nightly_stored(nightly):
    cap, val = nightly
    r2 = FakeR2()
    prefix = 'archive/canonical/bse/bulk_deals/'
    night = [val.normalize('bulk_deals', r) for r in json.loads(json.dumps(
        [cap.bulk_block_row(r) for r in js('bulk_beta_20261009.json')['Table'][:3]]))]
    parts, _ = archive.merge_partitioned(lambda p: None, canonical('bse', 'bulk_deals', night), '2026-10-09', 'bulk_deals')
    for part, f in parts.items():
        r2.objects[f'{prefix}{part}.parquet'] = parquet(f)
    r2.objects[prefix + '_state.json'] = json.dumps({'last_merged': '2026-10-09', 'records': 3}).encode()
    bse = FakeBSE(deals=js('bulk_history_20261009.json')['Table'])
    rep = bf.run_dataset('bulk', date(2026, 10, 9), date(2026, 10, 9), bse, bf.R2Sink(r2, 'bulk', RUN), RUN,
                         log=lambda *_: None)
    assert rep['rows_fetched'] == 6 and rep['already_in_archive'] == 3 and rep['rows_added'] == 3
    arch = pd.read_parquet(io.BytesIO(r2.objects[f'{prefix}year=2026/quarter=4.parquet']))
    assert len(arch) == 6 and arch['canonical_event_id'].is_unique
    assert (arch['source'] == parsers.DEALS_SOURCE).sum() == 3  # the nightly's rows untouched
    assert archive.from_history(arch).sum() == 3
    state = json.loads(r2.objects[prefix + '_state.json'])
    assert state['last_merged'] == '2026-10-09' and state['records'] == 6
    assert list(json.loads(r2.objects['archive/_backfill/bse_bulk.json'])['chunks']) == ['2026-10-09..2026-10-09']
    assert json.loads(r2.objects[f'clean/reports/backfill/{RUN}_bse_bulk.json'])['already_in_archive'] == 3


def test_insider_backfill_chunks_resume_recent_and_stop():
    r2 = FakeR2()
    bse = FakeBSE(csv=csv_body())
    rep = bf.run_dataset('insider', date(2026, 10, 1), date(2026, 10, 20), bse, bf.R2Sink(r2, 'insider', RUN), RUN,
                         log=lambda *_: None)
    assert [(a, b) for _, a, b in bse.calls] == [(date(2026, 10, 1), date(2026, 10, 10)),
                                                 (date(2026, 10, 11), date(2026, 10, 20))]
    assert rep['rows_added'] == 18  # the same sample twice: stored once
    bse2 = FakeBSE(csv=csv_body())
    rep = bf.run_dataset('insider', date(2026, 10, 1), date(2026, 10, 30), bse2, bf.R2Sink(r2, 'insider', RUN), RUN,
                         log=lambda *_: None)
    assert rep['chunks_skipped_done'] == 2 and len(bse2.calls) == 1
    recent = bf.R2Sink(r2, 'insider', RUN, recent=True)
    assert recent.done() == {}
    before = r2.objects['archive/_backfill/bse_insider.json']
    bf.run_dataset('insider', date(2026, 10, 1), date(2026, 10, 10), FakeBSE(csv=csv_body()), recent, RUN, log=lambda *_: None)
    assert r2.objects['archive/_backfill/bse_insider.json'] == before  # recent marks nothing done
    bse3 = FakeBSE(csv=csv_body(), script={1: Blocked('HTTP 403')})
    rep = bf.run_dataset('insider', date(2026, 11, 1), date(2026, 11, 30), bse3, bf.R2Sink(r2, 'insider', RUN), RUN,
                         log=lambda *_: None)
    assert rep['chunks_done'] == 1 and rep['stopped_at']['chunk'] == '2026-11-11..2026-11-20' and len(bse3.calls) == 2


def test_dry_run_writes_nothing():
    r2 = FakeR2()
    reports, code = bf.main(['--dataset', 'insider', '--from', '2026-10-01', '--to', '2026-10-10', '--dry-run'],
                            client=r2, bse=FakeBSE(csv=csv_body()))
    assert code == 0 and reports[0]['rows_fetched'] == 18 and r2.objects == {}


# --- events runner -----------------------------------------------------------------

class EventsBSE(FakeSast):
    def __init__(self, rows, actions):
        super().__init__(rows)
        self.action_rows = actions

    def actions(self, a, b):
        self.calls.append((a, b))
        return self.action_rows


def test_events_history_archive_clean_and_report(master):
    r2 = FakeR2()
    sast = js('sast_202511.json')
    infy = parsers.parse_sast(sast)[0].query("bse_code == '506590'").iloc[0]
    nse = pd.DataFrame([{'event_id': 'nse1', 'isin': 'INE602A01031', 'symbol': 'PCBL', 'action_type': infy['action_type'],
                         'trade_date_to': infy['trade_date_to'], 'shares_acquired': infy['shares_acquired'],
                         'shares_sold': infy['shares_sold']}])
    r2.objects['clean/current/sast.parquet'] = parquet(nse.astype({'trade_date_to': 'datetime64[ns]'}))
    bse = EventsBSE(sast, js('actions_20251008_20251015.json'))
    rep = events.run(events.Store(r2), bse, date(2026, 10, 12), ('sast', 'actions'), start=date(2025, 11, 1), end=date(2025, 12, 31),
                     master=master, log=lambda *_: None)
    s = rep['streams']['sast']
    assert s['chunks_done'] == 2 and s['dropped_other_regulations'] == {'10(5)': 2, '10(6)': 2}
    assert s['clean']['on_nse'] >= 1 and s['clean']['bse_only'] == s['clean']['rows'] - s['clean']['on_nse']
    assert 'archive/bse_events/sast/year=2025.parquet' in r2.objects
    clean = pd.read_parquet(io.BytesIO(r2.objects['clean/current/bse_sast.parquet']))
    assert clean['event_id'].is_unique and clean['on_nse'].sum() == s['clean']['on_nse']
    assert set(json.loads(r2.objects['archive/_backfill/bse_sast.json'])['chunks']) == {
        '2025-11-01..2025-11-30', '2025-12-01..2025-12-31'}
    assert json.loads(r2.objects['clean/reports/bse_events/2026-10-12.json'])['mode'] == 'history'
    assert rep['streams']['actions']['clean']['rows'] > 0 and 'clean/current/bse_actions.parquet' in r2.objects
    # a rerun resumes: nothing fetched again, nothing added twice
    bse2 = EventsBSE(sast, js('actions_20251008_20251015.json'))
    rep2 = events.run(events.Store(r2), bse2, date(2026, 10, 12), ('sast', 'actions'), start=date(2025, 11, 1), end=date(2025, 12, 31),
                      master=master, log=lambda *_: None)
    assert bse2.calls == [] and rep2['streams']['sast']['chunks_skipped_done'] == 2


def test_events_dry_run_counts_only():
    bse = EventsBSE(js('sast_202511.json'), js('actions_20251008_20251015.json'))
    rep = events.run(None, bse, date(2025, 11, 30), ('sast', 'actions'), days=29, log=lambda *_: None)
    assert rep['dry_run'] and rep['streams']['sast']['fetched'] > 0 and rep['streams']['actions']['fetched'] > 0


def test_tilings():
    assert events.pieces(date(2025, 11, 1), date(2025, 11, 30), 7, 3)[:2] == [
        (date(2025, 11, 1), date(2025, 11, 3)), (date(2025, 11, 4), date(2025, 11, 10))]
    assert events.months(date(2025, 10, 8), date(2025, 12, 5))[0] == (date(2025, 10, 8), date(2025, 10, 31))

