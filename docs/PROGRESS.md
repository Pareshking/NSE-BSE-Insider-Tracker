# Progress (09 Oct 2026, times IST)

## Where we are
Phase 0 audit approved. Phase 1 data foundation in production (PR #11, price layer PR #12). Phase 2 evidence closed (PR #13, #14; conclusion: insufficient evidence of an edge, `docs/RESEARCH.md` J.3 and K). Phase 3 product built on `feat/phase3-ui-shell` (draft PR #15); the owner waived a separate staging app and approved merge and cut-over (gates 2 and 7, see `docs/DECISIONS.md`). Phases 4-5: reconciliation note written (`docs/RECONCILIATION.md`); runbook and re-evaluation schedule still to do.

| Area | State |
|---|---|
| Raw layer (`raw_v2/`, write-once) | In production, nightly. Owner-side object-lock still to set |
| Clean layer (2026 window, counted reasons) | In production; `source_url` column appears after the next "Clean only" run |
| Price, market-cap and index layers | Complete from 1 Jan 2025 (NSE and BSE UDiFF, NSE `mcap`, all NSE indices incl. Nifty 500) |
| Precompute pipeline | `scripts/precompute_slim.py` (workflow "Precompute slim assets", dispatch only) writes `artifacts/prices_summary_slim.parquet` (11,277 ISINs, 3,326 with a market-cap bucket) and `ledger/ledger_marks.parquet`. Pages never load the full price table. Not yet scheduled |
| Forward ledger | Append-only. `promoter_accum_v1`: 252 signals. `promoter_campaign_v2`: 76 campaign signals. 328 total, 10 matured at 60 sessions (both series together) |
| Research | H1, H2, H8 and conditioned cuts run; benchmark simplified to Nifty 500 (owner). Costs: flat 0.30 percentage-point round trip applied on the evidence page (ESTIMATED assumption). Matched excess, buys-minus-sells and non-market hypotheses H3-H7/H9 deferred to the Phase 5 backlog |
| App (branch) | 13 pages in three groups: Executive Conviction (Overview, Promoter Screener, Company Deep Dive, Forward Ledger, Risk & Caution Flags, Signal Evidence), Exploration & Screeners (legacy tools), Operations & Audit (Data Health, Data Quality). Private watchlist (secrets or session). Theme aligned with the reference app |
| Tests | 191 pytest tests pass, plus the legacy page runner (`streamlit_app/tests/test_pages.py`, 0 failures) |
| Active branch | `feat/phase3-ui-shell` |

## Known risks
- The slim price summary and ledger marks are static until the precompute workflow is dispatched; a schedule needs a decision.
- Not verified on Streamlit Cloud: import path, memory (local estimate +19 MB for one company), grouped navigation (tested on Streamlit 1.65).
- Production could not be viewed from this environment (login wall).
- Under-powered tests are reported as "insufficient evidence"; the 120-session figures are PRELIMINARY — SAMPLE MATURING IN 2026.

## Next
1. Merge PR #15 (approved), dispatch "Clean only" on `main`, confirm the deploy loads.
2. Schedule or dispatch "Forward ledger update" then "Precompute slim assets" after the nightly run.
3. Phase 5 backlog: pledges and results dates, size/liquidity-matched excess, buys minus sells, H3-H7/H9, runbook.
