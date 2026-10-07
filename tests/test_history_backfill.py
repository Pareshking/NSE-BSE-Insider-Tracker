"""Historical backfill: NSE history fields -> nightly fields, chunk planning,
and the runner against a fake NSE and an in-memory R2.

Fixtures in tests/fixtures/history/ are real responses fetched 07 Oct 2026:
corporates-pit for 01-07 Mar 2016 and 01-07 Mar 2024 (first rows), and the
bulk / block deals CSVs for Mar 2024.
"""
from __future__ import annotations

import io
import json
from datetime import date

import nse_history_backfill as bf
import pandas as pd
import pytest
import requests
from conftest import FIXTURES, canonical
from test_archive_and_writer import FakeR2, parquet

from insiders_clean import archive
from insiders_clean.history import deal_rows, pit_row

HIST = FIXTURES / 'history'
RUN = '2026-10-08'


def pit(name):
    return json.loads((HIST / name).read_text(encoding='utf-8'))


def csv_bytes(name):
    return (HIST / name).read_bytes()


# --- mapping on the real samples ---------------------------------------------

def test_pit_mapping_nil_dash_and_sides():
    rows = pit('nse_pit_2016.json') + pit('nse_pit_2024.json')
    mapped = [pit_row(h) for h in rows]
    nil = next(i for i, h in enumerate(rows) if h['befAcqSharesNo'] == 'Nil')
    assert mapped[nil]['beforeSharesNo'] == '0'
    assert mapped[0]['history_remarks'] == '' and mapped[0]['history_derivativeType'] == ''  # '-' -> empty
    for h, m in zip(rows, mapped):
        if h['tdpTransactionType'] == 'Buy':
            assert m['transactionType'] == 'Acquisition'
            assert m['buyQuantity'] == h['secAcq'] and m['sellquantity'] == '' and m['sellValue'] == ''
        elif h['tdpTransactionType'] == 'Sell':
            assert m['transactionType'] == 'Disposal'
            assert m['sellquantity'] == h['secAcq'] and m['buyQuantity'] == '' and m['buyValue'] == ''
        assert m['broadcastDt'] == h['date'] and m['date'] == (h['intimDt'] or h['date'])
        assert m['source'] == 'nse_corporates_pit_history'


def test_pit_rows_go_through_the_writers_canonicalize():
    rows = [pit_row(h) for h in pit('nse_pit_2024.json')]
    df = canonical('nse', 'insider_trading', rows)
    sell = df[df['history_tdpTransactionType'] == 'Sell'].iloc[0]
    assert sell['canonical_transaction_type'] == 'DISPOSAL'
    assert sell['canonical_quantity'] > 0  # the unused buy side was emptied, not '0'
    assert df['canonical_broadcast_date'].str.match(r'\d{2}-\w{3}-2024').all()
    assert (archive.partitions(df, 'insider_trading') == 'year=2024/quarter=1').all()


@pytest.mark.parametrize('name,category', [('nse_bulk_2024.csv', 'bulk_deals'),
                                           ('nse_block_2024.csv', 'block_deals')])
def test_deal_csv_bom_trailing_spaces_and_indian_grouping(name, category):
    rows = deal_rows(csv_bytes(name))
    assert rows and set(rows[0]) >= {'BD_DT_DATE', 'BD_SYMBOL', 'BD_CLIENT_NAME', 'BD_QTY_TRD', 'BD_TP_WATP'}
    assert not any(k.startswith('﻿') for k in rows[0])
    df = canonical('nse', category, rows)
    first = df.iloc[0]
    assert first['canonical_quantity'] == float(rows[0]['BD_QTY_TRD'].replace(',', ''))
    assert df['canonical_quantity'].gt(0).all() and df['canonical_side'].isin(['BUY', 'SELL']).all()
    assert (archive.partitions(df, category) == 'year=2024/quarter=1').all()


def test_bulk_lakh_grouping_and_dash_remarks():
    rows = deal_rows(csv_bytes('nse_bulk_2024.csv'))
    aries = rows[0]  # "04-MAR-2024","ARIES",...,"SELL","1,04,593","329.88","-"
    assert aries['BD_SYMBOL'] == 'ARIES' and aries['BD_REMARKS'] == ''
    assert canonical('nse', 'bulk_deals', [aries])['canonical_quantity'].iloc[0] == 104593


