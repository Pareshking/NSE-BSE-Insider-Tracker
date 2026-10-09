import io
import zipfile

import pandas as pd
import pytest

from insiders_clean import adjust, market_cap

MCAP = ('Trade Date,Symbol,Series,Security Name,Category,Last Trade Date,Face Value(Rs.),Issue Size,'
        'Close Price/Paid up value(Rs.),Market Cap(Rs.)              \n'
        '08 OCT 2026,20MICRONS,EQ,20 MICRONS LTD           ,Listed    ,08 OCT 2026,               5.00,          35286502,'
        '            194.80,     6874163454.60 \n'
        '08 OCT 2026,,,,,,,,,\n')


def test_parse_mcap_plain_and_zip_and_validate():
    a = market_cap.parse_mcap(MCAP.encode())
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('MCAP08102026.csv', MCAP)
        z.writestr('pr08102026.csv', 'x')
    assert a.equals(market_cap.parse_mcap(buf.getvalue()))
    r = a.iloc[0]
    assert (r['symbol'], r['issue_size'], r['close']) == ('20MICRONS', 35286502, 194.8) and len(a) == 1
    v = market_cap.validate(a)
    assert v['mcap_not_size_x_close'] == 0 and v['listed'] == 1


def test_wrong_mcap_layout():
    with pytest.raises(ValueError):
        market_cap.parse_mcap(b'a,b\n1,2\n')


def _p(rows):
    return pd.DataFrame(rows, columns=['date', 'exchange', 'isin', 'symbol', 'series', 'close', 'prev_close', 'value'])\
        .assign(date=lambda d: pd.to_datetime(d['date']))


def test_split_detected_on_both_exchanges_and_adjusts_history():
    rows = []
    for ex in ('NSE', 'BSE'):
        rows += [('2026-01-05', ex, 'INE1', 'A', 'EQ', 100.0, 99.0, 10), ('2026-01-06', ex, 'INE1', 'A', 'EQ', 51.0, 50.0, 10),
                 ('2026-01-07', ex, 'INE1', 'A', 'EQ', 52.0, 51.0, 10)]
    f = adjust.implied_factors(_p(rows))
    ev = f[f['kind'] == 'split_bonus']
    assert sorted(ev['exchange']) == ['BSE', 'NSE'] and ev['factor'].round(2).eq(0.5).all()
    adj = adjust.adjust_as_of(f, _p(rows)[['date', 'exchange', 'isin', 'close']], '2026-01-07')
    nse = adj[adj['exchange'] == 'NSE'].set_index('date')['adj_close']
    assert nse['2026-01-05'] == 50.0 and nse['2026-01-07'] == 52.0


def test_no_look_ahead():
    rows = [('2026-01-05', 'NSE', 'INE1', 'A', 'EQ', 100.0, 99.0, 10), ('2026-01-06', 'NSE', 'INE1', 'A', 'EQ', 51.0, 50.0, 10)]
    f = adjust.implied_factors(_p(rows))
    adj = adjust.adjust_as_of(f, _p(rows)[['date', 'exchange', 'isin', 'close']], '2026-01-05')
    assert adj['adj_close'].tolist() == [100.0]


def test_stale_previous_print_gives_unknown_not_a_false_event():
    rows = [('2026-01-05', 'NSE', 'INE1', 'A', 'EQ', 100.0, 99.0, 10), ('2026-03-05', 'NSE', 'INE1', 'A', 'EQ', 60.0, 59.0, 10)]
    f = adjust.implied_factors(_p(rows))
    assert f['kind'].tolist() == ['unknown', 'unknown']


def test_odd_large_reset_is_counted_but_not_adjusted():
    rows = [('2026-01-05', 'NSE', 'INE1', 'A', 'EQ', 100.0, 99.0, 10), ('2026-01-06', 'NSE', 'INE1', 'A', 'EQ', 70.0, 73.0, 10)]
    f = adjust.implied_factors(_p(rows))
    assert f['kind'].tolist()[-1] == 'other_large'
    adj = adjust.adjust_as_of(f, _p(rows)[['date', 'exchange', 'isin', 'close']], '2026-01-06')
    assert adj['adj_close'].tolist() == [100.0, 70.0]


def test_bonus_and_consolidation_ratios_count():
    import numpy as np
    assert adjust.is_clean_ratio(np.array([0.5, 2 / 3, 0.2, 5.0, 0.8, 0.93])).tolist() == [True, True, True, True, True, False]
