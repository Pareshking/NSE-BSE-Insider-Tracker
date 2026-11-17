"""Start a nightly run GitHub dropped (owner, 17 Nov 2026: "Yes I want" a safety net).

On 16 Nov 2026 GitHub started neither R2 Storage Write (18:00 UTC) nor its 23:00 backup, so the clean step did not run
and the site stayed on 13 Nov data until it was started by hand. This runs a few times each morning (UTC). For each
nightly workflow it finds the last time the workflow was due, allowing `GRACE_HOURS` for GitHub's late starts, and:

  ok     a full run that started after that time succeeded: nothing to do;
  busy   a run is queued or running: wait for it (GitHub keeps one waiting run per group, a second would replace it);
  start  neither: start it (workflow_dispatch, default inputs) and say so in the job summary.

A full run is a scheduled one, or a manual one of the whole workflow: for NSE events only `dataset` all counts (a
results backfill is not the nightly), told by the run name.

    python scripts/nightly_watchdog.py            # needs GH_TOKEN and GITHUB_REPOSITORY (the gh CLI)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

GRACE_HOURS = 6
# workflow file -> (weekdays due, Monday 0; hour UTC; run names that count as a full run besides scheduled ones)
WATCHED = {
    'r2-storage.yml': ((0, 1, 2, 3, 4), 18, None),
    'nse-events.yml': ((0, 1, 2, 3, 4, 5), 16, 'NSE Corporate Events (all)'),
}


def last_due(now: datetime, weekdays, hour: int, grace_hours: int = GRACE_HOURS) -> datetime:
    """The latest due time at least `grace_hours` before now."""
    limit = now - timedelta(hours=grace_hours)
    d = limit.replace(hour=hour, minute=0, second=0, microsecond=0)
    if d > limit:
        d -= timedelta(days=1)
    while d.weekday() not in weekdays:
        d -= timedelta(days=1)
    return d


def _full(run: dict, full_name: str | None) -> bool:
    if run.get('event') == 'schedule':
        return True
    return full_name is None or run.get('displayTitle') == full_name


def decide(runs: list[dict], due: datetime, full_name: str | None = None) -> str:
    """'ok', 'busy' or 'start' for runs as `gh run list --json event,status,conclusion,createdAt,displayTitle` gives."""
    if any(r.get('status') != 'completed' for r in runs):
        return 'busy'
    for r in runs:
        created = datetime.fromisoformat(str(r.get('createdAt', '')).replace('Z', '+00:00'))
        if created >= due and r.get('conclusion') == 'success' and _full(r, full_name):
            return 'ok'
    return 'start'


def gh(*args: str) -> str:
    return subprocess.run(['gh', *args], check=True, capture_output=True, text=True).stdout


def main() -> int:
    now = datetime.now(timezone.utc)
    repo = os.environ['GITHUB_REPOSITORY']
    lines = []
    for wf, (days, hour, full_name) in WATCHED.items():
        due = last_due(now, days, hour)
        runs = json.loads(gh('run', 'list', '-R', repo, '--workflow', wf, '--limit', '30',
                             '--json', 'event,status,conclusion,createdAt,displayTitle'))
        state = decide(runs, due, full_name)
        if state == 'start':
            gh('workflow', 'run', wf, '-R', repo)
        lines.append(f'- {wf}: due {due:%a %d %b %H:%M} UTC -> {state}'
                     + (' (started: no full run succeeded since it was due, none waiting)' if state == 'start' else ''))
    print('\n'.join(lines))
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a') as fh:
            fh.write('## Nightly watchdog\n\n' + '\n'.join(lines) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
