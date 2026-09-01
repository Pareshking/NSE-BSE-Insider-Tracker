# BSE Validation Status

**BSE certification: ✅ VERIFIED (all 5 categories) — confirmed 2026-09-01.**

See `DATA_ACQUISITION.md` for the exact working method (CDP capture of BSE's
own Angular XHR traffic against `api.bseindia.com`). This file below
retains the investigation history; the "Current gate"/"Status" sections at
the bottom are superseded by the summary above.

## Active rule
BSE validation is independent of NSE. The legacy combined workflow is diagnostic only.

## First-party API integration
The live BSE pages exposed these first-party services and they are now wired into the dedicated BSE validation workflow as live browser/network contract evidence:

- `BulkDeal_Beta` -> Bulk
- `BlockDeal_Beta` -> Block
- `getCorp_Regulation_ng` -> Insider / corporate regulation
- `Pubissues_FurtherIssuesummary_RI_isd_ng` -> Rights
- `Pubissues_FurtherIssuesummary_Pref_isd_ng` -> Preferential
- `Pubissues_FurtherXbrlview_pref_ng` -> Preferential XBRL/detail lifecycle

Implementation: `scripts/bse_first_party_api_capture.py` captures the actual request URL, method, headers, POST payload, HTTP status, response body, JSON shape and known-service classification from the live BSE pages. The workflow archives this separately as `bse-api-contract-v2` evidence. This is not certified merely because the API returns HTTP 200.

## Current gate
A 90-day BSE run must prove, independently for Insider, Bulk, Block, Rights and Preferential:
- real populated records
- native source fields preserved
- requested date range actually affects acquisition
- multiple distinct transaction/event dates where expected
- pagination/continuation behaviour
- duplicate behaviour and deterministic intra-BSE keys
- correct BUY/SELL and acquisition/disposal semantics
- Rights/Preferential detail/lifecycle records rather than index rows alone

## Evidence already observed
Prior live runs established that Insider contained multiple historical dates, while Bulk/Block were effectively current-day in the tested window. Rights and Preferential index discovery worked and detail pages/API contracts were observable. Those results remain evidence, not certification.

## Status (superseded — see top of file)
- BSE Insider: ✅ VERIFIED — `scripts/bse_raw_capture_v2.py` (CDP capture)
- BSE Bulk: ✅ VERIFIED
- BSE Block: ✅ VERIFIED
- BSE Rights: ✅ VERIFIED
- BSE Preferential: ✅ VERIFIED
- BSE intra-source dedup: ✅ VERIFIED
- BSE certification: ✅ **VERIFIED** (`scripts/bse_validate.py` top-level `certification` field)

Confirmed by a fresh `BSE Only 90-Day Validation` workflow run
(run #15, commit `5f529de`) on 2026-09-01: all 5 dataset statuses and the
overall certification report as VERIFIED.

## Mandatory loop
**test -> inspect real output -> identify defect -> fix -> retest -> verify -> update documents -> continue**.

BSE certification is independently green. Cross-exchange matching / R2
backfill are still gated on NSE certification (see `VALIDATION_STATUS.md`).
