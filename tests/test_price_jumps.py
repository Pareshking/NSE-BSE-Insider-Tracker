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


def test_session_missing_from_the_layer_measures_no_factor():
    # 1 Feb 2026 (a Sunday session) is not in the layer: on 2 Feb every base price is that day's close, not 30 Jan's.
    # IIFL's 528.70 -> 475.75 looked like a 10:11 bonus (0.8998) and moved its whole line before February.
    rows = [_row('2026-01-30', 528.70, 530.0), _row('2026-02-02', 495.15, 475.75)]
    for k in range(150):
        isin, last = f'INE{k:03d}X01011', 100.0 + k
        rows += [_row('2026-01-30', last, last, isin=isin, sym=f'S{k}'),
                 _row('2026-02-02', last * 0.97, last * 0.98, isin=isin, sym=f'S{k}')]
    f = adjust.implied_factors(pd.DataFrame(rows))
    day = f[f['date'] == '2026-02-02']
    assert (day['kind_basis'] == 'previous_session_missing').all() and day['factor'].isna().all()
    close, _, _ = slim.adjusted_panels(pd.DataFrame(rows))
    assert close.loc['2026-01-30', 'INE530B01024'] == 528.70


def test_a_normal_day_of_dividends_is_not_a_missing_session():
    rows = []
    for k in range(150):
        isin, last = f'INE{k:03d}X01011', 100.0 + k
        base = last * 0.98 if k < 10 else last   # ten of 150 go ex-dividend
        rows += [_row('2026-03-02', last, last, isin=isin, sym=f'S{k}'), _row('2026-03-03', last, base, isin=isin, sym=f'S{k}')]
    f = adjust.implied_factors(pd.DataFrame(rows))
    assert not (f['kind_basis'] == 'previous_session_missing').any()


def test_filed_split_on_a_new_isin_with_no_base_price_is_applied():
    # KSE, 28 Oct 2025: the split's new ISIN prints with no base price; the old ISIN's prints are bridged under it,
    # and the split is filed under the old ISIN.
    rows = [_row('2025-10-24', 2700.0, 2690.0, isin='INE953E01014', sym='KSE'),
            _row('2025-10-27', 2698.35, 2700.0, isin='INE953E01014', sym='KSE'),
            _row('2025-10-28', 262.20, np.nan, isin='INE953E01022', sym='KSE')]
    acts = pd.DataFrame({'isin': ['INE953E01014'], 'purpose': ['split'], 'ex_date': ['2025-10-28'],
                         'face_value_from': [10.0], 'face_value_to': [1.0]})
    close, _, f, raw = slim.adjusted_and_raw(pd.DataFrame(rows), actions=acts)
    line = close['INE953E01022'].dropna()
    assert abs(line.pct_change().iloc[-1]) < 0.05
    out = price_jumps.jumps(raw, close, f, acts)
    assert out['isin'].tolist() == ['INE953E01022'] and out['status'].tolist() == ['adjusted']


def test_filed_bonus_after_a_gap_is_applied():
    # VEGA: no print for 12 days around its bonus; here a 4:1 bonus (factor 0.2).
    rows = [_row('2026-04-16', 312.25, 310.0, isin='INE603D01017', sym='VEGA'),
            _row('2026-04-28', 61.95, 312.25, isin='INE603D01017', sym='VEGA')]
    acts = pd.DataFrame({'isin': ['INE603D01017'], 'purpose': ['bonus'], 'ex_date': ['2026-04-24'], 'ratio': ['4:1']})
    close, _, f = slim.adjusted_panels(pd.DataFrame(rows), actions=acts)
    assert abs(close['INE603D01017'].pct_change().iloc[-1]) < 0.05


def test_bse_keeps_its_factor_on_a_day_nse_did_not_print():
    # PANORAMA: BSE-only on its 5:2 bonus (05 Dec 2025), on NSE from Aug 2026. The BSE factor must stay.
    i = 'INE258R01028'
    rows = [_row('2025-12-04', 164.35, 170.00, ex='BSE', series='B', isin=i, sym='PANORAMA'),
            _row('2025-12-05', 48.40, 164.35, ex='BSE', series='B', isin=i, sym='PANORAMA'),
            _row('2026-08-17', 60.0, 59.0, isin=i, sym='PANORAMA'), _row('2026-08-17', 60.0, 59.0, ex='BSE', series='B', isin=i, sym='PANORAMA'),
            _row('2026-08-18', 61.0, 60.0, isin=i, sym='PANORAMA'), _row('2026-08-18', 61.0, 60.0, ex='BSE', series='B', isin=i, sym='PANORAMA')]
    acts = pd.DataFrame({'isin': [i], 'purpose': ['bonus'], 'ex_date': ['2025-12-05'], 'ratio': ['5:2']})
    close, _, f = slim.adjusted_panels(pd.DataFrame(rows), actions=acts)
    b = f[(f['exchange'] == 'BSE') & (f['date'] == '2025-12-05')].iloc[0]
    assert b['kind'] == 'split_bonus' and np.isclose(b['factor'], 2 / 7)
    assert abs(close[i].loc['2025-12-04':'2025-12-05'].pct_change().iloc[-1]) < 0.05
    # Where NSE printed, BSE still takes NSE's factor.
    assert f[(f['exchange'] == 'BSE') & (f['date'] == '2026-08-18')]['kind'].item() == 'none'


