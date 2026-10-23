"""The company snapshot (insiders_clean/snapshot.py): market line, ownership and its change, insider flows."""
import numpy as np
import pandas as pd

from insiders_clean import snapshot

REF = pd.Timestamp('2026-10-19')
A, B, C = 'INE000A01011', 'INE000B01011', 'INE000C01011'


def summary():
    return pd.DataFrame({'isin': [A, B, C], 'symbol': ['AAA', 'BBB', 'CCC'], 'name': ['AAA LTD', 'BBB LTD', 'CCC LTD'],
                         'last_date': [REF] * 3, 'latest_close': [150.0, 90.0, 40.0], 'high_52w': [200.0, 100.0, 40.0],
                         'low_52w': [100.0, 50.0, 40.0], 'pct_off_high': [-0.25, -0.1, 0.0], 'ret_90d': [0.05, -0.02, 0.0],
                         'market_cap': [5e11, 2e11, 9e9], 'mcap_bucket': ['Large', 'Mid', 'Micro']})


def holdings():
    q = pd.to_datetime
    return pd.DataFrame({
        'isin': [A, A, A, B, B, C],
        'quarter_end': q(['2026-03-31', '2026-06-30', '2026-09-30', '2025-09-30', '2026-09-30', '2026-09-30']),
        'promoter_holding_pct': [50.0, 50.5, 51.0, 40.0, 41.0, 60.0],
        'promoter_pledge_pct': [10.0, 9.0, np.nan, 5.0, 5.0, 0.0],        # A's newest quarter has no pledge figure yet
        'mf_pct': [3.0, 3.5, 4.5, 8.0, 9.0, np.nan],
        'fpi_pct': [20.0, 19.0, 18.0, 10.0, 10.0, np.nan]})


def trade(isin, person, role, side, value, day, token=False):
    return {'isin': isin, 'company': 'X', 'nse_symbol': 'X', 'person_id': person.lower(), 'person_name': person, 'person_role': role,
            'side': side, 'quantity': 1, 'price': value, 'value': value, 'signed_value': value if side == 'BUY' else -value,
            'pct_of_mcap': 0.1, 'market_cap': 5e11, 'seen': pd.Timestamp(day), 'trade_date_to': pd.Timestamp(day) - pd.Timedelta(days=1),
            'trade_date_from': pd.Timestamp(day) - pd.Timedelta(days=1), 'is_token': token, 'is_market': True, 'is_primary': True,
            'needs_review': False, 'broadcast_date': pd.Timestamp(day)}


def trades():
    return pd.DataFrame([
        trade(A, 'Vama Sundari', 'promoter_group', 'BUY', 40e7, '2026-10-05'),
        trade(A, 'Vama Sundari', 'promoter_group', 'BUY', 20e7, '2026-06-01'),          # outside 90 days: counts for the date only
        trade(A, 'Dee Director', 'director', 'SELL', 5e7, '2026-10-10'),
        trade(A, 'Emp One', 'designated_person', 'SELL', 90e7, '2026-10-12'),           # never a decision-maker
        trade(B, 'Tiny Promoter', 'promoter', 'BUY', 1e6, '2026-10-14', token=True),    # a token buy is not buying
        trade(B, 'Kay Kmp', 'kmp', 'BUY', 3e7, '2026-10-15')])


def build(**kw):
    return snapshot.build(summary(), holdings(), trades(), ref=REF, **kw).set_index('isin')


def test_one_row_per_company_with_the_fixed_columns_largest_market_cap_first():
    out = snapshot.build(summary(), holdings(), trades(), ref=REF)
    assert list(out.columns) == snapshot.COLUMNS
    assert out['isin'].tolist() == [A, B, C] and out['market_cap'].is_monotonic_decreasing and out['isin'].is_unique


