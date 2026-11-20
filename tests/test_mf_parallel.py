"""Fund houses read side by side (scripts/mf_portfolios.py run_houses): every house once, a failing house never stops
the others, the report the same whatever order the houses finish in, and browser houses kept on the browser's thread.
Fakes only, no network."""
from __future__ import annotations

import threading
import time

import pandas as pd
import pytest

import mf_portfolios as mp
from collectors.mf_portfolios import find
from collectors.mf_portfolios.find import House


def _houses():
    plain = [House(f'p{i}', f'Plain {i}', f'https://p{i}.example/') for i in range(8)]
    browser = [House('b0', 'Browser 0', 'https://b0.example/', render=True),
               House('b1', 'Browser 1', 'https://b1.example/', browser_fetch=True)]
    return [plain[0], browser[0], *plain[1:5], browser[1], *plain[5:]]


def _fake_collect(delays: dict, fail: set = frozenset(), calls: list | None = None, lock=None):
    """collect_house as the run sees it: one result per month, after a delay per house (so they finish out of order)."""
    def collect(house, months, browser=None):
        if calls is not None:
            with lock:
                calls.append((house.key, threading.current_thread() is threading.main_thread()))
        time.sleep(delays.get(house.key, 0))
        if house.key in fail:
            raise RuntimeError(f'{house.key} broke')
        return [{'house': house.key, 'month': m, 'found': False, 'links_on_page': 0, 'files': [],
                 'why': 'no file for the month on the page'} for m in months]
    return collect


@pytest.mark.parametrize('workers', [1, 4, 16])
def test_every_house_runs_once_and_browser_houses_stay_on_the_main_thread(monkeypatch, workers):
    calls, lock = [], threading.Lock()
    monkeypatch.setattr(mp, 'collect_house', _fake_collect({}, calls=calls, lock=lock))
    hs = _houses()
    out = mp.run_houses(hs, lambda h: mp.run_house(h, ['2026-09', '2026-10']), workers=workers)
    assert [h.key for h, _ in out] == [h.key for h in hs]
    assert sorted(k for k, _ in calls) == sorted(h.key for h in hs)   # each exactly once
    on_main = dict(calls)
    assert on_main['b0'] and on_main['b1']                              # Playwright's thread
    if workers > 1:
        assert not any(on_main[h.key] for h in hs if not mp.uses_browser(h))
    for h, res in out:
        assert [r['month'] for r in res] == ['2026-09', '2026-10'] and all(r['house'] == h.key for r in res)


def test_a_failing_house_does_not_stop_the_others(monkeypatch):
    monkeypatch.setattr(mp, 'collect_house', _fake_collect({'p1': 0.05}, fail={'p2', 'b0'}))
    out = dict((h.key, res) for h, res in mp.run_houses(_houses(), lambda h: mp.run_house(h, ['2026-10']), workers=4))
    assert len(out) == 10
    for k in ('p2', 'b0'):
        assert out[k] == [{'house': k, 'month': '2026-10', 'found': False,
                           'why': f'collector error (RuntimeError: {k} broke)'}]
    assert all(res[0]['why'] == 'no file for the month on the page' for k, res in out.items() if k not in ('p2', 'b0'))


def test_an_exception_past_run_house_is_returned_in_its_place():
    def work(h):
        if h.key == 'p3':
            raise ValueError('boom')
        return h.key
    out = mp.run_houses(_houses(), work, workers=3)
    got = dict((h.key, r) for h, r in out)
    assert isinstance(got.pop('p3'), ValueError)
    assert got == {k: k for k in got}


def test_a_house_that_fails_midway_keeps_the_months_it_finished(monkeypatch):
    """A month archived before the error stays reported as found; only the months after it carry the error."""
    rows = pd.DataFrame({'isin': ['INE000A01011'], 'shares': [1.0], 'value_lakh': [1.0]})

    def collect(house, months, browser=None):
        return [{'house': house.key, 'month': '2026-09', 'found': True, 'files': ['u'], 'rows': rows},
                {'house': house.key, 'month': '2026-10', 'found': True, 'files': ['u'], 'rows': rows}]
    calls = []

    def holdings(r, key, month):
        calls.append(month)
        if month == '2026-10':
            raise OSError('disk')
        return pd.DataFrame({'isin': ['INE000A01011'], 'value_lakh': [1.0]})
    monkeypatch.setattr(mp, 'collect_house', collect)
    monkeypatch.setattr(mp.mf_holdings, 'holdings', holdings)
    monkeypatch.setattr(mp.mf_holdings, 'scheme_list', lambda *a: pd.DataFrame({'equity_lines': [1], 'passive': [False]}))
    res = mp.run_house(House('x', 'X', 'https://x.example/'), ['2026-09', '2026-10'])
    assert [r['month'] for r in res] == ['2026-09', '2026-10']
    assert res[0]['found'] and res[0]['isins'] == 1 and 'rows' not in res[0]
    assert res[1] == {'house': 'x', 'month': '2026-10', 'found': False, 'why': 'collector error (OSError: disk)'}


