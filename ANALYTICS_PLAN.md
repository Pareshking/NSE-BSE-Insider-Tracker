# Analytics & Redesign Plan

Status: DRAFT -- for discussion, not yet fully approved. This is the single
current to-do list for the frontend redesign. It supersedes ad-hoc chat
decisions; update this file when scope changes instead of re-deciding in
chat. Background/rationale for *why* a signal-finding layer is needed at all
(vs. mirroring NSE/BSE) is in `PROJECT_PLAN.md` and `FRONTEND_PRODUCT_SPEC.md`
-- this file is the concrete, current build plan.

## Why we're here

The app currently shows the same raw filings NSE/BSE already publish, styled
like a spreadsheet. That's redundant -- nobody needs a second copy of NSE's
own bulk-deals page. The only reason to exist is to surface things a human
scanning either exchange's site wouldn't quickly notice:

1. **Aggregation** -- ten small daily buys by one promoter are the same
   signal as one large purchase, and today they're invisible as a pattern.
2. **Materiality** -- a given ₹ or share number means completely different
   things depending on the company. **This was missing from the original
   plan and is now a first-class requirement.**

## Materiality normalization (new, not yet built)

Concrete example from the discussion: promoter of Company A sells 1 lakh
shares; promoter of Company B also sells 1 lakh shares. Company A's market
cap is ₹100 Cr, Company B's is ₹1,000 Cr. Same share count, same rupee value
maybe -- wildly different signal. A's promoter just sold a chunk of a small
company; B's promoter sold a rounding error. Absolute numbers alone hide
this. Every ranked/sorted view needs a size-relative metric, not just
absolute ₹/shares.

**Primary metric:** transacted value as a % of company market cap
(`canonical_value / market_cap`). Show it alongside the absolute number, and
make it a sortable column -- "biggest % of market cap moved" is arguably a
more useful default sort than "biggest ₹ amount" for spotting real signals
in small/mid caps.

**Secondary metric -- out of scope, not planned.** % of the promoter's own
disclosed shareholding (SEBI shareholding-pattern data) was considered and
explicitly rejected for now: not required, not part of Phase 0.5 or any
later phase currently planned. Market cap % is the only materiality metric
being built.

**Data gap -- this is new scope, not a config change.** We do not currently
fetch or store market cap / shares-outstanding / free-float for any company.
Existing `canonical_*` fields have no such column. To compute the primary
metric we need a new, small reference-data source:

- NSE: `/api/quote-equity?symbol=X` (or the equivalent used by
  `market-data/live-equity-market`) returns `securityInfo`/`priceInfo` with
  issued size and last price -- market cap = issued size × last price.
- BSE: scrip master / quote API has an equivalent (needs the same kind of
  live-diagnostic verification we did for NSE bulk deals before trusting an
  endpoint -- do not assume a candidate endpoint is real without capturing
  what the live BSE page actually calls).
- This is symbol/company-level reference data, not transaction-level -- it
  changes slowly (daily price move, near-static share count) and doesn't
  need every-run freshness. A once-daily fetch keyed by symbol/ISIN, cached
  and joined onto canonical rows at read time (or written as its own small
  R2 object, e.g. `reference/market_cap/{date}.json`), is enough.
- Scope: one new acquisition script per exchange (or one combined script if
  the endpoints are similar enough), one new `r2_writer.py` category, one
  join in the Streamlit data layer. Not a large build, but it is a real
  pipeline addition with its own certification/validation questions (what
  does "VERIFIED" mean for a reference dataset that isn't a transaction
  list?) -- needs the same rigor as any other data source before being
  trusted in a ranked view.

**Correction (2026-09-01, after re-reading the repo more carefully):** the
VR-sheet ingestion described below as future work is **already done**.
`reference_data/security_master_20260901.csv` (5,287 rows: ISIN, NSE
symbol, BSE scrip code, company, sector, industry, `mcap_category`) is
the already-extracted, already-committed result of that same
`stock-screener-01-Sep-2026--1932.xls` file, and `scripts/r2_writer.py`
already uses it (`load_security_master()`/`resolve_isin()`) as the primary
key for cross-exchange same-event matching. **Phase 0.5 does not need to
build the symbol crosswalk -- it already exists.** The only genuinely new
work is the numeric market-cap fetch + join described below.

