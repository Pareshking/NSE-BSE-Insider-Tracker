# Production (`main`) audit and multi-quarter realignment plan (9 Oct 2026, IST)

Nothing here is deployed. PR #15 is not merged. Facts below were read from `origin/main` and `feat/phase3-ui-shell` (`git diff origin/main...feat/phase3-ui-shell`); the live site was not opened from this environment (the owner confirmed it works).

## 1. What is live on `main` (VERIFIED from code)

Seven pages in a top navigation bar (`streamlit_app/app.py`), all built on the nightly **canonical archive** in R2 (`manifests/{date}.json`, `canonical/{exchange}/{category}/{date}/data.parquet`, market-cap reference), one run date at a time. None of them read the clean layer, the price table, the index series or the ledger. There is no price chart anywhere on `main`: the code states the project "deliberately has no price history".

| Page | What it does | Controls | Window |
|---|---|---|---|
| Overview (default) | run summary, signals, recent activity list | exchange (Both/NSE/BSE), run date, search | last 90 days |
| Confluence Screener | joins insider trades, bulk/block deals, rights/preferential by ISIN; ranks by Float Absorption Ratio (FAR = combined promoter + institutional net flow as % of market cap) | market-cap tier, category, company search, sort by FAR % or value, CSV export | the run's data |
| Entity Tracker | reverse lookup of a person/fund/client across all 5 categories, 90-day aggregated flow, flags a purchase coinciding with a promoter preferential allotment | exchange, run date, name search, CSV export | 90 days |
| Evidence & Drill-down | raw-ish tables per category (tabs) with filters and search | exchange, run date, per-column multiselects, search, CSV export | the run's data |
| Promoter Activity | net-position rollup by person and by company, with sparklines (plotly) | window **7D / 30D (default) / 90D**, sort basis, two tabs (By Person, By Company) | 7 / 30 / 90 |
| Bulk & Block Concentration | concentration of clients per security, large deals vs company size, repeat clients, sparklines | Bulk/Block tabs, window **7D / 30D (default) / 90D**, By Security / By Client | 7 / 30 / 90 |
| Data Quality | per-run certification matrix, manifest outcomes, cross-exchange flags | run date | one run |

Datasets loaded by `main`: the five canonical categories (insider trading, bulk deals, block deals, rights issue, preferential issue) for NSE and BSE, the daily manifest, and the market-cap reference. Charts: sparklines only (cumulative net flow per row).

30-day artifacts on `main` itself: Promoter Activity and Bulk & Block both default to 30D and offer 7D.

## 2. `main` vs `feat/phase3-ui-shell`

PR #15 changes 20 files (+866 / −1). In `streamlit_app/` the only edit to an existing file is `app.py`: **+5 lines, 0 deleted** (five `st.Page` entries appended after Data Quality). No existing page, library, filter, chart or test is modified or removed. The one deleted line in the PR is in `insiders_clean/insider.py` (a changed column list; adds `source_url`).

| Area | `main` | PR #15 | Lost / broken if merged |
|---|---|---|---|
| Existing 7 pages | live | unchanged, same order and default | nothing |
| Navigation | 7 items | 12 items | crowded on a phone (top bar, no sidebar); consider grouping or moving the 5 new pages behind a second section |
| Data source | canonical archive per run date | adds clean tables (`clean/current/*`), prices, Nifty indices, ledger, raw_v2 listings, cleaning report | none; additive reads |
| Price history | none | Company Deep Dive chart; ledger returns | n/a |
| Insider/deal views | rollups by person/company/security, FAR screener | promoter accumulation list, caution flags, per-company audit table | overlap in purpose with Promoter Activity and Bulk & Block (see §3) |
| Windows | 7/30/90D | 30-day repeat rule, 30/60-day risk windows, 30-day cluster; 90/180 look-backs | to be replaced (§3) |
| Clean layer | not used | `source_url` column added at next Clean only run | none (column is additive) |
| New R2 object | none | `ledger/forward_ledger.parquet` (already written, 252 rows, append-only) | none |

