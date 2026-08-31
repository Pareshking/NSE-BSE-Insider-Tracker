# Validation Status — NSE + BSE

Last updated: 2026-09-01

## Operating rule

No one-year R2 backfill and no production-schema freeze until all pipeline validation gates are cleared and the user explicitly authorizes the next stage.

## Current execution order

NSE and BSE acquisition/validation are **strictly separate**. The earlier combined workflow is legacy/diagnostic only. The active pipeline may proceed exchange-by-exchange without allowing one broken category to stop usable categories.

NSE categories: **Insider Trading → Bulk Deals → Block Deals → Rights Issues → Preferential Issues → NSE certification**.
BSE categories: **Insider Trading → Bulk Deals → Block Deals → Rights Issues → Preferential Issues → BSE certification**.

## Dedicated workflows

- `.github/workflows/nse-validation.yml` — NSE-only certification path.
- `.github/workflows/bse-validation.yml` — BSE-only certification path.
- `.github/workflows/data-validation.yml` — legacy combined diagnostic only; never certification.

## Date/completeness rule

Page count is never a completeness criterion. A one-day result is not historical certification. 90-day tests must inspect actual distinct source dates, earliest/latest dates, pagination termination, native fields and duplicate behaviour.

## Latest engineering changes — 2026-09-01

### NSE

1. **Insider hardening:** `scripts/nse_insider.py` now bootstraps the actual NSE Insider Trading page session before calling the PIT endpoint and records explicit 1D/7D/30D/90D evidence. Empty JSON also triggers a CSV diagnostic fallback.
2. **Bulk/Block evidence:** both scripts now write per-window counts and distinct dates rather than only aggregate row counts.
3. **Rights/Preferential diagnostics:** both scripts now use browser-rendered diagnostics that capture populated tables, page text and NSE network/API requests for 1D/7D/30D/90D. They do not treat an empty JavaScript shell as success.
4. **Workflow evidence:** the dedicated NSE workflow continues through Rights/Preferential and uploads all NSE-specific evidence directories.

**Observed prior NSE evidence:** the last certification-path run returned 280 Bulk rows and 221 Block rows across four requested windows, but its artifact did not expose per-window distinct dates. Insider returned HTTP 200 JSON with zero rows for all 1D/7D/30D/90D windows while the NSE homepage returned 403. Rights produced zero populated tables. Preferential failed because the old script waited for a table that never appeared.

Current NSE status remains **BLOCKED / PENDING CERTIFICATION** until the hardened scripts are actually executed and their real output inspected.

### BSE — diagnostic run inspected

Run **33449251611 / artifact 9779221849** completed successfully, but it ran the pre-hardening acquisition code. It is useful diagnostic evidence only, not BSE certification.

The 90-day capture exposed the following:

- **Insider:** 158 raw rows; 20 distinct transaction/broadcast date values spanning **2026-02-26 through 2026-08-31**. The date-search click reported `no_change`, so the source's default dataset must not be confused with proof that the requested date range was applied. Native fields and real promoter/acquisition semantics are present.
- **Bulk:** 74 rows, all observed on **31/08/2026**. Date search reported `no_change`. Therefore historical certification is **failed/pending**.
- **Block:** 41 extracted rows, with the first table element containing a whole multiline/tab-separated rendered table. The native row structure is recoverable, but parsing must flatten this representation. Observed records are all **31 Aug 26**. Duplicate executions exist and must be keyed deterministically.
- **Rights:** 110 index rows across 10 captured pages. Underlying API discovered: `Pubissues_FurtherIssuesummary_RI_isd_ng/w?fromdt=&todt=&company=`. Detail/lifecycle extraction is still pending.
- **Preferential:** 530 index rows across 10 captured pages; 20 detail pages produced 712 rendered detail rows. Underlying APIs discovered include `Pubissues_FurtherIssuesummary_Pref_isd_ng/w?fromdt=&todt=&company=` and `Pubissues_FurtherXbrlview_pref_ng/w?Fld_companyid=...&flag=...&Fld_AuthoriseDate=...`. This is strong extraction progress, but not certification until lifecycle semantics and historical coverage are validated.

Additional first-party BSE APIs discovered from the live pages:

- Bulk: `https://api.bseindia.com/BseIndiaAPI/api/BulkDeal_Beta/w`
- Block: `https://api.bseindia.com/BseIndiaAPI/api/BlockDeal_Beta/w`
- Insider: `https://api.bseindia.com/BseIndiaAPI/api/getCorp_Regulation_ng/w`

A new `scripts/bse_api_probe.py` now captures request headers and response bodies for these first-party APIs, so the next BSE run can establish the exact API contract and historical parameterization rather than relying on UI datepicker behaviour.

`bse_validate.py` was also hardened to flatten BSE's multiline/tab-separated Angular table representation and normalize B/S deal types to BUY/SELL while preserving raw native rows.

Current BSE status remains **BLOCKED / PENDING CERTIFICATION**.

## Category gates

| Exchange | Category | Status | Next gate |
|---|---|---|---|
| NSE | Insider | 🟡 Working / pending | Execute hardened 1D/7D/30D/90D + promoter semantics |
| NSE | Bulk | 🟡 Working / pending | Execute hardened 90D distinct-date audit |
| NSE | Block | 🟡 Working / pending | Execute hardened 90D distinct-date audit |
| NSE | Rights | 🔴 Not certified | Identify/populate underlying API/data |
| NSE | Preferential | 🔴 Not certified | Identify/populate underlying API/data |
| BSE | Insider | 🟡 Working / pending | API contract + historical parameter audit |
| BSE | Bulk | 🔴 Historical test failed | API parameterization + 90D date coverage |
| BSE | Block | 🔴 Historical test failed | API parameterization + 90D date coverage + dedup |
| BSE | Rights | 🟡 Index/detail acquisition working | Lifecycle API normalization + date coverage |
| BSE | Preferential | 🟡 Index/detail acquisition working | Lifecycle API normalization + date coverage |

## Promoter transaction rule

Promoter buying must be identified from source semantics, not merely `buyQuantity > 0`. Preserve person/category, acquisition/disposal, transaction date, disclosure/broadcast date, quantities, values and mode/type. Validate promoter/PAC classification independently for NSE and BSE.

## Deduplication rule

1. Deduplicate within NSE independently by category.
2. Deduplicate within BSE independently by category.
3. Cross-match NSE↔BSE only after both exchanges are certified.
4. Never automatically collapse NSE/BSE Bulk/Block executions because exchange-level execution is meaningful.
5. Insider disclosures require semantic matching before cross-exchange collapse.
6. Rights/Preferential lifecycle updates must not inflate underlying issue counts.

## Blocked downstream gates

- Cross-exchange matching: **BLOCKED** until NSE and BSE certification.
- R2 one-year backfill: **BLOCKED** and not started.
- Production schema freeze: **BLOCKED**.

## Execution dependency

The GitHub integration available to this engineering session exposes workflow inspection/reruns but not the Actions `workflow_dispatch` write operation. Therefore the hardened workflows/scripts are committed on `main`, but a fresh certification run cannot be dispatched from this session. The inspected BSE run above is explicitly not treated as certification.

## Mandatory engineering loop

**test → inspect real output → identify defect → fix → retest → verify → update documentation → continue**.

A green Actions run is execution evidence only. Certification requires actual records, native fields, dates, semantics, completeness and dedup evidence.