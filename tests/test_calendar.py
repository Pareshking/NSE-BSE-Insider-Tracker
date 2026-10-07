"""Trading calendar: deadlines in sessions, and the nightly self-extension
that keeps it working in 2027 and later without a hand-kept holiday file."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from insiders_clean.calendar import (
    Calendar,
    extend,
    holidays_from_nse,
    lateness,
    seed_state,
)


def test_seed_is_real_sessions(calendar):
    assert calendar.first == date(2024, 9, 30)
    # Known holidays absent, ordinary days present.
    for closed in (date(2025, 8, 15), date(2025, 10, 2), date(2025, 12, 25), date(2024, 11, 20)):
        assert closed not in calendar.days
    assert date(2025, 10, 3) in calendar.days


def test_holiday_is_skipped(calendar):
    # Wed 01 Oct 2025 -> Mon 06 Oct 2025; 02 Oct (Gandhi Jayanti) closed.
    assert calendar.sessions_after(date(2025, 10, 1), date(2025, 10, 6)) == 2
    assert lateness(calendar, date(2025, 10, 1), date(2025, 10, 6)) == (2, False)


def test_weekend_is_skipped(calendar):
    assert calendar.sessions_after(date(2026, 8, 28), date(2026, 8, 31)) == 1  # Fri -> Mon


def test_special_sessions_do_not_count(calendar):
    # Muhurat on Tue 21 Oct 2025, holiday 22 Oct: Mon 20 -> Thu 23 is one session.
    assert calendar.sessions_after(date(2025, 10, 20), date(2025, 10, 23)) == 1
    # Budget Saturday 01 Feb 2025 is not a deadline day.
    assert calendar.sessions_after(date(2025, 1, 31), date(2025, 2, 3)) == 1


def test_unknown_beyond_confirmed(calendar):
    assert calendar.sessions_after(date(2026, 9, 30), date(2026, 10, 5)) is None
    assert lateness(calendar, None, date(2026, 9, 1)) == (None, None)


def _probe_from(traded: set, broken: set = frozenset()):
    def probe(day):
        if day in broken:
            raise RuntimeError('HTTP 503')
        return day in traded
    return probe


def _state(through):
    return {'traded': [through.isoformat()], 'special_sessions': [], 'holidays': {},
            'confirmed_through': through.isoformat(), 'unexplained_closures': []}


def test_extends_into_2027_and_beyond_without_a_holiday_file():
    start = date(2027, 12, 24)  # Fri
    traded = {date(2027, 12, 27), date(2027, 12, 28), date(2027, 12, 29), date(2027, 12, 30),
              date(2027, 12, 31), date(2028, 1, 3)}
    holidays = [{'date': '2028-01-26', 'description': 'Republic Day'}]
    st = extend(_state(start), date(2028, 1, 4), _probe_from(traded), holidays)
    assert st['confirmed_through'] == '2028-01-03'  # 4 Jan: no bhavcopy yet, unlisted -> wait
    cal = Calendar.from_state(st)
    assert cal.sessions_after(date(2027, 12, 31), date(2028, 1, 3)) == 1  # across New Year weekend
    assert '2028' in st['holidays']


def test_listed_holiday_confirmed_at_once():
    st = extend(_state(date(2028, 1, 25)), date(2028, 1, 27), _probe_from({date(2028, 1, 27)}),
                [{'date': '2028-01-26', 'description': 'Republic Day'}])
    assert st['confirmed_through'] == '2028-01-27'
    assert '2028-01-26' not in st['traded'] and st['unexplained_closures'] == []


def test_outage_never_becomes_a_holiday():
    day = date(2028, 3, 1)
    st = extend(_state(day - timedelta(days=1)), day + timedelta(days=5), _probe_from(set(), broken={day}))
    assert st['confirmed_through'] == (day - timedelta(days=1)).isoformat()


def test_unexplained_closure_accepted_after_grace():
    day = date(2028, 3, 1)  # Wed, no bhavcopy, not on the list
    st = extend(_state(day - timedelta(days=1)), day + timedelta(days=4),
                _probe_from({day + timedelta(days=1), day + timedelta(days=2)}))
    assert st['unexplained_closures'] == ['2028-03-01']
    assert st['confirmed_through'] >= '2028-03-02'


def test_muhurat_on_listed_holiday_is_special():
    day = date(2027, 10, 29)  # hypothetical weekday Diwali with a Muhurat session
    st = extend(_state(day - timedelta(days=1)), day, _probe_from({day}),
                [{'date': day.isoformat(), 'description': 'Diwali Laxmi Pujan*'}])
    assert day.isoformat() in st['special_sessions']
    assert day not in Calendar.from_state(st).days


def test_holiday_payload_parsing():
    payload = {'CM': [{'tradingDate': '08-Nov-2026', 'description': 'Diwali Laxmi Pujan*'},
                      {'tradingDate': 'bad', 'description': 'x'}]}
    assert holidays_from_nse(payload) == [{'date': '2026-11-08', 'description': 'Diwali Laxmi Pujan*'}]


def test_seed_state_round_trips():
    st = seed_state()
    assert st['confirmed_through'] == '2026-10-01'
    with pytest.raises(KeyError):
        Calendar.from_state({})