Merge risks to settle before any deploy (none observed on `main` today, all ESTIMATED until run on Streamlit Cloud):
1. **Memory/latency:** Company Deep Dive and Forward Ledger load every stored NSE price month (about 1.1 million rows, roughly 150 MB or more in pandas) and the ledger page recomputes split/bonus factors over the whole table on each cache miss. Community Cloud memory is limited. Fix before deploy: precompute a slim per-ISIN price file and a ledger-marks file in a job, and load only those.
2. **Import path:** the new pages import `insiders_clean` from the repo root; this works locally and in the test runner, but must be confirmed in the deployed environment (Cloud runs from the repo root, so it should; unverified).
3. **Crowded navigation** (above).
4. **Overlap, not conflict:** the new Noteworthy page duplicates part of Promoter Activity and Confluence. Decide whether to merge them into one section rather than ship two promoter views with different windows.

## 3. Realignment to multi-quarter windows: plan (not yet implemented)

Goal: an executive multi-quarter conviction tracker. Remove every 30-day swing artifact from the new pages; the 30-day items to purge are: "repeat buying within 30 days" (Noteworthy cluster, ledger `prior_30d`/P4 cut), "rapid selling" (3+ days) and the 30/60-day risk windows. Keep P4/P5 history in RESEARCH.md as run (it was a registered variant); do not rewrite it.

**Windows (3 only):** 90 days (one quarter), 180 days (two quarters, the SEBI contra-trade window), 365 days (trailing year, but data starts 1 Jan 2026 so it is capped at about 9 months until 2027; the page must say "since 1 Jan 2026" rather than imply a full year).

**Core metrics per security, per window** (`insiders_clean/product_views.py`, new `promoter_absorption()` replacing `promoter_accumulation`):
- Promoter / promoter-group open-market **net value** = buys − sells, in ₹ lakh / crore (sales netted, so a promoter who sells back is not counted as accumulating).
- **% of equity absorbed** = sum of filed `holding_change_pct` (percentage points of shareholding, as reported) where present; otherwise `net value / market cap` as a fallback labelled ESTIMATED. Both shown; the filed figure is preferred.
- Number of buy days, first and last date, whether net positive in each of the three windows ("sustained": positive in 90 and 180 and 365).
- **Campaign grouping:** consecutive promoter buys with gaps of at most 90 days form one campaign (start, end, total value, % absorbed, buy days); a gap above 90 days starts a new one. Replaces the 30-day cluster flag.

**Pages:**
1. Noteworthy → "Promoter conviction": window selector 90/180/365; table of net value and % absorbed per window side by side; filter min net value (₹25 lakh default) or min % absorbed; sustained flag; campaign column; badge "Contextual Accumulation (No Proven Standalone Edge)" unchanged.
2. Deep Dive: add campaign bands (shaded spans) on the price chart; audit table unchanged.
3. Risk Flags → same three windows; cumulative promoter net selling (value and % of equity) replaces "rapid selling"; heavy-selling bar unchanged; the evidence note stays (mixed).
4. Ledger: the rule `promoter_accum_v1` is a single-day ≥ ₹25 lakh promoter buy and has no 30-day element, so existing rows stand. A multi-quarter rule would be a new version `promoter_campaign_v2` (new series, never mixed with v1): ledger rule change requires owner OK.
5. Data Health: no window change.

**Main's own 30D defaults (Promoter Activity, Bulk & Block):** not touched by PR #15. Proposal, needing your decision: change the default to 90D and replace 7D/30D options with 90D/180D/365D after checking that the canonical per-run files contain enough history (unverified; they may hold only a recent window, in which case these pages should read the clean tables instead).

**Tests and process:** add unit tests for net-of-sales, campaign gaps (89/91 days), the 365-day cap, missing `holding_change_pct`; extend `test_product_pages.py`; one PR update on `feat/phase3-ui-shell`; no merge until you approve. Open questions for you: (a) OK to start a v2 ledger series; (b) change main's 7D/30D defaults; (c) fold the new pages into the existing section or keep them separate; (d) approve the precomputed price/ledger file approach before deploy.

## 4. Implemented on this branch (not merged)
- 30-day cluster and "rapid selling" removed. `product_views`: `promoter_absorption` (net buys minus sells, 90/180/365, `sustained`), `campaigns` (gap <= 90 days, sales netted), `promoter_selling`.
- Noteworthy and Risk Flags use those windows; Promoter Activity and Bulk & Block now offer 90D/180D/365D (default 90D). The 365-day window covers only data from 1 Jan 2026.
- % of equity absorbed stays the market-cap proxy (ESTIMATED): `holding_change_pct` is a relative change in holding, not equity points, so it was not used.
- Still open: precomputed slim price/ledger files, navigation grouping, Evidence page, v2 ledger series.

