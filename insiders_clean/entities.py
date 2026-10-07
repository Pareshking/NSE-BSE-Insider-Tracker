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

import pandas as pd

from .securities import _title_word

# Variant -> one spelling, applied to the upper-cased, punctuation-free name.
_EQUIVALENTS = [
    (r'\bPVT\b', 'PRIVATE'), (r'\bPVTLTD\b', 'PRIVATE LIMITED'), (r'\bLTD\b', 'LIMITED'),
    (r'\bLIMTED\b', 'LIMITED'), (r'\bCO\b', 'COMPANY'), (r'\bCORP\b', 'CORPORATION'),
    (r'\bINTL\b', 'INTERNATIONAL'), (r'\bMGMT\b', 'MANAGEMENT'), (r'\bSVCS\b', 'SERVICES'),
    (r'\bLLP\b', 'LLP'), (r'\bHUF\b', 'HUF'), (r'&', ' AND '),
]


def entity_key(name) -> str | None:
    if name is None or (isinstance(name, float) and pd.isna(name)):
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
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return None
    s = re.sub(r'\s+', ' ', str(name)).strip()
    if s.upper() == s and any(ch.isalpha() for ch in s):
        s = ' '.join(_title_word(w) for w in s.split(' '))
    return s or None


def add_entity_columns(df: pd.DataFrame, name_col: str, prefix: str = 'entity') -> pd.DataFrame:
    """Adds {prefix}_id and {prefix}_name. The name shown for an ID is the
    spelling that occurs most often for it in this frame."""
    df = df.copy()
    df[f'{prefix}_id'] = df[name_col].map(entity_key)
    disp = df[name_col].map(entity_display)
    most_common = (pd.DataFrame({'id': df[f'{prefix}_id'], 'name': disp})
                   .dropna().groupby('id')['name'].agg(lambda s: s.value_counts().index[0]))
    df[f'{prefix}_name'] = df[f'{prefix}_id'].map(most_common)
    return df
