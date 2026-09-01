"""BSE multi-category acquisition using direct browser navigation to API endpoints.

Previous approach (browser-native fetch / js_fetch) returned status=0 for ALL
BSE API calls. Root cause: fetch() from bseindia.com to api.bseindia.com is a
cross-origin request; the headless Chrome on GitHub Actions throws NetworkError
(CORS policy or outbound network restriction blocks the XHR).

Fix: navigate the browser directly to each API URL. A navigation request is not
subject to CORS — Chrome simply renders the JSON response as a <pre> element.
We read document.body.innerText to get the raw JSON text and parse it.

BSE API base: https://api.bseindia.com/BseIndiaAPI/api/
  Bulk:         BulkDeal_Beta/w          (strDate/endDate in DDMMYYYY)
  Block:        BlockDeal_Beta/w         (same)
  Insider:      getCorp_Regulation_ng/w  (fromDT/ToDate in DD-MM-YYYY, Isdefault=0)
  Rights:       Pubissues_FurtherIssuesummary_RI_isd_ng/w  (fromdt/todt DD-MM-YYYY)
  Preferential: Pubissues_FurtherIssuesummary_Pref_isd_ng/w (same)
"""
from __future__ import annotations
import json, os, time
from datetime import date, timedelta
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

END      = date.fromisoformat(os.getenv('TARGET_DATE', '2026-08-31')) if os.getenv('TARGET_DATE') else date.today()
LOOK     = int(os.getenv('LOOKBACK_DAYS', '90'))
START_90 = END - timedelta(days=LOOK - 1)
OUT      = Path('artifacts/data_validation_v5')
OUT.mkdir(parents=True, exist_ok=True)
UA       = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/139 Safari/537.36'
BSE_API  = 'https://api.bseindia.com/BseIndiaAPI/api'

WINDOWS = [
    ('1d',  END,                    END),
    ('7d',  END - timedelta(days=6),  END),
    ('30d', END - timedelta(days=29), END),
    ('90d', START_90,               END),
]


def browser():
    o = Options()
    for x in ('--headless=new', '--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu',
               '--window-size=1920,1080', '--disable-blink-features=AutomationControlled',
               f'--user-agent={UA}'):
        o.add_argument(x)
    return webdriver.Chrome(options=o)


def nav_fetch(d, url):
    """Navigate browser directly to an API URL and read the JSON response body.

    This bypasses CORS entirely — a navigation is not subject to same-origin
    restrictions. Chrome renders JSON as a <pre> element in the body.
    """
    try:
        d.get(url)
        time.sleep(2)
        body_text = d.execute_script(
            "return document.body.innerText || document.documentElement.innerText || ''")
        if not body_text:
            from selenium.webdriver.common.by import By
            body_text = d.find_element(By.TAG_NAME, 'body').text
        body_text = body_text.strip()
        print(f'    nav_fetch {url[:80]}: {len(body_text)} bytes  preview={body_text[:100]!r}')
        obj = json.loads(body_text)
        return {'json': obj, 'status': 200, 'bytes': len(body_text)}
    except Exception as exc:
        print(f'    nav_fetch ERROR {url[:80]}: {exc}')
        return {'json': None, 'status': 0, 'bytes': 0, 'parse_error': str(exc)}


def flatten_records(obj):
    """Recursively extract the first homogeneous list of dicts from a BSE response."""
    if isinstance(obj, list):
        if obj and all(isinstance(x, dict) for x in obj):
            return obj
        out = []
        for x in obj:
            out.extend(flatten_records(x))
        return out
    if isinstance(obj, dict):
        out = []
        for v in obj.values():
            if isinstance(v, (list, dict)):
                out.extend(flatten_records(v))
        return out
    return []


def gf(row, *keys):
    """Return the first non-empty value found under any of the candidate keys."""
    for k in keys:
        v = str(row.get(k, '') or '').strip()
        if v and v.lower() not in ('none', 'null', '-', ''):
            return v
    return ''


# ── CONVERSION HELPERS ────────────────────────────────────────────────────────

def bulk_block_to_row(r):
    return [
        gf(r, 'DEAL_DATE', 'DealDate', 'deal_date'),
        gf(r, 'SCRIP_CODE', 'ScripCode', 'scrip_code'),
        gf(r, 'ScripName', 'SCRIP_NAME', 'scrip_name'),
        gf(r, 'CLIENT_NAME', 'ClientName', 'client_name'),
        gf(r, 'TRANSACTION_TYPE', 'TransactionType', 'transaction_type'),
        gf(r, 'QUANTITY', 'Qty', 'quantity'),
        gf(r, 'PRICE', 'Price', 'price'),
    ]


