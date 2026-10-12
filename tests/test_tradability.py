"""Tradability flags: NSE surveillance lists, price bands, trade for trade, SME, circuit-locked days.

Fixtures in tests/fixtures/tradability/ are trimmed real answers fetched 12 Oct 2026 (one row per survCode)."""
from __future__ import annotations

import io
import json
from pathlib import Path

import pandas as pd
import pytest

from insiders_clean import signals, tradability as T

FX = Path(__file__).resolve().parent / 'fixtures' / 'tradability'
DAY = '2026-10-12'


def load(name):
    return json.loads((FX / name).read_text(encoding='utf-8'))


def surv(day=DAY):
    return T.parse_surveillance(load('nse_asm_20261012.json'), load('nse_gsm_20261012.json'),
                                load('nse_esm_20261012.json'), day)


def px_row(day, isin, symbol, series, prev, o, h, l, c, vol=100):
    return {'date': pd.Timestamp(day), 'exchange': 'NSE', 'isin': isin, 'symbol': symbol, 'series': series,
            'open': o, 'high': h, 'low': l, 'close': c, 'prev_close': prev, 'volume': vol}


def test_surveillance_lists_parse_with_stages_from_real_answers():
    s = surv()
    assert set(s['list']) == {'asm_lt', 'asm_st', 'gsm', 'esm', 'ibc'}
    assert set(s.loc[s['list'] == 'asm_lt', 'stage']) == {'I', 'II', 'III', 'IV'}
    assert set(s.loc[s['list'] == 'esm', 'stage']) == {'I', 'II'}
    # GSM stage comes from survCode; NSE's gsmStage holds the code number in Roman numerals ('LXII' for 62).
    g = s[s['list'] == 'gsm']
    assert set(g['stage']) <= {'0', 'I', 'II', 'III', 'IV', 'V', 'VI'}
    raw = {r['isin']: r for r in load('nse_gsm_20261012.json')}
    ibc_row = next(r for r in raw.values() if r['survCode'].startswith('IBC - Receipt & GSM 0'))
    assert raw[ibc_row['isin']]['gsmStage'] == 'LXII'
    assert g.set_index('isin').loc[ibc_row['isin'], 'stage'] == '0'
    assert s[(s['list'] == 'ibc') & (s['isin'] == ibc_row['isin'])]['stage'].tolist() == ['Receipt']
    gsm3 = next(r for r in raw.values() if r['survCode'].startswith('GSM III'))
    assert g.set_index('isin').loc[gsm3['isin'], 'stage'] == 'III'
    # Combined codes ('LTASM I & GSM 0') give the GSM stage only: the ASM stage is on NSE's ASM list.
    combo = next(r for r in raw.values() if r['survCode'].startswith('LTASM I & GSM 0'))
    assert s[s['isin'] == combo['isin']]['list'].tolist() == ['gsm']


def test_sec_list_keeps_band_and_no_band():
    sl = T.parse_sec_list((FX / 'nse_sec_list_20261012.csv').read_bytes(), DAY)
    assert {'symbol', 'series', 'band_pct', 'band_text', 'remarks'} <= set(sl.columns)
    nb = sl[sl['band_text'] == 'No Band']
    assert len(nb) and nb['band_pct'].isna().all()
    assert set(sl['band_pct'].dropna()) <= {2, 5, 10, 20, 40}
    with pytest.raises(ValueError):
        T.parse_sec_list(b'a,b\n1,2\n', DAY)


def test_since_is_the_start_of_the_unbroken_run_from_our_snapshots():
    a, b, c = (pd.DataFrame([{'date': pd.Timestamp(d), 'list': 'esm', 'isin': 'X', 'symbol': 'X', 'stage': st,
                              'code': '', 'description': ''}]) for d, st in
               (('2026-10-12', 'I'), ('2026-10-13', 'II'), ('2026-10-14', 'II')))
    now = T.surveillance_now(pd.concat([a, b, c])).iloc[0]
    assert now['stage'] == 'II' and now['since'] == pd.Timestamp('2026-10-13') and not now['since_floor']
    first = T.surveillance_now(pd.concat([b, c])).iloc[0]
    assert first['since'] == pd.Timestamp('2026-10-13') and first['since_floor']  # "since at least"


def test_circuit_locked_needs_one_price_all_day_at_the_band():
    px = pd.DataFrame([
        px_row('2026-10-09', 'A', 'A', 'BE', 100, 105, 105, 105, 105),      # upper circuit at 5%
        px_row('2026-10-09', 'B', 'B', 'SM', 20.40, 19, 19, 19, 19, 1600),  # one trade, -6.9% on a 20% band
        px_row('2026-10-09', 'C', 'C', 'BE', 2.34, 2.30, 2.30, 2.30, 2.30), # 2% band, rounded to the paisa
        px_row('2026-10-09', 'D', 'D', 'EQ', 100, 95, 96, 95, 95),          # touched the band, traded above it
        px_row('2026-10-09', 'E', 'E', 'EQ', 100, 90, 90, 90, 90),          # no band: not judged
    ])
    cd = T.circuit_days(px, pd.Series({'A': 5.0, 'B': 20.0, 'C': 2.0, 'D': 5.0})).set_index('isin')
    assert set(cd.index) == {'A', 'C'}
    assert cd.loc['A', 'circuit_last_side'] == 'upper' and cd.loc['C', 'circuit_last_side'] == 'lower'


