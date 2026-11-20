"""The filing text step read in parallel: every filing once, a failure stays with its filing, the same records as a
serial run, a file filed twice read once, downloads per host and OCR pages per CPU kept to their limits. Fakes only:
no network, no tesseract."""
from __future__ import annotations

import random
import threading
import time
from datetime import date

import pandas as pd
from test_archive_and_writer import FakeR2

import announcement_sample as s
import filing_text_extract as fx
from clean_writer import put_parquet
from insiders_clean import filing_text as ft

DAY = date(2026, 10, 14)
COLS = ['event_id', 'file_url', 'file_type', 'broadcast_date']


def _archive(r2, exchange, rows):
    put_parquet(r2, f'archive/announcements/{exchange}/year=2026/month=10.parquet', pd.DataFrame(rows, columns=COLS))


def _nse(i, body=None):
    return (f'nse:{i}', f'https://nsearchives.nseindia.com/corporate/{i}.pdf', 'pdf', '2026-10-14')


def _bse(i):
    return (f'bse:{i}', f'https://www.bseindia.com/xml-data/corpfiling/AttachLive/{i}.pdf', 'pdf', '2026-10-14')


class Counting:
    """A fake text_of: the text is the bytes, after a random wait (completion order shuffled); raises on b'bad'."""

    def __init__(self, seed=0, fail=(b'bad',)):
        self.calls, self.lock, self.rnd, self.fail = [], threading.Lock(), random.Random(seed), fail

    def __call__(self, data, limit=None):
        with self.lock:
            self.calls.append(data)
            wait = self.rnd.random() * 0.01
        time.sleep(wait)
        if data in self.fail:
            raise ValueError('cannot read this one')
        return data.decode(), [f'{len(data)} bytes']


def _records(r2):
    out = []
    for ex in ('nse', 'bse'):
        df = ft.load_day(r2, ex, DAY)
        out.append(df.drop(columns=['extracted_at']).sort_values('event_id').reset_index(drop=True))
    return out


def _setup(n=40, bad=(7,), dup_on_bse=(3, 5, 11)):
    r2 = FakeR2()
    nse = [_nse(i) for i in range(n)]
    bse = [_bse(i) for i in range(n)]
    _archive(r2, 'nse', nse)
    _archive(r2, 'bse', bse)
    files = {}
    for i in range(n):
        files[_nse(i)[1]] = b'bad' if i in bad else f'nse text {i}'.encode()
        files[_bse(i)[1]] = files[_nse(i)[1]] if i in dup_on_bse else f'bse text {i}'.encode()
    return r2, files


def _go(r2, files, workers, text_of, pause=0.0):
    return fx.run(r2, DAY, DAY, minutes=5, workers=workers, pause=pause, download=lambda u: files[u], text_of=text_of)


def test_parallel_reads_every_filing_once_and_writes_the_same_records_as_a_serial_run():
    r2s, files = _setup()
    serial = _go(r2s, files, 1, Counting())
    r2p, _ = _setup()
    reader = Counting(seed=1)
    parallel = _go(r2p, files, 8, reader)
    assert parallel == serial
    for a, b in zip(_records(r2s), _records(r2p)):
        pd.testing.assert_frame_equal(a, b)
    nse, bse = _records(r2p)
    assert len(nse) == 40 and len(bse) == 40 and nse['event_id'].is_unique and bse['event_id'].is_unique
    # each distinct file read once, the BSE copies of NSE files (3, 5, 11) taking the NSE read's text
    distinct_ok = {d for d in files.values() if d != b'bad'}
    assert sorted(c for c in reader.calls if c != b'bad') == sorted(distinct_ok)


def test_a_failure_is_recorded_for_its_filing_only():
    r2, files = _setup(bad=(7,), dup_on_bse=())
    report = _go(r2, files, 4, Counting())
    nse, bse = (d.set_index('event_id') for d in _records(r2))
    assert nse.loc['nse:7', 'status'] == 'failed' and 'cannot read this one' in nse.loc['nse:7', 'reason']
    assert (nse.drop(index='nse:7')['status'] == 'ok').all() and (bse['status'] == 'ok').all()
    assert report['days'][0]['failed'] == 1 and report['days'][1]['failed'] == 0


def test_a_file_filed_on_both_exchanges_is_read_once_and_both_filings_get_their_own_record():
    r2, files = _setup(n=6, bad=(), dup_on_bse=(3,))
    reader = Counting()
    _go(r2, files, 4, reader)
    assert reader.calls.count(b'nse text 3') == 1
    nse, bse = (d.set_index('event_id') for d in _records(r2))
    for col in ('status', 'text', 'notes', 'file_sha256', 'file_bytes', 'pages', 'chars'):
        assert nse.loc['nse:3', col] == bse.loc['bse:3', col]
    assert bse.loc['bse:3', 'file_url'].startswith('https://www.bseindia.com/')