def test_impossible_dates_are_counted_not_dropped():
    rows = [pit_row(h) for h in pit('nse_pit_2024.json')[:3]]
    rows[1]['acqtoDt'] = '01-Mar-3034'
    assert bf.impossible_dates('insider', rows, RUN) == 1
    frame, _ = bf.canonical_frame('insider', rows)
    assert len(frame) == 3


# --- chunk planning ------------------------------------------------------------

def test_insider_quarters_2015_to_2026():
    chunks = bf.plan_chunks(date(2015, 11, 19), date(2026, 5, 2), 'quarter')
    assert chunks[0] == (date(2015, 11, 19), date(2015, 12, 31))
    assert chunks[1] == (date(2016, 1, 1), date(2016, 3, 31))
    assert chunks[-1] == (date(2026, 4, 1), date(2026, 5, 2))
    assert len(chunks) == 1 + 4 * 10 + 2
    assert all((b - a).days < 92 for a, b in chunks)
    assert all(chunks[i][1].toordinal() + 1 == chunks[i + 1][0].toordinal() for i in range(len(chunks) - 1))


def test_deal_years():
    chunks = bf.plan_chunks(date(2005, 11, 1), date(2008, 6, 30), 'year')
    assert chunks == [(date(2005, 11, 1), date(2005, 12, 31)), (date(2006, 1, 1), date(2006, 12, 31)),
                      (date(2007, 1, 1), date(2007, 12, 31)), (date(2008, 1, 1), date(2008, 6, 30))]


def test_insider_to_is_clipped_at_the_system_change():
    start, end, note = bf.resolve_range('insider', None, date(2026, 9, 30), None)
    assert (start, end) == (date(2026, 1, 1), date(2026, 5, 2)) and 'clipped' in note


# --- fake NSE ------------------------------------------------------------------

class Resp:
    def __init__(self, status=200, body=b''):
        self.status_code, self.content = status, body


class FakeNSE:
    """Answers by URL; `script` overrides by call number (0 = warm-up)."""

    def __init__(self, pit_body=None, csv_body=None, script=None):
        self.headers = {}
        self.calls = []
        self.pit_body = pit_body if pit_body is not None else json.dumps({'data': pit('nse_pit_2024.json')}).encode()
        self.csv_body = csv_body if csv_body is not None else csv_bytes('nse_bulk_2024.csv')
        self.script = script or {}

    def get(self, url, params=None, headers=None, timeout=None):
        n = len(self.calls)
        self.calls.append((url, dict(params or {})))
        if n in self.script:
            r = self.script[n]
            if isinstance(r, Exception):
                raise r
            return r
        if url == bf.HOME:
            return Resp(200, b'<html>home</html>')
        if url == bf.PIT_URL:
            return Resp(200, self.pit_body)
        return Resp(200, self.csv_body)


def client(nse):
    return bf.NseHistory(session=nse, sleep=lambda s: None)


def run(dataset, start, end, nse, sink):
    return bf.run_dataset(dataset, start, end, client(nse), sink, RUN, log=lambda *_: None)


def test_session_warms_up_once_and_paces_between_calls():
    waits = []
    nse = FakeNSE()
    http = bf.NseHistory(session=nse, sleep=waits.append)
    http.insider(date(2024, 1, 1), date(2024, 3, 31))
    http.insider(date(2024, 4, 1), date(2024, 6, 30))
    assert [u for u, _ in nse.calls] == [bf.HOME, bf.PIT_URL, bf.PIT_URL]
    assert nse.calls[1][1] == {'index': 'equities', 'from_date': '01-01-2024', 'to_date': '31-03-2024'}
    assert len(waits) == 2 and all(4 <= w <= 6 for w in waits)
    assert nse.headers['User-Agent'] == bf.UA


def test_deals_call_uses_csv_and_option():
    nse = FakeNSE()
    client(nse).deals('block_deals', date(2024, 1, 1), date(2024, 12, 31))
    assert nse.calls[1][1] == {'optionType': 'block_deals', 'from': '01-01-2024', 'to': '31-12-2024',
                               'csv': 'true'}


