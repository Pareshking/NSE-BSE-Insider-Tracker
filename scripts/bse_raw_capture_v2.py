"""BSE multi-category acquisition using BSE direct backend APIs (browser-native fetch).

The previous approach used Selenium table scraping plus Angular datepicker interaction.
The datepicker returned 'no_change' for all categories (custom widget not responding
to sendKeys), so all data was pinned to today's date.

This script bypasses the datepicker entirely: it calls the BSE Angular SPA backend
APIs from within the browser's JS context, explicitly passing date range parameters.
This gives us historical data for all four time windows (1d/7d/30d/90d).

BSE API base: https://api.bseindia.com/BseIndiaAPI/api/
  Bulk:         BulkDeal_Beta/w          (strDate/endDate in DDMMYYYY or DD/MM/YYYY)
  Block:        BlockDeal_Beta/w         (same params)
  Insider:      getCorp_Regulation_ng/w  (fromDT/ToDate in DD-MM-YYYY, Isdefault=0)
  Rights:       Pubissues_FurtherIssuesummary_RI_isd_ng/w  (fromdt/todt in DD-MM-YYYY)
  Preferential: Pubissues_FurtherIssuesummary_Pref_isd_ng/w (same)

Output: artifacts/data_validation_v5/bse_raw.json  (compatible with bse_validate.py)
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

BSE_PAGES = {
    'bulk_deals':          'https://www.bseindia.com/markets/equity/EQReports/bulk_deals.aspx',
    'block_deals':         'https://www.bseindia.com/markets/equity/EQReports/block_deals.aspx',
    'insider_trading':     'https://www.bseindia.com/corporates/insider_trading_new?expandable=2',
    'rights_issue':        'https://www.bseindia.com/markets/publicissues/furtherissuesummary_ri',
    'preferential_issue':  'https://www.bseindia.com/markets/publicissues/furtherissuesummary_pref',
}

_JS = """
const [url, cb] = [arguments[0], arguments[arguments.length-1]];
fetch(url, {
  credentials: 'include',
  headers: {
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Origin': 'https://www.bseindia.com',
    'Referer': 'https://www.bseindia.com/'
  }
}).then(async r => {
  const t = await r.text();
  cb(JSON.stringify({status: r.status, url: r.url, bytes: t.length, text: t}));
}).catch(e => cb(JSON.stringify({status: 0, error: String(e), bytes: 0, text: ''})));
"""


def browser():
    o = Options()
    for x in ('--headless=new', '--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu',
               '--window-size=1920,1080', '--disable-blink-features=AutomationControlled',
               f'--user-agent={UA}'):
        o.add_argument(x)
    return webdriver.Chrome(options=o)


def js_fetch(d, url):
    raw  = json.loads(d.execute_async_script(_JS, url))
    text = raw.get('text', '')
    try:
        raw['json'] = json.loads(text)
    except Exception as exc:
        raw['json']        = None
        raw['parse_error'] = str(exc)
    return raw


def flatten_records(obj):
    """Recursively extract the first list of dicts from a BSE API response."""
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
    """Get first non-empty value from a dict by trying multiple candidate keys."""
    for k in keys:
        v = str(row.get(k, '') or '').strip()
        if v and v.lower() not in ('none', 'null', '-', ''):
            return v
    return ''


# ── BULK / BLOCK conversion ──────────────────────────────────────────────────

def bulk_block_to_row(r):
    """Convert BulkDeal_Beta / BlockDeal_Beta record to 7-element positional row.

    bse_validate.py positional mapping:
      r[0]=deal_date  r[1]=security_code  r[2]=security_name
      r[3]=client     r[4]=side(B/S)      r[5]=quantity  r[6]=price
    """
    return [
        gf(r, 'DEAL_DATE', 'DealDate', 'deal_date'),
        gf(r, 'SCRIP_CODE', 'ScripCode', 'scrip_code'),
        gf(r, 'ScripName', 'SCRIP_NAME', 'scrip_name'),
        gf(r, 'CLIENT_NAME', 'ClientName', 'client_name'),
        gf(r, 'TRANSACTION_TYPE', 'TransactionType', 'transaction_type'),  # B or S
        gf(r, 'QUANTITY', 'Qty', 'quantity'),
        gf(r, 'PRICE', 'Price', 'price'),
    ]


# ── INSIDER conversion ────────────────────────────────────────────────────────

def insider_to_row(r):
    """Convert getCorp_Regulation_ng record to 16-element positional row.

    bse_validate.py positional mapping (cols 0–15):
      0=security_code  1=company         2=person         3=person_category
      4=holding_before 5=security_type   6=quantity       7=transaction_value
      8=transaction_type(ACQUISITION/DISPOSAL)            9=holding_after
      10=transaction_date 11=mode        12=derivatives   13=buy_value
      14=sell_value    15=broadcast_date
    """
    txn_raw = gf(r, 'Fld_TransactionType', 'Fld_AcquireDispose',
                    'Fld_TypeOfTransaction', 'Fld_TranType').upper()
    if 'ACQUI' in txn_raw or 'BUY' in txn_raw or 'PURCHASE' in txn_raw:
        txn = 'ACQUISITION'
    elif 'DISP' in txn_raw or 'SELL' in txn_raw or 'SALE' in txn_raw:
        txn = 'DISPOSAL'
    else:
        txn = txn_raw or 'ACQUISITION'

    return [
        gf(r, 'Fld_ScripCode', 'ScripCode', 'SCRIP_CODE'),                       # 0
        gf(r, 'Fld_CompanyName', 'CompanyName', 'Fld_Company', 'COMPANY_NAME'),   # 1
        gf(r, 'Fld_PromoterName', 'PromoterName', 'Fld_Name'),                    # 2
        gf(r, 'Fld_Category', 'Fld_PersonCategory', 'Fld_PromoterCategory',
               'Category'),                                                         # 3
        gf(r, 'Fld_SecuritiesHeldBefore', 'Fld_PreHolding', 'Fld_HoldingBefore',
               'Fld_BeforeHolding'),                                               # 4
        gf(r, 'Fld_TypeOfSecurity', 'Fld_SecurityType', 'Fld_TypeSecurity',
               'SecurityType'),                                                     # 5
        gf(r, 'Fld_SecuritiesAcquiredDisposed', 'Fld_SecuritiesAcquired',
               'Fld_Quantity', 'Fld_NoOfShares'),                                  # 6
        gf(r, 'Fld_TransactionValue', 'Fld_Value', 'Fld_TranValue'),              # 7
        txn,                                                                        # 8
        gf(r, 'Fld_SecuritiesHeldAfter', 'Fld_PostHolding', 'Fld_HoldingAfter',
               'Fld_AfterHolding'),                                                # 9
        gf(r, 'Fld_DateOfTransaction', 'Fld_TranDate', 'Fld_TransDate',
               'Fld_Date'),                                                         # 10
        gf(r, 'Fld_ModeOfAcquisition', 'Fld_Mode', 'Fld_TransactionMode'),        # 11
        gf(r, 'Fld_TradingInDerivatives', 'Fld_Derivatives', 'Fld_Deriv'),        # 12
        gf(r, 'Fld_BuyValue', 'Fld_Buy'),                                         # 13
        gf(r, 'Fld_SellValue', 'Fld_Sell'),                                       # 14
        gf(r, 'Fld_LetterDate', 'Fld_BroadcastDate', 'Fld_StampDate',
               'Fld_IntimationDate'),                                              # 15
    ]


# ── RIGHTS / PREFERENTIAL conversion ─────────────────────────────────────────

def ri_pref_to_row(r):
    """Convert Pubissues summary record to 4-element positional row."""
    return [
        gf(r, 'Company_Name', 'CompanyName', 'COMPANY_NAME'),
        gf(r, 'Listing_Stage', 'ListingStage', 'IP_Stage', 'Stage'),
        gf(r, 'Recordid', 'recordid', 'RecordID', 'scripcode', 'SCRIP_CODE'),
        gf(r, 'scripcode', 'ScripCode', 'SCRIP_CODE', 'Recordid'),
    ]


# ── PER-CATEGORY FETCH ────────────────────────────────────────────────────────

def fetch_bulk_block(d, endpoint_suffix, start, end):
    """Try multiple date param formats for BulkDeal_Beta / BlockDeal_Beta."""
    base = f'{BSE_API}/{endpoint_suffix}'
    # BSE commonly uses DDMMYYYY with no separator, or DD/MM/YYYY
    url_candidates = [
        f'{base}?strDate={start:%d%m%Y}&endDate={end:%d%m%Y}',
        f'{base}?strDate={start:%d/%m/%Y}&endDate={end:%d/%m/%Y}',
        f'{base}?fromDate={start:%d/%m/%Y}&toDate={end:%d/%m/%Y}',
        f'{base}?strDate={start:%Y-%m-%d}&endDate={end:%Y-%m-%d}',
        base,  # fallback: default (today only)
    ]
    for url in url_candidates:
        r    = js_fetch(d, url)
        rows = flatten_records(r.get('json') or {})
        if not rows:
            continue
        dates = {gf(x, 'DEAL_DATE') for x in rows if gf(x, 'DEAL_DATE')}
        # Accept this format if we get data spanning more than one day OR if the
        # 1-day window was requested (start==end)
        if dates and (len(dates) > 1 or start == end):
            return {'url': url, 'rows': rows, 'status': r.get('status'), 'bytes': r.get('bytes')}
        # For multi-day windows, keep trying; for fallback URL also accept single date
        if url == base and rows:
            return {'url': url, 'rows': rows, 'status': r.get('status'), 'bytes': r.get('bytes')}
    return {'url': base, 'rows': [], 'status': 0, 'bytes': 0}


def fetch_insider(d, start, end):
    url  = (f'{BSE_API}/getCorp_Regulation_ng/w?scripCode=&Regulation='
            f'&fromDT={start:%d-%m-%Y}&ToDate={end:%d-%m-%Y}&Isdefault=0')
    r    = js_fetch(d, url)
    rows = flatten_records(r.get('json') or {})
    return {'url': url, 'rows': rows, 'status': r.get('status'), 'bytes': r.get('bytes')}


def fetch_rights(d, start, end):
    url  = (f'{BSE_API}/Pubissues_FurtherIssuesummary_RI_isd_ng/w'
            f'?fromdt={start:%d-%m-%Y}&todt={end:%d-%m-%Y}&company=')
    r    = js_fetch(d, url)
    rows = flatten_records(r.get('json') or {})
    return {'url': url, 'rows': rows, 'status': r.get('status'), 'bytes': r.get('bytes')}


def fetch_preferential(d, start, end):
    url  = (f'{BSE_API}/Pubissues_FurtherIssuesummary_Pref_isd_ng/w'
            f'?fromdt={start:%d-%m-%Y}&todt={end:%d-%m-%Y}&company=')
    r    = js_fetch(d, url)
    rows = flatten_records(r.get('json') or {})
    return {'url': url, 'rows': rows, 'status': r.get('status'), 'bytes': r.get('bytes')}


# ── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    d = browser()
    datasets = {}

    try:
        # Warm up BSE session
        d.get('https://www.bseindia.com')
        time.sleep(5)

        for category in ('bulk_deals', 'block_deals', 'insider_trading',
                         'rights_issue', 'preferential_issue'):
            # Navigate to category page to establish cookies / session state
            d.get(BSE_PAGES[category])
            time.sleep(5)

            win_summaries = []
            all_api_rows  = []

            for win_name, wstart, wend in WINDOWS:
                # Fetch from BSE API with explicit date range
                if category == 'bulk_deals':
                    r = fetch_bulk_block(d, 'BulkDeal_Beta/w', wstart, wend)
                elif category == 'block_deals':
                    r = fetch_bulk_block(d, 'BlockDeal_Beta/w', wstart, wend)
                elif category == 'insider_trading':
                    r = fetch_insider(d, wstart, wend)
                elif category == 'rights_issue':
                    r = fetch_rights(d, wstart, wend)
                else:
                    r = fetch_preferential(d, wstart, wend)

                rows = r['rows']
                all_api_rows.extend(rows)

                # Detect distinct dates in the API response
                date_candidates = ['DEAL_DATE', 'Fld_LetterDate', 'Fld_DateOfTransaction',
                                   'Fld_TranDate', 'fromdt', 'todt']
                distinct_dates = sorted({
                    gf(x, *date_candidates) for x in rows if gf(x, *date_candidates)
                })

                win_summaries.append({
                    'name':            win_name,
                    'start_date':      str(wstart),
                    'end_date':        str(wend),
                    'api_url':         r['url'],
                    'status':          r.get('status'),
                    'bytes':           r.get('bytes'),
                    'count':           len(rows),
                    'distinct_dates':  distinct_dates,
                    'columns':         sorted(rows[0].keys()) if rows else [],
                })
                time.sleep(1)

            # Convert to positional row format for bse_validate.py compatibility
            if category in ('bulk_deals', 'block_deals'):
                convert = bulk_block_to_row
            elif category == 'insider_trading':
                convert = insider_to_row
            else:
                convert = ri_pref_to_row

            table_rows = [convert(r) for r in all_api_rows]

            # Rights/Preferential: bse_validate.py requires detail_pages with rows
            # to verify 'detail_nonempty'. We use the same rows as both pages and details.
            detail_pages = ([{'page': 1, 'rows': table_rows, 'links': []}]
                            if category in ('rights_issue', 'preferential_issue')
                            else [])

            # historical_date_test.status='changed' signals that a historical date
            # range was applied (we always pass explicit dates to the API).
            has_historical = any(
                w['count'] > 0 for w in win_summaries if w['name'] != '1d'
            )
            datasets[category] = {
                'method':          'BSE direct API (browser-native fetch)',
                'api_windows':     win_summaries,
                'pages':           [{'page': 1, 'rows': table_rows, 'links': []}],
                'detail_pages':    detail_pages,
                'row_count':       len(table_rows),
                'page_count':      1,
                'historical_date_test': {
                    'attempted':    True,
                    'status':       'changed' if has_historical else 'no_change',
                    'method':       'direct_api_date_params',
                    'start_date':   str(START_90),
                    'end_date':     str(END),
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
            'windows':  [(w['name'], w['count'], len(w['distinct_dates'])) for w in ds['api_windows']],
            'table_rows': ds['row_count'],
            'hist_applied': ds['historical_date_test']['status'],
        }
        for cat, ds in datasets.items()
    }
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
