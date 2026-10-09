# To do

What is open, in order, and how we will know each is done. Update this the
same day something is promised, started or finished. Pages follow the data:
`docs/DATA_TO_PAGES.md` maps each dataset to the sections it unlocks.

## Where things stand (09 Oct 2026)

- Data in R2: one year of NSE insider filings and bulk/block deals (from
  08 Oct 2025), nightly NSE + BSE collection, NSE events, and a price layer
  (NSE + BSE daily bhavcopy from 1 Jan 2025, NSE daily market cap, NSE index
  closes, a per-ISIN price summary rewritten after each nightly run).
- Kept from the 09 Oct work (PRs #11, #12): write-once raw layer
  (`raw_v2/`), nightly bulk/block from NSE's uncapped CSV, intraday round
  trips flagged in raw and excluded in clean, NSE revision markers (item 14),
  filing link `source_url` on insider rows, the price layer. Deals backfill
  redone with `--redo` (bulk +6,460 rows, flagged as round trips).
- Set aside from the 09 Oct work (owner): the 13-page app (PRs #15, #16),
  its research run and forward ledger, probes and its documents.
- Site v2 (PR #17, replaces draft PR #4): our pages on `main`.

## Next, in this order

| # | Item | Done when |
|---|---|---|
| A | ~~Check the 781 removed insider rows~~ **Done 08 Oct.** | Breakdown (clean-only run 37677587574): 37 corrected re-filings + 744 repeats; NSE 733 (727 with a different filing ID and later broadcast but the same person, shares, value, trade dates and holdings before/after; 6 the same filing ID twice), BSE 48 (same trade re-captured with small text differences). Checked against NSE's own filing list: only 41 of 3,152 filings are marked "Revision" and 2 carry prevAppId, e.g. HCL Tech 3119 is a "Revision" ("revised solely to rectify" the mode) with no prevAppId, while Prakash Steelage filed the same gift four times as "Original" in six minutes (3135-3139). Identical holdings before and after make two real trades impossible, so these are copies; removing them is right |
| B | ~~Run the backfill: last one year~~ **Done 08 Oct.** | Run 37678771716: insider 8 Oct 2025 - 2 May 2026, 7,523 rows; bulk 8 Oct 2025 - 2 Jun 2026, 14,844 fetched, 8,381 stored (6,460 intraday round trips dropped, 43.5%, same rule and share as nightly); block 848 rows. 5 insider rows carry dates mistyped in the filing itself (Campus 26-Nov-2026 for 2025; Premier Polyfilm intimation 03-Feb-2036; Solar Industries 3 gifts dated 09-Nov-2026 but published 11-Mar-2026): parsed correctly, stored as filed, held back by the cleaner. Clean rebuild (run 37679323259): insider 14,478 in -> 13,487 out; deals 17,421 -> 16,825; 2,367 securities, 57 unmatched. One-year default and best-effort warm-up merged in PR #9 (NSE 403s the home page to GitHub's runner, not the API) |
| C | Owner reviews the baseline numbers above | Owner confirms |
| D | PR #17 (was PR #4): on `main`, real-browser screenshots of every page on R2 data, fix what's wrong | CI green on the PR head; screenshots looked at |
| E | Merge PR #17, then a "Clean only" run (one-year window) | Live insiders.streamlit.app shows the new site on the rebuilt tables |
| F | Shareholding for every company | `nse-events.yml` run with dataset=shareholding and a wide window (~120 days), repeated until most companies' latest quarter is in (300 XBRL files per run) |
| G | Prices on the pages | From our own price layer (`artifacts/prices_summary_slim.parquet`, `prices/daily/`): CMP, 52-week high, 200-day average, price paid vs CMP, move since broadcast, and the ICDR minimum (higher of 90- and 10-session VWAP); pending columns on Screener, Today and Company filled; three checked by hand |
| H | Preferential and rights issues cleaned | Offer price, shares allotted, allotment and trading-approval dates, promoter or not; lock-in expiry (promoters 18 months, others 6); Capital raises sections S16-S18 built |

## Later

| # | Item | Done when |
|---|---|---|
| 7 | Signal lab and Track record page | Each signal in `docs/SIGNALS.md` shows 1-week, 1-, 3- and 6-month excess returns vs Nifty 500 from broadcast time, after ~0.25% costs, with case counts (one year of history limits the longer horizons) |
| 8 | Price chart with filings marked (company page) | Waits on G |
| 9 | Morning brief and watchlist warnings | Brief before 09:15 IST on trading days; warning when an insider sells, pledges or gets cheap shares in a watched stock |
| 10 | Model basket | Waits on 7 |
| 12 | Buyback price and route | Offer price and tender/open-market route attached to every buyback |
| 13 | BSE history and BSE events | In-page fetch working; BSE insider, bulk/block, SAST and corporate actions collected |
| 14 | ~~`nse_insider.py` keeps NSE's revision markers~~ **Coded 09 Oct; check the first nightly rows carry them** | `prevAppId`, `typeOfSubmission` and `revisionRemark` captured from the filing list, so the cleaner can say "revised per NSE: <remark>" vs "re-submitted as Original"; the content-based check stays (most re-filings are marked Original) |
| 15 | Retention deletes for real | Owner sets `R2_RETENTION_DELETE=1` once the archive has been stable; stays a dry run until then |
| 16 | Named-investor aliases | Curated list maps known investors' and funds' spellings to one name |
| 18 | NSE block deals BLOCKED in the nightly collection on 07 and 08 Oct | Validator passes again, or the cause is found (history block deals came in fine through the CSV endpoint) |
| 19 | Data checks from the 09 Oct brief | In the cleaning report and Data page: holding after - holding before = shares traded (right sign); implied price (value / shares) inside that day's high-low (catches lakh/crore unit errors and off-market prices); disclosure before trade or in the future; holding-only disclosures (on appointment) not counted as trades |
| 20 | Tradability flags | ASM / GSM / ESM stage, trade-for-trade, SME board, circuit-locked or suspended days, shown as flags (never silent drops), thresholds in config |
| 21 | One decision-maker per promoter family | Promoter-group entities acting together count once in cluster and breadth figures (linked through the shareholding pattern, not by name similarity) |
| 22 | Ownership headroom | Distance to the 75% promoter ceiling (minimum public shareholding, SCRR 19A) and creeping-acquisition room (SAST Reg 3(2), 5% a year) on the Company page |
| 23 | Deal participant types | Mutual fund, insurer, FPI, PMS/AIF, proprietary/HFT, corporate, individual, each with a confidence level; name mapping auditable |
| 24 | Disclosure lag and price before broadcast | How long each filing took to reach the public and how much the price moved before it did |
| 25 | Results dates and trading window | Board-meeting results dates joined to filings: buys right after the trading window opens marked |
| 26 | Forward record | Each signal recorded as it fires (time, rule version, entry price), never edited; outcomes filled in later; shown on Track record |
| 27 | Retire or fix "NSE-BSE Data Validation" | Red on every push since 07 Oct: its step expects `nse_acquisition_output.json` that is never written, with a fixed date 2026-08-31 |
| 28 | Object lock on `raw_v2/` | Owner sets R2 object lock or lifecycle protection on the raw layer |

## Decided, not to do

- Screener.in and Tijori are not scraped. The owner gave permission on
  08 Oct, but Screener's terms forbid copying or mirroring and its
  robots.txt disallows the paginated pages; Tijori's terms couldn't be read
  (rendered by script). NSE data and Paresh's public release cover the needs.
- No prices token and no Paresh data: our own exchange bhavcopy layer covers NSE and BSE (Paresh's covers about 38% of NSE symbols with 2026 data).
- History: only the last one year (owner, 08 Oct); the site grows daily from there.