def test_retries_network_errors_and_5xx_then_succeeds():
    nse = FakeNSE(script={1: requests.ConnectionError('reset'), 2: Resp(503), 3: Resp(500)})
    rows = client(nse).insider(date(2024, 1, 1), date(2024, 3, 31))
    assert len(rows) == 60 and len(nse.calls) == 5


def test_gives_up_after_three_retries():
    nse = FakeNSE(script={i: Resp(500) for i in range(1, 10)})
    with pytest.raises(bf.Failed):
        client(nse).insider(date(2024, 1, 1), date(2024, 3, 31))
    assert len(nse.calls) == 1 + 1 + bf.RETRIES


@pytest.mark.parametrize('resp', [Resp(403), Resp(401), Resp(429), Resp(200, b'<html>Access Denied</html>')])
def test_refusal_or_non_json_stops(resp):
    with pytest.raises(bf.Stopped):
        client(FakeNSE(script={1: resp})).insider(date(2024, 1, 1), date(2024, 3, 31))


def test_non_csv_deals_body_stops():
    with pytest.raises(bf.Stopped):
        client(FakeNSE(csv_body=b'{"data": []}')).deals('bulk_deals', date(2024, 1, 1), date(2024, 12, 31))


# --- the runner against FakeR2 ---------------------------------------------------

PREFIX = 'archive/canonical/nse/insider_trading/'
STATE = PREFIX + '_state.json'


def nightly_state(r2, last='2026-10-07', records=0):
    r2.objects[STATE] = json.dumps({'last_merged': last, 'records': records,
                                    'partitions_written_today': []}).encode()


def archived(r2, prefix=PREFIX):
    keys = sorted(k for k in r2.objects if k.startswith(prefix) and k.endswith('.parquet'))
    return pd.concat([pd.read_parquet(io.BytesIO(r2.objects[k])) for k in keys], ignore_index=True)


def test_backfill_merges_into_archive_and_keeps_last_merged():
    r2 = FakeR2()
    nightly_state(r2, records=7)
    rep = run('insider', date(2024, 1, 1), date(2024, 6, 30), FakeNSE(), bf.R2Sink(r2, 'insider', RUN))
    assert rep['chunks_done'] == 2 and rep['rows_fetched'] == 120
    assert rep['rows_added'] == 60  # same sample both quarters: stored once
    arch = archived(r2)
    assert len(arch) == 60 and arch['canonical_event_id'].is_unique
    assert set(arch['first_seen']) == {RUN} and set(arch['last_seen']) == {RUN}
    assert PREFIX + 'year=2024/quarter=1.parquet' in r2.objects
    state = json.loads(r2.objects[STATE])
    assert state['last_merged'] == '2026-10-07'
    assert state['records'] == 67
    assert state['backfill']['insider'] == {'chunks_done': 2, 'rows': 120, 'rows_added': 60, 'updated': RUN}
    progress = json.loads(r2.objects['archive/_backfill/nse_insider.json'])
    assert set(progress['chunks']) == {'2024-01-01..2024-03-31', '2024-04-01..2024-06-30'}
    report = json.loads(r2.objects[f'clean/reports/backfill/{RUN}_insider.json'])
    assert report['stopped_at'] is None and report['rows_added'] == 60
    assert not archive.possibly_withdrawn(arch, '2026-10-20').any()  # never in the nightly window


def test_no_state_file_is_created_where_the_nightly_has_none():
    r2 = FakeR2()
    run('insider', date(2024, 1, 1), date(2024, 3, 31), FakeNSE(), bf.R2Sink(r2, 'insider', RUN))
    assert STATE not in r2.objects and PREFIX + 'year=2024/quarter=1.parquet' in r2.objects


def test_resume_skips_done_chunks():
    r2 = FakeR2()
    run('insider', date(2024, 1, 1), date(2024, 3, 31), FakeNSE(), bf.R2Sink(r2, 'insider', RUN))
    nse = FakeNSE()
    rep = run('insider', date(2024, 1, 1), date(2024, 9, 30), nse, bf.R2Sink(r2, 'insider', RUN))
    assert rep['chunks_skipped_done'] == 1 and rep['chunks_done'] == 2
    assert [p.get('from_date') for _, p in nse.calls if p] == ['01-04-2024', '01-07-2024']


