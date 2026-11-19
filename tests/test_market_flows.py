"""Market flows: NSE provisional FII/DII, NSDL FPI daily and fortnightly sectors, SEBI mutual fund trends.

Fixtures in tests/fixtures/market_flows/ are real answers fetched 19 Nov 2026 by scripts/market_flows.py: the NSE
JSON as sent; SEBI's page as sent, gzipped; NSDL's pages cut to the part read (the archive's `dvArchiveData` table,
the sector list's `<select>`; the ASP.NET view state left out), gzipped; the sector report as sent, gzipped."""
from __future__ import annotations

import gzip
import io
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'streamlit_app'))
from insiders_clean import market_flows as M  # noqa: E402

FX = Path(__file__).resolve().parent / 'fixtures' / 'market_flows'


def text(name):
    b = (FX / name).read_bytes()
    return (gzip.decompress(b) if name.endswith('.gz') else b).decode('utf-8')


def nse(name):
    return json.loads(text(f'nse_{name}_20261118.json'))


# ---- parsers ------------------------------------------------------------------

def test_nse_both_answers_parse_to_fpi_and_dii_provisional():
    a = M.parse_nse(nse('fiidiiTradeReact'), 'fiidiiTradeReact')
    n = M.parse_nse(nse('fiidiiTradeNse'), 'fiidiiTradeNse')
    assert list(a.columns) == M.COLUMNS
    assert set(a['segment']) == {'cash_nse_bse_msei'} and set(n['segment']) == {'cash_nse'}
    assert set(a['category']) == {'fpi', 'dii'}
    assert a['provisional'].all() and set(a['date_basis']) == {'trade'}
    assert (a['date'] == pd.Timestamp('2026-11-18')).all()
    dii = a.set_index('category').loc['dii']
    assert (dii['buy_cr'], dii['sell_cr'], dii['net_cr']) == (14602.25, 17762.15, -3159.9)
    fpi = n.set_index('category').loc['fpi']
    assert fpi['net_cr'] == 4553.87
    with pytest.raises(ValueError):
        M.parse_nse([{'category': 'Retail', 'date': '18-Nov-2026', 'buyValue': '1', 'sellValue': '1',
                      'netValue': '0'}], 'fiidiiTradeNse')


def test_nsdl_month_parses_every_reporting_day_and_adds_to_nsdl_month_total():
    notes = []
    df = M.parse_nsdl_daily(text('nsdl_archive_to_20261119.html.gz'), notes)
    assert notes == [] and not df.attrs.get('short')
    days = sorted(df['date'].dt.strftime('%d').unique())
    assert days == ['02', '03', '04', '05', '06', '09', '11', '12', '13', '16', '17', '18']
    assert {'equity', 'equity_exchange', 'equity_primary', 'debt_general', 'debt_vrr', 'debt_far', 'hybrid',
            'mutual_funds', 'mutual_funds_equity_schemes', 'aif', 'total'} <= set(df['segment'])
    assert (df.groupby('date').size() == 25).all()
    assert not df['provisional'].any() and set(df['date_basis']) == {'reported'} and set(df['category']) == {'fpi'}
    eq = df[(df['date'] == pd.Timestamp('2026-11-18')) & (df['segment'] == 'equity')].iloc[0]
    assert (eq['buy_cr'], eq['sell_cr'], eq['net_cr']) == (26444.96, 15179.28, 11265.68)
    debt = df[(df['date'] == pd.Timestamp('2026-11-02')) & (df['segment'] == 'debt_general')].iloc[0]
    assert debt['net_cr'] == -548.33          # printed '(548.33)'
    # NSDL's own "Total for November" equity net: the twelve days add to it
    assert df.loc[df['segment'] == 'equity', 'net_cr'].sum() == pytest.approx(106228.84, abs=M.MONTH_TOL)


def test_nsdl_month_with_a_day_missing_is_named_short():
    html = text('nsdl_archive_to_20261119.html.gz')
    i = html.index("<td rowspan='25'>03-Nov-2026")
    j = html.index("<td rowspan='25'>04-Nov-2026")
    cut = html[:html.rfind('<tr', 0, i)] + html[html.rfind('<tr', 0, j):]
    notes = []
    df = M.parse_nsdl_daily(cut, notes)
    assert df.attrs.get('short') and any('November' in n for n in notes)
    assert pd.Timestamp('2026-11-03') not in set(df['date'])


