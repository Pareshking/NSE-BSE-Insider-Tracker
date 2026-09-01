# Validation Status — NSE + BSE

Last updated: 2026-09-01

## Operating rule
No one-year R2 backfill and no production-schema freeze until all validation gates are cleared and explicitly authorized.

## Exchange separation
NSE and BSE remain strictly separate. `.github/workflows/nse-validation.yml` and `.github/workflows/bse-validation.yml` are the certification paths. `data-validation.yml` is legacy diagnostic only.

## Latest engineering loop

### NSE fixes
The prior dedicated NSE artifact was inspected at record level. It exposed three concrete defects:
1. Insider PIT responses could contain non-JSON framing bytes and the parser converted all 1D/7D/30D/90D windows to zero rows.
2. The `nse.bulkdeals()` helper returned a single anchor date for multi-day requests in the observed run, so page/helper success was not accepted as historical coverage.
3. Rights/Preferential browser tables were populated but the real first-party APIs were not being consumed as the authoritative data layer.

Fixes now on `main`:
- Insider parser strips only non-JSON framing and preserves native PIT rows/columns.
- Bulk and Block use NSE's first-party historical endpoints `/api/historical/bulk-deals` and `/api/historical/block-deals` with explicit `from`/`to` dates instead of relying solely on the helper's range behaviour.
- Rights uses `corporate-further-issues-ri?index=FIRIIP` and `FIRILS`.
- Preferential uses `corporate-further-issues-pref?index=FIPREFIP` and `FIPREFLS`.
- Dedicated NSE workflow now marks every category `if: always()` so one failure cannot suppress subsequent categories.
- `scripts/nse_validate.py` now produces an evidence certification report and explicitly tests promoter-category transaction semantics from real insider rows.

The official NSE Rights and Preferential pages expose the lifecycle fields required by this project, including Rights record date/ratio/offer price/open-close/allotment/amount/listing/trading approval/submission and Preferential board resolution/allottee/consideration/offer price/allotment/shares/amount/listing/trading approval/lock-in fields. citeturn0search5turn0search1

### BSE first-party API integration
The following first-party services are incorporated into the BSE evidence loop:
- `BulkDeal_Beta`
- `BlockDeal_Beta`
- `getCorp_Regulation_ng`
- `Pubissues_FurtherIssuesummary_RI_isd_ng`
- `Pubissues_FurtherIssuesummary_Pref_isd_ng`
- `Pubissues_FurtherXbrlview_pref_ng`

`scripts/bse_first_party_api_capture.py` records browser-observed request URL, method, headers, POST payload, response status/body, JSON shape and samples.

### BSE validator fixes
The validator now:
- preserves native rows;
- expands multiline/tab-separated Angular tables;
- uses deterministic intra-BSE keys;
- normalizes B/S to BUY/SELL while preserving raw values;
- correctly maps BSE Insider native positions, including person category, transaction type, transaction date, mode, buy value, sell value and broadcast date;
- explicitly recognizes Promoter, Promoter Group and related promoter categories instead of treating any positive quantity as promoter buying;
- requires an actual historical-control change for Bulk/Block/Insider certification;
- treats Rights/Preferential detail rows as lifecycle evidence rather than counting index rows alone.

## Real evidence inspected
Prior BSE run `33449251611` remains diagnostic only:
- Insider: 158 raw rows; 154 structurally eligible rows; categories include Promoter Group, Promoter and Promoter & Director; 83 Acquisition and 66 Disposal rows.
- Bulk: 74 rows, all observed on 2026-08-31; date control `no_change`.
- Block: multiline rendering expanded to 59 physical rows but only 17 meaningful unique execution rows after header/render duplication; all observed on 2026-08-31.
- Rights: 110 index rows; underlying detail extraction still pending.
- Preferential: 530 index rows and 712 rendered detail rows across 20 detail pages; actual lifecycle fields are present in the detail pages, but historical control/API completeness is still pending.

These are defect-diagnosis observations, not certification.

## Current gates
| Exchange | Category | Status |
|---|---|---|
| NSE | Insider | 🟡 Working / fresh execution pending |
| NSE | Promoter semantics | 🟡 Logic implemented / fresh execution pending |
| NSE | Bulk | 🟡 Direct historical API implemented / fresh execution pending |
| NSE | Block | 🟡 Direct historical API implemented / fresh execution pending |
| NSE | Rights | 🟡 First-party APIs implemented / fresh execution pending |
| NSE | Preferential | 🟡 First-party APIs implemented / fresh execution pending |
| BSE | Insider | 🟡 Native mapping fixed / fresh API + historical execution pending |
| BSE | Promoter semantics | 🟡 Native category logic fixed / fresh execution pending |
| BSE | Bulk | 🔴 Historical gate failed in prior run / fresh API execution pending |
| BSE | Block | 🔴 Historical gate failed in prior run / fresh API execution pending |
| BSE | Rights | 🟡 Detail/API path identified / lifecycle validation pending |
| BSE | Preferential | 🟡 Detail extraction works / lifecycle + historical validation pending |
| Cross-exchange | Matching | 🔴 Blocked until both exchanges certify |
| R2 backfill | One-year | 🔴 Blocked |
| Production schema | Freeze | 🔴 Blocked |

## Execution state
The repository has continued receiving fixes on `main`. The latest dedicated NSE/BSE certification evidence still requires fresh runner execution and artifact inspection. No queued run, green diagnostic run, or artifact existence is treated as certification.

## Mandatory loop
**test → inspect real output → identify defect → fix → retest → verify → document → next category**.

R2 remains blocked and has not been started as a backfill.