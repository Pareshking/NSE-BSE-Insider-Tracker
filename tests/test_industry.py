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


# ---- saved as it goes, resumed, rebuilt from what R2 holds (20 Nov 2026) --------------------------

import io  # noqa: E402
from datetime import timezone  # noqa: E402


class FakeBSE:
    """BSEClient's surface the fetch uses: the scrip list, then one header per code, each answer captured for raw like
    the real client's raw hook. `stop_after`: raise KeyboardInterrupt after that many headers (a cancelled job)."""

    def __init__(self, stop_after=None):
        self.calls, self.via, self.asked, self.stop_after = 0, 'requests', [], stop_after

    def get(self, path, params, dataset, covers=None):
        import industry as script
        self.calls += 1
        if path == script.BSE_LIST:
            body = (FIX / 'bse_listofscripdata_sample.json').read_bytes()
        else:
            code = params['scripcode']
            if self.stop_after is not None and len(self.asked) >= self.stop_after:
                raise KeyboardInterrupt
            self.asked.append(code)
            f = FIX / f'bse_comheadernew_{code}.json'
            body = (f if f.exists() else FIX / 'bse_comheadernew_999999.json').read_bytes()
        script.RawCapture().put('bse', dataset, body, url=script.BSE_API + path, params=params,
                                content_type='application/json', covers=dict(covers or {}, via=self.via))
        return body

    def close(self):
        pass


def _r2(tmp_path, monkeypatch):
    """R2 double: raw keys write-once (OnceR2), every other key overwritable like R2 itself."""
    import raw_capture
    from test_raw_store import OnceR2
    monkeypatch.setattr(raw_capture, 'DIR', tmp_path / 'raw')

    class R2(OnceR2):
        def put_object(self, Bucket, Key, Body, ContentType=None, IfNoneMatch=None):
            if Key.startswith('raw_v2/'):
                return super().put_object(Bucket, Key, Body, ContentType, IfNoneMatch)
            self.objects[Key] = Body
    return R2()


def _pq(r2, key):
    return pd.read_parquet(io.BytesIO(r2.objects[key]))


def _staged(r2):
    return {k: _pq(r2, k) for k in r2.objects if k.startswith('staging/industry/') and k.endswith('.parquet')}


def test_parse_raw_reads_a_stored_answer_like_the_fetch():
    body = (FIX / 'bse_comheadernew_500002.json').read_bytes()
    rec = {'http_status': 200, 'url': 'https://api.bseindia.com/BseIndiaAPI/api/ComHeadernew/w',
           'params': {'quotetype': 'EQ', 'scripcode': '500002', 'seriesid': ''},
           'covers': {'scripcode': '500002', 'via': 'requests'}, 'fetched_at_utc': '2026-11-20T05:00:00.000001+00:00'}
    r = I.parse_raw('bse', rec, body)
    assert r['bse_code'] == '500002' and r['status'] == 'ok' and r['sector'] == 'Capital Goods'
    assert r['fetched_at'] == datetime(2026, 11, 20, 5, 0, 0, 1)
    assert I.parse_raw('bse', {**rec, 'http_status': 403}, body) is None
    assert I.parse_raw('bse', rec, None) is None
    assert I.parse_raw('bse', rec, b'<html>')['status'] == 'error'   # what the fetch recorded for an HTML page
    nse = {'http_status': 200, 'url': 'https://www.nseindia.com/api/quote-equity?symbol=ABB', 'covers': {},
           'fetched_at_utc': '2026-11-20T05:00:00+00:00'}
    body = json.dumps(nse_answer({'macro': 'Industrials'})).encode()
    assert I.parse_raw('nse', nse, body)['nse_symbol'] == 'ABB'
    assert I.parse_raw('nse', {**nse, 'url': 'https://www.nseindia.com/'}, body) is None


