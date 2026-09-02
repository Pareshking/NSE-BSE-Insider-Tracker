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

# Security-master crosswalk (ISIN <-> NSE symbol <-> BSE scrip code): the only
# reliable cross-exchange join key, since NSE (alpha tickers) and BSE (numeric
# scrip codes) otherwise share no identifier space at all. Snapshot from
# Value Research, 2026-09-01 -- see reference_data/README.md for provenance
# and staleness caveats. Missing gracefully: if the file isn't present,
# cross-exchange matching just falls back to fuzzy company-name matching.
SECURITY_MASTER_PATH = os.environ.get(
    'SECURITY_MASTER_PATH', 'reference_data/security_master_20260901.csv')

_isin_by_nse_symbol = None
_isin_by_bse_code = None


def load_security_master():
    """Build {NSE_SYMBOL: ISIN} and {BSE_SCRIP_CODE: ISIN} lookups, cached
    for the life of the process. Returns (empty, empty) dicts if the
    reference file isn't available -- callers degrade gracefully."""
    global _isin_by_nse_symbol, _isin_by_bse_code
    if _isin_by_nse_symbol is not None:
        return _isin_by_nse_symbol, _isin_by_bse_code
    _isin_by_nse_symbol, _isin_by_bse_code = {}, {}
    p = Path(SECURITY_MASTER_PATH)
    if not p.exists():
        print(f'  (no security master at {SECURITY_MASTER_PATH} -- cross-exchange '
              f'matching will use fuzzy company-name only)')
        return _isin_by_nse_symbol, _isin_by_bse_code
    df = pd.read_csv(p, dtype=str, keep_default_na=False)
    for _, row in df.iterrows():
        isin = (row.get('isin') or '').strip()
        if not isin:
            continue
        sym = (row.get('nse_symbol') or '').strip().upper()
        if sym:
            _isin_by_nse_symbol[sym] = isin
        code = (row.get('bse_scrip_code') or '').strip()
        if code:
            _isin_by_bse_code[code] = isin
    print(f'  loaded security master: {len(_isin_by_nse_symbol)} NSE symbols, '
          f'{len(_isin_by_bse_code)} BSE scrip codes -> ISIN')
    return _isin_by_nse_symbol, _isin_by_bse_code


def resolve_isin(exchange, category, row):
    """Best-effort ISIN for a row, using its own native field when the
    source already provides one (NSE rights/preferential), otherwise via
    the security-master symbol/scrip-code crosswalk."""
    direct = row.get('isin')
    if direct:
        return str(direct).strip() or None
    isin_by_nse_symbol, isin_by_bse_code = load_security_master()
    if exchange == 'nse':
        symbol = _pick(row, 'symbol', 'BD_SYMBOL', 'nseSymbol')
        if not symbol:
            return None
        symbol = str(symbol).strip().upper()
        isin = isin_by_nse_symbol.get(symbol)
        if isin:
            return isin
        return _prefix_match_symbol(symbol, isin_by_nse_symbol)
    else:
        # 'stage_3' is rights_issue/preferential_issue's scripcode field --
        # a real 6-digit BSE scrip code, same namespace as the security
        # master's bse_scrip_code (confirmed 2026-09-02 against live BSE
        # data: stage_3 values like 570005/544559/544459 hit the crosswalk
        # directly). 'bse_company_code' (BSE's COMPANY_CODE, e.g. 8255,
        # 13640) is a *different*, shorter internal BSE ID that never
        # matches bse_scrip_code -- it must not be tried before stage_3,
        # only as a last resort for any dataset that has no stage_3.
        code = _pick(row, 'security_code', 'stage_3', 'bse_company_code')
        return isin_by_bse_code.get(str(code).strip()) if code else None


