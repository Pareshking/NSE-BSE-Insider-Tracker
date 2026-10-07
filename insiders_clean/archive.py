"""The permanent store of everything collected: each source record once.

The nightly writer stores a full 90-day window under every run date, so one
filing is saved up to ~60 times (raw JSON and Parquet each). The archive
keeps each canonical row exactly once, keyed by canonical_event_id (a hash
of the native record, so it is stable across runs), with the first and last
run dates it was seen on.

The clean tables are rebuilt from the whole archive every night. That gives
three things the daily snapshots can't:
* history beyond the 90-day window, growing every day;
* an improved cleaning rule re-applies to all past data on the next run;
* the dated snapshots under raw/ and canonical/ become disposable once the
  archive has absorbed them (scripts/r2_retention.py).

A record that stops appearing at the source while it is still inside the
source's window may have been withdrawn; `last_seen` lets the cleaning
report count those rather than silently keeping or dropping them.
"""
from __future__ import annotations

import pandas as pd

KEY = 'canonical_event_id'


def _uniform(df: pd.DataFrame) -> pd.DataFrame:
    """Parquet needs one type per column. Native fields arrive as int on one
    day and '51000.0' on another, so object columns are stored as text;
    canonical numeric columns keep their numeric type."""
    df = df.copy()
    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].map(lambda v: None if v is None or (isinstance(v, float) and pd.isna(v)) else str(v))
            df[col] = df[col].astype('string')
    return df


def merge(archive: pd.DataFrame | None, new: pd.DataFrame | None, run_date: str) -> tuple[pd.DataFrame, int]:
    """(merged archive, number of records not seen before). Rows seen again
    take today's values (e.g. a newly flagged cross-exchange match) but keep
    their original first_seen."""
    if new is None or new.empty:
        return (archive if archive is not None else pd.DataFrame()), 0
    new = _uniform(new.drop(columns=['exchange', 'category'], errors='ignore'))
    new = new.drop_duplicates(KEY, keep='last').assign(first_seen=run_date, last_seen=run_date)
    if archive is None or archive.empty:
        return new.reset_index(drop=True), len(new)
    archive = _uniform(archive)
    first = archive.set_index(KEY)['first_seen']
    added = int((~new[KEY].isin(first.index)).sum())
    new['first_seen'] = new[KEY].map(first).fillna(run_date)
    merged = pd.concat([archive[~archive[KEY].isin(new[KEY])], new], ignore_index=True)
    return _uniform(merged), added


def possibly_withdrawn(archive: pd.DataFrame, run_date: str, window_days: int = 80) -> pd.Series:
    """Boolean mask: last seen before today although first seen recently
    enough that the source's rolling window should still include it."""
    if archive is None or archive.empty or 'last_seen' not in archive:
        return pd.Series(dtype=bool)
    today = pd.Timestamp(run_date)
    first = pd.to_datetime(archive['first_seen'])
    last = pd.to_datetime(archive['last_seen'])
    return (last < today) & (first >= today - pd.Timedelta(days=window_days))
