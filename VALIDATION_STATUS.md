# Validation Status — NSE + BSE

Last updated: 2026-09-01

## Operating rule

No one-year R2 backfill and no production-schema freeze until all pipeline validation gates are cleared and the user explicitly authorizes the next stage.

## Current execution order

NSE and BSE acquisition/validation are **strictly separate**. The earlier combined workflow is legacy/diagnostic only. The active pipeline may proceed exchange-by-exchange without allowing one broken category to stop usable categories.

NSE categories: **Insider Trading → Bulk Deals → Block Deals → Rights Issues → Preferential Issues → NSE certification**.
BSE categories: **Insider Trading → Bulk Deals → Block Deals → Rights Issues → Preferential Issues → BSE certification**.

For every category: preserve working acquisition, record unresolved defects as TODO, and continue to the next independent category when the current category's usable scope is validated. Do not declare full exchange certification until all required categories and date/completeness/dedup gates pass.

## Acquisition architecture

NSE and BSE acquisition engines are separate. NSE categories are isolated where their source mechanics differ:

- `scripts/nse_insider.py` — NSE Insider Trading only; independent date-window testing.
- `scripts/nse_bulk.py` — NSE Bulk Deals only.
- `scripts/nse_block.py` — NSE Block Deals only.
- `scripts/nse_rights.py` — NSE Rights Issue extraction/validation.
- `scripts/nse_preferential.py` — NSE Preferential Issue extraction/validation.
- `scripts/nse_acquisition.py` — shared NSE helper/legacy engine retained for compatibility; not the category certification path.
- `scripts/bse_acquisition.py` — BSE-specific acquisition engine.
- `scripts/acquisition_probe.py` — legacy/diagnostic orchestration only.

### Dedicated workflow rule

`/.github/workflows/nse-validation.yml` is the dedicated **NSE-only** validation workflow. It must not acquire BSE data.

`/.github/workflows/bse-validation.yml` is the dedicated **BSE-only** validation workflow. It must not acquire NSE data.

`/.github/workflows/data-validation.yml` is the older **combined NSE+BSE diagnostic workflow**. It is not an exchange certification workflow and must not be used for NSE or BSE certification.

**Never repeat the mistake of using the combined workflow as an NSE/BSE certification run.** New validation work must use the appropriate exchange-specific workflow.

## Date/completeness rule

Page count is never a completeness criterion. Pagination is only a transport mechanism. Completion is determined by verified date coverage and source semantics.

A one-day result is not historical certification. Where practical, use a 90-day test to establish date-range behavior and inspect the actual distinct source dates returned.

## NSE status

### Insider Trading — WORKING ACQUISITION / PENDING CERTIFICATION

A previous isolated probe returned a real 1-year NSE dataset (9,347 records), with native fields including `personCategory`, `acqName`, `buyQuantity`, `sellquantity`, `buyValue`, `sellValue`, `date`, `exchange`, etc. Short-window behavior returned zero and therefore requires date-semantic validation.

**TODO:** certify 90-day date behavior, promoter/person-category classification, BUY/SELL semantics, completeness and intra-NSE dedup.

### Bulk Deals — WORKING ACQUISITION / PENDING CERTIFICATION

Previous isolated capture returned 70 real records for 31-Aug-2026 with native NSE fields including `BD_DT_DATE`, `BD_SYMBOL`, `BD_CLIENT_NAME`, `BD_BUY_SELL`, `BD_QTY_TRD`, and `BD_TP_WATP`.

**TODO:** certify 90-day historical coverage, termination/completeness and intra-NSE dedup.

### Block Deals — WORKING ACQUISITION / PENDING CERTIFICATION

Previous isolated capture returned 11 real records for 31-Aug-2026 with native NSE fields.

**TODO:** certify 90-day historical coverage, termination/completeness and intra-NSE dedup.

### Rights Issues — EXTRACTION NOT YET CERTIFIED

Official NSE source: `https://www.nseindia.com/companies-listing/corporate-filings-RI`.

The page is JavaScript-rendered and exposes lifecycle information such as Record Date, Rights Ratio, Offer Price, Issue Opening/Closing, Entitlement dates, Allotment, Shares Allotted, Amount Raised, Listing, Trading Approval and Submission Date.

The prior requests-only approach captured the page shell. Browser-rendered extraction was implemented, but the dedicated validation artifact showed no usable Rights tables.

**TODO:** identify the real underlying data/API or reliable browser extraction, validate 90-day output, native fields and date semantics.

### Preferential Issues — EXTRACTION FAILED / PENDING FIX

