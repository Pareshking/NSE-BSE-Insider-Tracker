"""Find a fund house's month-end portfolio file(s) for a month on its disclosure page.

A page is read either as plain HTML (requests) or rendered in a headless browser (Playwright) when the links are
drawn by script. Every link (text and address) is scored against the month: its name or address must name the month
(October 2026 / Oct-26 / 31102026 / 2026-10-31 ...) and read as a monthly portfolio, not a fortnightly, debt-only,
risk-o-meter, AAUM or factsheet file. A fund house that files one workbook for all schemes gives one file
(`mode='one'`); one that files a workbook per scheme gives all of them (`mode='all'`).
Nothing is guessed: no candidate means "not found", reported with the page's link count.
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from urllib.parse import unquote, urljoin

FILE = re.compile(r'\.(xlsx|xls|xlsm|zip)(\?|#|$)', re.I)
EXCLUDE = re.compile(r'fortnight|debt|risk|a?aum|factsheet|fact-sheet|half|proxy|voting|commission|transaction|dashboard|'
                     r'riskometer|ter\b|expense|nav\b|dividend|idcw|brsr|esg-score|stress|liquidity|scheme-differentiation|'
                     r'stewardship|investor-complaint|unclaimed|kim|sid\b|top-?10|sector', re.I)
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36'


@dataclass
class House:
    key: str                     # short id, used in storage paths
    name: str                    # as AMFI lists it
    page: str                    # the disclosure page (from AMFI's Portfolio Disclosure list)
    render: bool = False         # links drawn by script: read the page in a browser
    mode: str = 'one'            # 'one' workbook for all schemes, or 'all' (a workbook per scheme)
    must: str | None = None      # a regex a candidate must also match (when the page lists other monthly files)
    exclude: str | None = None   # a regex that rules a candidate out, on top of EXCLUDE
    click: list = field(default_factory=list)   # texts to click (tabs) before reading links, in a browser


def month_tokens(month: str) -> re.Pattern:
    """A regex that matches a reference to the month-end of `month` ('2026-10')."""
    y, m = (int(x) for x in month.split('-'))
    full, short = calendar.month_name[m].lower(), calendar.month_abbr[m].lower()
    last = calendar.monthrange(y, m)[1]
    yy = f'{y % 100:02d}'
    parts = [
        rf'{full}[^a-z0-9]{{0,3}}(?:{y}|{yy}\b)', rf'\b{short}[^a-z0-9]{{0,3}}(?:{y}|{yy}\b)',
        rf'{full}(?:{y}|{yy}\b)', rf'{short}(?:{y}|{yy}\b)',
        rf'(?:{y}|{yy})[^a-z0-9]{{0,3}}{full}', rf'(?:{y})[^a-z0-9]{{0,3}}{short}\b',
        rf'{last}(?:st|nd|rd|th)?[^a-z0-9]{{0,3}}{full}[^a-z0-9]{{0,3}},?[^a-z0-9]{{0,3}}{y}',
        rf'{last}[^0-9]?{m:02d}[^0-9]?{y}', rf'{y}[^0-9]?{m:02d}[^0-9]?{last}', rf'{last}{m:02d}{yy}\b',
        rf'{full}[^a-z0-9]{{0,3}}{last},?[^a-z0-9]{{0,3}}{y}',
    ]
    return re.compile('|'.join(f'(?:{p})' for p in parts), re.I)


def candidates(links: list[tuple[str, str]], month: str, house: House) -> list[str]:
    """Addresses of the month's portfolio file(s) among (text, href) links, best first."""
    tok = month_tokens(month)
    must = re.compile(house.must, re.I) if house.must else None
    excl = re.compile(house.exclude, re.I) if house.exclude else None
    scored = []
    for text, href in links:
        if not href or not FILE.search(href):
            continue
        hay = f'{text} {unquote(href)}'.lower()
        base = f'{text} {unquote(href).split("?")[0].rsplit("/", 1)[-1]}'.lower()   # folder names say nothing of the file
        if not tok.search(hay) or EXCLUDE.search(base) or (excl and excl.search(base)) or (must and not must.search(hay)):
            continue
        score = (2 if 'monthly' in hay else 0) + (2 if re.search(r'all[ -_]?schemes?|consolidat|combined', hay) else 0) \
            + (1 if 'portfolio' in hay else 0)
        scored.append((score, href))
    seen, out = set(), []
    for _, h in sorted(scored, key=lambda x: -x[0]):
        if h not in seen:
            seen.add(h)
            out.append(h)
    if house.mode == 'one':
        return out[:1]
    return out


def links_plain(url: str, session=None, timeout: int = 60) -> list[tuple[str, str]]:
    import requests
    from bs4 import BeautifulSoup
    s = session or requests.Session()
    r = s.get(url, headers={'User-Agent': UA}, timeout=timeout)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, 'lxml')
    out = [(a.get_text(' ', strip=True), urljoin(r.url, a['href'])) for a in soup.find_all('a', href=True)]
    # Links in script data (JSON) rather than anchors
    out += [('', urljoin(r.url, m)) for m in re.findall(r'["\']([^"\'\s<>]+\.(?:xlsx|xls|xlsm|zip))["\']', r.text, re.I)]
    return out


def links_rendered(url: str, browser, click: list | None = None, wait_ms: int = 5000) -> list[tuple[str, str]]:
    ctx = browser.new_context(user_agent=UA, accept_downloads=False)
    page = ctx.new_page()
    seen: list[tuple[str, str]] = []
    page.on('request', lambda r: seen.append(('', r.url)) if FILE.search(r.url) else None)
    try:
        try:
            page.goto(url, wait_until='networkidle', timeout=90000)
        except Exception:  # noqa: BLE001 - a page that never goes idle still has its links
            pass
        page.wait_for_timeout(wait_ms)
        for t in click or []:
            try:
                page.get_by_text(t, exact=False).first.click(timeout=5000)
                page.wait_for_timeout(2500)
            except Exception:  # noqa: BLE001
                pass
        anchors = page.evaluate("() => [...document.querySelectorAll('a')].map(a => [a.innerText || a.title || '', a.href])")
        html = page.content()
    finally:
        ctx.close()
    out = [(t.strip(), h) for t, h in anchors if h]
    out += [('', urljoin(url, m)) for m in re.findall(r'["\']([^"\'\s<>]+\.(?:xlsx|xls|xlsm|zip))["\']', html, re.I)]
    return out + seen
