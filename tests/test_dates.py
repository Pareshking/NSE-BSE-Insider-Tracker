"""The shared date control (streamlit_app/ui/dates.py; owner, 19 Nov 2026: "A date selector or a date range selector
must be present on required pages"): the preset arithmetic, the clamping to the data and the product window, the
address round trip, and every dated page drawing it and saying the range it shows."""
from __future__ import annotations

import sys
from datetime import date

import pandas as pd
import pytest
from conftest import ROOT
from streamlit.testing.v1 import AppTest
from test_ui_pages import APP_PATHS, data_dir  # noqa: F401  (data_dir is the module fixture)

sys.path.insert(0, str(ROOT / 'streamlit_app'))

from ui import dates  # noqa: E402

LO, HI = date(2025, 10, 8), date(2026, 11, 19)


def test_product_start_is_the_pipelines():
    from insiders_clean.pipeline import PRODUCT_START
    assert dates.PRODUCT_START == PRODUCT_START


def test_presets_end_on_the_last_day_and_count_both_ends():
    assert dates.preset_range('day', LO, HI) == (HI, HI)
    assert dates.preset_range('1w', LO, HI) == (date(2026, 11, 13), HI)          # 7 days, as "7 days" was
    assert dates.Range(*dates.preset_range('1w', LO, HI), '1w').days == 7
    assert dates.preset_range('1m', LO, HI) == (date(2026, 10, 20), HI)          # from the same day a month before, plus one
    assert dates.preset_range('3m', LO, HI) == (date(2026, 8, 20), HI)
    assert dates.preset_range('6m', LO, HI) == (date(2026, 5, 20), HI)
    assert dates.preset_range('1y', LO, HI) == (date(2025, 11, 20), HI)
    assert dates.preset_range('all', LO, HI) == (LO, HI)
    assert dates.preset_range('1m', LO, date(2026, 3, 31)) == (date(2026, 3, 1), date(2026, 3, 31))   # month ends
    with pytest.raises(KeyError):
        dates.preset_range('2y', LO, HI)


def test_a_preset_longer_than_the_data_starts_at_the_first_day():
    lo = date(2026, 9, 1)
    assert dates.preset_range('1y', lo, HI) == (lo, HI)
    assert dates.preset_range('6m', lo, HI) == (lo, HI)


def test_forward_presets_start_today_and_stop_at_the_last_date_held():
    ref, far = date(2026, 11, 19), date(2027, 1, 17)
    assert dates.preset_range('day', ref, far, forward=True) == (ref, ref)
    assert dates.preset_range('1w', ref, far, forward=True) == (ref, date(2026, 11, 25))
    assert dates.preset_range('1m', ref, far, forward=True) == (ref, date(2026, 12, 18))
    assert dates.preset_range('3m', ref, far, forward=True) == (ref, far)    # nothing filed beyond 17 Jan
    with pytest.raises(KeyError):
        dates.preset_range('all', ref, far, forward=True)


def test_clamp_orders_and_keeps_inside():
    assert dates.clamp(date(2026, 11, 30), date(2026, 11, 1), LO, HI) == (date(2026, 11, 1), HI)
    assert dates.clamp(date(2024, 1, 1), date(2025, 1, 1), LO, HI) == (LO, LO)   # wholly before: the first day
    assert dates.clamp(None, None, LO, HI) == (LO, HI)
    assert dates.clamp('2026-10-01', pd.Timestamp('2026-10-31 15:30'), LO, HI) == (date(2026, 10, 1), date(2026, 10, 31))