def _prefix_match_symbol(query_symbol, isin_by_nse_symbol):
    """Fallback when an exact NSE symbol lookup misses: some NSE disclosure
    feeds use a different symbol variant than the current live ticker (e.g.
    'ATHERENERG' in insider-trading XBRL filings vs 'ATHER' as the live
    trading symbol -- confirmed on real captured data, 2026-09-01). Only
    accept a prefix match when it is UNIQUE: a short/generic query like
    'TATA' would prefix-match nine different Tata group tickers
    (TATASTEEL, TATAMOTORS, ...) and must be left unresolved rather than
    guessed, exactly like the ambiguous-candidate rule in
    find_cross_exchange_matches()."""
    if len(query_symbol) < 4:
        return None
    candidates = {s for s in isin_by_nse_symbol
                  if s and (s.startswith(query_symbol) or query_symbol.startswith(s))}
    if len(candidates) == 1:
        return isin_by_nse_symbol[next(iter(candidates))]
    return None

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
    result = None
    if category == 'insider_trading':
        if exchange == 'nse':
            qty = row.get('buyQuantity') or row.get('sellquantity')
            val = row.get('buyValue') or row.get('sellValue')
        else:
            qty = row.get('quantity')
            val = row.get('transaction_value')

        # NSE discloses the actual trade over a from/to window (acqfromDt..
        # acqtoDt), which differs from the disclosure/intimation date ('date')
        # for ~19% of real captured rows (2026-09-01) -- an aggregated
        # multi-day disclosure, not a single-day transaction. Surface the
        # real range instead of silently collapsing it to one day. BSE's
        # normalized schema has no separate from/to fields (its
        # 'transaction_date' is already a single day), so from==to there.
        txn_from = _pick(row, 'acqfromDt', 'transaction_date')
        txn_to = _pick(row, 'acqtoDt', 'transaction_date')
        is_range = bool(txn_from and txn_to and txn_from != txn_to)

        result = {
            'canonical_company': _pick(row, 'companyName', 'company', 'nameOfTheCompany'),
            'canonical_symbol': _pick(row, 'symbol', 'security_code'),
            'canonical_person': _pick(row, 'acqName', 'person'),
            'canonical_person_category': _pick(row, 'personCategory', 'person_category'),
            'canonical_transaction_type': (str(_pick(row, 'transactionType', 'transaction_type') or '').upper() or None),
            # _num(), not the raw native value: NSE and BSE mix numeric and
            # stringy representations of the same quantity (e.g. '51000.0')
            # across rows, which is fine natively but breaks Arrow/Parquet
            # once the frontend concats NSE+BSE into one column of mixed
            # int/str objects (confirmed 2026-09-01 on the deployed app --
            # ArrowInvalid: "Could not convert '51000.0' ... to int64").
            'canonical_quantity': _num(qty),
            'canonical_value': _num(val),
            'canonical_holding_before': _num(_pick(row, 'beforeSharesNo', 'holding_before')),
            'canonical_holding_after': _num(_pick(row, 'afterSharesNo', 'holding_after')),
            'canonical_transaction_date': _pick(row, 'date', 'transaction_date'),
            'canonical_transaction_date_from': txn_from,
            'canonical_transaction_date_to': txn_to,
            'canonical_transaction_date_is_range': is_range,
            'canonical_mode': _pick(row, 'modeOfAcquisition', 'mode'),
            'canonical_broadcast_date': _pick(row, 'broadcastDt', 'broadcast_date'),
            # NSE's schema carries appId/prevAppId to mark a filing as
            # amending an earlier one (0 occurrences in the 2026-09-01
            # sample, but expected to recur -- see PROJECT_PLAN.md section 8
            # "amended/re-filed disclosure" identity requirement).
            # canonical_event_id is a content hash and correctly differs
            # between the original and its revision; appId is NSE's own
            # stable filing identifier, so exposing the appId/prevAppId
            # chain (rather than trying to recompute a historical hash) is
            # what actually lets a consumer trace a revision to its
            # original across runs.
            'canonical_app_id': row.get('appId'),
            'canonical_prev_app_id': row.get('prevAppId'),
            'canonical_is_revision': bool(row.get('prevAppId')),
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
        result = {
            'canonical_company': company,
            'canonical_symbol': symbol,
            'canonical_client': client,
            'canonical_side': side,
            'canonical_quantity': _num(qty),
            'canonical_price': _num(price),
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

        result = {
            'canonical_company': None if company_unreliable else raw_company,
            'canonical_company_unreliable': company_unreliable,
            'canonical_symbol': _pick(row, 'nseSymbol', 'security_code', 'symbol'),
            'canonical_stage': _pick(row, 'stage', 'issueType'),
            # listing_stage_date/in_principle_date are BSE fields added
            # 2026-09-01 (see bse_raw_capture_v2.py's ri_pref_row(), pending
            # live re-verification) -- previously BSE rights/preferential had
            # NO date field at all here, which meant find_cross_exchange_matches()
            # could never confirm a match for these categories (a match
            # requires a date on both sides when there's no quantity to
            # compare). This is what actually closes that gap, not just the
            # ISIN crosswalk alone.
            'canonical_event_date': _pick(row, 'dateOfSubmission', 'boardResolutionDt',
                                           'listing_stage_date', 'in_principle_date', 'event_date'),
            'canonical_allottee_category': canonical_allottee_category,
            'canonical_amount_raised': None if amount_unreliable else amount,
            'canonical_amount_raised_unreliable': amount_unreliable,
        }

    if result is None:
        return {}
    result['canonical_isin'] = resolve_isin(exchange, category, row)
    return result


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

    def join_key(c):
        """Prefer the exact ISIN join key (from the security-master crosswalk
        or a native isin field) over fuzzy company-name matching -- NSE
        (alpha tickers) and BSE (numeric scrip codes) share no identifier
        space of their own, so ISIN is the only hard link between them."""
        isin = c.get('canonical_isin')
        if isin:
            return ('isin', isin)
        name = normalize_company(c.get('canonical_company'))
        return ('name', name) if name else None

    def index_by_key(canons):
        idx = {}
        for i, c in enumerate(canons):
            key = join_key(c)
            if key:
                idx.setdefault(key, []).append(i)
        return idx

    bse_by_key = index_by_key(bse_canons)
    nse_matches, bse_matches = {}, {}

    for i, nse_c in enumerate(nse_canons):
        key = join_key(nse_c)
        if not key or key not in bse_by_key:
            continue
        match_basis = key[0]
        nse_date = parse_loose_date(nse_c.get(date_field))
        candidates = []
        for j in bse_by_key[key]:
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
                               'match_confidence': confidence, 'match_basis': match_basis}
            bse_matches[j] = {'possible_duplicate_of': nse_c['_event_id'],
                               'match_confidence': confidence, 'match_basis': match_basis}
        # 0 or >1 candidates: ambiguous or no match -- leave unflagged rather than guess

    return nse_matches, bse_matches


def rows_to_parquet_bytes(exchange, category, rows, match_annotations=None):
    match_annotations = match_annotations or {}
    df = pd.json_normalize(rows)
    canon = pd.DataFrame([canonicalize(exchange, category, r) for r in rows])
    for col in canon.columns:
        df[col] = canon[col].values
    ids = [canonical_event_id(exchange, category, r) for r in rows]
    df.insert(0, 'cross_exchange_match_basis',
              [match_annotations.get(i, {}).get('match_basis') for i in range(len(rows))])
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


NSE_MARKET_CAP_PATH = 'artifacts/nse_market_cap/report.json'
BSE_MARKET_CAP_PATH = 'artifacts/bse_market_cap/report.json'


def cross_exchange_alias_rows(nse_rows, bse_rows):
    """A symbol missing from its own exchange's market-cap file is often
    still resolvable through the OTHER exchange, via the ISIN crosswalk
    both are already listed under in the security master. Checked against
    real data (2026-09-01): of 163 real NSE-transacting symbols missing
    from the NSE PR zip that day, 41 were cross-listed on BSE with a
    resolvable BSE market cap -- free coverage, no new fetch, just a
    smarter join. Full-universe count: 436 NSE symbols and 7 BSE scrips
    rescuable this way.

    Emits alias rows under the MISSING side's own symbol (NSE alpha ticker
    or BSE numeric code) pointing at the other exchange's market cap value,
    tagged 'source': 'cross_exchange_alias' so it's never confused with a
    same-exchange figure. Never overwrites a row that already resolved
    directly -- an exchange's own number for its own listing always wins."""
    isin_by_nse_symbol, isin_by_bse_code = load_security_master()
    nse_by_isin = {isin: sym for sym, isin in isin_by_nse_symbol.items()}
    bse_by_isin = {isin: code for code, isin in isin_by_bse_code.items()}

    nse_symbols = {r['symbol'] for r in nse_rows}
    bse_codes = {r['symbol'] for r in bse_rows}
    aliases = []

    for row in bse_rows:
        isin = isin_by_bse_code.get(row['symbol'])
        nse_symbol = nse_by_isin.get(isin) if isin else None
        if nse_symbol and nse_symbol not in nse_symbols:
            aliases.append({**row, 'symbol': nse_symbol, 'source': 'cross_exchange_alias',
                             'aliased_from': f'BSE:{row["symbol"]}'})
            nse_symbols.add(nse_symbol)  # don't alias the same target twice

    for row in nse_rows:
        isin = isin_by_nse_symbol.get(row['symbol'])
        bse_code = bse_by_isin.get(isin) if isin else None
        if bse_code and bse_code not in bse_codes:
            aliases.append({**row, 'symbol': bse_code, 'source': 'cross_exchange_alias',
                             'aliased_from': f'NSE:{row["symbol"]}'})
            bse_codes.add(bse_code)

    if aliases:
        print(f'  Cross-exchange alias: rescued {len(aliases)} symbols via ISIN crosswalk '
              f'({sum(1 for a in aliases if a["aliased_from"].startswith("BSE"))} NSE-side, '
              f'{sum(1 for a in aliases if a["aliased_from"].startswith("NSE"))} BSE-side)')
    return aliases


def write_market_cap(client):
    """Reference data, not a transaction dataset -- deliberately kept OUT of
    manifest['datasets'] and its VERIFIED/BLOCKED vocabulary. That list drives
    the Overview page's "NSE certified" badge via `all(status == VERIFIED for
    entries where exchange == nse)`; a reference dataset with any other status
    string in the same list would silently flip that badge to "partial" for a
    reason that has nothing to do with transaction-data certification. Market
    cap coverage is reported separately, under its own key.

    Merges NSE (scripts/nse_market_cap.py) and BSE (scripts/bse_market_cap.py)
    into one combined list -- safe because NSE symbols are alpha tickers and
    BSE scrip codes are pure numeric strings, so they never collide, and the
    frontend's join is a single case-insensitive lookup by canonical_symbol
    regardless of which exchange a row came from. Plus cross-exchange alias
    rows (see cross_exchange_alias_rows()) for symbols missing from their own
    exchange's file but resolvable via the other exchange's ISIN crosswalk."""
    nse_report = load_json(NSE_MARKET_CAP_PATH)
    bse_report = load_json(BSE_MARKET_CAP_PATH)
    nse_rows = (nse_report or {}).get('rows', [])
    bse_rows = (bse_report or {}).get('rows', [])
    alias_rows = cross_exchange_alias_rows(nse_rows, bse_rows) if (nse_rows and bse_rows) else []
    rows = nse_rows + bse_rows + alias_rows

    entry = {'dataset': 'market_cap', 'target_date': TARGET_DATE}
    if not rows:
        entry['written'] = False
        entry['reason'] = 'no NSE or BSE market cap report found, or zero rows resolved'
        print(f'  SKIP market_cap: {entry["reason"]}')
        return entry

    raw_bytes = json.dumps(rows, indent=2, default=str, ensure_ascii=False).encode('utf-8')
    key = f'reference/market_cap/{TARGET_DATE}/data.json'
    client.put_object(Bucket=BUCKET, Key=key, Body=raw_bytes, ContentType='application/json')
    entry.update({
        'written': True,
        'key': key,
        'symbols_resolved': len(rows),
        'nse_symbols_resolved': len(nse_rows),
        'nse_pr_zip_date_used': (nse_report or {}).get('pr_zip_date_used'),
        'bse_symbols_resolved': len(bse_rows),
        'bse_groups_fetched': (bse_report or {}).get('groups_fetched'),
        'cross_exchange_aliases_resolved': len(alias_rows),
    })
    print(f'  WRITE market_cap: {len(rows)} symbols ({len(nse_rows)} NSE + {len(bse_rows)} BSE + '
          f'{len(alias_rows)} cross-exchange aliases) -> {key}')
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

    manifest['reference_data'] = [write_market_cap(client)]

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
