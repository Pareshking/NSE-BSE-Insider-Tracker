"""ui/charts.py: each builder gives a chart spec for good data and nothing for no data; theme colours only."""
from __future__ import annotations

import json
import sys

import pandas as pd

from conftest import ROOT

sys.path.insert(0, str(ROOT / 'streamlit_app'))

from ui import charts  # noqa: E402
from ui.theme import COLORS  # noqa: E402


def _spec(chart) -> dict:
    return chart.to_dict()


def _colours(spec: dict) -> set:
    text = json.dumps(spec)
    return {c for c in COLORS.values() if c in text}


def test_diverging_bar_sorts_added_over_cut_and_writes_each_value():
    df = pd.DataFrame({'company': ['ITC', 'HDFC Bank', 'Infosys', 'Flat Co', 'No Data'],
                       'pct_change': [0.42, -1.09, 2.30, 0.0, None], 'tag': [None, None, 'new', None, None]})
    spec = _spec(charts.diverging_bar(df, 'company', 'pct_change', tag='tag'))
    rows = next(iter(spec['datasets'].values()))
    assert [r['_l'] for r in rows] == ['Infosys', 'ITC', 'HDFC Bank']          # zero and blank left out, largest added first
    assert [r['_t'] for r in rows] == ['+2.30 pts new', '+0.42 pts', '-1.09 pts']
    assert [r['_tone'] for r in rows] == ['up', 'up', 'down']
    assert {COLORS['buy'], COLORS['sell']} <= _colours(spec)
    assert 'legend' not in json.dumps(spec) or '"legend": null' in json.dumps(spec)


def test_diverging_bar_in_rupees_keeps_the_largest_and_repeats_no_label():
    df = pd.DataFrame({'company': ['A'] * 3 + [f'C{i}' for i in range(20)],
                       'net': [5e8, -3e8, 1e7] + [1e6 * (i + 1) for i in range(20)]})
    spec = _spec(charts.diverging_bar(df, 'company', 'net', fmt=lambda v: charts.rupees(v, signed=True), limit=5))
    rows = next(iter(spec['datasets'].values()))
    assert len(rows) == 5 and rows[0]['_l'] == 'A' and rows[-1]['_l'] == 'A (2)'
    assert rows[0]['_t'].startswith('+₹') and rows[-1]['_t'].startswith('−₹')


def test_diverging_bar_with_nothing_to_draw():
    assert charts.diverging_bar(None, 'company', 'x') is None
    assert charts.diverging_bar(pd.DataFrame(), 'company', 'x') is None
    assert charts.diverging_bar(pd.DataFrame({'company': ['A'], 'x': [0.0]}), 'company', 'x') is None
    assert charts.diverging_bar(pd.DataFrame({'company': ['A']}), 'company', 'x') is None


def test_buy_sell_split_one_bar_with_both_totals():
    spec = _spec(charts.buy_sell_split(3e9, 1e9))
    text = json.dumps(spec, ensure_ascii=False)
    assert 'Bought ₹300.00 Cr · 75%' in text and 'Sold ₹100.00 Cr · 25%' in text
    assert {COLORS['buy'], COLORS['sell']} <= _colours(spec)
    assert charts.buy_sell_split(2e8, 0) is not None            # bought only: still a bar
    assert charts.buy_sell_split(0, 0) is None and charts.buy_sell_split(None, float('nan')) is None


def test_holding_trend_one_company_and_small_multiples():
    one = pd.DataFrame({'company': ['ITC', 'ITC'], 'quarter_end': ['2026-06-30', '2026-09-30'], 'pct_of_company': [1.5, 1.2]})
    spec = _spec(charts.holding_trend(one))
    rows = next(iter(spec['datasets'].values()))
    assert [r['_q'] for r in rows] == ['Jun 26', 'Sep 26'] and {r['_tone'] for r in rows} == {'down'}
    assert 'facet' not in spec
    many = pd.DataFrame({'company': ['A', 'A', 'B', 'B', 'C'], 'quarter_end': ['2026-06-30', '2026-09-30'] * 2 + ['2026-09-30'],
                         'pct_of_company': [1.1, 2.0, 3.0, 3.0, 4.0]})
    spec = _spec(charts.holding_trend(many))
    assert 'facet' in spec and spec['facet']['field'] == '_s'
    tones = {r['_l']: r['_tone'] for r in next(iter(spec['datasets'].values()))}
    assert tones == {'A': 'up', 'B': 'flat', 'C': 'flat'}


def test_holding_trend_with_nothing_to_draw():
    assert charts.holding_trend(None) is None
    assert charts.holding_trend(pd.DataFrame(columns=['company', 'quarter_end', 'pct_of_company'])) is None
    assert charts.holding_trend(pd.DataFrame({'company': ['A'], 'quarter_end': [None], 'pct_of_company': [1.0]})) is None


def test_count_strip_shows_zero_and_nothing_when_unknown():
    html = charts.count_strip(4, 0, 2, 1)
    assert '▲ 4</b> added' in html and 'class="cs zero"><b>▼ 0</b> cut' in html and '+ 2</b> new' in html and '− 1</b> exited' in html
    assert charts.count_strip() == ''


def test_change_rows_marks_each_change():
    rows = pd.DataFrame({'company': ['ITC', 'HDFC', 'New Co', 'Gone Co', 'Only'], 'symbol': ['ITC', 'HDFCBANK', 'NEW', 'GONE', 'ONE'],
                         'pct_of_company': [2.0, 1.5, 1.2, None, 3.0], 'pct_change': [0.42, -1.09, 1.2, -1.1, None],
                         'change': ['added', 'cut', 'new', 'exited', 'no_previous'], 'sub': ['Mutual fund', '', '', '', '']})
    html = charts.change_rows(rows, sub='sub')
    assert '▲ 0.42' in html and '▼ 1.09' in html and '+ new' in html and '− exited' in html and 'one quarter' in html
    assert '/company?symbol=ITC' in html and 'Mutual fund' in html
    assert charts.change_rows(pd.DataFrame()) == '' and charts.change_rows(None) == ''
