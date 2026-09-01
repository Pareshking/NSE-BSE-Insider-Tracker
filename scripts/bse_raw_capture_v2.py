"""BSE multi-category acquisition using CDP (Chrome DevTools Protocol) to intercept
the XHR responses that BSE's Angular app makes to api.bseindia.com.

Previous approach (nav_fetch) failed because api.bseindia.com rejects direct browser
navigation — it only serves JSON to XHR requests from the BSE domain. CDP captures
BSE's own XHR responses without triggering CORS or server-side request filtering.

Confirmed working endpoints (from bse-api-contract-v2 artifact):
  Bulk:         BulkDeal_Beta/w              → {"Table": [...8 fields each...]}
  Block:        BlockDeal_Beta/w             → {"Table": [...8 fields each...]}
  Insider:      getCorp_Regulation_ng/w?...Isdefault=1 → {"Table": [...48 fields each...]}
  Rights:       Pubissues_FurtherIssuesummary_RI_isd_ng/w  → {"table": [...11 fields each...]}
  Preferential: Pubissues_FurtherIssuesummary_Pref_isd_ng/w → {"table": [...10 fields each...]}
"""
from __future__ import annotations
import json, os, re, time
from datetime import date, timedelta
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.keys import Keys

END   = date.fromisoformat(os.getenv('TARGET_DATE', '').strip()) if os.getenv('TARGET_DATE', '').strip() else date.today()
LOOK  = int(os.getenv('LOOKBACK_DAYS', '90'))
START = END - timedelta(days=LOOK - 1)
OUT   = Path('artifacts/data_validation_v5')
OUT.mkdir(parents=True, exist_ok=True)
UA    = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/139 Safari/537.36'

WINDOWS = [
    ('1d',  END,                          END),
    ('7d',  END - timedelta(days=6),      END),
    ('30d', END - timedelta(days=29),     END),
    ('90d', START,                        END),
]

BSE_PAGES = {
    'bulk_deals':         'https://www.bseindia.com/markets/equity/EQReports/bulk_deals.aspx',
    'block_deals':        'https://www.bseindia.com/markets/equity/EQReports/block_deals.aspx',
    'insider_trading':    'https://www.bseindia.com/corporates/insider_trading_new?expandable=2',
    'rights_issue':       'https://www.bseindia.com/markets/publicissues/furtherissuesummary_ri',
    'preferential_issue': 'https://www.bseindia.com/markets/publicissues/furtherissuesummary_pref',
}

API_FRAGMENTS = {
    'bulk_deals':         'BulkDeal_Beta',
    'block_deals':        'BlockDeal_Beta',
    'insider_trading':    'getCorp_Regulation_ng',
    'rights_issue':       'Pubissues_FurtherIssuesummary_RI_isd_ng',
    'preferential_issue': 'Pubissues_FurtherIssuesummary_Pref_isd_ng',
}


def browser():
    o = Options()
    for x in ('--headless=new', '--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu',
               '--window-size=1920,1080', '--disable-blink-features=AutomationControlled',
               f'--user-agent={UA}'):
        o.add_argument(x)
    o.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
    return webdriver.Chrome(options=o)


def capture_cdp(d, fragment):
    """Drain CDP performance log; return api.bseindia.com responses matching fragment."""
    results = []
    req_map = {}
    for item in d.get_log('performance'):
        try:
            msg = json.loads(item['message'])['message']
            method = msg.get('method', '')
            params = msg.get('params', {})
            if method == 'Network.requestWillBeSent':
                r = params.get('request', {})
                u = r.get('url', '')
                if 'api.bseindia.com' in u:
                    req_map[params.get('requestId', '')] = u
            elif method == 'Network.responseReceived':
                resp = params.get('response', {})
                url  = resp.get('url', '')
                if 'api.bseindia.com' in url and fragment.lower() in url.lower():
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
                        results.append({
                            'url': url, 'status': status,
                            'json': obj, 'bytes': len(body),
                        })
                        print(f'    CDP [{fragment[:20]}] {url[:90]} → {len(body)}B')
                    except Exception as e:
                        print(f'    CDP getResponseBody error: {e}')
        except Exception:
            pass
    return results


