# Clean layer

The site reads clean tables, not the exchange data as collected. This page
says where they live, what each rule does, and how storage is kept small.

## Nightly order (R2 Storage Write workflow)

1. Collect and validate NSE + BSE (unchanged).
1b. Every collector saves each response's exact bytes locally at fetch time
   (`scripts/raw_capture.py`); `scripts/raw_flush.py` then stores them in the
   write-once `raw_v2/` layer (see "Raw layer").
2. `scripts/r2_writer.py` writes `raw/` and `canonical/` for today. Intraday
   round-trip deal legs are flagged (`intraday_round_trip`), no longer dropped.
3. `scripts/update_calendar.py` extends the NSE trading calendar.
4. `scripts/clean_writer.py` merges today's canonical files into the archive
   and rebuilds the clean tables from the whole archive.

Steps 3 and 4 are `continue-on-error`: they can never fail the collection.

## R2 layout

| Key | What | Kept |
|---|---|---|
| `archive/canonical/{exchange}/{category}/year=YYYY/quarter=Q.parquet` | Every collected record once, with `first_seen` / `last_seen`, partitioned by the record's own date; past quarters are written once, then only read | Forever |
| `archive/canonical/{exchange}/{category}/_state.json` | Last run merged, record count, partitions written that night | Rewritten nightly |
| `clean/current/insider_trades.parquet` | One row per filing, cleaned, full history | Rewritten nightly |
| `clean/current/deals.parquet` | One row per client, security, day, side | Rewritten nightly |
| `clean/current/securities.parquet` | One row per security used | Rewritten nightly |
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
set to `1`. It never touches a dataset that has no archive (rights and
preferential issues are not archived yet), and it keeps market-cap history,
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

Written with `If-None-Match: *` (never overwrites); no retention job touches
it. Delete protection in the bucket (R2 object lock / lifecycle) is the
owner's to set; code cannot prove it. Wired into the NSE history backfill and
the nightly collectors. A failed raw write fails the backfill chunk; in the
nightly the flush step goes red.

## Product window

The product holds transactions dated on or after 8 Oct 2025: the last one
year as of 08 Oct 2026, growing daily from there
(`insiders_clean.pipeline.PRODUCT_START`; owner, 08 Oct, confirmed 09 Oct).
Anything older stays in the archive and never reaches a clean table. The clean
step removes them with counted reasons `before_product_start` and
`no_readable_transaction_date` (insider ranges use their last day). Reversible:
change the constant and rerun the clean step.

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
- **Revisions** are recognised by content (same person, security, side,
  quantity, value, dates, holdings before and after); the latest broadcast
  wins. NSE's `prevAppId` is not captured by `nse_insider.py`, and real
  corrections arrive without it.
- **Truncated names** (NSE cuts at ~30 characters) are merged within one
  security on a unique prefix match.
- **Deadlines**: SEBI PIT Reg 7(2)(a) insider -> company and 7(2)(b)
  company -> exchange, each within 2 trading sessions. BSE rows don't
  carry the intimation date, so only NSE rows get both checks.
- **Held back for a look** (`needs_review`): unmatched security, unknown
  mode, value over 25% of market cap, a market trade that multiplies the
  holding more than 20x, holding change that doesn't match the quantity,
  zero value on a market trade, mode contradicting side, dates out of
  order or in the future.
- NSE/BSE copies of one filing are linked; NSE is primary.

Deals (`insiders_clean/deals.py`): same execution in the bulk and block feed
counted once; same client, security, day and side rolled up with a
volume-weighted price; NSE/BSE copies linked; counterparties listed.

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
