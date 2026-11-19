from datetime import date

import pandas as pd

import price_backfill as pb
from test_prices import _csv, ROW


class Resp:
    def __init__(self, status, content=b'', ct='text/csv'):
        self.status_code, self.content, self.headers = status, content, {'Content-Type': ct}


class Sess:
    def __init__(self, resp):
        self.resp = resp
        self.headers = {}

    def get(self, url, timeout=0):
        return self.resp(url)

    def update(self, *_):
        pass


def test_weekdays_skip_weekend():
    assert [d.day for d in pb.weekdays(date(2026, 10, 8), date(2026, 10, 12))] == [8, 9, 12]


def test_run_counts_sessions_and_holidays(monkeypatch):
    def resp(url):
        return Resp(200, _csv(ROW)) if '20261008' in url else Resp(404, b'x')
    monkeypatch.setattr(pb.requests, 'Session', lambda: type('S', (), {'headers': {}, 'get': lambda self, u, timeout=0: resp(u)})())
    t = pb.run(date(2026, 10, 8), date(2026, 10, 9), ['NSE'], sleep=lambda s: None)
    assert t['NSE']['sessions'] == 1 and t['NSE']['no_file'] == 1 and t['NSE']['rows'] == 1


def test_weekend_sessions_are_fetched_and_a_file_of_another_day_is_not_kept(monkeypatch):
    # 1 Feb 2026 was a Sunday session (Budget day) the weekday loop never fetched (audit 19 Nov 2026).
    sunday = '2026-02-01,2026-02-01,CM,NSE,STK,1,INE000A01010,ABC,EQ,,,,,ABC LTD,10.0,12.0,9.5,11.0,11.0,10.0,,11.0,,,1000,11000.00,5,F1,1,,,,,'
    asked = []

    def resp(url):
        asked.append(url)
        if '20260201' in url:
            return Resp(200, _csv(sunday))
        if '20260131' in url:
            return Resp(200, _csv(ROW))   # a file dated 8 Oct 2026 served for 31 Jan: not stored under 31 Jan
        return Resp(404, b'x')
    monkeypatch.setattr(pb.requests, 'Session', lambda: type('S', (), {'headers': {}, 'get': lambda self, u, timeout=0: resp(u)})())
    t = pb.run(date(2026, 1, 30), date(2026, 2, 2), ['NSE'], sleep=lambda s: None, extra={date(2026, 2, 1), date(2026, 1, 31)})
    assert any('20260201' in u for u in asked) and t['NSE']['sessions'] == 1 and t['NSE']['wrong_day'] == 1
    assert [d.day for _, days in pb.months(date(2026, 1, 30), date(2026, 2, 2), {date(2026, 2, 1)}) for d in days] == [30, 1, 2]


def test_weekend_sessions_from_the_calendar():
    import json

    class C:
        def get_object(self, Bucket, Key):
            assert Key == pb.CALENDAR_KEY
            body = json.dumps({'traded': ['2026-01-30', '2026-02-01', '2026-02-02'], 'special_sessions': ['2025-10-21', '2026-11-08']})
            return {'Body': type('B', (), {'read': lambda self: body.encode()})()}
    assert pb.weekend_sessions(C(), 'b') == {date(2026, 2, 1), date(2026, 11, 8)}


def test_block_stops_run(monkeypatch):
    monkeypatch.setattr(pb.requests, 'Session', lambda: type('S', (), {'headers': {}, 'get': lambda self, u, timeout=0: Resp(403, b'x')})())
    try:
        pb.run(date(2026, 10, 8), date(2026, 10, 8), ['NSE'], sleep=lambda s: None)
        assert False
    except pb.Stop:
        pass


def test_html_page_for_a_missing_day_is_no_file_not_an_error(monkeypatch):
    monkeypatch.setattr(pb.requests, 'Session', lambda: type('S', (), {'headers': {}, 'get': lambda self, u, timeout=0: Resp(200, b'<!DOCTYPE html><html>', 'text/html')})())
    t = pb.run(date(2026, 10, 2), date(2026, 10, 2), ['BSE'], sleep=lambda s: None)
    assert t['BSE']['no_file'] == 1 and t['BSE']['errors'] == 0