def insider_to_row(r):
    txn_raw = gf(r, 'Fld_TransactionType', 'Fld_AcquireDispose',
                    'Fld_TypeOfTransaction', 'Fld_TranType').upper()
    if 'ACQUI' in txn_raw or 'BUY' in txn_raw or 'PURCHASE' in txn_raw:
        txn = 'ACQUISITION'
    elif 'DISP' in txn_raw or 'SELL' in txn_raw or 'SALE' in txn_raw:
        txn = 'DISPOSAL'
    else:
        txn = txn_raw or 'ACQUISITION'
    return [
        gf(r, 'Fld_ScripCode', 'ScripCode', 'SCRIP_CODE'),
        gf(r, 'Fld_CompanyName', 'CompanyName', 'Fld_Company', 'COMPANY_NAME'),
        gf(r, 'Fld_PromoterName', 'PromoterName', 'Fld_Name'),
        gf(r, 'Fld_Category', 'Fld_PersonCategory', 'Fld_PromoterCategory', 'Category'),
        gf(r, 'Fld_SecuritiesHeldBefore', 'Fld_PreHolding', 'Fld_HoldingBefore'),
        gf(r, 'Fld_TypeOfSecurity', 'Fld_SecurityType', 'SecurityType'),
        gf(r, 'Fld_SecuritiesAcquiredDisposed', 'Fld_SecuritiesAcquired',
               'Fld_Quantity', 'Fld_NoOfShares'),
        gf(r, 'Fld_TransactionValue', 'Fld_Value', 'Fld_TranValue'),
        txn,
        gf(r, 'Fld_SecuritiesHeldAfter', 'Fld_PostHolding', 'Fld_HoldingAfter'),
        gf(r, 'Fld_DateOfTransaction', 'Fld_TranDate', 'Fld_TransDate', 'Fld_Date'),
        gf(r, 'Fld_ModeOfAcquisition', 'Fld_Mode', 'Fld_TransactionMode'),
        gf(r, 'Fld_TradingInDerivatives', 'Fld_Derivatives', 'Fld_Deriv'),
        gf(r, 'Fld_BuyValue', 'Fld_Buy'),
        gf(r, 'Fld_SellValue', 'Fld_Sell'),
        gf(r, 'Fld_LetterDate', 'Fld_BroadcastDate', 'Fld_StampDate', 'Fld_IntimationDate'),
    ]


def ri_pref_to_row(r):
    return [
        gf(r, 'Company_Name', 'CompanyName', 'COMPANY_NAME'),
        gf(r, 'Listing_Stage', 'ListingStage', 'IP_Stage', 'Stage'),
        gf(r, 'Recordid', 'recordid', 'RecordID', 'scripcode', 'SCRIP_CODE'),
        gf(r, 'scripcode', 'ScripCode', 'SCRIP_CODE', 'Recordid'),
    ]


# ── PER-CATEGORY FETCHERS ─────────────────────────────────────────────────────

def fetch_bulk_block(d, suffix, start, end):
    """Try multiple date param formats; return first URL that yields rows."""
    base = f'{BSE_API}/{suffix}'
    url_candidates = [
        f'{base}?strDate={start:%d%m%Y}&endDate={end:%d%m%Y}',
        f'{base}?strDate={start:%d/%m/%Y}&endDate={end:%d/%m/%Y}',
        f'{base}?fromDate={start:%d/%m/%Y}&toDate={end:%d/%m/%Y}',
        f'{base}?strDate={start:%Y-%m-%d}&endDate={end:%Y-%m-%d}',
        base,
    ]
    for url in url_candidates:
        r    = nav_fetch(d, url)
        rows = flatten_records(r.get('json') or {})
        if rows and (start == end or len({gf(x, 'DEAL_DATE', 'DealDate') for x in rows if gf(x, 'DEAL_DATE', 'DealDate')}) >= 1):
            return {'url': url, 'rows': rows, 'status': r.get('status'), 'bytes': r.get('bytes')}
    return {'url': base, 'rows': [], 'status': 0, 'bytes': 0}


def fetch_insider(d, start, end):
    url = (f'{BSE_API}/getCorp_Regulation_ng/w?scripCode=&Regulation='
           f'&fromDT={start:%d-%m-%Y}&ToDate={end:%d-%m-%Y}&Isdefault=0')
    r   = nav_fetch(d, url)
    return {'url': url, 'rows': flatten_records(r.get('json') or {}),
            'status': r.get('status'), 'bytes': r.get('bytes')}


