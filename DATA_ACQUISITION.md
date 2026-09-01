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

**Method: Selenium, browser-native `fetch()` from within the page context.**

- Endpoint: `https://www.nseindia.com/api/historical/bulk-deals?from=DD-MM-YYYY&to=DD-MM-YYYY`.
- A plain `requests.Session` (even with copied cookies) gets Akamai's ~22KB
  HTML bot-detection page instead of JSON. Calling `fetch()` via
  `execute_async_script` from inside a live Chrome tab that has already
  loaded `nseindia.com/market-data/large-deals` satisfies Akamai's TLS/JS
  integrity checks and returns real JSON.
- **Known flakiness:** even through the browser, Akamai occasionally still
  serves the bot-detection HTML for one window (status 200, `bytes≈22085`,
  JSON-parse fails on line 2). `fetch_window()` now retries up to 3 times per
  window, reloading the page between attempts to refresh the session state.

### 3. Block Deals (`scripts/nse_block.py`)

Same method and same retry logic as Bulk Deals, against
`https://www.nseindia.com/api/historical/block-deals`.

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

### Known gaps not yet fixed (need a design decision or touch certified code)

- **BSE rights/preferential lose real fields at acquisition time.** BSE's
  underlying API for these categories actually returns `InPrincipleStatus`,
  `InPrinciple_date`, `ListingStatus`, `Listing_stage_date` (confirmed in
  `bse_raw.json`), but `bse_raw_capture_v2.py`'s row-reduction step discards
  all of them, and `bse_validate.py`'s `normalize()` then labels what's left
  as meaningless `stage_1`/`stage_2`/`stage_3` (one of which is literally an
  XML file path). Fixing this properly means editing the acquisition +
  validation scripts that are currently fully certified for BSE — real risk
  of destabilizing a green status for a labeling improvement, so left alone
  pending a deliberate decision to do it with re-verification.
- **No shared NSE/BSE identifier space.** NSE uses alpha tickers (`RELIANCE`),
  BSE uses 6-digit numeric scrip codes (`500325`) — they never overlap, so
  `find_cross_exchange_matches()` can only go through fuzzy company-name
  matching (see above), which is inherently weaker than an exact-ID join.
  NSE's Rights/Preferential rows do carry `isin` (the actual
  exchange-agnostic global security identifier), but BSE's captured data
  never includes it, and NSE Insider/Bulk/Block don't either. The real fix
  is ingesting NSE's and BSE's public security-master files (which map
  symbol ↔ scrip code ↔ ISIN ↔ company name) as a new reference-data source
  — a genuinely separate piece of work, not a quick patch.
- **NSE Insider's single `date` column silently collapses a range.** ~19%
  of captured rows (88/465 on 2026-09-01) have `acqfromDt != acqtoDt` — the
  disclosed transaction is an aggregate over a multi-day window, not a
  single date. `canonical_transaction_date` currently uses the disclosure/
  intimation date, not this range.
- **Revision/amendment tracking is unused.** NSE's insider schema carries
  `prevAppId`/`revisionRemark` fields meant to mark a filing as amending an
  earlier one (0 occurrences in the 2026-09-01 sample, but expected to
  recur). `canonical_event_id` currently treats a revised filing as a brand
  new, unrelated row rather than a new version of the original — this is
  exactly the "amended/re-filed disclosure" identity case
  `PROJECT_PLAN.md` section 8 calls out as a requirement, not yet built.

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