def test_bounds_follow_the_data_and_the_product_window():
    s = pd.Series(pd.to_datetime(['2025-06-01', '2026-03-04', '2026-11-18 21:10'], format='mixed'))
    assert dates.bounds(s) == (LO, date(2026, 11, 18))                          # nothing before 8 Oct 2025
    assert dates.bounds(s, hi='2026-11-10') == (LO, date(2026, 11, 10))         # never after the as-of date
    assert dates.bounds(pd.Series(pd.to_datetime(['2026-02-01', '2026-05-01'])), hi=HI) == (date(2026, 2, 1), date(2026, 5, 1))
    assert dates.bounds(None, pd.Series([], dtype='datetime64[ns]'), hi=HI) == (LO, HI)   # no data: the window to today
    aware = pd.Series(pd.to_datetime(['2026-11-18T20:00:00Z']))                  # 01:30 on 19 Nov in IST
    assert dates.bounds(aware)[1] == date(2026, 11, 19)
    assert dates.bounds(['2026-11-20', '2026-12-30'], hi='2026-11-19', forward=True) == (date(2026, 11, 19), date(2026, 12, 30))
    assert dates.bounds(None, hi='2026-11-19', forward=True) == (date(2026, 11, 19), date(2026, 11, 19))


def test_range_mask_counts_both_ends_and_any_time_of_day():
    r = dates.Range(date(2026, 11, 1), date(2026, 11, 3), dates.CUSTOM)
    s = pd.Series(['2026-10-31 23:59', '2026-11-01 00:00', '2026-11-03 18:00', '2026-11-04', None], index=[5, 6, 7, 8, 9])
    m = r.mask(s)
    assert list(m.index) == [5, 6, 7, 8, 9] and m.tolist() == [False, True, True, False, False]
    assert r.days == 3


def test_query_round_trip():
    for code in ('day', '1w', '1m', '3m', '6m', '1y', 'all'):
        r = dates.Range(*dates.preset_range(code, LO, HI), code)
        q = dates.to_query(r, default='1w')
        assert q == ({} if code == '1w' else {'range': code})
        back = dates.from_query(q, LO, HI) if q else None
        assert back is None if code == '1w' else back == r
    c = dates.Range(date(2026, 10, 1), date(2026, 10, 31), dates.CUSTOM)
    q = dates.to_query(c, default='1w')
    assert q == {'from': '2026-10-01', 'to': '2026-10-31'}
    assert dates.from_query(q, LO, HI) == c
    # an address outside the data is clamped, a bad one ignored
    assert dates.from_query({'from': '2024-01-01', 'to': '2030-01-01'}, LO, HI) == dates.Range(LO, HI, dates.CUSTOM)
    assert dates.from_query({'range': 'nope'}, LO, HI) is None
    assert dates.from_query({'from': 'garbage'}, LO, HI) is None
    assert dates.from_query({'range': '1M'}, LO, HI).preset == '1m'                # case does not matter
    assert dates.from_query({'range': '1m'}, date(2026, 11, 19), date(2027, 1, 17), forward=True).end == date(2026, 12, 18)
    assert dates.day_from_query({'day': '2026-11-17'}, LO, HI) == date(2026, 11, 17)
    assert dates.day_from_query({'day': '2030-01-01'}, LO, HI) == HI
    assert dates.day_from_query({}, LO, HI) is None


def test_the_words_a_page_shows():
    r = dates.Range(date(2026, 10, 20), HI, '1m')
    assert dates.describe(r) == '20 Oct 2026 to 19 Nov 2026'
    assert dates.label(r) == '20 Oct 2026 to 19 Nov 2026 (1M)'
    assert dates.label(dates.Range(HI, HI, 'day')) == '19 Nov 2026 (latest day)'
    assert dates.label(dates.Range(HI, HI, 'day'), forward=True) == '19 Nov 2026 (today)'
    assert dates.label(dates.Range(LO, HI, 'all')).endswith('(Since 8 Oct 2025)')
    assert dates.label(dates.Range(LO, HI, dates.CUSTOM)).endswith('(Custom)')


# ---- the pages ---------------------------------------------------------------------------------------------------------

