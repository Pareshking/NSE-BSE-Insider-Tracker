"""A day is complete, or it is named as short: BSE's count against ours, a repeat fetch, NSE's two-halves check."""
from __future__ import annotations

import io
import json
from datetime import date

import pandas as pd
from test_announcements import ROWS as NSE_ROWS
from test_announcements import FakeNSE
from test_archive_and_writer import FakeR2
from test_bse_announcements import ROWS as BSE_ROWS
from test_bse_announcements import FakeBSE

from collectors.bse import announcements as bann
from collectors.nse_events import announcements as nann

DAY = date(2026, 10, 12)


class FlakyBSE(FakeBSE):
    """The first `degraded` full fetches of a day lose a page in the middle but still report the full count."""

    def __init__(self, rows, degraded=1, **kw):
        super().__init__(rows, **kw)
        self.degraded = degraded

    def announcements(self, day, page):
        self.calls += 1
        self.asked.append((day, page))
        day_rows = [r for r in self.rows if r['NEWS_DT'][:10] == day.isoformat()]
        if page == 1 and self.degraded > 0:
            self.degraded -= 1
            self._cycle_degraded = True
        elif page == 1:
            self._cycle_degraded = False
        kept = day_rows[:self.size] + day_rows[2 * self.size:] if getattr(self, '_cycle_degraded', False) else day_rows
        return kept[(page - 1) * self.size:page * self.size], len(day_rows)


def _no_pause(monkeypatch):
    monkeypatch.setattr(bann, 'SHORT_PAUSE', 0)


def _archive(r2, prefix):
    keys = [k for k in r2.objects if k.startswith(prefix) and k.endswith('.parquet')]
    return pd.concat([pd.read_parquet(io.BytesIO(r2.objects[k])) for k in keys])


def test_a_short_day_is_fetched_again_and_the_repeat_completes_it(monkeypatch):
    _no_pause(monkeypatch)
    r2 = FakeR2()
    bse = FlakyBSE(BSE_ROWS, degraded=1)
    rep = bann.run(r2, bse, date(2026, 10, 13), start=DAY, end=DAY)
    day = rep['days'][0]
    assert day['retries'] == 1 and not day['short'] and day['unique'] == day['bse_count'] == len(BSE_ROWS)
    assert rep['short_days'] == [] and len(_archive(r2, bann.PREFIX)) == len(BSE_ROWS)
    rec = json.loads(r2.objects[bann.RECONCILIATION + '2026-10-12.json'])
    assert rec['bse_count'] == rec['fetched_unique'] == len(BSE_ROWS) and rec['retries'] == 1 and not rec['short']


def test_a_finished_day_still_short_after_the_repeats_is_reported_but_today_is_not(monkeypatch):
    _no_pause(monkeypatch)
    bse = FlakyBSE(BSE_ROWS, degraded=99)
    rep = bann.run(FakeR2(), bse, date(2026, 10, 13), start=DAY, end=DAY)
    assert rep['days'][0]['short'] and rep['days'][0]['retries'] == bann.SHORT_RETRIES
    assert rep['short_days'] == ['2026-10-12'] and any('fewer filings' in n for n in rep['notes'])
    live = bann.run(FakeR2(), FlakyBSE(BSE_ROWS, degraded=99), DAY, start=DAY, end=DAY)   # the day is still running
    assert live['days'][0]['short'] and live['short_days'] == []


def test_rows_without_an_id_count_in_the_day_and_are_kept_in_the_reconciliation():
    r2 = FakeR2()
    noid = dict(BSE_ROWS[0], NEWSID=None, NEWSSUB='no id filing')
    rep = bann.run(r2, FakeBSE(BSE_ROWS + [noid]), date(2026, 10, 13), start=DAY, end=DAY)
    assert not rep['days'][0]['short'] and rep['short_days'] == []
    rec = json.loads(r2.objects[bann.RECONCILIATION + '2026-10-12.json'])
    assert rec['rows_without_id'] == 1 and rec['without_id'][0]['NEWSSUB'] == 'no id filing'
    assert len(_archive(r2, bann.PREFIX)) == len(BSE_ROWS)   # the archive cannot key it; raw and the record keep it


