"""Writes validated NSE + BSE acquisition data to Cloudflare R2.

Reads the artifacts already produced and graded by nse_validate.py /
bse_validate.py and only writes a (exchange, category) dataset to R2 if its
own validator marked it VERIFIED for this run. A category that is BLOCKED,
missing, or empty is recorded in the manifest as `written: false` with a
reason -- it is never silently written as an empty "successful" dataset,
per the data-quality rule in PROJECT_PLAN.md section 11.

R2 layout:
  raw/{exchange}/{category}/{date}/raw.json           -- validated rows, native fields preserved, unmodified
  canonical/{exchange}/{category}/{date}/data.parquet -- same rows as Parquet + canonical_event_id/exchange/category/ingested_at columns
  manifests/{date}.json                                -- per-(exchange,category) ingestion outcome for this run

Both the raw JSON and the Parquet file are uploaded as a single `put_object`
call each (S3/R2 object writes are atomic -- a reader never sees a partial
object). The manifest is uploaded last and only after every dataset's writes
for this run have completed, so a manifest entry never points at data that
isn't actually in the bucket yet.
"""
from __future__ import annotations
import hashlib, io, json, os, re
from datetime import datetime, timedelta, timezone
from pathlib import Path
import boto3
import pandas as pd

TARGET_DATE = os.environ.get('TARGET_DATE', datetime.now(timezone.utc).date().isoformat())
BUCKET = os.environ.get('R2_BUCKET_NAME', '')

# canonical category name -> (NSE cert-report dataset key, NSE rows artifact path,
#                              BSE cert-report dataset key, BSE normalized artifact path)
CATEGORIES = {
    'insider_trading': (
        'insider', 'artifacts/nse_insider/90d.json',
        'insider_trading', 'artifacts/bse_validation/insider_trading_normalized.json',
    ),
    'bulk_deals': (
        'bulk', 'artifacts/nse_bulk/report.json',
        'bulk_deals', 'artifacts/bse_validation/bulk_deals_normalized.json',
    ),
    'block_deals': (
        'block', 'artifacts/nse_block/report.json',
        'block_deals', 'artifacts/bse_validation/block_deals_normalized.json',
    ),
    'rights_issue': (
        'rights', 'artifacts/nse_validation/rights/report.json',
        'rights_issue', 'artifacts/bse_validation/rights_issue_normalized.json',
    ),
    'preferential_issue': (
        'preferential', 'artifacts/nse_validation/preferential/report.json',
        'preferential_issue', 'artifacts/bse_validation/preferential_issue_normalized.json',
    ),
}

NSE_CERT_PATH = 'artifacts/nse_validation/certification_report.json'
BSE_CERT_PATH = 'artifacts/bse_validation/report.json'


def load_json(path):
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return None


def r2_client():
    return boto3.client(
        's3',
        endpoint_url=f"https://{os.environ['CLOUDFLARE_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ['R2_ACCESS_KEY_ID'],
        aws_secret_access_key=os.environ['R2_SECRET_ACCESS_KEY'],
        region_name='auto',
    )


def canonical_event_id(exchange, category, row):
    key = json.dumps(row, sort_keys=True, default=str)
    return hashlib.sha1(f'{exchange}|{category}|{key}'.encode('utf-8')).hexdigest()


def _pick(row, *keys):
    for k in keys:
        v = row.get(k)
        if v not in (None, ''):
            return v
    return None


