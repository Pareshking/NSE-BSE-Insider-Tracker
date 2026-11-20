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
import re
from datetime import date, timedelta
from urllib.parse import urljoin

from collectors.mf_portfolios.find import UA, links_plain, raise_for_status, shared_browser

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
    """The process's shared browser (find.shared_browser): a second sync_playwright() beside the collector's raises
    "Playwright Sync API inside the asyncio loop", which is what Edelweiss and Bandhan answered in every run with a
    render=True house. Each reader opens and closes its own context in it; the browser stays for the next."""
    yield shared_browser()


# --- Franklin Templeton: the literature JSON its Reports page is built from -----------------------------------------
FRANKLIN = 'https://www.franklintempletonindia.com'


@functools.lru_cache(maxsize=1)
def _franklin_lit() -> dict:
    r = _session().get(f'{FRANKLIN}/api/literature/v1/responseLitJson?type=report', timeout=TIMEOUT)
    raise_for_status(r)
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
        raise_for_status(r)
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
    raise_for_status(r)
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
    raise_for_status(r)
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
    raise_for_status(r)
    return _anchors(r.text, f'{LIC}/downloads/monthly-portfolio')


# --- PGIM India: the disclosures service behind its Monthly Portfolio tabs ------------------------------------------
PGIM_TABS = ('Equity',)   # Debt and Fund of Funds tabs hold no Indian equity shares


def pgim(month: str) -> list[tuple[str, str]]:
    r = _session().post('https://www.pgimindia.com/api/v1/brochure/published/disclosure',
                        json={'headerId': 2, 'sectionId': 'SECTION_747960037', 'source': 'W', 'branchCode': None},
                        timeout=TIMEOUT)
    raise_for_status(r)
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
    raise_for_status(r)
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
    raise_for_status(r)
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
            page.get_by_text('Monthly Portfolio and Risk-o-Meter', exact=False).first.click(timeout=60000)   # 15 s timed out on a runner (probe run 44663322178)
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


# --- Mahindra Manulife: Mandatory Disclosures > Portfolio Disclosure > Monthly Portfolio Disclosure ------------------
# The downloads list is shown only after the visitor declares "I am NOT a US person / resident of Canada" (the owner
# made that declaration for this collector, 19 Nov 2026). The list arrives encrypted and the page decrypts it in the
# browser, so the page is opened, the declaration clicked, and the list read as the page itself parses it. The files
# (cms.mahindramanulife.com) need nothing more.
MAHINDRA = 'https://www.mahindramanulife.com/downloads'
_CAPTURE = """(() => { const parse = JSON.parse; window.__lists = [];
  JSON.parse = function (t, r) { const v = parse.call(this, t, r);
    try { if (typeof t === 'string' && t.includes('Downloads fetched')) window.__lists.push(t); } catch (e) {}
    return v; }; })();"""


def mahindra_links(listing: dict) -> list[tuple[str, str]]:
    """(title, file) of every file under the 'Monthly Portfolio Disclosure' category of the downloads list."""
    out = []

    def walk(nodes, inside):
        for c in nodes or []:
            here = inside or (c.get('categoryName') or '').strip().lower() == 'monthly portfolio disclosure'
            if here:
                out.extend(((f.get('title') or '').strip(), f.get('fileUrl') or f.get('redirectUrl') or '')
                           for f in c.get('files') or [] if f.get('fileUrl') or f.get('redirectUrl'))
            walk(c.get('subcategories'), here)

    walk(listing.get('data'), False)
    return out


@functools.lru_cache(maxsize=1)
def _mahindra_listing() -> str:
    with _browser() as b:
        ctx = b.new_context(user_agent=UA)
        ctx.add_init_script(_CAPTURE)
        page = ctx.new_page()
        try:
            try:
                page.goto(MAHINDRA, wait_until='domcontentloaded', timeout=90000)
            except Exception:  # noqa: BLE001 - a page that never finishes loading still shows the declaration
                pass
            page.wait_for_timeout(6000)
            with contextlib.suppress(Exception):   # the welcome pop-up covers the page
                page.locator('button[aria-label="Close welcome message"]').first.click(timeout=5000)
            page.get_by_role('button', name=re.compile(r'I AM NOT A US PERSON', re.I)).first.click(timeout=20000)
            for _ in range(30):
                page.wait_for_timeout(1000)
                lists = page.evaluate('() => window.__lists')
                if lists:
                    return lists[-1]
        finally:
            ctx.close()
    raise ValueError('the downloads list did not arrive after the declaration')


