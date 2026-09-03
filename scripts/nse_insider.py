"""NSE Insider Trading acquisition via the real PIT filings API + XBRL detail parsing.

Two prior root causes, now both fixed:

1. The endpoint being called was /api/corporates-pit (returns empty 28-byte JSON
   for every date range). The ACTUAL endpoint the live page uses is
   /api/corporates-pit-gg?index=equities, which works with a plain HTTP GET and
   a normal User-Agent -- no Selenium, no cookies, no Akamai session needed at
   all. Verified directly: this endpoint consistently returns ~2000+ real
   filing records.

2. That list endpoint only returns filing-level metadata (company, symbol,
   broadcast time, and a link to the disclosure's XBRL XML) -- it does NOT
   contain the actual transaction fields (person, category, quantities). The
   real insider-trading data (CategoryOfPerson, NameOfThePerson,
   SecuritiesAcquiredOrDisposedTransactionType, quantities, dates) lives inside
   each filing's per-disclosure XBRL XML file (linked via `xmlFileName`), under
   the `in-bse-co:` namespace (NSE and BSE share the same SEBI PIT XBRL
   taxonomy). Each filing can contain multiple disclosure blocks (one per
   insider named in that filing).

This script fetches the filing list, filters to the lookback window, then
fetches+parses each filing's XML concurrently to build real per-transaction
rows with a personCategory field (Promoter / Promoter Group / KMP / Designated
Person / Director / Trust / etc.), matching what nse_validate.py expects.
"""
from __future__ import annotations
import json, os, re, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta, datetime
from pathlib import Path
import requests

BASE     = 'https://www.nseindia.com'
LIST_URL = f'{BASE}/api/corporates-pit-gg?index=equities'
TARGET   = date.fromisoformat(os.getenv('TARGET_DATE', '2026-08-31'))
LOOKBACK = int(os.getenv('LOOKBACK_DAYS', '90'))
OUT      = Path('artifacts/nse_insider')
OUT.mkdir(parents=True, exist_ok=True)
UA       = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
            '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
MAX_WORKERS  = 8
MAX_FILINGS  = 3000  # safety cap
FETCH_RETRIES = 2

# ── Per-filing cache ──────────────────────────────────────────────────────────
# Every run used to re-fetch the detail XML of EVERY filing in the 90-day
# window -- 1,724 requests on the 2026-08-31 run, of which 1,276 (74%) came
# back empty. That failure is not a parser bug: sampling this same code from a
# clean IP returned 120/120 OK, and then the filing-list endpoint itself
# started answering 403 once enough requests had been made from that IP. NSE
# rate-limits by volume, so a run that asks for 1,724 files trips the limit
# partway through and loses the remainder.
#
# A filing's XBRL is immutable once published: NSE issues an amendment as a
# NEW appId carrying prevAppId back to the original (see r2_writer.py's
# canonical_is_revision). So the detail only ever needs fetching once, and
# appId -- not a date cursor -- is the right key: a filing disclosed late is
# simply an appId not in the cache yet, whenever it shows up.
#
# The cache is a single R2 object rather than one per filing, so a run reads
# it in one GET instead of thousands of HEADs. Without R2 credentials (local
# runs, diagnostics) the cache is skipped entirely and behaviour is exactly
# what it was before -- fetch everything.
CACHE_KEY = 'cache/nse_insider/parsed_filings.json'
# Keep a margin beyond the window so a filing does not get evicted and
# immediately re-fetched when the window edge moves past it day to day.
CACHE_RETENTION_DAYS = LOOKBACK + 30

TAG_RE = re.compile(r'<in-bse-co:([A-Za-z0-9]+)[^>]*>([^<]*)</in-bse-co:\1>')

session = requests.Session()
session.headers.update({'User-Agent': UA, 'Accept': 'application/json, text/plain, */*'})


