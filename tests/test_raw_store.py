"""Write-once raw layer and the deals --redo recovery."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

import nse_history_backfill as bf
import pytest
from test_archive_and_writer import FakeR2
from test_history_backfill import FakeNSE, Resp, csv_bytes

from insiders_clean import raw_store
from insiders_clean.raw_store import RawStore, sha256_hex


class Missing(Exception):
    def __init__(self):
        self.response = {'Error': {'Code': '404'}}


class OnceR2(FakeR2):
    """FakeR2 that also answers head_object and refuses overwrites like If-None-Match."""

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise Missing()
        return {}

    def put_object(self, Bucket, Key, Body, ContentType=None, IfNoneMatch=None):
        if IfNoneMatch == '*' and Key in self.objects:
            raise AssertionError('overwrite attempted')
        self.objects[Key] = Body


def store(r2, t):
    return RawStore(r2, bucket='b', collector='test', clock=lambda: t)


T1 = datetime(2026, 10, 9, 7, 0, 0, 1, tzinfo=timezone.utc)
T2 = datetime(2026, 10, 9, 8, 0, 0, 1, tzinfo=timezone.utc)


def test_exact_bytes_stored_under_their_own_hash_with_fetch_metadata():
    r2, body = OnceR2(), b'{"data": [1, 2]}\n'
    rec = store(r2, T1).put('nse', 'insider', body, url='https://x/api', params={'a': 1},
                            content_type='application/json; charset=utf-8', covers={'from': '2026-01-01'})
    assert r2.objects[rec['blob_key']] == body
    assert rec['blob_key'].endswith(f'{sha256_hex(body)}.json') and rec['blob_key'].startswith('raw_v2/nse/insider/blobs/')
    meta = json.loads(r2.objects[rec['fetch_key']])
    assert meta['sha256'] == sha256_hex(body) and meta['bytes'] == len(body) and meta['params'] == {'a': 1}
    assert meta['url'] == 'https://x/api' and meta['http_status'] == 200 and meta['covers'] == {'from': '2026-01-01'}


def test_same_bytes_twice_is_one_blob_and_two_fetch_records_and_no_overwrite():
    r2, body = OnceR2(), b'a,b\n1,2\n'
    s1, s2 = store(r2, T1), store(r2, T2)
    r1 = s1.put('nse', 'bulk', body, url='u', content_type='text/csv')
    r2_ = s2.put('nse', 'bulk', body, url='u', content_type='text/csv')
    assert r1['blob_key'] == r2_['blob_key'] and r1['fetch_key'] != r2_['fetch_key']
    assert (s1.written, s1.reused, s2.written, s2.reused) == (1, 0, 0, 1)
    assert sum(k.endswith('.csv') for k in r2.objects) == 1


def test_changed_payload_gets_a_new_blob_old_one_untouched():
    r2 = OnceR2()
    a = store(r2, T1).put('nse', 'insider', b'[1]', url='u', content_type='application/json')
    b = store(r2, T2).put('nse', 'insider', b'[1,2]', url='u', content_type='application/json')
    assert a['blob_key'] != b['blob_key'] and r2.objects[a['blob_key']] == b'[1]'


def test_client_without_conditional_put_still_never_overwrites():
    class Old(OnceR2):
        def put_object(self, Bucket, Key, Body, ContentType=None, **kw):
            if kw:
                raise TypeError('unexpected keyword')
            self.objects[Key] = Body
    r2 = Old()
    s = store(r2, T1)
    s.put('nse', 'x', b'[0]', url='u')
    s.put('nse', 'x', b'[0]', url='u')
    assert s.written == 1 and s.reused == 1


def test_backfill_stores_the_response_before_parsing_and_flags_round_trips():
    r2 = OnceR2()
    body = csv_bytes('nse_bulk_2024.csv')

    class Headed(FakeNSE):
        def get(self, url, params=None, headers=None, timeout=None):
            r = super().get(url, params, headers, timeout)
            r.headers = {'Content-Type': 'text/csv'}
            return r
    http = bf.NseHistory(session=Headed(csv_body=body), sleep=lambda s: None, raw=store(r2, T1))
    rep = bf.run_dataset('bulk', date(2024, 1, 1), date(2024, 12, 31), http, bf.R2Sink(r2, 'bulk', '2026-10-09'),
                         '2026-10-09', log=lambda *_: None)
    blobs = [k for k in r2.objects if k.startswith('raw_v2/nse/bulk_deals/blobs/')]
    assert len(blobs) == 1 and r2.objects[blobs[0]] == body  # exact bytes, round trips included
    assert rep['rows_stored'] == rep['rows_fetched']  # nothing dropped


def test_backfill_aborts_the_chunk_if_the_raw_copy_cannot_be_written():
    class Broken(OnceR2):
        def put_object(self, *a, **k):
            raise RuntimeError('R2 down')

    class Headed(FakeNSE):
        def get(self, url, params=None, headers=None, timeout=None):
            r = super().get(url, params, headers, timeout)
            r.headers = {}
            return r
    r2 = Broken()
    http = bf.NseHistory(session=Headed(), sleep=lambda s: None, raw=store(r2, T1))
    rep = bf.run_dataset('insider', date(2024, 1, 1), date(2024, 3, 31), http, bf.DrySink(), '2026-10-09',
                         log=lambda *_: None)
    assert rep['chunks_done'] == 0 and rep['errors'] and 'raw store write failed' in rep['errors'][0]['error']


def test_redo_refetches_done_chunks_and_adds_nothing_twice():
    r2 = OnceR2()
    nse = FakeNSE()
    run = lambda redo: bf.run_dataset('bulk', date(2024, 1, 1), date(2024, 12, 31),  # noqa: E731
                                      bf.NseHistory(session=nse, sleep=lambda s: None),
                                      bf.R2Sink(r2, 'bulk', '2026-10-09', redo=redo), '2026-10-09',
                                      log=lambda *_: None)
    first = run(False)
    again = run(False)
    redo = run(True)
    assert first['rows_added'] > 0 and again['chunks_skipped_done'] == 1 and again['chunks_done'] == 0
    assert redo['chunks_done'] == 1 and redo['rows_added'] == 0  # idempotent merge


def test_capture_then_flush_stores_exact_bytes_with_original_fetch_time(tmp_path, monkeypatch):
    import raw_capture
    import raw_flush
    monkeypatch.setattr(raw_capture, 'DIR', tmp_path)
    body = '{"data": [{"x": 1}]}'
    name = raw_capture.capture('nse', 'bulk_deals', body, url='https://nse/api', status=200,
                              content_type='application/json', covers={'from': '2026-10-08'})
    assert name and len(list(tmp_path.iterdir())) == 2
    r2 = OnceR2()
    res = raw_flush.flush(r2, tmp_path, bucket='b')
    assert (res['found'], res['stored'], res['failed']) == (1, 1, 0) and not list(tmp_path.iterdir())
    blob = next(k for k in r2.objects if '/blobs/' in k)
    assert r2.objects[blob] == body.encode()
    meta = json.loads(next(v for k, v in r2.objects.items() if '/fetches/' in k))
    assert meta['url'] == 'https://nse/api' and meta['covers'] == {'from': '2026-10-08'}
    assert meta['fetched_at_utc'].startswith('20')


def test_flush_keeps_a_capture_that_could_not_be_stored(tmp_path, monkeypatch):
    import raw_capture
    import raw_flush
    monkeypatch.setattr(raw_capture, 'DIR', tmp_path)
    raw_capture.capture('bse', 'bulk', b'[1]', url='u')

    class Down(OnceR2):
        def put_object(self, *a, **k):
            raise RuntimeError('R2 down')
    res = raw_flush.flush(Down(), tmp_path, bucket='b')
    assert res['failed'] == 1 and res['stored'] == 0 and len(list(tmp_path.iterdir())) == 2  # nothing lost


def test_flush_of_a_missing_folder_is_not_an_error(tmp_path):
    import raw_flush
    assert raw_flush.flush(OnceR2(), tmp_path / 'nope', bucket='b')['found'] == 0
