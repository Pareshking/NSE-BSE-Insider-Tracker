# Data dictionary

What each clean table holds, where it comes from and how often it changes.
Cleaning rules for insider trades and deals are in `docs/CLEAN_LAYER.md`;
signal thresholds in `docs/SIGNALS.md`.

| Table (R2) | Grain | Source | Updated |
|---|---|---|---|
| `clean/current/insider_trades.parquet` | One SEBI PIT filing | NSE + BSE insider filings | Nightly (R2 Storage Write) |
| `clean/current/deals.parquet` | Client x security x day x side | NSE + BSE bulk and block deals | Nightly (R2 Storage Write) |
| `clean/current/securities.parquet` | One security | NSE/BSE equity lists + VR export | Nightly (R2 Storage Write) |
| `clean/current/sast.parquet` | One SAST Reg 29 disclosure line | NSE `/api/corporate-sast-reg29` | Daily (NSE Corporate Events) |
| `clean/current/actions.parquet` | One corporate action | NSE `/api/corporates-corporateActions` | Daily |
| `clean/current/meetings.parquet` | One board meeting | NSE `/api/corporate-board-meetings` | Daily |
| `clean/current/shareholding.parquet` | One company x quarter | NSE `/api/corporate-share-holdings-master` + each filing's XBRL | Daily |
| `clean/current/tradability.parquet` | One ISIN (NSE equity series, or on an NSE surveillance list) | NSE `/api/reportASM`, `/api/reportGSM`, `/api/reportESM`, `sec_list.csv`, NSE bhavcopy | Nightly (R2 Storage Write; also Tradability flags) |

## NSE corporate events (`collectors/nse_events/`)

Every run fetches the last 10 days (board meetings: up to 60 days ahead as
well), so filings NSE adds late are still caught. Rows are merged into
`archive/nse_events/{table}/year=YYYY.parquet` by `event_id`, a hash of the
fields that identify the event; fetching an event again never adds it twice.
The year is the event's own date. Each row keeps NSE's payload in
`raw_json`, plus `first_seen` and `last_seen` (run dates). The clean tables
add `isin`, `company_display` and `unmatched_security` from the security
master. A per-run report goes to `clean/reports/nse_events/{date}.json`.

Not collected: concall announcements (no buy/sell information).

### sast — SEBI SAST Regulation 29

Reg 29(1): a holder crossing 5%. Reg 29(2): a 5%+ holder moving 2% or more.
Covers funds and individuals outside the promoter group, which insider (PIT)
filings don't; promoters appear too (`is_promoter`).

| Column | Meaning |
|---|---|
| `symbol`, `company` / `target_company` | Target company as filed |
| `acquirer_name`, `acquirer_id` | Acquirer or seller; `acquirer_id` is the cleaned-name key used for person/fund pages |
| `is_promoter` | NSE's promoter flag (`promoterType` = Y) |
| `regulation` | `Reg29(1)` or `Reg29(2)` |
| `action_type` | `Acquisition`, `Sale` or `Both` |
| `mode`, `is_market` | Mode as filed (Open Market, Inter-se transfer, Preferential Allotment, Others, Public Issue); `is_market` only for Open Market |
| `trade_date_from`, `trade_date_to` / `transaction_date` | From NSE's "dd-MMM-yyyy to dd-MMM-yyyy" |
| `shares_acquired`, `shares_sold`, `shares_after` | As filed |
| `pct_acquired`, `pct_sold`, `post_stake_pct` | % of share capital, as filed |
| `shares_traded`, `percent_equity_traded` | Acquired minus sold; empty when the filing gives neither (a filed 0 stays 0) |
| `broadcast_ts`, `application_no`, `attachment` | NSE's publication time, filing number, attachment link |

### actions — corporate actions

Kept: buyback, bonus, split, rights, dividend. Dropped and counted in the
report: interest payments, unit distributions, demergers, other schemes.

| Column | Meaning |
|---|---|
| `purpose` | `buyback`, `bonus`, `split`, `rights`, `dividend` |
| `subject` | NSE's text, e.g. `Rights 3:5 @ Premium Rs 45/-` |
| `ex_date`, `record_date`, `broadcast_date` | As filed |
| `ratio` | Bonus and rights ratio, e.g. `3:5` |
| `face_value`, `rights_premium`, `rights_issue_price` | NSE writes the premium over face value; issue price = face value + premium |
| `dividend_per_share` | Rupees; ordinary + special when both are in one action |
| `face_value_from`, `face_value_to` | Split |
| `needs_price_gap` | True for buybacks and rights. Buyback price and route (tender vs open market) are not in this feed |

### meetings — board meetings

Kept when the meeting considers results, dividend, buyback, bonus, fund
raising, split, rights or a preferential issue. NSE files an "intimation"
row whose purpose is only in its description, so purpose and description
are both read, and all notices for one meeting are combined.

| Column | Meaning |
|---|---|
| `meeting_date` | As filed |
| `purposes` | Comma list of the flags below |
| `results`, `dividend`, `buyback`, `bonus`, `fund_raising`, `split`, `rights`, `preferential` | True when the meeting considers it |
| `description`, `intimation_ts` | NSE's text and the latest notice time |

