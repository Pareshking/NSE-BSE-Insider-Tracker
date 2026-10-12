"""Data checks from the 09 Oct brief (TODO 19): holdings arithmetic, implied
price against that day's range from our own price layer, disclosure dates,
holding-only disclosures. Filings are real NSE rows (conftest.py) with the
field under test changed; price rows are test values in the price layer's
own shape (insiders_clean/prices.py COLUMNS), not real prints."""
from __future__ import annotations

import io

import pandas as pd
from conftest import RUN_DATE, canonical

from insiders_clean import day_range, signals
from insiders_clean.insider import clean_insider

# Shreyasi Goenka's market buy in Zee (a real filing) is the template; each test changes one field.
ZEE_ISIN = 'INE256A01028'


def _base(real_nse_rows):
    return next(r for r in real_nse_rows if r['symbol'] == 'ZEEL' and r['acqName'] == 'Shreyasi Goenka')


def _prices(rows) -> bytes:
    """Rows (date, exchange, isin, series, low, high, volume) -> one month file of the price layer."""
    df = pd.DataFrame(rows, columns=['date', 'exchange', 'isin', 'series', 'low', 'high', 'volume'])
    df['date'] = pd.to_datetime(df['date'])
    for c in ('symbol', 'name', 'instrument_id'):
        df[c] = 'X'
    for c in ('open', 'close', 'last', 'prev_close', 'settle', 'value', 'trades'):
        df[c] = df['low']
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    return buf.getvalue()


def _ranges(rows_by_key: dict):
    ranges, info = day_range.load(rows_by_key.get, ['2026-08', '2026-09'])
    return ranges, info


ZEE_AUG = {
    'prices/daily/nse/2026-08.parquet': _prices([
        ('2026-08-20', 'NSE', ZEE_ISIN, 'EQ', 98.0, 104.0, 500000),
        ('2026-08-20', 'NSE', ZEE_ISIN, 'BE', 90.0, 99.0, 0),          # no trades that day: ignored
        ('2026-08-21', 'NSE', ZEE_ISIN, 'EQ', 101.0, 110.0, 400000),
    ]),
    'prices/daily/bse/2026-08.parquet': _prices([('2026-08-20', 'BSE', ZEE_ISIN, 'A', 97.5, 103.0, 20000)]),
}


def _one(real_nse_rows, master, calendar, report, ranges, **change):
    row = dict(_base(real_nse_rows), acqfromDt='2026-08-20', acqtoDt='2026-08-20', intimDt='2026-08-21',
               broadcastDt='24-Aug-2026 18:01:00', beforeSharesNo='6942048', afterSharesNo='7042048',
               buyQuantity='100000', buyValue='10000000')
    row.update(change)
    out = clean_insider(canonical('nse', 'insider_trading', [row]), master, calendar, report, RUN_DATE,
                        price_ranges=ranges)
    return out.iloc[0]


# --- price layer -> day ranges ---------------------------------------------------

def test_day_range_takes_both_exchanges_and_traded_series_only():
    ranges, info = _ranges(ZEE_AUG)
    d = ranges.set_index('date').loc[pd.Timestamp('2026-08-20')]
    assert (d['low'], d['high']) == (97.5, 104.0)   # BSE's low, NSE's high; the untraded BE row ignored
    assert info['months_read'] == 2 and info['last'] == '2026-08-21'
    assert 'prices/daily/nse/2026-09.parquet' in info['months_missing']


def test_unreadable_month_is_listed_not_raised():
    ranges, info = day_range.load({'prices/daily/nse/2026-08.parquet': b'not parquet'}.get, ['2026-08'])
    assert ranges is None and 'prices/daily/nse/2026-08.parquet' in info['months_unreadable']


# --- implied price -----------------------------------------------------------------

def test_price_inside_the_range_is_not_flagged(real_nse_rows, master, calendar, report):
    k = _one(real_nse_rows, master, calendar, report, _ranges(ZEE_AUG)[0])   # Rs.100 a share
    assert k['price_check'] == 'inside' and (k['day_low'], k['day_high']) == (97.5, 104.0)
    assert k['flags'] == '' and k['marks'] == ''


