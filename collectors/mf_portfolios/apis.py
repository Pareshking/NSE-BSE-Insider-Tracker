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


# NPS pension fund managers (their portfolio pages, as NPS Trust lists them at npstrust.org.in/scheme-portfolio).

def nps_sbi(month: str) -> list[tuple[str, str]]:
    """www.sbipensionfunds.co.in/disclosures/portfolio-details: the list is the page's own data file (Gatsby
    page-data.json), each entry a name ('Portfolio Details October 2026') and the workbook's upload address."""
    s = _session('https://www.sbipensionfunds.co.in/disclosures/portfolio-details/')
    r = s.get('https://www.sbipensionfunds.co.in/page-data/disclosures/portfolio-details/page-data.json', timeout=60)
    r.raise_for_status()
    return [(name, 'https://www.sbipensionfunds.co.in' + url) for name, url in re.findall(
        r'"name":"(Portfolio Details[^"]*)"[^{}]*?"pdf":\{"data":\{"id":\d+,"attributes":\{[^{}]*?"url":"(/uploads/[^"]+)"', r.text)]


def nps_icici(month: str) -> list[tuple[str, str]]:
    """www.icicipension.in/public_disclosure/portfolio_details: the page asks api.icicipension.in for the month
    ('oct', 2026) and gets one workbook (a signed download address, good for 15 minutes)."""
    y, m = _ym(month)
    s = _session('https://www.icicipension.in/public_disclosure/portfolio_details')
    r = s.get(f'https://api.icicipension.in/get_check/portfolio/{calendar.month_abbr[m].lower()}/{y}', timeout=60)
    r.raise_for_status()
    out = []
    for d in r.json().get('data') or []:
        a = d.get('attributes') or {}
        f = ((a.get('Scheme_Details') or {}).get('data') or {}).get('attributes') or {}
        if f.get('url'):
            out.append((f"{a.get('internal_identifier') or ''} {f.get('name') or ''}", f['url']))
    return out


def nps_axis(month: str) -> list[tuple[str, str]]:
    """www.axispensionfund.com/public-disclosures/portfolio-details: the page asks the site's WordPress list for the
    month and year; each entry's acf.pdf_report is the month's workbook."""
    y, m = _ym(month)
    s = _session('https://www.axispensionfund.com/public-disclosures/portfolio-details')
    r = s.get('https://www.axispensionfund.com/wordpress/wp-json/wp/v2/portfolio_reports/', params={'month': m, 'year': y},
              timeout=60)
    r.raise_for_status()
    out = []
    for d in r.json() or []:
        a = d.get('acf') or {}
        if str(a.get('year')) == str(y) and str(a.get('month')).lstrip('0') == str(m) and a.get('pdf_report'):
            out.append((f'{calendar.month_name[m]} {y} portfolio', a['pdf_report']))
    return out
