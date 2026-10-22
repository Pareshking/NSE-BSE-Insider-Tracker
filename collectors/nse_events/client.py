"""A polite NSE client: one browser identity, a warm-up visit for cookies,
3-5 s between calls, a few retries on network errors and 5xx, and a hard stop
on 401/403/429 (NSE rate-limits by IP; pressing on gets the runner blocked
for longer)."""
from __future__ import annotations

import random
import re
import time
from datetime import date, datetime

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
        # Called as on_response(url, response) for every 200 answer, before
        # parsing: the run that wants the write-once raw copy sets it.
        self.on_response = None

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

    def get(self, url, as_json=True, *, timeout=60, retries=None):
        self.warm_up()
        last = None
        attempts = self.retries if retries is None else max(1, int(retries))
        for attempt in range(attempts):
            self._wait()
            try:
                r = self.s.get(url, timeout=timeout)
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
            if self.on_response is not None:
                self.on_response(url, r)
            if not as_json:
                return r.text
            try:
                return r.json()
            except ValueError as exc:
                last = exc  # an HTML error page in place of JSON
                continue
        raise RuntimeError(f'{url}: gave up after {attempts} tries ({last})')

    # --- endpoints (all confirmed 07 Oct 2026) -------------------------------

    @staticmethod
    def _d(day: date) -> str:
        return day.strftime('%d-%m-%Y')

    def sast_reg29(self, start: date, end: date) -> list[dict]:
        j = self.get(f'{BASE}/api/corporate-sast-reg29?index=equities&from_date={self._d(start)}&to_date={self._d(end)}')
        return j.get('data', []) if isinstance(j, dict) else j

    def encumbrances(self, start: date, end: date) -> list[dict]:
        """SAST Reg 31(1)/(2) disclosures: each creation, release or invocation of a pledge, a non-disposal
        undertaking or another encumbrance by a promoter, with the lender (the page
        /companies-listing/corporate-filings-regulation-31, seen 22 Oct 2026)."""
        j = self.get(f'{BASE}/api/corporate-pledgedata-sast3132?index=equities&from_date={self._d(start)}&to_date={self._d(end)}')
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

    def integrated_results_url(self, start: date, end: date, page: int = 1, size: int = 100) -> str:
        """Financial results filed as NSE's integrated filing, newest first, `size` a page
        (confirmed 15 Oct 2026: {'data', 'size', 'page', 'totalCount'}; page=2 is the second page). The nightly
        results stream lists by it (run_daily.results_filings); it was dropped on 19 Oct (2d4f670) and every
        night's results fetch failed until 22 Oct."""
        return (f'{BASE}/api/integrated-filing-results?index=equities&from_date={self._d(start)}'
                f'&to_date={self._d(end)}&type=Integrated%20Filing-%20Financials&page={page}&size={size}')

    def integrated_filing_financials_url(self, symbol: str | None = None,
                                          quarter_end_date: str | None = None) -> str:
        """NSE's dedicated Integrated Filing-Financials API, scoped to one issuer or quarter."""
        from urllib.parse import quote
        if bool(symbol) == bool(quarter_end_date):
            raise ValueError('provide exactly one of symbol or quarter_end_date')
        if symbol:
            symbol = str(symbol).strip().upper()
            if not re.fullmatch(r'[A-Z0-9&._-]{1,32}', symbol):
                raise ValueError('a valid NSE symbol is required')
            query = f'symbol={quote(symbol, safe="")}'
        else:
            quarter_end_date = str(quarter_end_date).strip()
            try:
                datetime.strptime(quarter_end_date, '%d-%b-%Y')
            except ValueError as exc:
                raise ValueError('quarter_end_date must use DD-Mmm-YYYY, e.g. 30-Sep-2026') from exc
            query = f'quarterEndDate={quote(quarter_end_date, safe="")}'
        return f'{BASE}/api/integrated-filing-financials?index=equities&{query}'

    def corporate_governance_url(self, symbol: str) -> str:
        """NSE's dedicated corporate-governance API; do not infer it from financial filings."""
        from urllib.parse import quote
        symbol = str(symbol or '').strip().upper()
        if not symbol or not re.fullmatch(r'[A-Z0-9&._-]{1,32}', symbol):
            raise ValueError('a valid NSE symbol is required')
        return f'{BASE}/api/corporate-governance?index=equities&symbol={quote(symbol, safe="")}'

    @staticmethod
    def _rows(payload) -> list[dict]:
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, dict)]
        if isinstance(payload, dict):
            data = payload.get('data', [])
            if isinstance(data, list):
                return [row for row in data if isinstance(row, dict)]
        raise RuntimeError('unexpected NSE integrated filing payload shape')

    def integrated_filing_financials(self, symbol: str | None = None,
                                     quarter_end_date: str | None = None) -> list[dict]:
        """Fetch one issuer's or one quarter's financial filings; caller filters by the live window."""
        url = self.integrated_filing_financials_url(symbol=symbol, quarter_end_date=quarter_end_date)
        return self._rows(self.get(url, timeout=10, retries=1))

    def corporate_governance(self, symbol: str) -> list[dict]:
        """Fetch one issuer's governance filings through its separate endpoint."""
        return self._rows(self.get(self.corporate_governance_url(symbol), timeout=10, retries=1))

    def xbrl(self, url: str) -> str:
        return self.get(url, as_json=False)

    # --- buybacks (confirmed 12 Oct 2026) --------------------------------------
    # NSE's tender-offer window (market-data/all-upcoming-issues-ofs-tender-offer):
    # every buyback, takeover and delisting tender since 2015 with its offer
    # price, shares sought and shares tendered. No date parameters: the whole
    # list each call.

    def tender_offers_past(self) -> list[dict]:
        j = self.get(f'{BASE}/api/liveTenderPast-issues')
        return j.get('data', []) if isinstance(j, dict) else j

    def tender_offers_active(self) -> list[dict]:
        j = self.get(f'{BASE}/api/liveTenderActive-issues')
        return j if isinstance(j, list) else j.get('data', [])

    def daily_buybacks(self, start: date, end: date) -> list[dict]:
        """Daily buyback reports (corporate-filings-daily-buy-back): filed each
        day shares are bought back in an open-market buyback. On 12 Oct 2026
        the answer held the last two months whatever the dates asked."""
        j = self.get(f'{BASE}/api/corporates-daily-buyback?index=equities&from_date={self._d(start)}&to_date={self._d(end)}')
        return j.get('data', []) if isinstance(j, dict) else j

    # --- announcements (confirmed 13 Oct 2026) -------------------------------
    # Every Reg 30 announcement NSE broadcast in the window, each with its
    # PDF link. No cap seen: 01-30 Sep 2026 gave 17,127 rows in one call;
    # 08-12 Oct gave 1,999, the sum of its days.

    # index=sme (confirmed 13 Oct 2026): the SME board's filings, same fields and
    # the same seq_id numbering as equities, no seq_id or symbol in both.
    def announcements_url(self, start: date, end: date, index: str = 'equities') -> str:
        return f'{BASE}/api/corporate-announcements?index={index}&from_date={self._d(start)}&to_date={self._d(end)}'

    def announcements(self, start: date, end: date, index: str = 'equities') -> list[dict]:
        j = self.get(self.announcements_url(start, end, index))
        return j if isinstance(j, list) else j.get('data', [])

    def xbrl_announcements(self, start: date, end: date, index: str = 'equities',
                           symbol: str | None = None, feed_type: str = 'announcements') -> list[dict]:
        """Fetch one NSE XBRL-announcement feed type: announcements, para-a, para-b, or award.

        NSE exposes multiple feed types. The legacy announcements feed alone misses Para A/Para B
        records; para-b carries post-20-Jun-2026 material events, while award preserves the legacy
        order-award feed. A row's xbrl URL may differ from its ordinary PDF attachment URL.
        """
        if feed_type not in {'announcements', 'para-a', 'para-b', 'award'}:
            raise ValueError(f'unsupported NSE XBRL feed type: {feed_type}')
        query = (f'index={index}&from_date={self._d(start)}&to_date={self._d(end)}'
                 f'&type={feed_type}')
        if symbol:
            query += f'&symbol={symbol}'
        self.warm_up()
        old_referer = self.s.headers.get('Referer')
        old_x_requested_with = self.s.headers.get('X-Requested-With')
        self.s.headers['Referer'] = BASE + '/companies-listing/corporate-filings-announcements-xbrl'
        self.s.headers['X-Requested-With'] = 'XMLHttpRequest'
        try:
            # XBRL is an optional speed path, so its endpoint must never hold up live PDF
            # processing for the normal 60s x 3 network retry budget.
            j = self.get(f'{BASE}/api/XBRL-announcements?{query}', timeout=10, retries=1)
        finally:
            if old_referer is None:
                self.s.headers.pop('Referer', None)
            else:
                self.s.headers['Referer'] = old_referer
            if old_x_requested_with is None:
                self.s.headers.pop('X-Requested-With', None)
            else:
                self.s.headers['X-Requested-With'] = old_x_requested_with
        return j if isinstance(j, list) else j.get('data', [])

    # --- further issues (confirmed 12 Oct 2026) -----------------------------
    # Preferential, rights and QIP, each in two stages. With from_date/to_date
    # NSE returns every filing it posted in the window, not only the latest
    # 100 (08-10-2025 to 12-10-2026 gave 639 preferential listing filings).
    FURTHER_ISSUES = {
        ('preferential', 'in_principle'): 'corporate-further-issues-pref?index=FIPREFIP',
        ('preferential', 'listing'): 'corporate-further-issues-pref?index=FIPREFLS',
        ('rights', 'in_principle'): 'corporate-further-issues-ri?index=FIRIIP',
        ('rights', 'listing'): 'corporate-further-issues-ri?index=FIRILS',
        ('qip', 'in_principle'): 'corporate-further-issues-qip?index=FIQIPIP',
        ('qip', 'listing'): 'corporate-further-issues-qip?index=FIQIPLS',
    }

    def further_issues_url(self, kind: str, stage: str, start: date, end: date) -> str:
        return f'{BASE}/api/{self.FURTHER_ISSUES[(kind, stage)]}&from_date={self._d(start)}&to_date={self._d(end)}'
