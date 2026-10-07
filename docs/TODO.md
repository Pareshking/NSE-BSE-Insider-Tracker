# To do

What is open, in order, and how we will know each is done. Update this the
same day something is promised, started or finished. Pages follow the data:
`docs/DATA_TO_PAGES.md` maps each dataset to the sections it unlocks, so the
order here is by how many sections an item unlocks.

Priority after the backfill: 5 (shareholding coverage, used on four pages)
and 11 (preferential and rights cleaning, unlocks three sections; its data is
already collected), then 6 (prices).

| # | Item | State | Done when |
|---|---|---|---|
| 1 | Baseline cleaning report from R2 | Run started 07 Oct 2026 (manual dispatch of R2 Storage Write) | `clean/reports/2026-10-07.json` read and its summary confirmed by the owner |
| 2 | Merge PR 4 (new site) | Draft open | Merged after `clean/current/insider_trades.parquet` exists in R2 and CI is green on the PR head |
| 3 | History backfill runner (PR 2) | Being built | Resumable, paced runner merged with tests; NSE insider 19 Nov 2015 - 02 May 2026, bulk 2004+, block Nov 2005+ loaded into `archive/`; backfill report read |
| 4 | Clean step at 11-year scale | With PR 2 | Nightly clean over ~150k filings and ~500k deal rows finishes in minutes, measured |
| 5 | Shareholding for every company | Only filings of the last 10 days so far | One run with a wide window (latest quarter for all listed companies) so % of float and pledge cover the whole universe |
| 6 | Price join | Not started; needs a read-only R2 token for Paresh's price files (owner, in Cloudflare) | 52-week high, 200-day average, price paid vs today and the ICDR minimum price (higher of 90- and 10-session VWAP before the relevant date) on every NSE company, three checked by hand |
| 7 | Signal lab and Track record page | Waits on 3 and 6 | Each signal in `docs/SIGNALS.md` shows 1-week, 1-, 3- and 6-month excess returns vs Nifty 500 from broadcast time, after ~0.25% costs, with case counts |
| 8 | Price chart with filings marked (company page) | Waits on 6 | Chart on every company page with each filing at its broadcast date |
| 9 | Morning brief and watchlist warnings | Not started | Brief (email or Telegram) before 09:15 IST on trading days; a warning when an insider sells, pledges or gets cheap shares in a watched stock |
| 10 | Model basket | Waits on 7 | A public paper portfolio following stated rules, updated nightly, costs included |
| 11 | Rights and preferential issues in the clean layer | Not started | Archived and cleaned like insider trades; lifecycle stages grouped per issue; retention may then include them |
| 12 | Buyback price and route | Flagged (`needs_price_gap`) | Offer price and tender/open-market route attached to every buyback |
| 13 | BSE history and BSE events | Not started (BSE refuses direct API calls) | In-page fetch working; BSE insider, bulk/block, SAST and corporate actions collected |
| 14 | `nse_insider.py` keeps `prevAppId` | Open | Field captured; the cleaner's content-based revision check stays as a fallback |
| 15 | Retention deletes for real | Dry run, by decision | Owner sets `R2_RETENTION_DELETE=1` after the multi-year archive has been stable |
| 16 | Named-investor aliases | Not started | A curated list maps the spellings of known investors and funds (for example Rekha Jhunjhunwala, Ashish Kacholia, mutual-fund schemes) to one name, used by deals, SAST and person pages |
| 17 | Site pages rebuilt from `docs/DATA_TO_PAGES.md` | Map written 08 Oct 2026, awaiting owner's approval | Every section in the map that is In is on its page; pending ones are listed as pending, none substituted |
