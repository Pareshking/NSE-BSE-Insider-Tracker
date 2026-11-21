"""Every line of every fund-house file reaches the archive (owner, 21 Nov 2026: nothing may exist only in raw).

insiders_clean/mf_holdings.parse_workbook_lines, scripts/mf_portfolios.py (put_lines, run_house, backfill_lines) and
the raw coverage audit's amc adapter. Fakes and fixtures only, no network."""
from __future__ import annotations

import io
import json
import types
import zipfile
from datetime import datetime, timezone

import mf_portfolios as mp
import pandas as pd
import pytest
import raw_capture
import raw_coverage as rc
from test_mf_holdings import INDEX, NPS_CG, NPS_E1, SCHEME, _book
from test_raw_coverage import FakeR2, NoSuchKey, by

from collectors.mf_portfolios import find
from collectors.mf_portfolios.find import House
from insiders_clean import mf_holdings as m
from insiders_clean.raw_store import RawStore, sha256_hex

T1 = datetime(2026, 11, 20, 12, 0, 0, 1, tzinfo=timezone.utc)

# A scheme with every kind of section the SEBI format has, and lines without an ISIN under them.
FULL = [['ABC Mutual Fund'], ['SCHEME NAME :', 'ABC Balanced Advantage Fund'], ['PORTFOLIO STATEMENT AS ON :', '31-10-2026'], [],
        ['Name of the Instrument', 'ISIN', 'Rating / Industry^', 'Quantity', 'Market value (Rs. in Lakhs)', '% to AUM'],
        ['EQUITY & EQUITY RELATED'],
        ['(a) Listed / awaiting listing on Stock Exchanges'],
        ['ICICI Bank Ltd.', 'INE090A01021', 'Banks', 1000, 14.0, 1.0],
        ['ICICI Bank Ltd.', 'INE090A01021', 'Banks', 500, 7.0, 0.5],          # the same stock twice: two lines
        ['Sub Total', None, None, None, 21.0, 1.5],
        ['Derivatives'],
        ['ICICI Bank Ltd. Nov 2026 Future', None, None, -500, -7.0, -0.5],
        ['Debt Instruments'],
        ['7.1% XYZ NCD 2030', 'INE123A07012', 'CRISIL AAA', 100, 10.0, 0.7],
        ['7.32% GOI 2030', 'IN0020230135', 'SOV', 1000, 101.2, 7.0],
        ['Money Market Instruments'],
        ['91 Days Tbill 2026', 'IN002026X123', 'SOV', 100, 9.9, 0.7],
        ['TREPS', None, None, None, 500.0, 35.0],
        ['Units of REITs'],
        ['Embassy Office Parks REIT', 'INE041025011', 'Realty', 10, 0.4, 0.03],
        ['Net Receivables / (Payables)', None, None, None, -3.2, -0.2],
        ['GRAND TOTAL (AUM)', None, None, None, 1431.0, 100.0],
        ['^ Industry classification as recommended by AMFI and rating as given by the rating agency; please see the '
         'scheme information document for the risk factors of the scheme.']]
NOTES = [['Notes'], ['Back to index']]


def _parse(sheets, filename='x.xlsx', unit='lakh'):
    return m.parse_workbook_lines(_book(sheets), filename, unit)


def _filled(rows):
    return sum(1 for r in rows if any(c is not None and str(c).strip() for c in r))


