# Phase 3 architecture (UI shell, draft)

Status: working pages wired into the `streamlit_app/app.py` navigation, on branch `feat/phase3-ui-shell` (PR #15, draft). They go live only when this branch is merged to `main` (approval gate 2; redeploys production). Smoke tests: `streamlit_app/tests/test_product_pages.py`.

| Page | Purpose | Data | State |
|---|---|---|---|
| 1_Noteworthy_Accumulation | promoter open-market buys >= Rs 25 lakh, repeat buying within 30 days; net bulk/block buying | `clean/current/insider_trades`, `deals` | working |
| 2_Company_Deep_Dive | price with insider filings, deal days, split/bonus steps | `prices/daily/nse`, clean tables | working (search by symbol, name or ISIN; links to NSE XBRL where the filing has one); results dates not collected |
| 3_Risk_Flags | heavy insider selling as a caution flag | `insider_trades` | working (30/60 day, heavy and rapid selling); pledge spikes not collected |
| 4_Forward_Ledger | append-only maturing-signal table | `ledger/` (does not exist) | working; reads `ledger/forward_ledger.parquet`, written by the 'Forward ledger update' workflow (dispatch after merge to main) |
| 5_Data_Health | freshness and coverage | all tables | working (freshness, raw_v2 counts, exclusions by reason, unmapped entities) |

Design: pure functions in `insiders_clean/product_views.py` (tested), thin Streamlit pages, read-only cached loaders in `streamlit_app/lib/clean_data.py`. Honest labels: "no proven edge" on buy lists (RESEARCH.md J.3), sells are a caution flag, anything not built says so. The UI shows only absolute return and excess vs Nifty 500 where outcomes appear (not built yet).

Open items before cut-over: forward-ledger writer job, pledge and results-date collection, BSE market cap, matched-excess research (RESEARCH.md J.3), mobile layout check, page tests under `streamlit_app/tests`.
