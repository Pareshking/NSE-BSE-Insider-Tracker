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


def test_size_matched_excess_and_move_before_the_filing():
    close, index = panel()
    d = close.index
    small = pd.Series(np.linspace(1000, 1100, len(d)), index=d)
    ev = pd.DataFrame({'isin': ['A'], 'day': [d[20]], 'signal': ['promoter_buy'], 'value': [1e7],
                       'trade_date_to': [d[17]]})
    fr = track.forward_returns(ev, close, index, {'Nifty Smallcap 250': small}, {'A': 'Small'})
    p, q = 21, 21 + 21
    expect = fr['ret_1M'].iloc[0] - (small.iloc[q] / small.iloc[p] - 1) * 100
    assert abs(fr['excess_sm_1M'].iloc[0] - expect) < 1e-9
    assert abs(fr['pre_move'].iloc[0] - (close['A'].iloc[20] / close['A'].iloc[17] - 1) * 100) < 1e-9
    assert fr['lag_sessions'].iloc[0] == 3


def test_forward_ledger_appends_only_new_recent_events():
    days = pd.bdate_range('2026-09-01', periods=30)
    close = pd.DataFrame({'A': np.linspace(100, 130, 30), 'B': np.linspace(50, 40, 30)}, index=days)
    ev = pd.DataFrame({'signal': ['promoter_buy', 'promoter_buy', 'cluster'], 'isin': ['A', 'B', 'A'],
                       'day': [days[-1], days[-20], days[-2]], 'value': [3e6, 4e6, np.nan]})
    run = pd.Timestamp('2026-10-12 19:00')
    first = track.new_ledger_rows(ev, pd.DataFrame(), close, run)
    assert set(zip(first['signal'], first['isin'])) == {('promoter_buy', 'A'), ('cluster', 'A')}  # B is too old to be "firing now"
    assert (first['rules_version'] == track.RULES_VERSION).all() and (first['recorded_at'] == run).all()
    assert first.loc[first['signal'] == 'promoter_buy', 'close_at_record'].iloc[0] == 130
    again = track.new_ledger_rows(ev, first, close, run + pd.Timedelta(days=1))
    assert again.empty  # already recorded: never written twice
    fr = track.forward_returns(first.assign(day=pd.to_datetime(first['day'])), close, close['A'])
    assert 'recorded_at' in fr and 'excess_1W' in fr  # outcomes keep the stamped row


def test_model_basket_rules():
    from insiders_clean import basket
    days = pd.bdate_range('2026-01-01', periods=100)
    close = pd.DataFrame({'A': np.linspace(100, 150, 100), 'B': np.linspace(100, 80, 100), 'C': 100.0}, index=days)
    led = pd.DataFrame({'signal': ['cluster', 'cluster', 'promoter_buy', 'cluster', 'cluster'],
                        'isin': ['A', 'A', 'B', 'C', 'B'],
                        'day': [days[0], days[5], days[10], days[2], days[3]],
                        'recorded_at': days[[0, 5, 10, 2, 3]],
                        'evidence': ['leaning_positive', 'leaning_positive', 'no_edge', 'leaning_positive', 'leaning_positive'],
                        'trade_flags': ['', '', '', '', 'T2T,5% band']})
    pos = basket.positions(led, close)
    assert list(pos['isin']) == ['A', 'C']        # A once (already held), B no edge or flagged
    a = pos[pos['isin'] == 'A'].iloc[0]
    assert a['status'] == 'closed' and a['entry_date'] == days[1] and a['exit_date'] == days[1 + basket.HOLD_SESSIONS]
    assert abs(a['ret'] - ((close['A'].iloc[64] / close['A'].iloc[1] - 1) * 100 - track.COST_PCT)) < 1e-9
    nav = basket.nav(pos, close, close['C'])
    assert nav['basket'].iloc[-1] > 100 and (nav['index'] == 100).all()
    assert basket.positions(led.drop(columns='evidence'), close).empty  # unstamped rows never open


def test_universe_judged_on_the_event_day():
    ev = pd.DataFrame({'isin': ['A', 'A', 'B', 'C'], 'day': pd.to_datetime(['2026-01-10', '2026-06-10', '2026-03-01', '2026-03-01'])})
    hist = pd.DataFrame({'date': pd.to_datetime(['2026-01-09', '2026-06-09', '2026-02-27']), 'isin': ['A', 'A', 'B'],
                         'market_cap': [80e7, 150e7, 120e7]})
    keep = track.universe_on_day(ev, hist, {'C': 300e7, 'A': 500e7}, 100e7)
    assert list(keep) == [False, True, True, True]   # A small then big; B big; C not on NSE, BSE's latest used