def canonicalize(exchange, category, row):
    """Frontend-facing aligned fields, common by name across NSE and BSE for a
    given category. Computed from known native field names (verified against
    real captured data on 2026-09-01 -- see DATA_ACQUISITION.md); anything not
    recognized is left None rather than guessed. Never touches the native
    columns, which stay available for drill-down/audit alongside these.
    """
    if category == 'insider_trading':
        if exchange == 'nse':
            qty = row.get('buyQuantity') or row.get('sellquantity')
            val = row.get('buyValue') or row.get('sellValue')
        else:
            qty = row.get('quantity')
            val = row.get('transaction_value')
        return {
            'canonical_company': _pick(row, 'companyName', 'company', 'nameOfTheCompany'),
            'canonical_symbol': _pick(row, 'symbol', 'security_code'),
            'canonical_person': _pick(row, 'acqName', 'person'),
            'canonical_person_category': _pick(row, 'personCategory', 'person_category'),
            'canonical_transaction_type': (str(_pick(row, 'transactionType', 'transaction_type') or '').upper() or None),
            'canonical_quantity': qty,
            'canonical_value': val,
            'canonical_holding_before': _pick(row, 'beforeSharesNo', 'holding_before'),
            'canonical_holding_after': _pick(row, 'afterSharesNo', 'holding_after'),
            'canonical_transaction_date': _pick(row, 'date', 'transaction_date'),
            'canonical_mode': _pick(row, 'modeOfAcquisition', 'mode'),
            'canonical_broadcast_date': _pick(row, 'broadcastDt', 'broadcast_date'),
        }
    if category in ('bulk_deals', 'block_deals'):
        if exchange == 'nse':
            # NSE historical bulk/block-deals API field names (confirmed via
            # nse_validate.py's dedup key, which has matched real NSE data).
            # BD_SCRIP_NAME specifically is best-effort -- not yet re-verified
            # against a fresh capture since bulk/block have been Akamai-BLOCKED
            # for every run since this mapping was written.
            company = _pick(row, 'BD_SCRIP_NAME', 'BD_SYMBOL')
            symbol = _pick(row, 'BD_SYMBOL')
            client = _pick(row, 'BD_CLIENT_NAME')
            side_raw = str(_pick(row, 'BD_BUY_SELL') or '').upper()
            qty = _pick(row, 'BD_QTY_TRD')
            price = _pick(row, 'BD_TP_WATP')
            event_date = _pick(row, 'BD_DT_DATE')
        else:
            company = _pick(row, 'company', 'security_name')
            symbol = _pick(row, 'security_code')
            client = _pick(row, 'person')
            side_raw = str(_pick(row, 'side') or '').upper()
            qty = _pick(row, 'quantity')
            price = _pick(row, 'price')
            event_date = _pick(row, 'event_date')
        side = 'BUY' if side_raw in ('B', 'BUY') else ('SELL' if side_raw in ('S', 'SELL') else None)
        return {
            'canonical_company': company,
            'canonical_symbol': symbol,
            'canonical_client': client,
            'canonical_side': side,
            'canonical_quantity': qty,
            'canonical_price': price,
            'canonical_event_date': event_date,
        }
    if category in ('rights_issue', 'preferential_issue'):
        # NSE's 'companyName' field on the Rights (FIRILS/listing-stage) index
        # has been observed to contain a raw BSE scrip-code number instead of
        # an actual name (e.g. "500306") -- verified 2026-09-01. Never surface
        # a purely-numeric value as a company name; flag it instead.
        raw_company = _pick(row, 'nameOfTheCompany', 'companyName', 'company')
        company_unreliable = bool(raw_company) and str(raw_company).strip().isdigit()

        # categoryOfAllottee (Preferential only) has observed values 'Promoter',
        # 'Non Promoter', and 'Promoter & Non Promoter' -- the latter two both
        # contain the substring 'PROMOTER', so this MUST be an exact-value
        # mapping, never a substring/'in' check, or 'Non Promoter' allotments
        # would be misclassified as promoter allotments.
        allottee_raw = str(_pick(row, 'categoryOfAllottee') or '').strip()
        allottee_map = {
            'Promoter': 'PROMOTER',
            'Non Promoter': 'NON_PROMOTER',
            'Promoter & Non Promoter': 'MIXED',
        }
        canonical_allottee_category = allottee_map.get(allottee_raw)

        # totalAmntRaised/totalAmtRaised has been observed as scientific-notation
        # garbage (e.g. "3.64E+16" -- 36 quadrillion rupees, not a real issue
        # size) alongside a ~50% null/zero rate. Reject anything outside a sane
        # bound (10 trillion INR) rather than surfacing it as currency.
        raw_amount = _pick(row, 'totalAmntRaised', 'totalAmtRaised')
        amount = _num(raw_amount)
        amount_unreliable = raw_amount not in (None, '') and (
            amount is None or amount <= 0 or amount > 1e13)

        return {
            'canonical_company': None if company_unreliable else raw_company,
            'canonical_company_unreliable': company_unreliable,
            'canonical_symbol': _pick(row, 'nseSymbol', 'security_code', 'symbol'),
            'canonical_stage': _pick(row, 'stage', 'issueType'),
            'canonical_event_date': _pick(row, 'dateOfSubmission', 'boardResolutionDt', 'event_date'),
            'canonical_allottee_category': canonical_allottee_category,
            'canonical_amount_raised': None if amount_unreliable else amount,
            'canonical_amount_raised_unreliable': amount_unreliable,
        }
    return {}