def test_value_filed_in_lakh_is_held_back_not_fixed(real_nse_rows, master, calendar, report):
    k = _one(real_nse_rows, master, calendar, report, _ranges(ZEE_AUG)[0], buyValue='100')  # Rs.100 lakh
    assert k['price_check'] == 'power_of_ten'
    assert 'value_off_by_power_of_ten' in k['flags'] and k['needs_review']
    assert k['value'] == 100   # as filed: nothing is corrected by guessing
    assert report.data['tables']['insider_trades']['data_checks']['price']['power_of_ten'] == {'5': 1}


def test_quantity_and_value_swapped(real_nse_rows, master, calendar, report):
    k = _one(real_nse_rows, master, calendar, report, _ranges(ZEE_AUG)[0], buyQuantity='10000000', buyValue='100000')
    assert k['price_check'] == 'swapped' and 'quantity_value_swapped' in k['flags']


def test_a_little_outside_is_marked_far_outside_is_held_back(real_nse_rows, master, calendar, report):
    ranges = _ranges(ZEE_AUG)[0]
    near = _one(real_nse_rows, master, calendar, report, ranges, buyValue='11000000')   # Rs.110 vs high 104
    assert near['price_check'] == 'above' and near['marks'] == 'price_outside_day_range'
    assert not near['needs_review']
    far = _one(real_nse_rows, master, calendar, report, ranges, buyValue='6000000')     # Rs.60 vs low 97.5
    assert far['price_check'] == 'far_below' and 'price_far_outside_day_range' in far['flags']
    assert report.data['tables']['insider_trades']['marked'] == {'price_outside_day_range': 1}


def test_trade_over_two_sessions_uses_both(real_nse_rows, master, calendar, report):
    k = _one(real_nse_rows, master, calendar, report, _ranges(ZEE_AUG)[0], acqtoDt='2026-08-21',
             intimDt='2026-08-24', buyValue='10800000')                                   # Rs.108: inside 21 Aug
    assert k['price_check'] == 'inside' and (k['day_low'], k['day_high']) == (97.5, 110.0)


def test_off_market_kinds_are_counted_never_flagged(real_nse_rows, master, calendar, report):
    k = _one(real_nse_rows, master, calendar, report, _ranges(ZEE_AUG)[0], modeOfAcquisition='ESOP',
             buyValue='1000000')                                                          # Rs.10 exercise price
    assert k['kind'] == 'esop' and k['price_check'] == 'far_below' and k['flags'] == ''
    by_kind = report.data['tables']['insider_trades']['data_checks']['price']['by_kind']
    assert by_kind['esop'] == {'far_below': 1}


def test_unchecked_rows_say_why(real_nse_rows, master, calendar, report):
    ranges = _ranges(ZEE_AUG)[0]
    assert _one(real_nse_rows, master, calendar, report, ranges, acqfromDt='2026-09-02', acqtoDt='2026-09-02',
                intimDt='2026-09-03', broadcastDt='03-Sep-2026 18:00:00')['price_check'] == 'after_price_layer'
    assert _one(real_nse_rows, master, calendar, report, None)['price_check'] == 'no_price_layer'
    # Zee did not trade on 21 Aug in this layer (suspended, or a gap): nothing to compare with.
    gap = {'prices/daily/nse/2026-08.parquet': _prices([('2026-08-20', 'NSE', ZEE_ISIN, 'EQ', 98.0, 104.0, 1),
                                                        ('2026-08-24', 'NSE', ZEE_ISIN, 'EQ', 98.0, 104.0, 1)])}
    assert _one(real_nse_rows, master, calendar, report, _ranges(gap)[0], acqfromDt='2026-08-21',
                acqtoDt='2026-08-21', intimDt='2026-08-24')['price_check'] == 'no_print'


# --- holdings arithmetic ------------------------------------------------------------

def test_buy_that_lowers_the_holding_is_held_back(real_nse_rows, master, calendar, report):
    k = _one(real_nse_rows, master, calendar, report, None, beforeSharesNo='7042048', afterSharesNo='6942048')
    assert k['holding_check'] == 'against_side'
    assert 'holding_moves_against_side' in k['flags'] and 'holding_change_differs_from_quantity' not in k['flags']


def test_holding_change_of_the_wrong_size_is_held_back(real_nse_rows, master, calendar, report):
    k = _one(real_nse_rows, master, calendar, report, None, afterSharesNo='7142048')
    assert k['holding_check'] == 'differs' and 'holding_change_differs_from_quantity' in k['flags']