def test_action_matched_by_symbol():
    raw = pd.DataFrame({'INE00000N012': [100.0, 10.0]}, index=pd.to_datetime(['2026-01-01', '2026-01-02']))
    raw = raw.rename_axis(index='date', columns='isin')
    meta = pd.DataFrame({'isin': ['INE00000N012'], 'symbol': ['NEWCO'], 'name': ['New Co']})
    acts = pd.DataFrame({'isin': ['INE00000N011'], 'symbol': ['newco'], 'purpose': ['split'], 'ex_date': ['2026-01-02']})
    out = price_jumps.jumps(raw, raw, None, acts, meta=meta)
    assert out['status'].item() == 'action_not_adjusted' and out['actions'].item() == 'split'


def vedl():
    """Real prints of Vedanta (INE205A01025), NSE and BSE, 28 Apr - 4 May 2026: the demerger's ex-date (30 Apr, BSE
    'Spin Off') with the base price NOT reset (773.60 on NSE, 773.25 on BSE: the day before's closes)."""
    i = 'INE205A01025'
    return pd.DataFrame([
        _row('2026-04-28', 739.30, 742.50, isin=i, sym='VEDL'), _row('2026-04-28', 739.20, 742.60, ex='BSE', series='A', isin=i, sym='VEDL'),
        _row('2026-04-29', 773.60, 739.30, isin=i, sym='VEDL'), _row('2026-04-29', 773.25, 739.20, ex='BSE', series='A', isin=i, sym='VEDL'),
        _row('2026-04-30', 271.55, 773.60, isin=i, sym='VEDL'), _row('2026-04-30', 271.60, 773.25, ex='BSE', series='A', isin=i, sym='VEDL'),
        _row('2026-05-04', 294.65, 271.55, isin=i, sym='VEDL'), _row('2026-05-04', 294.80, 271.60, ex='BSE', series='A', isin=i, sym='VEDL'),
    ])


def test_bse_spin_off_and_schemes_are_kept():
    from collectors.bse import parsers as bse_parsers
    from collectors.nse_events.parsers import action_purpose
    raw = [{'scrip_code': 500295, 'long_name': 'Vedanta Ltd', 'Ex_date': '30 Apr 2026', 'Purpose': 'Spin Off ',
            'RD_Date': '01 May 2026'},
           {'scrip_code': 520056, 'long_name': 'TVS Holdings Ltd', 'Ex_date': '08 Sep 2026',
            'Purpose': 'Scheme of Arrangement', 'RD_Date': '08 Sep 2026'},
           {'scrip_code': 531775, 'long_name': 'CISTRO Telelink Ltd', 'Ex_date': '06 Mar 2026',
            'Purpose': 'Reduction of Capital', 'RD_Date': '06 Mar 2026'},
           {'scrip_code': 514010, 'long_name': 'Rudra Ecovation Ltd', 'Ex_date': '06 Nov 2026',
            'Purpose': 'Amalgamation', 'RD_Date': '06 Nov 2026'}]
    df, dropped = bse_parsers.parse_actions(raw)
    assert dropped == 0
    assert df['purpose'].tolist() == ['demerger', 'scheme', 'capital_reduction', 'scheme']
    assert action_purpose('Scheme Of Arrangement - Bonus 1:1') == 'bonus'   # still a bonus
    assert action_purpose('Demerger') == 'demerger'


def test_demerger_with_no_base_reset_is_adjusted_at_the_ex_date_close():
    # VEDL 30 Apr 2026: a filed demerger, the exchanges did not reset the base price. Owner directive 20 Nov 2026:
    # adjusted at the ex-date's closing price, factor = 271.55 / 773.60 (basis action_close), so the line no longer
    # falls 65% that day and the audit counts it adjusted.
    i = 'INE205A01025'
    acts = pd.DataFrame({'isin': [i], 'symbol': ['500295'], 'purpose': ['demerger'], 'ex_date': ['2026-04-30']})
    close, _, f, raw = slim.adjusted_and_raw(vedl(), actions=acts)
    d = f[(f['exchange'] == 'NSE') & (f['date'] == '2026-04-30')].iloc[0]
    assert d['kind'] == 'demerger' and d['kind_basis'] == 'action_close'
    assert np.isclose(d['factor'], 271.55 / 773.60)
    assert np.isclose(close.loc['2026-04-29', i], 271.55)
    assert close.loc['2026-04-30', i] == 271.55 and close.loc['2026-05-04', i] == 294.65
    meta = vedl()[['isin', 'symbol', 'name']]
    out = price_jumps.jumps(raw, close, f, acts, universe={i}, meta=meta)
    assert out.loc[out['date'] == '2026-04-30', 'status'].tolist() == ['adjusted']
    rep = price_jumps.report(out, raw)
    assert rep['in_universe']['scheme_not_adjusted']['moves'] == 0 and rep['in_universe']['unexplained']['moves'] == 0
    # Without the filed demerger the same move is not adjusted, and unexplained.
    close0, _, f0, _ = slim.adjusted_and_raw(vedl())
    assert close0.loc['2026-04-29', i] == 773.60 and (f0['kind'] != 'demerger').all()
    assert price_jumps.jumps(raw, close0, f0, None, universe={i}, meta=meta)['status'].tolist() == ['unexplained']
    # A scheme of arrangement or an amalgamation (not a demerger) is not adjusted from the close.
    sch = acts.assign(purpose='scheme')
    _, _, f2, _ = slim.adjusted_and_raw(vedl(), actions=sch)
    assert (f2['kind'] != 'demerger').all()


