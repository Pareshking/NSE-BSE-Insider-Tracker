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

---
## Addendum 09 Oct 2026 — R2 inventory and power (Actions run 37902086767, commit d98522a; VERIFIED = read from R2 by the workflow)

Aggregate output only. Prices for the windows are Paresh's public adjusted-close table (a proxy; NSE symbols only), to 2026-10-06.

**Archive (rows / date range / before 2026 / 2026 onward / round-trip flagged)**
| dataset | rows | date range | <2026 | >=2026 | RT flagged |
|---|---:|---|---:|---:|---:|
| nse/insider_trading | 12,370 | 2015-10-24 .. 2036-02-03 | 3,188 | 9,182 | n/a |
| nse/bulk_deals | 20,269 | 2025-10-08 .. 2026-10-08 | 5,572 | 14,697 | 6,460 |
| nse/block_deals | 1,732 | 2025-10-08 .. 2026-10-01 | 443 | 1,289 | 0 |
| bse/insider_trading | 2,174 | 2015-05-15 .. 2026-10-08 | 19 | 2,155 | n/a |
| bse/bulk_deals | 1,822 | 2026-09-01 .. 2026-10-08 | 0 | 1,822 | n/a |
| bse/block_deals | 206 | 2026-08-31 .. 2026-10-08 | 0 | 206 | n/a |

- VERIFIED: bulk redo (run 37901034740) added 6,460 rows (13,809 -> 20,269), all flagged `intraday_round_trip`; block redo (run 37901379384) added 0. The NSE insider archive holds dates up to 2036 (mistyped by filers; 0 unreadable).
- VERIFIED bug found and fixed (d98522a): the archive stores a flag column with gaps as text, so `astype(bool)` made every row "flagged" (14,841 of 20,269 on the first post-redo inventory). `as_flag()` now reads only explicit true; flags stay boolean in the archive.
- VERIFIED: bucket top-level prefixes are cache, canonical, clean, manifests, raw, reference (no `raw_v2` yet).
- Clean tables currently in R2 (built by `main` code before the product window): insider_trades 13,553 rows (3,341 dated before 2026), deals 16,958 (3,426 before 2026). Hazard: until this branch merges, the nightly clean on `main` ignores the flag, so `clean/deals` will include the 6,460 recovered round-trip legs. The old live app does not read that table.
- CLAIMED (script docstring, not measured): the nightly bulk/block collectors fetch one day per call and the endpoint caps a call at 70 rows, so a day with >70 deals loses its tail. The backfill's CSV endpoint has no such cap. Recommend moving nightly deals to the CSV endpoint.
- Nightly raw capture (scripts/raw_capture.py + raw_flush.py, step in r2-storage.yml) is unit-tested but NOT yet exercised in production (the nightly runs from `main`).

**Forward windows (2026 open-market, primary, not held back; entry = first session after broadcast date)**
| side | events | with price history |
|---|---:|---:|
| buy | 3,260 | 927 (28%) |
| sell | 2,013 | 1,356 (67%) |

Buys: horizon (sessions) -> complete events / companies / company-months / abnormal sd / MDE by events / MDE by company-months
- 5 -> 870 / 153 / 267 / 5.4% / 0.5% / 0.9%
- 20 -> 770 / 142 / 244 / 10.5% / 1.1% / 1.9%
- 60 -> 651 / 126 / 199 / 18.2% / 2.0% / 3.6%
- 120 -> 520 / 111 / 153 / 23.5% / 2.9% / 5.3%
- 250 -> 0 complete windows

Sells: 5 -> 1,274 / 149 / 312 / 5.2% / 0.4% / 0.8%; 20 -> 1,096 / 137 / 278 / 9.6% / 0.8% / 1.6%; 60 -> 683 / 111 / 191 / 19.8% / 2.1% / 4.0%; 120 -> 387 / 71 / 105 / 23.7% / 3.4% / 6.5%; 250 -> 0.

ESTIMATED reading: MDE = (1.96+0.84) x sd / sqrt(n), 5% two-sided, 80% power; "company-months" is a deliberately conservative effective n for clustered events (the by-events figures assume independence, which they are not). abnormal sd is vs the median stock, a crude benchmark. So with 2026 data alone: a ~1-2% abnormal return is detectable at 5-20 sessions, ~4-5% at 60-120 sessions, nothing at 250. Only 28% of buy events have price history in this proxy, so these are lower bounds on the sample the native price layer should give. Single market regime; no hold-out period yet exists. Conclusion: short-horizon (5-20 session) pooled tests are feasible now; any claim at 60+ sessions, or about subgroups (promoter vs director, size buckets), is underpowered.

## Addendum 3 (09 Oct 2026, 17:00 IST): native price layer coverage (VERIFIED from the final coverage run)

Source: NSE and BSE UDiFF bhavcopy plus NSE's daily `mcap` file, 1 Jan 2025 to 8 Oct 2026, raw bytes first in `raw_v2/`.

| Measure | Result |
|---|---|
| Price days stored | NSE 437 of 437, BSE 437 of 437 (100%); 3.48 million rows |
| Market-cap days stored | 437 of 437 (1.21 million rows) |
| Raw preserved | 0 stored days without a raw file (BSE holds 453 raw days: extra days are holiday/home-page responses stored as received) |
| 2026 insider events with an entry price | 9,918 of 9,990 with an ISIN (99.3%) |
| Insider events with history of at least 5 / 20 / 60 / 120 / 250 sessions | 9,901 / 9,840 / 9,626 / 9,529 / 8,879 of 9,990 |
| 2026 deal events with an entry price | 16,949 of 17,318 with an ISIN (97.9%) |
| Deal events with history of at least 5 / 20 / 60 / 120 / 250 sessions | 15,841 / 14,996 / 14,439 / 13,769 / 11,629 of 17,318 |
| Events in securities with no NSE price | 570 insider, 1,538 deal (BSE price used where it exists) |
| Split / bonus / consolidation resets found | 65 (59 NSE, 6 BSE); 1,531 other large resets counted, not applied; 12,657 minor (mostly dividends), not applied |
| BSE resets for NSE splits | BSE showed the same reset on only 1 of 56 NSE split days both traded: BSE's previous-close does NOT reset on splits |

Consequence (decision in `docs/DECISIONS.md`): dual-listed securities inherit the NSE split/bonus factor onto the BSE series; BSE-only securities keep raw prices and are flagged, since BSE's own previous close cannot be relied on to show splits. Deals rose to 17,701 events after the recovery backfill and clean rebuild (was 16,861).
