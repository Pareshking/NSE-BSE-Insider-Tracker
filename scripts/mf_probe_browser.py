"""Browser probe for the fund house probe (.github/workflows/mf-probe.yml), run on a GitHub runner by hand.

Opens each address in an ordinary headless Chromium visit (Playwright, the collector's own browser and user agent: a
normal page load, as a person's would be) and saves what came back: the page's HTTP status, the server that answered,
the title, how many links it drew and how many name a spreadsheet, the rendered HTML and a screenshot, plus every JSON
answer the page itself fetched. Nothing is clicked through, solved or disguised: no CAPTCHA, no stealth settings, no
changed fingerprint. A page that answers with a challenge is recorded as one and its house stays not collected.

    python scripts/mf_probe_browser.py OUT URL [URL ...]
    a URL may carry what a visitor picks after the page loads: 'URL|select=<select aria-label>=<option>|click=<text>'
    (spaces in an action as %20)
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from collectors.mf_portfolios.find import FILE, UA, close_browser, refused_hint, shared_browser  # noqa: E402

CHALLENGE = re.compile(r'just a moment|attention required|captcha|perfdrive|access denied|request unsuccessful|'
                       r'are you a robot|verify you are human|enable javascript and cookies', re.I)


def visit(browser, url: str, d: Path, n: int, actions: list | None = None) -> dict:
    actions = actions or []
    ctx = browser.new_context(user_agent=UA)
    page = ctx.new_page()
    first, js = [], []

    def on_response(r):
        if not first and r.request.resource_type == 'document':
            first.append(r)
        ct = (r.headers.get('content-type') or '')
        if 'json' in ct and len(js) < 40:
            try:
                js.append({'url': r.url, 'status': r.status, 'body': r.text()[:200000]})
            except Exception:  # noqa: BLE001 - a body already gone
                js.append({'url': r.url, 'status': r.status, 'body': None})
    page.on('response', on_response)
    err = None
    try:
        page.goto(url, wait_until='networkidle', timeout=90000)
    except Exception as exc:  # noqa: BLE001
        err = f'{type(exc).__name__}: {str(exc)[:200]}'
    try:
        page.wait_for_timeout(5000)
        for act in actions:   # what a visitor would pick on the page: 'select=<aria-label>=<option label>'
            kind, _, rest = act.replace('%20', ' ').partition('=')
            try:
                if kind == 'select':
                    aria, _, label = rest.partition('=')
                    page.locator(f'select[aria-label="{aria}"]').first.select_option(label=label, timeout=20000)
                elif kind == 'click':
                    page.get_by_text(rest, exact=False).first.click(timeout=20000)
                page.wait_for_timeout(8000)
            except Exception as exc:  # noqa: BLE001
                err = (err or '') + f' | {act}: {type(exc).__name__}: {str(exc)[:160]}'
        html = page.content()
        links = page.evaluate("() => [...document.querySelectorAll('a')].map(a => a.href).filter(Boolean)")
        page.screenshot(path=str(d / f'{n:02d}.png'), full_page=False)
    except Exception as exc:  # noqa: BLE001
        html, links, err = '', [], err or f'{type(exc).__name__}: {str(exc)[:200]}'
    finally:
        ctx.close()
    (d / f'{n:02d}.html').write_text(html)
    (d / f'{n:02d}.json').write_text(json.dumps(js, indent=1))
    status = first[0].status if first else None
    server = first[0].headers.get('server') if first else None
    return {'url': url, 'actions': actions, 'status': status, 'hint': refused_hint(server, html), 'links': len(links),
            'file_links': sum(bool(FILE.search(h)) for h in links), 'json_answers': len(js),
            'challenge': bool(CHALLENGE.search(html[:50000])), 'error': err}


def main(out: str, urls: list[str]) -> int:
    d = Path(out)
    d.mkdir(parents=True, exist_ok=True)
    rows = []
    try:
        b = shared_browser()
        for i, spec in enumerate(urls, 1):   # URL, or URL|action|action ...
            u, *acts = spec.split('|')
            rows.append(visit(b, u, d, i, acts))
            print(json.dumps(rows[-1]))
    finally:
        close_browser()
    (d / 'index.json').write_text(json.dumps(rows, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1], sys.argv[2:]))