def test_flush_side_by_side_stores_everything(tmp_path, monkeypatch):
    import raw_capture
    import raw_flush
    from test_raw_store import OnceR2
    monkeypatch.setattr(raw_capture, 'DIR', tmp_path)
    for n in range(40):
        raw_capture.capture('bse', 'comheadernew', f'{{"n": {n}}}', url='u', covers={'scripcode': str(n)})
    assert not list(tmp_path.glob('*.part'))
    r2 = OnceR2()
    res = raw_flush.flush(r2, tmp_path, bucket='b', workers=8)
    assert (res['found'], res['stored'], res['failed'], res['blobs_written']) == (40, 40, 0, 40)
    assert not list(tmp_path.iterdir()) and sum('/fetches/' in k for k in r2.objects) == 40


def test_saver_pushes_raw_and_a_checkpoint_every_n_answers(tmp_path, monkeypatch):
    import raw_capture

    import industry as script
    r2 = _r2(tmp_path, monkeypatch)
    live = {'nse': [], 'bse': []}
    t = [0.0]
    saver = script.Saver(r2, 'run1', live, every=2, minutes=10, workers=4, clock=lambda: t[0])
    assert not saver.due()
    for n, code in enumerate(['500002', '500014', '500012']):
        raw_capture.capture('bse', 'comheadernew', (FIX / f'bse_comheadernew_{code}.json').read_bytes(), url='u',
                            covers={'scripcode': code})
        live['bse'].append({**I.parse_bse(fx(f'bse_comheadernew_{code}.json'), code), 'fetched_at': NOW})
        if saver.due():
            saver.save({'run': 'run1'})
    assert saver.stats['saves'] == 1 and saver.stats['raw_stored'] == 2       # after the second answer
    assert len(_pq(r2, 'staging/industry/run1/bse.parquet')) == 2
    assert json.loads(r2.objects['staging/industry/run1/fetch_report.json']) == {'run': 'run1'}
    t[0] = 601                                                                  # ten minutes on: the third goes too
    assert saver.due()
    saver.save()
    assert saver.stats['raw_stored'] == 3 and len(_pq(r2, 'staging/industry/run1/bse.parquet')) == 3
    assert not list((tmp_path / 'raw').glob('*.json'))
    assert not saver.due()                                                      # nothing new since


def test_a_failed_save_never_stops_the_fetch(tmp_path, monkeypatch):
    import industry as script
    r2 = _r2(tmp_path, monkeypatch)

    def down(**kw):
        raise RuntimeError('R2 down')
    r2.put_object = down
    saver = script.Saver(r2, 'run1', {'bse': [{'bse_code': '1', 'status': 'ok', 'fetched_at': NOW}]}, every=1)
    stats = saver.save()
    assert stats['failed_saves'] == 1 and stats['saves'] == 0 and 'R2 down' in stats['errors'][-1]
    assert saver.due()   # tried again at the next save


def test_a_fetch_whose_exchange_dies_mid_way_still_stores_what_it_read(tmp_path, monkeypatch):
    import threading

    import industry as script
    r2 = _r2(tmp_path, monkeypatch)
    saver = script.Saver(r2, 'run1', every=1, minutes=60, workers=4)
    bse = FakeBSE(stop_after=3)   # the BSE thread dies while asking the fourth scrip
    hook = threading.excepthook
    threading.excepthook = lambda args: None
    try:
        script.fetch(r2, tmp_path / 'out', ['bse'], None, 60, {}, bse=bse, saver=saver, run='run1')
    finally:
        threading.excepthook = hook
    assert bse.asked == ['500002', '500003', '500008']
    assert len(_pq(r2, 'staging/industry/run1/bse.parquet')) == 3
    assert sum(k.startswith('raw_v2/bse/comheadernew/fetches/') for k in r2.objects) == 3
    assert sum(k.startswith('raw_v2/bse/scrip_list/fetches/') for k in r2.objects) == 1


