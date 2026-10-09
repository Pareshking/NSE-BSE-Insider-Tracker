# Progress (09 Oct 2026, times IST)

## Where we are
Phase 0 audit approved. Phase 1 data foundation in production (PR #11, price layer PR #12). Phase 2 evidence closed (PR #13, #14; conclusion: insufficient evidence of an edge, `docs/RESEARCH.md` J.3 and K). Phase 3 product merged to `main` (PR #15, cut-over approved by the owner at gates 2 and 7, no staging app; see `docs/DECISIONS.md`), followed by a density and menu overhaul (`fix/screener-density`). Phases 4-5: reconciliation note written (`docs/RECONCILIATION.md`); runbook and re-evaluation schedule still to do.

| Area | State |
|---|---|
| Raw layer (`raw_v2/`, write-once) | In production, nightly. Owner-side object-lock still to set |
| Clean layer (2026 window, counted reasons) | In production; `source_url` column appears after the next "Clean only" run |
| Price, market-cap and index layers | Complete from 1 Jan 2025 (NSE and BSE UDiFF, NSE `mcap`, all NSE indices incl. Nifty 500) |
| Precompute pipeline | `scripts/precompute_slim.py` (workflow "Precompute slim assets", dispatch only) writes `artifacts/prices_summary_slim.parquet` (11,277 ISINs, 3,326 with a market-cap bucket) and `ledger/ledger_marks.parquet`. Pages never load the full price table. Not yet scheduled |
| Forward ledger | Append-only. `promoter_accum_v1`: 252 signals. `promoter_campaign_v2`: 76 campaign signals. 328 total, 10 matured at 60 sessions (both series together) |
| Research | H1, H2, H8 and conditioned cuts run; benchmark simplified to Nifty 500 (owner). Costs: flat 0.30 percentage-point round trip applied on the evidence page (ESTIMATED assumption). Matched excess, buys-minus-sells and non-market hypotheses H3-H7/H9 deferred to the Phase 5 backlog |
| App (`main`) | 13 pages in three plain-named menus. Daily: Latest Filings, Promoter Screener, Company Page, Promoter Selling. Explore: Promoter Trades, Bulk & Block Deals, Overlapping Activity, Person & Fund Search, All Filings. Research & Data: Research Findings, Tracked Signals, Data Status, Run Checks. Private watchlist (secrets or session). Density overhaul (table first, no prose banners; caveats live on Research Findings) |
| Tests | 191 pytest tests pass, plus the legacy page runner (`streamlit_app/tests/test_pages.py`, 0 failures) |
| Automation | After the nightly "R2 Storage Write" run on `main`: Forward ledger update, then Precompute slim assets (workflow_run chain) |
| Active branch | `fix/screener-density` (merged to `main`) |

## Known risks
- The slim price summary and ledger marks refresh through the post-nightly chain; the first scheduled run is unobserved.
- Not verified on Streamlit Cloud: import path, memory (local estimate +19 MB for one company), grouped navigation (tested on Streamlit 1.65).
- Production could not be viewed from this environment (login wall).
- Under-powered tests are reported as "insufficient evidence"; the 120-session figures are PRELIMINARY — SAMPLE MATURING IN 2026.

## Next
1. Check the deployed app after each merge (not visible from the agent environment).
2. Watch the first scheduled chain after the nightly run (ledger update, then precompute).
3. Phase 5 backlog: pledges and results dates, size/liquidity-matched excess, buys minus sells, H3-H7/H9, runbook.
