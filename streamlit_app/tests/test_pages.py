"""Headless checks for the Streamlit frontend. No R2 credentials needed.

    python streamlit_app/tests/test_pages.py

Runs every page through Streamlit's own AppTest runner against an in-memory
fake bucket (fake_r2.py), under a matrix of the data shapes real runs
actually produce -- including ones where an exchange didn't publish a
canonical field, and one where R2 itself is unreachable.

Each scenario asserts two things:
  * the page renders without an uncaught exception, and
  * when R2 is down, the page SAYS SO rather than dying -- because an
    uncaught exception renders the bucket name and server paths into the
    browser (see .streamlit/config.toml's showErrorDetails note).

Every case here is a bug that was live at some point, not a hypothetical.
"""
import logging
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO / "streamlit_app"))

for name, value in {
    "CLOUDFLARE_ACCOUNT_ID": "test-account", "R2_ACCESS_KEY_ID": "test-key",
    "R2_SECRET_ACCESS_KEY": "test-secret", "R2_BUCKET_NAME": "test-bucket",
}.items():
    os.environ.setdefault(name, value)

import boto3
import pandas as pd
import streamlit as st

import fake_r2
from lib import fields

# st.page_link needs a live st.navigation context, which AppTest doesn't set
# up when running a single page file directly.
st.page_link = lambda *a, **kw: None

from streamlit.testing.v1 import AppTest  # noqa: E402  (after the stub above)

PAGES = [
    "overview", "confluence_screener", "entity_tracker", "transactions",
    "promoter_activity", "bulk_block_concentration", "data_quality",
]

# Each entry: a shape a real run has produced or could produce. The
# drop_cols cases stand in for an exchange that didn't publish that field --
# every one of these crashed a page before lib/fields.py existed.
SCENARIOS = [
    ("baseline", dict()),
    ("no person_category", dict(drop_cols=["canonical_person_category"])),
    ("no side", dict(drop_cols=["canonical_side"])),
    ("no client", dict(drop_cols=["canonical_client"])),
    ("no isin", dict(drop_cols=["canonical_isin"])),
    ("no allottee category", dict(drop_cols=["canonical_allottee_category"])),
    ("no market cap reference", dict(with_mcap=False)),
    ("no value/qty/price", dict(drop_cols=["canonical_value", "canonical_quantity", "canonical_price"])),
    # BSE writing text where NSE writes numbers. Each file is uniform; the
    # mixture appears when load_combined concatenates them, and it took down
    # Evidence & Drill-down and Promoter Activity on the live app.
    ("BSE quantity as text", dict(cast_by_exchange={"bse": {"canonical_quantity": str}})),
    ("BSE price as text", dict(cast_by_exchange={"bse": {"canonical_price": str}})),
    ("BSE holdings as text", dict(cast_by_exchange={"bse": {
        "canonical_holding_before": str, "canonical_holding_after": str}})),
    ("exchange not a string", dict(cast_by_exchange={"bse": {"exchange": lambda v: 2}})),
    ("mixed-type filter column", dict(cast_by_exchange={"bse": {"canonical_person_category": lambda v: 7}})),
]

DATES = ["2026-09-02", "2026-09-01"]

# The real formats seen in artifacts/, and the day each has to resolve to.
# A blanket dayfirst=True reads the first as 9 January; pandas' default
# reads the BSE one as 8 March.
DATE_CASES = {
    "2026-09-01": "2026-09-01",                 # NSE insider `date`
    "2026-08-30T18:30:00.000Z": "2026-08-31",   # NSE IST midnight, stamped in UTC
    "31-AUG-2026": "2026-08-31",                # NSE bulk `BD_DT_DATE`
    "31/08/2026": "2026-08-31",                 # BSE `event_date`
    "03/04/2026": "2026-04-03",                 # BSE, day-first and ambiguous
    "31-Aug-2026 17:40:12": "2026-08-31",       # NSE `broadcastDt`
    "garbage": None,                            # never guessed at
}