_CORP_SUFFIX_RE = re.compile(
    r'\b(LIMITED|LTD|LIMTED|PRIVATE|PVT|CO|COMPANY|CORP|CORPORATION|INDIA)\b')


def normalize_company(name):
    """Loose company-name key for cross-exchange matching: uppercase, strip
    punctuation and common corporate suffixes, collapse whitespace. Not used
    for display -- only to decide whether two rows might describe the same
    company."""
    if not name:
        return ''
    s = re.sub(r'[^A-Z0-9 ]', ' ', str(name).upper())
    s = _CORP_SUFFIX_RE.sub(' ', s)
    return re.sub(r'\s+', ' ', s).strip()


_LOOSE_DATE_FMTS = ('%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y', '%d-%b-%Y', '%d-%b-%y',
                     '%d-%B-%Y', '%d-Aug-%Y')


def parse_loose_date(v):
    s = str(v or '').strip()[:20]
    for f in _LOOSE_DATE_FMTS:
        try:
            return datetime.strptime(s.title() if '%b' in f or '%B' in f else s, f).date()
        except Exception:
            pass
    return None


def _num(v):
    try:
        return float(str(v).replace(',', ''))
    except (TypeError, ValueError):
        return None


def find_cross_exchange_matches(category, nse_canons, bse_canons):
    """Flag (never merge) NSE/BSE rows within the same category+run that
    plausibly describe the same underlying disclosure: same normalized
    company name and a nearby event date, with quantity as a corroborating
    (not required) signal when the category has one. Returns
    {row_index_within_its_own_list: {'possible_duplicate_of': other exchange's
    canonical_event_id, 'match_confidence': 'high'|'medium'}} for nse and bse
    separately. A company with more than one same-day candidate on the other
    side is left unmatched rather than guessing which one."""
    date_field = {
        'insider_trading': 'canonical_transaction_date',
        'bulk_deals': 'canonical_event_date', 'block_deals': 'canonical_event_date',
        'rights_issue': 'canonical_event_date', 'preferential_issue': 'canonical_event_date',
    }[category]
    qty_field = 'canonical_quantity' if category in (
        'insider_trading', 'bulk_deals', 'block_deals') else None

    def index_by_company(canons):
        idx = {}
        for i, c in enumerate(canons):
            key = normalize_company(c.get('canonical_company'))
            if key:
                idx.setdefault(key, []).append(i)
        return idx

    bse_by_company = index_by_company(bse_canons)
    nse_matches, bse_matches = {}, {}

    for i, nse_c in enumerate(nse_canons):
        key = normalize_company(nse_c.get('canonical_company'))
        if not key or key not in bse_by_company:
            continue
        nse_date = parse_loose_date(nse_c.get(date_field))
        candidates = []
        for j in bse_by_company[key]:
            bse_c = bse_canons[j]
            bse_date = parse_loose_date(bse_c.get(date_field))
            dates_close = bool(nse_date and bse_date and abs((nse_date - bse_date).days) <= 2)
            if nse_date and bse_date and not dates_close:
                continue
            if qty_field:
                # Quantity is the strong signal here; date is corroborating but
                # optional since intimation/broadcast timing can drift a bit.
                nq, bq = _num(nse_c.get(qty_field)), _num(bse_c.get(qty_field))
                if nq is not None and bq is not None:
                    if abs(nq - bq) > 1e-6:
                        continue  # same company/date but different quantity -> not a match
                    confidence = 'high'
                elif dates_close:
                    confidence = 'medium'
                else:
                    continue  # no quantity to compare and no date corroboration -- too weak
            else:
                # No quantity signal for this category (e.g. rights/preferential) --
                # a close date on BOTH sides is required; company name alone is not
                # enough evidence on its own.
                if not dates_close:
                    continue
                confidence = 'medium'
            candidates.append((j, confidence))
        if len(candidates) == 1:
            j, confidence = candidates[0]
            nse_matches[i] = {'possible_duplicate_of': bse_canons[j]['_event_id'],
                               'match_confidence': confidence}
            bse_matches[j] = {'possible_duplicate_of': nse_c['_event_id'],
                               'match_confidence': confidence}
        # 0 or >1 candidates: ambiguous or no match -- leave unflagged rather than guess

    return nse_matches, bse_matches


