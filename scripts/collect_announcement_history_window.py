"""Collect one bounded NSE/BSE history window and fail closed on partial coverage."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def validate_nse(report: dict, start: date, end: date, feeds: tuple[str, ...]) -> list[str]:
    errors = list(report.get("notes") or [])
    if report.get("window") != [start.isoformat(), end.isoformat()]:
        errors.append("NSE report window differs from requested dates")
    expected = {(a.isoformat(), b.isoformat(), market)
                for a, b in _month_chunks(start, end) for market in feeds}
    actual = {(str(c.get("from")), str(c.get("to")), str(c.get("market")))
              for c in report.get("calls", [])}
    missing = sorted(expected - actual)
    if missing:
        errors.append("missing NSE feed windows: " + ", ".join("/".join(x) for x in missing))
    return errors


def validate_bse(report: dict, start: date, end: date) -> list[str]:
    errors = list(report.get("notes") or [])
    if report.get("window") != [start.isoformat(), end.isoformat()]:
        errors.append("BSE report window differs from requested dates")
    expected, day = [], start
    while day <= end:
        expected.append(day.isoformat())
        day += timedelta(days=1)
    actual = [str(item.get("day")) for item in report.get("days", [])]
    if actual != expected:
        errors.append("BSE daily coverage mismatch; missing="
                      + repr(sorted(set(expected) - set(actual))))
    return errors


def _month_chunks(start: date, end: date):
    cursor = start
    while cursor <= end:
        nxt = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        yield cursor, min(nxt - timedelta(days=1), end)
        cursor = nxt


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--from", dest="start", type=date.fromisoformat, required=True)
    parser.add_argument("--to", dest="end", type=date.fromisoformat, required=True)
    args = parser.parse_args(argv)
    if args.end < args.start:
        parser.error("--to must be on or after --from")

    from r2_writer import BUCKET, r2_client
    from insiders_clean.raw_store import RawStore
    from collectors.nse_events import announcements as nse
    from collectors.bse import announcements as bse
    from collectors.nse_events.run_daily import security_master

    today = datetime.now(nse.IST).date()
    r2 = r2_client()
    setup = []
    master = security_master(r2, today.isoformat(), setup)
    nse_report = nse.run(
        r2, nse.NSEClient(), today,
        raw=RawStore(r2, bucket=BUCKET, collector="nse_announcements"),
        backfill_from=args.start, backfill_to=args.end,
    )
    bse_client = bse.BSEClient(raw=RawStore(r2, collector="bse_announcements"))
    try:
        bse_report = bse.run(r2, bse_client, today, start=args.start, end=args.end, master=master)
    finally:
        bse_client.close()

    print(nse.summary_markdown(nse_report), flush=True)
    print(bse.summary_markdown(bse_report), flush=True)
    errors = validate_nse(nse_report, args.start, args.end, tuple(nse.FEEDS))
    errors += validate_bse(bse_report, args.start, args.end)
    if errors:
        raise SystemExit("historical collection incomplete; no completion marker written: " + "; ".join(errors))
    print(f"Verified both exchanges covered {args.start} through {args.end}.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