## 5. Screener, precomputed assets and navigation (branch only, not merged)
- **Promoter Screener** (`pages/1_Promoter_Screener.py`, replaces Noteworthy): horizon 90D/180D/365D/Sustained, min net value (25L-5Cr), min equity absorbed (ESTIMATED market-cap proxy), market-cap bucket (ESTIMATED NSE rank: Large top 100, Mid 101-250, Small 251-500, Micro rest), active-campaign toggle (>= 2 buy days, gaps <= 90 days, last buy within 90 days of the latest data), drawdown from the 52-week high (adjusted closes), purity check (no promoter sales in the window). Output grid with CSV export and a button into Company Deep Dive. Net bulk/block buying moved out (the legacy Bulk & Block page covers deals).
- **Memory.** Pages no longer load the full price table. `scripts/precompute_slim.py` (workflow "Precompute slim assets", dispatch only) writes `artifacts/prices_summary_slim.parquet` (one row per ISIN) and `ledger/ledger_marks.parquet`. Deep Dive reads one ISIN's rows (parquet predicate, one month file at a time) and adjusts that ISIN only; Forward Ledger and Data Health read the derived files. Synthetic check (472k rows, 9 month files): full load +103 MB peak RSS; one-ISIN load +19 MB; cache hit 0.5 ms. Scaled to about 1.1M rows the full load is ESTIMATED at about 240 MB, before pandas copies in the old adjustment path.
- **Legacy selectors restored** to 7D/30D/90D with 90D default on Promoter Activity and Bulk & Block (the nightly archive has no deeper history).
- **Overview and Evidence** show `[Promoter Net: +Rs X Cr (180D) | Active Campaign | Contextual Accumulation]` for companies whose promoters net bought at least Rs 25 lakh over 180 days, joined by ISIN to the clean layer. "Active Campaign" appears only when the campaign rule holds; the badge appears for any net accumulator.
- **Navigation:** three sections (Executive Conviction, Exploration & Screeners, Operations & Audit). Legacy Data Quality kept beside Data Health & Lineage. Confluence caption no longer says "informed entities".
- **Not done:** `promoter_campaign_v2` ledger series (not in the latest directive), results dates, pledges, BSE market cap.

## 6. UI refinement, institutional alignment and ledger v2 (branch only, not merged; PR #15 back to draft)
- **Theme.** Read `Pareshking/Paresh` (design tokens only: `.streamlit/config.toml` and the CSS variables in `src/ui/theme.py`; none of its holdings/watchlist code). Adopted its "Clear Ledger" light palette (indigo `#4F46E5`, page `#F6F7F9`, surface white, bull `#067647`, bear `#B42318`), Geist / Geist Mono, 10px radius, tighter gutters (1.25rem, 0.5rem on phones) and tabular numerals. `streamlit_app/lib/style.py` `COLORS` mirror the same tokens. `showErrorDetails = "none"` is kept (a traceback would expose the R2 endpoint). The temporary clone was deleted. Merging changes the look of the live legacy pages as well (colors and font only; no logic).
- **Trade-hub tables** (`insiders_clean/trade_table.py`): Date | Symbol | Company | Traded By | Category | Mode | Side | Qty | Avg Price | Value (Rs Cr) | % of mcap (est.) | Holding change % | File. Newest first, then largest value; right-aligned numerics; 50-100 row pager. Used on the Screener (selected company), Deep Dive (insider and deal tabs), Evidence & Drill-down and, as a compact HTML table with soft pills, on the Overview feed. **Gap:** the clean data has no post-transaction shareholding percentage (only share counts), so the equity column is the ESTIMATED value / market cap and the holding column is the change in the filer's own holding.
- **Institutional alignment** (`product_views.deal_alignment`): bulk/block net buying (market makers excluded) on deal days inside the latest promoter campaign window, shown on the Screener grid and the Deep Dive. **Gap:** deals carry no reliable FII/DII label, so this says only that large deals coincided, not who traded.
- **Ledger v2** `promoter_campaign_v2` (`ledger.new_campaign_signals`): promoter open-market buy days after 30 Jun 2026 grouped into campaigns (gap at most 90 days); the signal is fixed at the first buy day, from the second on, where cumulative buying net of promoter open-market sales since the campaign start is at least Rs 25 lakh. Id = campaign start, entry convention as v1, later buys never edit the row. Same append-only guard as v1 (v1 rows untouched). The ledger page switches between the two series; both are marked at 60/120/250 sessions against Nifty 500 by the precompute job. Owner-approved on 9 Oct 2026.
