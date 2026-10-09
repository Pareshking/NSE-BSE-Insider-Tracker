# Phase 0 audit (read-only) — 09 Oct 2026

Labels: VERIFIED / ESTIMATED / CLAIMED / HYPOTHESIS. Partial: R2 data and `Pareshking/Paresh` were not reachable from this session (see section 12).

## 1. Architecture and data flow
- VERIFIED (code/docs): nightly GitHub Actions `r2-storage.yml` (cron `0 18 * * 1-5`) collects NSE+BSE (`scripts/nse_*.py`, `bse_*.py`) -> `r2_writer.py` writes raw/canonical to Cloudflare R2 -> `clean_writer.py` merges into `archive/` and rebuilds `clean/current/{insider_trades,deals,securities}.parquet` via `insiders_clean/`. `nse-events.yml` (21:30 IST Mon-Sat) collects SAST Reg 29, corporate actions, board meetings, shareholding/pledge. `history-backfill.yml` is manual.
- All data lives in R2, not git. Repo holds code, fixtures, probe artifacts (~7 MB JSON), `reference_data/security_master_20260901.csv`, and the one-off `stock-screener-01-Sep-2026--1932.xls`.
- The deployed Streamlit app on `main` (`streamlit_app/views/*`) is the old demo; the owner's own README/PRODUCT.md call it wrong. Replacement is draft PR #4 (`feat/ui-shell`).

