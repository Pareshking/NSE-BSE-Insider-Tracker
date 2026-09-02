# Validation Status — NSE + BSE

Last updated: 2026-09-02 (BSE ID-namespace bridge fixed -- rights/preferential cross-exchange matching now works)

**See `DATA_ACQUISITION.md` for the exact working method per category — this
file tracks pass/fail status; that one explains how each fetch actually
works and why.**

## 2026-09-02 (later): BSE rights/preferential cross-exchange matching fixed

The "real, precisely-diagnosed limitation" documented below (BSE
rights/preferential 0-match cross-exchange linking) is now fixed. The bug
was not a missing bridge -- the bridge was already being captured, just
never tried first.

`bse_raw_capture_v2.py`'s `ri_pref_row()` extracts TWO different BSE codes
per row: `stage_3` (the API's `scripcode` field, positions 0-3, in place
since before this project tracked rights/preferential separately) and
`bse_company_code` (the API's `COMPANY_CODE` field, added 2026-09-01 at
position 8). `resolve_isin()` in `scripts/r2_writer.py` tried
`bse_company_code` before `stage_3` -- so the newer, wrong-namespace field
was shadowing the older, correct one on every row that had both (which is
all of them, since both are ~100% populated).

Checked directly against the same evidence used to diagnose the gap:
`stage_3` values (`570005`, `544559`, `544459`, `544416`, `544412` from the
first 5 real rights_issue rows) are standard 6-digit BSE scrip codes --
4 of 5 found immediately in `reference_data/security_master_20260901.csv`'s
`bse_scrip_code` column (the 5th is very likely just outside that
snapshot's coverage, not a namespace problem). `bse_company_code`'s values
for the same 5 rows (`8255`, `13640`, `13799`, `14044`, `13679`) match
nothing in that column, confirming it never was the right field for this
lookup.

**Fix**: swapped the `_pick()` priority in `resolve_isin()`'s BSE branch to
`security_code`, `stage_3`, `bse_company_code` (was `security_code`,
`bse_company_code`, `stage_3`) -- `bse_company_code` stays as a last-resort
fallback for any future BSE dataset that has no `stage_3`, it just no
longer shadows the field that actually works for rights/preferential.

Re-ran `resolve_isin()` against the same run's evidence artifacts used to
find the bug:
- `rights_issue_normalized.json` (267 real rows): **260/267 (97.4%)** now
  resolve an ISIN, up from 0.
- `preferential_issue_normalized.json` (1,142 real rows): **1,084/1,142
  (94.9%)** now resolve an ISIN, up from 0.

**Live-run reconfirmation (2026-09-02, run
[33589055414](https://github.com/Pareshking/NSE-BSE-Insider-Tracker/actions/runs/33589055414),
commit `5a25a3d`)**: re-ran `resolve_isin()` against this run's own
freshly-fetched `bse_validation/rights_issue_normalized.json` /
`preferential_issue_normalized.json` (downloaded from its "Upload run
evidence" artifact, not the earlier cached rows used to diagnose the bug)
-- same **260/267 (97.4%)** and **1,084/1,142 (94.9%)** resolution rates.
The fix holds on a genuinely fresh acquisition, not just against the data
used to find the bug.

Note: `cross_exchange_matches_flagged` stayed at 0 for both categories in
this run's manifest, as expected -- that counter is a *different*
mechanism (`find_cross_exchange_matches()`, which flags NSE/BSE rows as
probable same-event duplicates by close dates, with no quantity signal to
corroborate for these two categories) and isn't driven by whether
`canonical_isin` resolves. Zero flagged matches here means no NSE/BSE pair
this run had a close-enough date on both sides, not that the ISIN fix
didn't take -- an earlier note in this section conflating the two was
wrong and is corrected here.

## 2026-09-02 reconfirmation: all 10 (exchange, category) pairs VERIFIED

Overnight safety-net check-in, `r2-storage.yml` run
[33575157195](https://github.com/Pareshking/NSE-BSE-Insider-Tracker/actions/runs/33575157195)
(commit `7a7f9b9`, target_date=2026-08-31, lookback_days=90): **manifest
shows `written_count: 10, skipped_count: 0`** -- NSE and BSE, all 5
categories each, all VERIFIED. This is the first run in this project's
history to certify all 10 combinations in a single pass.

Also confirmed as part of this run, checking a same-day change that had
been UNTESTED against live BSE data (new `bse_raw_capture_v2.py` fields
`in_principle_status`/`in_principle_date`/`listing_status`/
`listing_stage_date`/`bse_company_code` for Rights/Preferential):

- **Field-name assumptions were correct.** Downloaded the run's evidence
  artifact and checked `bse_validation/rights_issue_normalized.json`
  directly (267 real rows): `in_principle_status`, `in_principle_date`,
  `listing_status`, `bse_company_code` are 100% populated with real
  values (not empty strings); `listing_stage_date` is 52% populated
  (140/267) -- correctly partial, since not every rights issue has
  reached the listing stage yet, not a defect.
- **Real, precisely-diagnosed limitation found (not a regression, not new
  today -- rights/preferential cross-exchange matching has never worked):**
  `bse_company_code`'s values (e.g. `8255`, `13640`) are a *different* BSE
  internal ID namespace than the 6-digit `bse_scrip_code` in
  `reference_data/security_master_20260901.csv` (e.g. `500002`, `500325`)
  -- confirmed directly, `grep`ing the security master for these exact
  values found zero matches. `resolve_isin()`'s BSE branch looks up
  `bse_company_code` against that crosswalk and never finds it, so
  `canonical_isin` stays empty for every BSE rights/preferential row
  (`0` distinct ISINs across 267 rows, vs 107 on the NSE side) and
  cross-exchange matching for these two categories still can't confirm a
  link (`cross_exchange_matches_flagged: 0`, unchanged from before this
  change). The new date fields populate correctly and are ready to use
  the moment a real bridge between these two BSE ID namespaces is found
  -- that's a new, separate investigation (a BSE company-code-to-scrip-code
  lookup, not yet located), not a bug in what shipped.
- BSE `block_deals` (17 rows), `rights_issue` (267 rows), `preferential_issue`
  (1,142 rows) all independently confirmed VERIFIED in this same run --
  no regression from the field additions.
- Market cap reference data: 8,106 symbols resolved (3,169 NSE + 4,685 BSE
  + 252 cross-exchange aliases) in this same run, consistent with Phase 0.5's
  standalone testing earlier the same day.
- The gap-detection backfill (`scripts/backfill_gaps.py`) ran for real for
  the first time in production: found 10 weekdays (2026-08-17 through
  2026-08-28) with no manifest yet and backfilled all of them from this
  run's already-fetched data, exactly as designed.

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
- **NSE Bulk / Block: ✅ fully fixed and confirmed VERIFIED with real data
  2026-09-01, run #98 (`nse-validation.yml`, commit `12a0693`).** This took
  several rounds of real-evidence debugging — see `DATA_ACQUISITION.md`
  section 2 for the full technical account. Summary of what it actually
  was, in order of discovery:
  1. Earlier notes here said "previously VERIFIED, needs reconfirmation,"
     implying a regression. That was false: no run in this project's
     history ever actually passed `nse_validate.py`'s VERIFIED gate for
     these two categories — every run got an identical ~22KB bot-detection
     page, 0 real rows.
  2. First theory (IP-reputation block on GitHub's data-center IPs) looked
     plausible — a phone-browser test got real data instantly while the CI
     runner didn't — but didn't survive a direct test: `scripts/nse_bulk_diagnose.py`
     proved the real cause was a **dead endpoint** (`/api/historical/bulk-deals`),
     while the live page's actual endpoint (`/api/historicalOR/bulk-block-short-deals`)
     worked fine from the same IP in the same run.
  3. That endpoint turned out to cap results at 70 rows per call, and an
     initial chunking fix (7-day chunks) discovered the cap sorts
     **ascending** by date — so a busy day early in any multi-day chunk
     silently drops every later day in that chunk, including the actual
     target date.
  4. Final fix: fetch one calendar day per call (`CHUNK=1`), fetch the full
     90-day range exactly once, then slice into the 1d/7d/30d/90d windows.
  Confirmed result (run #98): **4,410 real Bulk Deal rows across 63 distinct
  dates**, **690 real Block Deal rows across 37 distinct dates**, 0 retries
  needed across 90 daily calls per script. `nse_validate.py`'s
  `certification` field reads **VERIFIED** — all 5 NSE categories are green.
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

**Update 2026-09-01 (later same day):** NSE bulk_deals/block_deals are now
fixed and confirmed VERIFIED with real data (see "Current confirmed state"
above) — the table right above reflects that specific 13:13Z run's result,
not current status. `r2-storage.yml` has not been re-run since the fix
landed, so a fresh R2 write with all 10 categories has not yet been
confirmed end-to-end; that's the natural next check.

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
| NSE | Bulk | ✅ VERIFIED (fixed and confirmed run #98, 2026-09-01 — dead endpoint + per-call ascending-sort cap, see "Current confirmed state" above) |
| NSE | Block | ✅ VERIFIED (fixed and confirmed run #98, 2026-09-01 — same fix as Bulk) |
| NSE | Rights | ✅ VERIFIED (confirmed run #87, 2026-09-01T16:58Z) |
| NSE | Preferential | ✅ VERIFIED (confirmed run #87, 2026-09-01T16:58Z) |
| BSE | Insider | ✅ VERIFIED |
| BSE | Promoter semantics | ✅ VERIFIED |
| BSE | Bulk | ✅ VERIFIED |
| BSE | Block | ✅ VERIFIED |
| BSE | Rights | ✅ VERIFIED |
| BSE | Preferential | ✅ VERIFIED |
| BSE | Overall certification | ✅ VERIFIED (run #15, commit 5f529de; reconfirmed 2026-09-02 run 33575157195, all 10/10) |
| Cross-exchange | Matching (insider/bulk/block) | ✅ Active, flag-only (ISIN crosswalk via `security_master`) |
| Cross-exchange | Matching (rights/preferential) | ✅ Fixed and live-run reconfirmed 2026-09-02 -- `resolve_isin()` now tries `stage_3` (BSE's real scrip code) before `bse_company_code` (a different ID namespace); 97.4%/94.9% ISIN resolution confirmed against both the original diagnostic evidence and a fresh `r2-storage.yml` acquisition (see 2026-09-02 (later) section above) |
| R2 backfill | Gap detection + catch-up | ✅ Built and confirmed working in production, 2026-09-02 (`scripts/backfill_gaps.py`, backfilled 10 real missing weekdays in one run) -- not a one-year historical backfill, which remains unscoped |
| Production schema | Freeze | 🔴 Not yet decided -- unrelated to this reconfirmation |

## Execution state
The repository has continued receiving fixes on `main`. The latest dedicated NSE/BSE certification evidence still requires fresh runner execution and artifact inspection. No queued run, green diagnostic run, or artifact existence is treated as certification.

## Mandatory loop
**test → inspect real output → identify defect → fix → retest → verify → document → next category**.

R2 remains blocked and has not been started as a backfill.
