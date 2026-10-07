"""Nightly: extend the NSE trading calendar in R2 (reference/nse_calendar.json).

For every day after the last confirmed one, asks NSE's archive whether that
day's bhavcopy exists (200 = traded, 404 = closed; anything else stops the
run there, to be retried tomorrow), and stores NSE's holiday list for the
current year so special sessions (Diwali Muhurat) are recognised. See
insiders_clean/calendar.py for the rules. Never needs a hand-edited file,
in 2027 or any later year.
"""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

from r2_writer import BUCKET, r2_client

from insiders_clean.calendar import extend, holidays_from_nse, seed_state

KEY = 'reference/nse_calendar.json'
IST = timezone(timedelta(hours=5, minutes=30))


def _archives(day: date):
    # Two independent NSE archives of the same day's market data. A
    # one-byte ranged GET: HEAD is refused (503) by the older host.
    yield f'https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{day:%Y%m%d}_F_0000.csv.zip'
    yield f'https://archives.nseindia.com/archives/equities/bhavcopy/pr/PR{day:%d%m%y}.zip'


def probe(day: date) -> bool:
    """True if either archive has the day, False only if both answer 404;
    raises otherwise, so an outage is never recorded as a holiday."""
    codes = []
    for url in _archives(day):
        try:
            resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0', 'Range': 'bytes=0-0'},
                                timeout=20, stream=True)
            resp.close()
            codes.append(resp.status_code)
        except requests.RequestException as exc:
            codes.append(type(exc).__name__)
        if codes[-1] in (200, 206):
            return True
    if all(c == 404 for c in codes):
        return False
    raise RuntimeError(f'bhavcopy check for {day}: {codes}')


def nse_holidays() -> list[dict]:
    try:
        from nse import NSE
        with NSE(tempfile.mkdtemp(), server=True) as n:
            return holidays_from_nse(n.holidays(type=NSE.HOLIDAY_TRADING))
    except Exception as exc:  # noqa: BLE001 -- the calendar still extends from bhavcopies alone
        print(f'  holiday list unavailable ({type(exc).__name__}); special sessions on '
              f'weekdays will count as sessions until it is fetched')
        return []


def main():
    client = r2_client()
    try:
        state = json.loads(client.get_object(Bucket=BUCKET, Key=KEY)['Body'].read())
    except client.exceptions.NoSuchKey:
        state = seed_state()
        print('  no calendar in R2 yet; starting from the seed')
    now = datetime.now(IST)
    # Today's bhavcopy is published in the evening; before 21:00 IST only
    # days up to yesterday are checked.
    through = now.date() if now.hour >= 21 else now.date() - timedelta(days=1)
    before = state['confirmed_through']
    state = extend(state, through, probe, nse_holidays())
    state['updated_at'] = now.isoformat()
    client.put_object(Bucket=BUCKET, Key=KEY, Body=json.dumps(state, indent=1).encode(),
                      ContentType='application/json')
    print(f'  calendar confirmed through {state["confirmed_through"]} (was {before}); '
          f'{len(state["traded"])} sessions, {len(state["special_sessions"])} special')
    if state['unexplained_closures']:
        print(f'  weekdays closed without a listed holiday: {state["unexplained_closures"]}')


if __name__ == '__main__':
    main()