def test_market_line_and_where_the_close_sits_in_the_52_week_range():
    out = build()
    assert out.loc[A, 'latest_close'] == 150.0 and out.loc[A, 'mcap_bucket'] == 'Large' and out.loc[A, 'company'] == 'AAA LTD'
    assert out.loc[A, 'range_pos'] == 50.0 and abs(out.loc[B, 'range_pos'] - 80.0) < 1e-9
    assert np.isnan(out.loc[C, 'range_pos'])                  # a flat range says nothing
    assert snapshot.build(summary(), names={A: 'Display A'}, ref=REF).set_index('isin').loc[A, 'company'] == 'Display A'


def test_ownership_is_the_latest_figure_and_its_change_from_the_quarter_before():
    out = build()
    assert out.loc[A, 'promoter'] == 51.0 and abs(out.loc[A, 'promoter_change_pts'] - 0.5) < 1e-9
    assert abs(out.loc[A, 'mf_change_pts'] - 1.0) < 1e-9 and abs(out.loc[A, 'fpi_change_pts'] + 1.0) < 1e-9
    assert out.loc[A, 'promoter_quarter'] == pd.Timestamp('2026-09-30')


def test_a_figure_not_yet_filed_keeps_the_last_one_with_its_own_quarter():
    out = build()
    assert out.loc[A, 'pledge'] == 9.0 and out.loc[A, 'pledge_quarter'] == pd.Timestamp('2026-06-30')   # not 10.0, not blank
    assert abs(out.loc[A, 'pledge_change_pts'] + 1.0) < 1e-9


def test_two_quarters_a_year_apart_give_no_change_since_last_quarter():
    out = build()
    assert out.loc[B, 'promoter'] == 41.0 and np.isnan(out.loc[B, 'promoter_change_pts'])
    assert out.loc[B, 'mf'] == 9.0 and np.isnan(out.loc[B, 'mf_change_pts'])


def test_a_company_with_one_quarter_or_no_figure_has_no_change_and_nothing_is_invented():
    out = build()
    assert out.loc[C, 'promoter'] == 60.0 and np.isnan(out.loc[C, 'promoter_change_pts'])
    assert np.isnan(out.loc[C, 'mf']) and pd.isna(out.loc[C, 'mf_quarter'])


def test_insider_flows_are_decision_makers_in_the_window_and_dates_are_all_time():
    out = build()
    assert out.loc[A, 'insider_buy_90d'] == 40e7 and out.loc[A, 'insider_sell_90d'] == 5e7        # the employee's 90 Cr never counts
    assert out.loc[A, 'insider_net_90d'] == 35e7 and out.loc[A, 'promoter_buy_90d'] == 40e7 and out.loc[A, 'promoter_sell_90d'] == 0
    assert out.loc[A, 'last_insider_buy'] == pd.Timestamp('2026-10-05') and out.loc[A, 'last_insider_sell'] == pd.Timestamp('2026-10-10')
    short = snapshot.build(summary(), holdings(), trades(), ref=REF, days=30).set_index('isin')
    assert short.loc[A, 'insider_buy_90d'] == 40e7
    old = snapshot.build(summary(), holdings(), trades(), ref=pd.Timestamp('2027-02-01')).set_index('isin')   # 119 days on
    assert old.loc[A, 'insider_buy_90d'] == 0 and old.loc[A, 'last_insider_buy'] == pd.Timestamp('2026-10-05')   # the date outlives the window


def test_a_token_buy_is_not_buying_and_a_kmp_buy_is():
    out = build()
    assert out.loc[B, 'insider_buy_90d'] == 3e7 and out.loc[B, 'promoter_buy_90d'] == 0
    assert out.loc[B, 'last_insider_buy'] == pd.Timestamp('2026-10-15')


def test_a_company_without_trades_has_zero_flows_and_no_dates():
    out = build()
    assert out.loc[C, ['insider_buy_90d', 'insider_sell_90d', 'insider_net_90d', 'promoter_buy_90d']].tolist() == [0.0] * 4
    assert pd.isna(out.loc[C, 'last_insider_buy']) and pd.isna(out.loc[C, 'last_insider_sell'])


