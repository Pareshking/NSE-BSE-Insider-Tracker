# Validation Status — NSE + BSE

Last updated: 2026-09-01

## Operating rule
No one-year R2 backfill and no production-schema freeze until all validation gates are cleared and explicitly authorized.

## Exchange separation
NSE and BSE remain strictly separate. `.github/workflows/nse-validation.yml` and `.github/workflows/bse-validation.yml` are the certification paths. `data-validation.yml` is legacy diagnostic only.

## Latest loop work

### BSE first-party API integration
The following live BSE first-party services are now incorporated into the BSE evidence loop:
- `BulkDeal_Beta`
- `BlockDeal_Beta`
- `getCorp_Regulation_ng`
- `Pubissues_FurtherIssuesummary_RI_isd_ng`
- `Pubissues_FurtherIssuesummary_Pref_isd_ng`
- `Pubissues_FurtherXbrlview_pref_ng`

`scripts/bse_first_party_api_capture.py` records browser-observed request URL, method, headers, POST payload, response status, response body, JSON shape and samples. It is executed by both the dedicated BSE workflow and the BSE-only diagnostic trigger workflow.

### BSE validator hardening
`scripts/bse_validate.py` now:
- preserves native rows;
- flattens multiline/tab-separated Angular tables;
- uses deterministic intra-BSE keys;
- normalizes B/S to BUY/SELL while preserving raw values;
- treats a historical test as applied only when the requested date operation actually changes the returned table (`historical_test.status == changed`);
- does not certify Bulk/Block/Insider merely because multiple dates happen to exist in an unchanged default response;
- separately inspects Rights/Preferential detail rows rather than counting index rows as lifecycle evidence.

This prevents the previous false-green path where a populated current/default BSE table could satisfy an accidental `earliest < latest` condition.

## Existing real BSE evidence
Prior run `33449251611` exposed real data but remains diagnostic only:
- Insider: 158 rows, 20 distinct dates, 2026-02-26 through 2026-08-31; date control reported `no_change`.
- Bulk: 74 rows, all observed 2026-08-31; date control `no_change`.
- Block: 41 parsed rows, observed 2026-08-31; multiline rendering and duplicate execution keys require validation.
- Rights: 110 index rows; detail/lifecycle validation pending.
- Preferential: 530 index rows and 712 rendered detail rows across 20 detail pages; lifecycle semantics and historical coverage pending.

These observations are evidence for defect diagnosis, not certification.

## NSE status
NSE hardened scripts are committed and the dedicated workflow remains separate. Actual fresh execution of the hardened 1D/7D/30D/90D evidence is still required before certification.

## Current gates
| Exchange | Category | Status |
|---|---|---|
| NSE | Insider | 🟡 Working / fresh validation pending |
| NSE | Promoter semantics | 🟡 Pending fresh source evidence |
| NSE | Bulk | 🟡 Working / fresh 90D validation pending |
| NSE | Block | 🟡 Working / fresh 90D validation pending |
| NSE | Rights | 🔴 Not certified |
| NSE | Preferential | 🔴 Not certified |
| BSE | Insider | 🟡 Working / fresh API + historical validation pending |
| BSE | Promoter semantics | 🟡 Pending fresh source evidence |
| BSE | Bulk | 🔴 Historical gate previously failed; API rerun pending |
| BSE | Block | 🔴 Historical gate previously failed; API rerun pending |
| BSE | Rights | 🟡 Detail/API extraction working; lifecycle validation pending |
| BSE | Preferential | 🟡 Detail/API extraction working; lifecycle validation pending |
| Cross-exchange | Matching | 🔴 Blocked |
| R2 backfill | One-year | 🔴 Blocked |
| Production schema | Freeze | 🔴 Blocked |

## Execution state
A fresh push has been made to `main` after the BSE validator/API changes. GitHub Actions is currently queueing the repository's runs; the visible latest run is `33450145143` (`R2 Connectivity Test`) and is still queued. The GitHub integration available in this session does not expose the Actions `workflow_dispatch` write operation, so a direct exchange-specific dispatch cannot be forced from here.

The repository must not interpret a queued run, a green diagnostic run, or an artifact existence as certification. Fresh exchange-specific artifacts must be inspected before any gate is upgraded.

## Mandatory loop
**test → inspect real output → identify defect → fix → retest → verify → document → next category**.

R2 remains blocked and has not been started as a backfill.