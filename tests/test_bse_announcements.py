"""BSE announcements: parser on real rows fetched 13 Oct 2026 (disseminated
12 Oct 2026, one row per category and subcategory seen that day,
tests/fixtures/bse/announcements.json) and the nightly run against an
in-memory R2 with BSE's paging."""
from __future__ import annotations

import io
import json
from datetime import date

import pandas as pd
from conftest import FIXTURES
from test_archive_and_writer import FakeR2

from collectors.bse import announcements as ann
from collectors.bse.client import Blocked

ROWS = json.loads((FIXTURES / 'bse' / 'announcements.json').read_text(encoding='utf-8'))


def test_parse_keeps_values_as_filed_with_bse_attachment_link():
    df = ann.parse(ROWS)
    assert len(df) == len({r['NEWSID'] for r in ROWS}) and df['event_id'].is_unique
    reit = df[df['news_id'] == '167c112f-bd71-4a7d-b7ca-77eb889f6df6'].iloc[0]
    assert (reit['bse_code'], reit['category'], reit['subcategory']) == ('544462', 'Others', None)
    assert reit['file_url'] == ann.ATTACHMENT + '276c5bba-13df-4f61-8df9-351d6f40e07e.pdf'
    assert reit['file_bytes'] == 887196 and reit['file_type'] == 'pdf'
    assert reit['broadcast_at'] == '2026-10-12T23:52:03.927000+05:30' and reit['broadcast_date'] == '2026-10-12'
    none = df[df['file_url'].isna()]
    assert len(none) >= 1 and none['file_bytes'].isna().all()
    assert ann.parse([dict(ROWS[0], NEWSID=None)]).empty   # no id: not archived, counted by the run


def test_groups_come_from_bse_subcategory():
    assert ann.group_of('Preferential Issue') == 'fund_raise'
    assert ann.group_of('Open Offer') == 'takeover'
    assert ann.group_of('Outcome of Board Meeting') == 'to_sort'
    assert ann.group_of(None, 'Others') == 'to_sort'
    assert ann.group_of('Certificate under Reg. 74 (5) of SEBI (DP) Regulations, 2018') == 'routine'
    assert ann.group_of('Daily Buy Back of equity shares') == 'routine'
    subs = {r['SUBCATNAME'] for r in ROWS}
    assert all(s in subs for g in ann.READING_GROUPS.values() for s in g)   # every mapped name seen on 12 Oct
    assert set(ann.CONCALL) <= subs


class FakeBSE:
    """BSE's paging: 50 rows a page (here `size`), Table1's count for the day."""

    def __init__(self, rows, size=20, block_on=None):
        self.rows, self.size, self.block_on, self.calls, self.via, self.asked = rows, size, block_on, 0, 'requests', []

    def announcements(self, day, page):
        self.calls += 1
        self.asked.append((day, page))
        if day == self.block_on:
            raise Blocked('HTTP 403')
        day_rows = [r for r in self.rows if r['NEWS_DT'][:10] == day.isoformat()]
        return day_rows[(page - 1) * self.size:page * self.size], len(day_rows)