Official NSE source: `https://www.nseindia.com/companies-listing/corporate-filings-PREF`.

The native page is JavaScript-rendered and exposes company, board resolution, allottee category, consideration, offer price, allotment, shares, amount raised, listing, trading approval, submission and lock-in information.

The dedicated NSE run failed at Preferential acquisition and produced no certified real dataset.

**TODO:** identify the real underlying data/API or reliable browser extraction, validate 90-day output, native fields and date semantics.

## BSE status

BSE proceeds independently and does not wait for unresolved NSE items.

### BSE baseline acquisition evidence

Previous BSE diagnostic evidence showed:

- Insider: 154 raw / 146 unique
- Bulk: 73
- Block: 19 raw / 17 unique
- Rights: 50 index records
- Preferential: 125 index records

These are acquisition evidence, not historical certification.

### BSE Validation Only #3 — 90-day test result

Run: **BSE Validation Only #3** (`c792abf`, run `33448485907`), manually triggered on `main`, completed **Success** in 1m31s with one BSE-only evidence artifact.

The run produced genuine BSE evidence, but the returned transaction data was overwhelmingly the 31-Aug-2026 capture rather than a demonstrably complete 90-day history. Therefore the run is accepted as **BSE acquisition validation**, but **not 90-day historical certification**.

Observed results:

- Insider: real records; promoter-group acquisition is present in source semantics. Example evidence includes `Promoter Group` + `Acquisition`, transaction date 26/08/2026 and broadcast date 31/08/2026.
- Bulk: 73 real rows; native fields include deal date, security code/name, client name, deal type, quantity and price; BUY/SELL direction is present.
- Block: 19 raw rows; real BSE block records captured; intra-source deduplication remains required.
- Rights: 50 index/list records and View Detail links; underlying lifecycle/detail extraction remains pending.
- Preferential: 125 index/list records and View Detail links; underlying lifecycle/detail extraction remains pending.

**TODO:** obtain genuine BSE 90-day historical transaction coverage for Insider/Bulk/Block; inspect distinct dates and completeness; normalize Insider fields; perform intra-BSE dedup; extract Rights/Preferential detail pages.

### BSE Insider normalization defect

The raw BSE Insider source contains meaningful promoter/category and acquisition fields, but the current normalized representation does not reliably map positional BSE columns into `event_date`, company, person and related normalized fields.

**TODO:** map BSE native columns explicitly and test against real promoter acquisition records before certification.

### BSE Bulk / Block

Bulk acquisition is working. Block acquisition is working, with raw-vs-unique counts demonstrating that deduplication matters.

**TODO:** prove historical date-range behavior, source completeness and deterministic intra-BSE dedup keys.

### BSE Rights / Preferential

The index/list layer is working and exposes companies plus View Detail links. The detail/lifecycle layer is not yet certified.

**TODO:** follow View Detail links, extract native lifecycle fields, determine date semantics and validate historical coverage.

## Promoter transaction rule

Promoter buying must be identified from source semantics, not merely `buyQuantity > 0`. Preserve person/category, transaction/acquisition date, buy/sell quantities and values, mode/type and disclosure/broadcast date. Validate promoter/PAC classification independently for NSE and BSE.

## Deduplication rule

1. Deduplicate within NSE using category-appropriate keys.
2. Deduplicate within BSE independently.
3. Cross-match NSE↔BSE only after both exchanges are independently certified.
4. Insider disclosures may represent the same underlying disclosure across exchanges; Bulk/Block executions remain exchange-aware and must not be automatically collapsed.
5. Rights/Preferential are issue/lifecycle observations; repeated lifecycle rows must not inflate underlying issue counts.

## Mandatory engineering loop

**test → inspect real output → identify defect → fix → retest → verify → update documents → continue**.

Do not stop the overall pipeline because one category fails. Keep verified/working categories and record failed categories as explicit TODO/pending gates. Do not call a green GitHub workflow data-quality certification without inspecting records, dates, native columns, completeness and duplicates.

## Current decision

- NSE: Insider/Bulk/Block acquisition working but not fully certified; Rights pending; Preferential pending/failing.
- BSE: Insider/Bulk/Block acquisition working; BSE #3 confirmed real source acquisition but **90-day historical certification remains pending**; Rights/Preferential index acquisition works but detail extraction remains pending.
- Combined workflow: legacy diagnostic only; **never use it as the certification path again**.
- Cross-exchange matching: blocked until independent exchange certification.
- R2 backfill: blocked.
- Production schema freeze: blocked.
