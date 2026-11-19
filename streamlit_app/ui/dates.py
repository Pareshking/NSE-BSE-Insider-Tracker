"""One date control for every dated page (owner, 19 Nov 2026: "A date selector or a date range selector must be present
on required pages").

Two shapes:

- `range_picker`: quick presets (the latest day, 1W, 1M, 3M, 6M, 1Y, since the product start of 8 Oct 2025) and
  "Custom", which reveals a date-range input. `forward=True` is the Calendar's: the presets run from the data's date
  into the future (the next week, month, three months).
- `day_picker`: one date, for a page about a single day (Today).

Both are clamped to the data's real first and last dates and to the product window (transactions from 8 Oct 2025,
insiders_clean/pipeline.py), keep the choice per page in session_state (it outlives a visit to another page), and put it
in the page address (`?range=1m`, `?from=2026-10-01&to=2026-10-31`, `?day=2026-11-17`) so a link keeps the range. The
default choice writes nothing to the address. The functions above the Streamlit ones are plain date arithmetic, tested
in tests/test_dates.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd
import streamlit as st

# the product window (insiders_clean/pipeline.py PRODUCT_START; tests/test_dates.py checks they agree)
PRODUCT_START = date(2025, 10, 8)

# preset code -> (label, offset back from the end). The code is what the address carries.
PRESETS = {
    'day': ('Latest day', None),
    '1w': ('1W', pd.DateOffset(days=7)),
    '1m': ('1M', pd.DateOffset(months=1)),
    '3m': ('3M', pd.DateOffset(months=3)),
    '6m': ('6M', pd.DateOffset(months=6)),
    '1y': ('1Y', pd.DateOffset(years=1)),
    'all': (f'Since {PRODUCT_START.day} {PRODUCT_START:%b %Y}', None),
}
FORWARD = {   # the Calendar: from the data's date forward
    'day': ('Today', None),
    '1w': ('Next 1W', pd.DateOffset(days=7)),
    '1m': ('Next 1M', pd.DateOffset(months=1)),
    '3m': ('Next 3M', pd.DateOffset(months=3)),
}
CUSTOM = 'custom'
CUSTOM_LABEL = 'Custom'


@dataclass(frozen=True)
class Range:
    start: date
    end: date
    preset: str          # a preset code, or CUSTOM

    @property
    def days(self) -> int:
        """Days in the range, both ends counted."""
        return (self.end - self.start).days + 1

    @property
    def start_ts(self) -> pd.Timestamp:
        return pd.Timestamp(self.start)

    @property
    def end_ts(self) -> pd.Timestamp:
        return pd.Timestamp(self.end)

    def mask(self, values) -> pd.Series:
        """True where a date (or a timestamp, any time of the day) falls inside the range, both ends included."""
        s = pd.Series(values) if not isinstance(values, pd.Series) else values
        try:
            d = pd.to_datetime(s, errors='coerce', format='mixed')
        except (TypeError, ValueError):
            d = pd.to_datetime(s, errors='coerce', format='mixed', utc=True)
        if getattr(d.dt, 'tz', None) is not None:
            d = d.dt.tz_convert('Asia/Kolkata').dt.tz_localize(None)
        d = d.dt.normalize()
        return (d >= self.start_ts) & (d <= self.end_ts)


def _d(v) -> date | None:
    t = pd.to_datetime(v, errors='coerce')
    if t is None or pd.isna(t):
        return None
    if t.tzinfo is not None:
        t = t.tz_convert('Asia/Kolkata').tz_localize(None)
    return t.date()


def _dates(x) -> pd.Series:
    """Dates of a column, a list or one value, IST, as naive days; unreadable ones dropped."""
    if x is None:
        return pd.Series(dtype='datetime64[ns]')
    s = pd.Series([x]) if isinstance(x, (str, date, pd.Timestamp)) else pd.Series(x)
    try:
        s = pd.to_datetime(s, errors='coerce', format='mixed')
    except (TypeError, ValueError):   # aware and naive mixed: read as UTC
        s = pd.to_datetime(s, errors='coerce', format='mixed', utc=True)
    if getattr(s.dt, 'tz', None) is not None:
        s = s.dt.tz_convert('Asia/Kolkata').dt.tz_localize(None)
    return s.dropna().dt.normalize()


def bounds(*dates, hi=None, forward: bool = False) -> tuple[date, date]:
    """(first, last) date a picker may offer, from the data's own dates over every series given.

    Backward (a page about the past): from the first date held, never before the product start, to the last date
    held, never after `hi` (the as-of date). Forward (the Calendar): from `hi` (today in the data) to the last date
    held. With no dates at all, both ends are `hi` (or the product start)."""
    s = pd.concat([_dates(x) for x in dates]) if dates else pd.Series(dtype='datetime64[ns]')
    first = s.min().date() if len(s) else None
    last = s.max().date() if len(s) else None
    h = _d(hi)
    if forward:
        lo = h or first or PRODUCT_START
        return lo, max(lo, last) if last else lo
    lo = max(PRODUCT_START, first) if first else PRODUCT_START
    top = min(h, last) if h and last else (h or last or lo)
    if top < lo:             # nothing held inside the window: the window's own end
        top = max(lo, h) if h else lo
    return lo, top


def clamp(start, end, lo, hi) -> tuple[date, date]:
    """start and end inside [lo, hi], in order; a range wholly outside lands on the nearest end."""
    s, e = _d(start) or lo, _d(end) or hi
    if s > e:
        s, e = e, s
    s, e = min(max(s, lo), hi), min(max(e, lo), hi)
    return s, e


def preset_range(code: str, lo, hi, forward: bool = False) -> tuple[date, date]:
    """The (start, end) of a preset against the data's bounds. Backward: the window ending on the last day
    (1W = the 7 days to it, 1M = from the same day a month before, plus one); "all" = from the first day.
    Forward: the window starting on the first day (today in the data)."""
    lo, hi = _d(lo), _d(hi)
    table = FORWARD if forward else PRESETS
    if code not in table:
        raise KeyError(code)
    off = table[code][1]
    if forward:
        if off is None:
            return lo, lo
        end = (pd.Timestamp(lo) + off - pd.Timedelta(days=1)).date()
        return clamp(lo, end, lo, hi)
    if code == 'day':
        return hi, hi
    if code == 'all':
        return lo, hi
    start = (pd.Timestamp(hi) - off + pd.Timedelta(days=1)).date()
    return clamp(start, hi, lo, hi)


def to_query(r: Range | None, default: str | None) -> dict:
    """The address keys for a choice: {} for the default, {'range': code} for another preset, {'from', 'to'} for Custom."""
    if r is None or r.preset == default:
        return {}
    if r.preset == CUSTOM:
        return {'from': r.start.isoformat(), 'to': r.end.isoformat()}
    return {'range': r.preset}


def from_query(q: dict, lo, hi, forward: bool = False) -> Range | None:
    """The choice an address carries, clamped to the bounds; None when it carries none (or nothing readable)."""
    table = FORWARD if forward else PRESETS
    code = str(q.get('range') or '').lower()
    if code in table:
        return Range(*preset_range(code, lo, hi, forward), code)
    a, b = _d(q.get('from')), _d(q.get('to'))
    if a or b:
        return Range(*clamp(a or lo, b or hi, _d(lo), _d(hi)), CUSTOM)
    return None


def day_from_query(q: dict, lo, hi) -> date | None:
    d = _d(q.get('day'))
    return None if d is None else clamp(d, d, _d(lo), _d(hi))[0]


def fmt(d) -> str:
    """'01 Oct 2026', as kit.day."""
    return pd.Timestamp(d).strftime('%d %b %Y')


def describe(r: Range) -> str:
    """'01 Oct 2026 to 31 Oct 2026', or one date when the range is one day: the words a page shows for its range."""
    if r.start == r.end:
        return fmt(r.start)
    return f'{fmt(r.start)} to {fmt(r.end)}'


def label(r: Range, forward: bool = False) -> str:
    """The range with its preset in brackets: '20 Oct 2026 to 19 Nov 2026 (1M)'."""
    table = FORWARD if forward else PRESETS
    name = table[r.preset][0] if r.preset in table else CUSTOM_LABEL
    return f'{describe(r)} ({name.lower() if r.preset == "day" else name})'


# ---- Streamlit -------------------------------------------------------------------------------------------------------

_KEYS = ('range', 'from', 'to', 'day')


def _write_query(key: str, q: dict) -> None:
    """Our keys of the address set to `q` (others, like ?symbol=, are left alone); written only when they change."""
    have = {k: st.query_params.get(k) for k in _KEYS if k in st.query_params}
    if have != q:
        for k in _KEYS:
            if k in st.query_params and k not in q:
                del st.query_params[k]
        for k, v in q.items():
            st.query_params[k] = v
    st.session_state[f'_dr_q_{key}'] = q


def _url_choice(key: str) -> dict | None:
    """Our keys of the address when they are new to this page (a link opened, back and forward in the browser);
    None when they are what this page wrote last, or absent (a menu click clears the address)."""
    q = {k: st.query_params.get(k) for k in _KEYS if k in st.query_params}
    if not q or q == st.session_state.get(f'_dr_q_{key}'):
        return None
    return q


def range_picker(key: str, lo, hi, default: str = '1w', forward: bool = False, presets: tuple[str, ...] | None = None,
                 caption: bool = False) -> Range:
    """The presets and Custom, in one row; returns the Range. `lo`/`hi` from `bounds`. The choice lives in
    session_state under `_dr_<key>` and in the address."""
    lo, hi = _d(lo), _d(hi)
    table = FORWARD if forward else PRESETS
    codes = [c for c in (presets or tuple(table)) if c in table]
    if default not in codes:
        default = codes[0]
    opts = codes + [CUSTOM]
    pk, rk, sk = f'{key}_preset', f'{key}_range', f'_dr_{key}'
    names = {**{c: table[c][0] for c in codes}, CUSTOM: CUSTOM_LABEL}

    url = _url_choice(key)
    picked = from_query(url, lo, hi, forward) if url else None
    if picked is not None and picked.preset not in opts:
        picked = None
    if picked is not None:                     # the address wins: a link or the browser's back button
        st.session_state[pk] = picked.preset
        if picked.preset == CUSTOM:
            st.session_state[rk] = (picked.start, picked.end)
    elif st.session_state.get(pk) not in opts:  # first visit, or back from another page: the page's own last choice
        saved = st.session_state.get(sk)
        st.session_state[pk] = saved.preset if isinstance(saved, Range) and saved.preset in opts else default
    if st.session_state[pk] == CUSTOM:
        cur = st.session_state.get(rk)
        saved = st.session_state.get(sk)
        if not (isinstance(cur, (tuple, list)) and cur):
            cur = (saved.start, saved.end) if isinstance(saved, Range) else preset_range(default, lo, hi, forward)
        a = cur[0]
        b = cur[1] if len(cur) > 1 else max(a, saved.end if isinstance(saved, Range) else a)
        st.session_state[rk] = clamp(a, b, lo, hi)   # inside the bounds before the input is drawn

    with st.container(key=f'dr_{key}', horizontal=True, vertical_alignment='center', gap='small'):
        st.segmented_control('Period', opts, format_func=names.get, key=pk, required=True, label_visibility='collapsed')
        code = st.session_state.get(pk) or default
        if code == CUSTOM:
            v = st.date_input('Dates', value=tuple(st.session_state[rk]), min_value=lo, max_value=hi, key=rk, format='DD/MM/YYYY', label_visibility='collapsed',
                              width=230, help=f'Any range from {fmt(lo)} to {fmt(hi)}: the data held for this page')
            v = tuple(v) if isinstance(v, (tuple, list)) else (v,)
            a = v[0] if v else lo
            b = v[1] if len(v) > 1 else a          # mid-pick: one date so far
            r = Range(*clamp(a, b, lo, hi), CUSTOM)
        else:
            r = Range(*preset_range(code, lo, hi, forward), code)
    st.session_state[sk] = r
    _write_query(key, to_query(r, default))
    if caption:
        st.caption(f'Showing {label(r, forward)}.')
    return r


def day_picker(key: str, lo, hi, caption: str | None = None) -> date:
    """One date (a page about a single day). The latest day is the default and writes nothing to the address, so the
    page follows the data as it grows; another day is kept per page and in the address (`?day=`)."""
    lo, hi = _d(lo), _d(hi)
    dk, sk = f'{key}_day', f'_dr_{key}'
    url = _url_choice(key)
    picked = day_from_query(url, lo, hi) if url else None
    if picked is not None:
        st.session_state[dk] = picked
    elif not isinstance(st.session_state.get(dk), date):
        saved = st.session_state.get(sk)
        st.session_state[dk] = saved if isinstance(saved, date) else hi
    st.session_state[dk] = clamp(st.session_state[dk], st.session_state[dk], lo, hi)[0]
    with st.container(key=f'dr_{key}', horizontal=True, vertical_alignment='center', gap='small'):
        d = st.date_input('Day', value=st.session_state[dk], min_value=lo, max_value=hi, key=dk, format='DD/MM/YYYY', label_visibility='collapsed',
                          width=150, help=f'Any day from {fmt(lo)} to {fmt(hi)}; the latest is {fmt(hi)}')
        d = d if isinstance(d, date) else hi
        if caption:
            st.caption(caption)
    st.session_state[sk] = d
    _write_query(key, {} if d == hi else {'day': d.isoformat()})
    return d