def test_resume_skips_what_an_earlier_run_answered_and_build_merges_the_checkpoints(tmp_path, monkeypatch):
    import industry as script
    from clean_writer import put_parquet
    r2 = _r2(tmp_path, monkeypatch)
    rows = [{**I.parse_bse(fx('bse_comheadernew_500002.json'), '500002'), 'fetched_at': NOW},
            {**I.parse_bse(fx('bse_comheadernew_999999.json'), '500003'), 'fetched_at': NOW}]
    put_parquet(r2, 'staging/industry/run1/bse.parquet', pd.DataFrame(rows, columns=I.BSE_ARCHIVE_COLUMNS))
    monkeypatch.setattr(script, 'now_utc', lambda: NOW + timedelta(hours=1))
    bse = FakeBSE()
    rep = script.fetch(r2, tmp_path / 'out', ['bse'], None, 60, {}, bse=bse,
                       saver=script.Saver(r2, 'run2', every=1000, minutes=60), run='run2')
    assert bse.asked == ['500008', '500009']             # 500002 and 500003 answered by run1
    assert rep['staging'] == {'objects': 1, 'nse': 0, 'bse': 2} and 'bse' not in rep['raw']   # raw only when nothing else
    assert rep['saves']['saves'] == 1 and len(_pq(r2, 'staging/industry/run2/bse.parquet')) == 2
    out = script.build(r2, None, NOW.date(), {})
    assert out['bse_archive']['rows'] == 4 and out['bse_archive']['rows_before'] == 0
    assert sorted(_pq(r2, script.ARCHIVE['bse'])['bse_code']) == ['500002', '500003', '500008', '500009']
    assert _pq(r2, script.CLEAN_KEY).set_index('isin').loc['INE117A01022', 'source'] == 'bse'
    bse3 = FakeBSE()   # a third run asks nothing more: everything is answered and fresh
    script.fetch(r2, tmp_path / 'out3', ['bse'], None, 60, {}, bse=bse3, saver=script.Saver(r2, 'run3'), run='run3')
    assert bse3.asked == []


def test_with_no_archive_or_checkpoint_the_answers_in_raw_are_read(tmp_path, monkeypatch):
    import industry as script
    from insiders_clean.raw_store import RawStore
    r2 = _r2(tmp_path, monkeypatch)
    store = RawStore(r2, bucket='b', collector='industry')
    for n, code in enumerate(['500002', '500014', '999999', '500002']):
        body = (FIX / f'bse_comheadernew_{code}.json').read_bytes()
        body += b' ' * (1100 if code == '500014' else 0)   # past raw_store.GZIP_MIN_BYTES: kept gzipped
        store.put('bse', 'comheadernew', body,
                  url=script.BSE_API + script.BSE_HEADER, params={'quotetype': 'EQ', 'scripcode': code, 'seriesid': ''},
                  content_type='application/json', covers={'scripcode': code, 'via': 'requests'},
                  fetched_at=datetime(2026, 11, 19, 16, n, tzinfo=timezone.utc))
    assert sum(k.endswith('.json.gz') for k in r2.objects) == 1
    out = script.build(r2, None, NOW.date(), {})
    assert out['raw']['bse']['fetch_records'] == 4 and out['raw']['bse']['answers'] == 4
    assert out['raw']['bse']['status'] == {'ok': 2, 'not_found': 1}   # 500002 twice: the later answer kept
    assert out['raw']['nse']['fetch_records'] == 0
    clean = _pq(r2, script.CLEAN_KEY)
    assert set(clean.loc[clean['source'] == 'bse', 'isin']) == {'INE117A01022', 'INE096A01010'}
    assert len(_pq(r2, script.ARCHIVE['bse'])) == 3
    assert 'bse' not in script.build(r2, None, NOW.date(), {})['raw']   # the archive exists now: raw is not read again
    # a fetch on a bucket with raw only keeps what it parsed as its own checkpoint and asks only the rest
    r2b = _r2(tmp_path / 'b', monkeypatch)
    r2b.objects.update({k: v for k, v in r2.objects.items() if k.startswith('raw_v2/')})
    monkeypatch.setattr(script, 'now_utc', lambda: NOW + timedelta(days=1))
    bse = FakeBSE()
    rep = script.fetch(r2b, tmp_path / 'out', ['bse'], None, 60, {}, bse=bse, saver=script.Saver(r2b, 'r'), run='r')
    assert rep['raw']['bse']['symbols'] == 3 and 'staging/industry/r-raw/bse.parquet' in r2b.objects
    assert '500002' not in bse.asked and '500003' in bse.asked


