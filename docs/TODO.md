# To do

What is open, in order, and how we will know each is done. Update this the
same day something is promised, started or finished. Pages follow the data:
`docs/DATA_TO_PAGES.md` maps each dataset to the sections it unlocks.

## Where things stand (08 Oct 2026, 02:00 IST)

- `main` = 50fb329: clean layer (PR #2), NSE corporate events (PR #3),
  `<NA>` hotfix (PR #6) and the backfill runner (PR #5) are merged.
- First real clean run in R2 (run 37674160420, 07 Oct): insider filings
  6,955 in -> 6,174 out (781 removed), deals 8,193 -> 7,823 (152 removed),
  1,484 securities, 26 unmatched. Archive: NSE insider 4,835, NSE bulk 5,386,
  NSE block 885, BSE insider 2,120, BSE bulk 1,745, BSE block 177 records.
  `clean/current/insider_trades.parquet` now exists.
- NSE events (SAST, actions, meetings, shareholding) collected once by hand
  on 07 Oct; the daily schedule runs from 08 Oct.
- PR #4 (new site, draft) on `feat/ui-shell` = 3bc4b6b: pages rebuilt from
  the data map; not merged yet.
- The overnight cloud run did not start; nothing ran after 02:00 IST.

## Update 09 Oct 2026 (Phase 1; details in `docs/AUDIT.md`, `docs/DECISIONS.md`, `docs/PROGRESS.md`)

- Work is on branch `ccr-27a6c75f-o9ztpa` / draft PR #11; nothing merged to `main` (it deploys production).
- Deals backfill redone with `--redo`: bulk +6,460 rows (flagged `intraday_round_trip`), block +0; item B's "dropped" counts below are superseded.
- New: write-once raw layer, nightly raw capture (untested in production), 1 Jan 2026 product window, data-inventory workflow.
- Open: nightly bulk/block 70-row cap (move to CSV endpoint?), native bhavcopy price layer, revision fields (item 14), `main` nightly clean ignores the round-trip flag until the branch merges.

## Tomorrow, in this order

| # | Item | Done when |
|---|---|---|
| A | ~~Check the 781 removed insider rows~~ **Done 08 Oct.** | Breakdown (clean-only run 37677587574): 37 corrected re-filings + 744 repeats; NSE 733 (727 with a different filing ID and later broadcast but the same person, shares, value, trade dates and holdings before/after; 6 the same filing ID twice), BSE 48 (same trade re-captured with small text differences). Checked against NSE's own filing list: only 41 of 3,152 filings are marked "Revision" and 2 carry prevAppId, e.g. HCL Tech 3119 is a "Revision" ("revised solely to rectify" the mode) with no prevAppId, while Prakash Steelage filed the same gift four times as "Original" in six minutes (3135-3139). Identical holdings before and after make two real trades impossible, so these are copies; removing them is right |
| B | ~~Run the backfill: last one year~~ **Done 08 Oct.** | Run 37678771716: insider 8 Oct 2025 - 2 May 2026, 7,523 rows; bulk 8 Oct 2025 - 2 Jun 2026, 14,844 fetched, 8,381 stored (6,460 intraday round trips dropped, 43.5%, same rule and share as nightly); block 848 rows. 5 insider rows carry dates mistyped in the filing itself (Campus 26-Nov-2026 for 2025; Premier Polyfilm intimation 03-Feb-2036; Solar Industries 3 gifts dated 09-Nov-2026 but published 11-Mar-2026): parsed correctly, stored as filed, held back by the cleaner. Clean rebuild (run 37679323259): insider 14,478 in -> 13,487 out; deals 17,421 -> 16,825; 2,367 securities, 57 unmatched. One-year default and best-effort warm-up merged in PR #9 (NSE 403s the home page to GitHub's runner, not the API) |
| C | Owner reviews the baseline numbers above | Owner confirms |
| D | PR #4: rebase on `main`, real-browser screenshots of every page on R2 data, fix what's wrong | CI green on the PR head; owner has seen the screenshots |
| E | Merge PR #4 | Merged after D; live insiders.streamlit.app shows the new site |
| F | Shareholding for every company | `nse-events.yml` run with dataset=shareholding and a wide window (~120 days), repeated until most companies' latest quarter is in (300 XBRL files per run) |
| G | Price join, no token needed | Paresh's public release `data-latest` (`nse_long_close.parquet`: adjusted closes, 1,419 NSE symbols; `ss_prices_2026.parquet`: OHLCV with volume; `bse_daily.parquet`) gives CMP, 52-week high, 200-day average, price paid vs CMP and the ICDR minimum (higher of 90- and 10-session VWAP); pending columns on Screener, Today and Company filled; three checked by hand |
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
| 14 | ~~`nse_insider.py` keeps NSE's revision markers~~ **Coded 09 Oct, unverified live** | `prevAppId`, `typeOfSubmission` and `revisionRemark` captured from the filing list, so the cleaner can say "revised per NSE: <remark>" vs "re-submitted as Original"; the content-based check stays (most re-filings are marked Original) |
| 15 | Retention deletes for real | Owner sets `R2_RETENTION_DELETE=1` once the archive has been stable; stays a dry run until then |
| 16 | Named-investor aliases | Curated list maps known investors' and funds' spellings to one name |
| 18 | NSE block deals BLOCKED in the nightly collection on 07 and 08 Oct | Validator passes again, or the cause is found (history block deals came in fine through the CSV endpoint) |

## Decided, not to do

- Screener.in and Tijori are not scraped. The owner gave permission on
  08 Oct, but Screener's terms forbid copying or mirroring and its
  robots.txt disallows the paginated pages; Tijori's terms couldn't be read
  (rendered by script). NSE data and Paresh's public release cover the needs.
- No prices token: Paresh's public `data-latest` release replaces it.
- History: only the last one year (owner, 08 Oct); the site grows daily from there.
