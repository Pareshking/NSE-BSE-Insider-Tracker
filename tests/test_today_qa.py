"""Today as questions and answers (streamlit_app/screens/proto.py today_headline)."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'streamlit_app'))


def test_headline_names_the_block_that_is_most_of_the_selling():
    from screens.proto import today_headline
    d = pd.DataFrame([
        {'side': 'BUY', 'isin': 'A', 'company': 'Control Print', 'value': 14.5e7, 'pct_of_company': 1.49},
        {'side': 'BUY', 'isin': 'H', 'company': 'Havells', 'value': 125.6e7, 'pct_of_company': 0.17},
        {'side': 'SELL', 'isin': 'F', 'company': 'Happy Forgings', 'value': 597.65e7, 'pct_of_company': 3.44},
        {'side': 'SELL', 'isin': 'G', 'company': 'Gallantt', 'value': 182.6e7, 'pct_of_company': 1.24}])
    head, sub = today_headline(d, {})
    assert 'three quarters of the selling is Happy Forgings' in head
    assert 'Control Print, 1.49% of the company' in sub and 'The largest in rupees: Havells' in sub


def test_headline_with_nothing_past_the_bar():
    from screens.proto import today_headline
    assert today_headline(pd.DataFrame(), {})[0].startswith('No promoter or director decision')


def test_results_rows_that_cannot_be_right_are_held_back():
    from insiders_clean.results import doubt_reason
    assert doubt_reason(-27.71e7, 1e7, 1e7, 5.0) == 'negative revenue'
    assert doubt_reason(29e7, 1e7, 6306e7, 10.0) == 'year-ago profit over 3x revenue'
    assert doubt_reason(50.59e7, 1092e7, 5e7, 10.0) == 'profit over 3x revenue'
    assert doubt_reason(1.47e5, 0, 1e5, -100.0) == 'revenue fell to almost nothing'
    assert doubt_reason(100e7, 10e7, 8e7, 12.0) == ''


def test_sast_action_label():
    from screens.proto import sast_action
    assert sast_action(float('nan'), 'Acquisition', 'Preferential Allotment')[0] == 'Allotted'
    assert sast_action(2.1, None, 'Open Market') == ('Bought', 'up')
    assert sast_action(-1.0, None, 'Open Market') == ('Sold', 'dn')
    assert sast_action(None, 'Sale', 'Others')[0] == 'Sold'


def test_many_clients_at_one_price_are_one_block():
    from screens.proto import club_blocks
    base = dict(date=pd.Timestamp('2026-11-18'), isin='INE530B01024', company='IIFL', sym='IIFL', side='BUY', price=617.0,
                pct=0.5, feed='block', ex='bse', n=1, kind='', who='')
    rows = [dict(base, _v=v, qty=1, client=c) for c, v in (('SBI MF', 503e7), ('Rimco', 375e7), ('Nippon MF', 275e7), ('X', 1e7))]
    rows.append(dict(base, _v=6776e7, side='SELL', client='Fih Mauritius', qty=1))
    out = club_blocks(rows)
    assert len(out) == 2
    blk = next(r for r in out if r['side'] == 'BUY')
    assert blk['_v'] == 1154e7 and 'SBI MF' in blk['who'] and '+1 more' in blk['who'] and '4 buyers' in blk['kind']


def test_names_list_says_each_name_once():
    from screens.proto import _names_list
    assert _names_list(['Happy Forgings', 'Happy Forgings', 'Azad Engineering'], 3) == 'Happy Forgings and Azad Engineering'