def rows_to_parquet_bytes(exchange, category, rows, match_annotations=None):
    match_annotations = match_annotations or {}
    df = pd.json_normalize(rows)
    canon = pd.DataFrame([canonicalize(exchange, category, r) for r in rows])
    for col in canon.columns:
        df[col] = canon[col].values
    ids = [canonical_event_id(exchange, category, r) for r in rows]
    df.insert(0, 'cross_exchange_match_confidence',
              [match_annotations.get(i, {}).get('match_confidence') for i in range(len(rows))])
    df.insert(0, 'cross_exchange_possible_match_id',
              [match_annotations.get(i, {}).get('possible_duplicate_of') for i in range(len(rows))])
    df.insert(0, 'canonical_event_id', ids)
    df.insert(0, 'category', category)
    df.insert(0, 'exchange', exchange)
    df['ingested_at'] = datetime.now(timezone.utc).isoformat()
    # Parquet requires uniform column types; anything left as native Python
    # objects (nested dicts/lists in a row's 'raw' field, etc.) is stored as
    # its JSON string form rather than dropped, to avoid losing data silently.
    for col in df.columns:
        if df[col].map(lambda v: isinstance(v, (dict, list))).any():
            df[col] = df[col].map(lambda v: json.dumps(v, default=str) if isinstance(v, (dict, list)) else v)
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    return buf.getvalue(), int(df['canonical_event_id'].nunique())


def get_rows(exchange, nse_key, nse_path, bse_key, bse_path):
    if exchange == 'nse':
        obj = load_json(nse_path)
        return (obj or {}).get('rows', [])
    obj = load_json(bse_path)
    return obj if isinstance(obj, list) else []


def get_status(exchange, nse_key, bse_key, nse_cert, bse_cert):
    if exchange == 'nse':
        return ((nse_cert or {}).get('datasets', {}).get(nse_key, {}) or {}).get('status', 'MISSING')
    return ((bse_cert or {}).get('datasets', {}).get(bse_key, {}) or {}).get('status', 'MISSING')


