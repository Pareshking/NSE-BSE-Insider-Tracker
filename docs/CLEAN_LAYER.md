# Clean layer

The site reads clean tables, not the exchange data as collected. This page
says where they live, what each rule does, and how storage is kept small.

## Nightly order (R2 Storage Write workflow)

1. Collect and validate NSE + BSE (unchanged).
1a. `scripts/nse_surveillance.py` fetches NSE's ASM, GSM and ESM lists and `sec_list.csv` (price bands), keeps one
   snapshot a day in `archive/tradability/`, and rebuilds `clean/current/tradability.parquet` with the last three
   months of NSE bhavcopy (`continue-on-error`; also its own workflow, Tradability flags). Flags only, never a
   filter (`docs/DATA_DICTIONARY.md`).
1b. Every collector saves each response's exact bytes locally at fetch time
   (`scripts/raw_capture.py`); `scripts/raw_flush.py` then stores them in the
   write-once `raw_v2/` layer (see "Raw layer").
2. `scripts/r2_writer.py` writes `raw/` and `canonical/` for today. Intraday
   round-trip deal legs are flagged (`intraday_round_trip`), no longer dropped.
3. `scripts/update_calendar.py` extends the NSE trading calendar.
4. `scripts/clean_writer.py` merges today's canonical files into the archive
   and rebuilds the clean tables from the whole archive. It also reads (never
   writes) the price layer `prices/daily/` for the insider price check, and
   NSE's daily market cap `marketcap/daily/nse/` for % of market cap at the
   trade date.

   and rebuilds the clean tables from the whole archive. Insider trades then
   get the results date and trading-window columns from the NSE events
   collector's `clean/current/meetings.parquet` (`insiders_clean/trading_window.py`;
   a failure there is a note in the report, never a missing table).

Steps 3 and 4 are `continue-on-error`: they can never fail the collection.

## R2 layout

| Key | What | Kept |
|---|---|---|
| `archive/canonical/{exchange}/{category}/year=YYYY/quarter=Q.parquet` | Every collected record once, with `first_seen` / `last_seen`, partitioned by the record's own date; past quarters are written once, then only read | Forever |
| `archive/canonical/{exchange}/{category}/_state.json` | Last run merged, record count, partitions written that night | Rewritten nightly |
| `clean/current/insider_trades.parquet` | One row per filing, cleaned, full history | Rewritten nightly |
| `clean/current/deals.parquet` | One row per client, security, day, side | Rewritten nightly |
| `clean/current/securities.parquet` | One row per security used | Rewritten nightly |
| `clean/current/tradability.parquet` | One row per ISIN: surveillance stage, T2T, SME, band, circuit days | Rewritten nightly |
| `archive/tradability/{surveillance,sec_list}/year=YYYY.parquet` | One parsed snapshot a day of NSE's surveillance lists and price bands | Forever |

| `clean/current/{preferential,rights,qip}.parquet`, `preferential_allottees`, `preferential_lockins`, `qip_allottees` | Further issues (`insiders_clean/issues.py`), rebuilt by `clean_writer.py` from the snapshots and the issues archive | Rewritten nightly |
| `archive/nse_events/issues/year=YYYY.parquet` | Every further-issue filing NSE posted in a date window (NSE events job), with NSE's row and the parsed XBRL | Forever |
| `archive/nse_events/promoter_group/batch={run time}.parquet` | Promoter-group members parsed in one NSE events run; a new file per run, never rewritten | Forever |
| `clean/current/promoter_group.parquet` | One row per company, quarter and promoter-group member, rebuilt from the batches | Rewritten daily |
| `clean/reports/{date}.json` | What each rule removed, flagged or couldn't place | Forever (small) |
| `clean/latest.json` | Pointer to the last complete run, written last | Rewritten nightly |
| `archive/_backfill/nse_{dataset}.json` | Backfill progress: chunks done, with row counts | Forever (small) |
| `clean/reports/backfill/{date}_{dataset}.json` | One backfill run: chunks, rows fetched / added, where it stopped | Forever (small) |
| `reference/nse_calendar.json` | Trading sessions, special sessions, holiday lists by year | Forever |
| `reference/security_lists/{date}/` | NSE equity lists as fetched | 30 days |
| `raw/…/{date}/`, `canonical/…/{date}/` | Dated 90-day snapshots from the writer | 14 days once archived |