def check_dates() -> list[str]:
    failures = []
    parsed = fields.parse_dates(pd.Series(list(DATE_CASES)))
    for (raw, expected), value in zip(DATE_CASES.items(), parsed):
        ok = (pd.isna(value) and expected is None) or (
            pd.notna(value) and value.strftime("%Y-%m-%d") == expected)
        if not ok:
            failures.append(f"parse_dates({raw!r}) -> {value}, expected {expected}")
    return failures


def check_ordering() -> list[str]:
    """Evidence & Drill-down must render newest-first in every tab.

    It shipped with no ordering at all, so rows appeared in whatever order
    the source returned. The fixture deliberately supplies unsorted dates,
    and sorting has to be on the PARSED date -- the raw column mixes NSE ISO
    with BSE day-first, so a string sort is not chronological either.
    """
    failures = []
    st.cache_data.clear()
    st.cache_resource.clear()
    app = AppTest.from_file(str(REPO / "streamlit_app" / "views" / "transactions.py"), default_timeout=90)
    app.run()
    if app.exception:
        return [f"Evidence & Drill-down raised: {app.exception[0].message.splitlines()[0][:70]}"]
    checked = 0
    for frame in app.dataframe:
        for col_name in ("canonical_transaction_date", "canonical_event_date"):
            col = frame.value.get(col_name)
            if col is None or not len(col):
                continue
            parsed = pd.to_datetime(col, format="%d %b %Y", errors="coerce")
            checked += 1
            if list(parsed) != sorted(parsed, reverse=True):
                failures.append(f"{col_name} not newest-first: {list(col)[:4]}")
    if not checked:
        failures.append("no dated tables rendered -- the ordering check asserted nothing")
    return failures


def run_page(name: str, expect_error: bool) -> str | None:
    """None when the page is fine, else a one-line description of what broke."""
    st.cache_data.clear()
    st.cache_resource.clear()
    app = AppTest.from_file(str(REPO / "streamlit_app" / "views" / f"{name}.py"), default_timeout=90)
    try:
        app.run()
        if name == "entity_tracker" and app.text_input:
            app.text_input[-1].set_value("alpha fund").run()
    except Exception as exc:  # a failure to even start the script
        return f"harness error: {type(exc).__name__}: {exc}"
    if app.exception:
        return f"uncaught exception: {app.exception[0].message.splitlines()[0][:80]}"
    if expect_error and not app.error:
        return "R2 was unreachable but the page showed no error"
    return None


def main() -> int:
    logging.disable(logging.CRITICAL)  # the pages log failures on purpose; not test output
    failures = check_dates()
    for message in failures:
        print(f"FAIL  date parsing: {message}")
    if not failures:
        print(f"ok    date parsing ({len(DATE_CASES)} real-world formats)")

    objects = fake_r2.build_objects(DATES)
    boto3.client = lambda *a, _o=objects, **kw: fake_r2.FakeS3(_o)
    order_failures = check_ordering()
    failures.extend(order_failures)
    for message in order_failures:
        print(f"FAIL  row ordering: {message}")
    if not order_failures:
        print("ok    row ordering (Evidence & Drill-down is newest-first)")

    cases = [(label, kwargs, False) for label, kwargs in SCENARIOS]
    cases.append(("R2 unreachable", dict(), True))

    for label, kwargs, expect_error in cases:
        outage = RuntimeError("simulated R2 outage") if expect_error else None
        objects = fake_r2.build_objects(DATES, **kwargs)
        boto3.client = lambda *a, _o=objects, _f=outage, **kw: fake_r2.FakeS3(_o, fail=_f)
        broken = []
        for page in PAGES:
            problem = run_page(page, expect_error)
            if problem:
                broken.append(f"{page}: {problem}")
        if broken:
            failures.extend(broken)
            print(f"FAIL  {label}")
            for line in broken:
                print(f"        {line}")
        else:
            print(f"ok    {label} ({len(PAGES)} pages)")

    print(f"\n{len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
