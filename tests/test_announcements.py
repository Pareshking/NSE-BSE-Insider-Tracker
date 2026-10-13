"""NSE announcements: parser on real rows fetched 13 Oct 2026 (broadcast in
Sep 2026, tests/fixtures/nse_events/announcements.json) and the nightly run
against an in-memory R2."""
from __future__ import annotations

import io
import json
from datetime import date

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
    assert tci['pdf_url'].endswith('_TCIL.pdf') and tci['pdf_bytes'] == int(969.94 * 1024)


def test_unreadable_time_and_missing_seq_id_are_kept_not_guessed():
    row = dict(ROWS[0], an_dt='not a date', seq_id=None, attFileSize='', fileSize=None)
    df = ann.parse([row, row])
    assert df['broadcast_date'].isna().all() and df['pdf_bytes'].isna().all()
    assert df['event_id'].iloc[0] == df['event_id'].iloc[1]   # same row, same hashed id
    assert ann.partition(None) == 'month=unknown'
    assert ann.size_bytes('0 Bytes') == 0 and ann.size_bytes('2.05 MB') == int(2.05 * 1024 ** 2)


def test_groups_come_from_nse_subject_only():
    assert ann.group_of('Post Buyback Public Announcement') == 'buyback'
    assert ann.group_of('Qualified Institutional Placement') == 'fund_raise'
    assert ann.group_of('Outcome of Board Meeting') == 'to_sort'
    assert ann.group_of('Trading Window') == 'routine' and ann.group_of(None) == 'routine'
    c = ann.counts(ann.parse(ROWS))
    assert c['by_group']['buyback']['announcements'] == 7   # Sep held one post-buyback announcement
    assert sum(g['announcements'] for g in c['by_group'].values()) == len(ROWS)


class FakeNSE:
    def __init__(self, rows, block=False):
        self.rows, self.block, self.calls, self.on_response, self.asked = rows, block, 0, None, []

    def announcements(self, a, b):
        self.calls += 1
        self.asked.append((a, b))
        if self.block:
            raise Blocked('HTTP 403')
        return self.rows


def test_nightly_run_archives_by_month_and_twice_adds_nothing(monkeypatch):
    r2 = FakeR2()
    concall = dict(ROWS[0], seq_id='1', desc='Analysts/Institutional Investor Meet/Con. Call Updates')
    rep = ann.run(r2, FakeNSE(ROWS + [concall]), date(2026, 10, 1))
    assert rep['window'] == ['2026-09-29', '2026-10-01']
    assert rep['added'] == len(ROWS) and rep['calls'][0]['not_archived_concall'] == 1
    keys = [k for k in r2.objects if k.startswith(ann.PREFIX)]
    assert keys and all('/year=2026/month=' in k for k in keys)
    arch = pd.concat([pd.read_parquet(io.BytesIO(r2.objects[k])) for k in keys])
    assert len(arch) == len(ROWS) and '1' not in set(arch['seq_id'])
    assert json.loads(r2.objects['clean/reports/announcements/2026-10-01.json'])['window_counts']['announcements'] \
        == len(ROWS)
    assert ann.run(r2, FakeNSE(ROWS), date(2026, 10, 1))['added'] == 0
    assert 'buyback' in ann.summary_markdown(rep)


def test_backfill_goes_month_by_month_and_refusal_stops():
    r2 = FakeR2()
    nse = FakeNSE(ROWS)
    ann.run(r2, nse, date(2026, 10, 5), backfill_from=date(2026, 8, 20))
    assert nse.asked == [(date(2026, 8, 20), date(2026, 8, 31)), (date(2026, 9, 1), date(2026, 9, 30)),
                         (date(2026, 10, 1), date(2026, 10, 5))]
    rep = ann.run(FakeR2(), FakeNSE(ROWS, block=True), date(2026, 10, 5), backfill_from=date(2026, 8, 20))
    assert rep['calls'] == [] and rep['added'] == 0 and 'refused' in rep['notes'][0]
