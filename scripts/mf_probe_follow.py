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

    # ICICI: the site first (cookies a browser would carry), then the page's own calls.
    call('icici site downloads page', 'GET',
         SITE + '/media-center/downloads?currentTabFilter=Disclosures&subCatTabFilter=MonthlyPortfolioDisclosures')
    cats = call('icici categories', 'GET', f'{API}/nms/v1/downloads/categories?userType=Investor', headers=api_h)
    call('icici categories plain', 'GET', f'{API}/nms/v1/downloads/categories?userType=Investor')
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
                 headers=api_h, json=body)
        try:
            files = ((r.json().get('success') or {}).get('data') or []) if r is not None else []
        except ValueError:
            files = []
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

    (d / 'INDEX.txt').write_text('\n'.join(index) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else 'probe'))
