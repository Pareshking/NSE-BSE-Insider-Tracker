"""Industry classification (insiders_clean/industry.py, scripts/industry.py, the store helpers).

BSE fixtures are real answers fetched on 19 Nov 2026 (tests/fixtures/industry/, ComHeadernew and a selection of
rows from ListofScripData). NSE refused its quote API both to the dev container and to GitHub's runners (HTTP 403,
19 Nov 2026, the workflow's probe job), so no real NSE answer exists yet: the NSE tests use answers built in code with
only the keys the parser reads (`info.isin`, `industryInfo.{macro,sector,industry,basicIndustry}`). Replace them with a
saved answer once NSE answers.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from insiders_clean import industry as I  # noqa: E402

FIX = ROOT / 'tests' / 'fixtures' / 'industry'
NOW = datetime(2026, 11, 19, 3, 0)


def fx(name):
    return json.loads((FIX / name).read_text())


def test_bse_header_gives_four_levels():
    r = I.parse_bse(fx('bse_comheadernew_500002.json'), '500002')
    assert r == {'bse_code': '500002', 'isin': 'INE117A01022', 'macro': 'Industrials', 'sector': 'Capital Goods',
                 'industry': 'Electrical Equipment', 'basic_industry': 'Heavy Electrical Equipment', 'status': 'ok'}
    r = I.parse_bse(fx('bse_comheadernew_500014.json'), '500014')
    assert (r['macro'], r['sector'], r['industry'], r['basic_industry']) == (
        'Commodities', 'Metals & Mining', 'Non - Ferrous Metals', 'Precious Metals')


def test_bse_unknown_and_unclassified_scrips():
    assert I.parse_bse(fx('bse_comheadernew_999999.json'), '999999')['status'] == 'not_found'
    r = I.parse_bse(fx('bse_comheadernew_543000.json'), '543000')
    assert r['status'] == 'no_industry' and r['isin'] == 'INF789F1AOK7' and r['macro'] is None
    assert I.parse_bse(None, '1')['status'] == 'error' and I.parse_bse([1], '1')['status'] == 'error'


def test_bse_list_keeps_company_isins_only():
    df = I.parse_bse_list(fx('bse_listofscripdata_sample.json'))
    assert list(df['bse_code']) == ['500002', '500003', '500008', '500009']   # INF fund unit and IN9 partly paid out
    assert df.loc[0, 'isin'] == 'INE117A01022' and df.loc[0, 'bse_symbol'] == 'ABB'


def nse_answer(industry_info=None, isin='INE117A01022'):
    j = {'info': {'symbol': 'ABB', 'isin': isin}, 'metadata': {'isin': isin}}
    if industry_info is not None:
        j['industryInfo'] = industry_info
    return j


def test_nse_quote_parse():
    r = I.parse_nse(nse_answer({'macro': 'Industrials', 'sector': 'Capital Goods', 'industry': 'Electrical Equipment',
                                'basicIndustry': 'Heavy Electrical Equipment'}), 'abb')
    assert r['nse_symbol'] == 'ABB' and r['isin'] == 'INE117A01022' and r['status'] == 'ok'
    assert r['basic_industry'] == 'Heavy Electrical Equipment'
    assert I.parse_nse(nse_answer({'macro': '', 'sector': '-'}), 'ABB')['status'] == 'no_industry'
    assert I.parse_nse(nse_answer(), 'ABB')['status'] == 'no_industry'
    assert I.parse_nse({}, 'X')['status'] == 'not_found'
    assert I.parse_nse('<html>', 'X')['status'] == 'error'


def test_due_missing_first_then_oldest_stale_and_limit():
    arch = pd.DataFrame({'nse_symbol': ['A', 'B', 'C', 'D'], 'status': ['ok', 'ok', 'no_industry', 'ok'],
                         'fetched_at': [NOW - timedelta(days=40), NOW - timedelta(days=5), NOW - timedelta(days=8),
                                        NOW - timedelta(days=31)]})
    todo = I.due(['A', 'B', 'C', 'D', 'E', 'F'], arch, 'nse_symbol', NOW, None)
    assert todo == ['E', 'F', 'A', 'D', 'C']   # B is fresh; C retried after 7 days
    assert I.due(['A', 'B', 'C', 'D', 'E', 'F'], arch, 'nse_symbol', NOW, 3) == ['E', 'F', 'A']
    assert I.due(['A'], None, 'nse_symbol', NOW, 400) == ['A']


def test_merge_later_answer_wins():
    old = pd.DataFrame([{'nse_symbol': 'A', 'status': 'error', 'fetched_at': NOW - timedelta(days=9)},
                        {'nse_symbol': 'B', 'status': 'ok', 'fetched_at': NOW - timedelta(days=9)}])
    new = pd.DataFrame([{'nse_symbol': 'A', 'status': 'ok', 'macro': 'Energy', 'fetched_at': NOW}])
    m = I.merge(old, new, 'nse_symbol', I.NSE_ARCHIVE_COLUMNS)
    assert len(m) == 2 and m.set_index('nse_symbol').loc['A', 'macro'] == 'Energy'
    assert list(m.columns) == I.NSE_ARCHIVE_COLUMNS


def test_build_nse_wins_then_bse_then_vr_master():
    nse = pd.DataFrame([{**I.parse_nse(nse_answer({'macro': 'Industrials', 'sector': 'Capital Goods',
                                                   'industry': 'Electrical Equipment',
                                                   'basicIndustry': 'Heavy Electrical Equipment'}), 'ABB'),
                         'fetched_at': NOW}])
    bse = pd.DataFrame([{**I.parse_bse(fx(f'bse_comheadernew_{c}.json'), c), 'fetched_at': NOW - timedelta(days=1)}
                        for c in ('500002', '500012', '500014', '999999', '543000')])
    bse.loc[bse['bse_code'] == '500002', 'macro'] = 'BSE words'   # must lose to NSE
    sec = pd.DataFrame({'isin': ['INE117A01022', 'INE714B01016', 'INE096A01010', 'INE144J01027'],
                        'nse_symbol': ['ABB', None, None, '20MICRONS'], 'bse_code': ['500002', '500012', '500014', '533022']})
    vr = pd.read_csv(ROOT / 'reference_data' / 'security_master_20260901.csv', dtype=str, keep_default_na=False)
    t, counts = I.build(nse, bse, sec, vr)
    assert list(t.columns) == I.COLUMNS == ['isin', 'nse_symbol', 'bse_code', 'macro', 'sector', 'industry',
                                            'basic_industry', 'source', 'as_of']
    r = t.set_index('isin')
    assert r.loc['INE117A01022', 'source'] == 'nse' and r.loc['INE117A01022', 'macro'] == 'Industrials'
    assert r.loc['INE117A01022', 'bse_code'] == '500002' and r.loc['INE117A01022', 'nse_symbol'] == 'ABB'
    assert r.loc['INE714B01016', 'source'] == 'bse' and r.loc['INE714B01016', 'sector'] == 'Chemicals'
    v = r.loc['INE144J01027']
    assert v['source'] == 'vr_master' and v['sector'] == 'Materials' and v['industry'] == 'Other Minerals'
    assert pd.isna(v['macro']) and pd.isna(v['basic_industry']) and v['as_of'] == pd.Timestamp('2026-09-01')
    assert r.loc['INE117A01022', 'as_of'] == pd.Timestamp(NOW.date())
    assert 'INF789F1AOK7' not in r.index and len(t) == 4
    assert counts == {'nse': 1, 'bse': 2, 'vr_master': 1, 'rows': 4, 'securities_without_class': 0}


def test_bse_due_skips_what_nse_covers():
    import industry as script
    scrips = I.parse_bse_list(fx('bse_listofscripdata_sample.json'))
    sec = pd.DataFrame({'isin': ['INE117A01022', 'INE208C01025', 'INE885A01032'],
                        'nse_symbol': ['ABB', 'AEGISLOG', 'ARE&M'], 'bse_code': ['500002', '500003', '500008']})
    nse_arch = pd.DataFrame({'nse_symbol': ['ABB', 'AEGISLOG'], 'isin': ['INE117A01022', None],
                             'status': ['ok', 'not_found'], 'fetched_at': [NOW, NOW]})
    # AEGISLOG unknown to NSE and AMBALALSA not on NSE come first; ABB and ARE&M (NSE's) after them
    assert script.bse_due(scrips, sec, nse_arch, None, NOW, None) == ['500003', '500009', '500002', '500008']
    assert script.bse_due(scrips, sec, nse_arch, None, NOW, 2) == ['500003', '500009']


def test_store_helpers_merge_by_isin():
    for p in (str(ROOT / 'streamlit_app'), str(ROOT)):
        if p not in sys.path:
            sys.path.insert(0, p)
    from data import store
    assert 'industry' in store.TABLES
    t = pd.DataFrame({'isin': ['INE1', 'INE2'], 'nse_symbol': ['A', None], 'bse_code': ['1', '2'],
                      'macro': ['Energy', None], 'sector': ['Oil', 'Materials'], 'industry': ['X', 'Y'],
                      'basic_industry': ['Z', None], 'source': ['nse', 'vr_master'],
                      'as_of': pd.to_datetime(['2026-11-19', '2026-09-01'])})
    assert store.industry_of('INE1', t)['basic_industry'] == 'Z'
    assert store.industry_of('INE2', t)['macro'] is None and store.industry_of('INE9', t) is None
    df = pd.DataFrame({'isin': ['INE2', 'INE9', 'INE1', 'INE1'], 'sector': ['vr', 'vr', 'vr', 'vr']}, index=[5, 6, 7, 8])
    out = store.with_industry(df, table=t)
    assert list(out.index) == [5, 6, 7, 8] and list(out['sector']) == ['vr'] * 4    # existing column kept
    assert list(out['macro'].fillna('-')) == ['-', '-', 'Energy', 'Energy']
    assert list(out['industry_source'].fillna('-')) == ['vr_master', '-', 'nse', 'nse']
    out = store.with_industry(df, table=t, prefix='ind_')
    assert list(out['ind_sector'].fillna('-')) == ['Materials', '-', 'Oil', 'Oil']
    assert 'macro' in store.with_industry(df, table=pd.DataFrame())