## 2-4. Sources, assets, weaknesses
- CLAIMED (docs/TODO.md, not re-checked; no R2 access): 07 Oct clean run 6,955 -> 6,174 insider filings; one-year backfill 08 Oct gave 14,478 -> 13,487 insider, 17,421 -> 16,825 deals, 2,367 securities, 57 unmatched.
- VERIFIED: tests pass — 90 passed (`tests` + `streamlit_app/tests`) with the pinned `pandas<3`; with unpinned pandas 3.x, 48 fail (`insiders_clean/dates.py:37` writes to a read-only array). Pin is in `requirements.txt`; `pandas` 3 breakage is a latent upgrade risk.
- Worth preserving: `insiders_clean/` (cleaning, archive, calendar, entities, dedup by content), `collectors/nse_events`, backfill runner, tests/fixtures with real filings, security master logic.
- Weaknesses found:
  1. VERIFIED (code `r2_writer.rows_to_parquet_bytes`, CLEAN_LAYER.md): intraday round-trip deals are dropped at ingestion (6,460 of 14,844 backfilled = 43.5%, CLAIMED count). This breaks the "immutable raw layer / exclude per analysis" rule (§9.1, §10).
  2. Revision handling is content-based because `nse_insider.py` does not capture `prevAppId`/`typeOfSubmission` (TODO #14).
  3. Market cap in signal calibration is the 06 Oct 2026 value, not point-in-time (docs/SIGNALS.md) — look-ahead for older trades.
  4. `needs_review` thresholds (25% of market cap, 20x holding) are hand-set literals.
  5. NSE block deals reported BLOCKED in nightly on 07-08 Oct (TODO #18, unresolved).
  6. `.gitignore` ignores `*.csv`, yet `security_master_20260901.csv` is tracked (forced add); the xls is a single dated snapshot and must not be used as history (used for sector/industry only, per docs).
  7. Many one-off probe workflows/scripts (v1–v4 validation, bse_*probe) are clutter; `data-validation.yml` and `acquisition-probe.yml` FAIL on every push to main (runs 37679757328, 37679757292); `acquisition-probe.yml` has `contents: write` and pushes to main.
  8. README (main) references `scripts/dev_ui.py`, which does not exist on main — VERIFIED by `git ls-files`.

## 5. Branches / PRs
- PRs #1–#3, #5–#10 merged. #4 open draft (`feat/ui-shell`, head ba22bc7; Tests and Site-preview runs green on that head; TODO says needs rebase on main).
- Remote branches (16): all but `main`/`feat/ui-shell` are merged or old: `bse-validation-fix`, `claude/css-injection-fix-e8sl63`, `claude/insider-analytics-audit-e8sl63`, `claude/nse-bse-pipeline-handover-9w6oms`, `nse-validation-loop`, `run-phase1-phase2-probe` — NOT yet classified (unread; HYPOTHESIS: abandoned/duplicate). No deletions proposed without your approval (gate 3).

## 6. Deployment
- VERIFIED: `https://insiders.streamlit.app/` returns HTTP 303 to Streamlit's auth page — the app is not anonymously reachable (access already restricted; who is on the allow-list was not checked).
- Entrypoint `streamlit_app/app.py`, Python 3.11 (`runtime.txt`), `.streamlit/config.toml` hides error details. Deployed branch: NOT determinable from git (probably `main`; every merge to main redeploys). **Question for you.**
- Streamlit Community Cloud limits: not yet fetched from official docs (to do in Phase 1 pre-work).

## 7. Prices / market cap
- CLAIMED (docs/TODO.md G): Paresh public release `data-latest` has adjusted closes for 1,419 NSE symbols, OHLCV 2026, `bse_daily.parquet`. Coverage vs our events and adjustment status UNVERIFIED: `Pareshking/Paresh` is not accessible from this session (GitHub API denied, github.com 403). The trading calendar is already seeded from it (CLEAN_LAYER.md).
- Market-cap history: `nse_market_cap`/`bse_market_cap` collectors exist; point-in-time depth unverified.

## 8. Sample size and power — ESTIMATED, not computed
Cannot measure forward-return windows without R2/price data. Rough reasoning: 1 Jan–9 Oct 2026 is ~190 trading days; the 250-day horizon has zero complete windows, 120-day only events before ~April. Open-market promoter buys per CLAIMED docs: ~320 "spotlight-sized" per year, ~496 promoter buys in >Rs5,000 Cr companies. With one regime and heavy event clustering, expected minimum detectable effect at 20–60 days is large (several % abnormal return). HYPOTHESIS: 2026-only cannot validate any signal; only gross short-horizon (5–20d) effects on the pooled open-market-buy set are testable. I will quantify once data is readable.

## 9. Questions answerable now vs not
- Now (descriptive): disclosure lags, categories mix, dedup/revision rates, deal churn, data quality.
- Not yet: any return claim at 60d+; marquee-investor effects; pledge-release effects; regime dependence.

## 10. Proposed target architecture (evolutionary, not rewrite)
Keep pipeline + `insiders_clean/`; change: (a) store never-dropped raw deals, move churn filtering to the clean layer; (b) add point-in-time price/market-cap + bhavcopy layer (official NSE archives preferred over Paresh as sole source; Paresh as optional read-only); (c) new `research/` package: event study, calendar-time portfolios, pre-registration in RESEARCH.md; (d) append-only forward ledger (parquet in R2, mirrored summary); (e) finish PR #4 UI as staging. Alternatives rejected: full rewrite (existing cleaning is tested and calibrated); DuckDB-in-git (public repo, growth).

## 11. Staged plan
P1 data foundation (raw-preserve fix, revision fields, bhavcopy, PIT market cap, data-health) -> P2 evidence -> P3 UI on staging branch -> P4 reconciliation + cut-over (gate 7) -> P5 runbook.

## 12. Contradictions, risks, decisions needed
1. **Scope contradiction (gate 5):** the backfill ingests 8 Oct 2025 onward (PR #9, "one year", owner 08 Oct), but this prompt says product data starts 1 Jan 2026 and pre-2026 disclosures are NOT permitted. The archive therefore already holds ~3 months of pre-2026 disclosures. Decide: (a) keep them in the archive but filter the product to >= 2026-01-01 (my recommendation: separate storage, research-only), or (b) purge.
2. Deployed branch? Who is on the Streamlit viewer allow-list?
3. R2 read-only credentials for this session (gate 6/4) so I can inventory real data; and approval path for reading `Pareshking/Paresh` (public release `data-latest` is blocked here; needs add_repo/read access).
4. Approve deleting/renaming stale branches and probe workflows? (gate 3) — nothing touched.
5. Failing `data-validation` / `acquisition-probe` workflows: fix or retire?
6. Risk: public repo — no holdings/watchlists committed; keep it that way.

## Not done in Phase 0 (honest gaps)
Contents of 6 stale branches; official Streamlit limits; source terms; regulation texts and literature (Phase 1/2 RESEARCH.md); live data inventory and power numbers; BSE docs (`BSE_*.md`, `PROJECT_PLAN.md`, `DATA_ACQUISITION.md`) skimmed by name only.

---
## Addendum 09 Oct 2026 — Paresh price data (read-only, public clone + `data-latest` release)

Method: shallow clone of `Pareshking/paresh` (HEAD c4e68e7, 2026-10-09) and the three public `data-latest` release files, inspected locally. Nothing written to that repo. Coverage below is against our **security master of 01 Sep 2026 (5,287 securities)**, NOT against actual 2026 disclosures — event-level coverage still needs R2 (credentials not yet in session).

- VERIFIED `nse_long_close.parquet`: wide table, 4,647 dates (2008-01-01 to 2026-10-06) x 1,419 NSE symbols, float32 closes; 1,245 symbols have data in 2026. Names say "adjusted"; adjustment method (splits/bonuses via `data/nse_prices/actions.parquet`, 109 actions in the repo copy) is CLAIMED, not independently checked. Symbol renames are tracked in `data/nse_prices/notes.json`.
- VERIFIED `ss_prices_2026.parquet`: 251,154 rows, 1,375 symbols, 2026-01-01 to 2026-10-08, OHLC as **int32** (sample closes 21208, 21430: looks like paise x100, HYPOTHESIS, must be confirmed before use) plus volume.
- VERIFIED `bse_daily.parquet`: 15.4M rows, 2008-01-01 to 2026-10-07, columns date, code, name, group, OHLC, prev_close, trades, shares, value, isin; 928,560 rows in 2026. Adjustment status unknown (UNVERIFIED).
- ESTIMATED coverage vs master: NSE symbols present with 2026 adjusted close 1,184 of 3,116 (38%); in `ss_prices` 1,326 (43%). BSE daily by ISIN: 4,574 of 5,287 (86.5%); of the 2,171 securities without an NSE symbol, 2,160 are in `bse_daily`.
- Implication (ESTIMATED): the adjusted-close table alone misses most of the universe (the NSE-750-style gap predicted in the prompt). `bse_daily` fills most gaps but needs a corporate-action adjustment layer. Recommendation: build our own PIT price layer from official NSE/BSE bhavcopy archives plus corporate actions; use Paresh files only as an optional cross-check.
- The security master carries Value Research ratings/scores as of 01 Sep 2026 (single snapshot): must never feed point-in-time features.
- Still open: R2 inventory, event-level price coverage, forward-window counts, power numbers.
