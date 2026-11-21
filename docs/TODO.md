# To do

What is open, in order, and how we will know each is done. Update this the
same day something is promised, started or finished. Pages follow the data:
`docs/DATA_TO_PAGES.md` maps each dataset to the sections it unlocks.

The earlier body of this file (every dated section to 20 Nov 2026, with run numbers) is kept word for word in
`docs/TODO_DONE.md`. Rewritten 21 Nov 2026 from `main` at 3b6f6fd (#321).

## Fund-house files: every line archived, 21 Nov 2026 (branch `mf-all-lines`)

Owner: every line of every raw file must reach the database. The raw coverage audit (21 Nov) found the fund-house
parser kept equity only (ICICI 33,232 non-equity lines, nps_lic 66,409 only in raw), skipped sheets and summed
duplicate lines. Now every filled row of every sheet read goes to `archive/mf_lines/` with its kind (equity, debt,
money market, cash, derivative, other, from the workbook's own headings), and every sheet not read to
`archive/mf_sheets_skipped/` with the reason (`docs/DATA_DICTIONARY.md`); the equity tables are byte-identical
(`tests/test_mf_lines.py`). **Next:** after merge, run Mutual fund portfolios (workflow) once with `lines` ticked
(months and houses blank) to fill every month already in raw, then Raw coverage audit with sources `amc`: the
non-equity lines should be found stored; what stays is the rows of skipped sheets (index and notes sheets), named.


## Where things stand (21 Nov 2026)

- **Data.** NSE and BSE insider filings, bulk and block deals, SAST, corporate actions (NSE main board and SME board),
  board meetings, shareholding patterns (promoter group, public holders over 1%, ownership by investor type), further
  issues, results XBRL (broadcasts from 8 Apr 2025), tradability flags, a price layer (NSE + BSE bhavcopy from
  1 Jan 2025), market flows (NSE provisional FII/DII, NSDL FPI daily and fortnightly sectors, SEBI mutual fund trends),
  fund houses' month-end portfolios (44 mutual fund houses and 5 NPS pension fund managers, `collectors/mf_portfolios/
  houses.py`), and the four-level industry classification. Product window: transactions from 8 Oct 2025.
- **Site** (insiders.streamlit.app, from `main`): Dashboard (default), Today, Insiders, Funds, Deals, Stakes,
  Situations in the bar; Results, Calendar, Filings, Companies, Investors, Data health under More; the company page is a
  decision page. Page-to-table map: `docs/DATA_TO_PAGES.md`, "The site on 21 Nov 2026".
- **Storage**: R2 bucket 2.29 GB on 21 Nov 2026 (2.44 GB on 20 Nov before zstd and gzip of `.xls`/`.txt`, #307).
- **Runners**: everything runs on GitHub's hosted runners except `mf-portfolios-own.yml` (label `mf`), which waits
  for the owner's own machine (`docs/OWN_RUNNER.md`).

## Done 19-21 Nov 2026 (merged to main)

- **Fund houses.** One shared browser for Edelweiss and Bandhan (#308); Angel One, WhiteOak, Edelweiss and Bajaj
  refuse GitHub's runners by address and are kept apart (`houses.RUNNER_BLOCKED`, `NOT_COLLECTED` with the reason),
  Union refuses machines outside India (`INDIA_ONLY`); access-request emails drafted in `docs/MF_ACCESS_REQUESTS.md`.
  ICICI Prudential and AlphaGrep collected through their own list services, read on the runner (#304); Mahindra
  Manulife and Helios added (#301); 12 more houses (#288); NPS pension fund managers (#287). Scheme-by-scheme tables
  and the AMFI scheme count check (#302). Own runner workflow and setup (#309).
- **Funds explorer** (#293): month or 3/6/12-month windows, size and industry filters, month-to-date deals, lists by %
  of company and size, house positioning, coverage by value.
- **Price jumps** (#303): IIFL Finance's false 5:4 "bonus" (NSE's block window series `BL` taken as the day's price);
  side-window series never a close, no factor across a session the layer lacks, filed splits on a new ISIN or after a
  gap applied, BSE keeps its own factor where NSE did not print; the audit `clean/reports/price_jumps.json`.
- **Demergers and schemes kept in the action feeds**, NSE actions backfill by month (`run_daily --dataset actions
  --from`) (#311).
- **Demergers adjusted at the ex-date close** (#314, owner directive 20 Nov 2026, which reversed "splits and bonuses
  only" for filed demergers): `KIND_ADJUSTED = ('split_bonus', 'demerger')`; `docs/CLEAN_LAYER.md`, "Price
  adjustment".
- **NSE SME corporate actions** (#319): only `index=equities` was asked, so NSE SME names had no splits or bonuses on
  file; all 12 companies behind the study universe's 13 unexplained price jumps were NSE SME names with no BSE code.
  With the SME board asked, 12 of the 13 are explained. Left: GICL, 15 Oct 2025, with nothing filed on either exchange.
- **Industry classification, four levels** (#292; incremental save and resume #312; BSE four at a time #315):
  4,835 companies have all four levels; 867 NSE-only companies keep the VR export's two levels, because NSE refuses
  GitHub's runners; companies with no class went from 225 to 40. Used by Results, Funds and the Dashboard.
- **Speed** (policy in `docs/PRODUCT.md`, "Speed"), measured:
  - Industry fetch (#315): 26 minutes for 3,250 BSE scrips (was 6-7 hours one at a time).
  - Nightly BSE step (#316, shareholding XBRLs four at a time): 6.6 minutes (was about 25 of the nightly's 37).
  - Filing text (#318: a file filed twice read once, OCR one page per CPU, PPM pages): about 106 filings a minute
    (was 19: the 14 Nov run, 3,034 files in 161 minutes).
  - Mutual fund raw flush (#317: 16 at a time, fund houses side by side): under 30 seconds (was 47 minutes).
- **Results revenue line**: banks and insurers read under their own revenue line, `revenue_basis` (#310); statement
  lines read from same-period sibling contexts (`results.same_period`: 51 Sep 2026 filings, 43 Ind AS and 8 NBFC, had
  put the period end in a metadata context) and Ind AS 117 insurers (`INS_IND_AS`, `InsuranceRevenue`, e.g. GODIGIT)
  (#321). Before #321, 55 companies of the Sep 2026 quarter had no revenue line. FY quarter, size and industry
  filters, KPI cards and sector roll-up on Results (#290); like-for-like basis comparisons (#297).
- **Raw coverage audit** (#320, read-only, `raw-coverage.yml`): of 83 `raw_v2/` datasets, 5 fully captured, 45 with
  gaps, 31 not checked, 2 with no parser found.
- **Site**: Dashboard (#296), company decision page (#299), bought-or-sold charts on Insiders, Deals, Stakes, People
  & funds, Holders and Investor flows (#294, #305), one date control on every dated page (#291, #298), controls
  redesign with radius tokens and no pill shapes (#300), Streamlit 1.67.0 (#295), block deals with the seller counted
  once (#289), Parquet written with zstd (#307).

## In progress (branches, not merged)

Owner, 21 Nov 2026: every raw line must reach the database from now on (`docs/PRODUCT.md`, "Raw retention").
- `mf-all-lines`
- `events-keep-all`
- `bse-shp-archive-all`

Done when: merged, and a Raw coverage audit run after them shows no dataset with gaps that is not named here.

## Open, in order

| # | Item | Done when |
|---|---|---|
| 1 | **The weekly Storage trim deletes by age, against the raw retention decision of 21 Nov.** `storage-trim.yml` runs every Sunday at 06:23 UTC with `--delete` and every step: `price_zips` deletes NSE PR zip blobs older than 30 days from `raw_v2/` (only the market cap is parsed from them), `filing_text` deletes every filing-text day file but today's, `results_xbrl` deletes raw results XBRL whose facts are in the archive. The next scheduled run is Sunday 22 Nov 2026. Not changed in this docs pass | the schedule or its steps changed to match the decision (or the owner confirms each step) |
| 2 | **Results rebuild after #321**: `clean/current/results.parquet` is rebuilt by the NSE events run; until then the 55 companies stay without a revenue line on the site | after the next NSE events run, `clean_peek RESULTS_BASIS` shows the Sep 2026 quarter's companies without a revenue line, each named |
| 3 | **Raw coverage: 45 datasets with gaps, 31 not checked, 2 with no parser** (#320). The three branches above cover part of it | every dataset fully captured, or its gap named here with the reason; the 31 checked (whole, not sampled) |
| 4 | **867 NSE-only companies at two industry levels**: NSE's quote API refuses GitHub's runners (`docs/DATA_DICTIONARY.md`, Industry classification). 40 companies have no class at all | they have NSE's four levels (a machine NSE answers, such as the own runner), or each is named with why not |
| 5 | **Own runner** for Angel One, WhiteOak, Edelweiss, Bajaj (and Union, from India): owner sets it up (`docs/OWN_RUNNER.md`) | the first "Mutual fund portfolios (own runner)" run collects them |
| 6 | **Fund houses not collected**: Kotak (Radware CAPTCHA), Navi (Cloudflare challenge), Union (outside India refused); access requests in `docs/MF_ACCESS_REQUESTS.md` are the owner's to send. NPS: UTI and Max Life (expired certificates), HDFC Pension (Akamai), Kotak (bot check), Tata (list never loads headless); Aditya Birla's October link answered 404 on its own site | each collected or its reason re-checked monthly |
| 7 | **HDFC 2025-12 scheme rows**: a `--schemes --house hdfc` run reports what differs (`differs`) | that run's report is read |
| 8 | **Dispatches named in the merged PRs, not confirmed from here**: `alphagrep` 2026-07..2026-10 and `icici` 2025-10..2026-08 (#304); Price backfill for the weekend sessions 2025-02-01, 2026-02-01, 2026-11-08, then Precompute slim assets (#303); Market flows backfill from 2025-10-08 (#283); NSE bulk and block deals refilled from 13 Nov 2026 (the nseindia.in move, #274) | each run's report read and noted here |
| 9 | **Price jump left unexplained**: GICL, 15 Oct 2025, nothing filed on NSE or BSE. The `insiders_clean/price_jumps.py` docstring still says a demerger's factor is applied only on an exchange base-price reset; since #314 it is also applied at the ex-date close | a filing or source explains GICL, or it stays named in the audit; the docstring matches `adjust.py` |
| 10 | **Filing text downloads up to 4 at once per host** (`scripts/filing_text_extract.py` `PER_HOST`), NSE's archive host included; the speed policy says never in parallel to NSE | the owner confirms, or NSE hosts are kept to one at a time |
| 11 | **Cash, TREPS and receivables per fund house**: the collector keeps equity lines only | parsed from raw (the `mf-all-lines` branch may cover it) |
| 12 | **Public holders**: not read for BSE-only companies (`bse_shareholding` inline XBRL). `promoter_group.pct_of_company` is 100 times too big for taxonomy 2025-05-31 filings (MOTILALOFS Jun 2025: 2122 for 21.22%; `parsers.parse_shp_members` multiplies the filed % by 100) | both fixed and tested |
| 13 | **Two directors, same rupees and %** (Vectras Enprocon): read `tables.insider_trades.same_trade_two_names` and the rows' `app_id` (`clean_peek TRADES:<code>`) | removed only if it is one filing |
| 14 | **NSDL's DII pages** (`DIIGenerateReport.aspx`) not read | read, or a reason |
| 15 | **ICDR minimum by VWAP** for issues that do not file it: needs each issue's relevant date, which no source we collect carries | a source with the relevant date |
| 16 | **Year-on-year before Apr 2025**: the older `corporates-financial-results` feed (pre-integrated XBRL, quarters Mar 2023 - Dec 2024) has no collector | owner decides |
| 17 | **Forward record of the Worth-a-look shortlist** (started 12 Nov 2026) | three months of picks measured |
| 18 | **Named-investor aliases** (`insiders_clean/investor_aliases.csv`) grow as names are checked | ongoing |
| 19 | **BSE**: rights terms not collected; BSE's recent SAST feed is thin for an unknown reason | collected; cause found |

Owner only: object lock or lifecycle protection on `raw_v2/` (R2 setting); the own runner (5); access emails (6); the
older results feed (16); a review of the 8 Oct baseline numbers (archived item C).

Resolved by the code since the last rewrite: `/today` is its own page since the Dashboard became the default (#296;
was D2).

## Parked or not re-checked

- **Parked 15 Nov 2026** (owner: no plan for the announcement reader or AI reading; the code is kept, nothing runs):
  supervised reader batches, headline format, concalls and annual reports, live-by-day reading, the text cache fill,
  the historical AI backfill (archived items Q, R, U, W, V, 29, 30; `docs/ANNOUNCEMENT_READER.md`). Announcement
  collection without AI still runs nightly (`announcement-collect.yml`); filing text runs by hand only.
- Not re-checked on 21 Nov 2026: run-4 reader findings (S), the context engine (T), Investors and Companies pages as
  designed in `docs/DESIGN_V3.md` (X4, X5), the blueprint review (31, `docs/BLUEPRINT_TODO.md`). See `docs/TODO_DONE.md`.

## Decided, not to do

- Screener.in and Tijori are not scraped. The owner gave permission on
  08 Oct, but Screener's terms forbid copying or mirroring and its
  robots.txt disallows the paginated pages; Tijori's terms couldn't be read
  (rendered by script). Third-party re-packagers stay out (`docs/PRODUCT.md`, Sources).
- No prices token and no Paresh data: our own exchange bhavcopy layer covers NSE and BSE (Paresh's covers about 38% of NSE symbols with 2026 data).
- History: only the last one year (owner, 08 Oct); the site grows daily from there.
- **Group-level round trips (decided 12 Oct: not built).** Nothing in the NSE/BSE rows says two clients trading
  opposite sides the same day are related; a rule that pairs them would flag ordinary trades and break rule 7. It needs
  a source that names the group (a common PAN, or a filing that lists persons acting in concert).