def test_every_line_kept_with_its_kind():
    df, rep, ln, sk = _parse({'Index': NOTES, 'BAF': FULL})
    assert len(ln) == _filled(FULL)                                    # every filled row of the sheet read
    assert ln['row'].tolist() == [i for i, r in enumerate(FULL, 1) if any(c is not None for c in r)]
    k = ln.set_index('row')
    assert k.loc[1, 'row_type'] == 'title' and k.loc[5, 'row_type'] == 'header'
    assert (k.loc[8, 'row_type'], k.loc[8, 'line_kind'], k.loc[8, 'kind_from']) == ('holding', 'equity', 'heading')
    assert k.loc[7, 'line_kind'] == 'equity'                           # '(a) Listed' does not end the equity section
    assert (k.loc[10, 'row_type'], k.loc[10, 'line_kind']) == ('total', 'equity')
    assert (k.loc[12, 'row_type'], k.loc[12, 'line_kind'], k.loc[12, 'quantity']) == ('value', 'derivative', -500)
    assert k.loc[14, 'line_kind'] == 'debt' and k.loc[14, 'rating'] == 'CRISIL AAA' and k.loc[15, 'line_kind'] == 'debt'
    assert k.loc[17, 'line_kind'] == 'money market' and k.loc[17, 'isin'] == 'IN002026X123'
    assert (k.loc[18, 'row_type'], k.loc[18, 'line_kind'], k.loc[18, 'kind_from']) == ('value', 'money market', 'name')
    assert k.loc[20, 'line_kind'] == 'other' and k.loc[20, 'section'] == 'Units of REITs'   # a kind outside the five
    assert (k.loc[21, 'line_kind'], k.loc[21, 'kind_from'], k.loc[21, 'value_lakh']) == ('cash', 'name', -3.2)
    assert k.loc[22, 'row_type'] == 'total' and k.loc[23, 'row_type'] == 'note'
    assert set(ln['line_kind']) <= set(m.LINE_KINDS)
    assert set(ln['scheme']) == {'ABC Balanced Advantage Fund'}
    assert json.loads(k.loc[14, 'cells']) == ['7.1% XYZ NCD 2030', 'INE123A07012', 'CRISIL AAA', '100', '10', '0.7']
    # the equity tables' lines are exactly the holding lines with an equity ISIN and a quantity
    assert ln['in_equity_tables'].sum() == 2 and rep['equity_lines'] == 2
    assert sk.to_dict('records') == [{'workbook': '', 'sheet': 'Index', 'reason': 'no ISIN and Quantity header',
                                      'rows': 2, 'filled_rows': 2}]


def test_holding_lines_are_the_rows_the_equity_tables_read():
    for sheets, unit in (({'BAF': FULL, 'SLCF': SCHEME, 'SNIF': INDEX}, 'lakh'), ({'E1': NPS_E1, 'CG': NPS_CG}, 'rupee')):
        df, _, ln, _ = _parse(sheets, unit=unit)
        h = ln[ln['row_type'] == 'holding'].reset_index(drop=True)
        cols = ['sheet', 'scheme', 'isin', 'name', 'quantity', 'value_lakh', 'pct_aum']
        pd.testing.assert_frame_equal(h[cols], df[cols], check_dtype=False)


def test_pension_form_kind_from_the_isin_or_its_own_words():
    _, _, ln, _ = _parse({'CG': NPS_CG}, unit='rupee')
    h = ln[ln['row_type'] == 'holding'].set_index('isin')
    assert (h.loc['INE040A01034', 'line_kind'], h.loc['INE040A01034', 'kind_from']) == ('equity', 'isin')
    assert (h.loc['IN0020230051', 'line_kind'], h.loc['IN0020230051', 'kind_from']) == ('debt', 'name')  # 'GOVERNMENT SECURITIES'
    assert abs(h.loc['IN0020230051', 'value_lakh'] - 315316.3475) < 1e-6


def test_zip_names_its_workbooks_and_an_unknown_line_is_other():
    z = io.BytesIO()
    with zipfile.ZipFile(z, 'w') as f:
        f.writestr('a.xlsx', _book({'S1': [['Name', 'ISIN', 'Quantity'], ['Mystery Paper', 'INE999Z09011', 5]]}))
        f.writestr('b.xlsx', _book({'Notes': NOTES}))
    _, _, ln, sk = m.parse_workbook_lines(z.getvalue(), 'month.zip')
    h = ln[ln['row_type'] == 'holding'].iloc[0]
    assert (h['workbook'], h['line_kind'], h['kind_from']) == ('a.xlsx', 'other', 'none')   # never guessed
    assert sk[['workbook', 'sheet']].values.tolist() == [['b.xlsx', 'Notes']]


# --- equity outputs unchanged ------------------------------------------------------------------------------------------

def old_parse_workbook(body, filename, value_unit='lakh'):
    """insiders_clean/mf_holdings.parse_workbook as it was before the lines archive (commit 9f02d7c), verbatim."""
    VALUE_UNIT, _books, _sheets, parse_rows, is_equity = m.VALUE_UNIT, m._books, m._sheets, m.parse_rows, m.is_equity
    if value_unit not in VALUE_UNIT:
        raise ValueError(f'value_unit {value_unit!r}: one of {sorted(VALUE_UNIT)}')
    rows, report = [], {'workbooks': 0, 'sheets': 0, 'sheets_read': 0, 'skipped': {}, 'value_unit': value_unit}
    for name, data in _books(body, filename):
        report['workbooks'] += 1
        for sheet, srows in _sheets(name, data):
            report['sheets'] += 1
            got, why = parse_rows(sheet, srows)
            if why:
                report['skipped'][why] = report['skipped'].get(why, 0) + 1
                continue
            report['sheets_read'] += 1
            rows += got
    df = pd.DataFrame(rows, columns=['sheet', 'scheme', 'isin', 'name', 'quantity', 'value_lakh', 'pct_aum'])
    df['value_lakh'] = pd.to_numeric(df['value_lakh'], errors='coerce') / VALUE_UNIT[value_unit]
    report['lines'] = int(len(df))
    report['equity_lines'] = int(is_equity(df['isin']).sum()) if len(df) else 0
    report['equity_lines_no_quantity'] = int((is_equity(df['isin']) & df['quantity'].isna()).sum()) if len(df) else 0
    return df, report