def mahindra(month: str) -> list[tuple[str, str]]:
    return mahindra_links(json.loads(_mahindra_listing()))


# --- ICICI Prudential: Downloads > Other Scheme Disclosures > Monthly Portfolio Disclosures --------------------------
# The page's own calls (www.icicipruamc.com static/js, read 19 Nov 2026): the category list, then the files list for
# the Monthly Portfolio Disclosures sub-category, 20 a page, newest first. Each month is one zip of a workbook per
# scheme, at www.icicipruamc.com/blob + its url. The service answers JSON only with the header the site's request code
# sends on every call (env: api); without it the gateway answers the site's 404 page, and a call without a JSON Accept
# gets an F5 "Please enable JavaScript" page, which is not worked around. apimf.icicipruamc.com resets connections
# from outside India, so the list is read on a GitHub runner (the Mutual fund portfolios workflow).
ICICI = ('https://www.icicipruamc.com/media-center/downloads?currentTabFilter=Disclosures'
         '&subCatTabFilter=MonthlyPortfolioDisclosures')
ICICI_API = 'https://apimf.icicipruamc.com/nms/v1/downloads/'
ICICI_BLOB = 'https://www.icicipruamc.com/blob'
ICICI_MONTHLY = 'MONTHLY_PORTFOLIO_DISCSLO_DWND'


def _icici_headers() -> dict:
    import uuid
    return {'User-Agent': UA, 'Accept': 'application/json, text/plain, */*', 'Origin': 'https://www.icicipruamc.com',
            'Referer': 'https://www.icicipruamc.com/', 'Content-type': 'application/json', 'env': 'api',
            'requestAPIId': str(uuid.uuid4())}


def _ist_day(ms: int) -> date:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ms / 1000, timezone(timedelta(hours=5, minutes=30))).date()


def icici_links(files: list[dict]) -> list[tuple[str, str]]:
    """(title, address) for each entry of the files list."""
    return [((f.get('title') or {}).get('text') or '', ICICI_BLOB + f['url']) for f in files if f.get('url')]


def icici(month: str, max_pages: int = 10) -> list[tuple[str, str]]:
    s = _session()
    r = s.get(ICICI_API + 'categories', params={'userType': 'Investor'}, headers=_icici_headers(), timeout=TIMEOUT)
    raise_for_status(r)
    cat = sub = None
    for c in (r.json().get('success') or {}).get('data') or []:
        for sc in c.get('subCategory') or []:
            if (sc.get('title') or {}).get('code') == ICICI_MONTHLY:
                cat, sub = c, sc
    if sub is None:
        raise ValueError(f'no {ICICI_MONTHLY} sub-category in the categories list')
    y, m = _ym(month)
    out: list[tuple[str, str]] = []
    for pg in range(1, max_pages + 1):
        r = s.post(ICICI_API + 'files', headers=_icici_headers(), timeout=TIMEOUT,
                   json={'categoryId': sub['id'], 'schemeCategory': '', 'userType': 'Investor', 'fileType': 'All',
                         'page': str(pg), 'size': '20', 'filter': [],
                         'categoryName': (cat.get('title') or {}).get('code')})
        raise_for_status(r)
        data = (r.json().get('success') or {}).get('data') or {}
        files = data.get('files') or []
        out += icici_links(files)
        oldest = min((f.get('applicableMonth') or 0 for f in files), default=0)   # ms: the month-end, IST midnight
        if not data.get('isNext') or not files or (oldest and _ist_day(oldest) < date(y, m, 1)):
            break
    return out


# --- AlphaGrep: Disclosures > Portfolio Disclosure, drawn from its content service (Strapi) ------------------------
# www.alphagrepmf.ai is an Angular page; its script reads cmsweb.alphagrepmf.ai/api/portfolios (each entry: a scheme,
# the accordion it sits in - Monthly - a title such as 'October Report', and the workbook). A workbook per scheme.
# The site and the service are behind the CAMS firewall, which blocks machines outside India; a GitHub runner is
# answered (mf-probe, 19 Nov 2026).
ALPHAGREP = 'https://www.alphagrepmf.ai/disclosures'
ALPHAGREP_CMS = 'https://cmsweb.alphagrepmf.ai'


