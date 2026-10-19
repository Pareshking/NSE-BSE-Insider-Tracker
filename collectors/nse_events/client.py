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

    def corporate_actions(self, start: date, end: date) -> list[dict]:
        j = self.get(f'{BASE}/api/corporates-corporateActions?index=equities&from_date={self._d(start)}&to_date={self._d(end)}')
        return j if isinstance(j, list) else j.get('data', [])

    def board_meetings(self, start: date, end: date) -> list[dict]:
        j = self.get(f'{BASE}/api/corporate-board-meetings?index=equities&from_date={self._d(start)}&to_date={self._d(end)}')
        return j if isinstance(j, list) else j.get('data', [])

    def shareholding_filings(self, start: date, end: date) -> list[dict]:
        j = self.get(f'{BASE}/api/corporate-share-holdings-master?index=equities&from_date={self._d(start)}&to_date={self._d(end)}')
        return j if isinstance(j, list) else j.get('data', [])

    INTEGRATED_FILING_TYPES = {
        'financials': 'Integrated Filing- Financials',
        'governance': 'Integrated Filing- Governance',
    }

    def integrated_filing_url(self, start: date, end: date, filing_type: str = 'financials',
                              page: int = 1, size: int = 100) -> str:
        """NSE's separate Integrated Filing tables; preserve type and pagination explicitly."""
        try:
            label = self.INTEGRATED_FILING_TYPES[filing_type]
        except KeyError as exc:
            raise ValueError(f'unsupported integrated filing type: {filing_type}') from exc
        from urllib.parse import quote
        return (f'{BASE}/api/integrated-filing-results?index=equities&from_date={self._d(start)}'
                f'&to_date={self._d(end)}&type={quote(label, safe="")}&page={page}&size={size}')

    # Backwards-compatible name retained for existing callers.
    def integrated_results_url(self, start: date, end: date, page: int = 1, size: int = 100) -> str:
        return self.integrated_filing_url(start, end, 'financials', page, size)

    def integrated_filings(self, start: date, end: date, filing_type: str = 'financials',
                           page_size: int = 100, max_pages: int = 100) -> list[dict]:
        """Fetch a bounded, paginated integrated-filing window; fail rather than silently truncating."""
        rows = []
        for page in range(1, max_pages + 1):
            payload = self.get(self.integrated_filing_url(start, end, filing_type, page, page_size),
                               timeout=10, retries=1)
            if isinstance(payload, list):
                data, total = payload, None
            elif isinstance(payload, dict):
                data = payload.get('data') or []
                total = payload.get('totalCount')
            else:
                raise RuntimeError(f'unexpected NSE integrated filing payload: {type(payload).__name__}')
            if not isinstance(data, list):
                raise RuntimeError('unexpected NSE integrated filing data shape')
            rows.extend(x for x in data if isinstance(x, dict))
            if not data or len(data) < page_size or (total is not None and len(rows) >= int(total)):
                return rows
        raise RuntimeError(f'NSE integrated filing pagination exceeded {max_pages} pages')

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
