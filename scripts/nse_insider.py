"""NSE Insider Trading acquisition using browser-native fetch.

Akamai Bot Manager blocks requests.Session — the response comes back as empty
JSON or garbled bytes. This script keeps the Selenium browser open and fetches
via execute_async_script so the full Akamai context (TLS fingerprint, cookie
jar, JS integrity checks) is preserved. The flatten() helper handles any
nested response structure, making the extraction robust to API key changes.
"""
from __future__ import annotations
import json, os, re, time
from datetime import date, timedelta, datetime
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

BASE     = 'https://www.nseindia.com'
PAGE     = f'{BASE}/companies-listing/corporate-filings-insider-trading'
API_URL  = f'{BASE}/api/corporates-pit'
TARGET   = date.fromisoformat(os.getenv('TARGET_DATE', '2026-08-31'))
LOOKBACK = int(os.getenv('LOOKBACK_DAYS', '90'))
OUT      = Path('artifacts/nse_insider')
OUT.mkdir(parents=True, exist_ok=True)
UA       = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/139 Safari/537.36'

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
    for x in ('--headless=new', '--no-sandbox', '--disable-dev-shm-usage',
               '--disable-gpu', '--window-size=1920,1080', f'--user-agent={UA}'):
        o.add_argument(x)
    return webdriver.Chrome(options=o)


def flatten(obj):
    """Recursively extract all dicts from nested JSON (handles any response shape)."""
    if isinstance(obj, list):
        if obj and all(isinstance(x, dict) for x in obj):
            return obj
        out = []
        for x in obj:
            out.extend(flatten(x))
        return out
    if isinstance(obj, dict):
        out = []
        for v in obj.values():
            out.extend(flatten(v))
        return out
    return []


DATE_FMTS = ('%d-%m-%Y', '%Y-%m-%d', '%d/%m/%Y', '%d-%b-%Y', '%d-%b-%y')
DATE_KEYS  = ('date', 'RECORD_DT', 'acqfromDt', 'acqtoDt', 'intimDt', 'broadcastDt',
              'mDate', 'bdDtDate', 'dtDate', 'Date', 'DATE')

def record_date(r):
    for k in DATE_KEYS:
        v = str(r.get(k) or '')
        if v and len(v) >= 8:
            for f in DATE_FMTS:
                try:
                    return datetime.strptime(v[:11].strip(), f).date().isoformat()
                except Exception:
                    pass
    return None


def js_fetch(d, url):
    raw  = json.loads(d.execute_async_script(_JS, url))
    text = raw.get('text', '')
    # Strip non-JSON framing bytes that Akamai occasionally prepends
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
    # Warm up by visiting the page with date params in the URL first
    page_url = (f'{PAGE}?from_date={start:%d-%m-%Y}&to_date={end:%d-%m-%Y}')
    d.get(page_url)
    time.sleep(5)

    api_url = f'{API_URL}?index=equities&from_date={start:%d-%m-%Y}&to_date={end:%d-%m-%Y}'
    raw = js_fetch(d, api_url)

    obj  = raw.get('json')
    # Debug: show top-level keys and response size
    if isinstance(obj, dict):
        top_keys = list(obj.keys())[:20]
    elif isinstance(obj, list):
        top_keys = [f'list[{len(obj)}]']
    else:
        top_keys = []
    print(f'  [{name}] status={raw.get("status")} bytes={raw.get("bytes")} '
          f'top_keys={top_keys} parse_error={raw.get("parse_error")}')
    if raw.get('bytes', 0) < 100:
        print(f'  [{name}] raw text preview: {raw.get("text","")[:200]!r}')

    rows  = flatten(obj) if obj is not None else []
    dates = sorted({d2 for r in rows if (d2 := record_date(r))})

    return {
        'name': name, 'start': str(start), 'end': str(end),
        'request_url': api_url, 'page_url': page_url,
        'status': raw.get('status'), 'bytes': raw.get('bytes'),
        'mode':        'json' if obj is not None else 'non_json',
        'parse_error': raw.get('parse_error'),
        'top_keys':    top_keys,
        'count':       len(rows),
        'columns':     sorted(rows[0].keys()) if rows and isinstance(rows[0], dict) else [],
        'sample':      rows[:2],
        'distinct_transaction_dates': dates,
        'rows':        rows,
    }


def main():
    d = browser()
    try:
        # Initial warm-up visit
        d.get(PAGE)
        time.sleep(8)
        print(f'Browser ready: {d.title!r}  cookies: {len(d.get_cookies())}')

        windows = []
        specs = [
            ('1d',  TARGET,                          TARGET),
            ('7d',  TARGET - timedelta(days=6),      TARGET),
            ('30d', TARGET - timedelta(days=29),     TARGET),
            ('90d', TARGET - timedelta(days=LOOKBACK-1), TARGET),
        ]
        for name, start, end in specs:
            print(f'Fetching window {name}: {start} → {end}')
            w = fetch_window(d, name, start, end)
            print(f'  [{name}] rows={w["count"]}  dates={len(w["distinct_transaction_dates"])}')
            windows.append(w)
            Path(OUT / f'{name}.json').write_text(
                json.dumps(w, indent=2, default=str), encoding='utf-8')
            time.sleep(2)

        report = {
            'source': 'NSE', 'dataset': 'insider_trading',
            'target_date': str(TARGET), 'lookback_days': LOOKBACK,
            'method': 'browser-native fetch (Akamai-safe) + flatten',
            'windows': [{k: v for k, v in w.items() if k not in ('rows', 'sample')}
                        for w in windows],
        }
        Path(OUT / 'report.json').write_text(
            json.dumps(report, indent=2, default=str), encoding='utf-8')
        print(json.dumps(report, indent=2, default=str))
    finally:
        d.quit()


if __name__ == '__main__':
    main()