def test_build_deletes_only_old_checkpoints(tmp_path, monkeypatch):
    import industry as script
    from clean_writer import put_parquet
    r2 = _r2(tmp_path, monkeypatch)
    row = pd.DataFrame([{**I.parse_bse(fx('bse_comheadernew_500002.json'), '500002'), 'fetched_at': NOW}],
                       columns=I.BSE_ARCHIVE_COLUMNS)
    put_parquet(r2, 'staging/industry/old/bse.parquet', row)
    put_parquet(r2, 'staging/industry/new/bse.parquet', row)
    stamp = {'staging/industry/old/bse.parquet': datetime.now(timezone.utc) - timedelta(days=3),
             'staging/industry/new/bse.parquet': datetime.now(timezone.utc)}
    plain = r2.list_objects_v2
    r2.list_objects_v2 = lambda **kw: {**plain(**kw), 'Contents': [
        {**o, 'LastModified': stamp.get(o['Key'])} for o in plain(**kw)['Contents']]}
    out = script.build(r2, None, NOW.date(), {})
    assert out['staging_deleted'] == 1 and r2.deleted == ['staging/industry/old/bse.parquet']
    assert out['bse_archive']['rows'] == 1 and script.ARCHIVE['bse'] in r2.objects


# ---- BSE asked side by side (speed test 20 Nov 2026, PR #313) -----------------------------------

def test_bse_parallel_fetches_every_code_once(tmp_path, monkeypatch):
    import time as _t

    import industry as script
    monkeypatch.setattr(__import__('raw_capture'), 'DIR', tmp_path / 'raw')
    made = []

    def factory():
        made.append(FakeBSE())
        return made[-1]
    codes = ['500002', '500012', '500014', '543000', '999999', '500003', '500004']
    rows, report = [], {}
    df = script.fetch_bse_parallel(codes, report, _t.monotonic() + 60, tmp_path / 'bse.parquet', rows=rows,
                                   workers=3, client_factory=factory)
    assert len(made) == 3 and sorted(c for f in made for c in f.asked) == sorted(codes)
    assert len(df) == len(codes) == len(rows) and set(df['bse_code'].astype(str)) == set(codes)
    assert report['bse']['workers'] == 3 and report['bse']['fetched'] == 7 and 'stopped' not in report['bse']
    assert len(pd.read_parquet(tmp_path / 'bse.parquet')) == 7


def test_bse_parallel_one_refusal_stops_every_worker(tmp_path, monkeypatch):
    import threading
    import time as _t

    import industry as script
    monkeypatch.setattr(__import__('raw_capture'), 'DIR', tmp_path / 'raw')
    gate = threading.Event()

    class Refused(FakeBSE):
        def get(self, path, params, dataset, covers=None):
            gate.set()
            raise script.BSEBlocked('HTTP 403 from header (requests)')

    class Slow(FakeBSE):
        def get(self, path, params, dataset, covers=None):
            gate.wait(5)
            _t.sleep(0.05)
            return super().get(path, params, dataset, covers)
    made = iter([Refused(), Slow()])
    codes = [f'5{n:05d}' for n in range(40)]
    report = {}
    df = script.fetch_bse_parallel(codes, report, _t.monotonic() + 60, None, workers=2,
                                   client_factory=lambda: next(made))
    assert report['bse']['stopped'].startswith('refused (HTTP 403')
    assert len(df) < 20   # the slow worker stopped well before its 20 codes
    assert 'another worker' in report['bse']['by_worker']['w1']['stopped']
