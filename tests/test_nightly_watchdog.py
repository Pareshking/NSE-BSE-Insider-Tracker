"""scripts/nightly_watchdog.py: when a nightly run was due, and whether to start it."""
from __future__ import annotations

from datetime import datetime, timezone

import nightly_watchdog as w

UTC = timezone.utc


def test_due_is_the_last_weekday_slot_past_the_grace():
    # Tue 17 Nov 2026 01:37 UTC: R2 Storage Write was due Mon 16 Nov 18:00 (7h37 ago, past the 6h grace)
    assert w.last_due(datetime(2026, 11, 17, 1, 37, tzinfo=UTC), (0, 1, 2, 3, 4), 18) == datetime(2026, 11, 16, 18, tzinfo=UTC)
    # Mon 16 Nov 20:00: Monday's slot is only 2h old, so the last one past the grace is Friday 13 Nov
    assert w.last_due(datetime(2026, 11, 16, 20, 0, tzinfo=UTC), (0, 1, 2, 3, 4), 18) == datetime(2026, 11, 13, 18, tzinfo=UTC)
    # Sun 15 Nov: NSE events runs Mon-Sat, so Saturday 14 Nov 16:00
    assert w.last_due(datetime(2026, 11, 15, 7, 37, tzinfo=UTC), (0, 1, 2, 3, 4, 5), 16) == datetime(2026, 11, 14, 16, tzinfo=UTC)


def test_decide_starts_only_a_dropped_run():
    due = datetime(2026, 11, 16, 18, tzinfo=UTC)
    old = {'event': 'schedule', 'status': 'completed', 'conclusion': 'success', 'createdAt': '2026-11-14T02:45:25Z'}
    assert w.decide([old], due) == 'start'                       # 16 Nov 2026: nothing since Friday
    late = {**old, 'createdAt': '2026-11-17T00:10:00Z'}
    assert w.decide([late, old], due) == 'ok'                    # started late but succeeded
    waiting = {**old, 'status': 'queued', 'conclusion': None, 'createdAt': '2026-11-17T01:00:00Z'}
    assert w.decide([waiting, old], due) == 'busy'               # never queue a second behind it
    failed = {**late, 'conclusion': 'failure'}
    assert w.decide([failed, old], due) == 'start'


def test_a_results_backfill_is_not_the_nightly():
    due = datetime(2026, 11, 16, 16, tzinfo=UTC)
    name = 'NSE Corporate Events (all)'
    backfill = {'event': 'workflow_dispatch', 'status': 'completed', 'conclusion': 'success',
                'createdAt': '2026-11-16T20:00:00Z', 'displayTitle': 'NSE Corporate Events (results)'}
    assert w.decide([backfill], due, name) == 'start'
    assert w.decide([{**backfill, 'displayTitle': name}], due, name) == 'ok'


def test_a_run_red_only_from_the_data_alarm_is_not_restarted():
    due = datetime(2026, 11, 16, 18, tzinfo=UTC)
    alarm = {'event': 'schedule', 'status': 'completed', 'conclusion': 'failure', 'createdAt': '2026-11-17T00:10:00Z',
             'failed_steps': ['Alarm: data not written']}
    assert w.decide([alarm], due) == 'ok'
    crashed = {**alarm, 'failed_steps': ['NSE Bulk', 'Alarm: data not written']}
    assert w.decide([crashed], due) == 'start'
    unknown = {**alarm, 'failed_steps': None}
    assert w.decide([unknown], due) == 'start'
