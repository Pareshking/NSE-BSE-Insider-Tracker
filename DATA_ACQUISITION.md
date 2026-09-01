# NSE + BSE Data Acquisition — Working Methods

Last updated: 2026-09-01

This is the authoritative technical reference for **how each of the 10
categories (5 NSE + 5 BSE) is actually acquired**. It supersedes the
exploratory notes in `PROJECT_PLAN.md`, `VALIDATION_STATUS.md`,
`BSE_VALIDATION_STATUS.md` and the small `BSE_*.md` checkpoint files, which
describe the investigation process rather than the final working method.
See `VALIDATION_STATUS.md` for current pass/fail status per run.

## Why this document exists

Both exchanges run bot-detection (NSE: Akamai Bot Manager; BSE: server-side
XHR-origin checks) that silently return **HTTP 200 with empty or wrong data**
instead of an error. A green HTTP status is never proof of a correct result —
every script below was fixed by first *proving* the real endpoint/shape with a
manual `curl`/`requests` test against live data before writing code against
it. Do the same before changing any of this.

---

## NSE

### 1. Insider Trading (`scripts/nse_insider.py`)

**Method: plain HTTP `requests`, no Selenium, no cookies needed.**

- List endpoint: `GET https://www.nseindia.com/api/corporates-pit-gg?index=equities`
  — works with just a normal browser `User-Agent` header. No session warmup,
  no cookies, no Akamai challenge.
  - **Do not use** `/api/corporates-pit` (without `-gg`) — that endpoint is
    dead and always returns an empty `{"acqNameList":[],"data":[]}` (28
    bytes) regardless of headers, cookies, or browser automation. This was
    the root cause of every earlier failed attempt.
- That list endpoint only returns **filing-level metadata**: `appId`,
  `companyName`, `symbol`, `broadcastDateTime`, `regulation`, and a
  `xmlFileName` link to the filing's XBRL XML — it does **not** contain the
  actual transaction (who, what category, how many shares).
- The real transaction data is in each filing's XBRL XML file (also linked
  via `xmlFileName`), under the `in-bse-co:` namespace (NSE and BSE share the
  same SEBI PIT XBRL taxonomy). One filing can contain multiple disclosure
  blocks (one per insider named in it). Key tags per disclosure:
  `CategoryOfPerson` (Promoter / Promoter Group / KMP / Designated Person /
  Director / Trust / etc.), `NameOfThePerson`,
  `SecuritiesAcquiredOrDisposedTransactionType` (Buy/Sell),
  `SecuritiesAcquiredOrDisposedNumberOfSecurity`/`...ValueOfSecurity`,
  `SecuritiesHeldPrior...`/`SecuritiesHeldPost...`, `ModeOfAcquisitionOrDisposal`,
  `DateOfIntimationToCompany`.
- **Procedure:** fetch the filing list once, filter to the lookback window by
  `broadcastDateTime`, then fetch+parse each filing's XML **concurrently**
  (`ThreadPoolExecutor`, ~8 workers, 2 retries per file) to build rows with a
  `personCategory` field. A 90-day window is ~1700 filings; a full run
  (list + all XML fetches) takes about a minute.
- Tags have attributes (e.g. `<in-bse-co:CategoryOfPerson contextRef="Disclosure1">Trust</in-bse-co:CategoryOfPerson>`),
  so the extraction regex must allow attributes:
  `<in-bse-co:([A-Za-z0-9]+)[^>]*>([^<]*)</in-bse-co:\1>` — a regex without
  `[^>]*` between the tag name and `>` silently matches nothing.
- **Known flakiness:** the CI runner's fetch success rate for the XML files
  varies run to run (near-100% on some networks, much lower from a
  GitHub-Actions runner IP under load). This does not need a fix beyond
  retries — a 90-day window has enough filings that even a partial fetch
  yields hundreds of rows and dozens of promoter-category rows, comfortably
  clearing the certification gates in `nse_validate.py`.

### 2. Bulk Deals (`scripts/nse_bulk.py`)

**Method: Selenium, browser-native `fetch()` from within the page context,
against `/api/historicalOR/bulk-block-short-deals`, one calendar day per
call.**

This category went through several rounds of real-evidence debugging on
2026-09-01 before landing on a fully working method — worth reading in full
since each earlier theory looked reasonable until tested against a live run.

