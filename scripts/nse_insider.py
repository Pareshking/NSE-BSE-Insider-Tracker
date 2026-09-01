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

    all_rows, ok, failed = [], 0, 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(fetch_and_parse, f): f for f in in_window}
        for fut in as_completed(futures):
            rows = fut.result()
            if rows:
                ok += 1
                all_rows.extend(rows)
            else:
                failed += 1

    print(f'XML filings fetched OK: {ok}, failed/empty: {failed}')
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
        'windows': [{k: v for k, v in w.items() if k not in ('rows', 'sample')}
                    for w in windows],
    }
    Path(OUT / 'report.json').write_text(
        json.dumps(report, indent=2, default=str), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'windows'}, indent=2))


if __name__ == '__main__':
    main()
