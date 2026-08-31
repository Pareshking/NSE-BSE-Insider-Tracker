# NSE-BSE Insider Tracker — AI Handover Memory & Master Task Tracker

> **Purpose:** This file is the persistent memory/handover document for any AI/engineer taking over this repository. Read this file before changing code. It records the project's mission, decisions, verified facts, failed experiments, current state, next actions, and definition of done.
>
> **Repository:** `Pareshking/NSE-BSE-Insider-Tracker`
> **Primary branch:** `main`
> **Current status:** Phase 1A + Phase 1B + Phase 2 acquisition validation in progress.
> **Validation target date:** `2026-08-31` (the previous trading/disclosure day at the time this work started).
> **Last updated:** 2026-09-01

---

## 0. HANDOVER INSTRUCTIONS — READ FIRST

### For the next AI/engineer

1. **Do not restart or redesign the project from scratch.** Continue from the current `main` branch.
2. **Read this file first**, then inspect the current repository/workflows/scripts before acting.
3. Treat the checkboxes and `Verified Findings` section as the current project state. Do not claim planned work is completed.
4. **Test → inspect results → fix → retest → continue.** Do not stop after the first failed method when a reasonable fallback exists.
5. Do not ask the user for manual permission for each small engineering step. The user has explicitly authorized autonomous execution of the Phase 1/2 validation loop.
6. Do not expose or request secret values in chat. GitHub repository secrets already contain the R2 credentials. Never commit credentials.
7. Official NSE/BSE material is the authority. Third-party Python libraries are only acquisition mechanisms/fallbacks.
8. A HTTP 200, a non-empty HTML page, or a successful Python call is **not** proof that useful data was acquired. Inspect actual records and fields.
9. A failed wrapper is not automatically evidence that NSE/BSE blocked the request; distinguish **source blocking**, **endpoint change**, **parser/library failure**, **empty result**, and **network failure**.
10. Keep insider transactions, bulk deals, block deals, rights issues, preferential issues, filings, transactions, allotments, and listings as distinct concepts.
11. Do not move to production storage/backfill until acquisition reliability is sufficiently established.
12. Update this document whenever a major test is verified, a method is rejected, an architecture decision is made, or a phase changes status.

---

## 1. PROJECT MISSION

Build a reliable, low-cost NSE + BSE market-disclosure system that can collect, preserve, search, and analyse at least one year of historical data while remaining inexpensive enough to operate using GitHub Actions + Cloudflare R2 + Streamlit.

Core goals:

- Prefer official NSE and BSE sources.
- Survive exchange blocking/rate limiting through legitimate session/library/browser fallbacks.
- Capture insider **BUY and SELL** transactions correctly.
- Capture NSE/BSE **bulk and block deals** as separate market-activity datasets.
- Capture **Rights and Preferential issues**, including lifecycle events where obtainable.
- Maintain at least one year of history, with capacity for longer retention.
- Store data compactly in Cloudflare R2, not as large GitHub repository files.
- Deduplicate deterministically without destroying source provenance.
- Preserve enough raw/source information to audit important records against NSE/BSE.
- Provide a Streamlit UI over canonical data.

The system is intended to become one site where these related datasets can be searched and correlated, **without incorrectly treating them as the same type of event**.

---

## 2. IMPORTANT PRODUCT/QUANTITATIVE DECISIONS

### 2.1 Insider vs market deals
Bulk/block deals are **not insider transactions**. They must remain separate in storage and UI. They may later be correlated analytically, but a participant must not be labelled an insider merely because they appear in a bulk/block disclosure.

### 2.2 Filing vs underlying event
A filing is a source publication. It is not necessarily one transaction/event.

We will model separately:

- Filing
- Insider transaction
- Market deal
- Issue
- Issue lifecycle event

### 2.3 Issue lifecycle
For Rights/Preferential issues, do not count the following as independent issues merely because they appear as separate disclosures:

`announcement → approval → allotment → listing approval → trading commencement`

These are lifecycle events belonging to an issue.

### 2.4 BUY/SELL
Do not infer SELL from a holding decrease. Use the disclosed transaction/action fields.

### 2.5 Cross-exchange duplication
The same economic transaction/disclosure may appear through NSE and BSE. Do not blindly concatenate NSE + BSE rows. Identity and provenance must be designed to distinguish:

- same filing mirrored across exchanges
- same transaction executed on a specific exchange
- genuinely separate transactions
- amended/re-filed disclosure

### 2.6 Source hierarchy
Preferred order:

