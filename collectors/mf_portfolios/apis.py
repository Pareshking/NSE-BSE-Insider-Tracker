"""Fund houses whose disclosure page draws its file list from a JSON call rather than links: the same call the page
makes, read directly. Each function takes a month ('2026-10') and returns (text, href) links, the input
`find.candidates` reads for any other page, so the month and file rules stay the same for every house.
Each was found by watching the page's own network requests in a browser (19 Nov 2026)."""
from __future__ import annotations

import calendar
import re

from collectors.mf_portfolios.find import UA


def _session(referer: str):
    import requests
    s = requests.Session()
    s.headers.update({'User-Agent': UA, 'Referer': referer, 'Origin': referer.split('/', 3)[0] + '//' + referer.split('/')[2],
                      'Accept': 'application/json, text/plain, */*'})
    return s


def _ym(month: str) -> tuple[int, int]:
    y, m = (int(x) for x in month.split('-'))
    return y, m


def hdfc(month: str) -> list[tuple[str, str]]:
    """www.hdfcfund.com/statutory-disclosure/portfolio/monthly-portfolio: one workbook per scheme."""
    y, m = _ym(month)
    s = _session('https://www.hdfcfund.com/statutory-disclosure/portfolio/monthly-portfolio')
    r = s.post('https://cms.hdfcfund.com/en/hdfc/api/v2/disclosures/monthfortportfolio',
               files={'year': (None, str(y)), 'type': (None, 'monthly'), 'month': (None, str(m))}, timeout=60)
    r.raise_for_status()
    files = (r.json().get('data') or {}).get('files') or []
    return [(f.get('title') or '', (f.get('file') or {}).get('url') or '') for f in files]


def axis(month: str) -> list[tuple[str, str]]:
    """www.axismf.com/statutory-disclosures, 8. Portfolios, Monthly Scheme Portfolios, scheme 'Consolidated'.
    The page first asks /cms/token for the bearer token it sends with the list call."""
    y, m = _ym(month)
    s = _session('https://www.axismf.com/statutory-disclosures')
    t = s.post('https://www.axismf.com/cms/token', json={}, timeout=60)
    t.raise_for_status()
    r = s.post('https://www.axismf.com/cms/get-scheme-documents', timeout=60,
               headers={'Authorization': t.json()['data']['token']},
               json={'sdType': 'yearMonthSchemeDocs', 'sdID': 'sdMonthSchemePortfolio', 'year': str(y),
                     'month': calendar.month_name[m], 'schemeCode': 'Consolidated'})
    r.raise_for_status()
    docs = (r.json().get('data') or {}).get('documentList') or []
    return [(d.get('documentName') or '', d.get('docuementURL') or d.get('documentURL') or '') for d in docs]


def uti(month: str) -> list[tuple[str, str]]:
    """www.utimf.com/downloads/consolidate-all-portfolio-disclosure: year and month, then 'Get Portfolio'."""
    y, m = _ym(month)
    s = _session('https://www.utimf.com/downloads/consolidate-all-portfolio-disclosure')
    r = s.get('https://www.utimf.com/api/get-consolidate-portfolio-disclosure',
              params={'year': y, 'month': calendar.month_name[m]}, timeout=60)
    r.raise_for_status()
    return [(d.get('name') or '', d.get('url') or d.get('doc') or '') for d in (r.json().get('rows') or [])]


def mirae(month: str, page_size: int = 500) -> list[tuple[str, str]]:
    """www.miraeassetmf.co.in/downloads/portfolio, Monthly Portfolio tab: one workbook per scheme, newest first,
    read page by page until the month is passed (titles name the month-end) or the list ends."""
    y, m = _ym(month)
    s = _session('https://www.miraeassetmf.co.in/downloads/portfolio')
    out: list[tuple[str, str]] = []
    for pg in range(1, 50):
        r = s.post('https://www.miraeassetmf.co.in/AjaxService/GetDownloadsData', timeout=60,
                   json={'request': {'modulename': 'portfolio_tab1', 'pgno': pg, 'pgsize': page_size}})
        r.raise_for_status()
        rows = r.json().get('Data') or []
        out += [(d.get('Title') or '', 'https://www.miraeassetmf.co.in' + (d.get('URL') or '')) for d in rows]
        if len(rows) < page_size or _before(rows[-1].get('Title') or '', y, m):
            break
    return out


def _before(title: str, y: int, m: int) -> bool:
    """True when a title ('Portfolio Details as on 30th September 2026 for ...') names a month-end before y-m."""
    names = {n.lower(): i for i, n in enumerate(calendar.month_name) if n}
    hit = re.search(r'(' + '|'.join(names) + r')\s*,?\s*(\d{4})', title.lower())
    return bool(hit) and (int(hit.group(2)), names[hit.group(1)]) < (y, m)