def test_the_study_universe_cuts_the_table():
    out = snapshot.build(summary(), holdings(), trades(), universe={A, B}, ref=REF)
    assert out['isin'].tolist() == [A, B]
    assert snapshot.build(summary(), universe=set(), ref=REF).empty


def test_missing_inputs_give_an_empty_or_market_only_table_with_the_same_columns():
    assert list(snapshot.build(None).columns) == snapshot.COLUMNS and snapshot.build(None).empty
    assert list(snapshot.build(pd.DataFrame()).columns) == snapshot.COLUMNS
    market = snapshot.build(summary())                         # no shareholding, no trades
    assert list(market.columns) == snapshot.COLUMNS and len(market) == 3
    assert market['promoter'].isna().all() and market['insider_net_90d'].isna().all()


def test_duplicate_quarters_and_exchange_copies_do_not_double_count():
    sh = pd.concat([holdings(), holdings().iloc[[2]]], ignore_index=True)      # A's latest quarter twice (revised copy)
    out = snapshot.build(summary(), sh, trades(), ref=REF).set_index('isin')
    assert out.loc[A, 'promoter'] == 51.0 and abs(out.loc[A, 'promoter_change_pts'] - 0.5) < 1e-9
    dup = pd.concat([summary(), summary().iloc[[0]]], ignore_index=True)
    assert snapshot.build(dup, ref=REF)['isin'].is_unique


# ---- the nightly writer and the site's reader ----------------------------------------------------------------------

class _Client:
    def __init__(self):
        self.put = {}

    def put_object(self, Bucket, Key, Body):  # noqa: N803 -- boto3's names
        self.put[(Bucket, Key)] = Body


def test_the_nightly_writes_the_snapshot_with_nse_and_bse_only_shareholding(capsys):
    import io

    import precompute_slim as nightly
    bse = pd.DataFrame({'isin': [C], 'symbol': ['500999'], 'quarter_end': pd.to_datetime(['2026-09-30']), 'promoter_holding_pct': [70.0],
                        'mf_pct': [1.5], 'on_nse': [False]})
    sec = pd.DataFrame({'isin': [A], 'display_name': ['Display A']})
    clean = {'shareholding': holdings(), 'bse_shareholding': bse, 'insider_trades': trades(), 'securities': sec}
    client = _Client()
    nightly.company_snapshot(client, 'bkt', summary(), clean, {A, B, C})
    body = client.put[('bkt', nightly.SNAPSHOT_KEY)]
    got = pd.read_parquet(io.BytesIO(body)).set_index('isin')
    assert list(got.columns) == snapshot.COLUMNS[1:] and len(got) == 3
    assert got.loc[A, 'company'] == 'Display A' and got.loc[A, 'insider_net_90d'] == 35e7
    assert got.loc[C, 'promoter'] == 70.0 and got.loc[C, 'mf'] == 1.5           # the BSE-only company's filing is in
    assert 'snapshot: 3 companies' in capsys.readouterr().out
    # without the shareholding or trades tables the market line is still written
    client2 = _Client()
    nightly.company_snapshot(client2, 'bkt', summary(), {}, None)
    assert len(pd.read_parquet(io.BytesIO(client2.put[('bkt', nightly.SNAPSHOT_KEY)]))) == 3


def test_the_site_reads_the_snapshot_and_an_absent_one_is_empty(tmp_path, monkeypatch):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'streamlit_app'))
    import streamlit as st
    from data import store
    (tmp_path / 'artifacts').mkdir()
    monkeypatch.setenv('INSIDERS_LOCAL_DATA', str(tmp_path))
    st.cache_data.clear()
    assert store.snapshot().empty
    snapshot.build(summary(), holdings(), trades(), ref=REF).to_parquet(tmp_path / 'artifacts' / 'company_snapshot.parquet')
    st.cache_data.clear()
    got = store.snapshot()
    assert len(got) == 3 and list(got.columns) == snapshot.COLUMNS
    st.cache_data.clear()