PAGES = [  # (module:function, query params, words the page must show)
    ('proto:insiders', {'range': '1m'}, '(1M)'),
    ('proto:deals', {'range': 'all'}, '(Since 8 Oct 2025)'),
    ('proto:stakes', {'range': 'all'}, '(Since 8 Oct 2025)'),
    ('proto:insiders', {'from': '2026-06-01', 'to': '2026-07-15'}, '01 Jun 2026 to 15 Jul 2026 (Custom)'),
    ('proto:situations', {'range': '6m'}, '(6M)'),
    ('proto:calendar', {'range': '3m'}, '(Next 3M)'),
    ('proto:investors_directory', {'range': 'all'}, '(Since 8 Oct 2025)'),
    ('proto:today', {}, 'showing the 7 days to'),
    ('filings_all:render', {'range': 'all'}, '(Since 8 Oct 2025)'),
    ('company:render', {'symbol': 'HCLTECH', 'range': 'all'}, '(Since 8 Oct 2025)'),
    ('entity:render', {'id': 'sbi-mutual-fund'}, 'Showing'),
]


def _render(data_dir, monkeypatch, screen, params):  # noqa: F811
    monkeypatch.setenv('INSIDERS_LOCAL_DATA', str(data_dir))
    mod, _, fn = screen.partition(':')
    at = AppTest.from_string(APP_PATHS + f"""
import streamlit as st
st.cache_data.clear(); st.cache_resource.clear()
if not st.session_state.get('_opened'):   # the address the page is opened with, once (as a browser does)
    st.session_state['_opened'] = True
    for k, v in {params!r}.items():
        st.query_params[k] = v
from ui import theme
theme.inject()
import importlib
getattr(importlib.import_module('screens.{mod}'), '{fn}')()
""", default_timeout=90)
    at.run()
    assert not at.exception, at.exception[0].value
    text = ' '.join(e.proto.body for e in at.get('html')) + ' '.join(c.value for c in at.caption) \
        + ' '.join(m.value for m in at.markdown)
    return at, text


@pytest.mark.parametrize(('screen', 'params', 'words'), PAGES, ids=[p[0] for p in PAGES])
def test_every_dated_page_draws_the_control_and_says_its_range(data_dir, monkeypatch, screen, params, words):  # noqa: F811
    at, text = _render(data_dir, monkeypatch, screen, params)
    assert words in text, text[:600]
    if screen != 'proto:today':
        opts = [o for w in at.get('button_group') for o in w.options]
        assert 'Custom' in opts, opts
        # the choice from the address is kept in it (a link keeps the range) and the page's other keys are left alone
        for k, v in params.items():
            assert at.query_params.get(k) in (v, [v]), (k, at.query_params)
    else:
        assert at.date_input, 'Today has a day picker'


def test_today_takes_a_past_day_from_the_address(data_dir, monkeypatch):  # noqa: F811
    at, text = _render(data_dir, monkeypatch, 'proto:insiders', {})
    lo = at.date_input[0].min if at.date_input else None   # insiders has no date box until Custom
    assert lo is None
    at, text = _render(data_dir, monkeypatch, 'proto:today', {'day': '2026-06-15'})   # the fixture's filings: May to Oct 2026
    assert '(a past day)' in text and '15 Jun 2026' in text
    assert at.query_params.get('day') in ('2026-06-15', ['2026-06-15'])
    at, text = _render(data_dir, monkeypatch, 'proto:today', {'day': '2020-01-01'})   # before the data: its first day
    assert at.date_input[0].value == at.date_input[0].min


def test_custom_reveals_a_range_box_clamped_to_the_data(data_dir, monkeypatch):  # noqa: F811
    at, text = _render(data_dir, monkeypatch, 'proto:deals', {'from': '2020-01-01', 'to': '2030-01-01'})
    box = at.date_input[0]
    assert box.min >= date(2025, 10, 8) and box.value[0] == box.min and box.value[1] == box.max
    assert '(Custom)' in text or '(latest day)' in text
    # picking a preset clears the dates from the address and writes the preset
    seg = next(w for w in at.get('button_group') if 'Custom' in w.options)
    seg.set_value('all')
    at.run()
    assert not at.exception
    assert at.query_params.get('range') in ('all', ['all']) and 'from' not in at.query_params