def test_results_are_the_same_whatever_order_houses_finish(monkeypatch):
    hs = _houses()
    runs = []
    for delays in ({h.key: 0.002 * i for i, h in enumerate(hs)},              # first listed finishes first
                   {h.key: 0.002 * (len(hs) - i) for i, h in enumerate(hs)},  # last listed finishes first
                   {}):
        monkeypatch.setattr(mp, 'collect_house', _fake_collect(delays, fail={'p4'}))
        for workers in (1, 6):
            out = mp.run_houses(hs, lambda h: mp.run_house(h, ['2026-08', '2026-09']), workers=workers)
            runs.append({h.key: res for h, res in out})
    assert all(list(r) == [h.key for h in hs] for r in runs)   # the report's order: the houses list's
    assert all(r == runs[0] for r in runs)


def test_workers_from_the_environment(monkeypatch):
    monkeypatch.setenv('MF_HOUSE_WORKERS', '3')
    assert mp.house_workers() == 3
    monkeypatch.setenv('MF_HOUSE_WORKERS', '0')
    assert mp.house_workers() == 1
    monkeypatch.setenv('MF_HOUSE_WORKERS', 'many')
    assert mp.house_workers() == 6
    monkeypatch.delenv('MF_HOUSE_WORKERS')
    assert mp.house_workers() == 6


def test_houses_that_use_the_browser_are_named():
    """Rendered pages, browser downloads and the apis2 readers that drive a page all count as browser houses."""
    import inspect

    from collectors.mf_portfolios import apis2
    from collectors.mf_portfolios.houses import BY_KEY
    for k in ('sbi', 'nps_lic', 'bandhan', 'mahindra', 'edelweiss', 'bajaj', 'jmf'):
        assert mp.uses_browser(BY_KEY[k]), k
    for k in ('hdfc', 'canara', 'invesco', 'hsbc', 'sundaram', 'icici', 'nippon', 'nps_sbi'):
        assert not mp.uses_browser(BY_KEY[k]), k
    # every apis2 function that opens the browser is one of BROWSER_READERS or called only by one
    src = inspect.getsource(apis2)
    fns = {name: inspect.unwrap(fn) for name, fn in vars(apis2).items() if callable(fn)}   # lru_cache unwrapped
    users = [name for name, fn in fns.items() if inspect.isfunction(fn) and fn.__module__ == apis2.__name__
             and 'with _browser()' in inspect.getsource(fn)]
    readers = {f.__name__ for f in apis2.BROWSER_READERS}
    for name in users:
        assert name in readers or any(f'{name}()' in inspect.getsource(r) for r in apis2.BROWSER_READERS), name
    assert src.count('with _browser()') == len(users)


def test_shared_browser_refuses_another_thread(monkeypatch):
    monkeypatch.setattr(find, '_PW', {'browser': object(), 'pw': None, 'thread': threading.get_ident()})
    assert find.shared_browser() is find._PW['browser']
    err = []

    def other():
        try:
            find.shared_browser()
        except RuntimeError as exc:
            err.append(str(exc))
    t = threading.Thread(target=other)
    t.start()
    t.join()
    assert err and 'other than the one that started it' in err[0]


def test_raw_capture_from_many_threads_keeps_every_capture(monkeypatch, tmp_path):
    import json

    import raw_capture
    monkeypatch.setattr(raw_capture, 'DIR', tmp_path)
    go = threading.Barrier(8)

    def one(i):
        go.wait()
        for j in range(5):
            raw_capture.capture('amc', 'x/portfolio_month', b'same bytes', url=f'https://h{i}.example/{j}')
    ts = [threading.Thread(target=one, args=(i,)) for i in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    metas = [json.loads(p.read_text()) for p in tmp_path.glob('*.json')]
    assert len(metas) == 40 and len({m['url'] for m in metas}) == 40
    assert len(list(tmp_path.glob('*.body'))) == 40 and not list(tmp_path.glob('*.part'))


def test_main_dry_run_reads_each_house_once(monkeypatch, capsys):
    hs = _houses()
    calls, lock = [], threading.Lock()
    monkeypatch.setattr(mp, 'HOUSES', hs)
    monkeypatch.setattr(mp, 'collect_house', _fake_collect({'p0': 0.02}, fail={'p5'}, calls=calls, lock=lock))
    monkeypatch.setattr(find, 'shared_browser', lambda: object())
    monkeypatch.setattr(find, 'close_browser', lambda: None)
    assert mp.main(['--month', '2026-10', '--dry-run']) == 0
    assert sorted(k for k, _ in calls) == sorted(h.key for h in hs)
    assert capsys.readouterr().out.strip().endswith('found 0 of 10 house-months')
