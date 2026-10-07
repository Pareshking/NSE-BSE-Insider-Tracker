"""A polite NSE client: one browser identity, a warm-up visit for cookies,
3-5 s between calls, a few retries on network errors and 5xx, and a hard stop
on 401/403/429 (NSE rate-limits by IP; pressing on gets the runner blocked
for longer)."""
from __future__ import annotations

import random
import time
from datetime import date

import requests

BASE = 'https://www.nseindia.com'
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')


class Blocked(RuntimeError):
    """NSE refused the session (401/403/429). Stop for this run."""


class NSEClient:
    def __init__(self, pause=(3.0, 5.0), retries=3, session=None, sleep=time.sleep):
        self.s = session or requests.Session()
        self.s.headers.update({'User-Agent': UA, 'Accept': 'application/json, text/plain, */*',
                               'Accept-Language': 'en-US,en;q=0.9', 'Referer': BASE + '/'})
        self.pause, self.retries, self.sleep = pause, retries, sleep
        self.calls = 0
        self._warm = False

    def _wait(self):
        if self.calls:
            self.sleep(random.uniform(*self.pause))
        self.calls += 1

    def warm_up(self):
        if self._warm:
            return
        try:
            self.s.get(BASE + '/', timeout=30)
        except requests.RequestException:
            pass  # the APIs answered without cookies in testing; warm-up is best effort
        self._warm = True

    def get(self, url, as_json=True):
        self.warm_up()
        last = None
        for attempt in range(self.retries):
            self._wait()
            try:
                r = self.s.get(url, timeout=60)
            except requests.RequestException as exc:
                last = exc
                continue
            if r.status_code in (401, 403, 429):
                raise Blocked(f'HTTP {r.status_code} for {url}')
            if r.status_code >= 500:
                last = RuntimeError(f'HTTP {r.status_code}')
                continue
            if r.status_code != 200:
                raise RuntimeError(f'HTTP {r.status_code} for {url}')
            if not as_json:
                return r.text
            try:
                return r.json()
            except ValueError as exc:
                last = exc  # an HTML error page in place of JSON
                continue
        raise RuntimeError(f'{url}: gave up after {self.retries} tries ({last})')

    # --- endpoints (all confirmed 07 Oct 2026) -------------------------------

    @staticmethod
    def _d(day: date) -> str:
        return day.strftime('%d-%m-%Y')

    def sast_reg29(self, start: date, end: date) -> list[dict]:
        j = self.get(f'{BASE}/api/corporate-sast-reg29?index=equities&from_date={self._d(start)}&to_date={self._d(end)}')
        return j.get('data', []) if isinstance(j, dict) else j

    def corporate_actions(self, start: date, end: date) -> list[dict]:
        j = self.get(f'{BASE}/api/corporates-corporateActions?index=equities&from_date={self._d(start)}&to_date={self._d(end)}')
        return j if isinstance(j, list) else j.get('data', [])

    def board_meetings(self, start: date, end: date) -> list[dict]:
        j = self.get(f'{BASE}/api/corporate-board-meetings?index=equities&from_date={self._d(start)}&to_date={self._d(end)}')
        return j if isinstance(j, list) else j.get('data', [])

    def shareholding_filings(self, start: date, end: date) -> list[dict]:
        j = self.get(f'{BASE}/api/corporate-share-holdings-master?index=equities&from_date={self._d(start)}&to_date={self._d(end)}')
        return j if isinstance(j, list) else j.get('data', [])

    def xbrl(self, url: str) -> str:
        return self.get(url, as_json=False)
