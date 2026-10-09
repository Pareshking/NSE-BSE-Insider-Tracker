# Phase 4 reconciliation: legacy `main` vs rebuilt app (09 Oct 2026, IST)

Basis: `main` at 97b2f58 (PR #14) against `feat/phase3-ui-shell` (PR #15). Owner approved gates 2 and 7 and waived a separate staging app (`docs/DECISIONS.md`). Labels: VERIFIED (read in code or run), ESTIMATED, NOT RUN.

## 1. What changes on the live app
| Area | `main` today | After merge |
|---|---|---|
| Navigation | 7 flat top-bar pages | 13 pages in three groups (Daily, Explore, Research & Data) with plain names; see `docs/DECISIONS.md` for the old-to-new name map. VERIFIED in `app.py` |
| Legacy pages | Overview, Confluence Screener, Entity Tracker, Evidence & Drill-down, Promoter Activity, Bulk & Block Concentration, Data Quality | All kept. Logic untouched except: Promoter Activity and Bulk & Block default window 30D -> 90D (options stay 7D/30D/90D); Confluence caption no longer says "informed entities"; Overview and Evidence gain dense trade tables, accumulation badges and the watchlist toggle |
| New pages | none | Promoter Screener, Company Deep Dive, Forward Ledger, Risk & Caution Flags, Signal Evidence, Data Health & Lineage |
| Look | IBM Plex, blue accent | Geist, indigo "Clear Ledger" palette, tighter gutters (`.streamlit/config.toml`, `lib/style.py`). Colors and fonts only |
| Data read | Nightly canonical archive (`r2_data`) | Legacy pages unchanged; new pages read `clean/current/*.parquet`, `artifacts/prices_summary_slim.parquet`, `ledger/*`, `indices/`, and one ISIN's `prices/daily/nse/*` on demand |
| Windows | 7D/30D/90D | Legacy pages as above. New pages use 90/180/365 days, campaigns with gaps <= 90 days, net of sales. No 30-day repeat or rapid-selling flags remain in new code |
| Automation | existing workflows | Added `ledger-update.yml` and `precompute-slim.yml` (dispatch only, shared R2 write lock). Nothing scheduled |

## 2. Numbers: legacy vs clean layer
NOT RUN as a side-by-side. The legacy Overview ranks promoter net flow from the nightly archive with a mode-text exclusion list; the new pages use the clean layer's `is_market` flag, primary-copy filings only and the 2026 window. Expect differences in promoter lists and values. A comparison needs R2 access, which exists only in GitHub Actions; run it as a follow-up job if the owner wants one. Both views are labelled in the app, and the legacy pages remain available for comparison after cut-over.

## 3. Verification done
- 191 pytest tests pass, including AppTest smoke tests for every new page (data present, artifacts missing, R2 outage) and the legacy runner (`python streamlit_app/tests/test_pages.py`, 0 failures). VERIFIED.
- Full-app AppTest of `app.py` with grouped navigation: no exceptions (Streamlit 1.65). VERIFIED.
- Memory, synthetic data (472k price rows, 9 month files): full load +103 MB peak RSS; one-ISIN load +19 MB; cache hit 0.5 ms. ESTIMATED for Streamlit Cloud.
- Precompute and ledger runs on real data (Actions): 11,277 ISINs summarised; ledger 252 v1 + 76 v2 = 328 rows, v1 rows unchanged. VERIFIED from job logs.

## 4. Not verified, known limitations
- Never opened on Streamlit Cloud: import path (`insiders_clean` added to `sys.path` in `app.py`), real memory, grouped navigation on the deployed Streamlit version, mobile layout.
- Slim summary and ledger marks are static until the workflows are dispatched; pages show their age in Data Health. A schedule is a follow-up needing a decision.
- BSE-only securities have no market-cap bucket ("n/a"); dual-listed BSE prices inherit NSE factors.
- The `source_url` column (exchange file links) appears only after the next "Clean only" run.
- Deals carry no FII/DII label; "Deals align" says only that large bulk/block buying coincided.
- The clean data has no post-transaction shareholding percentage; equity absorbed is value / market cap (ESTIMATED).
- Pledges, results dates, SAST and surveillance flags are not collected.

## 5. Rollback
Revert the squash-merge commit on `main`; Streamlit redeploys the previous app. R2 artifacts written during the rebuild are additive and harmless to the old app. Forward-ledger rows are append-only and stay. Reverting does not need any data step.
