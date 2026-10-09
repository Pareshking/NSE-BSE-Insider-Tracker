import numpy as np
import pandas as pd

from insiders_clean import evaluate as ev

DAYS = pd.bdate_range('2026-01-01', periods=40)


def _panels(n_peers=3):
    close = pd.DataFrame(100.0, index=DAYS, columns=['A'] + [f'P{i}' for i in range(n_peers)])
    close['A'] = 100.0 * np.cumprod(np.r_[1.0, np.full(len(DAYS) - 1, 1.01)])
    return close, close.mul(0.99)


def _events(**kw):
    base = {'isin': 'A', 'broadcast_date': DAYS[10], 'broadcast_ts': DAYS[10] + pd.Timedelta(hours=10)}
    base.update(kw)
    return pd.DataFrame([base])


def test_morning_disclosure_enters_same_close_afternoon_enters_next_open():
    close, op = _panels()
    early = ev.forward_returns(_events(), close, op, horizons=(5,))
    late = ev.forward_returns(_events(broadcast_ts=DAYS[10] + pd.Timedelta(hours=16)), close, op, horizons=(5,))
    assert early['entry_basis'][0] == 'close' and early['entry_pos'][0] == 10
    assert abs(early['ret_5'][0] - (1.01 ** 5 - 1)) < 1e-9
    assert late['entry_basis'][0] == 'open' and late['entry_pos'][0] == 11
    assert abs(late['ret_5'][0] - (close.iloc[16, 0] / op.iloc[11, 0] - 1)) < 1e-9


def test_no_time_of_day_defaults_to_next_open_and_conservative_uses_close():
    close, op = _panels()
    e = _events(broadcast_ts=pd.NaT)
    a = ev.forward_returns(e, close, op, horizons=(5,))
    b = ev.forward_returns(e, close, op, horizons=(5,), conservative=True)
    assert a['entry_basis'][0] == 'open' and b['ret_5'][0] < a['ret_5'][0]


def test_incomplete_window_is_not_counted_and_weekend_disclosure_rolls_forward():
    close, op = _panels()
    r = ev.forward_returns(_events(broadcast_date=DAYS[37], broadcast_ts=pd.NaT), close, op, horizons=(1, 5))
    assert not np.isnan(r['ret_1'][0]) and np.isnan(r['ret_5'][0])
    sat = pd.Timestamp('2026-01-10')
    r2 = ev.forward_returns(_events(broadcast_date=sat, broadcast_ts=sat + pd.Timedelta(hours=9)), close, op, horizons=(1,))
    assert r2['entry_pos'][0] == DAYS.searchsorted(pd.Timestamp('2026-01-12'))


def test_index_returns_and_excess():
    close, op = _panels()
    r = ev.forward_returns(_events(), close, op, horizons=(5,))
    idx = pd.Series(np.linspace(100, 110, len(close.index)), index=close.index)
    bm = ev.index_returns(idx, close.index, r['entry_pos'], r['entry_basis'], horizons=(5,))
    pos = int(r['entry_pos'][0])
    start = pos - 1 if r['entry_basis'][0] == 'open' else pos
    assert abs(bm['bm_5'][0] - (idx.iloc[pos + 5] / idx.iloc[start] - 1)) < 1e-12
    out = ev.excess(r, bm, horizons=(5,))
    assert abs(out['ex_5'][0] - (r['ret_5'][0] - bm['bm_5'][0])) < 1e-12
    gap = idx.copy(); gap.iloc[pos + 5] = np.nan
    assert np.isnan(ev.index_returns(gap, close.index, r['entry_pos'], r['entry_basis'], horizons=(5,))['bm_5'][0])


def test_summary_clusters_by_date_and_reports_n():
    df = pd.DataFrame({'broadcast_date': pd.to_datetime(['2026-01-02'] * 3 + ['2026-01-05', '2026-01-06']),
                       'ar_5': [0.02, 0.02, 0.02, -0.01, 0.03]})
    s = ev.summarise(df, 'ar_5')
    assert s['n'] == 5 and s['clusters'] == 3 and s['hit_rate'] == 0.8 and s['ci95'][0] <= s['mean'] <= s['ci95'][1]
    assert ev.summarise(df.iloc[0:0], 'ar_5') == {'n': 0}
    assert abs(ev.mde(0.1, 100) - 0.028) < 1e-9


def test_price_panel_prefers_nse_and_fills_with_bse():
    px = pd.DataFrame({'date': pd.to_datetime(['2026-01-01'] * 3 + ['2026-01-02']), 'exchange': ['NSE', 'BSE', 'BSE', 'BSE'],
                       'isin': ['X', 'X', 'Y', 'X'], 'close': [10.0, 11.0, 5.0, 12.0], 'value': [1.0, 2.0, 1.0, 1.0]})
    p = ev.price_panel(px, 'close')
    assert p.loc['2026-01-01', 'X'] == 10.0 and p.loc['2026-01-02', 'X'] == 12.0 and p.loc['2026-01-01', 'Y'] == 5.0
