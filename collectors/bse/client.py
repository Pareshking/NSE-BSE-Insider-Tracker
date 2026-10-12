"""A polite BSE client for api.bseindia.com.

Endpoints, parameters and caps confirmed with real answers on 12 Oct 2026
(fixtures in tests/fixtures/bse/):

* insider (SEBI PIT): Corp_Regulation_DownloadCSV_ng/w?scripCode=&Regulation=
  &fromDT=YYYYMMDD&ToDate=YYYYMMDD&Isdefault=2, the CSV behind the download
  button of BSE's insider page. Filters on the date reported to BSE; no cap
  seen (01-10 Oct 2026: 368 rows; a 30-day window = the sum of its three
  10-day windows). The JSON form of the same search (getCorp_Regulation_ng)
  stops at 25 rows, newest first, so it can't carry history.
* bulk / block deals: BulkDealData_ng/w?DealType=1|2&sc_code=&FDate=DD/MM/YYYY
  &TDate=DD/MM/YYYY. Filters on the deal date; no cap seen (30 days = the sum
  of three 10-day windows, 1,516 rows).
* SAST: Corporatesast/w?scripcode=&ddlregul=ALL&fromdate=YYYYMMDD&todate=
  YYYYMMDD. Filters on the first acquisition date. Some windows answer []
  although a wider window holds rows for those days (08-14 Mar 2026: [] ;
  01-31 Mar 2026: 315 rows in it), so callers tile and split (events.py).
* corporate actions: DefaultData/w?ddlcategorys=E&ddlindustrys=&segment=0
  &strSearch=S&Fdate=YYYYMMDD&TDate=YYYYMMDD&Purposecode=&scripcode=.
  Filters on the ex-date; a year in one call = the sum of its months.

Same headers as the `bse` package, which the nightly market-cap step already
uses from GitHub's runners. 4-6 s between calls, 3 retries on network errors
and 5xx, a hard stop on 401/403/429. Every answer is stored byte for byte in
raw_v2/ before it is read.

In-page fetch: notes from 09 Oct had BSE's API answering 403 outside a
browser. Plain requests with BSE's own Origin and Referer answer 200 from
here (12 Oct), so they come first; if BSE refuses them, the client moves to
an XHR made from inside a bseindia.com page in headless Chrome (the way BSE's
own pages call the API) for the rest of the run. Its raw copy is the page's
response text in UTF-8, marked `via: in_page_xhr` in the fetch record.
"""
from __future__ import annotations

import json
import random
import time
from datetime import date
from urllib.parse import urlencode

import requests

API = 'https://api.bseindia.com/BseIndiaAPI/api/'
HOME = 'https://www.bseindia.com/'
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/153.0.0.0 Safari/537.36')
HEADERS = {'User-Agent': UA, 'Accept': 'application/json, text/plain, */*', 'Accept-Language': 'en-US,en;q=0.5',
           'Origin': 'https://www.bseindia.com', 'Referer': HOME, 'Connection': 'keep-alive',
           'Sec-Fetch-Site': 'same-site'}
PACE_SECONDS = (4.0, 6.0)
RETRIES = 3
STOP_STATUSES = (401, 403, 429)
INSIDER_CSV_HEAD = 'Security Code,Security Name,Name of Person'


class Blocked(RuntimeError):
    """BSE refused us (401/403/429) or sent something that is not data. Stop."""


class Failed(RuntimeError):
    """Still failing after the retries (network error or 5xx)."""


def ymd(d: date) -> str:
    return d.strftime('%Y%m%d')


def dmy(d: date) -> str:
    return d.strftime('%d/%m/%Y')


class InPage:
    """api.bseindia.com called by an XHR from inside a bseindia.com page.
    (`fetch` with credentials fails BSE's CORS rule; a plain XHR passes.)"""

    SCRIPT = ("const cb = arguments[arguments.length - 1]; const x = new XMLHttpRequest();"
              "x.open('GET', arguments[0]); x.timeout = 90000;"
              "x.onload = () => cb([x.status, x.getResponseHeader('content-type') || '', x.responseText]);"
              "x.onerror = x.ontimeout = () => cb([0, '', '']); x.send();")

    def __init__(self, driver_factory=None):
        self._factory = driver_factory or self._chrome
        self._driver = None

    @staticmethod
    def _chrome():
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        o = Options()
        for a in ('--headless=new', '--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu',
                  '--disable-blink-features=AutomationControlled', f'--user-agent={UA}'):
            o.add_argument(a)
        d = webdriver.Chrome(options=o)
        d.set_script_timeout(120)
        return d

    def get(self, url: str) -> tuple[int, str, bytes]:
        if self._driver is None:
            self._driver = self._factory()
            self._driver.get(HOME)
        status, ctype, text = self._driver.execute_async_script(self.SCRIPT, url)
        return int(status or 0), ctype, (text or '').encode('utf-8')

    def close(self):
        if self._driver is not None:
            self._driver.quit()
            self._driver = None


