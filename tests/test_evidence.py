"""The verdict on a signal, from the measured summary (insiders_clean/evidence.py).
Numbers are the real 12 Oct 2026 measurements."""
import pandas as pd

from insiders_clean import evidence


def summary(**signals):
    rows = []
    for sig, per in signals.items():
        for horizon, (n, med, beat) in per.items():
            rows.append({'signal': sig, 'horizon': horizon, 'cases': n, 'median_excess': med, 'beat_index': beat})
    return pd.DataFrame(rows)


S = summary(
    cluster={'3M': (128, 2.99, 57.0), '6M': (115, 5.62, 61.7)},
    promoter_sell={'3M': (148, -4.64, 38.5), '6M': (106, -2.64, 48.1)},
    spotlight={'3M': (220, 0.10, 50.0), '6M': (186, -1.29, 48.9)},
    officer_buy={'3M': (26, 5.28, 69.2), '6M': (24, 25.4, 66.7)},
    fund_deal_buy={'3M': (666, -5.25, 41.6), '6M': (444, -6.45, 39.0)})


def test_a_signal_that_beat_the_index_on_both_horizons_leans_positive():
    v = evidence.verdict(S, 'cluster')
    assert v['kind'] == 'leaning_positive' and v['tone'] == 'buy'
    assert '+3.0% against Nifty 500 over 3 months (57% of 128 cases beat it), +5.6% over 6 months (115 cases)' in v['text']


def test_a_signal_that_lagged_is_a_drag():
    assert evidence.verdict(S, 'promoter_sell')['kind'] == 'drag'
    assert evidence.verdict(S, 'fund_deal_buy')['tone'] == 'sell'


def test_mixed_horizons_are_no_clear_edge():
    v = evidence.verdict(S, 'spotlight')
    assert v['kind'] == 'no_edge' and v['tone'] == 'mute'


def test_under_thirty_cases_is_too_few_even_when_the_return_is_large():
    v = evidence.verdict(S, 'officer_buy')
    assert v['kind'] == 'few' and '26 cases' in v['text']


def test_unmeasured_or_missing_summary():
    assert evidence.verdict(S, 'nothing')['kind'] == 'not_measured'
    assert evidence.verdict(None, 'cluster')['kind'] == 'not_measured'
    assert evidence.verdict(pd.DataFrame(), 'cluster')['kind'] == 'not_measured'


def test_six_month_row_with_few_cases_is_left_out_of_the_judgement():
    s = summary(x={'3M': (50, 2.0, 60.0), '6M': (10, -9.0, 30.0)})
    v = evidence.verdict(s, 'x')
    assert v['kind'] == 'leaning_positive' and '6 months' not in v['text']
