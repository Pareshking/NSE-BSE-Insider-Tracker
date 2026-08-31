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
- `scripts/nse_rights.py` — NSE Rights Issue extraction/validation using the official JS-rendered RI page.
- `scripts/nse_preferential.py` — NSE Preferential Issue extraction/validation using the official JS-rendered PREF page.
- `scripts/nse_acquisition.py` — shared NSE helper/legacy engine retained for compatibility; not the category certification path.
- `scripts/bse_acquisition.py` — BSE-specific acquisition engine.
- `scripts/acquisition_probe.py` — orchestration/legacy evidence only; it must not define the correctness of an exchange/category.

### Dedicated workflow rule

`/.github/workflows/nse-validation.yml` is the dedicated **NSE-only** validation workflow. It must not acquire BSE data. The older `data-validation.yml` remains a combined/legacy workflow and is **not** an NSE certification workflow. A green combined workflow must never be interpreted as NSE certification.

Rights/Preferential must be explicitly investigated on **both NSE and BSE**. They are issue/lifecycle data, not merely another deal table.

Page count is never a completeness criterion. Pagination is only a transport mechanism. Completion is determined by verified date coverage and source semantics.

## NSE gates

### Insider Trading — IN PROGRESS / BLOCKED until fresh isolated run

Previous isolated probe returned a real 1-year NSE dataset (9,347 records) but short windows returned zero. That discrepancy means date-window semantics are not yet certified. The official NSE page exposes date windows and archive data. The isolated `scripts/nse_insider.py` records response mode, native columns and counts for 1-day, 5-day, 30-day and 1-year windows.

PASS requires a real non-empty dataset or documented proof of zero records, correct date semantics, complete requested window, native columns, and duplicate behavior.

### Bulk Deals — GREEN FOR ACQUISITION / CERTIFICATION PENDING

The isolated NSE engine produced **70 real records for 31-Aug-2026** in the previous validation run. Native NSE fields were observed, including `BD_DT_DATE`, `BD_SYMBOL`, `BD_CLIENT_NAME`, `BD_BUY_SELL`, `BD_QTY_TRD`, and `BD_TP_WATP`. Acquisition is therefore green, but historical date-window completeness and final dedup certification remain open.

### Block Deals — GREEN FOR ACQUISITION / CERTIFICATION PENDING

The isolated NSE engine produced **11 real records for 31-Aug-2026** in the previous validation run. Native NSE fields were observed. Acquisition is therefore green, but historical date-window completeness and final dedup certification remain open.

### Rights Issues — EXTRACTION IMPLEMENTED / RETEST REQUIRED

Official NSE source: `https://www.nseindia.com/companies-listing/corporate-filings-RI`.

The native page is JavaScript-rendered and exposes Company Details plus a lifecycle table containing Record Date, Rights Ratio, Offer Price, Issue Opening/Closing, Entitlement Opening/Closing, Date of Allotment, Number of Shares Allotted, Amount Raised, Number of Shares Listed, Date of Listing, Date of Trading Approval, Revised Flag and Date of Submission. The previous requests-only probe captured the page shell instead of the populated records. The implementation now uses Selenium to render the official page and extracts the actual DOM tables for 1D/5D/30D/1Y windows. This is **not certified until a fresh run proves real rows and date coverage**.

### Preferential Issues — EXTRACTION IMPLEMENTED / RETEST REQUIRED

Official NSE source: `https://www.nseindia.com/companies-listing/corporate-filings-PREF`.

The native page is JavaScript-rendered and exposes Company Details and lifecycle sections containing Symbol, Company Name, ISIN, CIN, Board Resolution Date, Allottee Category, Consideration, Offer Price, Date of Allotment, Total Number of Shares Allotted, Amount Raised, Date of Listing, Date of Trading Approval, Date of Submission and lock-in details. The previous requests-only probe captured the page shell instead of the populated records. The implementation now uses Selenium to render the official page and extracts the actual DOM tables for 1D/5D/30D/1Y windows. This is **not certified until a fresh run proves real rows and date coverage**.

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

NSE remains the active exchange. Bulk and Block acquisition are green; Insider remains blocked on date semantics; Rights and Preferential have corrected browser-based extraction code awaiting fresh real-output validation. Do not start BSE until every NSE category is independently certified. Do not build production R2 data or freeze the production schema before explicit authorization.