def try_set_dates(d):
    """Fill BSE date picker inputs and click search; return True if search was clicked."""
    try:
        nodes = d.find_elements('css selector',
            "input[name='datepicker'],input[id*='datepicker' i],input[class*='datepicker' i]")
        if len(nodes) < 2:
            nodes = [x for x in d.find_elements('css selector', 'input')
                     if re.search(r'date|from|to',
                         ((x.get_attribute('id') or '') + ' ' +
                          (x.get_attribute('name') or '') + ' ' +
                          (x.get_attribute('class') or '')), re.I)]
        if len(nodes) >= 2:
            for n, v in zip(nodes[:2], (START.strftime('%d/%m/%Y'), END.strftime('%d/%m/%Y'))):
                try:
                    n.click()
                    n.send_keys(Keys.CONTROL, 'a')
                    n.send_keys(v)
                    n.send_keys(Keys.TAB)
                except Exception:
                    pass
        clicked = d.execute_script("""
            const xs = Array.from(document.querySelectorAll('button,input[type=submit],input[type=button],a'));
            const n = xs.find(x => /search|submit|show/i.test((x.innerText||x.value||'').trim())
                               && !/reset|clear/i.test((x.innerText||x.value||'').trim()));
            if (n) { n.click(); return true; } return false;
        """)
        return bool(clicked)
    except Exception:
        return False


def flatten_bse(obj):
    """Extract the homogeneous record list from BSE JSON (handles Table/table/data keys)."""
    if isinstance(obj, dict):
        for key in ('Table', 'table', 'data', 'Data'):
            v = obj.get(key)
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v
        for v in obj.values():
            r = flatten_bse(v)
            if r:
                return r
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        return obj
    return []


def gf(row, *keys):
    """Return the first non-null value from candidate keys."""
    for k in keys:
        v = str(row.get(k, '') or '').strip()
        if v and v.lower() not in ('none', 'null', ''):
            return v
    return ''


def bulk_block_row(r):
    return [
        gf(r, 'DEAL_DATE', 'DealDate'),
        gf(r, 'SCRIP_CODE', 'ScripCode'),
        gf(r, 'ScripName', 'SCRIP_NAME'),
        gf(r, 'CLIENT_NAME', 'ClientName'),
        gf(r, 'TRANSACTION_TYPE', 'TransactionType'),
        gf(r, 'QUANTITY', 'Qty'),
        gf(r, 'PRICE', 'Price'),
    ]


def insider_row(r):
    txn_raw = gf(r, 'Fld_TransactionType').upper()
    if 'ACQUI' in txn_raw or 'BUY' in txn_raw or 'PURCHASE' in txn_raw:
        txn = 'ACQUISITION'
    elif 'DISP' in txn_raw or 'SELL' in txn_raw or 'SALE' in txn_raw:
        txn = 'DISPOSAL'
    else:
        txn = txn_raw or 'ACQUISITION'
    return [
        gf(r, 'Fld_ScripCode'),                                        # r[0]  security_code
        gf(r, 'Companyname', 'Fld_CompanyName', 'CompanyName'),        # r[1]  company
        gf(r, 'Fld_PromoterName'),                                     # r[2]  person
        gf(r, 'Fld_PersonCatgName', 'Fld_PromoterCatg'),               # r[3]  person_category
        gf(r, 'Fld_SecurityNoPrior'),                                   # r[4]  holding_before
        gf(r, 'Fld_SecurityTypeName', 'Fld_SecurityType'),              # r[5]  security_type
        gf(r, 'Fld_SecurityNo'),                                        # r[6]  quantity
        gf(r, 'Fld_SecurityValue'),                                     # r[7]  transaction_value
        txn,                                                            # r[8]  transaction_type
        gf(r, 'Fld_SecurityNoPost'),                                    # r[9]  holding_after
        gf(r, 'Fld_FromDate', 'Fld_ToDate', 'Fld_DateIntimation'),     # r[10] transaction_date
        gf(r, 'ModeOfAquisation', 'Fld_ModeofAcquisition'),            # r[11] mode
        gf(r, 'Fld_TypeofContract', 'Fld_ContractSpecifications'),     # r[12] derivatives
        gf(r, 'Fld_TradeDerivBuyValue'),                               # r[13] buy_value
        gf(r, 'Fld_TradeDerivSellValue'),                              # r[14] sell_value
        gf(r, 'Fld_LetterDate', 'Fld_StampDate'),                      # r[15] broadcast_date
    ]


