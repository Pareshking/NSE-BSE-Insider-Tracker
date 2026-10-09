"""data_inventory on a synthetic bucket: counts, 2026 split, windows, power."""
from __future__ import annotations

import json

import data_inventory as di
import numpy as np
import pandas as pd
from test_archive_and_writer import FakeR2

import clean_writer


def prices(n=300, symbols=('AAA', 'BBB', 'CCC')):
    idx = pd.bdate_range('2025-06-02', periods=n)
    rng = np.random.default_rng(1)
    return pd.DataFrame({s: 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n))) for s in symbols}, index=idx)


def test_forward_windows_complete_only_when_the_future_exists_and_power_needs_30():
    p = prices()
    last = p.index[-1]
    ev = pd.DataFrame({'symbol': ['AAA'] * 40 + ['ZZZ'],  # ZZZ has no price history
                       'signal_date': [p.index[10].date()] * 20 + [p.index[200].date()] * 20 + [p.index[10].date()]})
    ev.loc[0, 'signal_date'] = (last - pd.Timedelta(days=1)).date()  # entry after the last session -> never complete
    r = di.forward_windows(ev, p)
    assert r['events'] == 41 and r['with_price_history'] == 40
    assert r['horizons']['5']['complete_events'] == 39  # the late event and ZZZ fall out
    assert r['horizons']['250']['complete_events'] == 19  # only the early ones (entry 11 + 250 <= 299)
    assert 'mde_events' in r['horizons']['5'] and 'mde_events' not in r['horizons']['250']  # n < 30: no power claim


def test_entry_is_the_session_after_the_signal_date():
    p = prices(40)
    sig = p.index[10].date()
    r = di.forward_windows(pd.DataFrame({'symbol': ['AAA'], 'signal_date': [sig]}), p)
    assert r['horizons']['20']['complete_events'] == 1   # entry at 11, 11 + 20 <= 39
    r = di.forward_windows(pd.DataFrame({'symbol': ['AAA'], 'signal_date': [p.index[20].date()]}), p)
    assert r['horizons']['20']['complete_events'] == 0   # entry at 21, 21 + 20 > 39


def test_inventory_counts_the_archive_and_the_2026_split(real_nse_rows):
    from conftest import canonical
    r2 = FakeR2()
    clean_writer.BUCKET = ''
    frame = canonical('nse', 'insider_trading', real_nse_rows[:20])
    clean_writer.put_parquet(r2, 'archive/canonical/nse/insider_trading/year=2026/quarter=4.parquet', frame)
    r2.objects['clean/latest.json'] = json.dumps({'date': '2026-10-09', 'report': 'clean/reports/x.json'}).encode()
    r2.objects['clean/reports/x.json'] = json.dumps({'tables': {'deals': {'input_rows': 5, 'output_rows': 3,
                                                    'removed': {'intraday_round_trip': {'count': 2}}}}}).encode()
    inv = di.inventory(r2, '', None, '2026-10-09')
    a = inv['archive']['nse/insider_trading']
    assert a['rows'] == 20 and a['rows_before_2026'] + a['rows_2026_onward'] + a['unreadable_dates'] == 20
    assert inv['archive']['bse/bulk_deals'] is None and a['intraday_round_trip_flagged'] == 0
    assert inv['clean_report']['deals']['removed'] == {'intraday_round_trip': 2}
    assert 'Archive' in di.to_markdown(inv)
