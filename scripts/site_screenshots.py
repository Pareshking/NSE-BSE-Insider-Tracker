"""Screenshot every page of a running site and fail on a page error.

    python scripts/site_screenshots.py http://localhost:8501 OUT_DIR

Used by .github/workflows/site-preview.yml to check the site on the real R2
data before it goes live: each page at desktop (1440 px) and phone (390 px)
width. A page that shows Streamlit's error box or a traceback fails the run,
so a broken page is caught even when nobody looks at the pictures.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright

PAGES = [('', 'today'), ('screener', 'screener'), ('insider-trades', 'insider-trades'), ('deals', 'deals'),
         ('capital-raises', 'capital-raises'), ('track-record', 'track-record'), ('data', 'data'),
         ('company?symbol=HCLTECH', 'company-hcltech'), ('entity', 'entity')]
WIDTHS = {'desktop': (1440, 1000), 'phone': (390, 844)}
ERROR_MARKERS = ('Traceback (most recent call last)', 'This app has encountered an error', 'Error running app')


async def main(base: str, out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    problems = []
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        for label, (w, h) in WIDTHS.items():
            page = await browser.new_page(viewport={'width': w, 'height': h})
            for path, name in PAGES:
                await page.goto(f'{base.rstrip("/")}/{path}', wait_until='networkidle', timeout=120_000)
                # Streamlit draws after the first paint; the first page also
                # loads every table from R2. Wait for the page head itself.
                try:
                    await page.wait_for_selector('.head h1', timeout=90_000)
                    await page.wait_for_timeout(2500)
                except Exception:  # noqa: BLE001 -- recorded as a problem below
                    problems.append({'page': name, 'width': label, 'error': 'page never rendered (no heading in 90 s)'})
                await page.screenshot(path=str(out / f'{name}-{label}.png'), full_page=(label == 'desktop'))
                text = await page.inner_text('body')
                hit = next((m for m in ERROR_MARKERS if m in text), None)
                if hit:
                    problems.append({'page': name, 'width': label, 'error': hit})
        await browser.close()
    (out / 'problems.json').write_text(json.dumps(problems, indent=2))
    for pr in problems:
        print(f'  ERROR on {pr["page"]} ({pr["width"]}): {pr["error"]}')
    print(f'  {len(PAGES) * len(WIDTHS)} screenshots, {len(problems)} pages with errors')
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main(sys.argv[1], Path(sys.argv[2]))))
