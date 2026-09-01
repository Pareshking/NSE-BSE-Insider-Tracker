"""NSE Insider Trading acquisition using browser-native fetch with date chunking.

The NSE PIT API (/api/corporates-pit) appears to cap responses at ~7 days of
broadcast data. Requests spanning 30–90 days return empty JSON. Fix: chunk any
window wider than 7 days into overlapping 7-day segments, combine and deduplicate.

One initial page warmup establishes the Akamai session; subsequent API calls
reuse that session without re-visiting the page (re-visiting can interfere with
Akamai's challenge state and costs 5s each).
"""
from __future__ import annotations
import json, os, time
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
CHUNK    = 7  # max days per API call; NSE PIT API caps around this window size

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


def api_call(d, start, end):
    """Single API call for a date range; returns (rows, status, bytes, parse_error)."""
    url = f'{API_URL}?index=equities&from_date={start:%d-%m-%Y}&to_date={end:%d-%m-%Y}'
    raw = js_fetch(d, url)
    obj = raw.get('json')
    if isinstance(obj, dict):
        top_keys = list(obj.keys())[:10]
    elif isinstance(obj, list):
        top_keys = [f'list[{len(obj)}]']
    else:
        top_keys = []
    rows = flatten(obj) if obj is not None else []
    print(f'    api {start:%d-%m-%Y}→{end:%d-%m-%Y}: status={raw.get("status")} '
          f'bytes={raw.get("bytes")} top_keys={top_keys} rows={len(rows)}')
    if raw.get('bytes', 0) < 100:
        print(f'    preview: {raw.get("text","")[:200]!r}')
    return rows, raw.get('status'), raw.get('bytes'), raw.get('parse_error')


def fetch_window(d, name, start, end):
    """Fetch a window, chunking into CHUNK-day segments to stay within API limits."""
    all_rows  = []
    seen_keys = set()
    total_bytes = 0
    last_status = None

    # Build chunks: step backward from end in CHUNK-day increments
    cursor = end
    while cursor >= start:
        chunk_start = max(cursor - timedelta(days=CHUNK - 1), start)
        rows, status, nbytes, _ = api_call(d, chunk_start, cursor)
        last_status = status
        total_bytes += nbytes or 0
        for r in rows:
            k = json.dumps(r, sort_keys=True, default=str)
            if k not in seen_keys:
                seen_keys.add(k)
                all_rows.append(r)
        cursor = chunk_start - timedelta(days=1)
        time.sleep(2)

    dates = sorted({d2 for r in all_rows if (d2 := record_date(r))})
    print(f'  [{name}] total rows={len(all_rows)} distinct_dates={len(dates)}')
    return {
        'name':  name, 'start': str(start), 'end': str(end),
        'status': last_status, 'bytes': total_bytes,
        'count':  len(all_rows),
        'columns': sorted(all_rows[0].keys()) if all_rows else [],
        'sample':  all_rows[:2],
        'distinct_dates': dates,
        'rows':    all_rows,
    }


def main():
    d = browser()
    try:
        d.get(PAGE)
        time.sleep(10)
        print(f'Browser ready: {d.title!r}  cookies: {len(d.get_cookies())}')

        windows = []
        specs = [
            ('1d',  TARGET,                              TARGET),
            ('7d',  TARGET - timedelta(days=6),          TARGET),
            ('30d', TARGET - timedelta(days=29),         TARGET),
            ('90d', TARGET - timedelta(days=LOOKBACK-1), TARGET),
        ]
        for name, start, end in specs:
            print(f'Fetching window {name}: {start} → {end}')
            w = fetch_window(d, name, start, end)
            windows.append(w)
            Path(OUT / f'{name}.json').write_text(
                json.dumps(w, indent=2, default=str), encoding='utf-8')
            time.sleep(3)

        report = {
            'source': 'NSE', 'dataset': 'insider_trading',
            'target_date': str(TARGET), 'lookback_days': LOOKBACK,
            'method': 'browser-native fetch + 7-day chunking + dedup',
            'windows': [{k: v for k, v in w.items() if k not in ('rows', 'sample')}
                        for w in windows],
        }
        Path(OUT / 'report.json').write_text(
            json.dumps(report, indent=2, default=str), encoding='utf-8')
        print(json.dumps({k: v for k, v in report.items() if k != 'windows'}, indent=2))
    finally:
        d.quit()


if __name__ == '__main__':
    main()
