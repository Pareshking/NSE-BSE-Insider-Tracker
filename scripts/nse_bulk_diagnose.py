"""One-off diagnostic (not part of the regular pipeline): finds out what API
calls NSE's own bulk/block-deals report pages actually make, and whether any
of them succeed from this runner right now.

Context: nse_bulk.py/nse_block.py warm up a session by visiting
market-data/large-deals, then call /api/historical/bulk-deals directly. Every
run so far has gotten back an identical ~22KB non-JSON bot-detection page
regardless of retries. Before concluding this is purely an IP-reputation
block, this script checks two things that would instead point to a code bug:

1. Does a DIFFERENT NSE report page (e.g. the "Bulk Deals Historical Data"
   page with a Custom date filter + CSV download) exist, and does it call a
   different API than the one nse_bulk.py assumes?
2. Are there other plausible endpoint/parameter variants worth trying, and do
   any of them get a real JSON response from this same runner/IP in this
   same run (which would rule out a blanket IP block, since everything here
   runs from the same IP within the same browser session)?

Writes artifacts/nse_bulk_diagnose/report.json and prints a human-readable
summary. Never touches nse_bulk.py/nse_block.py or the real pipeline.
"""
from __future__ import annotations
import json, os, time
from datetime import date, timedelta
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

END = date.fromisoformat(os.getenv('TARGET_DATE', '2026-08-31'))
START = END - timedelta(days=6)
OUT = Path('artifacts/nse_bulk_diagnose')
OUT.mkdir(parents=True, exist_ok=True)
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/139 Safari/537.36'

# Candidate human-facing pages that might render a bulk/block deals table --
# each could be backed by a different API than the one nse_bulk.py assumes.
CANDIDATE_PAGES = [
    'https://www.nseindia.com/market-data/large-deals',
    'https://www.nseindia.com/report-detail/display-bulk-and-block-deals',
    'https://www.nseindia.com/all-reports',
    'https://www.nseindia.com/market-data/securities-available-for-trading',
]


def browser():
    o = Options()
    for x in ('--headless=new', '--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu',
              '--window-size=1920,1080', '--disable-blink-features=AutomationControlled',
              f'--user-agent={UA}'):
        o.add_argument(x)
    o.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
    return webdriver.Chrome(options=o)


def drain_api_calls(d):
    """Every distinct nseindia.com/api/* request+response seen since the last drain."""
    seen = {}
    for item in d.get_log('performance'):
        try:
            msg = json.loads(item['message'])['message']
            method = msg.get('method', '')
            params = msg.get('params', {})
            if method == 'Network.responseReceived':
                resp = params.get('response', {})
                url = resp.get('url', '')
                if '/api/' in url and 'nseindia.com' in url:
                    req_id = params.get('requestId', '')
                    status = resp.get('status', 0)
                    try:
                        body = d.execute_cdp_cmd('Network.getResponseBody', {'requestId': req_id}).get('body', '')
                    except Exception as e:
                        body = f'<getResponseBody failed: {e}>'
                    seen[url] = {'status': status, 'bytes': len(body), 'preview': body[:200]}
        except Exception:
            pass
    return seen


def try_page(d, page_url):
    print(f'\n--- Visiting {page_url} ---')
    result = {'page': page_url, 'load_error': None, 'api_calls': {}}
    try:
        d.get(page_url)
        time.sleep(6)
        # Interact a little in case the table only loads on scroll/click
        try:
            d.execute_script('window.scrollTo(0, document.body.scrollHeight/2);')
            time.sleep(2)
        except Exception:
            pass
        result['api_calls'] = drain_api_calls(d)
        result['page_title'] = d.title
        result['final_url'] = d.current_url
    except Exception as e:
        result['load_error'] = str(e)
    for url, info in result['api_calls'].items():
        print(f"  [{info['status']}] {info['bytes']}B  {url}")
    if not result['api_calls']:
        print('  (no /api/ calls observed)')
    return result


def try_direct_variants(d):
    """A few plausible endpoint/param variants, called directly via fetch()
    from within the already-warmed browser session (same cookies/IP as the
    page visits above)."""
    variants = [
        ('current_as_used', f'https://www.nseindia.com/api/historical/bulk-deals?from={START:%d-%m-%Y}&to={END:%d-%m-%Y}'),
        ('no_dates', 'https://www.nseindia.com/api/historical/bulk-deals'),
        ('symbol_all', f'https://www.nseindia.com/api/historical/bulk-deals?symbol=ALL&from={START:%d-%m-%Y}&to={END:%d-%m-%Y}'),
        ('snapshot_current', 'https://www.nseindia.com/api/snapshot-capital-market-largedeal?index=bulk_deals'),
        ('large_deals_alt', f'https://www.nseindia.com/api/historical/large-deals?from={START:%d-%m-%Y}&to={END:%d-%m-%Y}&type=bulk'),
    ]
    js = """
    const [url, cb] = [arguments[0], arguments[arguments.length-1]];
    fetch(url, {credentials: 'include', headers: {'Accept': 'application/json, text/plain, */*'}})
      .then(async r => { const t = await r.text(); cb(JSON.stringify({status: r.status, bytes: t.length, preview: t.slice(0,200)})); })
      .catch(e => cb(JSON.stringify({status: 0, error: String(e)})));
    """
    results = {}
    print('\n--- Direct fetch() variants (same session/IP as above) ---')
    for name, url in variants:
        try:
            raw = json.loads(d.execute_async_script(js, url))
        except Exception as e:
            raw = {'status': 0, 'error': str(e)}
        results[name] = {'url': url, **raw}
        print(f"  [{raw.get('status')}] {name}: {raw.get('bytes', 0)}B  {url}")
    return results


def main():
    d = browser()
    report = {'target_date': str(END), 'pages': [], 'direct_variants': {}}
    try:
        for page_url in CANDIDATE_PAGES:
            report['pages'].append(try_page(d, page_url))
        report['direct_variants'] = try_direct_variants(d)
    finally:
        d.quit()
    (OUT / 'report.json').write_text(json.dumps(report, indent=2, default=str))
    print('\n=== Summary ===')
    any_real_json = False
    for pg in report['pages']:
        for url, info in pg['api_calls'].items():
            if info['bytes'] > 0 and info.get('preview', '').lstrip().startswith(('{', '[')):
                print(f"REAL JSON from page visit: {url} ({info['bytes']}B)")
                any_real_json = True
    for name, info in report['direct_variants'].items():
        if info.get('preview', '').lstrip().startswith(('{', '[')):
            print(f"REAL JSON from direct variant '{name}': {info['url']} ({info.get('bytes')}B)")
            any_real_json = True
    if not any_real_json:
        print('No variant tried in this run returned real JSON -- consistent with a block '
              'that affects every endpoint/page from this IP, not a wrong-endpoint bug.')


if __name__ == '__main__':
    main()
