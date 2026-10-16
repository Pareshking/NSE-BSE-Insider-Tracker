"""Financial results from NSE's integrated filing: list rows and XBRL (insiders_clean/results.py), and the nightly
stream's paging and XBRL fetch (collectors/nse_events/run_daily.py). Shapes as NSE sent them on 15 Oct 2026."""
from __future__ import annotations

import json

import pandas as pd
from collectors.nse_events import run_daily

from insiders_clean import results

ROW = {"attFileSize": "0 Bytes", "audited": "Un-Audited", "broadcast_Date": "15-Oct-2026 18:10:12",
       "cmName": "Nestle India Limited", "consolidated": "Consolidated", "creation_Date": "15-Oct-2026 18:10:58",
       "ixbrl": "https://nsearchives.nseindia.com/corporate/ixbrl/INTEGRATED_FILING_INDAS_201512_15102026181058_iXBRL_WEB.html",
       "pdf_attach": "https://nsearchives.nseindia.com/corporate/null", "qe_Date": "30-SEP-2026", "revised_Date": None,
       "revision_Remark": None, "seq_Id": "201512", "smName": "Nestle India Limited", "symbol": "NESTLEIND",
       "type": "Integrated Filing- Financials", "type_Sub": "Original",
       "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1739230_15102026061058_WEB.xml"}

XBRL = """<?xml version="1.0" encoding="UTF-8" standalone="no"?><!--IFIndAs V2.1 (26-06-2026)-->
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:in-capmkt="http://x/in-capmkt"
 xmlns:xbrldi="http://xbrl.org/2006/xbrldi">
 <xbrli:context id="OneD"><xbrli:entity><xbrli:identifier scheme="s">500790</xbrli:identifier></xbrli:entity>
  <xbrli:period><xbrli:startDate>2026-07-01</xbrli:startDate><xbrli:endDate>2026-09-30</xbrli:endDate></xbrli:period></xbrli:context>
 <xbrli:context id="FourD"><xbrli:entity><xbrli:identifier scheme="s">500790</xbrli:identifier></xbrli:entity>
  <xbrli:period><xbrli:startDate>2026-04-01</xbrli:startDate><xbrli:endDate>2026-09-30</xbrli:endDate></xbrli:period></xbrli:context>
 <xbrli:context id="OneI"><xbrli:entity><xbrli:identifier scheme="s">500790</xbrli:identifier></xbrli:entity>
  <xbrli:period><xbrli:instant>2026-09-30</xbrli:instant></xbrli:period></xbrli:context>
 <xbrli:context id="OneExpenses1D"><xbrli:entity><xbrli:identifier scheme="s">500790</xbrli:identifier>
  <xbrli:segment><xbrldi:explicitMember dimension="d">m</xbrldi:explicitMember></xbrli:segment></xbrli:entity>
  <xbrli:period><xbrli:startDate>2026-07-01</xbrli:startDate><xbrli:endDate>2026-09-30</xbrli:endDate></xbrli:period></xbrli:context>
 <in-capmkt:ISIN contextRef="OneD">INE239A01024</in-capmkt:ISIN>
 <in-capmkt:ScripCode contextRef="OneD">500790</in-capmkt:ScripCode>
 <in-capmkt:LevelOfRounding contextRef="OneD">Millions</in-capmkt:LevelOfRounding>
 <in-capmkt:DateOfStartOfReportingPeriod contextRef="OneD">2026-07-01</in-capmkt:DateOfStartOfReportingPeriod>
 <in-capmkt:DateOfEndOfReportingPeriod contextRef="OneD">2026-09-30</in-capmkt:DateOfEndOfReportingPeriod>
 <in-capmkt:RevenueFromOperations contextRef="OneD" unitRef="INR" decimals="-5">67883400000</in-capmkt:RevenueFromOperations>
 <in-capmkt:ProfitLossForPeriod contextRef="OneD" unitRef="INR" decimals="-5">10096100000</in-capmkt:ProfitLossForPeriod>
 <in-capmkt:BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations contextRef="OneD" unitRef="INRPerShare" decimals="INF">5.24</in-capmkt:BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations>
 <in-capmkt:DateOfStartOfReportingPeriod contextRef="FourD">2026-04-01</in-capmkt:DateOfStartOfReportingPeriod>
 <in-capmkt:DateOfEndOfReportingPeriod contextRef="FourD">2026-09-30</in-capmkt:DateOfEndOfReportingPeriod>
 <in-capmkt:RevenueFromOperations contextRef="FourD" unitRef="INR" decimals="-5">131665200000</in-capmkt:RevenueFromOperations>
 <in-capmkt:OtherExpenses contextRef="OneExpenses1D" unitRef="INR" decimals="-5">100</in-capmkt:OtherExpenses>
</xbrli:xbrl>"""


def test_list_row_as_filed_and_no_file_links_are_none():
    r = results.filing_rows([ROW, {**ROW, 'seq_Id': None}]).iloc[0]
    assert r['event_id'] == 'nse:result:201512' and r['symbol'] == 'NESTLEIND' and r['period_end'] == '2026-09-30'
    assert r['broadcast_at'].startswith('2026-10-15T18:10:12') and r['broadcast_date'] == '2026-10-15'
    assert r['kind'] == 'INDAS' and r['pdf_url'] is None and r['revision'] == 'Original'
    assert results.kind_of('https://x/INTEGRATED_FILING_NBFC_INDAS_1739204_15102026060332_WEB.xml') == 'NBFC_INDAS'


