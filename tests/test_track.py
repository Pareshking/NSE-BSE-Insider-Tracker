import numpy as np
import pandas as pd

from insiders_clean import track


def panel(n=200):
    days = pd.bdate_range('2026-01-01', periods=n)
    close = pd.DataFrame({'A': np.linspace(100, 199, n), 'B': np.full(n, 50.0)}, index=days)
    index = pd.Series(np.full(n, 1000.0), index=days)
    return close, index


def test_entry_is_the_close_of_the_session_after_the_day_made_public():
    close, index = panel()
    day = close.index[10]
    ev = pd.DataFrame({'isin': ['A'], 'day': [day], 'signal': ['promoter_buy'], 'value': [1e7]})
    fr = track.forward_returns(ev, close, index)
    assert fr['entry_date'].iloc[0] == close.index[11]
    e0, e1 = close['A'].iloc[11], close['A'].iloc[11 + 21]
    assert abs(fr['ret_1M'].iloc[0] - ((e1 / e0 - 1) * 100 - track.COST_PCT)) < 1e-9
    assert abs(fr['excess_1M'].iloc[0] - fr['ret_1M'].iloc[0]) < 1e-9  # flat index


def test_incomplete_windows_are_not_counted():
    close, index = panel(60)
    ev = pd.DataFrame({'isin': ['B'], 'day': [close.index[40]], 'signal': ['promoter_buy'], 'value': [1e7]})
    fr = track.forward_returns(ev, close, index)
    assert np.isfinite(fr['ret_1W'].iloc[0]) and np.isnan(fr['ret_1M'].iloc[0]) and np.isnan(fr['ret_6M'].iloc[0])
    s = track.summary(fr)
    assert s.loc[s['horizon'] == '1M', 'cases'].iloc[0] == 0


def test_a_run_of_tranches_is_one_event():
    close, _ = panel()
    d = close.index
    ev = pd.DataFrame({'isin': ['A'] * 4, 'day': [d[5], d[8], d[20], d[30]], 'signal': 'x', 'value': 1e7})
    kept = track._space(ev, d)
    assert list(kept['day']) == [d[5], d[30]]