**Data sources confirmed (2026-09-01), replacing guesses with real inspection:**

- `reference_data/security_master_20260901.csv` (see correction above) --
  3,116 rows have an NSE code, 4,581 have a BSE code (`bse_scrip_code` is
  null for 706, `nse_symbol` null for 2,171 -- real, not a defect, not
  every security is cross-listed). Gives sector/industry and a coarse
  `mcap_category` (Small/Mid/Large bucket only -- **not** a ₹ figure)
  immediately, but not precise market cap.
- `jugaad-data` (PyPI, NSE-only, actively maintained, already handles
  NSE's session/anti-bot dance so we don't reverse-engineer it ourselves
  again): `NSELive().stock_quote(symbol)` returns `securityInfo.issuedCap`
  (shares issued) and `priceInfo.lastPrice` in one call -- market cap =
  issuedCap x lastPrice, computable per NSE symbol. Confirmed via its
  docs, not yet tried against the live API from this environment. No BSE
  support at all, no ISIN/BSE-code fields.
- **Combined plan:** join the VR sheet's NSE Code onto our canonical rows
  to get symbols, call `jugaad-data` per unique NSE symbol for precise
  market cap, and fall back to the VR sheet's `Mcap Category` bucket where
  no NSE code/live quote exists (BSE-only names) -- ship with the coarse
  bucket for those rather than blocking on a full BSE market-cap source.
  A real numeric BSE market cap source is a later, separate investigation
  (needs the same live-diagnostic verification as everything else BSE) --
  not blocking Phase 0.5.
- Also usable later, same library: `jugaad_data.nse.stock_df()` /
  bhavcopy for historical NSE OHLC -- the missing piece for the
  price-correlation idea below, if that gets scoped.

**Decided:** Phase 1 (Promoter Activity) ships now with absolute ₹/shares
-- it's already built and smoke-tested. Market cap % lands as **Phase 0.5**,
before Phase 2 (Bulk/Block Concentration) starts, so that page launches with
materiality built in from day one instead of retrofitted. Promoter Activity
gets the market-cap % column added once Phase 0.5 lands.

## Visual / formatting (cross-cutting, applies to every page)

- No raw `canonical_*` names in any user-facing table -- human column
  headers everywhere (`st.column_config` for native tables, explicit
  `<th>` labels for custom HTML tables).
- Dates: consistent human format across the whole app (e.g. `31 Aug 2026`,
  not a mix of ISO strings and native filing formats). Pick one format,
  apply everywhere, including inside custom HTML tables and chart hover
  text.
- Every trend gets a real chart (Plotly, already added as a dependency),
  not a bare number -- sparklines in rollup rows, proper line/bar charts on
  detail views. No more relying on `st.dataframe`'s built-in formatting for
  anything analytical.
- Benchmark look-and-feel against Bloomberg-terminal-style / institutional
  quant-portal density: information-dense but not spreadsheet-y --
  consistent spacing rhythm, monospace tabular numerals for all numeric
  columns, restrained color coding (green/red already established for
  buy/sell), no default Streamlit table chrome.
