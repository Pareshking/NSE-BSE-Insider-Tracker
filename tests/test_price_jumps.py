"""Side-window series (IIFL Finance, 30 Jul 2026), the ratio guess that must show in the close, and the price-jump audit."""
import numpy as np
import pandas as pd

from insiders_clean import adjust, price_jumps, slim


def _row(day, close, prev, ex='NSE', series='EQ', isin='INE530B01024', sym='IIFL', value=1e9):
    return {'date': pd.Timestamp(day), 'exchange': ex, 'isin': isin, 'symbol': sym, 'series': series, 'name': sym,
            'open': close, 'high': close, 'low': close, 'close': close, 'prev_close': prev, 'volume': 1, 'value': value}


def iifl():
    """Real prints, NSE and BSE, 28-31 Jul 2026: NSE's block window (BL) on 30 Jul carries a base price of 334.25 and
    more value than EQ."""
    return pd.DataFrame([
        _row('2026-07-28', 582.35, 573.20, value=1.70e9), _row('2026-07-28', 582.15, 572.35, ex='BSE', series='A', value=4.5e7),
        _row('2026-07-29', 595.10, 582.35, value=1.46e9), _row('2026-07-29', 594.90, 582.15, ex='BSE', series='A', value=8.7e7),
        _row('2026-07-30', 607.85, 595.10, value=2.35e9), _row('2026-07-30', 590.00, 334.25, series='BL', value=3.74e9),
        _row('2026-07-30', 608.20, 594.90, ex='BSE', series='A', value=9.7e7),
        _row('2026-07-31', 608.65, 607.85, value=1.52e9), _row('2026-07-31', 608.65, 608.20, ex='BSE', series='A', value=7.3e7),
    ])


def test_block_window_series_is_never_the_session():
    f = adjust.implied_factors(iifl())
    nse = f[(f['exchange'] == 'NSE') & (f['date'] == '2026-07-30')].iloc[0]
    assert nse['close'] == 607.85 and nse['kind'] == 'none'
    assert (f['kind'] != 'split_bonus').all()


def test_iifl_line_has_no_jump():
    close, _, f = slim.adjusted_panels(iifl())
    line = close['INE530B01024']
    assert line['2026-07-29'] == 595.10 and line['2026-07-30'] == 607.85
    assert line.pct_change().abs().max() < 0.05


def test_side_series_rows_counted():
    c = adjust.side_series_rows(iifl())
    assert c == {'rows': 1, 'by_series': {'NSE:BL': 1}, 'would_have_won': 1}


def test_ratio_guess_needs_the_close_to_move():
    # A base price reset to a clean ratio (1:2 split, 0.5) while the close stays put is no split.
    p = pd.DataFrame([_row('2026-01-01', 100, 100, isin='INE000A01011', sym='X'),
                      _row('2026-01-02', 101, 50, isin='INE000A01011', sym='X')])
    f = adjust.implied_factors(p)
    r = f[f['date'] == '2026-01-02'].iloc[0]
    assert r['kind'] == 'other_large' and r['kind_basis'] == 'ratio_price_disagrees'
    # The same reset with the close halving is a split.
    p.loc[1, 'close'] = 51
    r = adjust.implied_factors(p).iloc[-1]
    assert r['kind'] == 'split_bonus' and r['kind_basis'] == 'ratio'


def _panels(rows):
    close, _, f, raw = slim.adjusted_and_raw(pd.DataFrame(rows))
    return raw, close, f


def test_jump_statuses():
    rows = []
    # A: a real 1:2 split (base reset, close halves) -> adjusted
    rows += [_row('2026-01-01', 100, 100, isin='INE00000A011', sym='A'), _row('2026-01-02', 51, 50, isin='INE00000A011', sym='A')]
    # B: a 60% fall with no reset and no action -> unexplained
    rows += [_row('2026-01-01', 100, 100, isin='INE00000B011', sym='B'), _row('2026-01-02', 40, 100, isin='INE00000B011', sym='B')]
    # C: a fall on a filed rights ex-date -> action_not_adjusted
    rows += [_row('2026-01-01', 100, 100, isin='INE00000C011', sym='C'), _row('2026-01-02', 50, 100, isin='INE00000C011', sym='C')]
    # D: base reset by 0.35 (a demerger, not a clean ratio) -> exchange_reset_not_adjusted
    rows += [_row('2026-01-01', 100, 100, isin='INE00000D011', sym='D'), _row('2026-01-02', 36, 35, isin='INE00000D011', sym='D')]
    # E: a doubling after a 40-day gap -> after_gap
    rows += [_row('2026-01-01', 100, 100, isin='INE00000E011', sym='E'), _row('2026-02-10', 200, 100, isin='INE00000E011', sym='E')]
    raw, adj, f = _panels(rows)
    acts = pd.DataFrame({'isin': ['INE00000C011'], 'purpose': ['rights'], 'ex_date': ['2026-01-02']})
    meta = pd.DataFrame(rows)[['isin', 'symbol', 'name']]
    out = price_jumps.jumps(raw, adj, f, acts, universe={'INE00000B011'}, meta=meta)
    got = dict(zip(out['symbol'], out['status']))
    assert got == {'A': 'adjusted', 'B': 'unexplained', 'C': 'action_not_adjusted', 'D': 'exchange_reset_not_adjusted',
                   'E': 'after_gap'}
    assert out.loc[out['symbol'] == 'C', 'actions'].item() == 'rights'
    rep = price_jumps.report(out, raw)
    assert rep['moves'] == 5 and rep['by_status']['unexplained'] == {'moves': 1, 'companies': 1}
    assert rep['in_universe']['unexplained']['moves'] == 1 and rep['in_universe']['adjusted']['moves'] == 0
    assert rep['rows'][0]['status'] == 'unexplained'


def test_made_by_adjustment_is_caught():
    # A wrong factor applied to a quiet line: the audit flags the move it creates.
    raw = pd.DataFrame({'X': [100.0, 101.0, 102.0]}, index=pd.to_datetime(['2026-01-01', '2026-01-02', '2026-01-05']))
    adj = raw.copy()
    adj.iloc[:2] *= 0.5
    out = price_jumps.jumps(raw.rename_axis(index='date', columns='isin'), adj.rename_axis(index='date', columns='isin'))
    assert out['status'].tolist() == ['made_by_adjustment']
    assert np.isclose(out['adj_move'].item(), 102 / 50.5 - 1)


def test_start_cuts_the_window():
    raw = pd.DataFrame({'X': [100.0, 30.0, 31.0]}, index=pd.to_datetime(['2025-10-01', '2025-10-02', '2025-10-09']))
    raw = raw.rename_axis(index='date', columns='isin')
    assert price_jumps.jumps(raw, raw, start='2025-10-08').empty
    assert len(price_jumps.jumps(raw, raw)) == 1
