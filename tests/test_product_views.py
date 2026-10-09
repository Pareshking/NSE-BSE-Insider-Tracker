import pandas as pd

from insiders_clean import product_views as pv


def _trades():
    rows = []
    def add(isin, date, value, role='promoter', person='p1', side='BUY', pct=0.01):
        rows.append(dict(isin=isin, broadcast_date=pd.Timestamp(date), value=value, person_role=role, person_id=person, side=side,
                         is_market=True, is_primary=True, trade_id=f'{isin}{date}{person}', company='Co ' + isin, pct_of_mcap=pct))
    add('A', '2026-05-01', 30e5); add('A', '2026-05-20', 30e5)       # repeat within 30 days
    add('B', '2026-05-02', 10e5)                                      # under Rs 25 lakh
    add('C', '2026-05-03', 40e5, role='director', person='d')        # not a promoter
    add('S', '2026-05-04', 60e5, role='director', person='d', side='SELL')
    add('M', '2026-05-05', 5e5, pct=0.2)                              # small value but 0.2% of market cap
    add('R', '2026-05-06', 1e5, side='SELL'); add('R', '2026-05-10', 1e5, side='SELL'); add('R', '2026-05-12', 1e5, side='SELL')
    return pd.DataFrame(rows)


def test_freshness_age():
    f = pv.freshness({'x': (pd.DataFrame({'d': ['2026-10-01', '2026-10-05']}), 'd')}, today='2026-10-09')
    assert f.loc[0, 'age_days'] == 4 and f.loc[0, 'rows'] == 2


def _mk(rows):
    return pd.DataFrame([dict(trade_id=f'{i}', isin=i_, company=i_, broadcast_date=d, value=v, side=sd, person_role='promoter', person_id='p',
                              is_market=True, is_primary=True, pct_of_mcap=v / 1e9, exchange='NSE')
                         for i, (i_, d, v, sd) in enumerate(rows)])


def test_absorption_is_net_of_sales():
    t = _mk([('A', '2026-04-01', 50e5, 'BUY'), ('A', '2026-05-01', 40e5, 'SELL'), ('B', '2026-04-01', 50e5, 'BUY')])
    out = pv.promoter_absorption(t, '2026-06-01', min_value=25e5).set_index('isin')
    assert out.loc['B', 'net_90d'] == 50e5 and 'A' not in out.index          # A nets only 10 lakh
    assert out.loc['B', 'sustained'] and out.loc['B', 'net_365d'] == 50e5


def test_campaign_gap_89_joins_91_splits():
    t = _mk([('A', '2026-01-02', 30e5, 'BUY'), ('A', '2026-04-01', 30e5, 'BUY')])   # 89 days
    assert len(pv.campaigns(t, '2026-06-01', min_value=0)) == 1
    t = _mk([('A', '2026-01-02', 30e5, 'BUY'), ('A', '2026-04-03', 30e5, 'BUY')])   # 91 days
    assert len(pv.campaigns(t, '2026-06-01', min_value=0)) == 2


def test_selling_windows():
    t = _mk([('S', '2026-01-10', 60e5, 'SELL'), ('S', '2026-05-20', 10e5, 'BUY')])
    out = pv.promoter_selling(t, '2026-06-01').iloc[0]
    assert out['sold_365d'] == 50e5 and out['sold_90d'] == -10e5
