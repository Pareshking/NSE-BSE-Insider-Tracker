"""NSE announcements: parser on real rows fetched 13 Oct 2026 (broadcast in
Sep 2026, tests/fixtures/nse_events/announcements.json) and the nightly run
against an in-memory R2."""
from __future__ import annotations

import io
import json
from datetime import date, timedelta

import pandas as pd
from conftest import FIXTURES
from test_archive_and_writer import FakeR2

from collectors.nse_events import announcements as ann
from collectors.nse_events.client import Blocked

ROWS = json.loads((FIXTURES / 'nse_events' / 'announcements.json').read_text(encoding='utf-8'))


def test_parse_keeps_values_as_filed_with_broadcast_time_in_ist():
    df = ann.parse(ROWS)
    assert len(df) == len(ROWS) and df['event_id'].is_unique
    tci = df[df['seq_id'] == '106799938'].iloc[0]
    assert (tci['symbol'], tci['isin'], tci['subject']) == ('TCI', 'INE688A01022', 'Buyback')
    assert tci['broadcast_at'] == '2026-09-29T14:13:30+05:30' and tci['broadcast_date'] == '2026-09-29'
    assert tci['file_url'].endswith('_TCIL.pdf') and tci['file_type'] == 'pdf'
    assert tci['file_bytes'] == int(969.94 * 1024)


def test_unreadable_time_and_missing_seq_id_are_kept_not_guessed():
    row = dict(ROWS[0], an_dt='not a date', seq_id=None, attFileSize='', fileSize=None)
    df = ann.parse([row, row])
    assert df['broadcast_date'].isna().all() and df['file_bytes'].isna().all()
    none = ann.parse([dict(ROWS[0], attchmntFile='-', attFileSize='0 Bytes')]).iloc[0]   # NSE's "no file"
    assert none['file_url'] is None and none['file_type'] is None and pd.isna(none['file_bytes'])
    assert ann.file_type('https://nsearchives.nseindia.com/corporate/BLS_ROSA_99452_KMP_Doc.zip') == 'zip'
    assert df['event_id'].iloc[0] == df['event_id'].iloc[1]   # same row, same hashed id
    assert ann.partition(None) == 'month=unknown'
    assert ann.size_bytes('0 Bytes') == 0 and ann.size_bytes('2.05 MB') == int(2.05 * 1024 ** 2)


def test_groups_come_from_nse_subject_only():
    assert ann.group_of('Post Buyback Public Announcement') == 'buyback'
    assert ann.group_of('Qualified Institutional Placement') == 'fund_raise'
    assert ann.group_of('Outcome of Board Meeting') == 'to_sort'
    assert ann.group_of('Trading Window') == 'routine' and ann.group_of(None) == 'routine'
    assert ann.group_of('Allotment of Securities', 'IIFL Finance Limited has informed the Exchange regarding '
                        'allotment of Non-Convertible Debentures on Private Placement basis.') == 'debt'
    assert ann.group_of('Allotment of Securities', 'Allotment of Equity Shares to QIBs') == 'fund_raise'
    c = ann.counts(ann.parse(ROWS))
    assert c['by_group']['buyback']['announcements'] == 7   # Sep held one post-buyback announcement
    assert sum(g['announcements'] for g in c['by_group'].values()) == len(ROWS)


class FakeNSE:
    def __init__(self, rows, block=False, sme=()):
        self.rows, self.block, self.calls, self.on_response, self.asked = rows, block, 0, None, []
        self.sme = list(sme)
        self.xbrl_asked = []
        self.integrated_asked = []

    def announcements(self, a, b, index='equities'):
        self.calls += 1
        self.asked.append((a, b, index))
        if self.block:
            raise Blocked('HTTP 403')
        return self.rows if index == 'equities' else self.sme

    def xbrl_announcements(self, a, b, index='equities', symbol=None, feed_type='announcements'):
        self.xbrl_asked.append((a, b, index, feed_type))
        if self.block:
            raise Blocked('HTTP 403')
        return []

    def integrated_filing_financials(self, symbol):
        self.integrated_asked.append((symbol, 'financials'))
        if self.block:
            raise Blocked('HTTP 403')
        return []

    def corporate_governance(self, symbol):
        self.integrated_asked.append((symbol, 'governance'))
        if self.block:
            raise Blocked('HTTP 403')
        return []


