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

import numpy as np
import pandas as pd

from .dates import parse_dates
from .history import HISTORY_SOURCES
from .missing import is_missing

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
        if df[col].dtype == object and df[col].dropna().map(lambda v: isinstance(v, (bool, np.bool_))).all() \
                and df[col].notna().any():
            df[col] = df[col].astype('boolean')  # a flag with gaps (older rows lack it) stays a flag
        elif df[col].dtype == object:
            df[col] = df[col].map(lambda v: None if is_missing(v) else str(v))
            df[col] = df[col].astype('string')
    return df


# Every raw row is archived (owner, 21 Nov 2026: nothing may exist only in raw). A row the clean tables leave out
# carries kept = false and its drop_reason; rows archived before the column existed were all kept. Columns that only
# the archive holds (the flag, its reason, and lossless copies added after the clean tables existed) are named here
# and taken off before a clean table is built, so the clean tables stay as they were.
KEPT = 'kept'
DROP_REASON = 'drop_reason'
ARCHIVE_ONLY_COLUMNS = (KEPT, DROP_REASON, 'bids_json')
# Lossless copies of the row as sent: merge keeps the archived copy when a row seen again comes without one.
KEEP_IF_MISSING = ('raw_json', 'bids_json')


def kept_mask(df: pd.DataFrame) -> pd.Series:
    """True for rows the clean tables use: kept true, or no flag (archived before 21 Nov 2026, all kept)."""
    if df is None or KEPT not in df.columns:
        return pd.Series(True, index=None if df is None else df.index, dtype=bool)
    return df[KEPT].astype('boolean').fillna(True).astype(bool)


def clean_view(df: pd.DataFrame | None) -> tuple[pd.DataFrame | None, dict]:
    """(the archive rows and columns a clean table is built from, {drop_reason: rows left out})."""
    if df is None or df.empty:
        return df, {}
    keep = kept_mask(df)
    out = {}
    if (~keep).any():
        reasons = df.loc[~keep, DROP_REASON] if DROP_REASON in df.columns else pd.Series('not kept', index=df.index[~keep])
        out = {str(k): int(v) for k, v in reasons.fillna('not kept').astype(str).value_counts().items()}
    view = df[keep].drop(columns=[c for c in ARCHIVE_ONLY_COLUMNS if c in df.columns]).reset_index(drop=True)
    return view, out


def with_kept(df: pd.DataFrame, kept, reason) -> pd.DataFrame:
    """`df` with the archive's kept flag and drop reason (scalars or per-row sequences) as its last two columns."""
    df = df.copy()
    df[KEPT] = kept
    df[DROP_REASON] = reason
    df[KEPT] = df[KEPT].astype(bool)
    df[DROP_REASON] = df[DROP_REASON].astype(object).where(~df[KEPT], None)
    return df


def backfill(archive: pd.DataFrame | None, new: pd.DataFrame | None, run_date: str, key: str = KEY,
             fill: tuple = (), add_kept: bool = False) -> tuple[pd.DataFrame | None, dict]:
    """Rows re-read from raw_v2 into an archive without changing what the clean tables read (scripts/raw_reparse.py):

    * a row already archived keeps every value and its first_seen / last_seen; only the `fill` columns are filled
      where the archive has none (a lossless copy added after the row was stored, e.g. raw_json);
    * a row not archived is added when it is kept = false (first_seen = last_seen = run_date): a row the clean
      tables leave out, which the collector used to drop;
    * a kept row that is not archived is only counted (`kept_not_archived`), never added, unless `add_kept`: adding
      it would change a clean table, which a re-read must not do on its own.

    Returns (archive, counts: added, filled, kept_not_archived)."""
    counts = {'added': 0, 'filled': 0, 'kept_not_archived': 0}
    if new is None or new.empty:
        return archive, counts
    new = _uniform(new.drop(columns=['exchange', 'category'], errors='ignore'))   # as merge stores them
    new = new.drop_duplicates(key, keep='last')
    have = set(archive[key].astype(str)) if archive is not None and not archive.empty else set()
    fresh = ~new[key].astype(str).isin(have)
    kept = kept_mask(new)
    counts['kept_not_archived'] = int((fresh & kept).sum())
    add = new[fresh & (~kept | add_kept)].assign(first_seen=run_date, last_seen=run_date)
    counts['added'] = len(add)
    if archive is None or archive.empty:
        return (_uniform(add.reset_index(drop=True)) if len(add) else archive), counts
    archive = archive.copy()
    by_key = new[~fresh].set_index(new.loc[~fresh, key].astype(str))
    for c in fill:
        if c not in by_key.columns:
            continue
        if c not in archive.columns:
            archive[c] = pd.Series(pd.NA, index=archive.index, dtype=object)
        hole = archive[c].isna()
        got = archive.loc[hole, key].astype(str).map(by_key[c])
        filled = got.notna()
        counts['filled'] += int(filled.sum())
        archive.loc[got[filled].index, c] = got[filled].astype(object)
    merged = pd.concat([archive, add], ignore_index=True) if len(add) else archive
    return _uniform(merged), counts


def merge(archive: pd.DataFrame | None, new: pd.DataFrame | None, run_date: str,
          key: str = KEY) -> tuple[pd.DataFrame, int]:
    """(merged frame, number of records not seen before). Rows seen again
    take today's values (e.g. a newly flagged cross-exchange match) but keep
    their original first_seen. `key` is the identity column (the corporate
    events collector uses its own event_id)."""
    if new is None or new.empty:
        return (archive if archive is not None else pd.DataFrame()), 0
    new = _uniform(new.drop(columns=['exchange', 'category'], errors='ignore'))
    new = new.drop_duplicates(key, keep='last').assign(first_seen=run_date, last_seen=run_date)
    if archive is None or archive.empty:
        return new.reset_index(drop=True), len(new)
    archive = _uniform(archive)
    first = archive.set_index(key)['first_seen']
    added = int((~new[key].isin(first.index)).sum())
    new['first_seen'] = new[key].map(first).fillna(run_date)
    # A lossless copy is never lost to a row seen again without it (a BSE deal from the history endpoint carries
    # raw_json, the same deal from the nightly page does not; a tender's bid book is in one of NSE's two lists).
    for c in KEEP_IF_MISSING:
        if c in archive.columns:
            prev = archive.drop_duplicates(key).set_index(key)[c]
            back = new[key].map(prev)
            new[c] = back if c not in new.columns else new[c].where(new[c].notna(), back)
    merged = pd.concat([archive[~archive[key].isin(new[key])], new], ignore_index=True)
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


def from_history(frame: pd.DataFrame) -> pd.Series:
    """Boolean mask: rows written by the historical backfill
    (scripts/nse_history_backfill.py), not by the nightly run."""
    if frame is None or 'source' not in frame:
        return pd.Series(False, index=None if frame is None else frame.index, dtype=bool)
    return frame['source'].astype('string').isin(HISTORY_SOURCES).fillna(False).astype(bool)


def possibly_withdrawn(frame: pd.DataFrame, run_date: str, window_days: int = 80) -> pd.Series:
    """Boolean mask: last seen before today although first seen recently
    enough that the source's rolling window should still include it.
    Backfilled rows are never in the nightly window, so never counted."""
    if frame is None or frame.empty or 'last_seen' not in frame:
        return pd.Series(dtype=bool)
    today = pd.Timestamp(run_date)
    first = pd.to_datetime(frame['first_seen'])
    last = pd.to_datetime(frame['last_seen'])
    return (last < today) & (first >= today - pd.Timedelta(days=window_days)) & ~from_history(frame)