def test_nsdl_unknown_asset_class_is_refused_not_guessed():
    html = text('nsdl_archive_to_20261119.html.gz').replace("<td rowspan='3'>Hybrid</td>", "<td rowspan='3'>Gold</td>", 1)
    with pytest.raises(ValueError, match='Gold'):
        M.parse_nsdl_daily(html)


def test_sebi_mutual_fund_days_and_total():
    notes = []
    df = M.parse_sebi(text('sebi_mf_to_20261119.html.gz'), notes)
    assert notes == []
    assert sorted(df['date'].dt.day.unique()) == [2, 3, 4]
    assert set(df['segment']) == {'equity', 'debt'} and set(df['category']) == {'mf'}
    eq = df[(df['date'] == pd.Timestamp('2026-11-04')) & (df['segment'] == 'equity')].iloc[0]
    assert (eq['buy_cr'], eq['sell_cr'], eq['net_cr']) == (12934.94, 15156.88, -2221.94)
    assert not df['provisional'].any() and set(df['date_basis']) == {'trade'}


def test_sebi_row_that_does_not_add_up_is_dropped_and_counted():
    html = text('sebi_mf_to_20261119.html.gz').replace('<td>(226.63)</td>', '<td>(999.63)</td>', 1)
    notes = []
    df = M.parse_sebi(html, notes)
    assert len(df) == 5 and any('buy - sell' in n for n in notes) and df.attrs.get('short')


def test_sector_report_reads_this_fortnight_and_checks_grand_total():
    df = M.parse_nsdl_sectors(text('nsdl_sectors_20261115.html.gz'))
    assert list(df.columns) == M.SECTOR_COLUMNS
    assert len(df) == 25 and df['sector'].iloc[-1] == 'Grand Total'
    assert set(df['fortnight_end']) == {pd.Timestamp('2026-11-15')}
    assert set(df['period_start']) == {pd.Timestamp('2026-11-01')}
    auto = df.set_index('sector').loc['Automobile and Auto Components']
    assert (auto['net_equity_cr'], auto['net_equity_usd_mn'], auto['auc_equity_cr'], auto['auc_total_cr']) == (
        7551, 802, 529709, 529753)
    assert auto['prev_net_equity_cr'] == -1098 and auto['prev_period_start'] == pd.Timestamp('2026-10-16')


def test_sector_options_read_irregular_file_names():
    opts = M.sector_options(text('nsdl_sector_list_20261119.html.gz'))
    by = dict(opts)
    assert opts[0][0] == date(2026, 11, 15)
    assert by[date(2026, 6, 30)].endswith('FIIInvestSector_June302026.html')
    assert by[date(2025, 7, 31)].endswith('FIIInvestSector_July312025.html')
    assert all(p.startswith('/web/StaticReports/') for p in by.values())
    assert sum(date(2025, 10, 8) <= d <= date(2026, 11, 19) for d in by) == 27   # 15 Oct 2025 to 15 Nov 2026


def test_build_keeps_window_and_latest_fetch():
    old = M.parse_nse(nse('fiidiiTradeReact'), 'fiidiiTradeReact')
    newer = old.copy()
    newer['net_cr'] = newer['net_cr'] + 0.0
    newer.loc[0, 'buy_cr'] = 1.0
    merged = M.merge(old, newer)
    assert len(merged) == 2 and 1.0 in set(merged['buy_cr'])
    early = old.assign(date=pd.Timestamp('2025-10-01'))
    t = M.build(pd.concat([merged, early]))
    assert t['date'].min() == pd.Timestamp('2026-11-18') and list(t.columns) == M.COLUMNS


# ---- the collector, end to end against a fake R2 and the real answers ----------------------

class Resp:
    def __init__(self, body: str, ctype='text/html'):
        self.content = body.encode('utf-8')
        self.text = body
        self.status_code = 200
        self.headers = {'Content-Type': ctype}


class FakeWeb:
    calls = 0

    def fetch(self, method, url, **kw):
        self.calls += 1
        if 'sebi.gov.in' in url:
            return Resp(text('sebi_mf_to_20261119.html.gz'))
        if url.endswith('Archive.aspx'):
            return Resp('<input type="hidden" name="__VIEWSTATE" value="x" />' if method == 'GET'
                        else text('nsdl_archive_to_20261119.html.gz'))
        if url.endswith('FPI_Fortnightly_Selection.aspx'):
            return Resp(text('nsdl_sector_list_20261119.html.gz'))
        if url.endswith('FIIInvestSector_Nov152026.html'):
            return Resp(text('nsdl_sectors_20261115.html.gz'))
        raise RuntimeError(f'HTTP 404 for {url}')


