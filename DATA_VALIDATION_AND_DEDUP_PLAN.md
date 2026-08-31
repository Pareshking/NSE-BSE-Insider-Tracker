# NSE + BSE Data Validation, Normalization & Cross-Exchange Deduplication Plan

## Purpose

This document is the mandatory validation stage before production R2 storage/backfill. Validation applies to **both NSE and BSE**, while preserving their native source structures.

The objective is to prevent duplicate rows, mirrored disclosures being counted twice, cross-exchange records being blindly combined, date-window mistakes, and loss of exchange-specific fields caused by premature schema flattening.

A green GitHub Action is not sufficient evidence of correctness. The actual records, columns, dates, identities and counts must be inspected.

## Critical rule: native NSE and BSE schemas are retained

NSE and BSE do **not** have to expose identical columns, names, date formats, identifiers or semantics. The production model therefore uses:

`raw_native_record -> source-specific parser -> canonical fields + preserved source fields`

Never rename/drop source fields merely to make NSE and BSE look identical.

Examples already observed:

- NSE Bulk/Block: `BD_DT_DATE`, `BD_DT_ORDER`, `BD_SYMBOL`, `BD_SCRIP_NAME`, `BD_CLIENT_NAME`, `BD_BUY_SELL`, `BD_QTY_TRD`, `BD_TP_WATP`.
- BSE Bulk: positional/table structure with `31/08/2026`, security code, security name/symbol, client, `B`/`S`, quantity and price.
- NSE Insider CSV: 29 source columns with long descriptive names and separate acquisition/disposal, prior/post holding, initiation and broadcast fields.
- BSE Insider: different field positions/names and separate acquisition date and broadcast date.

## Stage A — Source-level inspection (NSE + BSE)

For every dataset and acquisition method, capture source exchange, dataset, URL/endpoint/document reference, retrieval timestamp, requested date/range, every relevant source date, exact native column names/order, normalized names, row count, critical nulls, date min/max, BUY/SELL or deal-type distribution, source/document ID, parser/schema version and raw content hash.

Datasets are evaluated independently: Insider Trading, Bulk Deals, Block Deals, Rights Issues, Preferential Issues, Allotment/listing lifecycle events, and corporate filings where used as a source layer.

## Stage B — Date validation comes before counting completeness

A page/CSV returning records is **not** evidence that it returned the requested day's dataset.

For every dataset distinguish:

- transaction/deal/acquisition date;
- disclosure/broadcast/filing date;
- publication timestamp;
- retrieval date.

Never substitute retrieval date for transaction date.

Historical tests must deliberately request multiple dates/ranges, not only the latest trading day.

### Important finding from the 2026-08-31 artifact

BSE Insider returned **146 unique records** whose **broadcast date is 31/08/2026**, while acquisition dates span earlier dates. Correct interpretation: these are disclosures broadcast on 31-Aug that disclose transactions occurring on earlier dates; they are not 146 transactions executed on 31-Aug.

BSE Bulk/Block records in the artifact are dated 31/08/2026 / 31 Aug 26. NSE Bulk/Block records are dated 31-AUG-2026.

NSE Insider in the artifact returned a valid CSV header but zero parsed rows. This is **not accepted as proof of zero insider activity** because the official NSE page exposes 1D/1W/1M/3M/6M/1Y/Custom and Archive Data controls. The acquisition probe has been changed to test multiple date windows and actually parse the CSV rather than treating HTTP 200/header-only as success. urlNSE Insider Trading pagehttps://www.nseindia.com/companies-listing/corporate-filings-insider-trading

## Stage C — Intra-source deduplication

Before comparing NSE with BSE, detect duplicates inside each individual acquisition result.

Do not use weak keys such as `company + date + BUY/SELL`.

Preferred identity hierarchy:

1. Official source transaction/document/event ID.
2. Official filing number/reference plus event attributes.
3. Deterministic fallback fingerprint built from normalized fields.

### Insider fingerprint candidates

Issuer/security identity (prefer ISIN/security code), transaction/acquisition date, participant name, action type, security type, quantity, price/value, filing/broadcast/event reference and prior/post holding where useful.

### Bulk/Block fingerprint candidates

Exchange, deal date, security/ISIN/security code, client, buy/sell/deal type, quantity, trade price/WATP and source reference.

Repeated identical rows must be classified as parser/source duplication only after checking whether the source itself legitimately contains multiple identical-looking executions.

### Rights/Preferential

Create an issue identity first, then attach lifecycle events:

`announcement -> approval -> allotment -> listing approval -> trading commencement`

## Stage D — NSE validation

Repeat the complete source/date/dedup process for NSE.

Verified observations from the supplied artifact:

