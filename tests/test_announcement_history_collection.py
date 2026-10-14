"""Bounded date windows used by the historical announcement collection workflow."""
from datetime import date

from test_announcements import FakeNSE, ROWS as NSE_ROWS
from test_bse_announcements import FakeBSE
from test_archive_and_writer import FakeR2
from collectors.nse_events import announcements as nse_ann
from collectors.bse import announcements as bse_ann


def test_nse_history_collector_honours_bounded_month():
    nse = FakeNSE(NSE_ROWS)
    report = nse_ann.run(FakeR2(), nse, date(2026, 10, 14),
                         backfill_from=date(2026, 1, 1), backfill_to=date(2026, 1, 31))
    assert report['window'] == ['2026-01-01', '2026-01-31']
    assert nse.asked == [(date(2026, 1, 1), date(2026, 1, 31), market)
                         for market in ('equities', 'sme')]


def test_bse_history_collector_stops_at_requested_end_date():
    bse = FakeBSE([])
    report = bse_ann.run(FakeR2(), bse, date(2026, 10, 14),
                         start=date(2026, 1, 1), end=date(2026, 1, 2))
    assert report['window'] == ['2026-01-01', '2026-01-02']
    assert [day for day, _ in bse.asked] == [date(2026, 1, 1), date(2026, 1, 2)]