1. Official exchange endpoint/data file/XBRL/document.
2. A maintained library that reliably retrieves the official data.
3. Direct session/request fallback.
4. Browser automation only when justified and stable.

A third-party library is never the authority for the meaning of a record.

---

## 3. VERIFIED INFRASTRUCTURE STATE

### Cloudflare R2

Already completed:

- [x] Cloudflare account created.
- [x] R2 enabled/bucket created.
- [x] R2 S3 API credentials created.
- [x] Cloudflare Account ID obtained.
- [x] GitHub Actions repository secrets configured:
  - `CLOUDFLARE_ACCOUNT_ID`
  - `R2_ACCESS_KEY_ID`
  - `R2_SECRET_ACCESS_KEY`
  - `R2_BUCKET_NAME`
- [x] R2 connectivity has been tested successfully.

**Important clarification:** Cloudflare calls these **S3 API keys** because R2 provides an S3-compatible API. This is still Cloudflare R2, not Amazon S3.

GitHub is the code/workflow layer. R2 is the intended long-term data layer.

### GitHub Actions

Current acquisition probe workflow:

`.github/workflows/acquisition-probe.yml`

It:

- runs on pushes to `main`
- supports `workflow_dispatch`
- uses Python 3.12
- executes `scripts/acquisition_probe.py`
- targets `2026-08-31` for the current validation experiment
- publishes `artifacts/acquisition_probe.json`
- uploads a 14-day GitHub Actions artifact

The workflow has write permission because the probe is currently configured to publish its report to the repository.

---

## 4. VERIFIED ACQUISITION FINDINGS SO FAR

These are **verified observations**, not assumptions.

### NSE — Insider

- [ ] Production acquisition route not yet established.
- Direct NSE API testing from a GitHub runner previously returned **HTTP 403**.
- This proves that at least one direct route is blocked from the runner; it does **not** prove all NSE acquisition paths are blocked.
- A browser/session/library fallback is being tested.

### NSE — Bulk deals

- [x] A GitHub Actions runner successfully retrieved **70 records** for 2026-08-31 through the `nse`/NSE server-library route during the initial probe.
- Still needs validation against official NSE output and historical retrieval testing.

### NSE — Block deals

- [x] A GitHub Actions runner successfully retrieved **11 records** for 2026-08-31 through the `nse`/NSE server-library route during the initial probe.
- Still needs validation against official NSE output and historical retrieval testing.

### BSE — Insider

- [ ] Production acquisition route not yet established.
- Official BSE page reachability was demonstrated with **HTTP 200** during the initial probe.
- The previous `bseindia` wrapper returned no tables.
- `BseIndiaApi` previously failed with an internal `IndexError`.
- Neither failure should yet be classified as BSE blocking; endpoint/parser/library behaviour must be investigated.

### BSE — Bulk/Block

- [ ] Reliable acquisition route not yet established.
- Direct official endpoints/pages and wrapper alternatives are being tested.

### NSE/BSE Rights + Preferential

- [ ] Acquisition route not yet established.
- NSE has dedicated corporate-filing surfaces for these further issues; the current probe is testing those routes.
- BSE information is expected across corporate announcements, issue/public-issue surfaces, and allotment/listing notices; the probe is testing actual record retrieval rather than relying on page reachability.

---

## 5. CURRENT PHASE STATUS

### PHASE 1A — INSIDER TRADING ACQUISITION

**Goal:** Reliable unattended NSE + BSE Regulation 7(2) acquisition, including BUY and SELL.

Status: **IN PROGRESS**

Tasks:

- [ ] NSE official route.
- [ ] NSE maintained-library/session route.
- [ ] NSE direct archive/XBRL/CSV route.
- [ ] NSE browser/session fallback if required.
- [ ] BSE official route.
- [ ] BSE maintained wrapper route.
- [ ] BSE direct session/API fallback.
- [ ] Verify actual records, not merely HTTP success.
- [ ] Verify BUY records.
- [ ] Verify SELL records.
- [ ] Verify transaction date vs filing date.
- [ ] Verify participant/security/quantity/value fields.
- [ ] Verify execution exchange where disclosed.
- [ ] Preserve source document/XBRL/reference.
- [ ] Test repeatability.
- [ ] Test rate limiting/transient failure.
- [ ] Cross-check samples against official exchange material.

**Acceptance criteria:** at least one reliable unattended method per exchange, with BUY and SELL verified and source traceability.

---

### PHASE 1B — RIGHTS + PREFERENTIAL ISSUES

**Goal:** Add capital-raising/further-issue data without mixing it with insider trades.