- Bulk: **70 rows, 70 unique**, source date `31-AUG-2026`.
- Block: **11 rows, 11 unique**, source date `31-AUG-2026`.
- Insider: **0 parsed rows**, but the HTTP response was a valid CSV containing the 29-column schema/header. This is **UNRESOLVED**, not “no data”.

The acquisition probe is now testing NSE Insider using target-day, 5-day, 30-day and 1-year windows and parsing the returned CSV. The official page also exposes Archive Data and 1Y/Custom controls, so the historical route must be tested explicitly.

## Stage E — BSE validation

Verified observations from the supplied artifact:

- Bulk: **73 raw / 73 unique**, all `31/08/2026`.
- Block: **19 raw / 17 unique**, all `31 Aug 26`.
- Insider: **154 raw / 146 unique**; broadcast date `31/08/2026`, transaction/acquisition dates earlier.
- Rights: **50 rows captured during the 5-page test**; these are issue-stage/company rows, not yet a complete one-day transaction dataset.
- Preferential: **125 rows in the current raw artifact / 250 DOM row count observed in an earlier 5-page representation**; this surface is not yet certified as complete.

The 5-page limit is a **test safety cap only**. It must never be interpreted as “full day” or “complete historical dataset.” Pagination termination and total-result discovery must be established before production.

BSE Insider duplicate rows must be investigated at record level before finalizing the dedup fingerprint. BSE rendered pages may expose multiple DOM representations of the same source data.

## Stage F — Historical completeness tests

For each dataset establish the actual source mechanism for:

1. requested day;
2. previous trading day;
3. multi-day range;
4. one-month range;
5. one-year/archive range where supported.

For paginated pages record first-page count, every page traversed, final-page/termination condition, total pages if exposed, raw rows, unique rows and date distribution across all pages.

A fixed test limit such as five pages is only for safe experimentation and must be clearly labelled as incomplete.

## Stage G — Cross-exchange duplication audit

Do **not** simply concatenate NSE + BSE.

Classify candidate matches as:

1. Exact mirrored disclosure.
2. Same economic event, different source representation.
3. Exchange-specific transaction.
4. Potential match.
5. Unrelated.

### Insider

Compare after source-specific normalization: issuer/ISIN/security code, participant, transaction/acquisition date, disclosure/broadcast date, action, security type, quantity, price/value, prior/post holdings, filing/document IDs and execution exchange where disclosed.

Do not require identical column names or date strings.

**Never delete a source observation merely because it matches another exchange.** Provenance is retained.

### Bulk/Block

Do **not** automatically deduplicate identical-looking NSE and BSE deal rows. They are exchange-specific market executions. Only classify as mirrored when source evidence demonstrates that it is the same disclosure/event. Otherwise retain both and include `execution_exchange`.

### Rights/Preferential

Create one canonical `issue_id` for the underlying issue and retain NSE/BSE filings as separate source observations/lifecycle events.

## Stage H — Canonical schema

Minimum common fields:

- `canonical_event_id`
- `source_observation_id`
- `exchange`
- `dataset`
- `issuer_name`
- `isin` where available
- `security_code` where available
- `symbol`
- `event_date`
- `transaction_date` where applicable
- `filing_date`
- `broadcast_date`
- `participant_name`
- `action`
- `quantity`
- `price`
- `value`
- `source_document_id`
- `source_url`
- `retrieved_at`
- `content_hash`
- `schema_version`
- `dedup_status`
- `match_confidence`

Dataset-specific fields remain separate. Native NSE/BSE fields and raw values must remain auditable.

## Stage I — Acceptance tests before R2 historical backfill

All of the following must pass for **both NSE and BSE**:

- [ ] Exact native source columns documented.
- [ ] Native date fields and meanings documented.
- [ ] Critical fields parsed correctly.
- [ ] Transaction/deal/acquisition dates validated.
- [ ] Filing/broadcast dates validated separately.
- [ ] BUY records verified where applicable.
- [ ] SELL records verified where applicable.
- [ ] Intra-source duplicates measured and classified.
- [ ] Historical date retrieval verified on multiple dates.
- [ ] Pagination/Archive completeness verified where applicable.
- [ ] Repeated acquisition produces stable canonical IDs.
- [ ] Source observations remain auditable.
- [ ] Cross-exchange comparison completed.
- [ ] Mirrored disclosures do not inflate canonical counts.
- [ ] Genuine exchange-specific transactions are not incorrectly removed.
- [ ] Rights/Preferential lifecycle events do not inflate issue counts.
- [ ] Only after these tests pass: proceed to compact Parquet/R2 production storage and one-year backfill.

## Current decision

Do **not** build production R2 data from current probe counts. The next engineering stage is a joint **NSE + BSE record-level validation and historical completeness experiment**, with NSE Insider specifically unresolved and BSE pagination/date semantics still under test. This precedes historical backfill and production schema finalization.
