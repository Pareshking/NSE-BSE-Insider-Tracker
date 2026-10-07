"""Dates from NSE and BSE, read per value by shape.

NSE writes ISO (2026-08-27), month names (31-Aug-2026 17:40:12) and UTC
timestamps for IST midnight (2026-08-30T18:30:00.000Z); BSE writes DD/MM/YYYY.
One blanket `dayfirst` setting is wrong for one of them, so each value is
read by its own shape -- the same rules as streamlit_app/lib/fields.py,
which the views will drop once they read the clean tables.
"""
from __future__ import annotations

import pandas as pd

MARKET_TZ = 'Asia/Kolkata'
_ISO = r'^\s*\d{4}-\d{1,2}-\d{1,2}'
_TZ = r'(?:Z|[+-]\d{2}:?\d{2})\s*$'


def parse_dates(values) -> pd.Series:
    """Series of python `date` (or None), aligned to the input. A value
    that can't be read becomes None, never a guessed date."""
    s = values if isinstance(values, pd.Series) else pd.Series(values)
    text = s.astype('string').str.strip()
    out = pd.Series(pd.NaT, index=s.index, dtype='datetime64[ns]')
    iso = text.str.match(_ISO, na=False)
    tz = iso & text.str.contains(_TZ, regex=True, na=False)
    if tz.any():
        out.loc[tz] = (pd.to_datetime(text[tz], errors='coerce', format='ISO8601', utc=True)
                       .dt.tz_convert(MARKET_TZ).dt.tz_localize(None))
    plain = iso & ~tz
    if plain.any():
        out.loc[plain] = pd.to_datetime(text[plain].str[:10], errors='coerce', format='ISO8601')
    rest = ~iso & text.notna() & (text != '')
    if rest.any():
        out.loc[rest] = pd.to_datetime(text[rest], errors='coerce', dayfirst=True, format='mixed')
    return out.dt.date.where(out.notna(), None)
