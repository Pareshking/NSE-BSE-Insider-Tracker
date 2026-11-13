import pandas as pd

from insiders_clean import units


def test_percent_columns_in_range_pass():
    df = pd.DataFrame({'post_stake_pct': [3.32, 44.45, 100.0], 'percent_equity_traded': [-23.08, 0.61, 3.0], 'name': ['a', 'b', 'c']})
    assert units.check(df) == {}


def test_out_of_range_and_fractions_are_named():
    df = pd.DataFrame({'post_stake_pct': [3.3, 140.0] + [5.0] * 60, 'promoter_holding_pct': [0.41, 0.52] * 31,
                       'percent_equity_traded': [-150.0] + [1.0] * 61, 'encumbered_pct': ['     0.79'] * 62})
    out = units.check(df)
    assert out['post_stake_pct'] == {'out_of_range': 1, 'looks_like_fractions': False}
    assert out['promoter_holding_pct']['looks_like_fractions'] is True
    assert out['percent_equity_traded']['out_of_range'] == 1
    assert out['encumbered_pct']['looks_like_fractions'] is True   # text with leading spaces is read as a number


def test_small_true_percents_are_not_fractions():
    assert units.check(pd.DataFrame({'employee_trust_pct': [0.0, 0.1, 0.3] * 30})) == {}
