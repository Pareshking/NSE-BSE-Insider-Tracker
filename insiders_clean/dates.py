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
# Day-first shapes the exchanges actually write ('04-MAR-2024',
# '07-Mar-2016 18:50', '27/08/2026'). Tried before the general parser,
# which reads each value with dateutil: same dates, a fraction of the time
# on a full history (~650k rows).
_KNOWN_DAY_FIRST = ('%d-%b-%Y', '%d-%b-%Y %H:%M', '%d-%b-%Y %H:%M:%S', '%d/%m/%Y', '%d-%m-%Y')


def to_datetime_day_first(text: pd.Series) -> pd.Series:
    """pd.to_datetime(text, errors='coerce', dayfirst=True, format='mixed'),
    with the known shapes parsed by format first."""
    text = text.astype('string')
    out = pd.Series(pd.NaT, index=text.index, dtype='datetime64[ns]')
    todo = text.notna().to_numpy(dtype=bool)
    for fmt in _KNOWN_DAY_FIRST:
        if not todo.any():
            return out
        parsed = pd.to_datetime(text[todo], format=fmt, errors='coerce')
        hit = parsed.notna().to_numpy(dtype=bool)
        if hit.any():
            pos = todo.nonzero()[0][hit]
            out.iloc[pos] = parsed.to_numpy()[hit]
            todo[pos] = False
    if not todo.any():
        return out
    rest = pd.to_datetime(text[todo], errors='coerce', dayfirst=True, format='mixed')
    if rest.dtype != out.dtype:  # tz-aware or another unit: let pandas read it all, as before
        return pd.to_datetime(text, errors='coerce', dayfirst=True, format='mixed')
    out.iloc[todo.nonzero()[0]] = rest.to_numpy()
    return out


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
        out.loc[rest] = to_datetime_day_first(text[rest])
    return out.dt.date.where(out.notna(), None)
