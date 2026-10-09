"""Nightly bulk/block deals via NSE's CSV export (no row cap).

The JSON form of /api/historicalOR/bulk-block-short-deals returns at most 70
rows per call, sorted oldest first, so a day with more deals silently lost its
tail. The same endpoint with csv=true has no such cap (the history backfill
fetches whole calendar years with it). Rows are mapped to the same BD_* field
names the JSON form used, so everything downstream is unchanged, and tagged
`source` = nse_nightly_deals_csv. That tag is deliberately NOT one of
HISTORY_SOURCES: it is a nightly row (it moves `last_merged`).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from insiders_clean.history import deal_rows  # noqa: E402

CSV_SOURCE = 'nse_nightly_deals_csv'


def is_csv(text) -> bool:
    head = (text or '').lstrip('﻿').lstrip()[:200]
    return head.startswith(('"Date', 'Date')) and 'Symbol' in head


def rows_from_csv(text: str) -> list[dict]:
    rows = deal_rows(text.encode('utf-8'))
    for r in rows:
        r['source'] = CSV_SOURCE
    return rows
