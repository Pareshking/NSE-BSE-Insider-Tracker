"""The permanent store of everything collected: each source record once.

The nightly writer stores a full 90-day window under every run date, so one
filing is saved up to ~60 times (raw JSON and Parquet each). The archive
keeps each canonical row exactly once, keyed by canonical_event_id (a hash
of the native record, so it is stable across runs), with the first and last
run dates it was seen on.

Layout: archive/canonical/{exchange}/{category}/year=YYYY/quarter=Q.parquet,
partitioned by the record's own date (broadcast date for insider filings,
deal date for deals), plus _state.json. A record's date never changes, so a
past quarter is written once and then only read: a night's merge rewrites
the quarters its new records fall in, which is almost always just the
current one. Rows without a readable date go to year=unknown.

The clean tables are rebuilt from the whole archive every night. That gives
three things the daily snapshots can't:
* history beyond the 90-day window (and the backfill, back to 2015 for NSE
  insider filings);
* an improved cleaning rule re-applies to all past data on the next run;
* the dated snapshots under raw/ and canonical/ become disposable once the
  archive has absorbed them (scripts/r2_retention.py).
"""
from __future__ import annotations

import pandas as pd

from .dates import parse_dates

KEY = 'canonical_event_id'
# Column holding a record's own date, per category, in order of preference.
DATE_COLUMNS = {
    'insider_trading': ('canonical_broadcast_date', 'canonical_transaction_date_to', 'canonical_transaction_date'),
    'bulk_deals': ('canonical_event_date',),
    'block_deals': ('canonical_event_date',),
    'rights_issue': ('canonical_event_date',),
    'preferential_issue': ('canonical_event_date',),
}
UNKNOWN = 'year=unknown'


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
    """(merged frame, number of records not seen before). Rows seen again
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


def partition_of(day) -> str:
    if day is None or pd.isna(day):
        return UNKNOWN
    return f'year={day.year}/quarter={(day.month - 1) // 3 + 1}'


def partitions(df: pd.DataFrame, category: str) -> pd.Series:
    """Partition name for every row, from the record's own date."""
    day = pd.Series([None] * len(df), index=df.index, dtype=object)
    for col in DATE_COLUMNS[category]:
        if col in df.columns:
            parsed = parse_dates(df[col])
            day = day.where(day.notna(), parsed)
    return day.map(partition_of)


def merge_partitioned(load, new: pd.DataFrame | None, run_date: str, category: str):
    """Merge `new` into the partitions it touches. `load(partition)` returns
    the stored frame or None. Returns ({partition: merged frame}, added)."""
    if new is None or new.empty:
        return {}, 0
    parts = partitions(new, category)
    out, added = {}, 0
    for part, rows in new.groupby(parts, sort=True):
        merged, n = merge(load(part), rows, run_date)
        out[part] = merged
        added += n
    return out, added


def possibly_withdrawn(frame: pd.DataFrame, run_date: str, window_days: int = 80) -> pd.Series:
    """Boolean mask: last seen before today although first seen recently
    enough that the source's rolling window should still include it."""
    if frame is None or frame.empty or 'last_seen' not in frame:
        return pd.Series(dtype=bool)
    today = pd.Timestamp(run_date)
    first = pd.to_datetime(frame['first_seen'])
    last = pd.to_datetime(frame['last_seen'])
    return (last < today) & (first >= today - pd.Timedelta(days=window_days))