def fetch_filing_list():
    r = session.get(LIST_URL, timeout=20)
    r.raise_for_status()
    data = r.json()
    rows = data.get('data', []) if isinstance(data, dict) else []
    print(f'Filing list: {len(rows)} rows, status={r.status_code}')
    return rows


def parse_broadcast_date(v):
    for fmt in ('%d-%b-%Y %H:%M:%S', '%d-%b-%Y'):
        try:
            return datetime.strptime(str(v)[:20].strip(), fmt).date()
        except Exception:
            pass
    return None


def parse_disclosures(xml_text):
    """Split a filing's flat XBRL tag stream into per-person disclosure records."""
    tags = TAG_RE.findall(xml_text)
    company = filing_date = None
    records, current = [], None
    for name, val in tags:
        val = val.strip()
        if name == 'NameOfTheCompany' and company is None:
            company = val
        elif name == 'DateOfFiling' and filing_date is None:
            filing_date = val
        elif name == 'TypeOfInstrument':
            if current:
                records.append(current)
            current = {'securityType': val, 'company': company, 'filingDate': filing_date}
        elif current is not None:
            current[name] = val
    if current:
        records.append(current)
    return records


def to_row(rec, filing):
    txn_raw = rec.get('SecuritiesAcquiredOrDisposedTransactionType', '').upper()
    if 'BUY' in txn_raw or 'ACQUI' in txn_raw or 'ALLOT' in txn_raw or 'SUBSCRI' in txn_raw:
        txn_type = 'Acquisition'
    elif 'SELL' in txn_raw or 'SALE' in txn_raw or 'DISPOS' in txn_raw:
        txn_type = 'Disposal'
    else:
        txn_type = txn_raw.title() or 'Acquisition'

    qty = rec.get('SecuritiesAcquiredOrDisposedNumberOfSecurity', '')
    val = rec.get('SecuritiesAcquiredOrDisposedValueOfSecurity', '')

    return {
        'symbol':          filing.get('symbol', ''),
        'companyName':     rec.get('company') or filing.get('companyName', ''),
        'acqName':         rec.get('NameOfThePerson', ''),
        'personCategory':  rec.get('CategoryOfPerson', ''),
        'secType':         rec.get('securityType', ''),
        'transactionType': txn_type,
        'buyQuantity':     qty if txn_type == 'Acquisition' else '',
        'sellquantity':    qty if txn_type == 'Disposal' else '',
        'buyValue':        val if txn_type == 'Acquisition' else '',
        'sellValue':       val if txn_type == 'Disposal' else '',
        'beforeSharesNo':  rec.get('SecuritiesHeldPriorToAcquisitionOrDisposalNumberOfSecurity', ''),
        'afterSharesNo':   rec.get('SecuritiesHeldPostAcquistionOrDisposalNumberOfSecurity', ''),
        'modeOfAcquisition': rec.get('ModeOfAcquisitionOrDisposal', ''),
        'acqfromDt':       rec.get('DateOfAllotmentAdviceOrAcquisitionOfSharesOrSaleOfSharesSpecifyFromDate', ''),
        'acqtoDt':         rec.get('DateOfAllotmentAdviceOrAcquisitionOfSharesOrSaleOfSharesSpecifyToDate', ''),
        'date':            (rec.get('DateOfIntimationToCompany') or rec.get('filingDate')
                             or filing.get('_broadcast_date', '')),
        'intimDt':         rec.get('DateOfIntimationToCompany', ''),
        'broadcastDt':     filing.get('broadcastDateTime', ''),
        'appId':           filing.get('appId', ''),
    }


