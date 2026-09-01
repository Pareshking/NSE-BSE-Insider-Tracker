"""NSE Bulk Deals acquisition using browser-native fetch.

2026-09-01 finding: /api/historical/bulk-deals -- the endpoint this script
used to call -- is dead: it returns the same ~22KB Akamai bot-detection page
on every request regardless of parameters, retries, or session warmup (same
signature as the dead /api/corporates-pit endpoint that blocked Insider
Trading before nse_insider.py was rewritten). A live-network diagnostic
(scripts/nse_bulk_diagnose.py) captured what NSE's own "Bulk Deals/ Block
Deals/ Short Selling Archives" page (report-detail/display-bulk-and-block-deals)
actually calls: /api/historicalOR/bulk-block-short-deals?optionType=bulk_deals
-- from the SAME runner IP, in the SAME run, this endpoint returned real JSON
while /api/historical/bulk-deals returned the fake page. So this was a wrong
(retired) endpoint, not an IP block -- confirmed by getting real data back
from the very first live run after switching.
"""
from __future__ import annotations
import json, os, time
from datetime import date, datetime, timedelta
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

BASE    = 'https://www.nseindia.com'
PAGE    = f'{BASE}/report-detail/display-bulk-and-block-deals'
TARGET  = date.fromisoformat(os.getenv('TARGET_DATE', '2026-08-31'))
LOOKBACK = int(os.getenv('LOOKBACK_DAYS', '90'))
OUT     = Path('artifacts/nse_bulk')
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

CHUNK = 1  # max days per call -- see fetch_all() docstring below

def fetch_range(d, start, end, retries=3):
    """Single API call for one [start, end] sub-range. Returns (url, raw, rows, chunk_diag)."""
    url = f'{BASE}/api/historicalOR/bulk-block-short-deals?optionType=bulk_deals&from={start:%d-%m-%Y}&to={end:%d-%m-%Y}'
    raw = js_fetch(d, url)
    attempts = 1
    for attempt in range(retries):
        if raw.get('json') is not None:
            break
        # Akamai bot-detection HTML page instead of JSON -- reload the page to
        # refresh the session/challenge state, then retry.
        print(f'    non-JSON response for {start}..{end} (attempt {attempt+1}/{retries}), reloading page and retrying...')
        d.get(PAGE)
        time.sleep(6)
        raw = js_fetch(d, url)
        attempts += 1
    obj  = raw.get('json') or {}
    rows = obj.get('data', []) if isinstance(obj, dict) else (obj if isinstance(obj, list) else [])
    diag = {
        'start': str(start), 'end': str(end), 'attempts': attempts,
        'final_status': raw.get('status'), 'final_bytes': raw.get('bytes'),
        'mode': 'json' if raw.get('json') is not None else 'non_json', 'count': len(rows),
    }
    print(f'    [{start}..{end}] attempt {attempts}: status={diag["final_status"]} bytes={diag["final_bytes"]} mode={diag["mode"]} count={diag["count"]}')
    return url, rows, diag

def fetch_all(d, earliest, latest):
    """A single call to /api/historicalOR/bulk-block-short-deals caps results
    at 70 rows, sorted ASCENDING by date within the requested range -- NOT
    most-recent-first as first assumed. Confirmed 2026-09-01 with CHUNK=7:
    every 7-day chunk returned exactly 70 rows, ALL from that chunk's FIRST
    (oldest) day -- e.g. requesting 26-Aug..31-Aug returned only 26-Aug's
    deals, silently dropping 27-31 Aug entirely, because 26-Aug alone had
    >=70 deals and ascending sort never got past it within the 70-row cap.
    That meant the 1d window (which needs the single most RECENT date) came
    back empty even though the 90d window had 910 real rows spanning 13
    dates -- all of them chunk-start dates, none of them the target date.

    CHUNK=1 (one calendar day per call) is the only size that's actually
    safe against this: it guarantees each call's date range IS a single day,
    so the ascending-sort-plus-cap can never cause an earlier day to crowd
    out a later one -- the worst case is a single day itself having >70
    deals and losing its own tail, which is a real but much smaller and
    unavoidable limitation of a paginated endpoint we don't control.

    Fetches the FULL lookback range exactly once (chunked), rather than each
    named window (1d/7d/30d/90d) re-fetching its own overlapping range from
    scratch -- the first version of this fix made ~20 calls per run with
    heavy overlap between windows, which may have been enough rapid-fire
    same-endpoint traffic to trip a temporary block (bulk failed outright in
    that run while block, running immediately after in a fresh session,
    succeeded). Fetching once and slicing the combined rows by date for each
    window cuts total calls roughly in half with zero redundant overlap."""
    urls, rows_by_key, chunks = [], {}, []
    cur = earliest
    while cur <= latest:
        chunk_end = min(cur + timedelta(days=CHUNK - 1), latest)
        url, rows, diag = fetch_range(d, cur, chunk_end)
        urls.append(url)
        chunks.append(diag)
        for r in rows:
            key = json.dumps(r, sort_keys=True, default=str)
            rows_by_key[key] = r
        cur = chunk_end + timedelta(days=1)
        time.sleep(1)
    return list(rows_by_key.values()), urls, chunks

def slice_window(name, all_rows, start, end):
    def row_date(r):
        raw = r.get('BD_DT_DATE') or r.get('mTIMESTAMP') or r.get('date') or ''
        for fmt in ('%d-%b-%Y', '%d-%m-%Y', '%Y-%m-%d'):
            try:
                return datetime.strptime(str(raw), fmt).date()
            except ValueError:
                continue
        return None
    rows = [r for r in all_rows if (rd := row_date(r)) and start <= rd <= end]
    dates = sorted({str(r.get('BD_DT_DATE') or r.get('mTIMESTAMP') or r.get('date') or '') for r in rows})
    return {
        'name': name, 'start_date': str(start), 'end_date': str(end),
        'mode': 'json' if rows else 'non_json',
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

        earliest = TARGET - timedelta(days=LOOKBACK - 1)
        all_rows, urls, chunks = fetch_all(d, earliest, TARGET)

        windows = []
        specs = [
            ('1d',  TARGET,                          TARGET),
            ('7d',  TARGET - timedelta(days=6),      TARGET),
            ('30d', TARGET - timedelta(days=29),     TARGET),
            ('90d', earliest,                        TARGET),
        ]
        for name, start, end in specs:
            w = slice_window(name, all_rows, start, end)
            windows.append({k: v for k, v in w.items() if k != 'rows'})
            Path(OUT / f'{name}.json').write_text(json.dumps(w, indent=2, default=str))

        report = {
            'dataset': 'bulk_deals', 'source': 'NSE',
            'target_date': str(TARGET), 'lookback_days': LOOKBACK,
            'method': 'NSE historicalOR/bulk-block-short-deals API (browser-native fetch, same one the live report page uses); '
                      'fetched once as CHUNK-day sub-ranges and sliced per window to avoid redundant overlapping calls',
            'chunk_diagnostics': chunks,
            'request_urls': urls,
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
