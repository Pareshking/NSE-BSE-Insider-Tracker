"""NSE Insider Trading acquisition using browser-native fetch.

The NSE PIT API at /api/corporates-pit requires Akamai Bot Manager session state.
When called from requests.Session (even with copied cookies), Akamai returns empty JSON.
This script keeps the Selenium browser open and fetches via execute_async_script so
the full Akamai context (TLS fingerprint, cookie jar, JS-executed integrity checks)
is preserved across all four time windows.
"""
from __future__ import annotations
import json, os, time
from datetime import date, timedelta
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

BASE = 'https://www.nseindia.com'
PAGE = f'{BASE}/companies-listing/corporate-filings-insider-trading'
API  = f'{BASE}/api/corporates-pit'
TARGET  = date.fromisoformat(os.getenv('TARGET_DATE', '2026-08-31'))
LOOKBACK = int(os.getenv('LOOKBACK_DAYS', '90'))
OUT = Path('artifacts/nse_insider')
OUT.mkdir(parents=True, exist_ok=True)
UA  = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/139 Safari/537.36'

_JS = """
const [url, cb] = [arguments[0], arguments[arguments.length-1]];
fetch(url, {
  credentials: 'include',
  headers: {
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://www.nseindia.com/companies-listing/corporate-filings-insider-trading'
  }
}).then(async r => {
  const t = await r.text();
  cb(JSON.stringify({status: r.status, url: r.url, bytes: t.length, text: t}));
}).catch(e => cb(JSON.stringify({status: 0, error: String(e), bytes: 0, text: ''})));
"""

def browser():
    o = Options()
    for x in ('--headless=new','--no-sandbox','--disable-dev-shm-usage',
               '--disable-gpu','--window-size=1920,1080',f'--user-agent={UA}'):
        o.add_argument(x)
    return webdriver.Chrome(options=o)

def js_fetch(d, url):
    raw = json.loads(d.execute_async_script(_JS, url))
    text = raw.get('text','')
    # Strip non-JSON framing bytes (Akamai occasionally prepends garbage)
    s = min([p for p in (text.find('{'), text.find('[')) if p >= 0], default=-1)
    e = max(text.rfind('}'), text.rfind(']'))
    if s >= 0 and e >= s:
        text = text[s:e+1]
    try:
        raw['json'] = json.loads(text)
    except Exception as exc:
        raw['json'] = None
        raw['parse_error'] = str(exc)
    return raw

def fetch_window(d, name, start, end):
    url = f"{API}?index=equities&from_date={start:%d-%m-%Y}&to_date={end:%d-%m-%Y}"
    raw = js_fetch(d, url)
    obj  = raw.get('json') or {}
    rows = obj.get('data', []) if isinstance(obj, dict) else (obj if isinstance(obj, list) else [])
    dates = sorted({str(r.get('date','')) for r in rows if isinstance(r,dict) and r.get('date')})
    return {
        'name': name, 'start': str(start), 'end': str(end),
        'request_url': url,
        'status': raw.get('status'), 'bytes': raw.get('bytes'),
        'mode': 'json' if raw.get('json') is not None else 'non_json',
        'parse_error': raw.get('parse_error'),
        'count': len(rows),
        'columns': sorted(rows[0].keys()) if rows and isinstance(rows[0], dict) else [],
        'distinct_transaction_dates': dates,
        'rows': rows,
    }

def main():
    d = browser()
    try:
        d.get(PAGE)
        time.sleep(7)
        browser_title = d.title
        browser_url   = d.current_url
        cookies = [c['name'] for c in d.get_cookies()]

        windows, specs = [], [
            ('1d',  TARGET,                          TARGET),
            ('7d',  TARGET - timedelta(days=6),      TARGET),
            ('30d', TARGET - timedelta(days=29),     TARGET),
            ('90d', TARGET - timedelta(days=LOOKBACK-1), TARGET),
        ]
        for name, start, end in specs:
            w = fetch_window(d, name, start, end)
            windows.append(w)
            Path(OUT / f'{name}.json').write_text(
                json.dumps(w, indent=2, default=str), encoding='utf-8')
            time.sleep(2)

        report = {
            'source': 'NSE', 'dataset': 'insider_trading',
            'target_date': str(TARGET), 'lookback_days': LOOKBACK,
            'method': 'browser-native fetch (Akamai-safe)',
            'browser_title': browser_title, 'browser_url': browser_url,
            'cookie_names': cookies,
            'windows': [{k:v for k,v in w.items() if k != 'rows'} for w in windows],
        }
        Path(OUT/'report.json').write_text(
            json.dumps(report, indent=2, default=str), encoding='utf-8')
        print(json.dumps(report, indent=2, default=str))
    finally:
        d.quit()

if __name__ == '__main__':
    main()