- Full spacing/type audit against the published mockup's design tokens
  (`lib/style.py`'s `COLORS` already matches it) once page structure below
  is settled -- do this as a pass per page, not a separate blanket task.

## Requirements check against existing docs (2026-09-01)

User asked to check whether "other quantitative platform requirements"
(alerts, peer/sector comparison, price correlation, screener) are already
covered by `PROJECT_PLAN.md`/`FRONTEND_PRODUCT_SPEC.md`/
`FRONTEND_UI_BLUEPRINT.md`. Checked directly rather than assumed:

| Requirement | Status in docs |
|---|---|
| Search / advanced filters / export of filtered data | **Specified** (`FRONTEND_PRODUCT_SPEC.md` global filter bar, table export) |
| Rolling 7/30/90/365-day views | **Specified** (`PROJECT_PLAN.md` §13) -- what Promoter Activity builds toward |
| "Alerts" nav item in the blueprint | **False friend** -- scoped explicitly to data-quality/pipeline alerts ("BSE session blocked"), not investment-signal alerts. Don't assume this box is checked for a "notify me when promoter X crosses threshold" feature. |
| Peer / sector comparison | **Not specified anywhere** |
| Price-correlation overlay (stock price vs. insider activity) | **Not specified** -- only a vague "potential future correlations" list with an explicit correlation-is-not-causation warning, no design. Needs a real price-history data source we don't have yet (candidate: `jugaad-data` bhavcopy, NSE-only, above). |
| Investment-signal alerts/notifications | **Not specified** |
| Market-cap materiality | **Not specified anywhere** (confirmed zero mentions) -- this is genuinely new, not something we lost track of |

**Discussed and decided (2026-09-01):** effort ordering is Phase 6 <
Phase 8 < Phase 7, not the order originally listed:

- **Phase 6 (peer/sector comparison)** is cheapest -- rides entirely on
  Phase 0.5's market-cap data plus the VR sheet's Sector/Industry columns
  (already have both, no new external source). E.g. sector median net-buy
  vs. one company's net-buy, as a percentile/rank.
- **Phase 8 (investment-signal alerts)** is medium -- architecturally
  different from the other two (a background pipeline step, not a page):
  evaluate a committed watchlist/rule config at the end of the existing
  daily GitHub Actions run, deliver to one channel (email/Telegram).
  Single-user scope is correct here -- no accounts/auth exists or is
  worth building for one user.
- **Phase 7 (price-correlation overlay)** is heaviest -- needs a data
  source we don't have at all (daily OHLC price history, not deal-level
  data; candidate `jugaad-data` bhavcopy, NSE-only, same BSE gap pattern
  as market cap) plus real historical backfill, which `PROJECT_PLAN.md`
  §12 already lists as unfinished for every dataset, not just this one.

Decision: keep all three deferred/unscoped for now. Stay focused on
Phase 0.5 -> Phase 2 -> Phase 3 first; revisit 6/8/7 (in that effort
order) after.

## Full blueprint re-read findings (2026-09-01)

User asked to check whether `FRONTEND_UI_BLUEPRINT.md` had more detail on
what was originally supposed to be displayed. It does -- the earlier check
of this file was keyword-grep sampling, not a full read. Real gaps found,
now decided:

**Pulled into the near-term roadmap (user confirmed all of these):**

- **Trends & Charts module** (blueprint §16) -- daily/weekly/monthly event
  count, buy vs. sell, transaction value, category mix, across *all five*
  categories combined. Distinct from Promoter Activity's per-row
  sparklines -- this is a whole-market trend view. No new data source
  needed (uses existing canonical data across categories).
- **Downloads / export** (blueprint §18) -- CSV/JSON export of the
  currently filtered dataset, with metadata (exchange, category,
  requested/actual range, extraction timestamp, validation state, applied
  filters). Nothing like this exists yet on any page. Cheap, no new data
  source, applies to every page with a table.
- **Richer Rights/Preferential lifecycle UI** (blueprint §11-12) -- the
  blueprint specifies an explicit stage timeline (Announcement -> Record
  Date -> Ratio/Price -> Issue Open/Close -> Entitlement -> Allotment ->
  Listing/Trading Approval) with a detail drawer showing full stage
  history, not just a status field. This upgrades Phase 3's description
  below -- do this design work before Phase 3 build starts, not after.
- **Global search** (blueprint §3, §19) -- Cmd/Ctrl+K, searches
  company/symbol/ISIN/person/client/promoter category across all
  categories, grouped results. Pure navigation UX, no new data source.
  Streamlit has no native command-palette primitive -- will need a custom
  component or a workaround; not yet investigated how.
