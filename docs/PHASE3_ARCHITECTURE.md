# Phase 3 architecture (UI shell, draft)

Status: stubs only, on branch `feat/phase3-ui-shell`. Not deployed: `streamlit_app/app.py` builds its menu with `st.navigation`, which ignores the `pages/` folder, so these pages do not appear in production until a cut-over (approval gate 7). To preview, run each page file with `streamlit run streamlit_app/pages/<file>.py` with R2 read credentials.

| Page | Purpose | Data | State |
|---|---|---|---|
| 1_Noteworthy_Accumulation | promoter open-market buys >= Rs 25 lakh, repeat buying within 30 days; net bulk/block buying | `clean/current/insider_trades`, `deals` | working stub |
| 2_Company_Deep_Dive | price with insider filings, deal days, split/bonus steps | `prices/daily/nse`, clean tables | working stub; results dates not collected |
| 3_Risk_Flags | heavy insider selling as a caution flag | `insider_trades` | working stub; pledge spikes not collected |
| 4_Forward_Ledger | append-only maturing-signal table | `ledger/` (does not exist) | empty state, rules described |
| 5_Data_Health | freshness and coverage | all tables | working stub; exclusion counts link to the clean reports |

Design: pure functions in `insiders_clean/product_views.py` (tested), thin Streamlit pages, read-only cached loaders in `streamlit_app/lib/clean_data.py`. Honest labels: "no proven edge" on buy lists (RESEARCH.md J.3), sells are a caution flag, anything not built says so. The UI shows only absolute return and excess vs Nifty 500 where outcomes appear (not built yet).

Open items before cut-over: forward-ledger writer job, pledge and results-date collection, BSE market cap, matched-excess research (RESEARCH.md J.3), mobile layout check, page tests under `streamlit_app/tests`.