Tasks:

#### NSE
- [ ] Preferential issue proposed/in-principle.
- [ ] Preferential post-allotment.
- [ ] Allotment date.
- [ ] Number of shares/securities allotted.
- [ ] Issue price / amount where available.
- [ ] Listing/trading approval fields where available.
- [ ] Rights issue data.

#### BSE
- [ ] Preferential issue announcements.
- [ ] Preferential allotment/listing notices.
- [ ] Rights/public-issue data.
- [ ] Allotment/listing/trading commencement information where obtainable.

#### Common
- [ ] Stable issue identity.
- [ ] Separate lifecycle events.
- [ ] Source references.
- [ ] Historical retrieval test.
- [ ] Avoid double-counting one issue across lifecycle disclosures.

Status: **IN PROGRESS**

---

### PHASE 2 — BULK + BLOCK DEALS

**Goal:** Reliable market-deal acquisition for both exchanges.

#### NSE
- [x] Bulk route demonstrated: 70 records on 2026-08-31.
- [x] Block route demonstrated: 11 records on 2026-08-31.
- [ ] Cross-check sample against official NSE output.
- [ ] Historical retrieval.
- [ ] Repeatability/rate-limit test.

#### BSE
- [ ] Bulk route.
- [ ] Block route.
- [ ] Official endpoint/page validation.
- [ ] Wrapper comparison.
- [ ] Historical retrieval.
- [ ] Repeatability/rate-limit test.

Status: **IN PROGRESS**

---

## 6. CURRENT EXPERIMENT / LOOP

The project is intentionally following this loop:

```text
Inspect current code
      ↓
Run acquisition test on GitHub Actions
      ↓
Inspect actual logs + records
      ↓
Classify failure precisely
      ↓
Try a reasonable alternative method
      ↓
Run again
      ↓
Cross-check successful records against official source
      ↓
Mark method PASS / FALLBACK / REJECTED
      ↓
Continue until Phase 1A/1B/2 have defensible acquisition routes
```

The user explicitly requested that this loop continue without pausing for approval after every small test.

### Current probe scope

The hardened probe is intended to test:

- NSE insider
- NSE bulk
- NSE block
- NSE preferential
- NSE rights
- BSE insider
- BSE bulk
- BSE block
- BSE preferential
- BSE rights
- official-page/API availability
- wrapper/library alternatives
- browser/session fallback where justified

**Do not declare success until the generated artifact/logs have been inspected.**

---

## 7. DATA MODEL — TARGET

### Filing
A source disclosure/publication from NSE or BSE.

Suggested attributes:

- source exchange
- filing/document ID
- filing date/time
- company/security
- document URL/reference
- raw/source object reference
- retrieval timestamp
- content hash
- amendment/version information

### Insider Transaction
Underlying disclosed transaction.

Suggested attributes:

- company/security
- insider/participant as disclosed
- role/category
- transaction/action type
- BUY/SELL
- transaction date
- quantity
- price/value
- holding before/after where disclosed
- execution exchange where disclosed
- source filing ID
- deterministic event ID

### Market Deal
Bulk/block deal disclosure.

Suggested attributes:

- exchange/source
- date
- symbol/security
- client/participant
- buy/sell
- quantity
- price/weighted average price
- source ID/reference

### Issue
A Rights or Preferential issue.

### Issue Event
One lifecycle event associated with an issue:

- announcement
- board approval
- shareholder approval
- in-principle approval
- allotment
- listing approval
- trading commencement

This separation is mandatory to prevent double-counting.

---

## 8. DEDUPLICATION / VERSIONING

Requirements:

- [ ] Use source-specific stable IDs where available.
- [ ] Use deterministic fallback IDs when source IDs are absent.
- [ ] Include source/exchange in identity where appropriate.
- [ ] Preserve filing/document ID.
- [ ] Include event/transaction date and security/participant attributes as needed.
- [ ] Detect amended/re-filed disclosures.
- [ ] Do not silently overwrite historical source data.
- [ ] Never deduplicate only on company + date + BUY/SELL.
- [ ] Test cross-exchange duplicates.
- [ ] Test repeated daily pulls.

A useful future pattern is to keep both:

`source_filing_id` → provenance

`canonical_event_id` → deduplicated economic event

while retaining all source observations.

---

## 9. STORAGE PLAN — DO AFTER ACQUISITION IS PROVEN

Cloudflare R2 should hold the durable dataset.

Preferred structure:

