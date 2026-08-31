# NSE-BSE Insider Tracker — Project Plan & Task Tracker

> Single source of truth for project scope, engineering decisions, validation status, and remaining work.
>
> **Status:** Phase 1A + 1B + Phase 2 acquisition validation in progress.
> **Target validation date:** 2026-08-31.

## 1. Mission

Build a reliable, low-cost NSE + BSE market-disclosure data system with:

- Official NSE and BSE data wherever practical.
- Reliable fallback acquisition methods when exchanges block automated clients.
- At least one year of historical data, with room to retain more when inexpensive.
- Correct handling of BUY and SELL insider transactions.
- Correct distinction between filings, transactions, allotments, listings, and market-deal events.
- Deduplication without losing source provenance.
- Compact storage in Cloudflare R2 rather than using GitHub as the primary data store.
- GitHub Actions for scheduled acquisition/validation.
- Streamlit as the user-facing application.
- Auditable raw/source references so important records can be verified against NSE/BSE.

## 2. Data domains

### A. Insider trading — Phase 1A
- [ ] NSE Regulation 7(2), Equity
- [ ] NSE SME / REIT / InvIT where applicable
- [ ] BSE Regulation 7(2) / equivalent insider disclosures
- [ ] BUY transactions
- [ ] SELL transactions
- [ ] Other relevant transaction types
- [ ] Filing date vs transaction date
- [ ] Promoter / director / designated-person / connected-person classification
- [ ] Exchange of execution
- [ ] Source document / XBRL / filing reference
- [ ] Duplicate and amendment handling

### B. Market deals — Phase 2
- [x] NSE Bulk Deals acquisition path demonstrated
- [x] NSE Block Deals acquisition path demonstrated
- [ ] BSE Bulk Deals reliable acquisition path
- [ ] BSE Block Deals reliable acquisition path
- [ ] Validate quantities, prices, client names, symbols and dates
- [ ] Determine reliable historical retrieval method
- [ ] Define how repeated/amended records are identified

**Important:** Bulk/block deals are market-disclosure datasets, not insider transactions. They must remain separate in storage and analytics.

### C. Further issues — Phase 1B
- [ ] NSE Preferential Issue — proposed / in-principle
- [ ] NSE Preferential Issue — post-allotment
- [ ] NSE allotment/listing/trading-approval fields
- [ ] NSE Rights Issue
- [ ] BSE Preferential Issue announcements
- [ ] BSE Preferential allotment/listing notices
- [ ] BSE Rights Issue / public-issue data
- [ ] Separate issue lifecycle events: announcement → approval → allotment → listing → trading commencement
- [ ] Avoid counting multiple lifecycle disclosures as multiple issues

### D. Future candidate datasets
- [ ] Bonus issues
- [ ] Buybacks
- [ ] Mergers / demergers / corporate actions if useful
- [ ] Delivery / institutional indicators only after source quality is established

These are deliberately out of the current acquisition-validation scope unless evidence shows they materially improve the tracker.

## 3. Phase 1A — Insider acquisition validation

### Test strategy
Test multiple acquisition paths from GitHub Actions against 2026-08-31:

1. Official NSE endpoint/API.
2. Maintained NSE Python libraries/session methods.
3. Direct official archive/XBRL/CSV paths.
4. Browser/session fallback if required.
5. Official BSE endpoint/page/API.
6. Maintained BSE wrappers.
7. Direct requests/session fallback.

For every method record:

- HTTP/result status
- record count
- fields returned
- BUY count
- SELL count
- date correctness
- source/reference availability
- repeatability
- rate-limit/block behaviour
- GitHub Actions compatibility

### Acceptance criteria
- [ ] At least one reliable NSE acquisition method.
- [ ] At least one reliable BSE acquisition method.
- [ ] BUY and SELL records verified.
- [ ] Results cross-checked against official exchange material.
- [ ] Failure mode is known and logged when a route is blocked.
- [ ] Method can run unattended from GitHub Actions.

## 4. Phase 1B — Further issue acquisition validation

Test NSE and BSE Rights + Preferential issue data using official pages/endpoints first, then maintained wrappers/fallbacks.

Acceptance criteria:

