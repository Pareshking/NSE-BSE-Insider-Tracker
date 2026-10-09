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


def test_block_stops_run(monkeypatch):
    monkeypatch.setattr(pb.requests, 'Session', lambda: type('S', (), {'headers': {}, 'get': lambda self, u, timeout=0: Resp(403, b'x')})())
    try:
        pb.run(date(2026, 10, 8), date(2026, 10, 8), ['NSE'], sleep=lambda s: None)
        assert False
    except pb.Stop:
        pass
