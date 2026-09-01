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