def test_stop_on_403_keeps_completed_chunks_and_records_where():
    r2 = FakeR2()
    nightly_state(r2)
    nse = FakeNSE(script={2: Resp(403)})  # call 0 warm-up, 1 Q1, 2 Q2 -> 403
    rep = run('insider', date(2024, 1, 1), date(2024, 12, 31), nse, bf.R2Sink(r2, 'insider', RUN))
    assert rep['chunks_done'] == 1
    assert rep['stopped_at']['chunk'] == '2024-04-01..2024-06-30' and '403' in rep['stopped_at']['reason']
    assert len(nse.calls) == 3  # nothing after the refusal
    progress = json.loads(r2.objects['archive/_backfill/nse_insider.json'])
    assert list(progress['chunks']) == ['2024-01-01..2024-03-31']
    report = json.loads(r2.objects[f'clean/reports/backfill/{RUN}_insider.json'])
    assert report['stopped_at']['chunk'] == '2024-04-01..2024-06-30'
    assert json.loads(r2.objects[STATE])['last_merged'] == '2026-10-07'


def test_failed_chunk_is_reported_and_left_for_next_run():
    r2 = FakeR2()
    nse = FakeNSE(script={i: Resp(502) for i in range(1, 1 + 1 + bf.RETRIES)})
    rep = run('insider', date(2024, 1, 1), date(2024, 6, 30), nse, bf.R2Sink(r2, 'insider', RUN))
    assert [e['chunk'] for e in rep['errors']] == ['2024-01-01..2024-03-31'] and rep['chunks_done'] == 1
    progress = json.loads(r2.objects['archive/_backfill/nse_insider.json'])
    assert list(progress['chunks']) == ['2024-04-01..2024-06-30']


def test_dry_run_writes_nothing(monkeypatch, capsys):
    r2 = FakeR2()
    nightly_state(r2)
    before = dict(r2.objects)
    reports, code = bf.main(['--dataset', 'insider', '--from', '2024-01-01', '--to', '2024-03-31', '--dry-run'],
                            client=r2, http=client(FakeNSE()))
    assert code == 0 and reports[0]['rows_fetched'] == 60 and reports[0]['rows_added'] == 0
    assert r2.objects == before
    assert '2024-01-01..2024-03-31: fetched 60' in capsys.readouterr().out


def test_local_out_then_upload_from(tmp_path):
    r2 = FakeR2()
    nightly_state(r2)
    reports, code = bf.main(['--dataset', 'insider', '--from', '2024-01-01', '--to', '2024-06-30',
                             '--local-out', str(tmp_path)], client=r2, http=client(FakeNSE()))
    assert code == 0 and not any(k.startswith('archive/canonical') and k.endswith('.parquet') for k in r2.objects)
    assert (tmp_path / 'nse_insider' / '2024-01-01..2024-03-31.parquet').exists()
    reports, code = bf.main(['--dataset', 'insider', '--upload-from', str(tmp_path)], client=r2)
    assert code == 0 and reports[0]['chunks_done'] == 2 and reports[0]['rows_added'] == 60
    assert len(archived(r2)) == 60
    assert json.loads(r2.objects[STATE])['last_merged'] == '2026-10-07'
    reports, _ = bf.main(['--dataset', 'insider', '--upload-from', str(tmp_path)], client=r2)
    assert reports[0]['chunks_skipped_done'] == 2 and reports[0]['chunks_done'] == 0


def test_deals_to_defaults_to_the_day_before_the_earliest_nightly_record():
    r2 = FakeR2()
    nightly = [{'BD_DT_DATE': '10-Jul-2026', 'BD_SYMBOL': 'ABC', 'BD_SCRIP_NAME': 'Abc Ltd',
                'BD_CLIENT_NAME': 'X FUND', 'BD_BUY_SELL': 'BUY', 'BD_QTY_TRD': '100', 'BD_TP_WATP': '10',
                'source': 'NSE'},
               {'BD_DT_DATE': '02-Oct-2026', 'BD_SYMBOL': 'ABC', 'BD_SCRIP_NAME': 'Abc Ltd',
                'BD_CLIENT_NAME': 'Y FUND', 'BD_BUY_SELL': 'SELL', 'BD_QTY_TRD': '100', 'BD_TP_WATP': '10',
                'source': 'NSE'}]
    frame = canonical('nse', 'bulk_deals', nightly)
    parts, _ = archive.merge_partitioned(lambda p: None, frame, '2026-10-07', 'bulk_deals')
    for part, f in parts.items():
        r2.objects[f'archive/canonical/nse/bulk_deals/{part}.parquet'] = parquet(f)
    start, end, note = bf.resolve_range('bulk', None, None, r2)
    assert (start, end) == (date(2026, 1, 1), date(2026, 7, 9)) and '2026-07-10' in note

    # after a partial backfill, history rows don't move the default
    nse = FakeNSE(csv_body=csv_bytes('nse_bulk_2024.csv'))
    run('bulk', date(2024, 1, 1), date(2024, 12, 31), nse, bf.R2Sink(r2, 'bulk', RUN))
    assert bf.resolve_range('bulk', None, None, r2)[1] == date(2026, 7, 9)


