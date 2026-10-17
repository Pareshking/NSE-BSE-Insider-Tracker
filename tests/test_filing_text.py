"""The filing text cache: one row per filing, resumable, nothing cut, failures counted."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from test_archive_and_writer import FakeR2

import filing_text_extract as fx
from clean_writer import put_parquet, read_parquet
from insiders_clean import filing_text as ft

DAY = date(2026, 10, 14)


def _archive(r2, exchange, rows):
    cols = ['event_id', 'file_url', 'file_type', 'broadcast_date']
    put_parquet(r2, f'archive/announcements/{exchange}/year=2026/month=10.parquet', pd.DataFrame(rows, columns=cols))


def _row(i, day='2026-10-14', kind='pdf', url=None):
    return (f'nse:{i}', url or f'https://nsearchives.nseindia.com/corporate/{i}.pdf', kind, day)


def _run(r2, files, text=lambda data: (data.decode(), ['1.0 MB']), **kw):
    return fx.run(r2, DAY, DAY, minutes=5, workers=2, pause=0, download=lambda url: files[url],
                  text_of=lambda data, limit=None: text(data), **kw)


def test_key_is_one_file_per_exchange_and_day():
    assert ft.key('bse', '2026-01-05') == 'archive/filing_text/bse/year=2026/month=01/day=05.parquet'


def test_extracts_each_filing_once_and_keeps_the_full_text():
    r2 = FakeR2()
    _archive(r2, 'nse', [_row(1), _row(2, kind='zip'), _row(3, day='2026-10-13'), _row(4, kind='html'),
                         ('nse:xbrl:9', 'https://x/9.xml', 'xbrl', '2026-10-14'),
                         ('nse:5', None, 'pdf', '2026-10-14')])
    big = 'x' * 400_000
    files = {_row(1)[1]: big.encode(), _row(2)[1]: b'zip text'}
    report = _run(r2, files)
    got = ft.load_day(r2, 'nse', DAY).set_index('event_id')
    assert sorted(got.index) == ['nse:1', 'nse:2']
    assert got.loc['nse:1', 'chars'] == 400_000 and len(got.loc['nse:1', 'text']) == 400_000   # not cut
    assert got.loc['nse:2', 'status'] == 'ok' and got.loc['nse:2', 'extractor'] == ft.EXTRACTOR
    assert report['days'][0]['ok'] == 2 and report['days'][0]['files'] == 2
    again = _run(r2, files)   # nothing to do the second time
    assert again['days'][0]['cached'] == 2 and again['days'][0]['ok'] == 0


def test_empty_text_is_no_text_and_is_not_retried():
    r2 = FakeR2()
    _archive(r2, 'nse', [_row(1)])
    files = {_row(1)[1]: b'   '}
    assert _run(r2, files)['days'][0]['no_text'] == 1
    assert _run(r2, files)['days'][0]['cached'] == 1


def test_failures_are_retried_three_times_and_a_missing_file_never():
    r2 = FakeR2()
    _archive(r2, 'nse', [_row(1), _row(2)])
    calls = []

    def download(url):
        calls.append(url)
        raise RuntimeError('HTTP 404 gone' if url.endswith('2.pdf') else 'HTTP 503 busy')

    def run_once():
        return fx.run(r2, DAY, DAY, minutes=5, workers=1, pause=0, download=download,
                      text_of=lambda d, limit=None: (d.decode(), []))

    for _ in range(5):
        run_once()
    assert calls.count(_row(1)[1]) == ft.MAX_TRIES and calls.count(_row(2)[1]) == 1
    got = ft.load_day(r2, 'nse', DAY).set_index('event_id')
    assert (got['status'] == 'failed').all() and got.loc['nse:1', 'tries'] == ft.MAX_TRIES


def test_a_failed_filing_that_later_works_replaces_its_failure():
    r2 = FakeR2()
    _archive(r2, 'nse', [_row(1)])
    state = {'up': False}

    def download(url):
        if not state['up']:
            raise RuntimeError('HTTP 503 busy')
        return b'hello'

    kw = dict(minutes=5, workers=1, pause=0, download=download, text_of=lambda d, limit=None: (d.decode(), []))
    fx.run(r2, DAY, DAY, **kw)
    state['up'] = True
    fx.run(r2, DAY, DAY, **kw)
    got = ft.load_day(r2, 'nse', DAY)
    assert len(got) == 1 and got.iloc[0]['status'] == 'ok' and got.iloc[0]['text'] == 'hello'


def test_the_time_budget_stops_new_files_and_a_rerun_continues():
    r2 = FakeR2()
    _archive(r2, 'nse', [_row(i) for i in range(1, 6)])
    files = {_row(i)[1]: b't' for i in range(1, 6)}
    now = {'t': 0.0}
    seen = []

    def download(url):
        seen.append(url)
        now['t'] += 40   # each file takes 40 s of the budget's clock
        return files[url]

    kw = dict(workers=1, pause=0, download=download, text_of=lambda d, limit=None: (d.decode(), []))
    first = fx.run(r2, DAY, DAY, minutes=1, clock=lambda: now['t'], **kw)
    assert first['stopped_early'] and len(seen) < 5
    rest = fx.run(r2, DAY, DAY, minutes=1000, clock=lambda: now['t'], **kw)
    assert len(ft.load_day(r2, 'nse', DAY)) == 5 and not rest['stopped_early']


def test_pending_ignores_other_rows_and_keeps_the_never_tried():
    rows = pd.DataFrame([_row(1), _row(2), _row(3)], columns=['event_id', 'file_url', 'file_type', 'broadcast_date'])
    cached = pd.DataFrame([{'event_id': 'nse:1', 'status': 'ok', 'tries': 1},
                           {'event_id': 'nse:2', 'status': 'failed', 'tries': 3}])
    assert list(ft.pending(rows, cached)['event_id']) == ['nse:3']


def test_newest_first_starts_with_the_last_day_and_a_stop_leaves_the_oldest_for_the_next_run():
    r2 = FakeR2()
    rows = [('nse:1', 'https://nsearchives.nseindia.com/corporate/1.pdf', 'pdf', '2026-10-13'),
            ('nse:2', 'https://nsearchives.nseindia.com/corporate/2.pdf', 'pdf', '2026-10-14'),
            ('nse:3', 'https://nsearchives.nseindia.com/corporate/3.pdf', 'pdf', '2026-10-15')]
    put_parquet(r2, 'archive/announcements/nse/year=2026/month=10.parquet',
                pd.DataFrame(rows, columns=['event_id', 'file_url', 'file_type', 'broadcast_date']))
    order = []

    def download(url):
        order.append(url[-5:])
        return b't'

    now = {'t': 0.0}

    def clock():
        return now['t']

    def slow(url):
        now['t'] += 40
        return download(url)

    first = fx.run(r2, date(2026, 10, 13), date(2026, 10, 15), minutes=1, workers=1, pause=0, download=slow,
                   text_of=lambda d, limit=None: (d.decode(), []), clock=clock, newest_first=True)
    assert order[0] == '3.pdf' and first['stopped_early']
    assert ft.load_day(r2, 'nse', date(2026, 10, 15)).shape[0] == 1 and ft.load_day(r2, 'nse', date(2026, 10, 13)).empty


def test_the_reader_cache_returns_only_finished_records_made_from_the_same_link():
    r2 = FakeR2()
    day = date(2026, 10, 14)
    rows = pd.DataFrame([
        {'event_id': 'nse:1', 'exchange': 'nse', 'broadcast_date': '2026-10-14', 'file_url': 'https://x/1.pdf', 'status': 'ok', 'tries': 1, 'text': 'hello', 'extractor': ft.EXTRACTOR},
        {'event_id': 'nse:2', 'exchange': 'nse', 'broadcast_date': '2026-10-14', 'file_url': 'https://x/2.pdf', 'status': 'failed', 'tries': 1, 'text': None},
        {'event_id': 'nse:3', 'exchange': 'nse', 'broadcast_date': '2026-10-14', 'file_url': 'https://x/3.pdf', 'status': 'no_text', 'tries': 1, 'text': '', 'extractor': ft.EXTRACTOR},
        {'event_id': 'nse:4', 'exchange': 'nse', 'broadcast_date': '2026-10-14', 'file_url': 'https://x/4.pdf', 'status': 'ok', 'tries': 1, 'text': 'old', 'extractor': 'pdftotext-layout+xbrl-facts v1'}])
    ft.save_day(r2, 'nse', day, rows)
    cache = ft.Cache(r2)
    row = lambda e, u: {'event_id': e, 'exchange': 'NSE', 'broadcast_date': '2026-10-14', 'file_url': u}   # noqa: E731
    assert cache(row('nse:1', 'https://x/1.pdf'))['text'] == 'hello'
    assert cache(row('nse:1', 'https://x/other.pdf')) is None      # the link changed: a different file
    assert cache(row('nse:2', 'https://x/2.pdf')) is None          # failed: not finished
    assert cache(row('nse:3', 'https://x/3.pdf'))['status'] == 'no_text'
    assert cache(row('nse:4', 'https://x/4.pdf')) is None          # made by an older extractor: read again
    assert cache(row('nse:9', 'https://x/9.pdf')) is None          # not cached
    assert cache({'event_id': 'x', 'exchange': 'OTC', 'broadcast_date': '2026-10-14'}) is None
    assert cache({'event_id': 'bse:1', 'exchange': 'BSE', 'broadcast_date': '2026-10-14', 'file_url': 'u'}) is None   # no day file