class FakeNSE:
    calls = 0
    on_response = None

    def warm_up(self):
        pass

    def get(self, url):
        self.calls += 1
        return nse(url.rsplit('/', 1)[-1])


@pytest.fixture
def run_once(tmp_path, monkeypatch):
    import market_flows as F
    from test_archive_and_writer import FakeR2
    monkeypatch.setattr(F, 'capture', lambda *a, **k: None)
    r2 = FakeR2()
    report = F.run(r2, date(2026, 11, 19), None, date(2026, 11, 19), F.SOURCES, nse=FakeNSE(), web=FakeWeb())
    return F, r2, report


def test_nightly_run_writes_archive_clean_tables_and_report(run_once):
    F, r2, report = run_once
    keys = set(r2.objects)
    assert {'archive/market_flows/nse/year=2026.parquet', 'archive/market_flows/nsdl/year=2026.parquet',
            'archive/market_flows/sebi/year=2026.parquet', 'archive/market_flows/nsdl_sector/year=2026.parquet',
            F.CLEAN_KEY, F.SECTOR_KEY, 'clean/reports/market_flows/2026-11-19.json'} <= keys
    t = pd.read_parquet(io.BytesIO(r2.objects[F.CLEAN_KEY]))
    assert list(t.columns) == M.COLUMNS
    assert report['clean']['latest'] == {'nse': '2026-11-18', 'nsdl': '2026-11-18', 'sebi': '2026-11-04'}
    # this month and last asked of NSDL and SEBI; both fakes answer November, so the rows are kept once
    assert t[t['source'] == 'nsdl'].duplicated(['date', 'segment']).sum() == 0
    s = pd.read_parquet(io.BytesIO(r2.objects[F.SECTOR_KEY]))
    assert len(s) == 25 and report['clean']['sector_latest'] == '2026-11-15'
    # the newest two reports are asked for; the fake has only 15 Nov, and the miss is said, not hidden
    assert len(report['notes']) == 1 and 'sectors 2026-10-31: fetch failed' in report['notes'][0]


def test_nightly_rerun_skips_a_sector_report_already_stored(run_once):
    F, r2, _ = run_once
    web = FakeWeb()
    report = F.run(r2, date(2026, 11, 19), None, date(2026, 11, 19), ['sectors'], nse=FakeNSE(), web=web)
    assert report['parsed'] == {'nsdl_sector': 0}   # Nov 15 stored; Oct 31 is not in the fake and failed
    assert any('2026-10-31' in n for n in report['notes'])


def test_backfill_skips_nse_with_a_note():
    import market_flows as F
    report = {'notes': []}
    got = F.collect(date(2026, 11, 19), date(2025, 10, 8), date(2025, 12, 31), ['nse'], report, nse=FakeNSE(),
                    web=FakeWeb())
    assert 'nse' not in got and 'no history' in report['notes'][0]
    assert F.month_ends(date(2025, 10, 8), date(2026, 1, 10)) == [date(2025, 10, 31), date(2025, 11, 30),
                                                                   date(2025, 12, 31), date(2026, 1, 10)]


# ---- the site's line ------------------------------------------------------------

def test_flows_line_names_each_source_with_its_own_day(run_once):
    from screens.market_flows import flows_line
    F, r2, _ = run_once
    t = pd.read_parquet(io.BytesIO(r2.objects[F.CLEAN_KEY]))
    assert flows_line(t) == ('FPIs bought ₹5,867 Cr, DIIs sold ₹3,160 Cr on 18 Nov (exchanges, provisional); '
                             'NSDL: FPIs bought ₹11,266 Cr of equity, reported 18 Nov; '
                             'mutual funds sold ₹2,222 Cr of equity on 4 Nov (SEBI)')
    only_sebi = t[t['source'] == 'sebi']
    assert flows_line(only_sebi) == 'Mutual funds sold ₹2,222 Cr of equity on 4 Nov (SEBI)'
    nse_only = t[(t['source'] == 'nse') & (t['segment'] == 'cash_nse')]
    assert flows_line(nse_only) == 'FPIs bought ₹4,554 Cr, DIIs sold ₹4,455 Cr on 18 Nov (NSE, provisional)'
    assert flows_line(pd.DataFrame()) == '' and flows_line(None) == ''