- [ ] NSE preferential data returned and fields validated.
- [ ] NSE rights data returned and fields validated.
- [ ] BSE preferential data returned and fields validated.
- [ ] BSE rights data returned and fields validated.
- [ ] Proposed issue and actual allotment are distinguishable.
- [ ] Listing/trading commencement events are distinguishable.
- [ ] Source references retained.

## 5. Phase 2 — Bulk/block validation

### NSE
- [x] Bulk acquisition works in GitHub Actions.
- [x] Block acquisition works in GitHub Actions.
- [ ] Validate returned records against official NSE output.
- [ ] Test historical retrieval.

### BSE
- [ ] Find working official endpoint/page.
- [ ] Test direct session method.
- [ ] Test wrapper(s).
- [ ] Verify actual records rather than HTTP 200 alone.
- [ ] Validate historical retrieval.

### Analytical boundary
Do not label bulk/block participants as insiders unless an independent insider disclosure establishes that fact.

## 6. Acquisition architecture

Planned production flow:

```text
NSE/BSE official sources
        │
        ├── primary method
        ├── library/session fallback
        └── browser/direct fallback where justified
                 │
                 ▼
          validation + normalization
                 │
                 ├── raw/source snapshot
                 ├── canonical records
                 └── acquisition audit log
                 │
                 ▼
             Cloudflare R2
                 │
                 ▼
             Streamlit app
```

GitHub is the **code/workflow layer**, not the long-term data warehouse.

## 7. Storage design — after acquisition is proven

### Principles
- Store compact columnar data (Parquet preferred) in R2.
- Partition by source/domain/year/month as appropriate.
- Compress files.
- Do not repeatedly store identical raw payloads.
- Keep canonical records separate from raw source snapshots.
- Preserve source URL/document identifiers and retrieval timestamps.
- Use deterministic record/event IDs for deduplication.
- Keep amendments/corrections rather than silently overwriting history.
- Maintain an acquisition manifest so missing days can be detected.

### Retention
- [ ] Minimum one-year historical coverage.
- [ ] Backfill strategy defined.
- [ ] Daily incremental update strategy.
- [ ] Reconciliation/retry strategy for failed days.
- [ ] Storage-size benchmark after one-year sample.

## 8. Data model — planned

Separate these concepts:

### Filing
A disclosure/publication received from NSE/BSE.

### Transaction
An underlying insider BUY/SELL transaction or other disclosed transaction.

### Market deal
A bulk/block deal disclosure.

### Issue
A rights/preferential issue and its lifecycle.

### Issue event
Announcement, approval, allotment, listing approval, trading commencement, etc.

This distinction prevents one disclosure or lifecycle from being incorrectly counted multiple times.

## 9. Deduplication requirements

- [ ] Define stable source-specific IDs where available.
- [ ] Define deterministic fallback IDs when source IDs are absent.
- [ ] Include exchange/source in identity.
- [ ] Include filing/document identifiers.
- [ ] Include transaction date and participant/security attributes where needed.
- [ ] Handle amended/re-filed disclosures explicitly.
- [ ] Never deduplicate solely on company + date + BUY/SELL.
- [ ] Test duplicate cases from both exchanges.

## 10. BUY / SELL tracking

The final system must support:

- individual transaction history
- daily BUY value/quantity
- daily SELL value/quantity
- net BUY/SELL activity
- rolling 7/30/90/365-day totals
- promoter/insider-level history where disclosed
- company-level aggregation
- separate NSE and BSE execution attribution
- drill-down to source disclosure

Do not infer a SELL merely because holdings decreased. Use disclosed transaction/action fields.

## 11. Data quality controls

Every production run should check:

- [ ] expected trading/disclosure date
- [ ] source response received
- [ ] record count anomaly
- [ ] schema drift
- [ ] duplicate rate
- [ ] missing critical fields
- [ ] BUY/SELL distribution anomaly
- [ ] unusually large day-over-day volume change
- [ ] source availability / HTTP failures
- [ ] successful write to R2
- [ ] manifest updated

A failed source must not silently produce an empty successful dataset.

## 12. GitHub Actions

Current acquisition probe workflow:

- [x] Runs on `main` push.
- [x] Supports manual dispatch.
- [x] Uses Python 3.12.
- [x] Runs acquisition probe.
- [x] Publishes probe report as an artifact.
- [x] Current workflow has write permission for probe-report publication.

Future:

