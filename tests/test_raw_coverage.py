"""Raw coverage audit (scripts/raw_coverage.py): a fake R2 with a few raw_v2 datasets and their tables."""
from __future__ import annotations

import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest
import raw_coverage as rc

from collectors.bse import parsers as bse_parsers
from collectors.nse_events import announcements as nann
from collectors.nse_events import parsers as nse_parsers
from insiders_clean.raw_store import RawStore

ROOT = Path(__file__).resolve().parent.parent


class NoSuchKey(Exception):
    def __init__(self):
        super().__init__('NoSuchKey')
        self.response = {'Error': {'Code': 'NoSuchKey'}}


class FakeR2:
    """Objects in a dict; LIST pages of 3 (so pagination is used), CommonPrefixes for a delimiter. After `freeze()`
    every write or delete is recorded and refused."""

    PAGE = 3

    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.frozen = False
        self.writes: list = []

    def freeze(self):
        self.frozen = True

    def _write(self, op, key):
        if self.frozen:
            self.writes.append((op, key))
            raise PermissionError(f'{op} {key}')

    def put_object(self, Bucket, Key, Body, ContentType=None, IfNoneMatch=None, **kw):
        self._write('put_object', Key)
        self.objects[Key] = Body if isinstance(Body, bytes) else Body.encode()

    def delete_object(self, Bucket, Key, **kw):
        self._write('delete_object', Key)

    def delete_objects(self, Bucket, Delete, **kw):
        self._write('delete_objects', str(Delete))

    def copy_object(self, Bucket, Key, **kw):
        self._write('copy_object', Key)

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise NoSuchKey()
        return {'ContentLength': len(self.objects[Key])}

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise NoSuchKey()
        return {'Body': io.BytesIO(self.objects[Key])}

    def list_objects_v2(self, Bucket, Prefix='', Delimiter=None, ContinuationToken=None, **kw):
        keys = sorted(k for k in self.objects if k.startswith(Prefix))
        prefixes = []
        if Delimiter:
            direct, seen = [], set()
            for k in keys:
                rest = k[len(Prefix):]
                if Delimiter in rest:
                    p = Prefix + rest.split(Delimiter, 1)[0] + Delimiter
                    if p not in seen:
                        seen.add(p)
                        prefixes.append(p)
                else:
                    direct.append(k)
            keys = direct
        start = int(ContinuationToken or 0)
        page = keys[start:start + self.PAGE]
        out = {'Contents': [{'Key': k, 'Size': len(self.objects[k])} for k in page],
               'CommonPrefixes': [{'Prefix': p} for p in prefixes] if start == 0 else []}
        if start + self.PAGE < len(keys):
            out.update(IsTruncated=True, NextContinuationToken=str(start + self.PAGE))
        return out


