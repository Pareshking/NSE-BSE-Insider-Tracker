"""One test for 'no value', used everywhere.

Rows that pass through the archive come back with pandas' <NA> for a missing
text value, not None or NaN. Code that only checked `is None` or
`isinstance(v, float)` treated <NA> as the text '<NA>' (classing a missing
mode as 'unrecognised' and merging every nameless person into one), or
crashed asking whether <NA> is true (07 Oct 2026, first R2 run)."""
from __future__ import annotations

import pandas as pd

NA_TEXT = '<NA>'


def is_missing(v) -> bool:
    if v is None or v is pd.NA:
        return True
    if isinstance(v, str):
        return v == NA_TEXT
    try:
        return bool(pd.api.types.is_scalar(v) and pd.isna(v))
    except (TypeError, ValueError):
        return False


def present(v) -> bool:
    """A usable value: not missing and not blank text."""
    return not is_missing(v) and not (isinstance(v, str) and not v.strip())


def normalise(df: pd.DataFrame) -> pd.DataFrame:
    """Text columns back to plain objects with None for missing, including any
    literal '<NA>' an earlier run stored."""
    if df is None or df.empty:
        return df
    df = df.copy()
    for col in df.columns:
        if pd.api.types.is_string_dtype(df[col]) or df[col].dtype == object:
            s = df[col].astype(object)
            df[col] = s.where(~s.map(is_missing), None)
    return df


def as_flag(series):
    """A boolean flag column read back from the archive: real booleans, or
    the text 'True'/'False' (the archive stores mixed columns as text), or
    missing. Only an explicit true counts; text 'False' must never be truthy."""
    import pandas as pd
    def one(v):
        if isinstance(v, str):
            return v.strip().lower() in ('true', '1', 'yes')
        if v is None or v is pd.NA:
            return False
        try:
            if pd.isna(v):
                return False
        except (TypeError, ValueError):
            pass
        return bool(v)
    return series.map(one).astype(bool)
