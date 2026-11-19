"""Listing services of fund houses whose disclosure page draws its file list from an endpoint instead of links.

Each function takes a month ('2026-10') and returns (text, href) pairs of the house's portfolio files, read from the
same service the house's own page calls, with nothing guessed: `find.candidates` then picks the month's monthly
file(s) from them exactly as it does from page links. A service that cannot be read raises; the collector reports it.
Two houses (Edelweiss, Bandhan) fill their list only after a month is picked in a browser; those read the page in a
headless browser (CHROMIUM_PATH, as for render=True houses).
"""
from __future__ import annotations

import calendar
import contextlib
import functools
import json
import os
import re
from datetime import date, timedelta
from urllib.parse import urljoin

from collectors.mf_portfolios.find import UA, links_plain

TIMEOUT = 90


def _session():
    import requests
    s = requests.Session()
    s.headers['User-Agent'] = UA
    return s


def _anchors(html: str, base: str) -> list[tuple[str, str]]:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'lxml')
    return [(a.get_text(' ', strip=True), urljoin(base, a['href'].strip())) for a in soup.find_all('a', href=True)]


def _ym(month: str) -> tuple[int, int]:
    y, m = (int(x) for x in month.split('-'))
    return y, m


@contextlib.contextmanager
def _browser():
    from playwright.sync_api import sync_playwright
    exe = os.environ.get('CHROMIUM_PATH')   # a browser installed apart from the Python package (local runs)
    with sync_playwright() as pw:
        b = pw.chromium.launch(**({'executable_path': exe, 'args': ['--no-sandbox']} if exe else {}))
        try:
            yield b
        finally:
            b.close()


# --- Franklin Templeton: the literature JSON its Reports page is built from -----------------------------------------
FRANKLIN = 'https://www.franklintempletonindia.com'