def parquet(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    return buf.getvalue()


T1 = datetime(2026, 10, 20, 12, 0, 0, 1, tzinfo=timezone.utc)
T2 = datetime(2026, 10, 21, 12, 0, 0, 1, tzinfo=timezone.utc)

NSE_ANN = [
    {'seq_id': '1001', 'symbol': 'ABC', 'sm_isin': 'INE000A01011', 'sm_name': 'Abc Limited', 'desc': 'Outcome of Board Meeting',
     'an_dt': '20-Oct-2026 10:15:00', 'attchmntText': 'Board approved results', 'nsurl': 'https://example.invalid/x1'},
    {'seq_id': '1002', 'symbol': 'XYZ', 'sm_isin': 'INE000B01012', 'sm_name': 'Xyz Limited', 'desc': 'Press Release',
     'an_dt': '20-Oct-2026 11:30:00', 'attchmntText': 'New plant', 'nsurl': 'https://example.invalid/x2'},
]
BSE_ACTIONS = [
    {'scrip_code': '500001', 'long_name': 'Alpha Ltd', 'Purpose': 'Final Dividend - Rs. - 5.0000',
     'Ex_date': '15 Oct 2026', 'RD_Date': '15 Oct 2026'},
    {'scrip_code': '500002', 'long_name': 'Beta Ltd', 'Purpose': 'Interest Payment',
     'Ex_date': '16 Oct 2026', 'RD_Date': '16 Oct 2026'},
]
BSE_ACTIONS_2 = [
    {'scrip_code': '500003', 'long_name': 'Gamma Ltd', 'Purpose': 'Bonus issue 1:2',
     'Ex_date': '17 Oct 2026', 'RD_Date': '17 Oct 2026'},
]
NSE_SAST = [
    {'application_no': 'A1', 'symbol': 'ABC', 'company': 'Abc Limited', 'acquirerName': 'Fund One',
     'acqSaleType': 'Acquisition', 'regType': 'Reg29(1)', 'acquisitionMode': 'Open Market',
     'acquirerDate': '10-Oct-2026 to 12-Oct-2026', 'noOfShareAcq': '1,000', 'noOfShareAft': '50,000',
     'totAftShare': '5.10', 'timestamp': '13-Oct-2026 10:00:00'},
    {'application_no': 'A2', 'symbol': 'XYZ', 'company': 'Xyz Limited', 'acquirerName': 'Fund Two',
     'acqSaleType': 'Sale', 'regType': 'Reg29(2)', 'acquisitionMode': 'Open Market',
     'acquirerDate': '11-Oct-2026', 'noOfShareSale': '2,000', 'noOfShareAft': '9,000',
     'totAftShare': '3.20', 'timestamp': '13-Oct-2026 11:00:00'},
]


def build() -> FakeR2:
    r = FakeR2()
    s1 = RawStore(r, bucket='b', collector='nightly', clock=lambda: T1)
    s2 = RawStore(r, bucket='b', collector='nightly', clock=lambda: T2)
    ann = json.dumps(NSE_ANN).encode()
    s1.put('nse', 'announcements', ann, url='https://www.nseindia.com/api/corporate-announcements?index=equities',
           content_type='application/json', covers={'index': 'equities'})
    acts = json.dumps({'Table': BSE_ACTIONS}).encode()
    s1.put('bse', 'corporate_actions', acts, url='https://api.bseindia.com/BseIndiaAPI/api/DefaultData/w',
           content_type='application/json')
    s2.put('bse', 'corporate_actions', acts, url='https://api.bseindia.com/BseIndiaAPI/api/DefaultData/w',
           content_type='application/json')       # fetched again, same bytes: one blob
    s2.put('nse', 'sast', json.dumps({'data': NSE_SAST}).encode(),
           url='https://www.nseindia.com/api/corporate-sast-reg29', content_type='application/json')
    s1.put('nse', 'mystery_feed', b'{"a": 1}', url='https://example.invalid/mystery', content_type='application/json')
    s1.put('nse', 'asm', b'{"data": []}', url='https://www.nseindia.com/api/reportASM', content_type='application/json')
    # tables: announcements as the collector parsed them, with one stored value changed (a value mismatch)
    ann_df = nann.parse(NSE_ANN, 'equities')
    ann_df.loc[ann_df['seq_id'] == '1002', 'subject'] = 'Something else'
    r.objects['archive/announcements/nse/year=2026/month=10.parquet'] = parquet(ann_df)
    # BSE actions: every kept row stored
    act_df, _ = bse_parsers.parse_actions(BSE_ACTIONS)
    r.objects['archive/bse_events/actions/year=2026.parquet'] = parquet(act_df)
    # NSE SAST: one of the two filings never reached the archive
    sast_df = nse_parsers.parse_sast(NSE_SAST)
    r.objects['archive/nse_events/sast/year=2026.parquet'] = parquet(sast_df[sast_df['application_no'] == 'A1'])
    r.objects['raw/nse/insider_trading/2026-10-01/data.json.gz'] = b'x' * 10
    r.freeze()
    return r


@pytest.fixture()
def r2():
    return build()


def by(report, source, dataset):
    return next(d for d in report['datasets'] if d['source'] == source and d['dataset'] == dataset)


def test_datasets_are_discovered_by_listing(r2):
    rep = rc.run(r2, 'b', sample=10, max_blobs=50)
    found = {(d['source'], d['dataset']) for d in rep['datasets']}
    assert found == {('nse', 'announcements'), ('bse', 'corporate_actions'), ('nse', 'sast'),
                     ('nse', 'mystery_feed'), ('nse', 'asm')}


def test_counts(r2):
    rep = rc.run(r2, 'b', sample=10, max_blobs=50)
    a = by(rep, 'bse', 'corporate_actions')
    assert a['inventory']['fetch_records'] == 2
    assert a['inventory']['distinct_blobs'] == 1
    assert a['inventory']['fetch_days'] == 2
    assert (a['inventory']['first_day'], a['inventory']['last_day']) == ('2026-10-20', '2026-10-21')
    assert a['inventory']['blob_bytes'] > 0
    assert a['reparsed']['how'] == 'all 1 blobs'
    c = a['counts']
    assert (c['raw_rows'], c['parsed_rows'], c['in_table'], c['missing_from_table']) == (2, 1, 1, 0)
    assert c['unexplained_drop'] == 0
    n = by(rep, 'nse', 'announcements')['counts']
    assert (n['raw_rows'], n['parsed_rows'], n['in_table']) == (2, 2, 2)


def test_dropped_row_reported_with_parser_reason(r2):
    a = by(rc.run(r2, 'b', sample=10, max_blobs=50), 'bse', 'corporate_actions')
    assert a['counts']['dropped'] == {'purpose not kept (action_purpose)': 1}
    # everything kept is stored, every raw field is in raw_json: captured, but the design drop is said
    assert a['verdict'].startswith('fully captured')
    assert 'drops by design' in a['verdict'] and 'deleting raw loses them' in a['verdict']
    assert set(a['fields']['kept_in_raw_json']) | set(a['fields']['kept_as_column']) >= {'scrip_code', 'Purpose', 'Ex_date'}


def test_row_missing_from_table_is_a_gap(r2):
    s = by(rc.run(r2, 'b', sample=10, max_blobs=50), 'nse', 'sast')
    assert s['counts']['parsed_rows'] == 2 and s['counts']['in_table'] == 1 and s['counts']['missing_from_table'] == 1
    assert s['verdict'].startswith('gaps:') and '1 of 2 parsed rows not in archive/nse_events/sast/' in s['verdict']


def test_unkept_field_detected(r2):
    a = by(rc.run(r2, 'b', sample=10, max_blobs=50), 'nse', 'announcements')
    assert 'nsurl' in a['fields']['not_kept']          # the parser has no column for it and the archive no raw_json
    assert 'seq_id' in a['fields']['kept_as_column']
    assert 'an_dt' in a['fields']['value_found_in_a_column']    # renamed to broadcast_at
    assert 'nsurl' in a['verdict']


def test_value_mismatch_found(r2):
    a = by(rc.run(r2, 'b', sample=10, max_blobs=50), 'nse', 'announcements')
    assert a['values_compared'] == 2
    assert [(m['key'], m['field'], m['raw'], m['stored']) for m in a['mismatches']] == \
        [('nse:1002', 'subject', 'Press Release', 'Something else')]
    assert a['verdict'].startswith('gaps:') and '1 value mismatches' in a['verdict']


def test_dataset_without_parser_and_not_wired(r2):
    rep = rc.run(r2, 'b', sample=10, max_blobs=50)
    m = by(rep, 'nse', 'mystery_feed')
    assert m['verdict'] == 'no parser found' and m['inventory']['fetch_records'] == 1
    asm = by(rep, 'nse', 'asm')
    assert asm['verdict'].startswith('not checked:') and 'parse_surveillance' in asm['parser']


def test_bounded_sample_is_not_checked(r2):
    r2.frozen = False
    RawStore(r2, bucket='b', collector='nightly', clock=lambda: T2).put(
        'bse', 'corporate_actions', json.dumps({'Table': BSE_ACTIONS_2}).encode(),
        url='https://api.bseindia.com/BseIndiaAPI/api/DefaultData/w', content_type='application/json')
    act_df, _ = bse_parsers.parse_actions(BSE_ACTIONS + BSE_ACTIONS_2)
    r2.objects['archive/bse_events/actions/year=2026.parquet'] = parquet(act_df)
    r2.freeze()
    a = by(rc.run(r2, 'b', sources={'bse'}, sample=5, max_blobs=1), 'bse', 'corporate_actions')
    assert a['inventory']['distinct_blobs'] == 2 and a['reparsed']['blobs'] == 1
    assert a['verdict'].startswith('not checked: only 1 of 2 blobs re-parsed')


def test_missing_blob_and_old_raw_layout(r2):
    r2.frozen = False
    for k in [k for k in r2.objects if k.startswith('raw_v2/nse/sast/blobs/')]:
        del r2.objects[k]
    r2.freeze()
    rep = rc.run(r2, 'b', sample=5, max_blobs=50)
    s = by(rep, 'nse', 'sast')
    assert s['inventory']['records_without_blob_by_name'] == 1
    assert 'blob is gone' in s['verdict']
    assert rep['old_raw'] == [{'prefix': 'raw/nse/insider_trading', 'objects': 1, 'bytes': 10,
                               'verdict': rep['old_raw'][0]['verdict']}]


def test_nothing_written_and_report_renders(r2):
    rep = rc.run(r2, 'b', sample=5, max_blobs=50)
    assert r2.writes == []
    ro = rc.ReadOnly(r2, 'b')
    for name in ('put_object', 'delete_object', 'delete_objects', 'copy_object', 'client'):
        assert not hasattr(ro, name)
    text = rc.markdown(rep)
    assert '### raw_v2/nse' in text and '### raw_v2/bse' in text and '| mystery_feed |' in text
    assert 'no parser found' in text and '0 writes' in text
    json.dumps(rep, default=str)


def test_one_dataset_failing_does_not_stop_the_others(r2, monkeypatch):
    spec = rc.spec_for('nse', 'sast')

    def boom(*a, **k):
        raise RuntimeError('stored table unreadable')
    monkeypatch.setattr(spec, 'stored', boom)
    rep = rc.run(r2, 'b', sample=5, max_blobs=50)
    assert by(rep, 'nse', 'sast')['verdict'] == 'not checked: audit failed (RuntimeError)'
    assert by(rep, 'bse', 'corporate_actions')['verdict'].startswith('fully captured')


def test_time_budget_reached_is_said(r2):
    rep = rc.run(r2, 'b', sample=5, max_blobs=50, budget_s=0)
    assert {d['verdict'] for d in rep['datasets']} == {'not checked: time budget reached'}
    assert by(rep, 'nse', 'sast')['inventory']['fetch_records'] == 1


def test_norm():
    assert rc.norm('1,234') == rc.norm(1234.0) == '1234'
    assert rc.norm('15-Oct-2025') == rc.norm(pd.Timestamp('2025-10-15')) == '2025-10-15'
    assert rc.norm('2026-10-20T10:15:00+05:30') == rc.norm('20-Oct-2026 10:15:00') == '2026-10-20 10:15'
    assert rc.norm('-') is None and rc.norm(float('nan')) is None
    assert rc.norm('  Press  Release ') == 'press release'


def _flat(text: str) -> str:
    return ' '.join(text.split())


def test_refetch_quotes_are_in_the_files_they_cite():
    for s in rc.SPECS:
        if s.refetch == 'unknown':
            assert s.refetch_ref == ''
            continue
        assert s.refetch_ref, s.dataset
        assert _flat(s.refetch) in _flat((ROOT / s.refetch_ref).read_text(encoding='utf-8')), (s.dataset, s.refetch)


def test_specs_name_real_parsers():
    """Every parser a spec names exists where it says (nothing invented): module.function, a bare function of the
    module named before it, or a script path."""
    import importlib
    for s in rc.SPECS:
        module, script = None, None
        for part in re.split(r'\s*->\s*', s.parser):
            head = part.split(' ', 1)[0]
            if '/' in head:
                script = (ROOT / head).read_text(encoding='utf-8')
                for name in re.findall(r'\b([a-z_]+)\b', part.split(' ', 1)[1] if ' ' in part else ''):
                    assert f'def {name}(' in script, (s.dataset, part)
                continue
            if script is not None and '.' not in head:
                assert f'def {head}(' in script, (s.dataset, part)
                continue
            m = re.match(r'^([a-z_0-9]+(?:\.[a-z_0-9]+)*)\.([A-Za-z_0-9]+)$', head)
            if m:
                mod, name = m.groups()
                try:
                    module = importlib.import_module(mod)
                except ModuleNotFoundError:
                    module = importlib.import_module(mod.rsplit('.', 1)[-1])     # scripts on sys.path
            else:
                name = head
            assert module is not None and hasattr(module, name), (s.dataset, part)


# --- every wired adapter on real exchange answers (tests/fixtures), stored the way the collector stores them ------

FIX = ROOT / 'tests' / 'fixtures'
RUN = '2026-10-20'


def _rows(path):
    data = json.loads((FIX / path).read_text(encoding='utf-8'))
    if isinstance(data, dict):
        data = data.get('data') or data.get('Table') or []
    return data


def _events(parse):
    def build(path):
        from insiders_clean import archive
        out = parse(_rows(path))
        df = out[0] if isinstance(out, tuple) else out
        return archive.merge(None, df, RUN, key='event_id')[0]
    return build


def _canonical(exchange, category, mapped):
    import r2_writer

    from insiders_clean import archive
    body, _ = r2_writer.rows_to_parquet_bytes(exchange, category, mapped)
    return archive.merge(None, pd.read_parquet(io.BytesIO(body)), RUN)[0]


def _bse_meetings_table(path):
    from insiders_clean import archive
    data = json.loads((FIX / path).read_text(encoding='utf-8'))
    return archive.merge(None, bse_parsers.parse_board_meetings(data)[0], RUN, key='event_id')[0]


def _history():
    from insiders_clean import history
    return history


ROUND_TRIP = [
    ('nse', 'sast', 'nse_events/sast_reg29.json', 'archive/nse_events/sast/', _events(nse_parsers.parse_sast)),
    ('nse', 'actions', 'nse_events/corporate_actions.json', 'archive/nse_events/actions/',
     _events(nse_parsers.parse_corporate_actions)),
    ('nse', 'meetings', 'nse_events/board_meetings.json', 'archive/nse_events/meetings/',
     _events(nse_parsers.parse_board_meetings)),
    ('nse', 'encumbrances', 'nse_events/encumbrances_202610.json', 'archive/nse_events/encumbrances/',
     _events(nse_parsers.parse_encumbrances)),
    ('nse', 'daily_buybacks', 'nse_events/daily_buybacks.json', 'archive/nse_events/daily_buybacks/',
     _events(nse_parsers.parse_daily_buybacks)),
    ('nse', 'tenders', 'nse_events/tender_offers_past.json', 'archive/nse_events/tenders/',
     _events(nse_parsers.parse_tender_offers)),
    ('nse', 'shareholding_list', 'nse_events/shareholding_listing.json', 'archive/nse_events/shareholding/',
     _events(nse_parsers.parse_shareholding_listing)),
    ('nse', 'announcements', 'nse_events/announcements.json', 'archive/announcements/nse/',
     _events(lambda rows: nann.parse(rows, 'equities'))),
    ('bse', 'sast', 'bse/sast_202511.json', 'archive/bse_events/sast/', _events(bse_parsers.parse_sast)),
    ('bse', 'corporate_actions', 'bse/actions_20251008_20251015.json', 'archive/bse_events/actions/',
     _events(bse_parsers.parse_actions)),
    ('bse', 'board_meetings', 'bse/board_meetings_202602.json', 'archive/bse_events/meetings/', _bse_meetings_table),
    ('bse', 'shareholding_filings', 'bse/shareholding_listing_20261012.json', 'archive/bse_events/shareholding/',
     _events(bse_parsers.parse_shareholding_listing)),
    ('bse', 'bulk_deals_history', 'bse/bulk_history_20261009.json', 'archive/canonical/bse/bulk_deals/',
     lambda p: _canonical('bse', 'bulk_deals', bse_parsers.deal_rows(_rows(p)))),
    ('bse', 'block_deals_history', 'bse/block_history_20261008.json', 'archive/canonical/bse/block_deals/',
     lambda p: _canonical('bse', 'block_deals', bse_parsers.deal_rows(_rows(p)))),
    ('bse', 'insider_csv', 'bse/insider_20261001_20261010.csv', 'archive/canonical/bse/insider_trading/',
     lambda p: _canonical('bse', 'insider_trading', bse_parsers.insider_rows((FIX / p).read_bytes()))),
    ('nse', 'insider', 'history/nse_pit_2024.json', 'archive/canonical/nse/insider_trading/',
     lambda p: _canonical('nse', 'insider_trading', [_history().pit_row(r) for r in _rows(p)])),
    ('nse', 'bulk_deals', 'history/nse_bulk_2024.csv', 'archive/canonical/nse/bulk_deals/',
     lambda p: _canonical('nse', 'bulk_deals', _history().deal_rows((FIX / p).read_bytes()))),
]


@pytest.mark.parametrize('source,dataset,path,table,build_table', ROUND_TRIP, ids=[f'{s}/{d}' for s, d, *_ in ROUND_TRIP])
def test_round_trip_on_real_answers(source, dataset, path, table, build_table):
    """Raw as the exchange sent it, the table as the collector writes it: every parsed row is found by the parser's
    key, and no sampled value differs (the comparison itself raises no false alarm)."""
    r = FakeR2()
    body = (FIX / path).read_bytes()
    RawStore(r, bucket='b', collector='nse_history_backfill' if dataset.endswith('deals') else 'nightly',
             clock=lambda: T1).put(source, dataset, body, url='https://example.invalid/api',
                                   content_type='text/csv' if path.endswith('.csv') else 'application/json')
    r.objects[f'{table}year=2026.parquet'] = parquet(build_table(path))
    r.freeze()
    d = by(rc.run(r, 'b', sample=50, max_blobs=10), source, dataset)
    c = d['counts']
    assert c['parse_errors'] == {} and c['parsed_rows'] > 0
    assert c['missing_from_table'] == 0 and c['in_table'] == c['parsed_keys']
    assert c['unexplained_drop'] == 0, c
    assert d['mismatches'] == [], d['mismatches'][:3]
    assert d['values_compared'] > 0
    assert r.writes == []


def test_price_file_unkept_columns_and_values():
    from insiders_clean import prices
    head = list(prices._MAP) + ['FinInstrmTp', 'OptnTp']
    lines = [','.join(head),
             ','.join(['2026-10-20', 'NSE', 'INE000A01011', 'ABC', 'EQ', 'Abc Ltd', '1', '10', '12', '9', '11', '11',
                       '10', '11', '1000', '11000', '50', 'STK', '']),
             ','.join(['2026-10-20', 'NSE', 'INE000B01012', 'XYZ', 'EQ', 'Xyz Ltd', '2', '20', '22', '19', '21', '21',
                       '20', '21', '500', '10500', '20', 'STK', ''])]
    body = ('\n'.join(lines) + '\n').encode()
    r = FakeR2()
    RawStore(r, bucket='b', collector='price_backfill', clock=lambda: T1).put(
        'exchange_files', 'nse_udiff_cm', body, url='https://example.invalid/BhavCopy.csv', content_type='text/csv',
        covers={'day': '2026-10-20'})
    stored = prices.parse_udiff(body, 'NSE')
    stored.loc[stored['symbol'] == 'XYZ', 'close'] = 99.0
    r.objects['prices/daily/nse/2026-10.parquet'] = parquet(stored)
    r.freeze()
    d = by(rc.run(r, 'b', sample=5, max_blobs=10), 'exchange_files', 'nse_udiff_cm')
    assert d['counts']['parsed_rows'] == 2 and d['counts']['in_table'] == 2
    assert d['fields']['not_kept'] == ['FinInstrmTp', 'OptnTp']
    assert [(m['field'], m['stored']) for m in d['mismatches']] == [('close', '99')]
    assert d['verdict'].startswith('gaps:') and r.writes == []


def test_shareholding_xbrl_kept_gzipped_by_the_collector():
    """raw_v2/nse/shareholding_xbrl: gzipped before the store (run_daily._keep_raw), un-gzipped and checked against
    sha256_as_sent, parsed with parse_shp_xbrl, found on the archive row by record_id."""
    import gzip

    from insiders_clean import archive, raw_store
    xml = (FIX / 'nse_events' / 'shp_ZEEL_2026Q2.xml').read_bytes()
    r = FakeR2()
    RawStore(r, bucket='b', collector='nightly', clock=lambda: T1).put(
        'nse', 'shareholding_xbrl', gzip.compress(xml, 9, mtime=0), url='https://example.invalid/shp.xml',
        content_type='application/gzip',
        params={'record_id': '123', 'symbol': 'ZEEL', 'stored_as': 'gzip', 'sha256_as_sent': raw_store.sha256_hex(xml)})
    facts = nse_parsers.parse_shp_xbrl(xml.decode())
    row = pd.DataFrame([{'event_id': 'e1', 'record_id': '123', 'symbol': 'ZEEL', **facts}])
    row.loc[0, 'total_shares'] = facts['total_shares'] + 1
    r.objects['archive/nse_events/shareholding/year=2026.parquet'] = parquet(archive.merge(None, row, RUN, key='event_id')[0])
    r.freeze()
    d = by(rc.run(r, 'b', sample=5, max_blobs=10), 'nse', 'shareholding_xbrl')
    assert d['blob_status'] == {} and d['counts']['parsed_rows'] == 1 and d['counts']['in_table'] == 1
    assert [m['field'] for m in d['mismatches']] == ['total_shares']
    assert d['fields']['applicable'] is False and 'parse_shp_xbrl' in d['fields']['note']


def test_fund_house_workbook_round_trip():
    """A month-end workbook (raw_v2/amc/{house}/portfolio_month), stored as scripts/mf_portfolios.put_schemes does."""
    import openpyxl

    from collectors.mf_portfolios.houses import BY_KEY
    from insiders_clean import mf_holdings
    sheet = [['SCHEME NAME :', 'SBI Large Cap Fund'], [],
             ['Name of the Instrument / Issuer', 'ISIN', 'Rating / Industry^', 'Quantity', 'Market value\n(Rs. in Lakhs)', '% to AUM'],
             ['ICICI Bank Ltd.', 'INE090A01021', 'Banks', 3114000, 43533.72, 8.69],
             ['HDFC Bank Ltd.', 'INE040A01034', 'Banks', 5389800, 37340.53, 7.45],
             ['7.32% GOI 2030', 'IN0020230135', 'SOV', 100000, 101.2, 0.1]]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'SLCF'
    for row in sheet:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    body = buf.getvalue()
    house = BY_KEY['sbi']
    r = FakeR2()
    RawStore(r, bucket='b', collector='mf', clock=lambda: T1).put(
        'amc', 'sbi/portfolio_month', body, url='https://example.invalid/sbi/portfolio-oct-2026.xlsx',
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', covers={'month': '2026-10'})
    rows, _ = mf_holdings.parse_workbook(body, 'portfolio-oct-2026.xlsx', house.value_unit)
    sc = mf_holdings.scheme_holdings(rows, 'sbi', '2026-10', house.name)
    r.objects['archive/mf_schemes/month=2026-10/sbi.parquet'] = parquet(sc[sc['isin'] != 'INE040A01034'])
    r.freeze()
    d = by(rc.run(r, 'b', sample=5, max_blobs=10), 'amc', 'sbi/portfolio_month')
    c = d['counts']
    assert (c['raw_rows'], c['parsed_rows'], c['in_table'], c['missing_from_table']) == (3, 2, 1, 1)
    assert c['dropped'] == {'non-equity lines (not in mf_schemes by design)': 1} and c['unexplained_drop'] == 0
    assert d['fields'] == {'applicable': False, 'note': rc.spec_for('amc', 'sbi/portfolio_month').fields_note}
    assert d['values_compared'] == 1 and d['mismatches'] == []
    assert d['verdict'].startswith('gaps: 1 of 2 parsed rows not in') and r.writes == []