def alphagrep_links(entries: list[dict]) -> list[tuple[str, str]]:
    """(scheme, accordion, title and file name; address) for each entry of /api/portfolios."""
    out = []
    for e in entries:
        f = e.get('file') or {}
        if not f.get('url'):
            continue
        acc = (e.get('accordian_name') or {}).get('Name') or ''
        text = f"{(e.get('scheme') or {}).get('Name') or ''} {acc} portfolio {e.get('title') or ''} {f.get('name') or ''}"
        out.append((' '.join(text.split()), urljoin(ALPHAGREP_CMS, f['url'])))
    return out


def alphagrep(month: str) -> list[tuple[str, str]]:
    s = _session()
    s.headers.update({'Accept': 'application/json, text/plain, */*', 'Origin': 'https://www.alphagrepmf.ai',
                      'Referer': 'https://www.alphagrepmf.ai/'})
    entries: list[dict] = []
    for pg in range(1, 20):
        r = s.get(f'{ALPHAGREP_CMS}/api/portfolios', timeout=TIMEOUT,
                  params={'populate': '*', 'pagination[pageSize]': 100, 'pagination[page]': pg})
        raise_for_status(r)
        d = r.json()
        entries += d.get('data') or []
        if pg >= (((d.get('meta') or {}).get('pagination') or {}).get('pageCount') or 1):
            break
    return alphagrep_links(entries)


# --- Kotak Mahindra: Information > Forms and Downloads > Portfolios > Consolidated & Fortnightly Portfolio ----------
# A plain request to kotakmf.com is sent to a Radware bot check (validate.perfdrive.com); an ordinary browser visit
# from a GitHub runner was served the page itself, no check (probe run 44663322178, 20 Nov 2026). So the page is
# opened as a person would, the Portfolios list set to 'Consolidated & Fortnightly Portfolio', and the file list read
# from what the page then shows and fetches. A visit sent to the bot check is reported, never solved.
KOTAK = 'https://www.kotakmf.com/Information/forms-and-downloads'
KOTAK_PICK = 'Consolidated & Fortnightly Portfolio'
_FILE_IN_JSON = re.compile(r'"([^"\s<>]+\.(?:xlsx|xls|xlsm|zip))"', re.I)


def kotak_links(anchors: list, bodies: list[str]) -> list[tuple[str, str]]:
    """(text, address) from the page's links and from file addresses in the JSON answers it fetched (with the
    preceding 300 characters of the answer as text, where a title sits)."""
    out = [((t or '').strip(), h) for t, h in anchors if h]
    for body in bodies:
        b = body.replace('\\/', '/')
        for m in _FILE_IN_JSON.finditer(b):
            out.append((b[max(0, m.start() - 300):m.start()], urljoin('https://www.kotakmf.com/', m.group(1))))
    return out


def kotak(month: str) -> list[tuple[str, str]]:
    bodies: list[str] = []

    def keep(r):
        if 'kotakmf.com' in r.url and 'json' in (r.headers.get('content-type') or ''):
            with contextlib.suppress(Exception):
                bodies.append(r.text())

    with _browser() as b:
        ctx = b.new_context(user_agent=UA)
        page = ctx.new_page()
        page.on('response', keep)
        try:
            with contextlib.suppress(Exception):   # a page that never goes idle still has its lists
                page.goto(KOTAK, wait_until='networkidle', timeout=90000)
            page.wait_for_timeout(4000)
            for step in ('load', 'pick'):
                if 'perfdrive' in page.url:
                    raise RuntimeError(f'sent to the Radware bot check at {step} (validate.perfdrive.com); not worked around')
                if step == 'load':
                    page.locator('select[aria-label="Portfolios"]').first.select_option(label=KOTAK_PICK, timeout=60000)
                    page.wait_for_timeout(8000)
            anchors = page.evaluate("() => [...document.querySelectorAll('a')].map(a => [a.innerText || a.title || '', a.href])")
        finally:
            ctx.close()
    return kotak_links(anchors, bodies)
