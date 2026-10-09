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


def _v2_trades(rows):
    import pandas as pd
    return pd.DataFrame([dict(trade_id=f'{i}', isin=i_, company=i_, broadcast_date=pd.Timestamp(d), broadcast_ts=pd.Timestamp(d) + pd.Timedelta(hours=10),
                              value=v, side=sd, person_role='promoter', person_id='p', is_market=True, is_primary=True, pct_of_mcap=0.01)
                         for i, (i_, d, v, sd) in enumerate(rows)])


def test_campaign_signal_fires_at_second_buy_net_of_sales():
    t = _v2_trades([('A', '2026-07-06', 20e5, 'BUY'), ('A', '2026-08-20', 20e5, 'BUY'),            # 45 days apart: confirms at 40L net
                    ('B', '2026-07-06', 30e5, 'BUY'),                                              # single buy: no campaign signal
                    ('C', '2026-07-06', 20e5, 'BUY'), ('C', '2026-08-01', 20e5, 'SELL'), ('C', '2026-08-20', 20e5, 'BUY'),   # net 20L: not yet
                    ('D', '2026-07-06', 30e5, 'BUY'), ('D', '2026-10-20', 30e5, 'BUY')])           # 106-day gap: two campaigns of one buy
    s = lg.new_campaign_signals(t).set_index('isin')
    assert list(s.index) == ['A'] and s.at['A', 'value'] == 40e5 and s.at['A', 'campaign_buys'] == 2
    assert str(s.at['A', 'broadcast_date'])[:10] == '2026-08-20' and str(s.at['A', 'campaign_start'])[:10] == '2026-07-06'


def test_campaign_signal_waits_for_net_threshold_and_ignores_june():
    t = _v2_trades([('C', '2026-07-06', 20e5, 'BUY'), ('C', '2026-08-01', 20e5, 'SELL'), ('C', '2026-08-20', 20e5, 'BUY'),
                    ('C', '2026-09-15', 20e5, 'BUY'),                                              # net 40L-20L... = 40L at the third buy
                    ('J', '2026-06-20', 50e5, 'BUY'), ('J', '2026-06-25', 50e5, 'BUY')])           # before the hold-out start
    s = lg.new_campaign_signals(t)
    assert list(s['isin']) == ['C'] and str(s.iloc[0]['broadcast_date'])[:10] == '2026-09-15' and s.iloc[0]['value'] == 40e5


def test_campaign_id_stable_and_distinct_from_v1():
    t = _v2_trades([('A', '2026-07-06', 20e5, 'BUY'), ('A', '2026-08-20', 20e5, 'BUY')])
    a, b = lg.new_campaign_signals(t), lg.new_campaign_signals(t)
    assert a.iloc[0]['signal_id'] == b.iloc[0]['signal_id']
    assert lg.signal_id('A', '2026-07-06') != lg.signal_id('A', '2026-07-06', lg.RULE_V2)
