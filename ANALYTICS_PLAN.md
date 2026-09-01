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
| **Promoter Activity** | **Built, smoke-tested** | Net-position rollup, both grains (per person+company, per company), no threshold, sorted by \|net value\|. Needs: market-cap materiality column (Phase 0.5), column/date formatting pass. |
| Phase 0.5: Market cap join | Not started | Numeric market cap via `jugaad-data` (NSE) joined onto existing `security_master` crosswalk (already built, see correction above); coarse `mcap_category` fallback for BSE-only names. |
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

**In progress (2026-09-01): Phase 0.5, market cap join.** Plan:

1. Try `jugaad-data`'s `NSELive().stock_quote(symbol)` live against a
   handful of real NSE symbols from `security_master_20260901.csv` --
   confirm `securityInfo.issuedCap` and `priceInfo.lastPrice` actually
   come back as expected before building anything on top of an assumption.
2. Write a small acquisition step that: loads `security_master`, takes
   the distinct `nse_symbol` values actually appearing in that run's
   insider/bulk/block canonical rows (not all 3,116 -- only what's needed
   that day), fetches market cap per symbol, and writes a
   `reference/market_cap/{date}.json` (or similar) to R2.
3. Certification question to resolve as part of this: what does
   "VERIFIED" mean for a reference dataset that isn't a transaction list?
   Needs its own gate definition, not a copy of the transaction-data one.
4. Join market cap onto Promoter Activity's rollups (both grains), add
   the % of market cap column and make it sortable, using the coarse
   `mcap_category` fallback for BSE-only names with no NSE symbol.
5. Do not start Phase 2/2.5/3 build until this lands and Phase 1's
   formatting pass is done.
