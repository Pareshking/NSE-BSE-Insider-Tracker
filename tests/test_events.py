import pandas as pd

from insiders_clean import events as evm


def _t(**kw):
    base = dict(is_primary=True, side='BUY', is_market=True, isin='X', broadcast_date='2026-02-03', value=100.0,
                trade_id='a', person_id='p1', broadcast_ts='2026-02-03 11:00')
    base.update(kw)
    return base


def test_tranches_combine_and_non_primary_non_market_are_excluded():
    t = pd.DataFrame([_t(), _t(trade_id='b', person_id='p2', value=50.0), _t(trade_id='c', is_primary=False),
                      _t(trade_id='d', is_market=False), _t(trade_id='e', side='SELL')])
    e = evm.insider_events(t, 'BUY')
    assert len(e) == 1 and e['value'][0] == 150.0 and e['n_people'][0] == 2 and e['n_filings'][0] == 2


def test_flag_text_false_is_not_true():
    t = pd.DataFrame([_t(is_market='False'), _t(trade_id='z', is_primary='False')])
    assert evm.insider_events(t, 'BUY').empty


def test_deals_net_direction_and_market_maker_excluded():
    d = pd.DataFrame([dict(is_primary=True, isin='X', date='2026-03-02', signed_value=500.0, value=500.0, client_is_market_maker=False),
                      dict(is_primary=True, isin='X', date='2026-03-02', signed_value=-200.0, value=200.0, client_is_market_maker=False),
                      dict(is_primary=True, isin='X', date='2026-03-02', signed_value=-9e6, value=9e6, client_is_market_maker=True)])
    e = evm.deal_events(d)
    assert len(e) == 1 and e['side'][0] == 'BUY' and e['net_value'][0] == 300.0


def test_holdout_split_by_disclosure_date():
    e = pd.DataFrame({'broadcast_date': pd.to_datetime(['2025-12-31', '2026-01-01', '2026-06-30', '2026-07-01'])})
    dev, hold = evm.split(e)
    assert len(dev) == 2 and len(hold) == 1


def test_prior_buys_and_drawdown():
    import numpy as np
    ev = pd.DataFrame({'isin': ['A', 'A', 'B'], 'broadcast_date': pd.to_datetime(['2026-01-05', '2026-01-20', '2026-01-20'])})
    pb = evm.prior_buys(ev)
    assert list(pb) == [0, 1, 0]
    idx = pd.bdate_range('2025-01-01', periods=300)
    close = pd.DataFrame({'A': np.r_[np.linspace(100, 200, 260), np.linspace(200, 120, 40)]}, index=idx)
    e2 = pd.DataFrame({'isin': ['A'], 'broadcast_date': [idx[-1]]})
    assert abs(evm.drawdown_at_signal(e2, close).iloc[0] - (120 / 200 - 1)) < 1e-6
    assert np.isnan(evm.drawdown_at_signal(pd.DataFrame({'isin': ['A'], 'broadcast_date': [idx[10]]}), close).iloc[0])