### shareholding — quarterly shareholding pattern

One row per company and quarter; a revised filing replaces the original.

| Column | Meaning |
|---|---|
| `quarter_end`, `submission_date`, `revised` | As filed |
| `promoter_holding_pct`, `public_holding_pct`, `employee_trust_pct` | % of total shares, from NSE's listing. Public holding is the free-float denominator |
| `promoter_shares`, `total_shares` | From the XBRL |
| `promoter_pledged_shares`, `promoter_pledge_pct` | Pledged shares, and as a **% of the promoter group's own shares** (Zee, Jun 2026: 2,060,000 / 38,316,284 = 5.38%, matching the filing) |
| `promoter_encumbered_shares`, `promoter_encumbered_pct` | Pledge + non-disposal undertakings + other encumbrance |
| `xbrl_status` | `ok`, `pending` (not fetched yet; at most 300 a night), `no_xbrl`, or `failed: ...` |
| `shareholding_stale` | True when this quarter's XBRL isn't parsed and the pledge figures shown are the company's previous quarter's |

### preferential and rights — NSE issue records, one row per stage record

NSE returns the latest 100 records of each stage a day, so the table is every daily snapshot stacked, newest snapshot per record winning. An issue has two records, **In-Principle** (board date, amount, consideration; preferential also the allottee category) and **Listing Stage** (offer price, shares allotted, allotment, listing and trading-approval dates; rights also ratio, record date, issue open and close). They have separate `app_id`s and no shared key, so a listing record is linked to its approval by ISIN: the one In-Principle record filed in the 180 days before it, if there is exactly one.

| Column | Meaning |
|---|---|
| `stage` | `in_principle` or `listing` |
| `posted_on`, `submitted_on` | NSE posting date (`systemDate`/`sysDateTime`; the fields NSE calls `boardResDate` hold this too, not the board meeting) and the date filed |
| `board_date`, `amount_total`, `consideration`, `allottee_category` | In-Principle fields (`PROMOTER`, `NON_PROMOTER`, `MIXED`); on a listing record they are copied from its linked approval |
| `offer_price`, `shares_allotted`, `shares_listed`, `allotment_date`, `listing_date`, `trading_approval_date`, `amount_raised` | Listing-stage fields |
| `ratio`, `record_date`, `issue_open_date`, `issue_close_date` | Rights, listing stage |
| `link_status`, `linked_app_id` | `linked`, `ambiguous` (more than one possible approval; nothing copied), `no_in_principle_in_data` (its approval is not in the latest-100 lists) |
| `amount_unreliable` | NSE's amount was zero or above ₹1 lakh crore; the amount is blank |
| `lock_in_promoter_until`, `lock_in_other_until` | Preferential only, linked records with a trading-approval date: +18 months for promoters, +6 for others; a `MIXED` allotment gets both because the split is not filed |

BSE's rights and preferential rows carry only company, scrip code and two stage dates, so they are not used here.

## Tradability flags (`clean/current/tradability.parquet`)

Can the stock be traded the normal way today? `scripts/nse_surveillance.py`, rules in
`insiders_clean/tradability.py` (thresholds in its `Config`). Flags only: no page or signal drops a row for them.
Sources confirmed with real answers on 12 Oct 2026 (fixtures in `tests/fixtures/tradability/`).

| Column | Meaning |
|---|---|
| `isin`, `symbol`, `series`, `last_price_date` | From the latest NSE bhavcopy row (equity series EQ, BE, BZ, SM, ST, SZ); an ISIN on a surveillance list but not in the bhavcopy keeps a row with its listed symbol |
| `as_of` | Day of the surveillance snapshot used |
| `asm_lt_stage`, `asm_st_stage` | Long- and short-term ASM stage (`I`-`IV`), from NSE's `asmSurvIndicator` |
| `gsm_stage` | GSM stage (`0`-`VI`), read from `survCode` (`GSM - 0 (99)`, `GSM III & IBC - Receipt (65)`). NSE's own `gsmStage` field is not the stage: it holds the code number in Roman numerals (`LXII` for code 62) |
| `esm_stage` | ESM stage (`I`, `II`), from `esmSurvIndicator` |
| `ibc_stage` | Insolvency code on NSE's GSM list: `Receipt` (IBC receipt of disclosure) or `I` (ASM IBC stage I) |
| `{list}_since`, `{list}_since_floor` | First snapshot of the unbroken run in today's stage. Snapshots start 12 Oct 2026; when the run reaches our first snapshot, `_since_floor` is true and the date reads "since at least" |
| `surveillance_codes` | NSE's `survCode`s, joined |
| `trade_for_trade`, `t2t_since`, `t2t_since_floor` | Series BE, BZ or ST in the bhavcopy (every trade settled by delivery); since = first day of the unbroken run in the last 3 months of prices loaded |
| `sme` | Series SM, ST or SZ (NSE Emerge) |
| `band_pct`, `band_text`, `sec_list_date` | Price band from NSE's `sec_list.csv` (2, 5, 10, 20, 40; `No Band` = blank, F&O names), matched by symbol and series |
| `circuit_days`, `circuit_last`, `circuit_last_side`, `circuit_window` | Sessions in the last 20 where the stock traded at one price all day (open = high = low = close, volume > 0) at the band: move from the previous close at least the band less 0.1 point and one paisa for the tick. Judged on today's band, so a band change inside the window can add or miss a day; names without a band are not judged |
| `trade_flags`, `trade_flag_notes` | Short labels (`GSM 0`, `ESM I`, `LT-ASM I`, `ST-ASM II`, `IBC`, `T2T`, `SME`, `5% band`, `Circuit 3/20`) and a one-line explanation each; a band is flagged at 5% or tighter |