## Storage

Each nightly snapshot repeats the full 90-day window, so one filing is
stored up to ~60 times. The archive stores it once. `R2 Retention (weekly)`
deletes dated snapshots older than 14 days that the archive has absorbed.
It is a **dry run** until the repository variable `R2_RETENTION_DELETE` is
set to `1`. It never touches a dataset that has no archive (the rights and
preferential snapshots in `canonical/` are not archived; the window filings
in `archive/nse_events/issues/` are), and it keeps market-cap history,
manifests, the calendar and everything under `archive/` and `clean/`.

The current Streamlit pages still read dated `canonical/` files through the
run-date selector; with retention on, that selector offers the last 14 days
until the pages move to `clean/`.

Nightly bulk and block deals are read from NSE's uncapped CSV export
(`scripts/nse_deals_csv.py`), not the JSON form (70 rows per call).

## Raw layer (`raw_v2/`, write-once)

`insiders_clean/raw_store.py`. The exact bytes an exchange sent, never
filtered: round trips, duplicates, amendments and unreadable dates all stay.

| Key | What |
|---|---|
| `raw_v2/{source}/{dataset}/blobs/{sha256[:2]}/{sha256}.{ext}` | Response body, byte for byte, named by its own SHA-256 (same bytes = one object) |
| `raw_v2/{source}/{dataset}/fetches/{YYYY-MM-DD}/{utc timestamp}_{sha12}.json` | One record per fetch: URL, parameters, HTTP status, content type, UTC time, size, hash, collector, git commit, covered date range |

The NSE events collector stores board meetings, tender offers and daily
buyback reports here too (`raw_v2/nse/{meetings|tenders|daily_buybacks}/`),
through the client's `on_response` hook before parsing; a failed raw write
fails that stream for the night.

Written with `If-None-Match: *` (never overwrites); no retention job touches
it. The NSE events job stores the further-issue lists and XBRL files there
directly (`raw_v2/nse/further_issues/`, `raw_v2/nse/further_issue_xbrl/`);
a failed raw write is counted in its report (`raw_not_stored`). Delete protection in the bucket (R2 object lock / lifecycle) is the
owner's to set; code cannot prove it. Wired into the NSE history backfill and
the nightly collectors. A failed raw write fails the backfill chunk; in the
nightly the flush step goes red.

Shareholding XBRLs (`raw_v2/nse/shareholding_xbrl/`, from the first run after
12 Oct 2026) are the one dataset stored compressed: gzip of the bytes NSE sent,
with no timestamp so the same file is one blob; `params.sha256_as_sent` in the
fetch record is the hash of the uncompressed file. Kept, no longer discarded,
because the member lists are a second parse of the same file and a parser fix
should re-read it without asking NSE again. Size: 70 KB to 1.2 MB as sent
(ASIANPAINT 1.16 MB), about 30 times smaller compressed (ASIANPAINT 35 KB), so
roughly 100 MB a quarter for ~2,400 companies. A raw write that fails never
stops the parse.

Ownership by investor type (`clean/current/shareholding.parquet`, columns
`mf_pct`, `fpi_pct`, `retail_pct`, ... in `docs/DATA_DICTIONARY.md`) is a third
parse of the same file (`collectors/nse_events/parsers.parse_shp_categories`).
Each type is the sum of the SEBI sub-categories mapped to it; nothing is filled
by difference. `categories_check` says whether every filed subtotal equals its
sub-categories and the types add up to the total; `categories_unmapped` names
any shares or category that did not map. The run report's shareholding
coverage counts `categories_status`, `categories_check`, rows with something
unmapped, latest filings with the types, and `pending_categories`. Filled two
ways: `run_daily --dataset shareholding --reparse-raw` (workflow input
`reparse_raw=1`) re-reads every XBRL kept here, checks its SHA-256, and writes
the columns on that filing's archive row, with no NSE call and `last_seen`
untouched; a filing with no raw copy (fetched before 12 Oct 2026) is fetched
again by the normal path whenever it is in the listing window (`days=400`,
`chain=1` for four quarters), and the download is kept raw like any other.

## Product window