def test_real_filings_all_match(real_nse_rows, master, calendar, report):
    out = clean_insider(canonical('nse', 'insider_trading', real_nse_rows), master, calendar, report, RUN_DATE)
    moved = out[out['holding_check'] != 'not_applicable']
    assert len(moved) and set(moved['holding_check']) == {'match'}
    assert not out['flags'].str.contains('against_side|disclosed_before|power_of_ten').any()


# --- disclosure dates ---------------------------------------------------------------

def test_disclosed_before_the_trade(real_nse_rows, master, calendar, report):
    k = _one(real_nse_rows, master, calendar, report, None, intimDt='2026-08-19')
    assert 'disclosed_before_trade' in k['flags'] and 'dates_out_of_order' not in k['flags']


def test_disclosure_dated_in_the_future(real_nse_rows, master, calendar, report):
    k = _one(real_nse_rows, master, calendar, report, None, intimDt='2036-02-03')   # as Premier Polyfilm filed
    assert 'disclosure_dated_in_future' in k['flags'] and k['needs_review']


# --- holding-only disclosures -------------------------------------------------------

def test_holding_only_disclosure_is_not_a_trade(real_nse_rows, master, calendar, report):
    # On appointment: no shares, no value, holding unchanged; NSE's parser
    # files the empty transaction type as 'Acquisition'.
    k = _one(real_nse_rows, master, calendar, report, None, buyQuantity='', buyValue='', afterSharesNo='6942048',
             transactionType='Acquisition', modeOfAcquisition='Market Purchase')
    assert k['kind'] == 'holding_only' and not k['is_market'] and k['side'] is None
    assert k['flags'] == ''
    assert signals.eligible(pd.DataFrame([k])).empty
    ho = report.data['tables']['insider_trades']['data_checks']['holding_only']
    assert ho['count'] == 1 and ho['filed_as'] == {'market': 1}


def test_market_trade_with_no_quantity_but_a_moved_holding_is_held_back(real_nse_rows, master, calendar, report):
    k = _one(real_nse_rows, master, calendar, report, _ranges(ZEE_AUG)[0], buyQuantity='', buyValue='')
    assert k['kind'] == 'market' and 'missing_quantity' in k['flags']
    assert k['price_check'] == 'no_price'


def test_pledge_with_no_quantity_keeps_its_kind(real_nse_rows, master, calendar, report):
    k = _one(real_nse_rows, master, calendar, report, None, buyQuantity='', buyValue='', afterSharesNo='6942048',
             modeOfAcquisition='Pledge Creation', transactionType='Pledge Creation')
    assert k['kind'] == 'pledge_create'


# --- pipeline -------------------------------------------------------------------------

def test_pipeline_notes_a_missing_price_layer(real_nse_rows):
    from insiders_clean.calendar import seed_state
    from insiders_clean.pipeline import run
    _, rep = run({('nse', 'insider_trading'): canonical('nse', 'insider_trading', real_nse_rows[:3])},
                 RUN_DATE, seed_state())
    assert any('price check not run' in n for n in rep['notes'])
    assert rep['tables']['insider_trades']['data_checks']['price']['price_layer'] is False


# --- Data page ------------------------------------------------------------------------

def test_data_page_shows_the_checks(real_nse_rows, master, calendar, report, tmp_path, monkeypatch, request):
    import json

    from streamlit.testing.v1 import AppTest
    from test_ui_pages import APP_PATHS
    _one(real_nse_rows, master, calendar, report, _ranges(ZEE_AUG)[0], buyValue='100')
    rep = dict(report.data, price_layer={'first': '2026-08-20', 'last': '2026-08-21'})
    (tmp_path / 'clean').mkdir()
    (tmp_path / 'clean' / 'report_local.json').write_text(json.dumps(rep, default=str))
    (tmp_path / 'clean' / 'latest.json').write_text(json.dumps({'date': RUN_DATE, 'report': 'local'}))
    monkeypatch.setenv('INSIDERS_LOCAL_DATA', str(tmp_path))
    import streamlit as st
    st.cache_data.clear()   # the site's readers cache by table name; never leak this folder to other tests
    request.addfinalizer(st.cache_data.clear)
    at = AppTest.from_string(APP_PATHS + """
from ui import theme
theme.inject()
from screens import data_status
data_status.render()
""", default_timeout=60)
    at.run()
    assert not at.exception, at.exception[0].value
    html = ' '.join(str(getattr(e, 'body', '')) for e in at.get('html'))
    assert 'Implied price inside the day' in html and '1 off by a power of ten' in html
    assert 'Holding-only disclosures' in html
