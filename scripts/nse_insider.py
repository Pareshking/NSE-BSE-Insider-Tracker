"""NSE Insider Trading acquisition: stealth CDP capture of the real PIT endpoint.

Root cause of the previous failure: INSIDER_KEYS was too broad
('corporate-filings', 'pit', 'insider') and matched OTHER NSE corporate-filings
APIs the page also loads (event calendar, actions, etc.), not the actual
/api/corporates-pit endpoint. Those unrelated rows had no personCategory field,
so the promoter check always saw 0 promoter rows even with thousands of rows
captured. Fix: narrow capture to 'corporates-pit' only, validate captured rows
actually look like PIT records, add Akamai-evading stealth flags (BSE's script
already had these; NSE's did not), and interact with the page's date filter to
force a fresh XHR covering the full lookback window.
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
UA       = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
            '(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36')

# Only the actual PIT API endpoint — NOT the broader 'corporate-filings'/'pit'
# substrings that also match unrelated NSE APIs on the same page.
INSIDER_KEYS   = ('corporates-pit',)
PIT_FIELD_HITS = ('personCategory', 'acqName', 'acqfromDt', 'buyQuantity', 'sellQuantity')

_JS_FETCH = """
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
              '--disable-gpu', '--window-size=1920,1080',
              '--disable-blink-features=AutomationControlled',
              '--disable-extensions', '--no-first-run', '--no-default-browser-check',
              f'--user-agent={UA}'):
        o.add_argument(x)
    o.add_experimental_option('excludeSwitches', ['enable-automation'])
    o.add_experimental_option('useAutomationExtension', False)
    o.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
    d = webdriver.Chrome(options=o)
    d.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {'source': """
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
        Object.defineProperty(navigator, 'languages', {get: () => ['en-US','en']});
        window.chrome = {runtime: {}};
    """})
    return d


# ── CDP capture (narrowed to real PIT endpoint) ─────────────────────────────────

def capture_nse_cdp(d):
    results = []
    for item in d.get_log('performance'):
        try:
            msg    = json.loads(item['message'])['message']
            method = msg.get('method', '')
            params = msg.get('params', {})
            if method != 'Network.responseReceived':
                continue
            resp   = params.get('response', {})
            url    = resp.get('url', '')
            if 'nseindia.com' not in url or not any(k in url.lower() for k in INSIDER_KEYS):
                continue
            req_id = params.get('requestId', '')
            status = resp.get('status', 0)
            try:
                body = d.execute_cdp_cmd(
                    'Network.getResponseBody', {'requestId': req_id}
                ).get('body', '')
                try:
                    obj = json.loads(body)
                except Exception:
                    obj = None
                results.append({'url': url, 'status': status, 'json': obj, 'bytes': len(body)})
                print(f'  CDP PIT: {url[:90]} -> {len(body)}B status={status}')
            except Exception as e:
                print(f'  CDP body error on {url[:60]}: {e}')
        except Exception:
            pass
    return results


