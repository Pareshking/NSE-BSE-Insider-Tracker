"""Evidence-first BSE validator; never certifies from HTTP success alone.

Supports two acquisition modes:
  legacy  – Selenium table scraping (rows as string arrays in pages/detail_pages)
  api     – BSE direct API fetch (rows as positional string arrays, api_windows for counts)
"""
from __future__ import annotations
import hashlib, json, re
from datetime import datetime
from pathlib import Path

RAW     = Path('artifacts/data_validation_v5/bse_raw.json')
OUT     = Path('artifacts/bse_validation')
OUT.mkdir(parents=True, exist_ok=True)

DATE_RE = re.compile(r'\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2}|\d{1,2}\s+[A-Za-z]{3}\s+\d{2,4})\b')
FORMATS = ('%d/%m/%Y', '%d-%m-%Y', '%d/%m/%y', '%d-%m-%y', '%Y-%m-%d', '%d %b %y', '%d %b %Y')


def text(x):
    return re.sub(r'\s+', ' ', str(x or '').strip())


def expand(row):
    if len(row) == 1 and ('\n' in str(row[0]) or '\t' in str(row[0])):
        out = []
        for line in str(row[0]).replace('\r', '').split('\n'):
            p = [text(x) for x in line.strip().split('\t')]
            if len(p) > 1 and any(p):
                out.append(p)
        return out or [row]
    return [row]


def parse_dates(row):
    out = []
    for cell in row:
        for m in DATE_RE.findall(text(cell)):
            for f in FORMATS:
                try:
                    out.append(datetime.strptime(m, f).date().isoformat())
                    break
                except ValueError:
                    pass
    return out


def dedup_key(ds, row):
    r = [text(x) for x in row]
    if ds in ('bulk_deals', 'block_deals') and len(r) >= 7:
        return tuple(r[i] for i in (0, 1, 3, 4, 5, 6))
    if ds == 'insider_trading' and len(r) >= 16:
        return tuple(r[i] for i in (0, 1, 2, 3, 6, 7, 8, 10, 15))
    if ds in ('rights_issue', 'preferential_issue'):
        return tuple(x.upper() for x in r[:6])
    return tuple(r)


def normalize(ds, r):
    if ds in ('bulk_deals', 'block_deals') and len(r) >= 7:
        side = {'B': 'BUY', 'S': 'SELL'}.get(text(r[4]).upper(), text(r[4]).upper())
        return {'event_date': text(r[0]), 'security_code': text(r[1]),
                'security_name': text(r[2]), 'company': text(r[2]),
                'person': text(r[3]), 'side': side,
                'quantity': text(r[5]), 'price': text(r[6]), 'raw': r}
    if ds == 'insider_trading' and len(r) >= 16:
        return {'security_code': text(r[0]), 'company': text(r[1]),
                'person': text(r[2]), 'person_category': text(r[3]),
                'holding_before': text(r[4]), 'security_type': text(r[5]),
                'quantity': text(r[6]), 'transaction_value': text(r[7]),
                'transaction_type': text(r[8]).upper(),
                'holding_after': text(r[9]), 'transaction_date': text(r[10]),
                'mode': text(r[11]), 'trading_in_derivatives': text(r[12]),
                'buy_value': text(r[13]), 'sell_value': text(r[14]),
                'broadcast_date': text(r[15]), 'raw': r}
    if ds in ('rights_issue', 'preferential_issue') and r:
        # stage_1/2/3 kept as-is (backward compatible with anything already
        # reading them); the named fields below are the same positions
        # 4-8 added to ri_pref_row() in bse_raw_capture_v2.py -- pending
        # live re-verification since bulk/block/rights/preferential have
        # been Akamai-BLOCKED for every run since that mapping was written.
        return {'company': text(r[0]),
                'stage_1': text(r[1]) if len(r) > 1 else '',
                'stage_2': text(r[2]) if len(r) > 2 else '',
                'stage_3': text(r[3]) if len(r) > 3 else '',
                'in_principle_status': text(r[4]) if len(r) > 4 else '',
                'in_principle_date': text(r[5]) if len(r) > 5 else '',
                'listing_status': text(r[6]) if len(r) > 6 else '',
                'listing_stage_date': text(r[7]) if len(r) > 7 else '',
                'bse_company_code': text(r[8]) if len(r) > 8 else '',
                'raw': r}
    return {'raw': r}


def collect_rows(obj, field):
    rows = []
    for page in obj.get(field, []):
        for raw in page.get('rows', []):
            rows.extend(x for x in expand(raw) if x)
    return rows


def strip_headers(rows):
    out = []
    for r in rows:
        h = ' '.join(text(x).lower() for x in r)
        if (('deal date' in h and 'security code' in h) or
                ('security code' in h and 'company name' in h) or
                h.startswith('company name ip stage')):
            continue
        out.append(r)
    return out


def api_window_dates(obj):
    """Extract distinct dates reported by api_windows (new acquisition format)."""
    dates = set()
    for w in obj.get('api_windows', []):
        dates.update(w.get('distinct_dates', []))
    return sorted(dates)