def test_build_flags_every_row_and_drops_none():
    s = surv()
    an_esm = s[s['list'] == 'esm'].iloc[0]
    px = pd.DataFrame([
        px_row('2026-10-08', 'INEBE', 'BESTK', 'EQ', 50, 50, 51, 49, 50),
        px_row('2026-10-09', 'INEBE', 'BESTK', 'BE', 50, 52.5, 52.5, 52.5, 52.5),
        px_row('2026-10-09', 'INESM', 'SMSTK', 'SM', 30, 30, 31, 29, 30),
        px_row('2026-10-09', 'INEEQ', 'EQSTK', 'EQ', 10, 10, 11, 9, 10),
        px_row('2026-10-09', an_esm['isin'], an_esm['symbol'], 'BE', 10, 10, 10.2, 9.8, 10),
        px_row('2026-10-09', 'INEBOND', 'GSEC', 'GS', 100, 100, 100, 100, 100),  # not an equity series
    ])
    sl = pd.DataFrame({'date': pd.Timestamp(DAY), 'symbol': ['BESTK', 'SMSTK', 'EQSTK'], 'series': ['BE', 'SM', 'EQ'],
                       'band_pct': [5.0, 20.0, float('nan')], 'band_text': ['5', '20', 'No Band'], 'remarks': ''})
    t = T.build(s, sl, px).set_index('isin')
    assert 'INEBOND' not in t.index
    assert set(s['isin']) <= set(t.index)  # on a list today but not in the bhavcopy: still a row
    be = t.loc['INEBE']
    assert be['trade_for_trade'] and be['t2t_since'] == pd.Timestamp('2026-10-09') and not be['t2t_since_floor']
    assert list(be['trade_flags']) == ['T2T', '5% band', 'Circuit 1/20']
    assert list(t.loc['INESM', 'trade_flags']) == ['SME']
    assert list(t.loc['INEEQ', 'trade_flags']) == []
    assert t.loc[an_esm['isin'], 'trade_flags'][0] == f'ESM {an_esm["stage"]}'
    assert 'since at least 12 Oct 2026' in t.loc[an_esm['isin'], 'trade_flag_notes'][0]
    assert len(t.loc['INEBE', 'trade_flag_notes']) == len(t.loc['INEBE', 'trade_flags'])
    # Round trip through parquet (the site reads it back as arrays).
    buf = io.BytesIO()
    t.reset_index().to_parquet(buf, index=False)
    back = pd.read_parquet(io.BytesIO(buf.getvalue()))
    rows = signals.with_tradability(pd.DataFrame({'isin': ['INEBE', 'INEEQ', 'BSEONLY'], 'n': [1, 2, 3]}), back)
    assert len(rows) == 3 and rows['trade_flags'].tolist() == [['T2T', '5% band', 'Circuit 1/20'], [], None]


def test_thresholds_come_from_config():
    px = pd.DataFrame([px_row('2026-10-09', 'A', 'A', 'EQ', 100, 110, 110, 110, 110)])
    sl = pd.DataFrame({'date': pd.Timestamp(DAY), 'symbol': ['A'], 'series': ['EQ'], 'band_pct': [10.0],
                       'band_text': ['10'], 'remarks': ''})
    assert list(T.build(None, sl, px)['trade_flags'][0]) == ['Circuit 1/20']
    cfg = T.Config(tight_band_max_pct=10.0, circuit_window=5)
    assert list(T.build(None, sl, px, cfg)['trade_flags'][0]) == ['10% band', 'Circuit 1/5']


def test_company_cell_draws_flags_as_amber_badges(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parent.parent / 'streamlit_app'))
    from ui.table import Col, _cell
    html, _, _ = _cell(Col('company', 'Company', 'co'), {'company': 'X Ltd', 'nse_symbol': 'X',
                                                         'trade_flags': ['ESM I'], 'trade_flag_notes': ['why']}, {})
    assert 'tg-warn' in html and 'ESM I' in html and 'title="why"' in html
    html, _, _ = _cell(Col('company', 'Company', 'co'), {'company': 'X Ltd', 'nse_symbol': 'X', 'trade_flags': None}, {})
    assert 'tg-warn' not in html


def test_nightly_job_stores_snapshots_and_the_clean_table(monkeypatch, tmp_path):
    import clean_writer
    import nse_surveillance as job
    import raw_capture

    from test_archive_and_writer import FakeR2

    monkeypatch.setattr(raw_capture, 'DIR', tmp_path)
    bodies = {'asm': (FX / 'nse_asm_20261012.json').read_bytes(), 'gsm': (FX / 'nse_gsm_20261012.json').read_bytes(),
              'esm': (FX / 'nse_esm_20261012.json').read_bytes(), 'sec_list': (FX / 'nse_sec_list_20261012.csv').read_bytes()}

    class Resp:
        status_code, headers = 200, {'Content-Type': 'application/json'}

        def __init__(self, body):
            self.content = body

    monkeypatch.setattr(job, 'get_bytes', lambda nse, url: Resp(bodies[next(k for k, u in job.SOURCES.items() if u == url)]))
    r2 = FakeR2()
    nse = type('N', (), {'calls': 4})()
    rep = job.run(r2, nse, pd.Timestamp(DAY).date())
    assert rep['parsed']['surveillance'] > 0 and rep['parsed']['sec_list'] > 0 and not rep['notes']
    assert 'archive/tradability/surveillance/year=2026.parquet' in r2.objects
    t = clean_writer.read_parquet(r2, job.CLEAN_KEY)
    assert len(t) == rep['clean']['isins'] and rep['clean']['flagged'] > 0
    assert len(list(tmp_path.glob('*.body'))) == 4  # every answer captured for raw_v2
    rep2 = job.run(r2, nse, pd.Timestamp(DAY).date())  # a rerun replaces the day, never doubles it
    snaps = clean_writer.read_parquet(r2, 'archive/tradability/surveillance/year=2026.parquet')
    assert len(snaps) == rep2['parsed']['surveillance']
