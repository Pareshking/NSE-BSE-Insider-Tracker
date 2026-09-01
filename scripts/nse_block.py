"""NSE Block Deals acquisition using browser-native fetch.

2026-09-01 finding: /api/historical/block-deals -- the endpoint this script
used to call -- is dead: it returns the same ~22KB Akamai bot-detection page
on every request regardless of parameters, retries, or session warmup (same
signature as the dead /api/corporates-pit endpoint that blocked Insider
Trading before nse_insider.py was rewritten). A live-network diagnostic
(scripts/nse_bulk_diagnose.py) captured what NSE's own "Bulk Deals/ Block
Deals/ Short Selling Archives" page (report-detail/display-bulk-and-block-deals)
actually calls: /api/historicalOR/bulk-block-short-deals?optionType=block_deals
-- from the SAME runner IP, in the SAME run, this endpoint returned real JSON
while /api/historical/block-deals returned the fake page. So this was a wrong
(retired) endpoint, not an IP block -- confirmed by getting real data back
from the very first live run after switching (see nse_bulk.py, fixed the
same way).
"""
from __future__ import annotations
import json, os, time
from datetime import date, timedelta
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

BASE    = 'https://www.nseindia.com'
PAGE    = f'{BASE}/report-detail/display-bulk-and-block-deals'
TARGET  = date.fromisoformat(os.getenv('TARGET_DATE', '2026-08-31'))
LOOKBACK = int(os.getenv('LOOKBACK_DAYS', '90'))
OUT     = Path('artifacts/nse_block')
OUT.mkdir(parents=True, exist_ok=True)
UA      = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/139 Safari/537.36'

_JS = """
const [url, cb] = [arguments[0], arguments[arguments.length-1]];
fetch(url, {
  credentials: 'include',
  headers: {
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://www.nseindia.com/report-detail/display-bulk-and-block-deals'
  }
}).then(async r => {
  const t = await r.text();
  cb(JSON.stringify({status: r.status, url: r.url, bytes: t.length, text: t}));
}).catch(e => cb(JSON.stringify({status: 0, error: String(e), bytes: 0, text: ''})));
"""

def browser():
    o = Options()
    for x in ('--headless=new', '--no-sandbox', '--disable-dev-shm-usage',
               '--disable-gpu', '--window-size=1920,1080', f'--user-agent={UA}'):
        o.add_argument(x)
    return webdriver.Chrome(options=o)

def js_fetch(d, url):
    raw  = json.loads(d.execute_async_script(_JS, url))
    text = raw.get('text', '')
    try:
        raw['json'] = json.loads(text)
    except Exception as exc:
        raw['json'] = None
        raw['parse_error'] = str(exc)
    return raw

def fetch_window(d, name, start, end, retries=3):
    url = f'{BASE}/api/historicalOR/bulk-block-short-deals?optionType=block_deals&from={start:%d-%m-%Y}&to={end:%d-%m-%Y}'
    raw = js_fetch(d, url)
    for attempt in range(retries):
        if raw.get('json') is not None:
            break
        # Akamai bot-detection HTML page instead of JSON -- reload the page to
        # refresh the session/challenge state, then retry.
        print(f'  [{name}] non-JSON response (attempt {attempt+1}/{retries}), reloading page and retrying...')
        d.get(PAGE)
        time.sleep(6)
        raw = js_fetch(d, url)
    obj  = raw.get('json') or {}
    rows = obj.get('data', []) if isinstance(obj, dict) else (obj if isinstance(obj, list) else [])
    dates = sorted({
        str(r.get('BD_DT_DATE') or r.get('mTIMESTAMP') or r.get('date') or '')
        for r in rows
        if (r.get('BD_DT_DATE') or r.get('mTIMESTAMP') or r.get('date'))
    })
    return {
        'name': name, 'request_url': url,
        'status': raw.get('status'), 'bytes': raw.get('bytes'),
        'start_date': str(start), 'end_date': str(end),
        'mode': 'json' if raw.get('json') is not None else 'non_json',
        'parse_error': raw.get('parse_error'),
        'count': len(rows),
        'columns': sorted(rows[0].keys()) if rows and isinstance(rows[0], dict) else [],
        'distinct_dates': dates,
        'rows': rows,
    }

def main():
    d = browser()
    try:
        d.get(PAGE)
        time.sleep(6)

        windows, all_rows = [], []
        specs = [
            ('1d',  TARGET,                          TARGET),
            ('7d',  TARGET - timedelta(days=6),      TARGET),
            ('30d', TARGET - timedelta(days=29),     TARGET),
            ('90d', TARGET - timedelta(days=LOOKBACK-1), TARGET),
        ]
        for name, start, end in specs:
            w = fetch_window(d, name, start, end)
            windows.append({k: v for k, v in w.items() if k != 'rows'})
            Path(OUT / f'{name}.json').write_text(json.dumps(w, indent=2, default=str))
            all_rows.extend(w['rows'])
            time.sleep(2)

        report = {
            'dataset': 'block_deals', 'source': 'NSE',
            'target_date': str(TARGET), 'lookback_days': LOOKBACK,
            'method': 'NSE historicalOR/bulk-block-short-deals API (browser-native fetch, same one the live report page uses)',
            'windows': windows,
            'count': len(all_rows),
            'unique_observations': len({json.dumps(r, sort_keys=True, default=str) for r in all_rows}),
            'columns': sorted(all_rows[0].keys()) if all_rows and isinstance(all_rows[0], dict) else [],
            'rows': all_rows,
        }
        Path(OUT / 'report.json').write_text(json.dumps(report, indent=2, default=str))
        print(json.dumps({k: v for k, v in report.items() if k != 'rows'}, indent=2))
    finally:
        d.quit()

if __name__ == '__main__':
    main()
