# NSE + BSE Data Validation, Normalization & Cross-Exchange Deduplication Plan

## Purpose

This document extends `PROJECT_PLAN.md` with the mandatory validation stage before production R2 storage/backfill. Validation applies to **both NSE and BSE**, not BSE alone.

The objective is to prevent three classes of errors:

1. duplicate rows within one exchange/source;
2. the same disclosure represented multiple times by different source surfaces;
3. NSE and BSE records being blindly combined when they represent the same underlying disclosure/event.

A green GitHub Action is not sufficient evidence of correctness. The actual records, columns, dates, identities and counts must be inspected.

## Stage A — Source-level inspection (NSE + BSE)

For every dataset and acquisition method, capture:

- source exchange;
- dataset/domain;
- source URL/endpoint/document reference;
- retrieval timestamp;
- source-reported date/range;
- exact column names;
- normalized column names;
- row count;
- null/blank counts for critical fields;
- date min/max;
- BUY/SELL or Deal Type distribution where applicable;
- source identifier/document identifier if supplied;
- parser/schema version;
- raw content hash.

Datasets are evaluated independently:

- Insider Trading
- Bulk Deals
- Block Deals
- Rights Issues
- Preferential Issues
- Allotment/listing lifecycle events
- Corporate filings where used as a source layer

## Stage B — Intra-source deduplication

Before comparing NSE with BSE, detect duplicates inside each individual acquisition result.

### Do not use weak keys such as

`company + date + BUY/SELL`

### Preferred identity hierarchy

1. Official source transaction/document/event ID.
2. Official filing number/reference plus event attributes.
3. Deterministic fallback fingerprint built from normalized fields.

The fallback fingerprint should use the fields appropriate to the dataset, for example:

### Insider

- issuer/security identity (prefer ISIN);
- transaction date;
- participant name normalized but original preserved;
- transaction/action type;
- BUY/SELL/action;
- security type;
- quantity;
- price/value;
- disclosed filing/event reference when available.

### Bulk/Block

- **exchange must remain part of the raw identity**;
- deal date;
- security/ISIN/security code;
- client name;
- buy/sell/deal type;
- quantity;
- trade price/WATP;
- source reference where available.

Repeated identical rows must be classified as parser/source duplication only after checking whether the source itself legitimately contains multiple identical-looking executions.

### Rights/Preferential

Do not treat every filing as a new issue. First create an issue identity, then attach lifecycle events.

Possible lifecycle events:

`announcement → approval → allotment → listing approval → trading commencement`

## Stage C — Date validation

For every dataset distinguish:

- transaction/deal date;
- disclosure/filing date;
- publication timestamp;
- retrieval date.

Never substitute retrieval date for transaction date.

Historical tests must deliberately request multiple dates, not only the latest trading day.

Acceptance requires that the returned records actually belong to the requested period.

## Stage D — NSE validation

Repeat the complete Stage A-C process for NSE.

Current known acquisition observations:

- NSE Insider direct API produced CSV successfully in the probe.
- NSE Bulk produced 70 records through the `nse` library/server route.
- NSE Block produced 11 records through the `nse` library/server route.
- Direct NSE bulk/block requests can return the NSE blocking page.

These counts are **not yet production-certified**. NSE records must still be inspected for exact fields, duplicates, date coverage, BUY/SELL semantics, and historical retrieval.

## Stage E — BSE validation

Repeat the same process for BSE.

Current probe observations on 2026-08-31:

- Bulk: 73 extracted rows.
- Block: 41 extracted rows.
- Insider: 154 extracted rows.
- Rights: 10 extracted rows.
- Preferential: 53 extracted rows.

The BSE Selenium output must be parsed carefully because a rendered page can expose both a compact/table representation and a second representation of the same rows. `row_count` must therefore be calculated after normalization/deduplication, not merely from every DOM representation.

The current BSE block sample also contains apparently identical rows (for example repeated client/quantity/price combinations). These must be investigated before deletion: an identical-looking row can be a genuine separate execution or a duplicated DOM representation.

## Stage F — Cross-exchange duplication audit

This is mandatory before canonical storage.

### Important rule: do NOT simply concatenate NSE + BSE.

For each domain, classify matches as one of:

1. **Exact mirrored disclosure** — same underlying filing/event published by both exchanges.
2. **Same economic event, different source representation** — fields differ slightly but evidence indicates one event.
3. **Exchange-specific transaction** — genuinely separate NSE/BSE execution; retain both.
4. **Potential match** — high similarity but insufficient evidence; retain both and flag for review.
5. **Unrelated** — retain independently.

### Insider cross-exchange matching

For candidate matches compare, after normalization:

- issuer/ISIN;
- participant name;
- transaction date;
- action/BUY/SELL;
- security type;
- quantity;
- price/value;
- filing/document identifiers;
- transaction/execution exchange where disclosed.

Use a deterministic matching score/decision table. Exact or near-exact matches may receive one `canonical_event_id` while retaining two `source_observation` records.

**Never delete the source observation merely because it matches another exchange.** Provenance is retained.

### Bulk/Block cross-exchange matching

Do **not** automatically deduplicate identical-looking NSE and BSE deal rows. Bulk/block deals are exchange-specific market executions and the same participant/date/quantity/price can legitimately occur separately.

Only mark a cross-exchange bulk/block record as a duplicate/mirror when the source explicitly demonstrates that it is the same disclosure/event. Otherwise retain the exchange-specific transaction and include `execution_exchange`.

### Rights/Preferential cross-exchange matching

These are corporate events and are much more likely to be mirrored across NSE/BSE.

Create one canonical `issue_id` for the underlying issue and retain NSE/BSE filings as separate source observations/lifecycle events.

## Stage G — Canonical schema

The production layer should contain both provenance and canonical identity.

Minimum common fields:

- `canonical_event_id`
- `source_observation_id`
- `exchange`
- `dataset`
- `issuer_name`
- `isin` where available
- `symbol`
- `event_date`
- `filing_date` where available
- `participant_name`
- `action`
- `quantity`
- `price`
- `value` where available
- `source_document_id`
- `source_url`
- `retrieved_at`
- `content_hash`
- `schema_version`
- `dedup_status`
- `match_confidence`

Dataset-specific fields remain separate; do not force unrelated concepts into one overloaded table.

## Stage H — Acceptance tests before R2 historical backfill

All of the following must pass for **both NSE and BSE**:

- [ ] Exact source columns documented.
- [ ] Critical fields parsed correctly.
- [ ] Transaction/deal dates validated.
- [ ] BUY records verified where applicable.
- [ ] SELL records verified where applicable.
- [ ] Intra-source duplicates measured and classified.
- [ ] Historical date retrieval verified on multiple dates.
- [ ] Repeated acquisition of the same date produces stable canonical IDs.
- [ ] Source observations remain auditable.
- [ ] Cross-exchange comparison completed.
- [ ] Mirrored disclosures do not inflate canonical counts.
- [ ] Genuine exchange-specific transactions are not incorrectly removed.
- [ ] Rights/Preferential lifecycle events do not inflate issue counts.
- [ ] Only after these tests pass: proceed to compact Parquet/R2 production storage and one-year backfill.

## Current decision

The project will **not** build the production R2 dataset from the current probe counts alone. The next engineering stage is a joint **NSE + BSE record-level validation and cross-exchange deduplication experiment**. This stage precedes historical backfill and production schema finalization.
