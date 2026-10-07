"""NSE trading sessions, for SEBI PIT Regulation 7(2) disclosure deadlines.

Reg 7(2)(a): the insider tells the company within two trading days of the
trade. Reg 7(2)(b): the company tells the exchange within two trading days
of receiving that disclosure. Counting calendar days would flag every
Thursday or Friday trade as late, so lateness is counted in sessions.

How the calendar stays right in 2027 and after, with no hand-kept file:

* Lateness is only ever asked about dates that have already happened, so
  the calendar needs to know which past days NSE traded -- not future
  holidays. Every night, scripts/update_calendar.py asks NSE's archive
  whether a bhavcopy exists for each day since the last confirmed one. A
  bhavcopy exists exactly when NSE traded (checked 07 Oct 2026: 05 Oct 200;
  02 Oct, 14 Sep and a Saturday 404; the 2025 Muhurat day and the 2026
  Budget Sunday 200).
* NSE's holiday list for the current year (fetched the same night, kept per
  year) tells special sessions apart: a day that traded but is on the
  holiday list (Diwali Muhurat, marked with *) or falls on a weekend
  (Budget day) does not count as a trading day for deadlines. Counting it
  would make a filing look later than it was, so leaving it out can only
  under-flag, never falsely flag.
* The calendar carries `confirmed_through`. A question that reaches past
  it gets None, never an assumed answer. If a night's check fails, the
  date simply isn't confirmed, and the next run picks it up.

The seed (reference_data/nse_sessions.csv, 30 Sep 2024 to 01 Oct 2026) is the
set of days NSE traded per the Paresh project's NSE close history.
"""
from __future__ import annotations

import bisect
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

SEED_PATH = Path(__file__).resolve().parent.parent / 'reference_data' / 'nse_sessions.csv'
DISCLOSURE_LIMIT_SESSIONS = 2
# Special sessions inside the seed range, before holiday lists were kept:
# the one-hour Diwali Muhurat sessions on otherwise-closed weekdays.
SEED_SPECIAL_SESSIONS = ['2024-11-01', '2025-10-21']
# A weekday with no bhavcopy and no holiday listing may just be a late
# upload. It is retried on later nights and only accepted as a closure
# after this many days.
UNEXPLAINED_CLOSURE_GRACE_DAYS = 3


def _d(x) -> date:
    return x if isinstance(x, date) else pd.Timestamp(x).date()


class Calendar:
    def __init__(self, traded, special=(), confirmed_through=None):
        traded = sorted({_d(t) for t in traded})
        special = {_d(s) for s in special}
        self.first = traded[0] if traded else None
        self.confirmed_through = _d(confirmed_through) if confirmed_through else (traded[-1] if traded else None)
        self.days = [t for t in traded if t.weekday() < 5 and t not in special]

    @classmethod
    def from_state(cls, state: dict):
        return cls(state['traded'], state.get('special_sessions', ()), state.get('confirmed_through'))

    def covers(self, start, end) -> bool:
        return bool(self.first and start >= self.first and end <= self.confirmed_through)

    def sessions_after(self, start, end):
        """Sessions in (start, end]. None when the calendar can't answer."""
        if start is None or end is None or not self.covers(start, end):
            return None
        if end <= start:
            return 0
        return bisect.bisect_right(self.days, end) - bisect.bisect_right(self.days, start)


def lateness(cal: Calendar, start, end, limit=DISCLOSURE_LIMIT_SESSIONS):
    """(sessions, is_late); both None when a date is missing or the
    calendar can't answer."""
    n = cal.sessions_after(start, end)
    if n is None:
        return None, None
    return n, n > limit


def seed_state() -> dict:
    traded = pd.read_csv(SEED_PATH)['date'].tolist()
    return {'traded': traded, 'special_sessions': list(SEED_SPECIAL_SESSIONS),
            'holidays': {}, 'confirmed_through': traded[-1], 'unexplained_closures': [],
            'source': 'seed: Paresh NSE close history; then nightly bhavcopy checks'}


def holidays_from_nse(payload) -> list[dict]:
    """NSE's holiday-master response -> [{date, description}] for the
    capital-market segment."""
    rows = (payload or {}).get('CM') or []
    out = []
    for r in rows:
        try:
            day = pd.to_datetime(r['tradingDate'], format='%d-%b-%Y').date()
        except (KeyError, ValueError, TypeError):
            continue
        out.append({'date': day.isoformat(), 'description': str(r.get('description') or '').strip()})
    return out


def extend(state: dict, today: date, probe, holidays: list[dict] | None = None) -> dict:
    """Confirm days after state['confirmed_through'] up to `today`.

    `probe(day)` returns True if NSE published a bhavcopy for that day,
    False if it did not (HTTP 404), and raises on anything else (network
    error, 403, 5xx) -- in which case confirmation stops at the day before,
    to be retried next run. Returns a new state dict."""
    st = {**state, 'traded': list(state['traded']),
          'special_sessions': list(state.get('special_sessions', [])),
          'holidays': dict(state.get('holidays', {})),
          'unexplained_closures': list(state.get('unexplained_closures', []))}
    for h in holidays or []:
        st['holidays'].setdefault(h['date'][:4], {})[h['date']] = h['description']
    listed = {d for year in st['holidays'].values() for d in year}

    day = _d(st['confirmed_through']) + timedelta(days=1)
    while day <= today:
        try:
            traded = probe(day)
        except Exception:  # noqa: BLE001 -- any failure: stop here, retry next run
            break
        iso = day.isoformat()
        if traded:
            st['traded'].append(iso)
            if day.weekday() >= 5 or iso in listed:
                st['special_sessions'].append(iso)
        elif day.weekday() < 5 and iso not in listed:
            # Possibly a late upload, not a closure: wait before accepting.
            if (today - day).days < UNEXPLAINED_CLOSURE_GRACE_DAYS:
                break
            st['unexplained_closures'].append(iso)
        st['confirmed_through'] = iso
        day += timedelta(days=1)
    st['traded'] = sorted(set(st['traded']))
    st['special_sessions'] = sorted(set(st['special_sessions']))
    return st
