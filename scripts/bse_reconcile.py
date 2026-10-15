"""Does each archived BSE day hold what BSE says it holds? (one request a day, no filing text)

BSE states its count of filings for a day on the first page of that day's list. For every day in the window this asks
for page 1, counts the archived filings of the day (archive/announcements/bse/) and compares:

    ok         the archive holds BSE's count
    one_short  one fewer: usually a row BSE sends without a NEWSID (the archive cannot key it; the raw answers keep it)
    short      two or more fewer: filings are missing, fetch the day again (announcement-collect.yml, exchanges=bse)
    over       the archive holds more than BSE counts now (BSE removed or re-dated some)

The result is kept per day in clean/reports/announcements_bse/reconciliation/check/{day}.json. Exit code 3 when a day is
`short` or `over`. Nothing else is written; no model.

    python scripts/bse_reconcile.py --from 2026-01-01          # to today
    python scripts/bse_reconcile.py --days 7                   # the last 7 days (the nightly guard)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

from collectors.bse import announcements as bann  # noqa: E402
from collectors.bse.client import Blocked, BSEClient, Failed  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
CHECK = bann.RECONCILIATION + 'check/'


def archived_counts(r2, first: date, last: date) -> dict[str, int]:
    from clean_writer import read_parquet
    counts: dict[str, int] = {}
    cur = date(first.year, first.month, 1)
    while cur <= last:
        df = read_parquet(r2, f'{bann.PREFIX}{bann.partition(cur.isoformat())}.parquet')
        if df is not None and not df.empty:
            for day, n in df['broadcast_date'].astype(str).value_counts().items():
                counts[day] = counts.get(day, 0) + int(n)
        cur = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
    return counts


def status_of(bse_count: int, archived: int) -> str:
    diff = bse_count - archived
    return 'ok' if diff == 0 else 'one_short' if diff == 1 else 'over' if diff < 0 else 'short'


def reconcile(r2, bse, first: date, last: date, write: bool = True, run_id: str | None = None) -> list[dict]:
    from clean_writer import put
    have = archived_counts(r2, first, last)
    out, day = [], first
    while day <= last:
        try:
            _, count = bse.announcements(day, 1)
        except (Blocked, Failed) as exc:
            out.append({'day': day.isoformat(), 'status': 'not_checked', 'reason': f'{type(exc).__name__}: {exc}'})
            if isinstance(exc, Blocked):
                break
            day += timedelta(days=1)
            continue
        archived = have.get(day.isoformat(), 0)
        rec = {'day': day.isoformat(), 'bse_count': count, 'archived': archived,
               'status': status_of(count, archived) if count is not None else 'not_checked',
               'checked_at_utc': datetime.now(timezone.utc).isoformat(), 'workflow_run_id': run_id or os.environ.get('GITHUB_RUN_ID')}
        out.append(rec)
        if write:
            put(r2, f"{CHECK}{rec['day']}.json", json.dumps(rec, indent=1).encode(), 'application/json')
        day += timedelta(days=1)
    return out


def markdown(rows: list[dict]) -> str:
    tally = pd.Series([r['status'] for r in rows]).value_counts().to_dict()
    out = ['## BSE: archive against BSE\'s own count, day by day', '', f'{len(rows)} days checked: {tally}', '']
    bad = [r for r in rows if r['status'] != 'ok']
    if bad:
        out += ['| day | BSE says | archived | status |', '|---|---|---|---|']
        out += [f"| {r['day']} | {r.get('bse_count')} | {r.get('archived')} | {r['status']}{(' ' + r['reason']) if r.get('reason') else ''} |"
                for r in bad]
    return '\n'.join(out) + '\n'


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--from', dest='first', type=date.fromisoformat, default=None)
    ap.add_argument('--to', dest='last', type=date.fromisoformat, default=None)
    ap.add_argument('--days', type=int, default=7)
    args = ap.parse_args(argv)
    from insiders_clean.raw_store import RawStore
    from r2_writer import r2_client
    today = datetime.now(IST).date()
    last = args.last or today
    first = args.first or last - timedelta(days=args.days - 1)
    r2 = r2_client()
    bse = BSEClient(raw=RawStore(r2, collector='bse_reconcile'))
    try:
        rows = reconcile(r2, bse, first, last)
    finally:
        bse.close()
    text = markdown(rows)
    print(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as f:
            f.write(text)
    live = today.isoformat()   # today's own day grows while it is read
    return 3 if any(r['status'] in ('short', 'over') and r['day'] != live for r in rows) else 0


if __name__ == '__main__':
    sys.exit(main())