Snapshots: `archive/tradability/surveillance/year=YYYY.parquet` (date, list, isin, symbol, company, stage, code,
description, listed_at) and `archive/tradability/sec_list/year=YYYY.parquet` (date, symbol, series, band), one per
day (a rerun replaces the day). Raw answers: `raw_v2/nse/{asm|gsm|esm|sec_list}/`. Report:
`clean/reports/tradability/{date}.json`.

Not available: **suspended** securities. NSE's `content/equities/suspension.csv` answers, but its newest entry is
16 Jul 2012, so it is not used; a suspended stock simply has no bhavcopy row. Bands before 12 Oct 2026 and
surveillance stages before that day are not known. BSE's own surveillance lists are not collected; BSE-only names
have no row.

## Archive and raw layer columns (not clean tables)

| Column | Where | Meaning |
|---|---|---|
| `intraday_round_trip` | `archive/canonical/.../bulk_deals`, `block_deals` | True when the row is a leg of a same-day, same-client, equal-size buy+sell. Absent on rows written before 09 Oct 2026; may be boolean or text, read with `as_flag` |
| `canonical_prev_app_id`, `canonical_submission_type`, `canonical_revision_remark` | archive, NSE insider | NSE's own revision markers from the filing list (clean table: `prev_app_id`, `nse_submission_type`, `nse_revision_remark`). Not part of the row id |
| `first_seen`, `last_seen` | archive | Run dates a row was first and last collected |
| `raw_v2/...` | R2 | Exact response bytes and one fetch record each: see `docs/CLEAN_LAYER.md` ("Raw layer") |

## Not yet collected

BSE equivalents of the four event tables (BSE's API needs an in-page fetch).
Buyback offer price and route, which need the offer documents.

## Prices (derived, `prices/daily/{nse|bse}/{YYYY-MM}.parquet`)

One row per exchange, date, ISIN, symbol, series, as printed in the exchange's UDiFF bhavcopy. Never adjusted. Raw files: `raw_v2/exchange_files/{nse_udiff_cm|bse_udiff_cm}/`.

| Column | Meaning |
|---|---|
| `date`, `exchange`, `isin`, `symbol`, `series`, `name`, `instrument_id` | Identity as printed that day (symbols and ISINs can change) |
| `open`, `high`, `low`, `close`, `last`, `prev_close`, `settle` | Prices in rupees, unadjusted; `prev_close` is the exchange's own previous close |
| `volume`, `value`, `trades` | Traded quantity, traded value, number of trades |

## Market cap (derived, `marketcap/daily/nse/{YYYY-MM}.parquet`)

NSE's daily `mcap` file from the PR zip. One row per date, symbol, series. Raw: `raw_v2/exchange_files/nse_pr_zip/`.

| Column | Meaning |
|---|---|
| `date`, `symbol`, `series`, `name`, `category` | Identity that day; category is Listed or Permitted |
| `face_value`, `issue_size` | Face value and shares in issue on that day |
| `close`, `market_cap` | Close in rupees; market cap = issue size x close (31 and 12 rows on the two sample days differ and are kept) |

## Price summary (derived, `artifacts/prices_summary_slim.parquet`)

One row per ISIN, rewritten after each nightly run by `scripts/precompute_slim.py`
(workflow "Precompute slim assets"), so the site never loads the full price table.
Prices adjusted for splits and bonuses only.

| Column | Meaning |
|---|---|
| `isin`, `symbol`, `name`, `exchange` | Latest identity; NSE preferred, BSE fills the gaps |
| `last_date`, `latest_close` | Last session with a print and its adjusted close |
| `high_52w`, `low_52w`, `pct_off_high` | Range over the 365 days to the last stored session; `pct_off_high` = close / high - 1 |
| `ret_90d`, `ret_180d` | Price change over 90 and 180 calendar days |
| `last_split_date`, `last_split_factor`, `n_splits` | Splits and bonuses seen in the price table |
| `market_cap`, `mcap_rank`, `mcap_bucket` | NSE market cap on the last stored day; bucket by rank (1-100 Large, 101-250 Mid, 251-500 Small, rest Micro), computed by us, not AMFI's list. BSE-only names have none |

## Adjustment factors (computed, not stored yet)

`insiders_clean/adjust.py` derives `factor = prev_close / previous close` per exchange and ISIN from the price table; `kind` is `structural`, `minor`, `none` or `unknown`. Adjusted price at T uses only factors dated up to T.