def test_deals_without_archive_need_explicit_to():
    with pytest.raises(SystemExit):
        bf.resolve_range('block', None, None, FakeR2())
    with pytest.raises(SystemExit):
        bf.resolve_range('block', None, None, None)


def test_deals_round_trips_dropped_as_the_nightly_writer_does():
    rows = deal_rows(csv_bytes('nse_bulk_2024.csv'))
    frame, dropped = bf.canonical_frame('bulk', rows)
    assert len(frame) + dropped == len(rows)


def test_nightly_clean_keeps_backfill_entry_and_last_merged(monkeypatch, real_nse_rows):
    """clean_writer after a backfill: the backfill entry survives, and a
    night with nothing written does not take last_merged from the
    backfill's last_seen."""
    import clean_writer
    r2 = FakeR2()
    r2.objects['canonical/nse/insider_trading/2026-10-06/data.parquet'] = parquet(
        canonical('nse', 'insider_trading', real_nse_rows[:20]).drop(columns=['exchange', 'category']))
    monkeypatch.setattr(clean_writer, 'TARGET_DATE', '2026-10-07')
    clean_writer.update_archive(r2, 'nse', 'insider_trading', [], {})
    assert json.loads(r2.objects[STATE])['last_merged'] == '2026-10-06'
    run('insider', date(2024, 1, 1), date(2024, 3, 31), FakeNSE(), bf.R2Sink(r2, 'insider', '2026-10-09'))
    monkeypatch.setattr(clean_writer, 'TARGET_DATE', '2026-10-10')  # nothing written that night
    clean_writer.update_archive(r2, 'nse', 'insider_trading', [], {})
    state = json.loads(r2.objects[STATE])
    assert state['last_merged'] == '2026-10-06' and state['records'] == 80
    assert state['backfill']['insider']['chunks_done'] == 1


# --- helpers that keep a full-history clean fast give the old answers ---------

def test_day_first_fast_path_matches_the_general_parser():
    from insiders_clean.dates import to_datetime_day_first
    values = pd.Series(['04-MAR-2024', '07-Mar-2016 18:50', '01-Oct-2026 16:42:04', '27/08/2026', '05-06-2024',
                        '2026-08-27', '31 Aug 2026', '13/25/2024', '01-Mar-3034', '', None, 'garbage',
                        '1-Mar-2016'], dtype=object)
    expected = pd.to_datetime(values.astype('string'), errors='coerce', dayfirst=True, format='mixed')
    pd.testing.assert_series_equal(to_datetime_day_first(values), expected, check_names=False)


def test_most_common_and_per_group_match_the_groupby_lambdas():
    import numpy as np

    from insiders_clean.entities import most_common, per_group
    rng = np.random.default_rng(3)
    n = 5000
    f = pd.DataFrame({'a': rng.choice(['x', 'y', None], n), 'b': rng.integers(0, 300, n).astype(str),
                      'v': rng.choice([f'v{i}' for i in range(5)] + [None], n)})
    old = f.dropna(subset=['v']).groupby(['a', 'b'])['v'].agg(lambda s: s.value_counts().index[0])
    new = most_common(f, ['a', 'b'], 'v')
    assert len(old) == len(new) and all(new[k] == v for k, v in old.items())  # ties included
    g = f.groupby(['a', 'b'], dropna=False, sort=False)
    assert per_group(g.ngroup().to_numpy(), f['v'], lambda c: '|'.join(map(str, c))) == \
        g['v'].agg(lambda s: '|'.join(map(str, s))).tolist()