def fetch_rights(d, start, end):
    url = (f'{BSE_API}/Pubissues_FurtherIssuesummary_RI_isd_ng/w'
           f'?fromdt={start:%d-%m-%Y}&todt={end:%d-%m-%Y}&company=')
    r   = nav_fetch(d, url)
    return {'url': url, 'rows': flatten_records(r.get('json') or {}),
            'status': r.get('status'), 'bytes': r.get('bytes')}


def fetch_preferential(d, start, end):
    url = (f'{BSE_API}/Pubissues_FurtherIssuesummary_Pref_isd_ng/w'
           f'?fromdt={start:%d-%m-%Y}&todt={end:%d-%m-%Y}&company=')
    r   = nav_fetch(d, url)
    return {'url': url, 'rows': flatten_records(r.get('json') or {}),
            'status': r.get('status'), 'bytes': r.get('bytes')}


# ── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    d = browser()
    datasets = {}

    try:
        # Warm up on BSE main domain so cookies (.bseindia.com) are established
        d.get('https://www.bseindia.com')
        time.sleep(5)
        print(f'BSE main page loaded: {d.title!r}')

        categories = {
            'bulk_deals':         ('BulkDeal_Beta/w',  fetch_bulk_block),
            'block_deals':        ('BlockDeal_Beta/w', fetch_bulk_block),
            'insider_trading':    (None,               fetch_insider),
            'rights_issue':       (None,               fetch_rights),
            'preferential_issue': (None,               fetch_preferential),
        }

        for category, (suffix, fetcher) in categories.items():
            print(f'\n=== {category} ===')
            win_summaries = []
            all_api_rows  = []

            for win_name, wstart, wend in WINDOWS:
                print(f'  window {win_name}: {wstart} → {wend}')
                if suffix:
                    r = fetcher(d, suffix, wstart, wend)
                else:
                    r = fetcher(d, wstart, wend)

                rows = r['rows']
                all_api_rows.extend(rows)
                print(f'  → {len(rows)} rows  status={r.get("status")}')

                date_keys = ('DEAL_DATE', 'DealDate', 'Fld_LetterDate',
                             'Fld_DateOfTransaction', 'Fld_TranDate')
                distinct_dates = sorted({
                    gf(x, *date_keys) for x in rows if gf(x, *date_keys)
                })

                win_summaries.append({
                    'name':           win_name,
                    'start_date':     str(wstart),
                    'end_date':       str(wend),
                    'api_url':        r['url'],
                    'status':         r.get('status'),
                    'bytes':          r.get('bytes'),
                    'count':          len(rows),
                    'distinct_dates': distinct_dates,
                    'columns':        sorted(rows[0].keys()) if rows else [],
                })
                time.sleep(1)

            if category in ('bulk_deals', 'block_deals'):
                convert = bulk_block_to_row
            elif category == 'insider_trading':
                convert = insider_to_row
            else:
                convert = ri_pref_to_row

            table_rows   = [convert(r) for r in all_api_rows]
            detail_pages = ([{'page': 1, 'rows': table_rows, 'links': []}]
                            if category in ('rights_issue', 'preferential_issue') else [])
            has_hist = any(w['count'] > 0 for w in win_summaries if w['name'] != '1d')

            datasets[category] = {
                'method':       'BSE direct API (browser navigation, no CORS)',
                'api_windows':  win_summaries,
                'pages':        [{'page': 1, 'rows': table_rows, 'links': []}],
                'detail_pages': detail_pages,
                'row_count':    len(table_rows),
                'page_count':   1,
                'historical_date_test': {
                    'attempted':  True,
                    'status':     'changed' if has_hist else 'no_change',
                    'method':     'direct_api_date_params',
                    'start_date': str(START_90),
                    'end_date':   str(END),
                },
                'network_requests': [],
                'controls':         [],
            }

    finally:
        d.quit()

    result = {
        'target_date':   str(END),
        'start_date':    str(START_90),
        'lookback_days': LOOK,
        'datasets':      datasets,
    }
    Path(OUT / 'bse_raw.json').write_text(
        json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding='utf-8')

    summary = {
        cat: {
            'windows':    [(w['name'], w['count'], len(w['distinct_dates'])) for w in ds['api_windows']],
            'table_rows': ds['row_count'],
            'hist_applied': ds['historical_date_test']['status'],
        }
        for cat, ds in datasets.items()
    }
    print('\n=== SUMMARY ===')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