def write_dataset(client, exchange, category, rows, status, match_annotations=None):
    entry = {
        'exchange': exchange, 'category': category, 'status': status,
        'target_date': TARGET_DATE, 'row_count': len(rows) if rows else 0,
    }
    if status != 'VERIFIED' or not rows:
        entry['written'] = False
        entry['reason'] = (
            f"validator status is {status!r}, not VERIFIED" if status != 'VERIFIED'
            else 'VERIFIED but zero rows -- skipped to avoid a silent empty dataset'
        )
        print(f'  SKIP {exchange}/{category}: {entry["reason"]}')
        return entry

    raw_bytes = json.dumps(rows, indent=2, default=str, ensure_ascii=False).encode('utf-8')
    raw_key = f'raw/{exchange}/{category}/{TARGET_DATE}/raw.json'
    client.put_object(Bucket=BUCKET, Key=raw_key, Body=raw_bytes, ContentType='application/json')

    parquet_bytes, unique_ids = rows_to_parquet_bytes(exchange, category, rows, match_annotations)
    parquet_key = f'canonical/{exchange}/{category}/{TARGET_DATE}/data.parquet'
    client.put_object(Bucket=BUCKET, Key=parquet_key, Body=parquet_bytes,
                       ContentType='application/octet-stream')

    cross_matched = len(match_annotations) if match_annotations else 0
    entry.update({
        'written': True,
        'raw_key': raw_key,
        'parquet_key': parquet_key,
        'unique_event_ids': unique_ids,
        'cross_exchange_matches_flagged': cross_matched,
        'raw_sha256': hashlib.sha256(raw_bytes).hexdigest(),
        'parquet_sha256': hashlib.sha256(parquet_bytes).hexdigest(),
        'raw_bytes': len(raw_bytes),
        'parquet_bytes': len(parquet_bytes),
    })
    print(f'  WRITE {exchange}/{category}: {len(rows)} rows ({unique_ids} unique, '
          f'{cross_matched} cross-exchange matches flagged) -> {parquet_key}')
    return entry


def main():
    nse_cert = load_json(NSE_CERT_PATH)
    bse_cert = load_json(BSE_CERT_PATH)
    if nse_cert is None:
        print(f'WARNING: {NSE_CERT_PATH} not found -- all NSE categories will be skipped as MISSING')
    if bse_cert is None:
        print(f'WARNING: {BSE_CERT_PATH} not found -- all BSE categories will be skipped as MISSING')

    client = r2_client()
    manifest = {
        'target_date': TARGET_DATE,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'datasets': [],
    }

    for category, (nse_key, nse_path, bse_key, bse_path) in CATEGORIES.items():
        nse_rows = get_rows('nse', nse_key, nse_path, bse_key, bse_path)
        bse_rows = get_rows('bse', nse_key, nse_path, bse_key, bse_path)
        nse_status = get_status('nse', nse_key, bse_key, nse_cert, bse_cert)
        bse_status = get_status('bse', nse_key, bse_key, nse_cert, bse_cert)

        nse_matches, bse_matches = {}, {}
        if nse_status == 'VERIFIED' and bse_status == 'VERIFIED' and nse_rows and bse_rows:
            nse_canons = [canonicalize('nse', category, r) for r in nse_rows]
            bse_canons = [canonicalize('bse', category, r) for r in bse_rows]
            for i, r in enumerate(nse_rows):
                nse_canons[i]['_event_id'] = canonical_event_id('nse', category, r)
            for j, r in enumerate(bse_rows):
                bse_canons[j]['_event_id'] = canonical_event_id('bse', category, r)
            nse_matches, bse_matches = find_cross_exchange_matches(category, nse_canons, bse_canons)
            if nse_matches:
                print(f'  {category}: flagged {len(nse_matches)} possible cross-exchange match(es)')

        manifest['datasets'].append(write_dataset(client, 'nse', category, nse_rows, nse_status, nse_matches))
        manifest['datasets'].append(write_dataset(client, 'bse', category, bse_rows, bse_status, bse_matches))

    written = sum(1 for d in manifest['datasets'] if d.get('written'))
    manifest['written_count'] = written
    manifest['skipped_count'] = len(manifest['datasets']) - written

    manifest_key = f'manifests/{TARGET_DATE}.json'
    manifest_bytes = json.dumps(manifest, indent=2, default=str).encode('utf-8')
    client.put_object(Bucket=BUCKET, Key=manifest_key, Body=manifest_bytes,
                       ContentType='application/json')

    print(f'\nManifest written: s3://{BUCKET}/{manifest_key}')
    print(f'{written}/{len(manifest["datasets"])} datasets written to R2 for {TARGET_DATE}')
    print(json.dumps(manifest, indent=2, default=str))


if __name__ == '__main__':
    main()