def test_two_filings_of_the_same_bytes_at_once_are_read_once():
    r2 = FakeR2()
    _archive(r2, 'bse', [_bse(i) for i in range(8)])
    files = {_bse(i)[1]: b'the same results PDF' for i in range(8)}
    gate = threading.Event()

    def slow(data, limit=None):
        slow.calls += 1
        gate.wait(2)
        return data.decode(), []
    slow.calls = 0
    threading.Timer(0.05, gate.set).start()
    _go(r2, files, 8, slow)
    bse = ft.load_day(r2, 'bse', DAY)
    assert slow.calls == 1 and len(bse) == 8 and (bse['text'] == 'the same results PDF').all()


def test_when_the_shared_read_fails_the_other_filing_reads_the_file_itself():
    r2 = FakeR2()
    _archive(r2, 'bse', [_bse(1), _bse(2)])
    files = {_bse(1)[1]: b'same', _bse(2)[1]: b'same'}
    calls = []

    def flaky(data, limit=None):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError('pymupdf hiccup')
        return data.decode(), []
    _go(r2, files, 2, flaky)
    bse = ft.load_day(r2, 'bse', DAY)
    assert len(calls) == 2 and sorted(bse['status']) == ['failed', 'ok']


def test_a_later_run_takes_the_text_of_a_file_already_in_the_days_cache():
    r2, files = _setup(n=4, bad=(), dup_on_bse=(2,))
    _archive(r2, 'bse', [])
    _go(r2, files, 2, Counting())                     # NSE only: bse has no rows yet
    _archive(r2, 'bse', [_bse(i) for i in range(4)])
    reader = Counting()
    _go(r2, files, 2, reader)
    assert b'nse text 2' not in reader.calls and len(reader.calls) == 3
    bse = ft.load_day(r2, 'bse', DAY).set_index('event_id')
    assert bse.loc['bse:2', 'text'] == 'nse text 2' and bse.loc['bse:2', 'notes'] == '10 bytes'


def test_downloads_stay_at_four_per_host_whatever_the_workers():
    r2, files = _setup(n=30, bad=(), dup_on_bse=())
    live, most, lock = {}, {}, threading.Lock()

    def download(url):
        host = url.split('/')[2]
        with lock:
            live[host] = live.get(host, 0) + 1
            most[host] = max(most.get(host, 0), live[host])
        time.sleep(0.01)
        with lock:
            live[host] -= 1
        return files[url]
    fx.run(r2, DAY, DAY, minutes=5, workers=12, pause=0, download=download, text_of=Counting())
    assert most and all(n <= fx.PER_HOST for n in most.values())
    assert max(most.values()) > 1          # still in parallel


def test_ocr_pages_run_one_per_slot_and_tesseract_gets_the_resolution(monkeypatch, tmp_path):
    monkeypatch.setattr(s, '_OCR_SEM', threading.BoundedSemaphore(2))
    live, most, cmds, lock = [0], [0], [], threading.Lock()

    def render(data, page, out_dir, dpi=200, fmt='png'):
        p = out_dir / f'p{page}.{fmt}'
        p.write_bytes(b'P6')
        return p

    class Out:
        stdout, stderr, returncode = b'page text', b'', 0

    def fake_run(cmd, **kw):
        with lock:
            cmds.append(cmd)
            live[0] += 1
            most[0] = max(most[0], live[0])
        time.sleep(0.02)
        with lock:
            live[0] -= 1
        return Out()
    monkeypatch.setattr(s, 'render_page', render)
    monkeypatch.setattr(s.subprocess, 'run', fake_run)
    threads = [threading.Thread(target=s.ocr_page, args=(b'%PDF', i)) for i in range(1, 9)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(cmds) == 8 and most[0] <= 2
    assert all(c[0] == 'tesseract' and c[1].endswith('.ppm') and c[c.index('--dpi') + 1] == '200' for c in cmds)


def test_a_page_drawn_as_ppm_by_pymupdf_when_pdftoppm_leaves_nothing(monkeypatch, tmp_path):
    import pymupdf
    d = pymupdf.open()
    d.new_page().insert_text((72, 72), 'scan')
    monkeypatch.setattr(s.subprocess, 'run', lambda *a, **k: None)
    got = s.render_page(d.tobytes(), 1, tmp_path, fmt='ppm')
    assert got is not None and got.suffix == '.ppm' and got.read_bytes()[:2] == b'P6'


def test_workers_default_to_the_cpus_and_the_environment_overrides(monkeypatch):
    monkeypatch.delenv('FILING_TEXT_WORKERS', raising=False)
    monkeypatch.setattr(fx.os, 'cpu_count', lambda: 4)
    assert fx.default_workers() == 4
    monkeypatch.setenv('FILING_TEXT_WORKERS', '6')
    assert fx.default_workers() == 6