def _pq(df):
    b = io.BytesIO()
    df.to_parquet(b, index=False, compression='zstd')
    return b.getvalue()


CASES = [({'Index': NOTES, 'BAF': FULL, 'SLCF': SCHEME, 'SNIF': INDEX}, 'x.xlsx', 'lakh'),
         ({'E1': NPS_E1, 'CG': NPS_CG}, 'forms.xlsx', 'rupee')]


@pytest.mark.parametrize('sheets,name,unit', CASES)
def test_equity_outputs_byte_identical_to_before(sheets, name, unit):
    body = _book(sheets)
    old_df, old_rep = old_parse_workbook(body, name, unit)
    for new_df, new_rep in (m.parse_workbook(body, name, unit), m.parse_workbook_lines(body, name, unit)[:2]):
        assert new_rep == old_rep
        pd.testing.assert_frame_equal(new_df, old_df)
        for f in (lambda r: m.holdings(r, 'abc', '2026-10'), lambda r: m.scheme_holdings(r, 'abc', '2026-10', 'ABC'),
                  lambda r: m.scheme_list(r, 'abc', '2026-10', 'ABC')):
            assert _pq(f(new_df)) == _pq(f(old_df))


# --- the collector writes them --------------------------------------------------------------------------------------

class R2(FakeR2):
    PAGE = 1000
    exceptions = types.SimpleNamespace(NoSuchKey=NoSuchKey)


URL = 'https://abc.example/docs/all-schemes-monthly-portfolio---as-on-31st-october-2026.xlsx'


def _house():
    return House('abc', 'ABC Mutual Fund', 'https://abc.example/', mode='all')


def _collector(monkeypatch, tmp_path, bodies):
    monkeypatch.setattr(raw_capture, 'DIR', tmp_path)
    monkeypatch.setattr(find, 'links_plain', lambda page: [('Download', u) for u in bodies])
    monkeypatch.setattr(mp, '_download', lambda u, timeout=180: (bodies[u], 'application/vnd.ms-excel', 200))


def test_run_house_writes_every_line_and_the_equity_archives_unchanged(monkeypatch, tmp_path):
    body = _book({'Index': NOTES, 'BAF': FULL, 'SLCF': SCHEME})
    _collector(monkeypatch, tmp_path, {URL: body})
    r2 = R2()
    res = mp.run_house(_house(), ['2026-10'], r2=r2)[0]
    assert res['found'] and res['all_lines'] == _filled(FULL) + _filled(SCHEME) and res['sheets_skipped'] == 1
    assert 'lines' not in res and 'skipped_sheets' not in res               # counts only in the report
    old_df, _ = old_parse_workbook(body, URL.rsplit('/', 1)[-1])
    o = r2.objects
    assert o['archive/mf_holdings/month=2026-10/abc.parquet'] == _pq(m.holdings(old_df, 'abc', '2026-10').assign(kind='mf'))
    assert o['archive/mf_schemes/month=2026-10/abc.parquet'] == _pq(m.scheme_holdings(old_df, 'abc', '2026-10', 'ABC Mutual Fund'))
    assert o['archive/mf_scheme_list/month=2026-10/abc.parquet'] == _pq(m.scheme_list(old_df, 'abc', '2026-10', 'ABC Mutual Fund'))
    ln = pd.read_parquet(io.BytesIO(o['archive/mf_lines/month=2026-10/abc.parquet']))
    sk = pd.read_parquet(io.BytesIO(o['archive/mf_sheets_skipped/month=2026-10/abc.parquet']))
    assert len(ln) == res['all_lines'] and set(ln['blob_sha256']) == {sha256_hex(body)}
    assert set(ln['amc']) == {'abc'} and set(ln['month']) == {'2026-10'} and set(ln['file']) == {URL.rsplit('/', 1)[-1]}
    assert ln.columns.tolist() == ['amc', 'month', 'file', 'blob_sha256', *m.LINE_COLS]
    assert sk[['sheet', 'reason', 'filled_rows']].values.tolist() == [['Index', 'no ISIN and Quantity header', 2]]
    assert ((ln['line_kind'] == 'debt') & (ln['row_type'] == 'holding')).sum() == 2 and ln['in_equity_tables'].sum() == 2 + 2   # FULL 2, SCHEME 2


