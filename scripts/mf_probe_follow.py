"""Follow-up calls for the fund house probe (.github/workflows/mf-probe.yml), run on a GitHub runner by hand.

Saves every answer byte for byte into OUT (the workflow uploads it as an artifact), with a one-line index, so we can
read what a house's service really answers a runner. Nothing here solves or works around a CAPTCHA or bot check:
an answer that is one is saved and read, and the house stays not collected.

ICICI Prudential: the calls its own Downloads page makes (www.icicipruamc.com static/js, 19 Nov 2026):
    GET  https://apimf.icicipruamc.com/nms/v1/downloads/categories?userType=Investor
    POST https://apimf.icicipruamc.com/nms/v1/downloads/files
         {categoryId, schemeCategory, userType: 'Investor', fileType: 'All', page, size, filter: [], categoryName}
    files at https://www.icicipruamc.com/blob + each file's url
AlphaGrep: the disclosures page and the first portfolio files it links.

    python scripts/mf_probe_follow.py OUT
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36'
API = 'https://apimf.icicipruamc.com'
SITE = 'https://www.icicipruamc.com'


def main(out: str) -> int:
    import requests
    d = Path(out)
    d.mkdir(parents=True, exist_ok=True)
    index = []
    n = [0]

    def save(label: str, r) -> None:
        n[0] += 1
        name = f'{n[0]:02d}-{re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:60]}'
        (d / f'{name}.body').write_bytes(r.content)
        (d / f'{name}.headers').write_text(f'{r.request.method} {r.url}\nHTTP {r.status_code}\n' +
                                           ''.join(f'{k}: {v}\n' for k, v in r.headers.items()))
        line = f'{name} | {r.request.method} {r.url} | HTTP {r.status_code} | {len(r.content)} bytes | {r.headers.get("Content-Type")}'
        index.append(line)
        print(line)

    def call(label, method, url, **kw):
        try:
            r = s.request(method, url, timeout=60, **kw)
        except Exception as exc:  # noqa: BLE001 - a refused call is a finding, written down
            index.append(f'{label} | {method} {url} | {type(exc).__name__}: {exc}')
            print(index[-1])
            return None
        save(label, r)
        return r

    s = requests.Session()
    s.headers.update({'User-Agent': UA, 'Accept-Language': 'en-IN,en;q=0.9'})
    api_h = {'Accept': 'application/json, text/plain, */*', 'Origin': SITE, 'Referer': SITE + '/',
             'Content-type': 'application/json'}
    # What the site's own request code adds to every API call (index.*.js: headers.env = REACT_APP_ENV, which is
    # 'api'; a fresh requestAPIId per call). Without env the gateway answers the site's 404 page.
    import uuid
    full_h = {**api_h, 'env': 'api'}

    # ICICI: the site first (cookies a browser would carry), then the page's own calls.
    call('icici site downloads page', 'GET',
         SITE + '/media-center/downloads?currentTabFilter=Disclosures&subCatTabFilter=MonthlyPortfolioDisclosures')
    call('icici categories json-accept', 'GET', f'{API}/nms/v1/downloads/categories?userType=Investor', headers=api_h)
    cats = call('icici categories site-headers', 'GET', f'{API}/nms/v1/downloads/categories?userType=Investor',
                headers={**full_h, 'requestAPIId': str(uuid.uuid4())})
    picks = []
    if cats is not None:
        try:
            data = cats.json()
        except ValueError:
            data = None
        for cat in ((data or {}).get('success') or {}).get('data') or []:
            for sub in cat.get('subCategory') or []:
                code = str((sub.get('title') or {}).get('code') or '') + ' ' + str((sub.get('title') or {}).get('text') or '')
                if re.search(r'portfolio', code, re.I):
                    picks.append((cat, sub))
        (d / 'icici-portfolio-subcategories.json').write_text(json.dumps(
            [{'category': (c.get('title') or {}), 'category_id': c.get('id'), 'sub': (s_.get('title') or {}),
              'sub_id': s_.get('id')} for c, s_ in picks], indent=1))
    first_file = None
    for cat, sub in picks[:6]:
        body = {'categoryId': str(sub.get('id') or ''), 'schemeCategory': '', 'userType': 'Investor', 'fileType': 'All',
                'page': '1', 'size': '20', 'filter': [], 'categoryName': (cat.get('title') or {}).get('code')}
        r = call(f'icici files {(sub.get("title") or {}).get("code")}', 'POST', f'{API}/nms/v1/downloads/files',
                 headers={**full_h, 'requestAPIId': str(uuid.uuid4())}, json=body)
        try:
            files = ((r.json().get('success') or {}).get('data') or []) if r is not None else []
        except ValueError:
            files = []
        if isinstance(files, dict):   # {'files': [...], 'isNext': ...}
            files = files.get('files') or []
        for f in files if isinstance(files, list) else []:
            if f.get('url') and first_file is None and re.search(r'monthly', json.dumps(f), re.I):
                first_file = f
    if first_file is not None:
        call('icici first monthly file', 'GET', SITE + '/blob' + first_file['url'])

    # AlphaGrep: the page, then the first portfolio files it links.
    page = call('alphagrep disclosures', 'GET', 'https://www.alphagrepmf.ai/disclosures')
    if page is not None and page.status_code == 200:
        links = sorted(set(re.findall(r'https?://[^"\'\s<>]+?\.(?:xlsx|xls|pdf|zip)', page.text, re.I) +
                           ['https://www.alphagrepmf.ai' + p for p in
                            re.findall(r'["\'](/[^"\'\s<>]+?\.(?:xlsx|xls|pdf|zip))["\']', page.text, re.I)]))
        (d / 'alphagrep-links.txt').write_text('\n'.join(links))
        for u in [u for u in links if re.search(r'portfolio', u, re.I)][:3]:
            call('alphagrep file', 'GET', u)

    # AlphaGrep's page is an Angular shell: keep its main script and the addresses in it (its list call is there).
    if page is not None and page.status_code == 200:
        for js in re.findall(r'src="(main\.[0-9a-f]+\.js)"', page.text)[:1]:
            r = call('alphagrep main js', 'GET', 'https://www.alphagrepmf.ai/' + js)
            if r is not None and r.status_code == 200:
                (d / 'alphagrep-js-addresses.txt').write_text('\n'.join(sorted(set(
                    re.findall(r'["\'`](https?://[^"\'`\s]+|/?api/[^"\'`\s]+)', r.text)))))
    # Its content service (Strapi), named in that script: the document library and the archive the page lists.
    ag_h = {'Accept': 'application/json, text/plain, */*', 'Origin': 'https://www.alphagrepmf.ai',
            'Referer': 'https://www.alphagrepmf.ai/'}
    for path in ('document-libraries', 'archive-documents'):
        for q in ('populate=*&pagination[pageSize]=100', 'populate=*&pagination[pageSize]=100&pagination[page]=2'):
            call(f'alphagrep cms {path}', 'GET', f'https://cmsweb.alphagrepmf.ai/api/{path}?{q}', headers=ag_h)
    # The Portfolio Disclosure tab reads /api/portfolios (by accordion); keep the list and its first workbooks.
    r = call('alphagrep cms portfolios', 'GET',
             'https://cmsweb.alphagrepmf.ai/api/portfolios?populate=*&pagination[pageSize]=100', headers=ag_h)
    call('alphagrep cms portfolios accordions', 'GET',
         'https://cmsweb.alphagrepmf.ai/api/portfolios?populate=accordian_name&pagination[pageSize]=100', headers=ag_h)
    try:
        ups = re.findall(r'"url":"(/uploads/[^"]+)"', r.text) if r is not None else []
    except Exception:  # noqa: BLE001
        ups = []
    for u in [u for u in ups if re.search(r'month|portfolio', u, re.I)][:2]:
        call('alphagrep portfolio file', 'GET', 'https://cmsweb.alphagrepmf.ai' + u, headers=ag_h)

    # BSE: ICICI Prudential's filings among the announcements BSE disseminated around the 10th (portfolio
    # disclosures are filed as PDFs against its listed ETFs). Keeps the matching rows and the first PDFs.
    # The nightly collector's own BSE client (plain requests, then an XHR from inside a bseindia.com page if refused).
    from datetime import date
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from collectors.bse.client import BSEClient
    bse = BSEClient(raw=None, pace=(1.0, 2.0))
    hits = []
    for day in (date(2026, 11, 6), date(2026, 11, 7), date(2026, 11, 9), date(2026, 11, 10)):
        pg = 0
        for pg in range(1, 60):
            try:
                rows, total = bse.announcements(day, pg)
            except Exception as exc:  # noqa: BLE001
                index.append(f'bse {day} page {pg} | {type(exc).__name__}: {exc}')
                break
            hits += [x for x in rows if re.search(r'icici|monthly portfolio',
                                                  str(x.get('SLONGNAME')) + str(x.get('NEWSSUB')), re.I)]
            if len(rows) < 50:
                break
        index.append(f'bse {day}: {pg} pages ({bse.via}), ICICI Prudential rows so far {len(hits)}')
    bse.close()
    (d / 'bse-icici-rows.json').write_text(json.dumps(hits, indent=1, default=str))
    port = sorted((x for x in hits if re.search(r'portfolio', str(x.get('NEWSSUB')) + str(x.get('HEADLINE')), re.I)),
                  key=lambda x: 'icici' not in str(x.get('SLONGNAME')).lower())
    for x in port[:3]:
        if x.get('ATTACHMENTNAME'):
            call(f'bse icici pdf {x.get("SCRIP_CD")}', 'GET',
                 'https://www.bseindia.com/xml-data/corpfiling/AttachLive/' + x['ATTACHMENTNAME'],
                 headers={'Referer': 'https://www.bseindia.com/'})

    (d / 'INDEX.txt').write_text('\n'.join(index) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else 'probe'))