- **Validation & Evidence audit centre upgrade** (blueprint §15) -- current
  Data Quality page (`streamlit_app/views/data_quality.py`) is much
  thinner than spec: it has a certification matrix + known limitations +
  security-master snapshot info, but none of the blueprint's `Runs |
  Source Comparison | API Evidence | Schema | Duplicates | Coverage |
  Errors` tabs, and no `Discovered -> Integrated -> Tested -> Validated`
  state distinction for endpoints. **Decided (2026-09-01):** the pipeline
  writes its own run-summary JSON to R2 at the end of each GitHub Actions
  run (workflow name, commit, status, timing, artifact links) -- the
  frontend reads it the same way it reads everything else, no GitHub
  token in the public Streamlit app. Implementation needs: (1) a new step
  at the end of the acquisition/validation/r2-storage workflows writing
  e.g. `runs/{date}/{workflow}.json`, (2) a new "Runs" tab reading it.
  Not yet built.

**Removed entirely (2026-09-01):**

- **API Documentation / external API** (blueprint §4 sidebar item) --
  decided out of scope, not just deferred: there are no external
  consumers of this data and none are planned. If the frontend itself
  ever needs a documented internal contract, that's covered by the
  existing `lib/r2_data.py` module + `PROJECT_PLAN.md`'s
  backend-to-frontend contract fields, not a separate API/docs product.
  Not on the roadmap in any form.

**Noted, deliberately not pulled forward:**

- Accessibility (WCAG 2.2 AA), performance targets, staged loading
  messages, mobile-specific layout, empty/error-state richness (blueprint
  §24-30) -- real, documented requirements, but engineering/UX hygiene
  rather than "quantitative platform" content. Not tracked as a phase;
  revisit once the page set stabilizes.
- Indian digit-grouping for raw currency values (`₹1,23,45,678`, blueprint
  §22) vs. our current `fmt_inr()` fallback which uses US-style grouping
  for values under ₹1,000 -- a small, concrete formatting bug. Folded into
  the existing "Visual / formatting" cross-cutting section above, not a
  separate phase.
- "Top Companies" cross-category ranking (blueprint §16) -- likely the
  same thing as the already-planned Phase 4 Signals home page (which pulls
  top-ranked items from Phases 1-3 into one ranked front door). Treated as
  the same deliverable, not a new one, unless it turns out Phase 4 doesn't
  cover the cross-category blend the blueprint describes.

## Page structure

Revised sequence after the full blueprint re-read (2026-09-01) -- items
pulled forward this round are marked **NEW**.

| Page / deliverable | Status | Notes |
|---|---|---|
| Overview | Live, redesigned | Certification/status home -- KPIs, latest activity, coverage. Not a signal page. |
| **Promoter Activity** | **Built, smoke-tested, market cap joined** | Net-position rollup, both grains (per person+company, per company), no threshold, sortable by \|net value\| or by \|% of market cap\|. Still needs: full column/date-format audit pass. |
| Phase 0.5: Market cap join | **Shipped, both exchanges** | NSE: PR bhavcopy zip, whole market, one request, ~2,301 EQ-series symbols in ~1.8s. BSE: `bse.BSE().listSecurities()` across all 24 groups, official pre-computed `Mktcap` field, ~4,685 scrips in ~15-20s. No per-symbol lookups on either side (see correction below) -- combined into one `reference/market_cap` write. |
| **NEW** Downloads / export | Not started, cross-cutting | CSV/JSON export + metadata, applies to every table page. Cheap, no new data source -- do this early, right after Phase 0.5, since every later page benefits from it existing. |
| Phase 2: Bulk & Block Concentration | Not started | Top clients by volume per security, largest-transactions view, concentration metric. Ship with materiality (% of market cap) from the start. |
| **NEW** Phase 2.5: Trends & Charts | Not started | Whole-market daily/weekly/monthly event count, buy vs. sell, category mix across all 5 categories. No new data source. |
| Phase 3: Rights & Preferential Pipeline | Not started | **NEW: upgraded design** -- explicit lifecycle timeline (Announcement -> Record Date -> Ratio/Price -> Issue Open/Close -> Entitlement -> Allotment -> Listing) with full stage-history detail drawer, per blueprint §11-12, not just a status field. BSE `in_principle_status`/`listing_stage_date` still need live re-verification before trusting in UI. |
| Validation & Evidence upgrade | Not started | Expand Data Quality into blueprint §15's audit centre (Runs/Source Comparison/API Evidence/Schema/Duplicates/Coverage/Errors tabs). "Runs" data source decided (2026-09-01): pipeline writes its own run-summary JSON to R2, no GitHub credentials in the public app -- see decision above. |
| Phase 4: Signals (home) | Not started | Ranked cross-page front door, pulls top items from Phases 1-3 -- also intended to cover the blueprint's "Top Companies" cross-category ranking (insider + bulk/block blended). Replaces Overview as default landing page once it exists. |
| **NEW** Global search | Not started, sequence after Phase 4 | Cmd/Ctrl+K across companies/persons/ISIN, grouped results. Needs the page set to stabilize first since results link into pages; Streamlit has no native command-palette primitive, implementation approach not yet investigated. |
| Cross-exchange correlated signals | Deferred (Phase 5) | Depends on the still-partial cross-exchange matcher -- already helped by the existing `security_master` ISIN crosswalk. |
| Peer / sector comparison | Deferred (Phase 6, unscoped) | Rides on Phase 0.5 + existing Sector/Industry columns once scoped. |
| Price-correlation overlay | Deferred (Phase 7, unscoped) | Needs a price-history source (candidate: `jugaad-data` bhavcopy, NSE-only) plus historical backfill. |
| Investment-signal alerts/notifications | Deferred (Phase 8, unscoped) | Distinct from the existing data-quality "Alerts" nav item. |
| Evidence & Drill-down | Live, renamed from "Transactions" | Raw per-transaction view with source fields -- kept, demoted from top-level signal page to drill-down destination. |
| Data Quality | Live, unchanged | Kept as-is. |

## Immediate next steps

**Phase 0.5 shipped (2026-09-01): market cap join, real numbers, both grains.**

What actually got built, in the order it was found, since the plan changed
twice as real data came in:

1. First version called `jugaad-data`'s `NSELive().stock_quote()` once per
   NSE symbol -- worked (verified live against RELIANCE/ZYDUSLIFE/
   20MICRONS), but ~638 individual calls for one day's activity (~18 min),
   more anti-bot exposure than necessary.
2. User pointed at `github.com/Pareshking/Paresh` (a sibling project),
   which already solves this with NSE's Bhavcopy "PR" zip -- a different,
   older report format than the sec_bhavdata_full/UDIFF bhavcopy variants
   (confirmed those do NOT carry market cap by inspecting both directly).
   One request covers ~2,300-3,100 EQ-series stocks with an official,
   pre-computed `Market Cap(Rs.)` column. That project's own history
   documents months of believing NSE blocks this fetch from CI, which
   turned out to be a logging bug silently discarding a successful parse
   -- the same shape of mistake as this project's own bulk-deals
   "IP block" theory. Treat any future "NSE is blocking us" claim with
   the same suspicion.
3. Real coverage check against this run's actual 638 needed symbols: the
   PR zip covered 475 (74%) -- the gap is SME/micro-cap-board names that
   bulk deals frequently include and NSE's mainboard archive doesn't
   track. No SME-equivalent bulk file was found (two guessed URLs both
   404'd, not chased further -- this project's own rule against trusting
   a guessed endpoint shape). Final design: PR zip first (whole market,
   one request), `jugaad-data` per-symbol fallback only for the ~163
   symbols the zip doesn't cover. `scripts/nse_market_cap.py`.
4. Certification question resolved: rather than force a reference dataset
   through the transaction-data VERIFIED/BLOCKED gate (which would have
   silently corrupted the Overview page's "NSE certified" badge -- that
   badge's `all(status == VERIFIED for nse entries)` logic doesn't know
   the difference between a certification failure and an unrelated
   reference dataset), market cap gets its own `manifest['reference_data']`
   list, entirely separate from `manifest['datasets']`. See
   `write_market_cap()` in `scripts/r2_writer.py`.
5. Joined onto Promoter Activity (both grains): `% of market cap` column,
   plus a sort-basis toggle (`% of market cap` / `Absolute ₹ value`) --
   verified against realistic test data that a small company's smaller
   absolute move (STEL's Rs.8.40L) correctly outranks a large company's
   bigger absolute move (Zydus's Rs.6.83Cr) when sorting by materiality,
   which is the entire point of this phase.
6. **BSE gap closed same day.** User pointed at BSE's own "List of Listed
   Companies" utility as a workaround (bhavcopy price x a shares-outstanding
   master). Before building that two-step join, checked what the `bse`
   package (already a dependency) exposes: `BSE().listSecurities(group=...)`
   already returns an official, pre-computed `Mktcap` field (Rs. Crore) --
   same shape of finding as NSE's PR zip. No two-step join needed. One call
   per BSE group (24 groups, no bulk "all" endpoint) resolved ~4,685 scrips
   in ~15-20s. `scripts/bse_market_cap.py`, merged into the same
   `reference/market_cap` write as NSE's (safe: NSE alpha tickers and BSE
   numeric scrip codes never collide in one lookup keyed by symbol).
7. **Fixed a real performance bug, confirmed with timed before/after runs.**
   The NSE per-symbol fallback (step 3) ran sequentially with a 0.5s sleep
   between calls. Flagged by the user as suspiciously slow compared to the
   reference project's "super fast" NSE path; the actual cause was never
   comparing against the reference repo's own fallback design, which runs
   8 concurrent workers (`ThreadPoolExecutor`) for the exact same kind of
   one-request-per-symbol problem. Parallelizing alone brought a full run
   from timed-out-at-300s down to ~3.5 minutes -- better, but still slow
   for 163 symbols at 8-way concurrency. Looking at the actual failures
   explained why: **160 of 163 fallback symbols failed** (only 3 net new
   beyond the PR zip's 475), split between an `'equityResponse'` KeyError
   raised inside jugaad-data itself and a plain "no market cap field in
   the response" -- both deterministic per symbol, not transient network
   blips, so the 2-retry-with-2s-backoff default was purely paying a
   repeat-failure tax with zero chance of succeeding on retry. Dropped to
   0 retries (kept as a parameter, not removed as a concept): timed at
   **37.6s** for the identical 478/638 resolved -- same correctness, ~5.6x
   faster than the parallelized-with-retries version, ~10x faster than
   the original sequential-with-sleep version.
8. **User's final correction, same day: drop the per-symbol fallback
   entirely, not just its retries.** Given the fallback rescued only 3
   symbols out of 163 attempts, and given "a stock is only listed on the
   other exchange" is a real, acceptable limit rather than something to
   patch with individual searches, `scripts/nse_market_cap.py` now just
   dumps the whole PR zip's EQ-series universe every run (same shape as
   `bse_market_cap.py`) -- no `collect_symbols()`, no per-run dependency
   on `nse_insider`/`nse_bulk`/`nse_block` having already run, no
   `jugaad-data` dependency at all (removed from `requirements.txt`).
   Result: **1.8 seconds**, and broader coverage too (the full ~2,301-symbol
   universe, not just the ~638 symbols a given day happened to need).
   Both `*_market_cap.py` scripts are now fully independent of every
   other acquisition step and of each other -- moved to the front of
   `r2-storage.yml`, BSE before NSE per explicit ordering preference.
9. Wired both NSE and BSE market cap into the daily pipeline as their own
   steps in `r2-storage.yml`.
10. **User asked directly: does the combined market cap now resolve
    everything? Checked rather than assumed -- no.** 163 of 638 real
    NSE-transacting symbols (that day's insider+bulk data) still had no
    market cap: NSE's PR zip only covers ~2,301 EQ-series symbols, missing
    SME/micro-cap-board names. But checking further found real, free
    upside: 41 of those 163 (436 in the full universe) ARE cross-listed
    on BSE with a resolvable BSE market cap -- previously wasted because
    the merge only matched a symbol against its OWN exchange's rows, not
    the other exchange's, even though the ISIN crosswalk to make that
    match already existed (`load_security_master()`, already used for
    cross-exchange transaction matching). Added
    `cross_exchange_alias_rows()` to `r2_writer.py`: for a symbol missing
    from its own exchange's file, emit an alias row under its own
    symbol/code pointing at the other exchange's market cap value, tagged
    `source: cross_exchange_alias`, never overwriting a row that already
    resolved directly. Result: NSE-side real coverage 475/638 (74.4%) ->
    516/638 (80.9%), zero new fetches.
11. **User then found the real remaining cause: the PR zip was being
    filtered to `Series == 'EQ'` only.** That filter existed on an
    untested assumption (a symbol appearing under multiple series might
    overwrite its own row with a different paid-up value). Checked real
    data: the file has 3,171 rows -- EQ (2,301), SM/ST (SME, 448+116,
    exactly the series the user named), and BE/BZ/IV/RR/SZ/IT (real
    listed instruments, not noise). Exactly one Symbol value repeats
    across rows in practice, and it's a `TOTAL` grand-total footer row,
    not a real security -- so the assumed collision risk was never real.
    Removed the series filter (excluding `TOTAL` by name instead). Real
    coverage against that day's 638 actual NSE-transacting symbols: 475
    (74.4%, EQ-only) -> **632 (99.1%), no series filter** -- the single
    biggest jump in this whole phase, and it needed zero new
    infrastructure, just reading the file NSE already gives us properly.
    Combined with the cross-exchange alias, the 6 still-missing symbols
    are explainable, not mysterious: `GANGAFO-RE`/`GENESYS-RE`/
    `SUMEET-RE` are NSE "Rights Entitlement" temporary trading
    instruments and `GVPTECHPP`/`KRISHPP` are partly-paid rights shares
    -- neither has an independent capital structure to report a market
    cap against. Only `AURIGROW` is a genuinely unexplained gap.

**Also fixed this round, found while working the above:**

- **The daily schedule was silently broken.** `r2-storage.yml` has had a
  `schedule: cron: '0 18 * * 1-5'` (weekdays) the whole time, but
  `TARGET_DATE` defaulted to a hardcoded `'2026-08-31'` whenever
  `inputs.target_date` was empty -- which it always is on a schedule
  trigger (no `inputs` context exists for `schedule` events). The
  "automatic daily update" has been re-fetching the same fixed date on
  every scheduled run, never advancing. Fixed with a `Determine target
  date` step that computes `date -u +%F` when no manual date was given.
- **Gap detection + backfill.** New `scripts/backfill_gaps.py`, run as a
  step after every write: checks the last 10 weekdays for a missing
  `manifests/{date}.json` (a prior run that failed outright before
  writing one) and, if found, re-invokes `r2_writer.py` for that date
  reusing the CURRENT run's already-fetched 90-day data -- no new
  NSE/BSE calls needed, since every acquisition script already pulls 90
  days every run. Backfilled manifests are stamped `backfilled: true` +
  `backfilled_from_run_date`, and the Overview page shows an explicit
  banner when viewing one, so a catch-up write is never confused with a
  same-day capture.
- **Date formatting.** `generated_at` (a full ISO timestamp with
  microseconds and a UTC offset) was rendered raw in Overview's
  "Freshness" field, and `st.dataframe`'s default rendering can show a
  parquet date column with a spurious `00:00:00` even when the
  underlying value is a pure date. Added `style.fmt_date()` /
  `fmt_date_col()` (clean `DD Mon YYYY`, falls back to the original
  string rather than blanking anything unparseable) and applied it
  everywhere a date renders: Overview's freshness + latest-activity
  table, Promoter Activity's window caption, and Evidence & Drill-down's
  table + evidence-drawer date fields.

Next: Phase 2 (Bulk & Block Concentration), shipping with materiality
from day one now that the market-cap join exists.
