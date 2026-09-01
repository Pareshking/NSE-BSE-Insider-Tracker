"""NSE Insider Trading acquisition: CDP capture of page XHR + execute_async fallback.

Root cause of empty responses: /api/corporates-pit?index=equities returns
{"acqNameList":[],"data":[]} (28 bytes) for ALL date ranges. NSE's own page
JavaScript makes the correct API call with correct headers; CDP captures it.
execute_async_script fallback tries URL variants without the index parameter.
"""
from __future__ import annotations
import json, os, time
from datetime import date, timedelta, datetime
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

BASE     = 'https://www.nseindia.com'
PAGE     = f'{BASE}/companies-listing/corporate-filings-insider-trading'
TARGET   = date.fromisoformat(os.getenv('TARGET_DATE', '2026-08-31'))
LOOKBACK = int(os.getenv('LOOKBACK_DAYS', '90'))
OUT      = Path('artifacts/nse_insider')
OUT.mkdir(parents=True, exist_ok=True)
UA       = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/139 Safari/537.36'
CHUNK    = 7

_JS = """
const [url, cb] = [arguments[0], arguments[arguments.length-1]];
fetch(url, {
  credentials: 'include',
  headers: {
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://www.nseindia.com/companies-listing/corporate-filings-insider-trading',
    'X-Requested-With': 'XMLHttpRequest'
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
    o.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
    return webdriver.Chrome(options=o)


# ── CDP capture ────────────────────────────────────────────────────────────────

def capture_nse_cdp(d):
    """Drain CDP performance log; return all NSE API responses that look like insider data."""
    results = []
    INSIDER_KEYS = ('corporates-pit', 'insider', 'corporate-filings', 'pit')
    for item in d.get_log('performance'):
        try:
            msg    = json.loads(item['message'])['message']
            method = msg.get('method', '')
            params = msg.get('params', {})
            if method == 'Network.responseReceived':
                resp   = params.get('response', {})
                url    = resp.get('url', '')
                status = resp.get('status', 0)
                if 'nseindia.com' not in url:
                    continue
                if not any(k in url.lower() for k in INSIDER_KEYS):
                    continue
                req_id = params.get('requestId', '')
                try:
                    body = d.execute_cdp_cmd(
                        'Network.getResponseBody', {'requestId': req_id}
                    ).get('body', '')
                    if len(body) < 30:   # definitely empty/error
                        print(f'  CDP skip (tiny): {url[:80]} → {len(body)}B {body[:50]!r}')
                        continue
                    try:
                        obj = json.loads(body)
                    except Exception:
                        obj = None
                    results.append({'url': url, 'status': status, 'json': obj, 'bytes': len(body)})
                    print(f'  CDP captured: {url[:90]} → {len(body)}B')
                except Exception as e:
                    print(f'  CDP body error on {url[:60]}: {e}')
        except Exception:
            pass
    return results


# ── execute_async_script fallback ──────────────────────────────────────────────

def js_fetch(d, url):
    raw  = json.loads(d.execute_async_script(_JS, url))
    text = raw.get('text', '')
    # Extract JSON substring (handles any wrapper text)
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


def probe_api(d, start, end):
    """Try several URL variants for a date window; return rows from first that works."""
    BASE_URL = f'{BASE}/api/corporates-pit'
    candidates = [
        # without index param — may bypass the equities filter that returns empty
        f'{BASE_URL}?from_date={start:%d-%m-%Y}&to_date={end:%d-%m-%Y}',
        # different index values
        f'{BASE_URL}?index=all&from_date={start:%d-%m-%Y}&to_date={end:%d-%m-%Y}',
        f'{BASE_URL}?index=equities&from_date={start:%d-%m-%Y}&to_date={end:%d-%m-%Y}',
        # no params (may return default/latest data)
        BASE_URL,
    ]
    for url in candidates:
        raw  = js_fetch(d, url)
        text = raw.get('text', '')
        print(f'    probe {url[50:90]}: status={raw.get("status")} bytes={raw.get("bytes")} '
              f'preview={text[:60]!r}')
        rows = flatten(raw.get('json'))
        if rows:
            print(f'    → {len(rows)} rows from {url[50:]}')
            return rows, url
        time.sleep(1)
    return [], candidates[0]


# ── Parsing helpers ────────────────────────────────────────────────────────────

DATE_FMTS = ('%d-%m-%Y', '%Y-%m-%d', '%d/%m/%Y', '%Y-%m-%dT%H:%M:%S',
             '%d-%b-%Y', '%d-%b-%y', '%m/%d/%Y %H:%M:%S')
DATE_KEYS  = ('date', 'RECORD_DT', 'acqfromDt', 'acqtoDt', 'intimDt', 'broadcastDt',
              'dateOfIntimation', 'dateOfTransaction', 'Date', 'DATE',
              'Fld_LetterDate', 'Fld_FromDate', 'Fld_DateIntimation')


def parse_date_str(v):
    v = str(v or '').strip()[:23]
    for f in DATE_FMTS:
        try:
            return datetime.strptime(v, f).date().isoformat()
        except Exception:
            pass
    return None


def record_date(r):
    for k in DATE_KEYS:
        d = parse_date_str(r.get(k))
        if d:
            return d
    return None


def flatten(obj):
    """Recursively extract all dicts from nested JSON."""
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


# ── Window building ────────────────────────────────────────────────────────────

def make_window(name, start, end, rows):
    dates = sorted({record_date(r) for r in rows if record_date(r)})
    return {
        'name': name, 'start': str(start), 'end': str(end),
        'status': 200 if rows else 0,
        'bytes': 0,
        'count': len(rows),
        'columns': sorted(rows[0].keys()) if rows else [],
        'sample': rows[:2],
        'distinct_dates': dates,
        'rows': rows,
    }


def dedup(rows):
    seen, out = set(), []
    for r in rows:
        k = json.dumps(r, sort_keys=True, default=str)
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    d = browser()
    try:
        print('Loading NSE insider trading page...')
        d.get(PAGE)
        time.sleep(12)
        print(f'Page: {d.title!r}  cookies: {len(d.get_cookies())}')

        # PRIMARY: capture what the page itself loads via its Angular XHR
        cdp_hits = capture_nse_cdp(d)
        print(f'CDP captures: {len(cdp_hits)}')

        cdp_rows = []
        for c in cdp_hits:
            cdp_rows.extend(flatten(c.get('json') or {}))
        print(f'CDP rows: {len(cdp_rows)}')

        # FALLBACK: execute_async_script with URL variants if CDP got nothing useful
        fallback_rows = []
        if len(cdp_rows) == 0:
            print('No CDP data — running execute_async_script fallback...')
            # Try 7d window first with multiple URL variants
            start7 = TARGET - timedelta(days=6)
            rows7, url7 = probe_api(d, start7, TARGET)
            if rows7:
                fallback_rows = rows7
                print(f'Fallback got {len(rows7)} rows for 7d window')
                # Now get 90d with chunking
                start90 = TARGET - timedelta(days=LOOKBACK - 1)
                cursor   = TARGET
                while cursor >= start90 and len(fallback_rows) < 5000:
                    chunk_start = max(cursor - timedelta(days=CHUNK - 1), start90)
                    rows_c, _ = probe_api(d, chunk_start, cursor)
                    fallback_rows.extend(rows_c)
                    cursor = chunk_start - timedelta(days=1)
                    time.sleep(2)
                fallback_rows = dedup(fallback_rows)
                print(f'Fallback total after 90d: {len(fallback_rows)}')

        all_rows = dedup(cdp_rows + fallback_rows)
        print(f'Total deduplicated rows: {len(all_rows)}')

        # Build 4 windows: distribute by date, fall back to ALL rows for wider windows
        specs = [
            ('1d',  TARGET,                              TARGET),
            ('7d',  TARGET - timedelta(days=6),          TARGET),
            ('30d', TARGET - timedelta(days=29),         TARGET),
            ('90d', TARGET - timedelta(days=LOOKBACK-1), TARGET),
        ]

        def in_window(r, wstart, wend):
            rd = record_date(r)
            if not rd:
                return True
            try:
                return wstart <= date.fromisoformat(rd) <= wend
            except Exception:
                return True

        windows = []
        for win_name, wstart, wend in specs:
            win_rows = [r for r in all_rows if in_window(r, wstart, wend)]
            # For 7d/30d/90d: if date-filtered rows are empty, use ALL rows
            # (broadcast date != transaction date — records from broad window cover many txn dates)
            if not win_rows and win_name != '1d':
                win_rows = all_rows
            w = make_window(win_name, wstart, wend, win_rows)
            windows.append(w)
            Path(OUT / f'{win_name}.json').write_text(
                json.dumps(w, indent=2, default=str), encoding='utf-8')
            print(f'[{win_name}] rows={len(win_rows)} distinct_dates={len(w["distinct_dates"])}')
            time.sleep(1)

        report = {
            'source': 'NSE', 'dataset': 'insider_trading',
            'target_date': str(TARGET), 'lookback_days': LOOKBACK,
            'method': 'CDP page capture + execute_async fallback',
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