```text
R2 bucket
├── raw/
│   ├── nse/
│   └── bse/
├── canonical/
│   ├── insider/
│   ├── bulk/
│   ├── block/
│   ├── preferential/
│   └── rights/
├── manifests/
└── audits/
```

Exact partitioning is still to be benchmarked.

### Principles

- Prefer Parquet/columnar storage for canonical datasets.
- Compress data.
- Partition by domain/source/date as useful.
- Avoid storing duplicate full payloads unnecessarily.
- Keep raw/source snapshots for auditability, but use retention/deduplication intelligently.
- Store deterministic IDs and retrieval metadata.
- Maintain a manifest for every expected acquisition day/domain.
- Make failed/partial days detectable.
- Use atomic/validated writes so a failed run cannot masquerade as a complete day.

### Retention goal

- Minimum: **one year**.
- Prefer ability to retain longer if R2 footprint remains small.
- GitHub repository must not become the historical data warehouse.

---

## 10. DAILY INGESTION ARCHITECTURE — TARGET

```text
                NSE official sources
                         │
                ┌────────┴────────┐
                │ primary adapter │
                └────────┬────────┘
                         │ fallback(s)
                         ▼
                    validation
                         │
BSE official ───────► normalization
                         │
                         ├──────────────┐
                         ▼              ▼
                  raw/source       canonical
                  provenance        Parquet
                         │              │
                         └──────┬───────┘
                                ▼
                       R2 + manifest/audit
                                │
                                ▼
                         Streamlit read layer
```

GitHub Actions performs scheduled collection and validation. R2 holds durable data. Streamlit reads canonical data.

---

## 11. DAILY DATA-QUALITY CONTROLS

Every production ingestion should verify:

- expected date
- source availability
- HTTP/status outcome
- actual record count
- schema fingerprint/drift
- critical-field completeness
- duplicate count
- BUY/SELL distribution
- abnormal record-count change
- source/document references
- successful R2 write
- manifest update
- no silent replacement by stale cache

A source failure must be represented as a failure/partial state, **not an empty successful dataset**.

---

## 12. HISTORICAL BACKFILL

After daily acquisition is reliable:

- [ ] Determine official historical coverage for each dataset.
- [ ] Determine safest backfill cadence/rate.
- [ ] Backfill in bounded date ranges.
- [ ] Check record counts and gaps.
- [ ] Deduplicate during ingestion, not only at the end.
- [ ] Preserve source references.
- [ ] Write to R2 incrementally.
- [ ] Build reconciliation report.
- [ ] Verify minimum one-year coverage.

Do not assume every NSE/BSE dataset has identical historical availability or API behaviour.

---

## 13. STREAMLIT — TARGET APPLICATION

The eventual single-site UI should include:

### Insider Trading
- company search
- insider/participant search
- BUY/SELL filters
- date range
- quantity/value
- promoter/director/category where disclosed
- rolling 7/30/90/365-day views
- source-document drill-down

### Bulk / Block Deals
- company/security
- participant/client
- BUY/SELL
- quantity/value
- date
- exchange

### Rights / Preferential
- company
- issue type
- issue lifecycle status
- proposed/allotted/listed/trading commencement
- issue price/quantity where available
- source reference

### Combined analytics
Potential future correlations:

- insider activity + bulk/block activity
- insider activity + capital raising
- repeated insider BUY/SELL patterns
- unusual activity windows

**Important:** Correlation is not causation. UI labels must reflect what the data actually establishes.

### Operational status
The application should eventually display:

- last successful ingestion
- source status
- data coverage
- missing days
- current dataset version

---

## 14. FUTURE DATASETS — NOT CURRENT BLOCKERS

Potential additions after the core system is reliable:

- Bonus issues
- Buybacks
- Mergers/demergers
- Other corporate actions
- Delivery/institutional indicators

Do not expand scope merely for completeness. Add datasets when source quality and analytical value justify them.

---

## 15. PHASED MASTER CHECKLIST

### Phase 0 — Infrastructure
- [x] GitHub repository created.
- [x] Cloudflare R2 created.
- [x] R2 S3-compatible credentials created.
- [x] Account ID obtained.
- [x] GitHub secrets configured.
- [x] R2 connectivity verified.

### Phase 1A — Insider
- [ ] NSE reliable route.
- [ ] BSE reliable route.
- [ ] BUY verified.
- [ ] SELL verified.
- [ ] Source auditability verified.
- [ ] Historical retrieval verified.
- [ ] Failure/retry behaviour verified.