def test_a_file_read_again_replaces_its_lines_and_another_file_keeps_its_own(monkeypatch, tmp_path):
    a, b = _book({'BAF': FULL}), _book({'SLCF': SCHEME})
    r2 = R2()
    h = _house()
    _, _, la, sa = mp.file_lines(a, URL, 'lakh')
    _, _, lb, sb = mp.file_lines(b, URL + '?v=2', 'lakh')
    mp.put_lines(r2, h, '2026-10', la, sa)
    mp.put_lines(r2, h, '2026-10', lb, sb)
    mp.put_lines(r2, h, '2026-10', la, sa)                                # the first file again: not doubled
    ln = pd.read_parquet(io.BytesIO(r2.objects['archive/mf_lines/month=2026-10/abc.parquet']))
    assert ln.groupby('blob_sha256').size().to_dict() == {sha256_hex(a): len(la), sha256_hex(b): len(lb)}


def test_a_file_that_is_not_a_workbook_is_recorded_not_dropped(monkeypatch, tmp_path):
    _collector(monkeypatch, tmp_path, {URL: b'<html>not here</html>'})
    r2 = R2()
    res = mp.run_house(_house(), ['2026-10'], r2=r2)[0]
    assert not res['found'] and res['sheets_skipped'] == 1
    sk = pd.read_parquet(io.BytesIO(r2.objects['archive/mf_sheets_skipped/month=2026-10/abc.parquet']))
    assert sk['reason'].iloc[0].startswith('file not read (ValueError') and sk['sheet'].iloc[0] == ''
    assert 'archive/mf_holdings/month=2026-10/abc.parquet' not in r2.objects


def test_backfill_fills_past_months_from_raw_once(monkeypatch):
    a, b = _book({'Index': NOTES, 'BAF': FULL}), _book({'SLCF': SCHEME})
    r2 = R2()
    st = RawStore(r2, bucket='b', collector='mf', clock=lambda: T1)
    st.put('amc', 'abc/portfolio_month', a, url=URL, content_type='application/vnd.ms-excel', covers={'month': '2026-09'})
    st.put('amc', 'abc/portfolio_month', a, url=URL + '?again', content_type='application/vnd.ms-excel',
           covers={'month': '2026-09'})                                   # the same bytes fetched twice: read once
    st.put('amc', 'abc/portfolio_month', b, url=URL, content_type='application/vnd.ms-excel', covers={'month': '2026-10'})
    st.put('amc', 'abc/portfolio_month', b'gone', url=URL, status=404, covers={'month': '2026-08'})
    monkeypatch.setattr(mp, 'run_houses', lambda hs, work, workers=None: [(h, work(h)) for h in hs])
    rep = mp.backfill_lines(r2, [_house()])['abc']
    assert rep['months'] == ['2026-09', '2026-10'] and rep['files_read'] == 2
    assert rep['lines'] == _filled(FULL) + _filled(SCHEME) and rep['sheets_skipped'] == 1
    ln9 = pd.read_parquet(io.BytesIO(r2.objects['archive/mf_lines/month=2026-09/abc.parquet']))
    assert len(ln9) == _filled(FULL) and 'archive/mf_lines/month=2026-08/abc.parquet' not in r2.objects
    again = mp.backfill_lines(r2, [_house()])['abc']
    assert again['months'] == [] and again['files_read'] == 0


def test_lines_flag_is_wired(monkeypatch):
    seen = {}
    monkeypatch.setattr(mp, 'backfill_lines', lambda r2, houses: seen.setdefault('houses', [h.key for h in houses]) and {})
    monkeypatch.setattr(mp, 'rebuild', lambda r2: {})
    monkeypatch.setattr(mp, 'run_houses', lambda hs, work, workers=None: [])
    monkeypatch.setattr(mp.find, 'shared_browser', lambda: None)   # sbi is a browser house; CI has no Playwright
    import r2_writer
    monkeypatch.setattr(r2_writer, 'r2_client', lambda: R2())
    assert mp.main(['--month', '2026-10', '--house', 'sbi', '--lines', '--no-amfi']) == 0
    assert seen['houses'] == ['sbi']


# --- the audit finds them --------------------------------------------------------------------------------------------

