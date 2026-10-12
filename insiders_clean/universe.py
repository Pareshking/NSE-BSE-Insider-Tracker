"""The study universe: companies with a market cap of Rs 100 Cr or more
(owner, 12 Oct 2026: "stocks I am never going to invest in or study" are the
smaller ones, about 30% of what the exchanges list).

Collection and raw stay complete (rule 5), so the cutoff can change without a
backfill. The clean step writes clean/current/universe.parquet, one row per
ISIN with its latest market cap (NSE's when listed there, else BSE's) and
`in_universe`; the site keeps only those rows in every table it reads, and the
track record judges each event on its own day's market cap (track.py), so a
company that grew or shrank since does not change the past.
"""
from __future__ import annotations

import pandas as pd

MIN_MARKET_CAP = 100e7   # Rs 100 Cr
COLUMNS = ['isin', 'company', 'nse_symbol', 'bse_code', 'market_cap', 'in_universe', 'why']


def table(securities: pd.DataFrame) -> pd.DataFrame:
    """securities (one row per ISIN, with market_cap) -> the universe table."""
    if securities is None or securities.empty:
        return pd.DataFrame(columns=COLUMNS)
    s = securities.drop_duplicates('isin').copy()
    if 'company' not in s and 'display_name' in s:
        s['company'] = s['display_name']
    for c in COLUMNS:
        if c not in s:
            s[c] = None
    mcap = pd.to_numeric(s['market_cap'], errors='coerce')
    s['market_cap'] = mcap
    s['in_universe'] = mcap.ge(MIN_MARKET_CAP).fillna(False).astype(bool)
    s['why'] = ['no market cap' if pd.isna(m) else '' if m >= MIN_MARKET_CAP else 'under Rs 100 Cr' for m in mcap]
    return s[COLUMNS].reset_index(drop=True)


def report(u: pd.DataFrame) -> dict:
    return {'min_market_cap': MIN_MARKET_CAP, 'isins': int(len(u)), 'in_universe': int(u['in_universe'].sum()) if len(u) else 0,
            'under_cutoff': int((u['why'] == 'under Rs 100 Cr').sum()) if len(u) else 0,
            'no_market_cap': int((u['why'] == 'no market cap').sum()) if len(u) else 0}
