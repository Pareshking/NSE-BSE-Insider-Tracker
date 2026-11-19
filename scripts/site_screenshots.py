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
import time
from pathlib import Path

from playwright.async_api import async_playwright

PAGES = [('', 'today'), ('insiders', 'insiders'), ('deals', 'deals'), ('stakes', 'stakes'), ('situations', 'situations'),
         ('results', 'results'), ('calendar', 'calendar'), ('company?symbol=HCLTECH', 'company-hcltech'), ('company?symbol=IIFL', 'company-iifl'), ('data-health', 'data-health'),
         ('watchlist?watch=HAVELLS,JSL,HCLTECH,TITAN', 'watchlist'), ('raises', 'raises'), ('risks', 'risks'),
         ('investors', 'investors'), ('track-record', 'evidence'), ('filings-all', 'filings'), ('data', 'data'), ('market', 'old-market-address'),
         ('proto-today', 'old-proto-address'),
         # the shared date control (ui/dates.py): a preset, a Custom range and a past day, each from the address
         ('insiders?range=1m', 'insiders-1m'), ('deals?from=2026-10-01&to=2026-10-31', 'deals-custom'),
         ('today?day=2026-11-10', 'today-past-day'), ('calendar?range=3m', 'calendar-3m'),
         ('entity?id=sbi-mutual-fund', 'entity-sbi-mf'), ('ownership', 'holders'), ('investor-flows', 'investor-flows'),
         ('ownership', 'holders-90d')]
# Long pages drawn taller at phone width, so the screenshot reaches their charts (the entity page's holdings).
TALL = {'entity-sbi-mf': 7000, 'holders-90d': 4000}
# A period button pressed before the screenshot, where the default period is often empty.
CLICK = {'holders-90d': '90 days'}
# Tall viewports: Streamlit scrolls inside its own container, so a "full page"
# screenshot would stop at the first screen.
WIDTHS = {'desktop': (1440, 2600), 'phone': (390, 2200)}
# Streamlit marks the app "notRunning" once a script run has finished.
RUN_FINISHED = "() => document.querySelector('[data-testid=\"stApp\"]')?.dataset.testScriptState === 'notRunning'"
ERROR_MARKERS = ('Traceback (most recent call last)', 'This app has encountered an error', 'Error running app')


async def main(base: str, out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    problems, timings = [], []
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        for label, (w, h) in WIDTHS.items():
            page = await browser.new_page(viewport={'width': w, 'height': h})
            for path, name in PAGES:
                await page.set_viewport_size({'width': w, 'height': TALL.get(name, h) if label == 'phone' else h})
                await page.goto(f'{base.rstrip("/")}/{path}', wait_until='networkidle', timeout=120_000)
                # Streamlit draws after the first paint; the first page also
                # loads every table from R2. Wait for the page head itself.
                t0 = time.monotonic()
                try:
                    await page.wait_for_selector('.head h1', timeout=90_000)
                except Exception:  # noqa: BLE001 -- recorded as a problem below
                    problems.append({'page': name, 'width': label, 'error': 'page never rendered (no heading in 90 s)'})
                # Then wait for the script run to finish: tables lower down are
                # computed after the head is drawn.
                try:
                    await page.wait_for_function(RUN_FINISHED, timeout=90_000)
                    await page.wait_for_timeout(1500)
                except Exception:  # noqa: BLE001
                    problems.append({'page': name, 'width': label, 'error': 'page still running after 90 s'})
                if name in CLICK:
                    try:
                        await page.get_by_role('button', name=CLICK[name], exact=True).first.click()
                        await page.wait_for_timeout(1000)
                        await page.wait_for_function(RUN_FINISHED, timeout=90_000)
                        await page.wait_for_timeout(1500)
                    except Exception as e:  # noqa: BLE001
                        problems.append({'page': name, 'width': label, 'error': f'could not press {CLICK[name]!r}: {e}'})
                timings.append({'page': name, 'width': label, 'seconds': round(time.monotonic() - t0, 1)})
                await page.screenshot(path=str(out / f'{name}-{label}.png'), full_page=(label == 'desktop'))
                text = await page.inner_text('body')
                hit = next((m for m in ERROR_MARKERS if m in text), None)
                if hit:
                    problems.append({'page': name, 'width': label, 'error': hit})
        await browser.close()
    (out / 'problems.json').write_text(json.dumps(problems, indent=2))
    (out / 'timings.json').write_text(json.dumps(timings, indent=2))
    for t in timings:
        print(f'  {t["page"]} ({t["width"]}): ready in {t["seconds"]} s')
    for pr in problems:
        print(f'  ERROR on {pr["page"]} ({pr["width"]}): {pr["error"]}')
    print(f'  {len(PAGES) * len(WIDTHS)} screenshots, {len(problems)} pages with errors')
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main(sys.argv[1], Path(sys.argv[2]))))