def test_nightly_run_archives_by_month_and_twice_adds_nothing(monkeypatch):
    r2 = FakeR2()
    concall = dict(ROWS[0], seq_id='1', desc='Analysts/Institutional Investor Meet/Con. Call Updates')
    rep = ann.run(r2, FakeNSE(ROWS + [concall]), date(2026, 10, 1))
    assert rep['window'] == ['2026-09-29', '2026-10-01']
    assert rep['added'] == len(ROWS) + 1 and rep['calls'][0]['concall'] == 1   # concalls are archived since 15 Oct
    keys = [k for k in r2.objects if k.startswith(ann.PREFIX)]
    assert keys and all('/year=2026/month=' in k for k in keys)
    arch = pd.concat([pd.read_parquet(io.BytesIO(r2.objects[k])) for k in keys])
    assert len(arch) == len(ROWS) + 1 and '1' in set(arch['seq_id'])
    assert json.loads(r2.objects['clean/reports/announcements/2026-10-01.json'])['window_counts']['announcements'] \
        == len(ROWS) + 1
    assert ann.run(r2, FakeNSE(ROWS), date(2026, 10, 1))['added'] == 0
    assert 'buyback' in ann.summary_markdown(rep)


def test_backfill_goes_month_by_month_and_refusal_stops():
    r2 = FakeR2()
    nse = FakeNSE(ROWS)
    ann.run(r2, nse, date(2026, 10, 5), backfill_from=date(2026, 8, 20))
    months = [(date(2026, 8, 20), date(2026, 8, 31)), (date(2026, 9, 1), date(2026, 9, 30)),
              (date(2026, 10, 1), date(2026, 10, 5))]
    # Main-board only: the whole window and the cross-check's two halves.
    wholes = [(a, b, 'equities') for a, b in months]
    assert [x for x in nse.asked if x in wholes] == wholes
    assert all(market == 'equities' for _, _, market in nse.asked)
    for a, b in months:
        mid = a + (b - a) // 2
        assert (a, mid, 'equities') in nse.asked and (mid + timedelta(days=1), b, 'equities') in nse.asked
    rep = ann.run(FakeR2(), FakeNSE(ROWS, block=True), date(2026, 10, 5), backfill_from=date(2026, 8, 20))
    assert rep['calls'] == [] and rep['added'] == 0 and 'refused' in rep['notes'][0]


def test_xbrl_parse_failure_never_prevents_standard_pdf_archive(monkeypatch):
    class XbrlFakeNSE(FakeNSE):
        def xbrl_announcements(self, a, b, index='equities', symbol=None, feed_type='announcements'):
            return [{'appId': 'bad-xbrl', 'attachment': 'https://nsearchives.nseindia.com/corporate/xbrl/bad.xml'}]

    def broken_parse(*args, **kwargs):
        raise ValueError('malformed XBRL metadata')

    monkeypatch.setattr(ann, 'parse_xbrl', broken_parse)
    r2 = FakeR2()
    rep = ann.run(r2, XbrlFakeNSE(ROWS[:3]), date(2026, 10, 1))
    assert rep['added'] == 3
    assert rep['window_counts']['announcements'] == 3
    assert any('XBRL' in note and 'parse failed' in note for note in rep['notes'])
    archived = pd.concat([pd.read_parquet(io.BytesIO(r2.objects[k]))
                          for k in r2.objects if k.startswith(ann.PREFIX)])
    assert len(archived) == 3
    assert not set(archived['file_type']) & {'xml', 'xbrl'}  # failed optional XBRL parse added no synthetic rows


