# Validation Status — NSE + BSE

Last updated: 2026-09-01 (post-XBRL-rewrite)

**See `DATA_ACQUISITION.md` for the exact working method per category — this
file tracks pass/fail status; that one explains how each fetch actually
works and why.**

## Current confirmed state

- **BSE: ✅ VERIFIED — all 5 categories.** Confirmed by a fresh, isolated
  `BSE Only 90-Day Validation` run (run #15, commit `5f529de`,
  2026-09-01): every dataset status and the top-level `certification` field
  read VERIFIED.
- **NSE Insider Trading: ✅ fixed.** The root cause was calling a dead
  endpoint (`/api/corporates-pit`, always empty) instead of the real one
  (`/api/corporates-pit-gg`), and the real transaction data (person,
  category, quantities) living in each filing's linked XBRL XML rather than
  the list response. Rewritten in `scripts/nse_insider.py`; confirmed
  `promoter_semantics: VERIFIED` in two consecutive live runs (1638 and 224
  promoter-category rows respectively, well above the `>0` gate).
- **NSE Rights / Preferential: ✅ confirmed VERIFIED** in a fresh run
  (`nse-validation.yml` run #87, 2026-09-01T16:58Z, commit `c8f2d9f`) —
  recovered fully from the earlier Akamai escalation.
- **NSE Bulk / Block: CORRECTION — no evidence this has ever actually been
  VERIFIED with real data in this project.** Earlier notes here described
  this as "previously VERIFIED, needs a clean reconfirmation run," implying
  a regression from working code. That was checked against the actual
  evidence on 2026-09-01 and does not hold up: three separate runs spanning
  the full day — `2f92237` (05:52 UTC), `973ce485` (06:52 UTC), and `c8f2d9f`
  (16:58 UTC, run #87) — all got the **identical** ~22,085–22,087-byte
  non-JSON bot-detection page across all 4 windows (1d/7d/30d/90d), 0 real
  rows every time, regardless of script version or retry logic. Real data
  would vary in size by date range; an identical byte count every time
  means it's the same static page, not a data question. No run in this
  project's history (checked from the earliest recorded run onward) shows
  `nse_bulk`/`nse_block` actually passing `nse_validate.py`'s VERIFIED gate
  (which strictly requires real captured rows — see `scripts/nse_validate.py`
  lines 14-16 — so there's no looser historical definition this could be
  hiding behind either).
  **2026-09-01 17:16 IST — user confirmed via phone browser that NSE's own
  Bulk Deals page loads real 31-Aug-2026 data instantly from an ordinary
  mobile connection.** This rules out "no data" or "site down," and points
  at IP-reputation blocking of GitHub Actions' data-center IP ranges
  specifically for this endpoint (Insider/Rights/Preferential aren't
  affected from the same IPs, so it's endpoint-specific, not domain-wide) —
  and consistent with it never having worked from a GitHub-hosted runner in
  the first place, not something that broke.
  **Revised expectation: a cooldown period may not be sufficient on its
  own** the way it was for Rights/Preferential — if this is IP-based rather
  than request-cadence-based, the block may persist indefinitely from
  GitHub-hosted runners. Decision (2026-09-01): keep the existing
  scheduled-retry approach for now rather than standing up a self-hosted
  runner or a manual CSV fallback; revisit if retries keep failing over
  multiple days.
- **Operational lesson:** don't fire `nse-validation.yml` repeatedly within
  a short window while iterating — space test runs out (10+ minutes) to
  avoid tripping Akamai's edge rate limiter across the whole domain.

## Phase 4 (R2 storage): first live run confirmed working

`r2-storage.yml` was merged to `main` and run for real
(run #1, `33511424713`, 2026-09-01T13:13Z) against the live R2 bucket.
`scripts/r2_writer.py` itself has **zero bugs** — every VERIFIED dataset
wrote a real raw JSON object + Parquet file with a real SHA256 confirmed in
the manifest, and every non-VERIFIED dataset was correctly skipped with a
reason, never written as empty:

| Exchange | Category | Result |
|---|---|---|
| NSE | insider_trading | ✅ written (465 rows) |
| NSE | rights_issue | ✅ written (200 rows) — recovered from Akamai already |
| NSE | preferential_issue | ✅ written (200 rows) — recovered from Akamai already |
| NSE | bulk_deals | 🔴 skipped — still Akamai-BLOCKED |
| NSE | block_deals | 🔴 skipped — still Akamai-BLOCKED |
| BSE | bulk_deals | ✅ written (59 rows) |
| BSE | block_deals | ✅ written (17 rows) |
| BSE | rights_issue | ✅ written (267 rows) |
| BSE | insider_trading | 🔴 skipped — BLOCKED this run (was VERIFIED 20 min earlier in the standalone BSE run; BSE's CDP capture is timing-sensitive, this reads as normal day-to-day flakiness, not a regression) |
| BSE | preferential_issue | 🔴 skipped — BLOCKED this run (same as above) |

6/10 datasets written this run. NSE rights/preferential already recovered
from the earlier Akamai block on their own — only the bulk/block-deals
endpoints specifically are still cooling down.

## Operating rule
No one-year R2 backfill and no production-schema freeze until all validation gates are cleared and explicitly authorized.

## Exchange separation
NSE and BSE remain strictly separate. `.github/workflows/nse-validation.yml` and `.github/workflows/bse-validation.yml` are the certification paths. `data-validation.yml` is legacy diagnostic only.

## Frontend product direction
A production frontend specification is documented in `FRONTEND_PRODUCT_SPEC.md`. The website is required to be a world-class quantitative research interface, not a raw scraper-output viewer. The planned flow is:

**Overview → Insider → Bulk → Block → Rights → Preferential → Data Quality/Validation → evidence drill-down**

The frontend must expose source provenance, extraction time, requested versus actual date coverage, certification state, native exchange fields, transaction semantics, lifecycle status and duplicate/match status. NSE and BSE remain visually separated until cross-exchange matching is independently certified. The UI must never manufacture a green/trusted state from workflow success alone.

### Visual reference concepts
Two frontend visual concept references are now stored in `docs/frontend-concepts/`:

- `frontend-concept-a.svg` — conservative institutional research-terminal direction with dominant research table, provenance, coverage and evidence panels.
- `frontend-concept-b.svg` — analytics-heavy terminal direction with persistent search, category tabs, top-company analytics and validation/evidence center.

The recommended direction is **Concept B as the starting visual benchmark combined with Concept A's stronger provenance/evidence treatment**. These are design references only; their illustrative KPI values/statuses must never be copied into production as factual data.

Frontend acceptance includes responsive/mobile research UX, dense but readable tables, sticky headers, filtering/search, exports, row-level evidence, loading/error/empty states, accessibility, performance targets and explicit warnings for incomplete/uncertified data.

## Latest engineering loop

### NSE fixes
The prior dedicated NSE artifact was inspected at record level. It exposed three concrete defects:
1. Insider PIT responses could contain non-JSON framing bytes and the parser converted all 1D/7D/30D/90D windows to zero rows.
2. The `nse.bulkdeals()` helper returned a single anchor date for multi-day requests in the observed run, so helper success was not accepted as historical coverage.
3. Rights/Preferential browser tables were populated but the real first-party APIs were not being consumed as the authoritative data layer.

Fixes now on `main`:
- Insider parser strips only non-JSON framing and preserves native PIT rows/columns.
- Bulk and Block use NSE's first-party historical endpoints `/api/historical/bulk-deals` and `/api/historical/block-deals` with explicit `from`/`to` dates instead of relying solely on the helper's range behaviour.
- Rights uses `corporate-further-issues-ri?index=FIRIIP` and `FIRILS`.
- Preferential uses `corporate-further-issues-pref?index=FIPREFIP` and `FIPREFLS`.
- Dedicated NSE workflow now marks every category `if: always()` so one failure cannot suppress subsequent categories.
- `scripts/nse_validate.py` now produces an evidence certification report and explicitly tests promoter-category transaction semantics from real insider rows.

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
| NSE | Insider | ✅ VERIFIED (corporates-pit-gg + XBRL rewrite) |
| NSE | Promoter semantics | ✅ VERIFIED (confirmed 2 consecutive runs) |
| NSE | Bulk | 🔴 BLOCKED — no confirmed successful run found in this project's history (see "Current confirmed state" above); likely IP-reputation block on GitHub-hosted runners, not a cooldown issue |
| NSE | Block | 🔴 BLOCKED — same as Bulk above |
| NSE | Rights | ✅ VERIFIED (confirmed run #87, 2026-09-01T16:58Z) |
| NSE | Preferential | ✅ VERIFIED (confirmed run #87, 2026-09-01T16:58Z) |
| BSE | Insider | ✅ VERIFIED |
| BSE | Promoter semantics | ✅ VERIFIED |
| BSE | Bulk | ✅ VERIFIED |
| BSE | Block | ✅ VERIFIED |
| BSE | Rights | ✅ VERIFIED |
| BSE | Preferential | ✅ VERIFIED |
| BSE | Overall certification | ✅ VERIFIED (run #15, commit 5f529de) |
| Cross-exchange | Matching | 🔴 Blocked until NSE overall certification is reconfirmed green |
| R2 backfill | One-year | 🔴 Blocked |
| Production schema | Freeze | 🔴 Blocked |

## Execution state
The repository has continued receiving fixes on `main`. The latest dedicated NSE/BSE certification evidence still requires fresh runner execution and artifact inspection. No queued run, green diagnostic run, or artifact existence is treated as certification.

## Mandatory loop
**test → inspect real output → identify defect → fix → retest → verify → document → next category**.

R2 remains blocked and has not been started as a backfill.
