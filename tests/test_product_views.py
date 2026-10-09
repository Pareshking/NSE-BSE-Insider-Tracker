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


def _acc():
    t = _mk([('A', '2026-02-02', 60e5, 'BUY'), ('A', '2026-04-20', 60e5, 'BUY'), ('A', '2026-05-25', 20e5, 'SELL'),
             ('B', '2026-05-01', 50e5, 'BUY'), ('C', '2026-05-02', 30e5, 'BUY')])
    return t, pv.promoter_absorption(t, '2026-06-01', min_value=1)


def _summary():
    return pd.DataFrame({'isin': ['A', 'B', 'C'], 'symbol': ['AA', 'BB', 'CC'], 'mcap_bucket': ['Micro', 'Small', 'Large'],
                         'pct_off_high': [-0.40, -0.10, -0.20]})


def test_screen_horizon_filters_and_purity():
    t, acc = _acc()
    camps = pv.active_campaigns(t, '2026-06-01')
    out = pv.screen(acc, _summary(), camps, '180D', min_net=25e5)
    assert list(out['isin']) == ['A', 'B', 'C'] and out.set_index('isin').at['A', 'net'] == 100e5
    assert list(pv.screen(acc, _summary(), camps, '180D', exclude_sellers=True)['isin']) == ['B', 'C']   # A sold in window
    assert list(pv.screen(acc, _summary(), camps, '180D', buckets=['Micro', 'Small'])['isin']) == ['A', 'B']
    assert list(pv.screen(acc, _summary(), camps, '180D', min_drawdown=0.15)['isin']) == ['A', 'C']
    assert list(pv.screen(acc, _summary(), camps, '180D', active_only=True)['isin']) == ['A']             # A: 2 buys 77 days apart, last 42d ago
    assert list(pv.screen(acc, _summary(), camps, 'Sustained')['isin']) == ['A', 'B', 'C']


def test_screen_works_without_price_summary():
    t, acc = _acc()
    out = pv.screen(acc, None, None, '90D', min_net=25e5)
    assert 'A' in set(out['isin']) and out['mcap_bucket'].isna().all() and not out['active'].any()


def test_campaign_status_and_365_boundary():
    t = _mk([('A', '2026-01-02', 30e5, 'BUY'), ('A', '2026-02-20', 30e5, 'BUY')])
    c = pv.active_campaigns(t, '2026-03-30')
    assert bool(c.at[0, 'active']) and c.at[0, 'campaign_buys'] == 2
    assert not bool(pv.active_campaigns(t, '2026-07-01').at[0, 'active'])        # last buy > 90 days before asof
    # data only starts 2026-01-01, so the 365-day window cannot reach back further than the data
    a = pv.promoter_absorption(t, '2026-12-31', min_value=1)
    assert a.at[0, 'net_365d'] == 60e5 and a.at[0, 'net_90d'] == 0


def test_badge_text_and_map():
    assert pv.badge_text(12.5e7, True) == '[Promoter Net: +₹12.50 Cr (180D) | Active Campaign | Contextual Accumulation]'
    t, _ = _acc()
    b = pv.accumulation_badges(t, '2026-06-01')
    assert 'Active Campaign' in b['A'] and 'Active Campaign' not in b['B']


def test_slim_price_summary_and_bucket():
    from insiders_clean import slim
    days = pd.bdate_range('2025-09-01', periods=300)
    close = pd.DataFrame({'A': range(100, 400), 'B': [50.0] * 300}, index=days).astype(float)
    close.iloc[-5:, 1] = float('nan')                                 # B stopped trading 5 sessions ago
    meta = pd.DataFrame({'isin': ['A', 'B'], 'symbol': ['AA', 'BB'], 'name': ['a', 'b'], 'exchange': ['NSE', 'NSE']})
    factors = pd.DataFrame({'isin': ['A'], 'date': [days[10]], 'factor': [0.5], 'kind': ['split_bonus'], 'exchange': ['NSE']})
    mc = pd.DataFrame({'symbol': ['AA', 'BB'], 'market_cap': [9e9, 1e9]})
    s = slim.price_summary(close, meta, factors, mc).set_index('isin')
    assert s.at['A', 'latest_close'] == 399 and s.at['A', 'high_52w'] == 399 and s.at['A', 'pct_off_high'] == 0
    assert s.at['B', 'latest_close'] == 50 and s.at['A', 'n_splits'] == 1 and s.at['A', 'last_split_factor'] == 0.5
    assert s.at['A', 'mcap_bucket'] == 'Large' and s.at['A', 'ret_90d'] > 0
    assert [slim.bucket(r) for r in (100, 101, 250, 251, 500, 501)] == ['Large', 'Mid', 'Mid', 'Small', 'Small', 'Micro']


def test_trade_table_columns_and_order():
    from insiders_clean import trade_table as tt
    t = _mk([('A', '2026-04-01', 50e5, 'BUY'), ('A', '2026-05-01', 90e5, 'SELL')])
    t['person_name'], t['mode_raw'], t['quantity'], t['price'], t['symbol'] = 'X Promoter', 'Market Purchase', 1000, 50.0, 'AA'
    out = tt.insider_rows(t)
    assert list(out['Value (₹ Cr)']) == [0.9, 0.5] and out.iloc[0]['Side'] == '🔴 Market Sell' and out.iloc[0]['Category'] == 'Promoter'
    assert list(out.columns)[:6] == ['Date', 'Symbol', 'Company', 'Traded By', 'Category', 'Mode']
    assert tt.insider_rows(t, 'ZZZ').empty


def test_deal_alignment_inside_campaign_window():
    t = _mk([('A', '2026-02-02', 60e5, 'BUY'), ('A', '2026-04-20', 60e5, 'BUY')])
    camps = pv.active_campaigns(t, '2026-06-01')
    d = pd.DataFrame([dict(isin='A', date='2026-03-10', is_primary=True, value=5e7, signed_value=5e7, client_is_market_maker=False),
                      dict(isin='A', date='2026-01-10', is_primary=True, value=9e7, signed_value=-9e7, client_is_market_maker=False)])
    out = pv.deal_alignment(d, camps, '2026-06-01').set_index('isin')
    assert out.at['A', 'deal_net'] == 5e7 and out.at['A', 'deal_days'] == 1 and bool(out.at['A', 'deal_coincides'])