def test_revision_without_broadcast_time_uses_creation_time():
    r = results.filing_rows([{**ROW, 'broadcast_Date': None, 'type_Sub': 'Revision', 'revised_Date': '15-OCT-2026 18:06:12',
                              'revision_Remark': 'Cash flow corrected'}]).iloc[0]
    assert r['broadcast_at'].startswith('2026-10-15T18:10:58') and r['revision'] == 'Revision'
    assert r['revised_at'].startswith('2026-10-15T18:06:12') and r['revision_remark'] == 'Cash flow corrected'


def test_xbrl_quarter_and_year_to_date_are_told_apart():
    parsed = results.parse_xbrl(XBRL)
    assert results.periods(parsed) == ('OneD', 'FourD')
    s = results.summary(parsed)
    assert s['isin'] == 'INE239A01024' and s['bse_code'] == '500790' and s['rounding'] == 'Millions'
    assert s['quarter_revenue'] == 67883400000.0 and s['ytd_revenue'] == 131665200000.0
    assert s['quarter_profit'] == 10096100000.0 and s['quarter_eps_basic'] == 5.24
    assert s['quarter_tax'] is None                      # not filed: blank, never guessed
    assert s['ytd_start'] == '2026-04-01' and s['period_end_xbrl'] == '2026-09-30'


def test_first_quarter_has_no_separate_year_to_date():
    parsed = results.parse_xbrl(XBRL.replace('2026-04-01', '2026-07-01'))
    q, ytd = results.periods(parsed)
    assert q in ('OneD', 'FourD') and ytd is None


class FakeNSE:
    def __init__(self, pages, xbrl=XBRL):
        self.pages, self.xbrl_text, self.urls, self.calls = pages, xbrl, [], 0

    def integrated_results_url(self, start, end, page=1, size=100):
        return f'list?page={page}'

    def get(self, url, as_json=True, **_):
        self.urls.append(url)
        page = int(url.rsplit('=', 1)[1])
        return json.dumps(self.pages[page - 1] if page <= len(self.pages) else {'data': [], 'totalCount': 3})

    def xbrl(self, url):
        self.urls.append(url)
        return self.xbrl_text


def test_pages_until_total_count_and_xbrl_read_once():
    from datetime import date
    pages = [{'data': [ROW, {**ROW, 'seq_Id': '201511'}], 'totalCount': 3}, {'data': [{**ROW, 'seq_Id': '201509'}], 'totalCount': 3}]
    nse, report = FakeNSE(pages), {'notes': []}
    rows = run_daily.results_filings(nse, None, date(2026, 10, 12), date(2026, 10, 15), report)
    assert len(rows) == 3 and report['results_listed'] == 3 and nse.urls == ['list?page=1', 'list?page=2']
    got = run_daily.fetch_results_xbrl(nse, None, rows, None, report, max_xbrl=2)
    assert sorted(got['xbrl_status']) == ['ok', 'ok', 'pending']
    again = run_daily.fetch_results_xbrl(FakeNSE([]), None, rows.iloc[:1], got, report, max_xbrl=5)
    assert set(again['xbrl_status']) == {'ok'} and len(again) == 2   # the pending one is retried, the read one kept
    table = results.clean(got)
    assert 'xbrl_json' not in table and table['quarter_revenue'].notna().sum() == 2


def test_a_backfill_fetches_several_files_at_once_and_a_refusal_stops_them_all(monkeypatch):
    from datetime import date
    pages = [{'data': [{**ROW, 'seq_Id': str(201500 + k), 'xbrl': f'http://x/{k}.xml'} for k in range(8)], 'totalCount': 8}]
    nse, report = FakeNSE(pages), {'notes': []}
    rows = run_daily.results_filings(nse, None, date(2026, 10, 12), date(2026, 10, 15), report)

    class Worker:
        def __init__(self, pause=None):
            pass

        def xbrl(self, url):
            return XBRL
    monkeypatch.setattr(run_daily, 'NSEClient', Worker)
    got = run_daily.fetch_results_xbrl(nse, None, rows, None, report, max_xbrl=6, workers=3)
    assert sorted(got['xbrl_status'].astype(str)) == ['ok'] * 6 + ['pending'] * 2 and report['results_xbrl_fetched'] == 6

    class Refusing(Worker):
        def xbrl(self, url):
            raise run_daily.Blocked('HTTP 429')
    monkeypatch.setattr(run_daily, 'NSEClient', Refusing)
    report = {'notes': []}
    got = run_daily.fetch_results_xbrl(nse, None, rows, None, report, max_xbrl=8, workers=3)
    assert set(got['xbrl_status'].astype(str)) == {'pending'} and report['results_xbrl_blocked']


def test_a_long_span_is_listed_in_windows_of_31_days():
    from datetime import date
    seen = []

    class Windows(FakeNSE):
        def integrated_results_url(self, start, end, page=1, size=100):
            seen.append((start, end))
            return f'list?page={page}'
    rows = run_daily.results_filings(Windows([{'data': [ROW], 'totalCount': 1}]), None, date(2026, 1, 1), date(2026, 3, 15), {'notes': []})
    windows = sorted(set(seen))
    assert windows[0] == (date(2026, 1, 1), date(2026, 1, 31)) and windows[-1][1] == date(2026, 3, 15) and len(windows) == 3
    assert len(rows) == 1


def test_a_window_is_listed_instead_of_the_last_days():
    from datetime import date
    seen = []

    class Windows(FakeNSE):
        def integrated_results_url(self, start, end, page=1, size=100):
            seen.append((start, end))
            return f'list?page={page}'
    run_daily.results_filings(Windows([{'data': [ROW], 'totalCount': 1}]), None, date(2025, 1, 1), date(2025, 1, 20), {'notes': []})
    assert set(seen) == {(date(2025, 1, 1), date(2025, 1, 20))}
