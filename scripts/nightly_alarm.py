"""Fail the nightly run loudly when data was not written (owner, 18 Nov 2026: "Yes" to an alarm).

From at least 13 Nov 2026 NSE bulk and block deals, rights and preferential issues were skipped every night (NSE moved
to nseindia.in; the browser fetch was blocked) and BSE promoter-group batches failed to save, while R2 Storage Write
reported success. This runs as the last step of that workflow, after every collector, the clean step and Precompute,
so nothing is held back; it fails the run (a red run and GitHub's failure email) when:

  - a dataset in the manifest r2_writer wrote (artifacts/r2_manifest.json) was not written, with its reason;
  - the BSE events step (artifacts/bse_events.log) printed a note saying something failed.

The watchdog (scripts/nightly_watchdog.py) does not restart a run whose only failed step is this one: the data that
could be fetched was written; starting again would ask the exchanges for the same thing.

    python scripts/nightly_alarm.py [manifest] [bse_log]
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

STEP_NAME = 'Alarm: data not written'
NOTE = re.compile(r'note:\s*(.+?failed.*)$', re.IGNORECASE)


def problems(manifest: dict | None, bse_log: str | None) -> list[str]:
    out = []
    if manifest is None:
        out.append('no manifest: r2_writer did not finish, nothing is known about what was written')
    else:
        for d in manifest.get('datasets', []):
            if not d.get('written'):
                name = f"{d.get('exchange', '?')}/{d.get('category', d.get('dataset', '?'))}"
                out.append(f"{name} not written: {d.get('reason', 'no reason given')}")
        for d in manifest.get('reference_data', []):
            if d and not d.get('written'):
                out.append(f"{d.get('dataset', 'reference')} not written: {d.get('reason', 'no reason given')}")
    for line in (bse_log or '').splitlines():
        m = NOTE.search(line)
        if m:
            out.append(f'BSE events: {m[1].strip()}')
    return out


def main(argv: list[str]) -> int:
    mpath = Path(argv[0] if argv else 'artifacts/r2_manifest.json')
    lpath = Path(argv[1] if len(argv) > 1 else 'artifacts/bse_events.log')
    manifest = json.loads(mpath.read_text()) if mpath.exists() else None
    bse_log = lpath.read_text(errors='replace') if lpath.exists() else None
    found = problems(manifest, bse_log)
    lines = [f'- {p}' for p in found] or ['- every dataset written; no failed note']
    print('\n'.join(lines))
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a') as fh:
            fh.write('## Nightly alarm\n\n' + '\n'.join(lines) + '\n')
    for p in found:
        print(f'::error title=Data not written::{p}')
    return 1 if found else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
