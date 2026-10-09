import numpy as np
import pandas as pd
import pytest

from insiders_clean import ledger as lg


def _trades():
    r = lambda d, v, role='promoter': dict(isin='A', broadcast_date=pd.Timestamp(d), value=v, person_role=role, person_id='p', side='BUY',  # noqa: E731
                                           is_market=True, is_primary=True, trade_id=f'{d}{v}', pct_of_mcap=0.1)
    return pd.DataFrame([r('2026-06-29', 50e5), r('2026-07-02', 30e5), r('2026-07-03', 10e5), r('2026-07-06', 30e5, 'director')])


def test_new_signals_only_post_june_promoter_material():
    s = lg.new_signals(_trades())
    assert list(pd.to_datetime(s['broadcast_date']).dt.strftime('%Y-%m-%d')) == ['2026-07-02']
    assert s['signal_id'].iloc[0] == lg.signal_id('A', '2026-07-02')


def test_append_only_keeps_rows_and_refuses_edits():
    base = pd.DataFrame([dict(signal_id='s1', isin='A', entry_date=pd.Timestamp('2026-07-03'), entry_price=10.0)])
    new = pd.DataFrame([dict(signal_id='s1', isin='A', entry_date=pd.Timestamp('2026-07-03'), entry_price=10.0),
                        dict(signal_id='s2', isin='B', entry_date=pd.Timestamp('2026-07-04'), entry_price=5.0)])
    out = lg.append_only(base, new)
    assert list(out['signal_id']) == ['s1', 's2']
    with pytest.raises(ValueError):
        lg.append_only(base, new.assign(entry_price=[11.0, 5.0]))


def test_mark_returns_to_date_and_matured_horizon():
    idx = pd.bdate_range('2026-07-01', periods=70)
    close = pd.DataFrame({'A': np.linspace(100, 170, 70)}, index=idx)
    nifty = pd.Series(np.linspace(1000, 1070, 70), index=idx)
    led = pd.DataFrame([dict(signal_id='s', isin='A', entry_date=idx[0], entry_basis='close', entry_price=100.0)])
    m = lg.mark(led, close, close, nifty)
    assert abs(m['return_to_date'][0] - 0.7) < 1e-9 and abs(m['excess_to_date_vs_nifty500'][0] - (0.7 - 0.07)) < 1e-9
    assert abs(m['ret_60'][0] - (close['A'].iloc[60] / 100 - 1)) < 1e-9
    assert np.isnan(m['ret_120'][0]) and m['sessions_since_entry'][0] == 69