def _r2_client():
    """boto3 S3 client for R2, or None when this run has no credentials.
    Missing credentials are not an error: the cache is an optimisation, and
    the script must still work without it."""
    missing = [k for k in ('CLOUDFLARE_ACCOUNT_ID', 'R2_ACCESS_KEY_ID',
                           'R2_SECRET_ACCESS_KEY', 'R2_BUCKET_NAME')
               if not os.environ.get(k)]
    if missing:
        print(f'  (no filing cache: {", ".join(missing)} not set -- fetching every filing)')
        return None
    try:
        import boto3
        return boto3.client(
            's3',
            endpoint_url=f"https://{os.environ['CLOUDFLARE_ACCOUNT_ID']}.r2.cloudflarestorage.com",
            aws_access_key_id=os.environ['R2_ACCESS_KEY_ID'],
            aws_secret_access_key=os.environ['R2_SECRET_ACCESS_KEY'],
            region_name='auto',
        )
    except Exception as exc:
        print(f'  (no filing cache: could not build R2 client -- {type(exc).__name__})')
        return None


def load_cache(client):
    """{appId: {"broadcast": "YYYY-MM-DD", "rows": [...]}}. Any problem
    reading it yields an empty cache and a full fetch -- never a failed run,
    since a stale or unreadable cache must not be able to break acquisition."""
    if client is None:
        return {}
    try:
        body = client.get_object(Bucket=os.environ['R2_BUCKET_NAME'], Key=CACHE_KEY)['Body'].read()
        cache = json.loads(body)
        if not isinstance(cache, dict):
            raise ValueError('cache is not an object')
        print(f'  Filing cache: {len(cache)} filing(s) already parsed')
        return cache
    except Exception as exc:
        name = type(exc).__name__
        if 'NoSuchKey' in name or '404' in str(exc):
            print('  Filing cache: none yet (first run) -- fetching every filing')
        else:
            print(f'  Filing cache: unreadable ({name}) -- fetching every filing')
        return {}


def save_cache(client, cache):
    """Write the cache back, pruned to the retention window. Failure here is
    logged and swallowed: the run's data is already complete without it."""
    if client is None:
        return
    cutoff = (TARGET - timedelta(days=CACHE_RETENTION_DAYS)).isoformat()
    pruned = {k: v for k, v in cache.items()
              if str((v or {}).get('broadcast') or '') >= cutoff}
    dropped = len(cache) - len(pruned)
    try:
        client.put_object(
            Bucket=os.environ['R2_BUCKET_NAME'], Key=CACHE_KEY,
            Body=json.dumps(pruned, default=str).encode('utf-8'),
            ContentType='application/json',
        )
        print(f'  Filing cache: saved {len(pruned)} filing(s)'
              + (f', pruned {dropped} older than {cutoff}' if dropped else ''))
    except Exception as exc:
        print(f'  Filing cache: could not save ({type(exc).__name__}) -- not fatal')


def fetch_and_parse(filing):
    url = filing.get('xmlFileName')
    if not url:
        return []
    for attempt in range(FETCH_RETRIES):
        try:
            r = session.get(url, timeout=12)
            if r.status_code == 200 and r.text:
                recs = parse_disclosures(r.text)
                return [to_row(rec, filing) for rec in recs]
            return []
        except Exception:
            if attempt + 1 < FETCH_RETRIES:
                time.sleep(0.8)
    return []


# ── Window building ────────────────────────────────────────────────────────────

DATE_FMTS = ('%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y', '%d-%b-%Y')


def parse_date_str(v):
    v = str(v or '').strip()[:23]
    for f in DATE_FMTS:
        try:
            return datetime.strptime(v, f).date().isoformat()
        except Exception:
            pass
    return None


def record_date(r):
    for k in ('date', 'intimDt', 'acqfromDt', 'acqtoDt'):
        d = parse_date_str(r.get(k))
        if d:
            return d
    return None


def dedup(rows):
    seen, out = set(), []
    for r in rows:
        k = json.dumps(r, sort_keys=True, default=str)
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


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


