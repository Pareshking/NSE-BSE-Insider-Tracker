# BSE Validation Status

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

## Status
- BSE Insider: 🟡 working / historical certification pending
- BSE Bulk: 🔴 historical date-range defect pending first-party API integration validation
- BSE Block: 🔴 historical date-range + duplicate-key validation pending
- BSE Rights: 🟡 index/detail discovery working; lifecycle API validation pending
- BSE Preferential: 🟡 index/detail discovery working; lifecycle API validation pending
- BSE intra-source dedup: 🔴 pending category-level historical evidence
- BSE certification: 🔴 blocked

## Mandatory loop
**test -> inspect real output -> identify defect -> fix -> retest -> verify -> update documents -> continue**.

Do not begin cross-exchange matching or R2 backfill until BSE certification is independently green.