class BSEClient:
    def __init__(self, session=None, sleep=time.sleep, rng=None, pace=PACE_SECONDS, raw=None,
                 in_page: InPage | None = None, allow_in_page: bool = True):
        self.raw = raw  # insiders_clean.raw_store.RawStore, or None (dry run)
        self.session = session or requests.Session()
        self.session.headers.update(HEADERS)
        self.sleep, self.rng, self.pace = sleep, rng or random.Random(), pace
        self.in_page, self.allow_in_page = in_page, allow_in_page
        self.via = 'in_page_xhr' if in_page is not None else 'requests'
        self.calls = 0

    def _wait(self):
        if self.calls:
            self.sleep(self.rng.uniform(*self.pace))
        self.calls += 1

    def _fetch(self, url: str, params: dict) -> tuple[int, str, bytes]:
        if self.via == 'in_page_xhr':
            return self.in_page.get(f'{url}?{urlencode(params)}')
        r = self.session.get(url, params=params, timeout=90)
        return r.status_code, r.headers.get('Content-Type', ''), r.content

    def get(self, path: str, params: dict, dataset: str, covers: dict | None = None) -> bytes:
        url = API + path
        last = None
        for _ in range(RETRIES + 1):
            self._wait()
            try:
                status, ctype, body = self._fetch(url, params)
            except requests.RequestException as e:
                last = f'{type(e).__name__}: {e}'
                continue
            if status in STOP_STATUSES and self.via == 'requests' and self.allow_in_page:
                # BSE refused a plain request: the rest of the run goes through the page.
                self.in_page = self.in_page or InPage()
                self.via = 'in_page_xhr'
                try:
                    status, ctype, body = self._fetch(url, params)
                except Exception as e:  # noqa: BLE001 -- no browser: report the refusal itself
                    raise Blocked(f'HTTP {status} from {url}; in-page fetch failed ({type(e).__name__}: {e})') from e
            if status in STOP_STATUSES:
                raise Blocked(f'HTTP {status} from {url} ({self.via})')
            if status == 0 or status >= 500:
                last = f'HTTP {status} from {url} ({self.via})'
                continue
            if status != 200:
                raise Blocked(f'HTTP {status} from {url} ({self.via})')
            if self.raw is not None:
                try:  # exact bytes first, before any parsing
                    self.raw.put('bse', dataset, body, url=url, params=params, status=status,
                                 content_type=ctype or None, covers=dict(covers or {}, via=self.via))
                except Exception as e:  # noqa: BLE001 -- never continue without the raw copy
                    raise Failed(f'raw store write failed: {type(e).__name__}: {e}') from e
            return body
        raise Failed(f'{last} (after {RETRIES} retries)')

    # --- endpoints -----------------------------------------------------------------

    def insider_csv(self, a: date, b: date) -> bytes:
        body = self.get('Corp_Regulation_DownloadCSV_ng/w',
                        {'scripCode': '', 'Regulation': '', 'fromDT': ymd(a), 'ToDate': ymd(b), 'Isdefault': '2'},
                        'insider_csv', {'from': a.isoformat(), 'to': b.isoformat()})
        head = body.decode('utf-8-sig', errors='replace').lstrip()[:200]
        if not head.startswith(INSIDER_CSV_HEAD):
            raise Blocked(f'not the insider CSV ({body[:60]!r})')
        return body

    def _json(self, path, params, dataset, covers):
        body = self.get(path, params, dataset, covers)
        try:
            payload = json.loads(body.decode('utf-8', errors='replace'))
        except ValueError:
            raise Blocked(f'not JSON from {path} ({body[:60]!r})') from None
        rows = payload.get('Table') if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise Blocked(f'JSON without a row list from {path}')
        return rows

    def deals(self, kind: str, a: date, b: date) -> list[dict]:
        deal_type = {'bulk': '1', 'block': '2'}[kind]
        return self._json('BulkDealData_ng/w', {'DealType': deal_type, 'sc_code': '', 'FDate': dmy(a), 'TDate': dmy(b)},
                          f'{kind}_deals_history', {'from': a.isoformat(), 'to': b.isoformat()})

    def sast(self, a: date, b: date) -> list[dict]:
        return self._json('Corporatesast/w', {'scripcode': '', 'ddlregul': 'ALL', 'fromdate': ymd(a), 'todate': ymd(b)},
                          'sast', {'from': a.isoformat(), 'to': b.isoformat()})

    def actions(self, a: date, b: date) -> list[dict]:
        return self._json('DefaultData/w', {'ddlcategorys': 'E', 'ddlindustrys': '', 'segment': '0', 'strSearch': 'S',
                                            'Fdate': ymd(a), 'TDate': ymd(b), 'Purposecode': '', 'scripcode': ''},
                          'corporate_actions', {'from': a.isoformat(), 'to': b.isoformat()})

    def close(self):
        if self.in_page is not None:
            self.in_page.close()
