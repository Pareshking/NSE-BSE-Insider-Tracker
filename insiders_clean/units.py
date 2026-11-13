"""Percent columns in one unit (synthesis C5, 13 Nov 2026): NSE and BSE file percents (3.32), some XBRL fractions
(0.0332, multiplied by 100 at parse). Nothing is changed here: each nightly table is checked and the result counted
in the run report, so a unit slip (a fraction left as a fraction, a value past 100) is seen on Data health, not
discovered on a page."""
from __future__ import annotations

import pandas as pd

SIGNED = ('percent_equity_traded',)   # a sale is negative
FRACTION_MIN_ROWS = 50


def pct_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c.endswith('_pct') or c in SIGNED]


def check(df: pd.DataFrame) -> dict:
    """{column: {'out_of_range': n, 'looks_like_fractions': bool}} for the percent columns with a problem; {} if none.
    Out of range: below 0 (below -100 for a signed move) or above 100.5. Looks like fractions: at least 50 values,
    all within [-1, 1] and the largest above 0.5 (a whole column filed as 0.41 for 41%)."""
    out = {}
    if df is None or df.empty:
        return out
    for c in pct_columns(df):
        v = pd.to_numeric(df[c].astype(str).str.strip().replace({'': None, 'None': None, 'nan': None}), errors='coerce').dropna()
        if v.empty:
            continue
        lo = -100.5 if c in SIGNED else -0.0001
        bad = int(((v < lo) | (v > 100.5)).sum())
        # a column of small true percents (employee trusts, mostly under 1%) is not fractions: those reach well under 0.5
        frac = len(v) >= FRACTION_MIN_ROWS and bool(v.abs().le(1).all()) and float(v.abs().max()) > 0.5
        if bad or frac:
            out[c] = {'out_of_range': bad, 'looks_like_fractions': frac}
    return out