### Phase 1B — Rights/Preferential
- [ ] NSE preferential.
- [ ] NSE rights.
- [ ] BSE preferential.
- [ ] BSE rights.
- [ ] Lifecycle model verified.
- [ ] Historical retrieval verified.

### Phase 2 — Bulk/Block
- [x] NSE bulk route demonstrated.
- [x] NSE block route demonstrated.
- [ ] NSE validation/historical test.
- [ ] BSE bulk reliable route.
- [ ] BSE block reliable route.
- [ ] BSE validation/historical test.

### Phase 3 — Acquisition hardening
- [ ] Adapter interface.
- [ ] Retry/backoff.
- [ ] Rate-limit handling.
- [ ] Source fallback selection.
- [ ] Schema drift checks.
- [ ] Data-quality gates.
- [ ] Failure notifications.

### Phase 4 — Storage
- [ ] R2 layout finalized.
- [ ] Canonical schema finalized.
- [ ] Parquet writer.
- [ ] Compression/partition benchmark.
- [ ] Dedup/versioning.
- [ ] Manifest.
- [ ] Atomic writes.
- [ ] Read layer.

### Phase 5 — Historical data
- [ ] One-year backfill.
- [ ] Gap detection.
- [ ] Reconciliation.
- [ ] Storage-size benchmark.

### Phase 6 — Streamlit
- [ ] Data access layer.
- [ ] Insider dashboard.
- [ ] Bulk/block dashboard.
- [ ] Rights/preferential dashboard.
- [ ] Combined analytics.
- [ ] Search/filtering.
- [ ] Source drill-down.
- [ ] Data-quality page.
- [ ] Mobile layout.

### Phase 7 — Production
- [ ] Scheduled daily ingestion.
- [ ] Monitoring.
- [ ] Failure alerts.
- [ ] Automated tests.
- [ ] Deployment verification.
- [ ] Documentation.

---

## 16. DEFINITION OF DONE

The project is production-ready only when all of the following are true:

1. NSE and BSE data can be acquired unattended using documented primary/fallback methods.
2. Insider BUY and SELL records are correctly captured.
3. Bulk and block deals are captured separately and reliably.
4. Rights and Preferential issue data are captured separately from insider transactions.
5. Issue lifecycle events do not cause double-counting.
6. At least one year of history is stored outside GitHub in compact R2 objects.
7. Duplicate and amended filings are handled deterministically.
8. Missing/failed acquisition days are detectable and recoverable.
9. Streamlit reads canonical R2 data rather than repository-sized datasets.
10. Important displayed records can be traced back to NSE/BSE source material.
11. Daily acquisition has retry/rate-limit/failure handling.
12. Data-quality checks prevent silent empty or incomplete datasets from being marked successful.
13. Automated tests remain green after deployment.

---

## 17. CHANGE LOG / DECISION HISTORY

### 2026-09-01

- Created `NSE-BSE-Insider-Tracker` project and began acquisition-first architecture.
- Created Cloudflare R2 storage and GitHub Actions credentials.
- Established GitHub Actions as the acquisition execution layer and R2 as durable storage.
- First acquisition probe found direct NSE API HTTP 403 from GitHub runner.
- First probe successfully retrieved **70 NSE bulk** and **11 NSE block** records for 2026-08-31 using an NSE server/library route.
- First BSE probe reached official page with HTTP 200 but existing wrappers did not yet yield reliable tables.
- Expanded scope to include Rights and Preferential issues after identifying their official NSE/BSE availability.
- Decided to treat Filing, Insider Transaction, Market Deal, Issue, and Issue Event as separate data-model concepts.
- Decided not to move to storage/backfill until source acquisition reliability is established.
- User explicitly authorized the AI to continue the Phase 1A + 1B + Phase 2 test/verify/fix/retest loop without requesting incremental approval.
- This file was upgraded from a simple project plan into the **persistent AI handover/memory document** so another AI can continue the project without relying on chat history.

---

## 18. HANDOVER SNAPSHOT

**If taking over today, the immediate job is:**

> Inspect the latest GitHub Actions acquisition probe for 2026-08-31, inspect the actual JSON/log output, classify each NSE/BSE method as PASS / FALLBACK / REJECTED, then continue testing alternatives for any unresolved dataset. Do not move to R2 production storage until Phase 1A/1B/2 acquisition routes are defensible.

**Current unresolved core question:**

> Can GitHub Actions reliably acquire NSE + BSE insider, bulk, block, Rights, and Preferential data every day despite exchange anti-bot/rate-limit behaviour?

Answer this with experiments and source verification, not assumptions.
