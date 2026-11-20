"""One headless browser per run (collectors/mf_portfolios/find.py shared_browser).

Run 44654006211 (20 Nov 2026): Edelweiss and Bandhan answered "It looks like you are using Playwright Sync API inside
the asyncio loop" in every run that also had a render=True house, because their list readers (apis2._browser) started
a second sync_playwright() beside the collector's. They now share the collector's browser.
"""
from __future__ import annotations

import sys
import types

import pytest

from collectors.mf_portfolios import find

NESTED = 'It looks like you are using Playwright Sync API inside the asyncio loop.\nPlease use the Async API instead.'


class _FakePlaywright:
    """Stands in for playwright.sync_api.sync_playwright with its one rule: one started instance at a time."""
    active = 0
    starts = 0

    def start(self):
        if _FakePlaywright.active:
            raise RuntimeError(NESTED)
        _FakePlaywright.active += 1
        _FakePlaywright.starts += 1
        outer = self

        class _Chromium:
            def launch(self, **kw):
                return types.SimpleNamespace(close=lambda: None, owner=outer)
        self.chromium = _Chromium()
        return self

    def stop(self):
        _FakePlaywright.active -= 1

    def __enter__(self):
        return self.start()

    def __exit__(self, *a):
        self.stop()


@pytest.fixture
def fake_playwright(monkeypatch):
    mod = types.ModuleType('playwright.sync_api')
    mod.sync_playwright = _FakePlaywright
    pkg = types.ModuleType('playwright')
    pkg.sync_api = mod
    monkeypatch.setitem(sys.modules, 'playwright', pkg)
    monkeypatch.setitem(sys.modules, 'playwright.sync_api', mod)
    monkeypatch.setattr(find, '_PW', {})
    _FakePlaywright.active = _FakePlaywright.starts = 0
    yield
    find.close_browser()


def test_old_pattern_is_the_error(fake_playwright):
    """The failure as the run had it: the collector's instance started, then a reader's own."""
    pw = _FakePlaywright().start()
    with pytest.raises(RuntimeError, match='Sync API inside the asyncio loop'):
        with _FakePlaywright():
            pass
    pw.stop()


def test_readers_share_the_collectors_browser(fake_playwright):
    from collectors.mf_portfolios import apis2
    b = find.shared_browser()                    # what scripts/mf_portfolios.py starts for render=True houses
    for _ in range(3):                           # Edelweiss, Bandhan, Mahindra, month after month
        with apis2._browser() as got:
            assert got is b
    assert _FakePlaywright.starts == 1
    find.close_browser()
    assert _FakePlaywright.active == 0 and find._PW == {}


def test_reader_alone_starts_the_browser(fake_playwright):
    """A run of only Edelweiss (no render=True house) starts the browser on first use."""
    from collectors.mf_portfolios import apis2
    with apis2._browser() as b:
        assert b is find.shared_browser()
    assert _FakePlaywright.starts == 1


def test_real_playwright_reader_beside_collector(monkeypatch):
    """With Playwright and a Chromium at hand (CHROMIUM_PATH or Playwright's own): the reader's browser opens a
    context beside the collector's without the nested-loop error."""
    pytest.importorskip('playwright.sync_api')
    from collectors.mf_portfolios import apis2
    monkeypatch.setattr(find, '_PW', {})
    try:
        b = find.shared_browser()
    except Exception as exc:  # noqa: BLE001 - no browser installed here
        pytest.skip(f'no browser: {type(exc).__name__}')
    try:
        with apis2._browser() as got:
            ctx = got.new_context()
            ctx.close()
        assert got is b
    finally:
        find.close_browser()


def test_refusal_hint():
    assert find.refused_hint('cloudflare', '<html><title>Just a\n moment...</title>') == 'server cloudflare, title "Just a moment..."'
    assert find.refused_hint(None, '') == 'server ?'