def _audit_r2(body, drop_row=None, skipped=True):
    from collectors.mf_portfolios.houses import BY_KEY
    r = FakeR2()
    RawStore(r, bucket='b', collector='mf', clock=lambda: T1).put(
        'amc', 'sbi/portfolio_month', body, url='https://example.invalid/sbi/portfolio-oct-2026.xlsx',
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', covers={'month': '2026-10'})
    _, _, ln, sk = mp.file_lines(body, 'https://example.invalid/sbi/portfolio-oct-2026.xlsx', BY_KEY['sbi'].value_unit)
    if drop_row is not None:
        ln = ln[ln['row'] != drop_row]
    r.objects['archive/mf_lines/month=2026-10/sbi.parquet'] = _pq(ln.assign(amc='sbi', month='2026-10'))
    if skipped:
        r.objects['archive/mf_sheets_skipped/month=2026-10/sbi.parquet'] = _pq(sk.assign(amc='sbi', month='2026-10'))
    r.freeze()
    return r


def test_audit_finds_every_line_stored():
    body = _book({'Index': NOTES, 'BAF': FULL})
    r = _audit_r2(body)
    d = by(rc.run(r, 'b', sample=5, max_blobs=10), 'amc', 'sbi/portfolio_month')
    c = d['counts']
    n = _filled(FULL)
    assert (c['raw_rows'], c['parsed_rows'], c['in_table'], c['missing_from_table']) == (n + 1 + 2, n + 1, n + 1, 0)
    assert c['unexplained_drop'] == 0 and d['mismatches'] == [] and d['values_compared'] == 5
    # no non-equity line is a drop any more; the skipped sheet is found recorded, its rows said to be only in raw
    assert list(c['dropped']) == ['rows of sheets skipped (no ISIN and Quantity header): the sheet is in '
                                  'archive/mf_sheets_skipped/, its rows only in raw']
    assert not any('non-equity' in g for g in d['gaps']) and r.writes == []


def test_audit_fully_captured_without_skipped_sheets_and_a_missing_line_is_a_gap():
    body = _book({'BAF': FULL})
    d = by(rc.run(_audit_r2(body), 'b', sample=5, max_blobs=10), 'amc', 'sbi/portfolio_month')
    assert d['verdict'] == 'fully captured' and d['counts']['dropped'] == {}
    d = by(rc.run(_audit_r2(body, drop_row=18), 'b', sample=5, max_blobs=10), 'amc', 'sbi/portfolio_month')
    assert d['counts']['missing_from_table'] == 1 and d['missing_examples'][0].endswith('|BAF|18')
    assert d['verdict'].startswith('gaps: 1 of')
    d = by(rc.run(_audit_r2(_book({'Index': NOTES, 'BAF': FULL}), skipped=False), 'b', sample=5, max_blobs=10),
           'amc', 'sbi/portfolio_month')
    assert d['counts']['missing_from_table'] == 1 and d['missing_examples'][0].endswith('|Index|0')   # skipped sheet not recorded


def test_a_failure_reading_lines_never_costs_the_equity_rows(monkeypatch, tmp_path):
    body = _book({'BAF': FULL, 'SLCF': SCHEME})
    want, want_rep = old_parse_workbook(body, 'x.xlsx')

    def boom(*a, **k):
        raise RuntimeError('cell from the future')
    monkeypatch.setattr(m, 'line_rows', boom)
    df, rep, ln, sk = m.parse_workbook_lines(body, 'x.xlsx')
    pd.testing.assert_frame_equal(df, want)
    assert rep == want_rep and ln.empty
    assert sk['reason'].tolist() == ['lines not read (RuntimeError: cell from the future)'] * 2
    # and in the collector, a failure outside the sheets: the equity archive as before, the file listed
    monkeypatch.setattr(mp, 'file_lines', boom)
    _collector(monkeypatch, tmp_path, {URL: body})
    r2 = R2()
    res = mp.run_house(_house(), ['2026-10'], r2=r2)[0]
    assert res['found'] and res['all_lines'] == 0
    old_df, _ = old_parse_workbook(body, URL.rsplit('/', 1)[-1])
    assert r2.objects['archive/mf_holdings/month=2026-10/abc.parquet'] == _pq(m.holdings(old_df, 'abc', '2026-10').assign(kind='mf'))
    sk = pd.read_parquet(io.BytesIO(r2.objects['archive/mf_sheets_skipped/month=2026-10/abc.parquet']))
    assert sk['reason'].tolist() == ['lines not read (RuntimeError: cell from the future)']
