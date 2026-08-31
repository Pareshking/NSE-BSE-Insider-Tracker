# Validation Status — NSE + BSE

Last updated: 2026-09-01

## Operating rule

No one-year R2 backfill and no production-schema freeze until all pipeline validation gates are cleared and the user explicitly authorizes the next stage.

## Current execution order

NSE and BSE acquisition/validation are **strictly separate**. The earlier combined workflow is legacy/diagnostic only. The active pipeline may proceed exchange-by-exchange without allowing one broken category to stop usable categories.

NSE categories: **Insider Trading → Bulk Deals → Block Deals → Rights Issues → Preferential Issues → NSE certification**.
BSE categories: **Insider Trading → Bulk Deals → Block Deals → Rights Issues → Preferential Issues → BSE certification**.

For every category: preserve working acquisition, record unresolved defects as TODO, and continue to the next independent category when the current category's usable scope is validated. Do not declare full exchange certification until all required categories and date/completeness/dedup gates pass.

## Dedicated workflows

- `.github/workflows/nse-validation.yml` — NSE-only certification path.
- `.github/workflows/bse-validation.yml` — BSE-only certification path.
- `.github/workflows/data-validation.yml` — legacy combined diagnostic only; never certification.

## Date/completeness rule

Page count is never a completeness criterion. A one-day result is not historical certification. 90-day tests must inspect actual distinct source dates, earliest/latest dates, pagination termination, native fields and duplicate behaviour.

## Latest engineering changes — 2026-09-01

### NSE

1. **Insider hardening:** `scripts/nse_insider.py` now bootstraps the actual NSE Insider Trading page session before calling the PIT endpoint and records explicit 1D/7D/30D/90D evidence, status, native columns and distinct transaction dates. An empty JSON response now also triggers a CSV diagnostic request.
2. **Bulk/Block evidence:** both scripts now write per-window counts and distinct dates rather than only aggregate row counts. This makes nested-window duplication and historical coverage auditable.
3. **Rights/Preferential diagnostics:** both scripts now use browser-rendered diagnostics that capture populated tables, page text and NSE network/API requests for 1D/7D/30D/90D. They do not treat an empty JavaScript shell as success.
4. **Workflow evidence:** the dedicated NSE workflow continues through Rights/Preferential and uploads all NSE-specific evidence directories.

**Observed prior NSE evidence:** the last certified-path run returned 280 Bulk rows and 221 Block rows across four requested windows, but the artifact did not expose per-window distinct dates, so this is **not** historical certification. Insider returned HTTP 200 JSON with zero rows for all 1D/7D/30D/90D windows while the homepage returned 403; this is consistent with an NSE session/cookie problem and is now explicitly addressed by page-session bootstrap. Rights produced zero populated tables. Preferential failed because the old script waited for a table that never appeared.

Current NSE status remains **BLOCKED / PENDING CERTIFICATION** until new evidence is executed and inspected.

### BSE

1. **Historical capture hardening:** `scripts/bse_raw_capture_v2.py` now uses the requested `LOOKBACK_DAYS`/`TARGET_DATE`, attempts actual datepicker interaction, captures browser/network requests, preserves native controls and anchor attributes, and records detail-page evidence for Rights/Preferential.
2. **BSE-only validator added:** `scripts/bse_validate.py` performs BSE-only normalization, native-column checks, semantic checks, date extraction, intra-BSE duplicate counting and a separate detail-page gate for Rights/Preferential.
3. **Dedicated workflow hardened:** `.github/workflows/bse-validation.yml` now runs capture → BSE-only validation → separate evidence artifacts and has a 30-minute runtime bound. It does not invoke NSE acquisition.
4. **Important existing evidence:** BSE transaction capture is real, but the previous 90-day attempt was not historical certification because its date-range interaction did not demonstrate genuine 90-day variation. The new capture is instrumented to diagnose that defect rather than assume success.

Current BSE status remains **BLOCKED / PENDING CERTIFICATION** until the new evidence proves historical date coverage and all five categories pass.

## Category gates

| Exchange | Category | Status | Next gate |
|---|---|---|---|
| NSE | Insider | 🟡 Working / pending | Inspect 1D/7D/30D/90D real dates + promoter semantics |
| NSE | Bulk | 🟡 Working / pending | Inspect 90D distinct dates + completeness |
| NSE | Block | 🟡 Working / pending | Inspect 90D distinct dates + completeness |
| NSE | Rights | 🔴 Not certified | Identify/populate underlying API/data |
| NSE | Preferential | 🔴 Not certified | Identify/populate underlying API/data |
| BSE | Insider | 🟡 Working / pending | Validate datepicker result + native normalization |
| BSE | Bulk | 🟡 Working / pending | Prove 90D distinct dates |
| BSE | Block | 🟡 Working / pending | Prove 90D dates + deterministic dedup |
| BSE | Rights | 🔴 Not certified | Detail/lifecycle extraction |
| BSE | Preferential | 🔴 Not certified | Detail/lifecycle extraction |

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

The GitHub integration available to this engineering session exposes workflow inspection and reruns but does not expose the Actions `workflow_dispatch` write operation. The latest BSE-only diagnostic run (`33449251611`) is still executing its older acquisition code; it is not being treated as certification. The updated dedicated workflows are committed on `main` and require a fresh dispatch/push-triggered run before their new evidence can be inspected. This is an execution-tool limitation, not a data-certification pass.

## Mandatory engineering loop

**test → inspect real output → identify defect → fix → retest → verify → update documentation → continue**.

A green Actions run is execution evidence only. Certification requires actual records, native fields, dates, semantics, completeness and dedup evidence.