def main():
    from_date = TARGET - timedelta(days=LOOKBACK - 1)

    filings = fetch_filing_list()

    in_window = []
    for f in filings:
        bd = parse_broadcast_date(f.get('broadcastDateTime'))
        if bd is None:
            continue
        f['_broadcast_date'] = bd.isoformat()
        if from_date <= bd <= TARGET:
            in_window.append(f)

    in_window = in_window[:MAX_FILINGS]
    print(f'Filings in {LOOKBACK}d window ({from_date} to {TARGET}): {len(in_window)}')

    # Split the window into what is already parsed and what actually has to
    # be fetched. Only the second group costs an NSE request, and keeping
    # that group small is the whole point -- see CACHE_KEY above.
    r2 = _r2_client()
    cache = load_cache(r2)

    all_rows, ok, failed, from_cache = [], 0, 0, 0
    to_fetch = []
    for filing in in_window:
        app_id = str(filing.get('appId') or '').strip()
        cached = cache.get(app_id) if app_id else None
        if cached and isinstance(cached.get('rows'), list):
            all_rows.extend(cached['rows'])
            from_cache += 1
        else:
            to_fetch.append(filing)

    print(f'Cached: {from_cache}, to fetch: {len(to_fetch)}')
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(fetch_and_parse, f): f for f in to_fetch}
        for fut in as_completed(futures):
            filing = futures[fut]
            rows = fut.result()
            if rows:
                ok += 1
                all_rows.extend(rows)
                app_id = str(filing.get('appId') or '').strip()
                if app_id:
                    # Only successful parses are cached. Caching an empty
                    # result would make a rate-limited failure permanent --
                    # the filing would never be retried on a later run.
                    cache[app_id] = {'broadcast': filing.get('_broadcast_date', ''), 'rows': rows}
            else:
                failed += 1

    save_cache(r2, cache)
    print(f'XML filings fetched OK: {ok}, failed/empty: {failed}, reused from cache: {from_cache}')
    all_rows = dedup(all_rows)
    print(f'Total disclosure rows parsed: {len(all_rows)}')

    promoter_rows = [r for r in all_rows if 'PROMOTER' in str(r.get('personCategory', '')).upper()]
    print(f'Rows with PROMOTER category: {len(promoter_rows)}')

    specs = [
        ('1d',  TARGET,                       TARGET),
        ('7d',  TARGET - timedelta(days=6),   TARGET),
        ('30d', TARGET - timedelta(days=29),  TARGET),
        ('90d', from_date,                    TARGET),
    ]

    def in_win(r, wstart, wend):
        rd = record_date(r)
        if not rd:
            return False
        try:
            return wstart <= date.fromisoformat(rd) <= wend
        except Exception:
            return False

    windows = []
    for win_name, wstart, wend in specs:
        win_rows = [r for r in all_rows if in_win(r, wstart, wend)]
        w = make_window(win_name, wstart, wend, win_rows)
        windows.append(w)
        Path(OUT / f'{win_name}.json').write_text(
            json.dumps(w, indent=2, default=str), encoding='utf-8')
        print(f'[{win_name}] rows={len(win_rows)} distinct_dates={len(w["distinct_dates"])}')

    report = {
        'source': 'NSE', 'dataset': 'insider_trading',
        'target_date': str(TARGET), 'lookback_days': LOOKBACK,
        'method': 'corporates-pit-gg filing list + per-filing XBRL XML parse (plain HTTP, no Akamai issue)',
        'filings_in_window': len(in_window),
        'filings_fetched_ok': ok,
        'filings_failed': failed,
        # The measurement that says whether the cache is doing its job:
        # filings_reused_from_cache should climb towards filings_in_window
        # over successive runs, and nse_requests_made should fall to roughly
        # the daily delta (~20-30) from the 1,724 it was.
        'filings_reused_from_cache': from_cache,
        'nse_requests_made': 1 + len(to_fetch),   # the filing list, plus each detail fetch
        'filing_cache_enabled': r2 is not None,
        'windows': [{k: v for k, v in w.items() if k not in ('rows', 'sample')}
                    for w in windows],
    }
    Path(OUT / 'report.json').write_text(
        json.dumps(report, indent=2, default=str), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'windows'}, indent=2))


if __name__ == '__main__':
    main()