def test_an_incremental_top_up_writes_no_reconciliation():
    r2 = FakeR2()
    bann.run(r2, FakeBSE(BSE_ROWS), date(2026, 10, 13), start=DAY, end=DAY)
    before = set(r2.objects)
    bann.run(r2, FakeBSE(BSE_ROWS), date(2026, 10, 13), start=DAY, end=DAY, incremental=True)
    assert [k for k in r2.objects if k.startswith(bann.RECONCILIATION)] == [bann.RECONCILIATION + '2026-10-12.json']
    assert set(r2.objects) - before <= set()


class LossyNSE(FakeNSE):
    """The first (whole-window) answer lacks one filing; the two halves have everything."""

    def announcements(self, a, b, index='equities'):
        rows = super().announcements(a, b, index)
        return rows[:-1] if self.calls == 1 else rows


def test_the_nse_cross_check_adds_filings_the_first_fetch_lacked_and_says_so():
    r2 = FakeR2()
    rep = nann.run(r2, LossyNSE(NSE_ROWS), date(2026, 10, 1))
    call = rep['calls'][0]
    assert call['cross_check']['only_second'] == 1 and call['cross_check']['only_first'] == 0
    assert rep['added'] == len(NSE_ROWS) and any('the two fetches differ' in n for n in rep['notes'])


def test_the_nse_cross_check_is_quiet_when_both_fetches_agree():
    rep = nann.run(FakeR2(), FakeNSE(NSE_ROWS), date(2026, 10, 1))
    check = rep['calls'][0]['cross_check']
    assert check['only_first'] == check['only_second'] == 0 and check['first'] == len(NSE_ROWS)
    assert not [n for n in rep['notes'] if 'differ' in n]


def test_reconcile_compares_each_day_with_bse_and_names_the_short_ones():
    import bse_reconcile as rc
    r2 = FakeR2()
    bann.run(r2, FakeBSE(BSE_ROWS), date(2026, 10, 13), start=DAY, end=DAY)
    rows = rc.reconcile(r2, FakeBSE(BSE_ROWS), DAY, date(2026, 10, 13))
    assert [(r['day'], r['status']) for r in rows] == [('2026-10-12', 'ok'), ('2026-10-13', 'ok')]   # 13 Oct: 0 and 0
    assert json.loads(r2.objects[rc.CHECK + '2026-10-12.json'])['bse_count'] == len(BSE_ROWS)
    # lose three filings from the archive: short; BSE counts one more than we hold: one_short; fewer than BSE: over
    key = bann.PREFIX + 'year=2026/month=10.parquet'
    arch = pd.read_parquet(io.BytesIO(r2.objects[key]))
    buf = io.BytesIO()
    arch.iloc[3:].to_parquet(buf, index=False)
    r2.objects[key] = buf.getvalue()
    assert rc.reconcile(r2, FakeBSE(BSE_ROWS), DAY, DAY)[0]['status'] == 'short'
    assert rc.status_of(10, 9) == 'one_short' and rc.status_of(9, 10) == 'over' and rc.status_of(5, 5) == 'ok'
    assert 'short' in rc.markdown(rc.reconcile(r2, FakeBSE(BSE_ROWS), DAY, DAY, write=False))


def test_reconcile_stops_when_bse_refuses():
    import bse_reconcile as rc
    rows = rc.reconcile(FakeR2(), FakeBSE(BSE_ROWS, block_on=DAY), DAY, date(2026, 10, 13))
    assert rows == [{'day': '2026-10-12', 'status': 'not_checked', 'reason': 'Blocked: HTTP 403'}]
