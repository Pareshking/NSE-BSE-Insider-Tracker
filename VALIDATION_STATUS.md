# Validation Status — NSE + BSE

Last updated: 2026-09-01

## Operating rule

No one-year R2 backfill and no production-schema freeze until all pipeline validation gates are cleared and the user explicitly authorizes the next stage.

## Current execution order

Finish NSE completely before starting BSE. Within NSE: Insider → Bulk → Block → NSE-only validation/documentation. Each category uses its own acquisition code and must pass real-output/date/completeness/dedup validation before the next category is accepted.

## Acquisition architecture

NSE and BSE acquisition engines are separate. NSE categories are now also isolated:

- `scripts/nse_insider.py` — NSE Insider Trading only; official corporate-filings PIT endpoint; independent date-window testing.
- `scripts/nse_bulk.py` — NSE Bulk Deals only.
- `scripts/nse_block.py` — NSE Block Deals only.
- `scripts/nse_acquisition.py` — shared NSE helper/legacy engine retained for compatibility; not the category certification path.
- `scripts/bse_acquisition.py` — BSE-specific acquisition engine.
- `scripts/acquisition_probe.py` — orchestration/legacy evidence only; it must not define the correctness of an exchange/category.

Page count is never a completeness criterion. Pagination is only a transport mechanism. Completion is determined by verified date coverage and source semantics.

## NSE gates

### Insider Trading — IN PROGRESS / BLOCKED until fresh run

Previous probe returned HTTP 200 with a header-only CSV and zero parsed rows. That was not evidence that NSE had no insider records. The official NSE page exposes date windows and archive data. A new isolated `scripts/nse_insider.py` now establishes an NSE session and queries the native JSON response for 1-day, 5-day, 30-day and 1-year windows, recording status, response mode, columns and counts. Commit introducing the isolated engine: `90624a5241c1bce6c98352763f3dda131fb4c633`.

PASS requires a real non-empty dataset or documented proof of zero records, correct date semantics, complete requested window, native columns, and duplicate behavior.

### Bulk Deals — IN PROGRESS

Previously observed: 70 unique records for 31-Aug-2026 through the NSE package. It is now isolated in `scripts/nse_bulk.py`. Fresh real-output and date-completeness verification is required before PASS.

### Block Deals — IN PROGRESS

Previously observed: 11 unique records for 31-Aug-2026 through the NSE package. It is now isolated in `scripts/nse_block.py`. Fresh real-output and date-completeness verification is required before PASS.

## BSE gates

BSE validation does not begin as a production gate until all NSE gates are green.

Prior diagnostic baseline: Insider 154 raw / 146 unique; Bulk 73 / 73; Block 19 / 17; Rights and Preferential were capped at five pages only. Those figures are not full-day completeness certification.

## Critical date rule

Dates are source-specific and semantic. Do not collapse them into one `event_date` prematurely. Preserve transaction/deal date, acquisition/allotment date, disclosure/filing date, broadcast date and retrieval timestamp where available. BSE Insider already demonstrated that a 31-Aug broadcast can contain an earlier acquisition date.

## Deduplication rule

1. Deduplicate within NSE using fields appropriate to the category.
2. Deduplicate within BSE independently.
3. Cross-match NSE↔BSE only after both sources are independently certified.
4. Insider disclosures may represent the same underlying disclosure across exchanges; Bulk/Block executions remain exchange-aware and must not be automatically collapsed.

## Mandatory loop

For each category: **test → inspect real output → identify defect → fix → retest → verify → update documents → move to next category only after validation is complete.**

A green GitHub workflow is not data-quality certification. Actual records, native columns, relevant date fields, completeness, pagination/termination behavior and duplicate behavior must be inspected.