@functools.lru_cache(maxsize=1)
def _franklin_lit() -> dict:
    r = _session().get(f'{FRANKLIN}/api/literature/v1/responseLitJson?type=report', timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def franklin(month: str) -> list[tuple[str, str]]:
    out = []
    for group in _franklin_lit().get('FirstDropDown', []):
        if group.get('id') != 'MONTHLY-PORTFOLIO-DSCLR':
            continue
        for rec in (group.get('dataRecords') or {}).get('linkdata', []):
            if rec.get('literatureHref'):   # the page's download address is /download + the document's address
                out.append((rec.get('dctermsTitle') or '', f'{FRANKLIN}/download{rec["literatureHref"]}'))
    return out


# --- Canara Robeco: the monthly-portfolio page filtered by year and month, in pages of 15 schemes --------------------
CANARA = 'https://www.canararobeco.com/documents/statutory-disclosures/scheme-dashboard/scheme-monthly-portfolio/'


def canara(month: str) -> list[tuple[str, str]]:
    y, m = _ym(month)
    s, out, seen = _session(), [], set()
    for page in range(1, 21):
        links = links_plain(f'{CANARA}?filteryear={y}&filtermonth={m:02d}&pagination={page}', session=s)
        files = [(t, h) for t, h in links if '/wp-content/uploads/' in h and re.search(r'\.(xlsx?|zip)$', h, re.I)]
        new = [(t, h) for t, h in files if h not in seen]
        if not new:
            break
        seen.update(h for _, h in new)
        out += new
    return out


# --- Invesco: the holdings service behind its Monthly Holdings tabs (one row per scheme, a column per month) ----------
INVESCO = 'https://www.invescomutualfund.com/api/CompleteMonthlyHoldings'
INVESCO_CLASSES = ('equity', 'hybrid', 'index-funds', 'exchange-traded-fund')   # the tabs that hold equity shares


def invesco(month: str) -> list[tuple[str, str]]:
    y, m = _ym(month)
    s, out = _session(), []
    ab = calendar.month_abbr[m]
    for c in INVESCO_CLASSES:
        r = s.get(INVESCO, params={'year': y, 'classification': c}, timeout=TIMEOUT)
        r.raise_for_status()
        for row in r.json():
            url = (row.get(f'{ab}Url') or '').strip()
            if url:   # labelled as the page labels it: "<scheme> - October-2026"
                out.append((f'{(row.get("Name") or "").strip()} - {calendar.month_name[m]}-{y}', url))
    return out


# --- quant: the statutory-disclosures accordion, filled by a page method per year --------------------------------------
def quant(month: str) -> list[tuple[str, str]]:
    y, _ = _ym(month)
    r = _session().post('https://quantmutual.com/statutorydisclosures.aspx/displaydisclouser',
                        data=json.dumps({'id': str(y), 'cat': 'MONTHLY PORTFOLIO'}),
                        headers={'Content-Type': 'application/json; charset=utf-8'}, timeout=TIMEOUT)
    r.raise_for_status()
    return _anchors(r.json().get('d') or '', 'https://quantmutual.com/')


# --- Sundaram: the portfolio page's AjaxPro method for the Monthly category ------------------------------------------
SUNDARAM = 'https://www.sundarammutual.com/Monthly-Fortnightly-Adhoc-Portfolios'


def sundaram(month: str) -> list[tuple[str, str]]:
    s = _session()
    page = s.get(SUNDARAM, timeout=TIMEOUT)
    page.raise_for_status()
    ajax = re.search(r'/ajax/Modules_Disclosure_Monthly_Fortnightly_Adhoc_Portfolios,[^"\']+\.ashx', page.text)
    if not ajax:
        raise ValueError('portfolio method not on the page')
    r = s.post(urljoin(SUNDARAM, ajax.group(0)) + '?_method=GetCategory&_session=no', data='Catid=Monthly',
               headers={'Content-Type': 'text/plain; charset=utf-8'}, timeout=TIMEOUT)
    r.raise_for_status()
    html = r.text.strip()
    if html.startswith("'") and html.endswith("'"):   # an AjaxPro string: quoted, quotes escaped
        html = html[1:-1].replace("\\'", "'").replace('\\"', '"').replace('\\/', '/')
    return _anchors(html, SUNDARAM)


# --- LIC: the Consolidated Portfolio tab (type 639 = Monthly Portfolio), by month ----------------------------------
LIC = 'https://www.licmf.com'


def lic(month: str) -> list[tuple[str, str]]:
    y, m = _ym(month)
    s = _session()
    s.get(f'{LIC}/downloads/monthly-portfolio', timeout=TIMEOUT).raise_for_status()
    r = s.post(f'{LIC}/downloads/consolidated-portfolio-files', data={'id': '639', 'month': str(m), 'year': str(y)},
               timeout=TIMEOUT)
    r.raise_for_status()
    return _anchors(r.text, f'{LIC}/downloads/monthly-portfolio')


# --- PGIM India: the disclosures service behind its Monthly Portfolio tabs ------------------------------------------
PGIM_TABS = ('Equity',)   # Debt and Fund of Funds tabs hold no Indian equity shares


def pgim(month: str) -> list[tuple[str, str]]:
    r = _session().post('https://www.pgimindia.com/api/v1/brochure/published/disclosure',
                        json={'headerId': 2, 'sectionId': 'SECTION_747960037', 'source': 'W', 'branchCode': None},
                        timeout=TIMEOUT)
    r.raise_for_status()
    out = []
    for tab in r.json().get('data') or []:
        if tab.get('tabName') not in PGIM_TABS:
            continue
        for c in tab.get('content') or []:
            path = re.sub(r'^(?:https?:)?/*', '', (c.get('pdfPath') or '').strip())   # stored as //www..., /www... or https://www...
            if path:
                out.append((f'{c.get("title") or ""} {c.get("dateMonthYear") or ""}'.strip(), 'https://' + path))
    return out


# --- WhiteOak Capital: the CMS its Scheme Portfolios page reads (period Monthly, published after the month-end) -----
def whiteoak(month: str) -> list[tuple[str, str]]:
    y, m = _ym(month)
    end = date(y, m, calendar.monthrange(y, m)[1])
    params = {'filters[period][$eq]': 'Monthly', 'filters[published_date][$gt]': end.isoformat(),
              'filters[published_date][$lte]': (end + timedelta(days=60)).isoformat(),
              'pagination[pageSize]': 200, 'populate': 'doc_file'}
    r = _session().get('https://cms.whiteoakamc.com/api/scheme-portfolios', params=params, timeout=TIMEOUT)
    r.raise_for_status()
    out = []
    for row in r.json().get('data') or []:
        a = row.get('attributes') or {}
        f = ((a.get('doc_file') or {}).get('data') or {}).get('attributes') or {}
        url = f.get('url') or a.get('doc_link')
        if url:
            out.append((a.get('doc_name') or '', url))
    return out


# --- 360 ONE: the download list is in the page's own data (Next.js), as fileName / fileUrl pairs ---------------------
ONE360 = 'https://www.360.one/asset/mutual-funds/downloads/'


def one360(month: str) -> list[tuple[str, str]]:
    r = _session().get(ONE360, timeout=TIMEOUT)
    r.raise_for_status()
    text = r.text.replace('\\"', '"').replace('\\/', '/')
    return [(n, u) for n, u in re.findall(r'"fileName":"([^"]*)","fileUrl":"([^"]+)"', text)]


# --- HSBC: the information library page; its portfolio files are served without an extension ---------------------
HSBC = 'https://www.assetmanagement.hsbc.co.in/en/mutual-funds/investor-resources/information-library'


def hsbc(month: str) -> list[tuple[str, str]]:
    return [(t, h) for t, h in links_plain(HSBC, timeout=240) if re.search(r'/mutual-funds/portfolios/document-\d{8}/', h, re.I)]


# --- Edelweiss: Portfolio of scheme(s) > Monthly Portfolio, year and month picked in a browser ------------------------
EDELWEISS = 'https://www.edelweissmf.com/statutory/portfolio-of-schemes'


def edelweiss(month: str) -> list[tuple[str, str]]:
    y, m = _ym(month)
    with _browser() as b:
        ctx = b.new_context(user_agent=UA)
        page = ctx.new_page()
        try:
            try:
                page.goto(EDELWEISS, wait_until='networkidle', timeout=60000)
            except Exception:  # noqa: BLE001 - a page that never goes idle still has its links
                pass
            page.wait_for_timeout(4000)
            page.get_by_text('Monthly Portfolio and Risk-o-Meter', exact=False).first.click(timeout=15000)
            page.wait_for_timeout(4000)
            for placeholder, label in (('Select Year', str(y)), ('Select Month', calendar.month_abbr[m])):
                page.locator(f'mat-select[placeholder="{placeholder}"]').first.click(timeout=15000)
                page.wait_for_timeout(1000)
                page.locator('mat-option').filter(has_text=re.compile(rf'^\s*{label}\s*$')).first.click(timeout=15000)
                page.wait_for_timeout(3000)
            anchors = page.evaluate("() => [...document.querySelectorAll('a')].map(a => [a.innerText || '', a.href])")
        finally:
            ctx.close()
    return [(t.strip(), h) for t, h in anchors if h and '/Monthly_Portfolio' in h]


# --- Bandhan: Disclosure of Detailed Scheme Portfolios > Monthly; one file per scheme, picked scheme by scheme -------
# The list comes from an encrypted service, so the page is driven as a person would: year, month, then each scheme
# in turn; each file's address is the one its row starts downloading (the download itself is cancelled).
BANDHAN = 'https://bandhanmutual.com/statutory-disclosures/scheme-portfolios/monthly-half-yearly'

def bandhan(month: str) -> list[tuple[str, str]]:
    from urllib.parse import parse_qs, urlparse
    y, m = _ym(month)
    out = []

    def pick(page, i, label):
        """Open dropdown i and click option `label` (None: list its options and close it); None when not offered."""
        box = page.locator('button[type=button].w-full').nth(i).locator('xpath=..')
        opts = box.locator('li')
        for _ in range(3):   # the list toggles; make sure it is open
            if opts.count():
                break
            box.locator('button').first.click(force=True, timeout=15000)
            page.wait_for_timeout(1000)
        names = [t.strip() for t in opts.all_inner_texts()]
        if label is None or label not in names:
            if opts.count():
                box.locator('button').first.click(force=True, timeout=15000)
            return names if label is None else None
        k = names.index(label)
        opts.nth(k).scroll_into_view_if_needed(timeout=15000)   # the list scrolls; a click lands only on what shows
        opts.nth(k).click(timeout=15000)
        return names

    def rows_text(page):
        return page.locator('div.flex-1 > div.text-base').all_inner_texts()

    with _browser() as b:
        ctx = b.new_context(user_agent=UA, accept_downloads=True)
        page = ctx.new_page()
        try:
            for load in range(3):   # the page sometimes arrives without its lists; load it again
                try:
                    page.goto(BANDHAN, wait_until='networkidle', timeout=90000)
                except Exception:  # noqa: BLE001
                    pass
                page.wait_for_timeout(4000)
                with contextlib.suppress(Exception):   # the push-notification prompt covers the dropdowns
                    page.get_by_text('May be later').click(timeout=3000)
                bad = next((label for i, label in ((0, str(y)), (1, calendar.month_name[m]))
                            if pick(page, i, label) is None or page.wait_for_timeout(2500)), None)
                if bad is None:
                    break
            else:
                raise ValueError(f'{bad} not offered on the page')
            schemes = pick(page, 2, None) or []
            if not schemes:
                raise ValueError('no schemes listed for the month')
            before, todo = rows_text(page), list(schemes)
            for attempt in range(4):   # a pick whose rows never load is tried again on a later pass
                missing = []
                for s in todo:
                    first = attempt == 0 and s == schemes[0]   # the scheme shown on arrival
                    if not first and pick(page, 2, s) is None:
                        missing.append(s)
                        continue
                    now = before
                    for _ in range(40):   # its rows load after the pick
                        page.wait_for_timeout(500)
                        now = rows_text(page)
                        if first or now != before:
                            break
                    if not first and now == before:
                        missing.append(s)
                        continue
                    before = now
                    rows = page.locator('div.flex-1 > div.text-base')
                    for k in range(rows.count()):
                        text = rows.nth(k).inner_text().strip()
                        with page.expect_download(timeout=20000) as dl:
                            rows.nth(k).evaluate('e => e.click()')
                        url = dl.value.url
                        dl.value.cancel()
                        out.append((text, parse_qs(urlparse(url).query).get('filepath', [url])[0]))
                todo = missing
                if not todo:
                    break
            if missing:
                import sys
                print(f'bandhan {month}: {len(missing)} of {len(schemes)} schemes showed no file after 4 passes: {missing}',
                      file=sys.stderr)
        finally:
            ctx.close()
    return out