def test_demerger_small_move_is_left_as_printed():
    i = 'INE00000Q011'
    rows = [_row('2026-01-01', 100, 99, isin=i, sym='Q'), _row('2026-01-02', 97, 100, isin=i, sym='Q')]
    acts = pd.DataFrame({'isin': [i], 'purpose': ['demerger'], 'ex_date': ['2026-01-02']})
    close, _, f, _ = slim.adjusted_and_raw(pd.DataFrame(rows), actions=acts)
    assert close.loc['2026-01-01', i] == 100 and (f['kind'] != 'demerger').all()


def test_demerger_with_an_exchange_base_reset_is_applied():
    # A filed demerger whose ex-date base price the exchange reset (0.36, not a clean ratio): the factor is the
    # exchange's base over our previous close (basis action_base_price), applied to the line.
    i = 'INE00000Q011'
    rows = [_row('2026-01-01', 100, 99, isin=i, sym='Q'), _row('2026-01-02', 37, 36, isin=i, sym='Q'),
            _row('2026-01-05', 38, 37, isin=i, sym='Q')]
    acts = pd.DataFrame({'isin': [i], 'purpose': ['demerger'], 'ex_date': ['2026-01-02']})
    close, _, f, raw = slim.adjusted_and_raw(pd.DataFrame(rows), actions=acts)
    d = f[f['date'] == '2026-01-02'].iloc[0]
    assert d['kind'] == 'demerger' and d['kind_basis'] == 'action_base_price' and np.isclose(d['factor'], 0.36)
    assert np.isclose(close.loc['2026-01-01', i], 36)
    assert adjust.coverage(f)['demerger'] == 1
    # The same reset with no demerger filed is not applied.
    close0, _, f0, _ = slim.adjusted_and_raw(pd.DataFrame(rows))
    assert close0.loc['2026-01-01', i] == 100 and (f0['kind'] != 'demerger').all()


def test_nse_actions_backfill_goes_month_by_month():
    from datetime import date

    from collectors.nse_events import run_daily

    class FakeNSE:
        on_response = None

        def __init__(self):
            self.calls = []

        def corporate_actions(self, a, b, index='equities'):
            self.calls.append((a, b, index))
            if index == 'sme':   # NSE's SME board (21 Nov 2026): a bonus on an SME name
                return [{'symbol': 'SMECO', 'series': 'SM', 'isin': 'INE000M01019', 'exDate': '07-Jul-2026',
                         'subject': 'Bonus 4:1', 'recDate': '07-Jul-2026', 'comp': 'SME Co Limited'}] if a.month == 7 else []
            if a.month == 6:
                return [{'symbol': 'SPLITCO', 'series': 'EQ', 'isin': 'INE000S01019', 'exDate': '05-Jun-2026',
                         'subject': 'Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 1/- Per Share',
                         'recDate': '05-Jun-2026', 'faceVal': '10', 'comp': 'Split Co Limited'}]
            return [{'symbol': 'X', 'series': 'EQ', 'isin': 'INE000X01011', 'subject': 'Interest Payment',
                     'exDate': '01-Jul-2026'}]

    nse = FakeNSE()
    df, dropped = run_daily.fetch_actions(nse, date(2026, 7, 24), date(2026, 8, 3), backfill_from=date(2026, 6, 1))
    months = [(date(2026, 6, 1), date(2026, 6, 30)), (date(2026, 7, 1), date(2026, 7, 31)),
              (date(2026, 8, 1), date(2026, 8, 3))]
    assert nse.calls == [(a, b, i) for a, b in months for i in ('equities', 'sme')]
    assert dropped == 2 and sorted(df['purpose']) == ['bonus', 'split']
    sp = df[df['purpose'] == 'split']
    assert (sp['face_value_from'].item(), sp['face_value_to'].item()) == (10.0, 1.0)
    assert df.loc[df['purpose'] == 'bonus', 'symbol'].item() == 'SMECO'
    nse2 = FakeNSE()
    run_daily.fetch_actions(nse2, date(2026, 7, 24), date(2026, 8, 3))
    assert nse2.calls == [(date(2026, 7, 24), date(2026, 8, 3), 'equities'), (date(2026, 7, 24), date(2026, 8, 3), 'sme')]