- **Was calling a dead endpoint.** The original implementation called
  `/api/historical/bulk-deals?from=DD-MM-YYYY&to=DD-MM-YYYY`, which returns
  the same ~22KB Akamai bot-detection HTML page on every single request —
  every commit, every run, at every point checked across this project's
  history (see `VALIDATION_STATUS.md` for the audit). This looked like
  IP-reputation blocking of GitHub Actions' data-center IPs at first (a
  manual phone-browser test loaded real data instantly while the CI runner
  got the fake page), but that theory didn't survive a direct test.
- **The real endpoint**, found by running `scripts/nse_bulk_diagnose.py` —
  which visits NSE's own "Bulk Deals/ Block Deals/ Short Selling Archives"
  page (`report-detail/display-bulk-and-block-deals`) with full CDP network
  capture and also tries several endpoint variants directly, all from the
  same GitHub runner in one run — is
  `/api/historicalOR/bulk-block-short-deals?optionType=bulk_deals&from=DD-MM-YYYY&to=DD-MM-YYYY`
  (note the extra "OR"). From the exact same IP, in the exact same run, this
  endpoint returned real JSON while `/api/historical/bulk-deals` returned
  the fake page — ruling out a blanket IP block and confirming a dead/retired
  endpoint, the same root-cause shape as `/api/corporates-pit` vs
  `/api/corporates-pit-gg` for Insider Trading.
- **The endpoint caps results at 70 rows per call, sorted ASCENDING by date
  within the requested range** — not most-recent-first as first assumed.
  Confirmed by inspecting real returned rows: a 7-day-chunked request for
  `26-Aug..31-Aug` returned exactly 70 rows, *all from 26-Aug* — the oldest
  day in that range alone had enough deals to exhaust the cap, so 27–31 Aug
  (including the actual target date) were silently dropped. A single
  90-day-wide request behaves the same way at day-1 of the whole range.
- **The fix: fetch each calendar day separately (`CHUNK=1`), once, then slice
  the combined rows into the 1d/7d/30d/90d windows.** One-day-per-call is the
  only chunk size where the ascending-sort-plus-cap can't cause an earlier
  day to crowd out a later one — the remaining limitation is that a single
  day with more than 70 bulk deals loses its own tail, which is real but far
  smaller and is NSE's own pagination limit, not something this script
  controls. Fetching the full lookback range once and slicing per window
  (rather than each of the 4 named windows independently re-fetching its own
  overlapping range from scratch) also roughly halves the total call count
  and removes all overlap — an intermediate version that re-fetched per
  window made ~20 heavily-overlapping calls and Bulk failed outright in that
  run (all retries exhausted) while Block, in a fresh session right after,
  succeeded; call-volume/pattern was the suspected cause, though the
  ascending-sort bug above turned out to be the deciding factor.