- [ ] Separate test workflow from production ingestion workflow.
- [ ] Scheduled daily ingestion after acquisition methods are hardened.
- [ ] Retry/backoff.
- [ ] Failure notification.
- [ ] R2 write verification.
- [ ] Historical backfill workflow.
- [ ] Reconciliation workflow.

## 13. Cloudflare R2

Infrastructure already established:

- [x] Cloudflare account created.
- [x] R2 bucket created.
- [x] R2 S3-compatible API credentials created.
- [x] Account ID available.
- [x] GitHub Actions secrets configured:
  - `CLOUDFLARE_ACCOUNT_ID`
  - `R2_ACCESS_KEY_ID`
  - `R2_SECRET_ACCESS_KEY`
  - `R2_BUCKET_NAME`
- [x] GitHub → R2 connectivity test passed.

Next:

- [ ] Define production bucket layout.
- [ ] Implement canonical Parquet writer.
- [ ] Implement manifest.
- [ ] Implement atomic/validated writes.
- [ ] Implement read layer for Streamlit.

## 14. Streamlit application

After data pipeline is reliable:

- [ ] Repository application structure finalized.
- [ ] Insider dashboard.
- [ ] Bulk/block dashboard.
- [ ] Rights/preferential dashboard.
- [ ] Combined unusual-activity view.
- [ ] Company search.
- [ ] Insider/participant search.
- [ ] Date range filters.
- [ ] BUY vs SELL views.
- [ ] Source-document drill-down.
- [ ] Last successful ingestion timestamp.
- [ ] Data-quality/status page.
- [ ] Mobile-friendly layout.

## 15. Validation / research rules

- Official NSE/BSE material is the reference standard whenever available.
- Third-party libraries are acquisition tools, not authoritative sources.
- A successful HTTP response is not sufficient evidence that data acquisition succeeded.
- Record counts must be inspected.
- Samples must be checked against official exchange data.
- Never silently substitute stale cached data for a failed current-day source.
- Keep acquisition logs so failures are diagnosable.
- Do not claim a dataset is complete until historical and daily tests support that conclusion.

## 16. Current execution queue

### NOW — acquisition validation
- [x] Phase 1A/2 initial probe created.
- [x] NSE bulk/block initial route demonstrated.
- [x] BSE official page reachability demonstrated.
- [ ] Finish current Phase 1A + 1B + Phase 2 probe.
- [ ] Inspect complete probe artifact/logs.
- [ ] Select best NSE insider method.
- [ ] Select best BSE insider method.
- [ ] Select best BSE bulk/block method.
- [ ] Validate NSE/BSE Rights + Preferential methods.

### NEXT — hardening
- [ ] Repeat successful methods multiple times.
- [ ] Test rate limiting.
- [ ] Test transient failures and retries.
- [ ] Test empty-day handling.
- [ ] Test schema drift detection.
- [ ] Build acquisition adapter interface.

### THEN — storage
- [ ] R2 layout.
- [ ] Canonical schema.
- [ ] Parquet compression/partitioning.
- [ ] Deduplication.
- [ ] Manifest/reconciliation.
- [ ] One-year backfill.

### THEN — application
- [ ] Streamlit data layer.
- [ ] Dashboards.
- [ ] Search/filtering.
- [ ] Analytics.
- [ ] Production deployment.

## 17. Definition of done

The project is production-ready when:

1. NSE and BSE data can be acquired unattended with a documented primary/fallback method.
2. Insider BUY and SELL data are correctly captured and auditable.
3. Bulk and block deals are reliably captured separately.
4. Rights and preferential issue lifecycle data are captured separately from insider transactions.
5. At least one year of data is stored outside GitHub in compact R2 objects.
6. Duplicate/amended filings are handled deterministically.
7. Failed or incomplete acquisition days are detectable and recoverable.
8. Streamlit reads from the canonical R2 dataset rather than repository-sized data files.
9. Every important displayed record can be traced to its exchange/source.
10. Automated tests and acquisition checks remain green after deployment.

---

## Change log

### 2026-09-01
- Established this document as the project-wide task tracker and framework.
- Added Phase 1A insider acquisition validation.
- Added Phase 1B Rights + Preferential issue acquisition validation.
- Added Phase 2 Bulk + Block deal validation.
- Documented Cloudflare R2/GitHub architecture and one-year storage objective.
- Documented filing/transaction/issue-event separation and deduplication requirements.
