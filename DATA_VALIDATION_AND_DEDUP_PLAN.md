# NSE + BSE Data Validation, Normalization & Cross-Exchange Deduplication Plan

## Purpose

This is the mandatory validation stage before production R2 storage/backfill. Validation applies to **both NSE and BSE**, while preserving native source structures.

A green GitHub Action is not sufficient evidence of correctness. Actual records, columns, dates, identities and counts must be inspected.

## Mandatory dataset inventory

The project must explicitly cover these categories on **both exchanges where the exchange publishes the corresponding data**:

1. Insider Trading
2. Bulk Deals
3. Block Deals
4. Rights Issues
5. Preferential Issues / Preferential Allotment
6. Allotment/listing lifecycle events where published as a distinct source surface
7. Other relevant corporate-filing surfaces discovered during source audit

**Rights and Preferential are mandatory and must not be omitted from the NSE sequence.**

## Source architecture

NSE and BSE acquisition are independent. Where category source mechanics differ materially, use category-specific acquisition code. The acquisition layer preserves native records; normalization happens downstream.

`raw_native_record -> source/category parser -> canonical fields + preserved source fields`

Never rename/drop source fields merely to make NSE and BSE look identical.

## Date-first completeness rule

Page count is never the definition of completeness. Pagination is only a transport mechanism.

For every category determine which date the exchange actually filters on and preserve all relevant dates, including where applicable:

- transaction/deal date;
- acquisition/disposal date;
- issue/announcement date;
- approval date;
- allotment date;
- listing/trading commencement date;
- disclosure/filing date;
- broadcast/publication timestamp;
- retrieval timestamp.

A requested date must not be confused with a record's transaction date. Historical tests must deliberately request multiple dates/ranges.

## NSE execution order

Finish **all NSE categories first**, in this order:

### 1. NSE Insider Trading

Verify official source, session behavior, native columns, date-window semantics, historical/archive route, complete requested window, BUY/SELL/action fields and intra-source duplicates.

### 2. NSE Bulk Deals

Verify official source, native structure, date semantics, completeness/history, BUY/SELL and intra-source duplicates.

### 3. NSE Block Deals

Verify official source, native structure, date semantics, completeness/history, BUY/SELL/deal type and intra-source duplicates.

### 4. NSE Rights Issues

Identify the exact official NSE source surface and validate the issue/lifecycle structure. Verify announcement/approval/allotment/listing dates separately, issuer/security identity, issue terms and historical completeness. Do not treat an issue-stage row as a simple transaction row.

### 5. NSE Preferential Issues / Preferential Allotment

Identify the exact official NSE source surface and validate issue/allotment lifecycle fields, dates, issuer/security identity, quantities/terms and historical completeness. Do not merge this category into Rights merely because both are issuance events.

### 6. NSE-only certification

Only after all five categories pass their individual gates, perform the unified NSE validation and update the handover/status documents. Then, and only then, begin BSE.

## BSE execution order

BSE begins only after NSE is completely certified. Repeat the same category-by-category source/date/completeness/dedup process, including Rights and Preferential.

## Native-schema requirement

NSE and BSE may have different column names, identifiers, date formats and semantics. Store source-specific fields alongside canonical fields. Examples previously observed include NSE `BD_DT_DATE`/`BD_DT_ORDER`/`BD_BUY_SELL` versus different BSE table fields, and different Insider date/holding representations.

## Intra-source deduplication

Deduplicate separately within each exchange/category. Prefer official document/event IDs; otherwise use a deterministic category-specific fingerprint. Do not use weak keys such as company + date + BUY/SELL.

For Rights/Preferential, create an issue identity and attach lifecycle observations rather than counting every lifecycle row as a new issue.

## Cross-exchange matching

Only after both exchanges are independently certified.

Classify candidates as exact mirrored disclosure, same economic event/different representation, exchange-specific, potential match, or unrelated. Preserve every source observation and provenance.

Insider disclosures may be mirrored across NSE/BSE. Bulk/Block executions remain exchange-aware and must not be automatically collapsed merely because issuer/client/date/quantity look similar.

## Acceptance gates before R2

For **every NSE and BSE category**:

- [ ] Exact native columns documented.
- [ ] Relevant date fields and meanings documented.
- [ ] Real records inspected.
- [ ] Requested date/window completeness demonstrated.
- [ ] Historical retrieval demonstrated.
- [ ] Pagination/archive termination mechanism demonstrated where applicable.
- [ ] BUY/SELL/action/deal types verified where applicable.
- [ ] Intra-source duplicates measured and classified.
- [ ] Stable source/canonical identity demonstrated.
- [ ] Rights/Preferential lifecycle semantics validated separately.
- [ ] Cross-exchange matching completed after source certification.
- [ ] Mirrored disclosures do not inflate canonical counts.
- [ ] Genuine exchange-specific observations are retained.

Only after all gates pass **and after explicit user authorization** may production schema freeze and one-year R2 backfill begin.