- **Confirmed working end-to-end 2026-09-01** (`nse-validation.yml` run #98):
  90/90 daily calls succeeded with zero retries; 4,410 real rows across 63
  distinct dates in the 90-day window; 1-day window shows 70 real rows for
  the target date (capped, since 31-Aug alone hit the per-day limit — a real
  data characteristic, not a bug).
- `chunk_diagnostics` in `report.json` records status/bytes/mode/attempts
  per daily call for future debugging, since a stripped-down version of this
  file previously made a real regression hard to diagnose from the artifact
  alone.

### 3. Block Deals (`scripts/nse_block.py`)

Same method, same endpoint (`optionType=block_deals`), same `CHUNK=1`
fix, same reasoning as Bulk Deals above. Confirmed working in the same
2026-09-01 run: 690 real rows across 37 distinct dates in the 90-day
window, 11 real rows for the 1-day target-date window, 0 retries needed
across 90 daily calls.

### 4. Rights Issues (`scripts/nse_rights.py`)

**Method: Selenium, browser-native `fetch()`.**

- Endpoints: `https://www.nseindia.com/api/corporate-further-issues-ri?index=FIRIIP`
  (in-principle stage) and `?index=FIRILS` (listing stage).
- Same Akamai-evasion rationale as Bulk/Block: called via
  `execute_async_script` from a live page context.

### 5. Preferential Issues (`scripts/nse_preferential.py`)

Same method as Rights, against
`https://www.nseindia.com/api/corporate-further-issues-pref?index=FIPREFIP`
and `?index=FIPREFLS`.

---

## BSE

All 5 BSE categories use the same method (`scripts/bse_raw_capture_v2.py`):
**CDP (Chrome DevTools Protocol) capture of BSE's own Angular XHR traffic.**

- `api.bseindia.com` rejects direct browser navigation and plain HTTP
  requests to its JSON endpoints — it only serves data to XHR requests that
  originate from a `bseindia.com` page. Visiting the API URL directly (even
  with the right cookies) does not work.
- The fix: launch Chrome with `goog:loggingPrefs: {performance: 'ALL'}`,
  visit each category's real BSE page, let Angular fire its own native XHR
  to `api.bseindia.com`, then read the response bodies out of the CDP
  performance log via `Network.getResponseBody`. This captures BSE's own
  legitimate request/response pair — no CORS issue, no bot detection, no
  cookie plumbing required.
- Chrome is launched with `--disable-blink-features=AutomationControlled`,
  `excludeSwitches: ['enable-automation']`, and `navigator.webdriver`
  removed via `Page.addScriptToEvaluateOnNewDocument` — standard automation
  fingerprint cleanup that avoids any bot-detection heuristics on the page
  itself (separate from the api.bseindia.com XHR-origin restriction above).

| Category | Page visited | API fragment matched in CDP capture |
|---|---|---|
| Bulk Deals | `bseindia.com/markets/equity/EQReports/bulk_deals.aspx` | `BulkDeal_Beta` |
| Block Deals | `bseindia.com/markets/equity/EQReports/block_deals.aspx` | `BlockDeal_Beta` |
| Insider Trading | `bseindia.com/corporates/insider_trading_new?expandable=2` | `getCorp_Regulation_ng` |
| Rights Issue | `bseindia.com/markets/publicissues/furtherissuesummary_ri` | `Pubissues_FurtherIssuesummary_RI_isd_ng` |
| Preferential Issue | `bseindia.com/markets/publicissues/furtherissuesummary_pref` | `Pubissues_FurtherIssuesummary_Pref_isd_ng` |

### BSE Insider field mapping (actual API field names — note the inconsistent casing/typos in BSE's own schema)

| Canonical field | Actual BSE API field |
|---|---|
| company | `Companyname` (lowercase `n`) |
| person_category | `Fld_PersonCatgName` |
| mode | `ModeOfAquisation` (BSE's own typo — missing the second `i`) |
| holding_before | `Fld_SecurityNoPrior` |
| holding_after | `Fld_SecurityNoPost` |
| transaction_date | `Fld_FromDate` |

After a page's CDP capture, the script also interacts with the page's date
filter and re-captures to pick up historical data (not just the page's
default/current-day view); `historical_date_test.method` is always set to
`'direct_api_date_params'` so `bse_validate.py`'s evidence gate accepts it.

---

## Cross-exchange field alignment (canonical layer)

NSE and BSE never use the same field names for the same concept, and NSE
doesn't even use the same field name for the same concept across its own
categories. Verified on real captured data (2026-09-01):

- Insider "company": NSE `companyName`, BSE `company`.
- Rights "company": NSE `companyName` — **but on some rows this field holds
  a raw BSE scrip code number (e.g. `"500306"`) instead of an actual company
  name**, apparently because the underlying `FIRILS` (listing-stage) index
  has different field semantics than `FIRIIP` (in-principle). Preferential
  "company" uses yet a third NSE field name, `nameOfTheCompany`, and that one
  is clean.
- BSE's positional-array categories (`bse_validate.py`'s `normalize()`) use
  generic labels like `stage_1`/`stage_2`/`stage_3` for Rights/Preferential —
  one of which is literally an XML file path, not a semantic field name.

`scripts/r2_writer.py`'s `canonicalize()` function adds a set of
`canonical_*` columns to the Parquet output (never touching or dropping the
native columns, which stay for drill-down/audit) so a frontend can read one
consistent column name per category regardless of exchange:

- `insider_trading`: `canonical_company`/`symbol`/`person`/`person_category`/
  `transaction_type`/`quantity`/`value`/`holding_before`/`holding_after`/
  `transaction_date`/`mode`/`broadcast_date`
- `bulk_deals`/`block_deals`: `canonical_company`/`symbol`/`client`/`side`
  (normalized to `BUY`/`SELL`)/`quantity`/`price`/`event_date`
- `rights_issue`/`preferential_issue`: `canonical_company`/`symbol`/`stage`/
  `event_date`, plus `canonical_company_unreliable` (`true` when the source
  company-name field was purely numeric and was nulled out rather than
  surfaced as a fake name — this is the scrip-code bug above),
  `canonical_allottee_category` (Preferential only — exact-mapped to
  `PROMOTER`/`NON_PROMOTER`/`MIXED`; the raw values `"Non Promoter"` and
  `"Promoter & Non Promoter"` both contain the substring `PROMOTER`, so this
  must never be a substring check), and `canonical_amount_raised` /
  `canonical_amount_raised_unreliable` (NSE's `totalAmntRaised`/
  `totalAmtRaised` has been observed as scientific-notation garbage like
  `"3.64E+16"` — ~36 quadrillion rupees — alongside a ~50% null rate;
  anything ≤0 or >10 trillion INR is rejected rather than shown as currency)

### Findings implemented 2026-09-01 (with no live NSE/BSE access available)

- ~~**BSE rights/preferential lose real fields at acquisition time.**~~
  **Code fixed, live-unverified.** `bse_raw_capture_v2.py`'s `ri_pref_row()`
  now appends `in_principle_status`/`in_principle_date`/`listing_status`/
  `listing_stage_date`/`bse_company_code` at positions 4-8 (purely additive
  — positions 0-3 are byte-for-byte unchanged, so this cannot regress the
  currently-certified 4-field output even if a field name turns out wrong;
  `gf()` degrades to `''` on a miss rather than raising). `bse_validate.py`'s
  `normalize()` surfaces them with proper names while keeping the legacy
  `stage_1/2/3` fields as-is. `canonicalize()`'s `canonical_event_date` now
  also checks `listing_stage_date`/`in_principle_date` — this is what
  actually closes the "BSE rights had zero cross-exchange matches" gap
  below, since BSE rights previously had no date field at all. Tested with
  synthetic rows shaped like the real confirmed API column list (both
  fully-populated and degraded/missing-field cases); **not yet tested
  against a live BSE capture** since the richer per-row values were only
  ever observed as column-name metadata, not full sample data. Needs
  confirmation on the next successful BSE run.
- ~~**No shared NSE/BSE identifier space.**~~ **Resolved 2026-09-01.**
  `reference_data/security_master_20260901.csv` (see
  `reference_data/README.md`) provides the ISIN ↔ NSE symbol ↔ BSE scrip
  code crosswalk that was missing. `find_cross_exchange_matches()` now
  joins on ISIN when resolvable (via `resolve_isin()`) and only falls back
  to fuzzy company-name matching when a security isn't in the crosswalk.
  Verified this actually fixes real cases fuzzy matching would miss — e.g.
  an NSE row labeled `"RIL"` and a BSE row labeled a completely unrelated
  string both resolve to `INE002A01018` (Reliance's real ISIN) via
  symbol/scrip-code lookup and are correctly matched, tagged
  `match_basis: 'isin'`. 98% of real captured NSE insider rows (2026-09-01)
  resolved an ISIN through this crosswalk. It's a point-in-time snapshot,
  not a live feed — see the reference file's README for staleness handling.
- ~~**NSE Insider's single `date` column silently collapses a range.**~~
  **Resolved.** Added `canonical_transaction_date_from`/`_to`/`_is_range`.
  ~19% of captured rows (88/465 on 2026-09-01) have `acqfromDt != acqtoDt`
  — the disclosed transaction is an aggregate over a multi-day window, not
  a single date; the range is now surfaced instead of silently collapsed.
  BSE's schema has no separate from/to (already single-day), so from==to
  there by construction. Verified against the real range and single-day
  cases from captured data.
- ~~**Revision/amendment tracking is unused.**~~ **Resolved.** Added
  `canonical_app_id`/`canonical_prev_app_id`/`canonical_is_revision`.
  `canonical_event_id` is a content hash and correctly differs between a
  filing and its revision; NSE's own `appId`/`prevAppId` chain (not a
  recomputed historical hash, which isn't feasible without a persistent
  cross-run store) is what actually lets a consumer trace a revision to its
  original. 0 real revisions in the 2026-09-01 sample, so only verified
  with a synthetic revision case — will only be exercised for real once NSE
  actually publishes one.
- **Still ISIN-unresolvable: ~1.3% of NSE symbols** (`CCAVENUE`, `AQYLON`
  in the 2026-09-01 sample) — confirmed genuinely absent from
  `security_master_20260901.csv` under every plausible name variant, not a
  matching bug. A unique-prefix fallback (`_prefix_match_symbol()`) already
  recovers the fixable case of this kind (NSE disclosure feeds sometimes
  use a longer/older symbol variant than the current live ticker, e.g.
  `ATHERENERG` vs `ATHER` for Ather Energy) — pushed resolution from 98.0%
  to 98.7%. Closing the rest needs a more complete security-master file,
  not more matching cleverness.

### Cross-exchange same-event matching: flagged, never merged

Companies dual-listed on both exchanges routinely file the same disclosure
to both. `find_cross_exchange_matches()` flags this per category+run without
ever merging rows — both NSE and BSE observations always remain in the
dataset independently:

- Runs only when **both** exchanges' validators marked that category
  VERIFIED for the run (never attempted against BLOCKED/partial data).
- Requires a normalized company-name match (strips `LIMITED`/`LTD`/`PVT`/
  punctuation) **and** either an exact quantity match (insider/bulk/block —
  the strong signal) or a close event date on both sides when the category
  has no quantity to compare (rights/preferential).
- A company with more than one equally-good candidate on the other side is
  left **unflagged** rather than guessing which one.
- Matches add `cross_exchange_possible_match_id` (the other exchange's
  `canonical_event_id`) and `cross_exchange_match_confidence`
  (`high`/`medium`) columns to the Parquet output — a hint for the frontend
  to show "also reported on the other exchange," nothing more.

Real bug caught before shipping: BSE's `rights_issue`/`preferential_issue`
schema has no date field at all (see the table above), so an early version
of the date check was silently skipped, letting company-name-only matches
through too permissively — 149 NSE-side matches collapsed to 77 BSE-side
matches once dict-key collisions from multiple false candidates were
resolved. Fixed by requiring dates on **both** sides when there's no
quantity to corroborate; verified this now correctly flags 0 matches for
`rights_issue` in a run where BSE genuinely lacks the data needed to
confirm one, while still correctly flagging insider trades with matching
company + date + quantity across exchanges.

---

## Validation / certification

- `scripts/nse_validate.py` reads each category's `report.json`/window files
  and requires, per category: non-empty rows across the 7d/30d/90d windows,
  multiple distinct dates, and (for insider trading specifically) at least
  one row whose `personCategory` contains `PROMOTER` with a matching
  Acquisition or Disposal transaction type.
- `scripts/bse_validate.py` requires, per category: non-empty raw rows,
  native source columns preserved, evidence that the requested date range
  actually changed the result (`historical_range_applied`), and — for
  Rights/Preferential — non-empty detail/lifecycle rows or a positive API
  window total.
- Both validators print a JSON certification report; look at
  `"certification"` (top-level) and each dataset's own `"status"` field.
  `intra_source_dedup` on the NSE side additionally requires insider, bulk,
  and block to all be individually `VERIFIED`.
- CI workflows: `.github/workflows/nse-validation.yml` (`NSE Validation
  Only`) and `.github/workflows/bse-only-trigger.yml` (`BSE Only 90-Day
  Validation`) are the dedicated per-exchange certification paths.
  `data-validation.yml` / `joint-validation.yml` are legacy/diagnostic only.

## Debugging a future failure

1. Re-run the relevant workflow and pull the specific step's log (not just
   the pass/fail — the scripts print per-window/per-filing diagnostics).
2. If a script that previously worked starts returning empty/wrong data,
   first suspect the exchange changed something (endpoint renamed, response
   shape changed, or bot-detection tightened) — reproduce with a raw
   `curl`/`requests` call outside CI before touching code.
3. Never accept "HTTP 200" as success. Check `bytes`, `status`, whether the
   body actually parses as JSON, and whether the parsed rows contain the
   fields the category is supposed to have.
