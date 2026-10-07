"""People and funds: one stable ID per name, however it was typed.

The same fund turns up as "HRTI PRIVATE LIMITED", "Hrti Pvt. Ltd." and
"HRTI PVT LTD". `entity_key` reduces all of these to one key, which is also
the ID in links (/entity?id=...). Display keeps the most common spelling
seen, put into title case when it was all capitals.

Deliberately conservative: only spelling and corporate-suffix variants are
merged. Two names that differ by a word stay two entities -- a wrong merge
puts one fund's trades on another's page, which is worse than a split.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from .missing import is_missing
from .securities import _title_word

# Variant -> one spelling, applied to the upper-cased, punctuation-free name.
_EQUIVALENTS = [
    (r'\bPVT\b', 'PRIVATE'), (r'\bPVTLTD\b', 'PRIVATE LIMITED'), (r'\bLTD\b', 'LIMITED'),
    (r'\bLIMTED\b', 'LIMITED'), (r'\bCO\b', 'COMPANY'), (r'\bCORP\b', 'CORPORATION'),
    (r'\bINTL\b', 'INTERNATIONAL'), (r'\bMGMT\b', 'MANAGEMENT'), (r'\bSVCS\b', 'SERVICES'),
    (r'\bLLP\b', 'LLP'), (r'\bHUF\b', 'HUF'), (r'&', ' AND '),
]


def entity_key(name) -> str | None:
    if is_missing(name):
        return None
    s = str(name).upper().replace('&', ' & ')
    s = re.sub(r"[.,'()\"/\\-]", ' ', s)
    for pat, rep in _EQUIVALENTS:
        s = re.sub(pat, rep, s)
    s = re.sub(r'[^A-Z0-9 ]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    if not s:
        return None
    return s.lower().replace(' ', '-')


def entity_display(name) -> str | None:
    if is_missing(name):
        return None
    s = re.sub(r'\s+', ' ', str(name)).strip()
    if s.upper() == s and any(ch.isalpha() for ch in s):
        s = ' '.join(_title_word(w) for w in s.split(' '))
    return s or None


def most_common(frame: pd.DataFrame, by: list[str], col: str) -> pd.Series:
    """Most frequent `col` per `by` group -- the same answer as
    groupby(by)[col].agg(lambda s: s.value_counts().index[0]), rows with a
    missing key or value left out, without a Python call per group. Groups
    whose top count is tied still go through value_counts, so a tie resolves
    exactly as it did before."""
    f = frame[by + [col]].dropna()
    if f.empty:
        return pd.Series(dtype=object)
    counts = f.groupby(by + [col], sort=False).size().rename('_n').reset_index()
    best = counts[counts['_n'] == counts.groupby(by, sort=False)['_n'].transform('max')]
    tied = best.duplicated(by, keep=False)
    out = best[~tied].set_index(by)[col]
    if tied.any():
        tied_keys = pd.MultiIndex.from_frame(best.loc[tied, by].drop_duplicates())
        sub = f[pd.MultiIndex.from_frame(f[by]).isin(tied_keys)]
        out = pd.concat([out, sub.groupby(by)[col].agg(lambda s: s.value_counts().index[0])])
    return out


def per_group(codes, values, func) -> list:
    """[func(values of group 0), func(values of group 1), ...] for integer
    group codes 0..n-1 (e.g. GroupBy.ngroup()), each group's values in row
    order. One sort instead of a pandas Series per group."""
    codes = np.asarray(codes)
    if len(codes) == 0:
        return []
    order = np.argsort(codes, kind='stable')
    vals = np.asarray(values, dtype=object)[order]
    bounds = np.flatnonzero(np.diff(codes[order])) + 1
    return [func(chunk) for chunk in np.split(vals, bounds)]


def add_entity_columns(df: pd.DataFrame, name_col: str, prefix: str = 'entity') -> pd.DataFrame:
    """Adds {prefix}_id and {prefix}_name. The name shown for an ID is the
    spelling that occurs most often for it in this frame."""
    df = df.copy()
    # Each distinct spelling is keyed once, not once per row.
    codes, uniques = pd.factorize(df[name_col])
    ids = np.array([entity_key(u) for u in uniques] + [entity_key(None)], dtype=object)
    shown = np.array([entity_display(u) for u in uniques] + [entity_display(None)], dtype=object)
    df[f'{prefix}_id'] = pd.Series(ids[codes], index=df.index, dtype=object)
    disp = pd.Series(shown[codes], index=df.index, dtype=object)
    common = most_common(pd.DataFrame({'id': df[f'{prefix}_id'], 'name': disp}), ['id'], 'name')
    df[f'{prefix}_name'] = df[f'{prefix}_id'].map(common)
    return df