def test_run_reads_every_page_and_twice_adds_nothing():
    r2 = FakeR2()
    bse = FakeBSE(ROWS)
    rep = ann.run(r2, bse, date(2026, 10, 13), days=2)
    assert [d['day'] for d in rep['days']] == ['2026-10-12', '2026-10-13']
    d12 = rep['days'][0]
    assert d12['bse_count'] == len(ROWS) and d12['unique'] == len(ROWS) and not d12['short']
    assert d12['pages'] == -(-len(ROWS) // 20)
    concall = sum(r['SUBCATNAME'] in ann.CONCALL for r in ROWS)
    assert concall and d12['concall'] == concall and rep['added'] == len(ROWS)   # concalls are archived since 15 Oct
    keys = [k for k in r2.objects if k.startswith(ann.PREFIX)]
    assert keys == [ann.PREFIX + 'year=2026/month=10.parquet']
    arch = pd.read_parquet(io.BytesIO(r2.objects[keys[0]]))
    assert len(arch) == len(ROWS)
    assert json.loads(r2.objects['clean/reports/announcements_bse/2026-10-13.json'])['added'] == rep['added']
    assert ann.run(r2, FakeBSE(ROWS), date(2026, 10, 13), days=2)['added'] == 0
    assert 'BSE-only share not counted' in ann.summary_markdown(rep)


def test_short_day_and_refusal_are_reported(monkeypatch):
    monkeypatch.setattr(ann, 'SHORT_PAUSE', 0)
    class Short(FakeBSE):
        def announcements(self, day, page):
            rows, n = super().announcements(day, page)
            return (rows if page == 1 else []), n
    rep = ann.run(None, Short(ROWS), date(2026, 10, 12), days=1)
    assert rep['days'][0]['short'] and 'fewer filings than BSE counts on 2026-10-12' in rep['notes']
    rep = ann.run(None, FakeBSE(ROWS, block_on=date(2026, 10, 12)), date(2026, 10, 12), days=1)
    assert rep['days'] == [] and 'refused' in rep['notes'][0]


def test_bse_only_share_from_the_security_master():
    class Master:
        def resolve(self, exchange, code):
            return ({'516038': 'INE1', '544462': 'INE2'}.get(code), 'code')

        def record(self, isin):
            return {'INE1': {'nse_symbol': None}, 'INE2': {'nse_symbol': 'X'}}.get(isin)
    df = ann.parse(ROWS)
    listed = ann.on_nse(df, Master())
    c = ann.counts(df, listed)
    unmatched = sum(code not in ('516038', '544462') for code in df['bse_code'])
    assert c['bse_only']['announcements'] == unmatched + int((df['bse_code'] == '516038').sum())
    assert ann.counts(df, ann.on_nse(df, None)).get('bse_only') is None


def test_incremental_run_stops_paging_at_known_filings():
    r2 = FakeR2()
    ann.run(r2, FakeBSE(ROWS), date(2026, 10, 12), days=1)
    bse = FakeBSE(ROWS)
    rep = ann.run(r2, bse, date(2026, 10, 12), days=1, incremental=True)
    assert bse.calls == 1 and rep['days'][0]['caught_up'] and not rep['days'][0]['short'] and rep['added'] == 0

def test_history_collection_logs_day_progress(capsys):
    report = ann.run(FakeR2(), FakeBSE([]), date(2026, 10, 14),
                     start=date(2026, 1, 1), end=date(2026, 1, 1))
    output = capsys.readouterr().out
    assert 'BSE collection: starting 2026-01-01' in output
    assert 'BSE collection: finished 2026-01-01 pages=1' in output
    assert report['days'][0]['day'] == '2026-01-01'


def test_bse_http_request_has_bounded_timeout():
    from collectors.bse.client import BSEClient

    class Response:
        status_code = 200
        headers = {'Content-Type': 'application/json'}
        content = b'{}'

    class Session:
        def __init__(self):
            self.headers = {}
            self.timeout = None

        def get(self, url, params, timeout):
            self.timeout = timeout
            return Response()

    session = Session()
    client = BSEClient(session=session, sleep=lambda _: None, pace=(0, 0), allow_in_page=False)
    status, _, _ = client._fetch('https://example.test/api', {})
    assert status == 200
    assert session.timeout == 45


def _concall_rows(day):
    return [
        dict(ROWS[0], NEWSID='call-1', NEWS_DT=day.isoformat() + 'T10:00:00', SUBCATNAME=ann.CONCALL[0]),
        dict(ROWS[1], NEWSID='call-2', NEWS_DT=day.isoformat() + 'T10:01:00', SUBCATNAME=ann.CONCALL[1]),
        dict(ROWS[2], NEWSID='known-3', NEWS_DT=day.isoformat() + 'T10:02:00', SUBCATNAME='Preferential Issue'),
    ]


def test_incremental_fetch_counts_archived_concall_rows_as_known():
    day = date(2026, 10, 12)
    bse = FakeBSE(_concall_rows(day), size=2)
    fetched, stats = ann.fetch_day(bse, day, known={'call-1', 'call-2'})
    assert bse.asked == [(day, 1)] and len(fetched) == 2 and stats['caught_up']


def test_incremental_fetch_continues_past_a_page_with_an_unknown_concall():
    day = date(2026, 10, 12)
    bse = FakeBSE(_concall_rows(day), size=2)
    fetched, stats = ann.fetch_day(bse, day, known={'call-2', 'known-3'})
    assert bse.asked == [(day, 1), (day, 2)] and len(fetched) == 3
    assert stats['caught_up'] and not stats['short']