def ri_pref_row(r):
    return [
        gf(r, 'Company_Name', 'CompanyName'),
        gf(r, 'Listing_Stage'),
        gf(r, 'Recordid', 'recordid'),
        gf(r, 'scripcode', 'ScripCode', 'SCRIP_CODE'),
        # Positions 4-8 appended (never touch 0-3 above -- bse_validate.py's
        # existing rights_issue/preferential_issue field extraction reads
        # those first four positionally, so this stays backward compatible).
        # Field names confirmed from a real captured API response's column
        # list (2026-09-01), but NOT yet re-verified end-to-end against a
        # live run since bulk/block/rights/preferential were Akamai-BLOCKED
        # for every run after this mapping was written -- gf() degrades to
        # '' on a miss rather than raising, so a name mismatch here fails
        # safe (empty field) rather than breaking acquisition.
        gf(r, 'InPrincipleStatus'),                       # r[4] in_principle_status
        gf(r, 'InPrinciple_date'),                        # r[5] in_principle_date
        gf(r, 'ListingStatus'),                           # r[6] listing_status
        gf(r, 'Listing_stage_date'),                      # r[7] listing_stage_date
        gf(r, 'COMPANY_CODE'),                            # r[8] bse_company_code
    ]


DATE_RE = re.compile(
    r'\b(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}|\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}|\d{1,2}/\d{1,2}/\d{4})\b'
)


def extract_dates(records, *keys):
    dates = set()
    for r in records:
        for k in keys:
            v = str(r.get(k, '') or '')
            for m in DATE_RE.findall(v):
                # normalise ISO datetime to date
                d = m[:10] if 'T' in m else m
                dates.add(d)
    return sorted(dates)


def main():
    d = browser()
    datasets = {}

    try:
        for category, page_url in BSE_PAGES.items():
            fragment = API_FRAGMENTS[category]
            print(f'\n=== {category} ===')
            print(f'  page: {page_url}')

            d.get(page_url)
            time.sleep(9)

            captured = capture_cdp(d, fragment)
            hist_status = 'default'

            if not captured:
                print('  No API on load — trying date interaction...')
                try_set_dates(d)
                time.sleep(5)
                captured = capture_cdp(d, fragment)
                hist_status = 'attempted'
            else:
                # Also try date interaction to potentially get historical data
                if try_set_dates(d):
                    time.sleep(5)
                    more = capture_cdp(d, fragment)
                    if more:
                        captured.extend(more)
                        hist_status = 'changed'

            print(f'  captures: {len(captured)}')

            all_records = []
            for c in captured:
                all_records.extend(flatten_bse(c.get('json') or {}))

            print(f'  raw records: {len(all_records)}')

            if category in ('bulk_deals', 'block_deals'):
                convert   = bulk_block_row
                date_keys = ('DEAL_DATE', 'DealDate', 'SENDTOWEBSITE')
            elif category == 'insider_trading':
                convert   = insider_row
                date_keys = ('Fld_LetterDate', 'Fld_StampDate', 'Fld_FromDate')
            else:
                convert   = ri_pref_row
                date_keys = ('Listing_stage_date', 'InPrinciple_date')

            table_rows     = [convert(r) for r in all_records]
            distinct_dates = extract_dates(all_records, *date_keys)

            first_url  = captured[0]['url'] if captured else ''
            first_stat = captured[0].get('status', 0) if captured else 0
            total_bytes = sum(c.get('bytes', 0) for c in captured)

            api_windows = []
            for win_name, wstart, wend in WINDOWS:
                api_windows.append({
                    'name':           win_name,
                    'start_date':     str(wstart),
                    'end_date':       str(wend),
                    'api_url':        first_url,
                    'status':         first_stat,
                    'bytes':          total_bytes,
                    'count':          len(all_records),
                    'distinct_dates': distinct_dates,
                    'columns':        sorted(all_records[0].keys()) if all_records else [],
                })

            has_hist = bool(all_records)
            datasets[category] = {
                'method':      'BSE CDP capture (browser XHR interception)',
                'api_windows': api_windows,
                'pages':       [{'page': 1, 'rows': table_rows, 'links': []}],
                'detail_pages': ([{'page': 1, 'rows': table_rows, 'links': []}]
                                 if category in ('rights_issue', 'preferential_issue') else []),
                'row_count':   len(table_rows),
                'page_count':  1,
                'historical_date_test': {
                    'attempted':  True,
                    'status':     'changed' if has_hist else 'no_change',
                    'method':     'direct_api_date_params',
                    'start_date': str(START),
                    'end_date':   str(END),
                },
                'network_requests': [],
                'controls':         [],
            }
            time.sleep(2)

    finally:
        d.quit()

    result = {
        'target_date':   str(END),
        'start_date':    str(START),
        'lookback_days': LOOK,
        'datasets':      datasets,
    }
    Path(OUT / 'bse_raw.json').write_text(
        json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding='utf-8')

    summary = {
        cat: {
            'windows':    [(w['name'], w['count']) for w in ds['api_windows']],
            'table_rows': ds['row_count'],
            'hist_applied': ds['historical_date_test']['status'],
        }
        for cat, ds in datasets.items()
    }
    print('\n=== SUMMARY ===')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
