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

**Data sources confirmed (2026-09-01), replacing guesses with real inspection:**

- `stock-screener-01-Sep-2026--1932.xls` (already in repo root, a Value
  Research screener export) -- opens fine with `xlrd`'s
  `ignore_workbook_corruption=True` flag (a known quirk of this export
  format, not real corruption). 5,287 companies with `Security`, `ISIN`,
  `BSE Code`, `NSE Code`, `Sector`, `Industry`, `Stock Rating`,
  `Quality/Growth/Valuation/Momentum Score`, `Mcap Category`
  (Small/Mid/Large Cap bucket only -- **not** a ₹ figure). 3,116 rows have
  an NSE code, 4,581 have a BSE code. This is exactly the NSE<->BSE<->ISIN
  cross-reference the cross-exchange matcher has been missing -- use it as
  a static `reference/company_master` table (ingest once, re-ingest when
  the user provides a refreshed export). It gives sector/industry and a
  coarse cap-tier immediately, but not precise market cap.
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

Decision needed: peer/sector comparison, price-correlation overlay, and
investment-signal alerts are real ideas but unscoped and not blocking
anything currently in flight. Default position: keep them as named future
phases (not built now) unless the user wants one pulled forward.

## Page structure

| Page | Status | Notes |
|---|---|---|
| Overview | Live, redesigned | Certification/status home -- KPIs, latest activity, coverage. Not a signal page. |
| **Promoter Activity** | **Built, smoke-tested** | Net-position rollup, both grains (per person+company, per company), no threshold, sorted by \|net value\|. Needs: market-cap materiality column (Phase 0.5), column/date formatting pass. |
| Bulk & Block Concentration | Not started (Phase 2) | Top clients by volume per security, largest-transactions view, concentration metric. Ship with materiality (% of market cap) from the start. |
| Rights & Preferential Pipeline | Not started (Phase 3) | Lifecycle-stage view (BSE `in_principle_status`/`listing_stage_date` -- still unverified against live BSE data, verify before trusting in UI). Promoter vs non-promoter allotment share, amount-raised trend. |
| Signals (home) | Not started (Phase 4) | Ranked cross-page front door, pulls top items from Phases 1-3. Replaces Overview as the default landing page once it exists. |
| Cross-exchange correlated signals | Deferred (Phase 5) | Depends on the still-partial cross-exchange matcher -- the VR sheet's ISIN/BSE/NSE mapping (Phase 0.5) directly helps this. |
| Peer / sector comparison | Deferred (Phase 6, unscoped) | Not in original docs. VR sheet's Sector/Industry columns make this feasible once scoped. |
| Price-correlation overlay | Deferred (Phase 7, unscoped) | Not in original docs. Needs a price-history source (candidate: `jugaad-data` bhavcopy, NSE-only). |
| Investment-signal alerts/notifications | Deferred (Phase 8, unscoped) | Not in original docs -- distinct from the existing data-quality "Alerts" nav item. |
| Evidence & Drill-down | Live, renamed from "Transactions" | Raw per-transaction view with source fields -- kept, demoted from top-level signal page to drill-down destination. |
| Data Quality | Live, unchanged | Kept as-is. |

## Immediate next steps

1. Commit + push current Promoter Activity page, plotly dependency, and
   this plan doc.
2. Scope Phase 0.5 (market cap reference data) as its own small
   investigation -- verify real NSE/BSE endpoints via live diagnostic
   (same method used for the bulk-deals fix), not assumed endpoint shapes.
3. Do not start Phase 2/3 build until Phase 0.5's data source is confirmed
   real and Phase 1's formatting pass is done.
