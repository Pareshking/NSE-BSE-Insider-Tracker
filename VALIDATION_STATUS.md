# Validation Status — NSE + BSE

Last updated: 2026-09-01

## Operating rule

No one-year R2 backfill and no production-schema freeze until all pipeline validation gates are cleared and the user explicitly authorizes the next stage.

## Current execution order

**Finish NSE completely before starting BSE.** NSE categories are: **Insider Trading → Bulk Deals → Block Deals → Rights Issues → Preferential Issues → NSE-only validation/documentation**. Each category uses independent acquisition logic where useful and must pass real-output/date/completeness/dedup validation before the next category is accepted. Do not omit Rights or Preferential Issues.

## Acquisition architecture

NSE and BSE acquisition engines are separate. NSE categories are isolated where their source mechanics differ:

- `scripts/nse_insider.py` — NSE Insider Trading only; official corporate-filings PIT endpoint; independent date-window testing.
- `scripts/nse_bulk.py` — NSE Bulk Deals only.
- `scripts/nse_block.py` — NSE Block Deals only.
- `scripts/nse_acquisition.py` — shared NSE helper/legacy engine retained for compatibility; not the category certification path.
- `scripts/bse_acquisition.py` — BSE-specific acquisition engine.
- `scripts/acquisition_probe.py` — orchestration/legacy evidence only; it must not define the correctness of an exchange/category.

Rights/Preferential must be explicitly investigated on **both NSE and BSE**. They are issue/lifecycle data, not merely another deal table.

Page count is never a completeness criterion. Pagination is only a transport mechanism. Completion is determined by verified date coverage and source semantics.

## NSE gates

### Insider Trading — IN PROGRESS / BLOCKED until fresh run

Previous probe returned HTTP 200 with a header-only CSV and zero parsed rows. That was not evidence that NSE had no insider records. The official NSE page exposes date windows and archive data. A new isolated `scripts/nse_insider.py` establishes an NSE session and queries the native response for 1-day, 5-day, 30-day and 1-year windows, recording status, response mode, columns and counts.

PASS requires a real non-empty dataset or documented proof of zero records, correct date semantics, complete requested window, native columns, and duplicate behavior.

### Bulk Deals — IN PROGRESS

Previously observed: 70 unique records for 31-Aug-2026 through the NSE package. It is isolated in `scripts/nse_bulk.py`. Fresh real-output and date-completeness verification is required before PASS.

### Block Deals — IN PROGRESS

Previously observed: 11 unique records for 31-Aug-2026 through the NSE package. It is isolated in `scripts/nse_block.py`. Fresh real-output and date-completeness verification is required before PASS.

### Rights Issues — NOT YET VALIDATED

NSE Rights Issue acquisition/filing coverage is a mandatory NSE gate. The exact official NSE source, date semantics, lifecycle fields, historical/archive behavior and completeness mechanism must be identified and tested before this category can pass.

### Preferential Issues — NOT YET VALIDATED

NSE Preferential Issue/allotment coverage is a mandatory NSE gate. The exact official NSE source, date semantics, lifecycle fields, historical/archive behavior and completeness mechanism must be identified and tested before this category can pass.

## BSE gates

BSE validation does not begin as a production gate until all NSE gates are green.

Prior diagnostic baseline: Insider 154 raw / 146 unique; Bulk 73 / 73; Block 19 / 17; Rights and Preferential were capped at five pages only. Those figures are not full-day completeness certification.

## Critical date rule

Dates are source-specific and semantic. Do not collapse them into one `event_date` prematurely. Preserve transaction/deal date, acquisition/allotment date, disclosure/filing date, broadcast date and retrieval timestamp where available. BSE Insider already demonstrated that a 31-Aug broadcast can contain an earlier acquisition date.

For Rights/Preferential, distinguish issue/announcement date, approval date, allotment date, listing/commencement date and filing/publication date wherever supplied.

## Deduplication rule

1. Deduplicate within NSE using fields appropriate to the category.
2. Deduplicate within BSE independently.
3. Cross-match NSE↔BSE only after both sources are independently certified.
4. Insider disclosures may represent the same underlying disclosure across exchanges; Bulk/Block executions remain exchange-aware and must not be automatically collapsed.
5. Rights/Preferential records are issue/lifecycle observations; repeated lifecycle rows must not inflate the underlying issue count.

## Mandatory loop

For each category: **test → inspect real output → identify defect → fix → retest → verify → update documents → move to next category only after validation is complete.**

A green GitHub workflow is not data-quality certification. Actual records, native columns, relevant date fields, completeness, pagination/termination behavior and duplicate behavior must be inspected.

## Current decision

NSE remains the active exchange. The complete NSE gate list now explicitly includes Insider, Bulk, Block, Rights and Preferential Issues. Do not start BSE until every NSE category is independently certified. Do not build production R2 data or freeze the production schema before explicit authorization.