The product holds transactions dated on or after 8 Oct 2025: the last one
year as of 08 Oct 2026, growing daily from there
(`insiders_clean.pipeline.PRODUCT_START`; owner, 08 Oct, confirmed 09 Oct).
Anything older stays in the archive and never reaches a clean table. The clean
step removes them with counted reasons `before_product_start` and
`no_readable_transaction_date` (insider ranges use their last day). Reversible:
change the constant and rerun the clean step.

Further issues are not cut at the window: an allotment posted before it still
has lock-ins expiring inside it. The cleaning report counts them
(`posted_before_product_start`).

## Further issues (preferential, rights, QIP)

`insiders_clean/issues.py`. Stage records are linked by ISIN (one approval in
the 180 days before, else no link). From the XBRL: the filed ICDR minimum and
relevant date, every proposed allottee, the filed lock-in lines, and QIP
allottees. A link is dropped when the approval proposed fewer securities than
were allotted (`more_shares_than_approved`; seen on real filings, e.g. Kanpur
Plastipack and Lloyds Metals). Lock-in dates use the filed lines where present
and the rule (promoters 18 months, others 6, from trading approval) otherwise.
Our own ICDR estimate (90/10-session VWAP before the filed relevant date) is
computed only beside the filed figure, from `prices/daily/` for the months it
needs, and left blank across a split or bonus.

## Promoter-group link (insider filings)

