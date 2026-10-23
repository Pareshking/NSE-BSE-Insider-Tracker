import asyncio, sys
from pathlib import Path
from playwright.async_api import async_playwright
S = Path(__file__).resolve().parent
import os, tempfile
OUT = S.parent; HTML = Path(tempfile.gettempdir()) / 'design_v3_html'
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=os.environ.get('PW_CHROMIUM') or None, args=['--no-sandbox'])
        for f in sorted(HTML.glob('*.html')):
            phone = 'phone' in f.name
            pg = await b.new_page(viewport={'width': 390 if phone else 1440, 'height': 900}, device_scale_factor=2 if not phone else 2)
            await pg.route('**/fonts.googleapis.com/**', lambda r: r.abort()); await pg.route('**/fonts.gstatic.com/**', lambda r: r.abort())
            await pg.goto(f'file://{f}'); await pg.wait_for_timeout(300)
            await pg.screenshot(path=str(OUT / (f.stem + '.png')), full_page=True, **({'clip': {'x': 0, 'y': 0, 'width': 390, 'height': 2300}} if phone else {}))
            print('shot', f.stem)
        await b.close()
asyncio.run(main())