def main():
    if not RAW.exists():
        raise SystemExit(f'Missing {RAW}')

    src    = json.loads(RAW.read_text(encoding='utf-8'))
    report = {
        'source':       'BSE',
        'capture_start': src.get('start_date'),
        'capture_end':   src.get('target_date'),
        'lookback_days': src.get('lookback_days'),
        'datasets':      {},
        'certification': 'BLOCKED',
    }

    for ds, obj in src.get('datasets', {}).items():
        rows    = strip_headers(collect_rows(obj, 'pages'))
        details = strip_headers(collect_rows(obj, 'detail_pages'))

        # Deduplicate
        unique, seen, dups = [], {}, []
        for r in rows:
            k = dedup_key(ds, r)
            h = hashlib.sha1(json.dumps(k, ensure_ascii=False).encode()).hexdigest()
            if h in seen:
                dups.append({'duplicate_of': seen[h], 'key': k, 'raw': r})
            else:
                seen[h] = len(unique)
                unique.append(r)

        # Date coverage — prefer api_windows dates when present (more reliable)
        api_dates = api_window_dates(obj)
        row_dates = sorted({d for r in rows for d in parse_dates(r)})
        dts       = api_dates if api_dates else row_dates

        # Semantics
        sem = {}
        if ds in ('bulk_deals', 'block_deals'):
            e   = [r for r in rows if len(r) >= 7]
            sem = {
                'native_columns_present': bool(e) and all(len(r) >= 7 for r in e),
                'has_direction':           bool(e) and all(text(r[4]).upper() in ('B', 'S', 'BUY', 'SELL') for r in e),
                'buy_rows':  sum(text(r[4]).upper() in ('B', 'BUY')  for r in e),
                'sell_rows': sum(text(r[4]).upper() in ('S', 'SELL') for r in e),
            }
        elif ds == 'insider_trading':
            e    = [r for r in rows if len(r) >= 16]
            cats = {text(r[3]).upper() for r in e}
            sem  = {
                'native_columns_present': bool(e) and all(len(r) >= 16 for r in e),
                'has_person':             bool(e) and all(text(r[2]) for r in e),
                'has_category':           bool(e) and all(text(r[3]) for r in e),
                'acquisition_rows':       sum(text(r[8]).upper() == 'ACQUISITION' for r in e),
                'disposal_rows':          sum(text(r[8]).upper() == 'DISPOSAL' for r in e),
                'promoter_or_group_rows': sum('PROMOTER' in text(r[3]).upper() for r in e),
                'categories':             sorted(cats),
            }
        elif ds in ('rights_issue', 'preferential_issue'):
            # Count API window totals when detail_pages aren't available separately
            api_total = sum(w.get('count', 0) for w in obj.get('api_windows', []))
            sem = {
                'index_rows':    len(rows),
                'detail_pages':  len(obj.get('detail_pages', [])),
                'detail_rows':   len(details),
                'detail_dates':  sorted({d for r in details for d in parse_dates(r)}),
                'detail_nonempty': bool(details) or api_total > 0,
                'api_window_total': api_total,
            }

        hist = obj.get('historical_date_test', {})
        # Accept 'changed' status OR direct API date params as historical evidence
        hist_applied = (hist.get('status') == 'changed' or
                        hist.get('method') == 'direct_api_date_params')

        x = {
            'raw_rows':            len(rows),
            'unique_rows':         len(unique),
            'duplicate_rows':      len(dups),
            'distinct_dates':      dts,
            'earliest_date':       dts[0]  if dts else None,
            'latest_date':         dts[-1] if dts else None,
            'historical_test':     hist,
            'historical_range_applied': hist_applied,
            'api_windows':         obj.get('api_windows', []),
            'semantics':           sem,
            'normalized_file':     str(OUT / f'{ds}_normalized.json'),
            'status':              'PENDING',
        }
        report['datasets'][ds] = x
        (OUT / f'{ds}_normalized.json').write_text(
            json.dumps([normalize(ds, r) for r in unique], indent=2, ensure_ascii=False),
            encoding='utf-8')

    # Certification gates
    for ds in ('insider_trading', 'bulk_deals', 'block_deals'):
        x = report['datasets'].get(ds, {})
        x['status'] = (
            'VERIFIED'
            if (x.get('raw_rows', 0) > 0 and
                x.get('historical_range_applied') and
                x.get('semantics', {}).get('native_columns_present') and
                x.get('distinct_dates'))
            else 'BLOCKED'
        )

    for ds in ('rights_issue', 'preferential_issue'):
        x = report['datasets'].get(ds, {})
        x['status'] = (
            'VERIFIED'
            if (x.get('raw_rows', 0) > 0 and
                x.get('semantics', {}).get('detail_nonempty'))
            else 'BLOCKED'
        )

    report['certification'] = (
        'VERIFIED'
        if all(report['datasets'].get(ds, {}).get('status') == 'VERIFIED'
               for ds in ('insider_trading', 'bulk_deals', 'block_deals',
                          'rights_issue', 'preferential_issue'))
        else 'BLOCKED'
    )

    (OUT / 'report.json').write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