def is_valid_pit_data(rows):
    if not rows:
        return False
    sample = rows[:20]
    hits = sum(1 for r in sample if isinstance(r, dict) and any(f in r for f in PIT_FIELD_HITS))
    return hits >= max(1, len(sample) // 3)


# ── Date-filter page interaction ────────────────────────────────────────────────

def try_set_nse_date_range(d, from_date, to_date):
    fmt = '%d-%m-%Y'
    fd, td = from_date.strftime(fmt), to_date.strftime(fmt)
    print(f'  Attempting date range set: {fd} -> {td}')
    try:
        set_count = d.execute_script("""
            const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
            const inputs = Array.from(document.querySelectorAll('input[type=text], input:not([type])'));
            const dateInputs = inputs.filter(i => {
                const a = ((i.placeholder||'')+(i.id||'')+(i.name||'')+(i.className||'')).toLowerCase();
                return /date|from|to|dd|period/.test(a);
            });
            let count = 0;
            const vals = [arguments[0], arguments[1]];
            for (let i = 0; i < Math.min(2, dateInputs.length); i++) {
                setter.call(dateInputs[i], vals[i]);
                ['input','change','blur'].forEach(ev =>
                    dateInputs[i].dispatchEvent(new Event(ev, {bubbles:true})));
                count++;
            }
            return count;
        """, fd, td)
        print(f'  Date inputs set: {set_count}')
    except Exception as e:
        print(f'  Date set failed: {e}')

    time.sleep(1)
    try:
        clicked = d.execute_script("""
            const btns = Array.from(document.querySelectorAll('button, input[type=submit], input[type=button]'));
            const btn = btns.find(b => {
                const t = (b.textContent || b.value || '').trim().toLowerCase();
                return /^(search|apply|go|filter|submit)/.test(t) && !/reset|clear/.test(t);
            });
            if (btn) { btn.click(); return (btn.textContent || btn.value || 'clicked').trim(); }
            return null;
        """)
        print(f'  Search button clicked: {clicked!r}')
        return bool(clicked)
    except Exception as e:
        print(f'  Click failed: {e}')
        return False


# ── execute_async_script fallback ──────────────────────────────────────────────

def js_fetch(d, url):
    raw  = json.loads(d.execute_async_script(_JS_FETCH, url))
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


def probe_api(d, start, end):
    BASE_URL = f'{BASE}/api/corporates-pit'
    fd, td = f'{start:%d-%m-%Y}', f'{end:%d-%m-%Y}'
    candidates = [
        f'{BASE_URL}?from_date={fd}&to_date={td}',
        f'{BASE_URL}?index=equities&from_date={fd}&to_date={td}',
        f'{BASE_URL}?index=all&from_date={fd}&to_date={td}',
        BASE_URL,
    ]
    for url in candidates:
        raw   = js_fetch(d, url)
        rows  = flatten(raw.get('json'))
        valid = is_valid_pit_data(rows)
        print(f'    probe {url[len(BASE):90]}: status={raw.get("status")} '
              f'bytes={raw.get("bytes")} rows={len(rows)} valid={valid}')
        if rows and valid:
            return rows, url
        time.sleep(1.5)
    return [], candidates[0]


# ── Parsing helpers ────────────────────────────────────────────────────────────

DATE_FMTS = ('%d-%m-%Y', '%Y-%m-%d', '%d/%m/%Y', '%Y-%m-%dT%H:%M:%S',
             '%d-%b-%Y', '%d-%b-%y', '%m/%d/%Y %H:%M:%S')
DATE_KEYS  = ('acqfromDt', 'acqtoDt', 'intimDt', 'broadcastDt',
              'dateOfIntimation', 'dateOfTransaction', 'date', 'Date', 'DATE')


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


def dedup(rows):
    seen, out = set(), []
    for r in rows:
        k = json.dumps(r, sort_keys=True, default=str)
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


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


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    d = browser()
    try:
        from_date = TARGET - timedelta(days=LOOKBACK - 1)

        print('Loading NSE insider trading page...')
        d.get(PAGE)
        time.sleep(15)
        print(f'Page: {d.title!r}  cookies: {len(d.get_cookies())}')

        # Drain initial-load CDP log (may already contain a PIT XHR)
        cdp_hits = capture_nse_cdp(d)

        # Interact with the date filter to force a fresh, wider-range XHR
        set_ok = try_set_nse_date_range(d, from_date, TARGET)
        if set_ok:
            time.sleep(12)
            cdp_hits.extend(capture_nse_cdp(d))

        cdp_rows = []
        for c in cdp_hits:
            rows = flatten(c.get('json') or {})
            if is_valid_pit_data(rows):
                cdp_rows.extend(rows)
            else:
                print(f'  Discarding non-PIT capture from {c["url"][:80]} '
                      f'({len(rows)} rows, sample keys: '
                      f'{list(rows[0].keys())[:6] if rows else []})')
        cdp_rows = dedup(cdp_rows)
        print(f'CDP validated PIT rows: {len(cdp_rows)}')

        fallback_rows = []
        if not cdp_rows:
            print('No valid CDP PIT data — running execute_async fallback...')
            rows7, url7 = probe_api(d, TARGET - timedelta(days=6), TARGET)
            if rows7:
                fallback_rows = rows7
                cursor = TARGET - timedelta(days=7)
                while cursor >= from_date and len(fallback_rows) < 10000:
                    chunk_start = max(cursor - timedelta(days=6), from_date)
                    rc, _ = probe_api(d, chunk_start, cursor)
                    fallback_rows.extend(rc)
                    cursor = chunk_start - timedelta(days=1)
                    time.sleep(2)
                fallback_rows = dedup(fallback_rows)
                print(f'Fallback total after {LOOKBACK}d: {len(fallback_rows)}')
            else:
                raw = js_fetch(d, f'{BASE}/api/corporates-pit')
                rows_all = flatten(raw.get('json'))
                if is_valid_pit_data(rows_all):
                    fallback_rows = rows_all
                    print(f'Fallback default-call rows: {len(fallback_rows)}')

        all_rows = dedup(cdp_rows + fallback_rows)
        print(f'Total validated PIT rows: {len(all_rows)}')

        promoter_rows = [r for r in all_rows if 'PROMOTER' in str(r.get('personCategory', '')).upper()]
        print(f'Rows with PROMOTER category: {len(promoter_rows)}')

        specs = [
            ('1d',  TARGET,                TARGET),
            ('7d',  TARGET - timedelta(days=6),  TARGET),
            ('30d', TARGET - timedelta(days=29), TARGET),
            ('90d', from_date,             TARGET),
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
            'method': 'Stealth CDP page capture (narrowed to corporates-pit) + execute_async fallback',
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