def test_nightly_run_collects_all_dedicated_xbrl_feed_types():
    class ParaBFakeNSE(FakeNSE):
        def xbrl_announcements(self, a, b, index='equities', symbol=None, feed_type='announcements'):
            self.xbrl_asked.append((a, b, index, feed_type))
            if feed_type == 'para-b':
                return [{'appId': '100779', 'symbol': 'CAMLINFINE', 'isin': 'INE052I01032',
                         'companyName': 'Camlin Fine Sciences Limited',
                         'subject': 'Change in Directors/KMP/SMP/Auditor/RTA',
                         'broadcastDateTime': '18-10-2026 10:59:38',
                         'attachment': 'https://nsearchives.nseindia.com/corporate/xbrl/CIM_11353_WebXMLFile_20261018_105938126.xml'}]
            return []

    r2 = FakeR2()
    nse = ParaBFakeNSE(ROWS[:1])
    rep = ann.run(r2, nse, date(2026, 10, 19))
    assert {feed for _, _, market, feed in nse.xbrl_asked if market == 'equities'} == {
        'announcements', 'para-a', 'para-b', 'award'
    }
    assert {call['feed_type'] for call in rep['xbrl_calls']} == {
        'announcements', 'para-a', 'para-b', 'award'
    }
    archived = pd.concat([pd.read_parquet(io.BytesIO(r2.objects[k]))
                          for k in r2.objects if k.startswith(ann.PREFIX)])
    xbrl = archived[archived['event_id'].astype(str).str.startswith('nse:xbrl:')]
    assert len(xbrl) == 1
    assert xbrl.iloc[0]['file_type'] == 'xbrl'
    assert xbrl.iloc[0]['xbrl_url'].endswith('105938126.xml')


def test_sme_feed_is_not_collected():
    r2 = FakeR2()
    sme = [dict(ROWS[0], seq_id='900000001', symbol='SMEX', desc='Preferential issue')]
    nse = FakeNSE(ROWS[:3], sme=sme)
    rep = ann.run(r2, nse, date(2026, 10, 1))
    assert rep['added'] == 3
    assert [c['market'] for c in rep['calls']] == ['equities']
    assert all(market == 'equities' for _, _, market in nse.asked)
    arch = pd.concat([pd.read_parquet(io.BytesIO(r2.objects[k]))
                      for k in r2.objects if k.startswith(ann.PREFIX)])
    assert set(arch['market']) == {'equities'}
    assert '900000001' not in set(arch['seq_id'])



def test_run_queries_symbol_scoped_integrated_financials_only_for_live_results():
    result_pdf = {
        'seq_id': 'LIVE-RESULTS', 'symbol': 'IOC', 'sm_isin': 'INE242A01010',
        'sm_name': 'Indian Oil Corporation Limited', 'desc': 'Financial Results',
        'attchmntText': 'Unaudited financial results for the quarter ended September 30, 2026',
        'attchmntFile': 'https://nsearchives.nseindia.com/corporate/IOC_results.pdf',
        'an_dt': '30-Sep-2026 18:43:00', 'exchdisstime': '30-Sep-2026 18:43:01',
    }

    class IntegratedFakeNSE(FakeNSE):
        def integrated_filing_financials(self, symbol):
            self.integrated_asked.append((symbol, 'financials'))
            return [{
                'symbol': symbol, 'companyName': 'Indian Oil Corporation Limited',
                'broadcastDateTime': '30-Sep-2026 18:43:11',
                'xbrl': 'https://nsearchives.nseindia.com/corporate/xbrl/IOC_results.xml',
            }]

    nse = IntegratedFakeNSE([result_pdf])
    r2 = FakeR2()
    rep = ann.run(r2, nse, date(2026, 10, 1))
    assert nse.integrated_asked == [('IOC', 'financials')]
    assert any(x['feed_type'] == 'integrated-financials' and x['rows'] == 1 for x in rep['xbrl_calls'])
    archived = pd.concat([pd.read_parquet(io.BytesIO(r2.objects[k]))
                          for k in r2.objects if k.startswith(ann.PREFIX)])
    xml = archived[archived['file_type'] == 'xbrl']
    assert len(xml) == 1 and xml.iloc[0]['file_url'].endswith('IOC_results.xml')
    pdfs = archived[archived['file_url'].astype(str).str.endswith('.pdf')]
    assert not pdfs.empty and pdfs['file_type'].eq('pdf').all()