The clean step reads `clean/current/promoter_group.parquet` and adds
`promoter_group_id` to every insider filing whose filer is in the company's
latest promoter-group list (`insiders_clean/promoter_group.py`). Identity only:
the filer's `person_id` (`entity_key` of the name) equals a member's key, or the
name before a bracket does on either side (a HUF with its karta, a trust with
its trustees, a filer's former name). Never by similarity: "JSL Overseas Holding
LTF" stays unlinked from "JSL Overseas Holding LTD". The cleaning report's
`promoter_group_link` counts, for promoter-role and for director/KMP filings:
all, in a company with a list, linked, linked through the bracket rule, and up
to 20 unlinked promoter filers by name. Nothing is removed or held back.

Checked on real data, 12 Oct 2026: NSE PIT filings of Jan-Mar 2026 for 50
companies with promoter trades, against their Jun 2026 lists: 557 of 665
promoter-role filings link (83.8%; 22 through the bracket rule). The unlinked
are spellings that differ ("Kakatiya Industries (P) Ltd", "M/s Kewal Kiran
Finance Private Limited", initials for a middle name) and one company whose
promoters changed between the filings and the list (CRESTO: the seven Q1
buyers are not in the Jun list). None of 44 director/KMP filings there named a
group member.

## Intraday round trips (deals)

Same client, security and day with equal buy and sell size (within 1%) are
real trades without a change of ownership. Raw and archive keep them with
`intraday_round_trip` = true; the clean step excludes them (reason
`intraday_round_trip`). The archive stores that column as boolean, or as text
when old rows lack it, so read it with `insiders_clean.missing.as_flag`, never
`astype(bool)` (`'False'` is truthy). Rows dropped before 09 Oct 2026 in the
nightly-collected window are lost; the backfilled window was recovered with
`--redo` (+6,460 bulk rows).

## Rules

Insider trades (`insiders_clean/insider.py`):

- **Trade type** from the mode of acquisition. Only `market` is a decision to
  buy or sell; ESOP, gift, inter-se, off-market, preferential, pledge,
  scheme, conversion, offer for sale, bonus, rights and allotment are kept
  but never counted as market trades. Unknown modes are reported.
- **Side** from the transaction type; the mode is a fallback only.
- **Revisions**, in this order: (1) a filing whose `prevAppId` names a
  filing we hold replaces it (`superseded_by_revision`); (2) a filing NSE
  lists as `Revision` (`typeOfSubmission`) without `prevAppId` replaces the
  one earlier NSE filing (other appId, broadcast before it) with rows of the
  same person, security, trade dates and kind, preferring one of the same
  side (`superseded_by_revision_marker`); two or more candidates: nothing is
  removed, counted as `revision_marker.ambiguous`; none: `no_original`. This
  catches the correction of a quantity or value, which changes the very
  fields the content match compares (audit W10). (3) The BSE copy of a
  replaced NSE row goes too (`bse_copy_of_replaced_filing`), unless it is
  also a copy of a row still kept. (4) Content: same person, security, side,
  quantity, value, dates, holdings before and after; the latest broadcast
  wins. NSE's markers (`prevAppId`, `typeOfSubmission`, `revisionRemark`)
  are captured by `nse_insider.py` since 09 Oct 2026; most re-filings are
  marked `Original`, so (4) stays.
- **Truncated names** (NSE cuts at ~30 characters) are merged within one
  security on a unique prefix match: a name cut mid-word, or cut at a word
  boundary when its raw spelling is 26-32 characters. Never when the added
  words make another legal person: an HUF, a trust, a family, a foundation,
  or a company when the shorter name is no company ("Ramesh Kumar Agarwal"
  and "Ramesh Kumar Agarwal HUF" stay two; audit W5).
- **% of market cap** = value / market cap on the trade's last day
  (`market_cap_at_trade`), from NSE's daily mcap file
  (`marketcap/daily/nse/YYYY-MM.parquet`, issue size x close, read only by
  `clean_writer.py`), matched on the NSE symbol (the filed NSE symbol where
  today's has no figure, e.g. after a rename), as of the session itself or
  the last one before it within 10 calendar days. No dated figure (BSE-only
  names; trades after the layer's last day, as the layer is extended by the
  Price backfill workflow): the latest market cap, `market_cap_basis` =
  `latest`. `market_cap` stays the latest (the size of the company today:
  study universe, token rule). Counts in `tables.*.market_cap_basis` and
  `market_cap_layer` (audit W1).
- **Deadlines**: SEBI PIT Reg 7(2)(a) insider -> company and 7(2)(b)
  company -> exchange, each within 2 trading sessions. BSE rows from the
  nightly page capture don't (rows from BSE's insider CSV do); those rows don't
  carry the intimation date, so only NSE rows get both checks.
- **Held back for a look** (`needs_review`): unmatched security, unknown
  mode, value over 25% of market cap, a market trade that multiplies the
  holding more than 20x, zero value or no shares on a market trade, mode
  contradicting side, and the data checks below.
- **NSE/BSE copies of one filing** are linked; NSE is primary. A BSE row is
  a copy only when person, ISIN, side, kind, shares and trade dates agree,
  and each NSE row takes at most one BSE row (in date order); an NSE row is
  never demoted, so a buy and a sale of the same size on one day stay two
  trades (audit W3). Dates agree on the last day of the trade, except for a
  BSE nightly row (the capture files the from-date as the to-date), which
  agrees when its date lies inside the NSE row's span (audit W4). Counted
  in `nse_bse_copies`.
- **One BSE filing in both BSE feeds** (the nightly page capture and BSE's
  insider CSV) is one row: BSE rows are matched on the from-date (the capture
  files only that), the CSV's row is kept (it adds the to-date and the
  intimation date) and the other is removed as `bse_same_filing_two_feeds`.
  The report counts BSE input rows by feed (`bse_rows_by_feed`).

## Data checks (insider filings, from the 09 Oct brief)

Each check is a counted outcome in the cleaning report
(`tables.insider_trades.data_checks`) and on the Data page. A failing row is
either **held back** (a flag in `flags`, so `needs_review` keeps it out of
signals, rankings and totals) or **marked** (a name in `marks`, counted in
`marked`, nothing held back). Nothing is corrected: a row keeps the numbers
it was filed with. Counts are before the product window, like every flag
count.

| Check | Column | Held back or marked, and why |
|---|---|---|
| Holding after - holding before = shares traded, up for a buy, down for a sale (within 1% or 1 share) | `holding_check`: `match`, `differs`, `against_side`, `against_side_and_differs`, `not_filed`, `not_applicable` (no side, or a pledge) | Held back: `holding_change_differs_from_quantity` (size) and `holding_moves_against_side` (a buy that lowers the holding). When the holdings contradict the side or size, the direction or the size of the trade is in doubt, and every signal rests on both |
| Implied price (value / shares) inside the low-high of the trade's sessions in our own price layer (`insiders_clean/day_range.py`; both exchanges, traded series only, 2% tolerance for charges and rounding) | `price_check`, `day_low`, `day_high`; market trades only are acted on | Held back: `value_off_by_power_of_ten` (price x 10^2, 10^3, 10^5, 10^6 or 10^7 either way lands inside: value filed in lakh, crore, thousand, million or paise), `quantity_value_swapped`, `price_far_outside_day_range` (more than 20% beyond the band: 20% is the widest fixed daily price band on NSE and BSE, so charges or rounding never explain it and a trade date one session off rarely does; F&O stocks have no fixed band). These make `value` and `% of market cap` wrong by a factor, or show a price no exchange trade those days could have had. Marked only: `price_outside_day_range` (2% to 20% outside), because the tolerance is not yet measured on real filings; the diagnostic below measures it. ESOP, preferential, gift and other non-market rows are priced off the market by design: their outcomes are counted by kind, never flagged |
| Disclosure dated before the trade, or in the future | flags | Held back: `disclosed_before_trade` (told the company or published before the trade's last day), `disclosure_dated_in_future` (intimation or broadcast after the run date), `trade_date_in_future`, `dates_out_of_order` (from after to, intimation after broadcast). The broadcast time starts every return's clock (`docs/PRODUCT.md`), so a filing whose dates cannot be in that order cannot be timed |
| Holding-only disclosures (on appointment, on becoming a promoter) | `kind` = `holding_only` | Not a flag: the row is kept as filed, but becomes kind `holding_only`, `is_market` false and no side, so it is never counted as a trade. Recognised from the numbers, not the wording: no shares and no value filed, a holding filed and unchanged (pledges keep their kind). Needed because NSE's nightly parser files an empty transaction type as `Acquisition`. Counted with the kind it was filed as (`data_checks.holding_only`) |

Price check outcomes that mean "not checked" are counted with their reason:
`no_price` (no shares or value), `no_isin`, `no_dates`, `span_too_long`
(over 31 days), `before_price_layer` / `after_price_layer` (the price layer
is extended by the Price backfill workflow, not nightly, so recent filings
can be after its last day), `no_print` (no trade printed for the ISIN in the
span) and `no_price_layer`. The months read, missing or unreadable are in the
report under `price_layer`.

**Diagnostic** (read-only): Actions -> **Data checks diagnostic** runs the
clean step on R2 data through a client that refuses writes, and leaves
aggregate counts, how far outside the range market trades fall, and the rows
each check touched (filing number and link, no names) as a run artifact
(`scripts/data_checks_diagnose.py`). Use it to set the 2% tolerance and to
decide whether a price a little outside should be held back.

Not checked for deals: a bulk or block deal's price against the range. Whether
NSE's and BSE's bhavcopy high and low include the block-deal window has not
been verified, so a block price outside them might be normal.

Deals (`insiders_clean/deals.py`): same execution in the bulk and block feed
counted once; same client, security, day and side rolled up with a
volume-weighted price; counterparties listed; % of market cap on the deal's
day, as for insider trades.

**NSE and BSE deals are never copies of each other** (audit W8). Each
exchange publishes the bulk and block deals executed on its own platform:
SEBI's bulk-deal circular (Jan 2004) has brokers report to the exchange
every transaction in a scrip above 0.5% of its listed shares and the
exchange disseminate them the same day; SEBI's block-deal guidelines
(Sep 2005, `sebi.gov.in` circular 8382) put block trades in a separate
window on each exchange, which disseminates its own. Our fixtures agree:
BSE's lists carry BSE scrip codes and no exchange field, NSE's carry NSE
symbols. So a client's NSE leg and BSE leg on one day are two executions,
even of the same size (a split order): both are primary and both count.
Equal legs are only marked (`same_size_on_other_exchange`) and counted
(`same_size_on_both_exchanges`: legs, and legs at the same price within
0.05%). A BSE leg would be demoted only as a duplicate of the same record,
which the feeds never produce across exchanges (one record is in one
exchange's file).

Split and bonus adjustment (`insiders_clean/adjust.py`, used by
`precompute_slim.py` for prices and the Track record, and by the ICDR
estimate): a reset in the exchange's base price is applied only as a split
or bonus. Where NSE or BSE filed a corporate action (`actions`,
`bse_actions`) between the previous print and the session, the action
decides: a bonus n:h (factor h/(h+n)) or split (new / old face value)
within 1.5% of the price's factor is applied, even under the 5% line
(`kind_basis` = `action`); a factor that differs from the filed ratio is
not (`action_mismatch`); a large reset on a date with only a dividend,
rights or buyback filed is never a bonus (`action_not_split_bonus`: a 20%
special dividend is 0.8, the factor of a 1:4 bonus). Where nothing is
filed (BSE-only names, dates before the action history) the reset is
guessed from clean ratios within 1.5%: 1/k and k for k up to 20, a/(a+b)
for a and b up to 5, and h/(h+n) for h of 6 or 10 and n up to h + 1 (1:6,
1:10, 3:10, 7:10, 11:10; audit W7). The guess covers about half of all
factors between 0.05 and 0.95 (35% before), so it can still take a rights
issue or demerger for a bonus; bonus ratios with 7, 8 or 9 held are left to
the filed actions, since with them almost any reset matches. Counts:
`adjust.coverage(...)['by_basis']`, printed by Precompute slim assets.

Securities (`insiders_clean/securities.py`): NSE's equity lists (main + SME)
and BSE's list win on identity; the 01 Sep Value Research export only
supplies sector and industry.

## Backfill

`scripts/nse_history_backfill.py` loads NSE's history into the same
archive, so the nightly clean step rebuilds the clean tables over all of it.

| Dataset | Endpoint | Default range | One call |
|---|---|---|---|
| `insider` | `/api/corporates-pit` (JSON) | one year back - 02 May 2026 by default (NSE serves from 19 Nov 2015; NSE's new system from 03 May is the nightly's) | a calendar quarter |
| `bulk` | `/api/historicalOR/bulk-block-short-deals`, `csv=true` | one year back by default (NSE serves from Jan 2004) - the day before the earliest nightly record | a calendar year |
| `block` | same | one year back by default (NSE serves from Nov 2005) - the day before the earliest nightly record | a calendar year |

Run it from Actions -> **NSE History Backfill** (dataset, from, to,
dry run; dry run is the default and writes nothing), or locally:

    python scripts/nse_history_backfill.py --dataset insider --dry-run
    python scripts/nse_history_backfill.py --dataset all

- **Pacing**: one warm-up of nseindia.com, one browser User-Agent for the
  whole run, 4-6 s between calls; network errors and 5xx are retried 3
  times, then the chunk is reported and left for the next run.
- **Stops** at once on HTTP 401/403/429 or a body that is not JSON/CSV; the
  report's `stopped_at` names the chunk. Everything before it is kept.
- **Resume**: rerun the same command. Chunks listed in
  `archive/_backfill/nse_{dataset}.json` are skipped.
- **Fallback** when NSE blocks the GitHub runner: run on a home connection
  with `--local-out DIR` (writes each chunk's canonical Parquet to DIR, no R2
  needed for insider; deals need `--to`), then
  `--upload-from DIR` with R2 credentials to merge those files into R2.
- **What it writes**: rows go through `r2_writer.rows_to_parquet_bytes`
  (intraday round trips FLAGGED in `intraday_round_trip`, never dropped) and `archive.merge_partitioned`
  with first_seen = last_seen = the run date. `_state.json` gets `records`
  and a `backfill` entry; `last_merged` is never moved (retention reads it),
  and no state file is created where the nightly has not built one.
  Backfilled rows carry `source` = `nse_corporates_pit_history` or
  `nse_historical_deals_csv`, are never counted as possibly withdrawn, and
  never set `last_merged`.
- Rows with impossible dates (a 2024 filing with a trade date in 3034) are
  stored as they came and counted in the report; the cleaner flags them.
- **`--redo`** (workflow input `redo`) refetches chunks already marked done.
  The merge is idempotent (same row id: only `last_seen` moves).
- Raw responses are stored in `raw_v2/` before parsing when writing to R2.
- Don't run it during the nightly R2 Storage Write run (18:00 UTC): both
  write archive partitions.

The clean step was measured on a synthetic full history (154k insider
filings, 510k bulk/block rows): 19 s and 1.9 GB peak for the whole
process (136 s and 2.7 GB before the per-group Python calls were removed).

### Board meetings (results dates)

Actions -> **NSE Corporate Events (daily)** with dataset `meetings` and
`from` = `2025-07-01`: one call per calendar month from that day to 60 days
ahead (18 months from a mid-October run, about 2 minutes), each response into `raw_v2/` first, then
merged by `event_id`. Starting in July 2025 covers the results season before
the product window (08 Oct 2025), so October 2025 trades have their window.
Then run **Clean only** so insider trades get the trading-window columns.

## BSE history

`scripts/bse_history_backfill.py` (insider, bulk, block) and `collectors/bse/events.py`
(SAST, corporate actions) read BSE's own history endpoints (`collectors/bse/client.py`;
parameters and caps confirmed 12 Oct 2026). Run from Actions -> **BSE History Backfill**
(dataset, from, to, redo, dry run; dry run is the default), or locally:

    python scripts/bse_history_backfill.py --dataset all --dry-run
    python -m collectors.bse.events --from 2025-10-08 --dataset sast --dry-run

| Dataset | Endpoint | One call | Cap |
|---|---|---|---|
| `insider` | `Corp_Regulation_DownloadCSV_ng` (the insider page's CSV download), filtered on the date reported to BSE | 10 days | none seen; the JSON form `getCorp_Regulation_ng` stops at 25 rows, so it is not used |
| `bulk` / `block` | `BulkDealData_ng?DealType=1/2`, filtered on the deal date | 10 / 31 days | none seen |
| `sast` | `Corporatesast?ddlregul=ALL`, filtered on the first acquisition date | a month, read three ways (below) | none seen, but some windows answer `[]` |
| `actions` | `DefaultData?strSearch=S`, filtered on the ex-date | a month | none seen (a year = its months) |

- **Nightly** (R2 Storage Write, before the clean step): insider and deals for the
  last 10 days (`--recent 10`), SAST and actions for the last 30. The page capture
  (`bse_raw_capture_v2.py`) reads BSE's defaults only (today's deals; the day's
  insider filings plus a fixed older block), so a missed day was never filled.
- **Deals** map to exactly the nightly row, so a deal both stored has one id; a
  row already in the archive is not written again (`already_in_archive`).
- **SAST** answers `[]` for some windows that hold rows (08-14 Mar 2026 `[]`; 01-31
  Mar 2026 has 315 rows in those days). Every window is read whole, in 7-day
  pieces (a piece answering `[]` is split down to one day) and in 7-day pieces
  shifted by 3 days, united by `event_id`; weekdays with no row in any are listed
  in the report.
- **In-page fetch**: requests with BSE's own Origin and Referer answer (the `bse`
  package does the same for market cap from GitHub's runners). On a 401/403/429 the
  client moves to an XHR from inside a bseindia.com page in headless Chrome for the
  rest of the run (`via: in_page_xhr` in the raw fetch record); tried 12 Oct, same
  answers as requests.
- Pacing 4-6 s, 3 retries, stop on 401/403/429; resumable through
  `archive/_backfill/bse_{dataset}.json`; reports in `clean/reports/backfill/` and
  `clean/reports/bse_events/`. Shares the `r2-archive-writes` concurrency group.

## Trading calendar

Seeded from the days NSE traded per the Paresh project's close history
(30 Sep 2024 to 01 Oct 2026). Each night a bhavcopy check on two NSE
archives confirms the days since; NSE's holiday list for the year marks
special sessions (Muhurat, Budget weekends), which don't count as trading
days. An answer that needs a day not yet confirmed is left empty. No
hand-edited file is needed in any year.

## Tests

`python -m pytest tests -q`. Real NSE filings fetched 07 Oct 2026 are in
`tests/fixtures/nse_pit_real.json` and go through the production writer's
own `canonicalize()`.

**Calibration, 12 Oct 2026** (read-only diagnostic, 8,609 market trades with a price layer): 8,003 inside the
traded range, 106 between 2% and 20% outside (marked only: about 1.2%, mostly multi-day trades priced at an
average), 215 more than 20% outside. Most of those 215 were two filing errors, now named and held back with their
own reasons: the value field holding one share's price (`value_filed_as_price_per_share`) and shares valued at
face value, Rs 1-10 (`valued_at_face_value`). The 2% and 20% tolerances stay.
