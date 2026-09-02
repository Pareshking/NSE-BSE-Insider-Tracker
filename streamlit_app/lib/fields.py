"""Safe access and parsing for the canonical_* fields.

Two problems this module exists to solve, both found in live data:

1. **Dates arrive in more than one convention.** NSE insider/acquisition
   rows carry ISO (`2026-08-28`, and `2026-06-02T18:30:00.000Z` for the
   bulk-deal order timestamps); BSE bulk/block rows carry Indian
   DD/MM/YYYY (`31/08/2026`). A single blanket `dayfirst` setting is wrong
   for one of them either way -- `dayfirst=True` reads ISO `2026-09-01` as
   9 January 2026, and `dayfirst=False` reads BSE `03/04/2026` as 4 March
   instead of 3 April. `parse_dates()` picks per value by shape instead,
   mirroring the format list `scripts/r2_writer.py::parse_loose_date`
   already applies on the ingest side (ISO first, then day-first forms).

2. **A canonical column can be absent** for an exchange/category that
   didn't produce it. `df.get(col, pd.Series(dtype=object))` -- the old
   idiom here -- returns a series with an *empty* index, and pandas raises
   `IndexingError: Unalignable boolean Series` the moment it's used as a
   row mask. `text_col`/`num_col` return a column aligned to `df.index`
   whether or not the column exists, so a missing field narrows a result
   instead of crashing the page.
"""
from __future__ import annotations

import pandas as pd

# Leading ISO date (`2026-08-28`, `2026-06-02T18:30:00.000Z`) -- unambiguous,
# must never be read day-first.
_ISO_PREFIX = r"^\s*\d{4}-\d{1,2}-\d{1,2}"
# ...ending in an explicit UTC offset. NSE stamps IST midnight as
# `2026-08-30T18:30:00.000Z`; the same row's BD_DT_DATE reads `31-AUG-2026`,
# so these have to be read on the market's clock to land on the same day.
_ISO_TZ_SUFFIX = r"(?:Z|[+-]\d{2}:?\d{2})\s*$"
MARKET_TZ = "Asia/Kolkata"


def parse_dates(values) -> pd.Series:
    """Parse a column of canonical dates to datetime64, per-value by shape.

    Unparseable values become NaT (never a guessed date). Returns a Series
    aligned to the input's index so it can be used directly as a filter.
    """
    series = values if isinstance(values, pd.Series) else pd.Series(values)
    if pd.api.types.is_datetime64_any_dtype(series):
        return series
    text = series.astype(str).str.strip()
    out = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")

    iso = text.str.match(_ISO_PREFIX, na=False)
    offset = iso & text.str.contains(_ISO_TZ_SUFFIX, regex=True, na=False)
    iso_naive = iso & ~offset
    if offset.any():
        # Same instant, read on the exchange's clock, then made naive again
        # so it compares against the naive dates in the rest of the column.
        out.loc[offset] = (
            pd.to_datetime(text[offset], errors="coerce", format="ISO8601", utc=True)
            .dt.tz_convert(MARKET_TZ)
            .dt.tz_localize(None)
        )
    if iso_naive.any():
        # Parsed as written -- no timezone shift, or a naive same-day
        # timestamp like `2026-08-31 17:40:12` would roll to the next day.
        out.loc[iso_naive] = pd.to_datetime(text[iso_naive], errors="coerce", format="ISO8601")
    rest = ~iso
    if rest.any():
        # dayfirst is right for the DD/MM/YYYY forms and a no-op on the
        # month-name ones; nothing ISO-shaped reaches this branch.
        # format="mixed" parses each value on its own: without it pandas
        # infers ONE format from the first element and coerces every row
        # that doesn't match to NaT -- which is exactly what happens to a
        # concatenated NSE (`31-AUG-2026`) + BSE (`31/08/2026`) column.
        out.loc[rest] = pd.to_datetime(text[rest], errors="coerce", dayfirst=True, format="mixed")
    return out


def parse_date(value):
    """Single-value `parse_dates`. Returns a Timestamp, or NaT."""
    if value is None:
        return pd.NaT
    return parse_dates(pd.Series([value])).iloc[0]


def text_col(df: pd.DataFrame, name: str, *, upper: bool = False) -> pd.Series:
    """`df[name]` as strings, aligned to `df.index`.

    Returns an all-empty (never all-"nan") column of the right length when
    the field is missing, so `.str.contains(...)` yields an all-False mask
    rather than an unalignable one.
    """
    if name not in df.columns:
        return pd.Series("", index=df.index, dtype=object)
    col = df[name].fillna("").astype(str)
    return col.str.upper() if upper else col


def num_col(df: pd.DataFrame, name: str, *, fill: float | None = 0.0) -> pd.Series:
    """`df[name]` as numbers, aligned to `df.index`; NaN (or `fill`) where
    the value isn't numeric, and an all-`fill` column when it's missing."""
    if name not in df.columns:
        return pd.Series(float("nan") if fill is None else fill, index=df.index, dtype="float64")
    col = pd.to_numeric(df[name], errors="coerce")
    return col.fillna(fill) if fill is not None else col


def as_float(value, default: float = 0.0) -> float:
    """Scalar coercion that actually replaces a missing value.

    `pd.to_numeric(x, errors="coerce") or 0` does NOT: NaN is truthy, so the
    NaN survives and renders as "₹nan" downstream.
    """
    if isinstance(value, str):
        value = value.replace(",", "").strip()   # same as scripts/r2_writer.py::_num
    number = pd.to_numeric(value, errors="coerce")
    if number is None or pd.isna(number):
        return default
    return float(number)
