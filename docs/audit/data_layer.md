# Data-layer audit (REVAMP_PLAN Phase 3, data side)

Repo: `C:\Users\Quali\NSE-BSE-Insider-Tracker\.claude\worktrees\revamp` at `066fb19` (origin/main). Read-only: no repo file was changed.
Method: every file in the brief read line by line; fixtures in `tests/fixtures/` inspected; the suspected defects marked
**verified** were reproduced with a synthetic run of the production functions (script:
`C:\Users\Quali\AppData\Local\Temp\claude\C--Users-Quali-NSE-BSE-Insider-Tracker\b0547058-1862-47c5-9ee9-3b0c3878abf3\scratchpad\verify1.py`,
which uses `tests/conftest.py`'s `canonical()` and the real security master). Items marked **to confirm** depend on
production data; the exact check is given.

Severity: **W** = a number on the site is wrong, **M** = misleading (label, base or evidence does not match what is
computed), **E** = edge case, **P** = performance.

Counts: **W 13 · M 13 · E 15 · P 3** (44).

---

## W: wrong numbers

### W1. "% of market cap" uses today's market cap for every trade and deal
- `insiders_clean/insider.py:356,365`, `insiders_clean/deals.py:157-159`, `scripts/clean_writer.py:285-286`,
  `insiders_clean/securities.py:132-136,227`.
- Coded: `mcap_body = last_good(client, 'reference/market_cap/{day}/data.json', run_day, include_today=True)` and
  `df['pct_of_mcap'] = (df['value'] / df['market_cap'] * 100).where(df['market_cap'] > 0)`: one market cap (the
  latest file) divides every trade back to 08 Oct 2025.
- Should be: value / market cap **on the trade date** (or the broadcast date). The point-in-time figure is already
  collected: `insiders_clean/market_cap.py` parses NSE's PR-zip `mcap*.csv` (issue size x close, "VERIFIED ...
  shares outstanding point in time") into `marketcap/daily/nse/` (`scripts/price_backfill.py:35`), but the clean step
  never reads it. A stock that halved since a trade shows that trade at twice its real share of the company.
  SIGNALS.md admits "approximate" but the site's tables label it as if exact (see M4).
- Feeds: Spotlight (0.15%), Float absorber (0.5%), token rule (>Rs 5,000 Cr), `value_over_25pct_of_mcap` flag,
  every "% of mcap" column, handshakes `pct_of_mcap_sold`, small-cap filter (< Rs 5,000 Cr).
- Fix: join `marketcap/daily/nse` by (symbol or ISIN, trade_date_to, asof backward); BSE-only names: shares from the
  shareholding XBRL `NumberOfShares @ ShareholdingPattern_ContextI` (already parsed as `total_shares`) x the close
  from `prices/daily/bse`. Keep `market_cap_now` as a separate column for the size bucket.
- Test: two filings of one ISIN on dates whose mcap files differ 2x; assert `pct_of_mcap` differs 2x and equals
  value / that day's mcap.

### W2. Look-ahead in the Track record: signals are selected with today's market cap
- `insiders_clean/track.py:70-73,113-121`, `insiders_clean/signals.py:45-46,114-115`.
- Coded: `t = signals.eligible(trades)` (token = `market_cap > TOKEN_MIN_MCAP`, today's), spotlight replay sums
  today's `pct_of_mcap`, fund deals filtered `market_cap < SMALL_CAP_MAX_MCAP` (today's).
- Should be: PRODUCT.md, "Nothing published after the broadcast may feed a signal". A stock that fell after a buy now
  has a smaller cap, so its old buys cross 0.15% more easily and stop being "token"; a small cap that rallied above
  Rs 5,000 Cr drops out of `fund_deal_buy`. The scorecard is biased toward losers for Spotlight/token and against
  winners for the small-cap deal signal, and the evidence verdicts (`evidence.py`) and the model basket inherit it.
- Fix: W1's point-in-time mcap in `eligible()`; add the event-day mcap to `track_events`.
- Test: a buy whose stock has since fallen 60%: with point-in-time mcap it is not a spotlight event; today's code
  makes it one. Add to the "no look-ahead" test family PRODUCT.md promises.

### W3. NSE/BSE copy link ignores side and kind, and demotes every NSE row but one (verified)
- `insiders_clean/insider.py:494-510`.
- Coded: `link = ['isin', 'person_id', 'quantity', 'trade_date_to']` ... `primary = nse.index[0] if len(nse) else
  grp.index[0]; others = grp.index.drop(primary); df.loc[others, 'is_primary'] = False`.
- Problem: a person who files two different transactions of the same size on the same day (buy and sell; a market buy
  and a pledge; a pledge and its revocation) on both exchanges forms one group; the second NSE row becomes
  `is_primary = False` and leaves every signal. Reproduced: NSE buy 50,000 + NSE sale 50,000 on 02 Sep, each also on
  BSE -> only the buy is primary; the Rs 7.55 Cr sale disappears from "Promoters selling".
- Fix: add `side` and `kind` (and `value` within 1%) to the link key, and pair at most one row per exchange (rank
  within group, link rank-to-rank), never demote a row of the primary exchange.
- Test: the four-row case above -> both NSE rows primary, both BSE rows linked to the right one.

### W4. A multi-day NSE filing and its BSE nightly copy never link: counted twice (verified)
- `scripts/bse_raw_capture_v2.py:233` (`gf(r, 'Fld_FromDate', 'Fld_ToDate', ...)` -> one `transaction_date`),
  `scripts/r2_writer.py:217-218` (BSE `txn_to` falls back to that date), `insiders_clean/insider.py:401` (de-dup knows
  this: `_key_to` uses the from-date for BSE) vs `:494` (the NSE/BSE link uses `trade_date_to`).
- Reproduced: NSE 01-03 Sep buy of Rs 7.5 Cr, BSE nightly copy -> both `is_primary`, eligible value Rs 15 Cr.
  Real filings span days (r2_writer comment: ~19% of NSE rows are ranges). BSE CSV rows (to-date present) link;
  nightly-only BSE rows (no CSV twin, or the two-feed match failed) double count.
- Fix: link on `trade_date_from` when either side is a BSE nightly row (`source` not `bse_insider_csv`), or on
  (isin, person, side, quantity, value within 1%, from-date). Also map `Fld_ToDate` into the nightly row (the JSON has
  it: `tests/fixtures/bse/insider_json_20261009.json` carries `Fld_ToDate` and `Fld_DateIntimation`).
- Production check: eligible rows with `exchange == 'bse'`, `is_primary`, `source != 'bse_insider_csv'` that have an
  NSE row with the same isin, person_id, side, quantity and `trade_date_from`.
- Test: the reproduced case -> one primary row, `listed_on == 'bse,nse'`.

### W5. The truncated-name merge folds an individual into his HUF (verified)
- `insiders_clean/insider.py:131-158`.
- Coded: within a security, an ID of 15+ characters that is a prefix of exactly one longer ID is remapped to it.
- Reproduced: "Ramesh Kumar Agarwal" and "Ramesh Kumar Agarwal HUF" -> both become `ramesh-kumar-agarwal-huf`, the
  individual's trades shown under the HUF's name. HUFs, "... Family Trust", "... Holdings Pvt Ltd" sharing the
  promoter's name are common; the merge sums two legal persons into one for Spotlight/Float absorber and
  `buys_in_days`, and mislabels the filer.
- Should be: merge only names cut at NSE's XBRL limit (the raw name is 28-31 characters, or ends mid-word), never when
  the longer key just adds whole words such as `huf`, `trust`, `private-limited`.
- Test: the pair above stays two IDs; "Vama Sundari Investments (Delh" still merges.

### W6. "Funds net buying small caps" and the `fund_deal_buy` track signal count every client
- `insiders_clean/signals.py:348-373` (used unfiltered at `streamlit_app/screens/actions.py:120`),
  `insiders_clean/track.py:113-121`.
- Coded: only `client_is_market_maker` is removed; `net = signed_value.groupby([isin, date]).sum()`.
- Should be: restrict to `client_type in participants.INSTITUTIONAL` (the Deals page already does,
  `screens/deals.py:53`). Today individuals, promoters' companies, brokers and corporates are "funds"; and the track
  signal nets all clients per day, so a fund's 10 Cr buy against a promoter's 10 Cr block sale scores 0 while the
  label says "net buy by a real fund".
- Test: deals with one mutual-fund buy and one individual buy in a small cap -> only the fund appears and net value
  equals the fund's.

### W7. Many bonus ratios are never adjusted (verified)
- `insiders_clean/adjust.py:77-81`.
- Coded: clean ratios `{1/k, k for k in 2..20} | {a/(a+b) for a, b in 1..5}`.
- Reproduced with `is_clean_ratio`: bonus 1:6 (0.857), 1:10 (0.909), 3:10 (0.769), 7:10 (0.588), 11:10 (0.476) are
  big resets but not "clean", so `kind = 'other_large'` and the prices are left unadjusted: Track record returns,
  `pre_move`, 52-week high and `pct_off_high` show a false 9-41% drop across the ex-date. The reverse also happens: a
  ~20% special dividend (factor 0.8 = 4/5) is adjusted as a bonus.
- Fix: classify with the corporate-actions table already collected (`clean/current/actions.parquet`, `bse_actions`:
  purpose bonus/split, `ratio`, `face_value_from/to`, `ex_date`): expected factor = b/(a+b) for bonus a:b,
  to/from for a split; accept the implied factor when within 1.5% of the expected one on the ex-date. Keep the ratio
  guess only as a fallback, with a,b up to 20.
- Test: a 1:10 bonus series (prev_close reset by 10/11) -> adjusted close continuous; a 20% special dividend with a
  dividend action and no bonus -> not adjusted.

### W8. Deals: NSE and BSE "copies" are separate executions
- `insiders_clean/deals.py:203-219` (docstring step 3, DATA_DICTIONARY "NSE/BSE copies linked").
- Coded: legs with the same isin, client, date, side and quantity on both exchanges -> the BSE leg `is_primary = False`.
- Should be: each exchange disseminates bulk/block deals executed on its own platform (SEBI's 2004 bulk-deal and 2005
  block-deal circulars; the 0.5% threshold is per exchange). An equal quantity on both is a coincidence or a split
  order, not one trade, so every signal (`company_board`, handshakes, small caps, track) loses the BSE half.
- Production check: linked pairs where the two prices differ by more than 0.05% -> separate executions.
- Fix: drop the NSE/BSE linking for deals; sum both exchanges in flows.
- Test: same client buys 1,00,000 on NSE at 100.0 and 1,00,000 on BSE at 100.4 -> both primary, net = both.

### W9. Bulk feed and block feed overlap only partly removed (to confirm)
- `insiders_clean/deals.py:126-134`.
- Coded: one execution in both feeds is recognised only when quantity and price are identical.
- Risk: a bulk-deal line is the client's whole day on the exchange (the 0.5% test is on the day's aggregate), which
  includes block-window trades; when the client also traded in the normal window, the bulk line's quantity and
  average price differ from the block line, both stay, and the block quantity is counted twice.
- Production check: (exchange, client, security, day, side) present in both feeds with `bulk_qty > block_qty`; if
  `bulk_qty - block_qty` matches normal-window volume pattern, the bulk line contains the block.
- Fix: when both feeds have the leg, keep the bulk line as the leg and keep the block line only as a `feeds` mark.
- Test: bulk 3,00,000 @ 101 and block 2,00,000 @ 100 for one client/day -> one leg of 3,00,000.

### W10. A revision that corrects quantity or value is kept beside the original (to confirm)
- `insiders_clean/insider.py:390-418`.
- Coded: supersede only through `prevAppId`, else de-dup on `side, quantity, value, dates, holdings` all equal.
- Problem: the commonest correction (a mistyped quantity or value) changes exactly the fields in the key, and the
  code's own comment says "real corrections arrive without" prevAppId; both rows then count. A power-of-ten typo is
  caught by the price check, an ordinary one is not.
- Use what is captured: `nse_submission_type` / `nse_revision_remark` (NSE list `typeOfSubmission`,
  `revisionRemark`, kept since `scripts/nse_insider.py:131-137`).
- Production check: pairs with the same (isin, person_id, side, trade_date_from, trade_date_to), broadcast within
  30 days, different quantity or value, where the later has `nse_submission_type` like 'Revis%'.
- Fix: such a pair with a revision marker -> the earlier one removed as `superseded_by_revision_marker`.
- Test: original 10,000 sh / Rs 1.0 Cr, revision 12,000 sh / Rs 1.2 Cr typed 'Revision' without prevAppId -> one row.

### W11. Identical deal rows collapse into one (to confirm)
- `scripts/r2_writer.py:176-181` (`canonical_event_id` = hash of the row's content), `insiders_clean/archive.py:68`
  (`new.drop_duplicates(key, keep='last')`).
- Two genuine block trades of the same client, size and price on one day (common in staged promoter sales) have the
  same id; the archive keeps one, the clean table halves the quantity.
- Production check: in `raw_v2` deal CSVs, count lines that are byte-identical within one day's file.
- Fix: add the line's ordinal within the fetch (or NSE's own row number) to the id for deal rows.
- Test: two identical block lines in one CSV -> two archive rows, leg quantity doubled.

### W12. Security type is never checked: warrants, debentures and derivative lines can count as equity buys (to confirm)
- Parsed but unused: `scripts/nse_insider.py:157` (`secType` from XBRL `TypeOfInstrument`),
  `scripts/bse_raw_capture_v2.py:216` (`security_type`), BSE CSV `security_type` (`collectors/bse/parsers.py:73`);
  `insiders_clean/insider.py` reads none of them.
- Fixture: `tests/fixtures/nse_pit_real.json` has two ZEEL rows with `secType` 'Warrant' (here filed as
  'Preferential Offer', so not market). A 'Market Purchase' of NCDs or warrants, or a derivative line, would be an
  open-market equity buy with `pct_of_mcap` of the equity, and a price far from the share price would be held back
  for the wrong reason.
- Production check: `value_counts` of the archive's `secType` / `security_type` for rows the cleaner marks
  `is_market`.
- Fix: `security_kind` column; `is_market` only for equity shares.
- Test: a 'Market Purchase' row with secType 'Non Convertible Debentures' -> `is_market` false, kind `non_equity`.

### W13. Honorifics break the NSE/BSE and promoter-group links (to confirm)
- `insiders_clean/entities.py:41-53`: `entity_key('Mr. Ramesh Agarwal')` = `mr-ramesh-agarwal`,
  `entity_key('Ramesh Agarwal')` = `ramesh-agarwal`.
- A filing typed with "Mr/Mrs/Ms/Shri/Smt/Dr" on one exchange and without on the other fails the copy link (W3/W4
  key includes `person_id`), so both are primary and count twice; the same filer also misses the promoter-group link
  and the cluster rule.
- Production check: pairs with the same isin, side, quantity, trade dates on NSE and BSE but different person_id.
- Fix: strip leading honorifics in `entity_key` (keeps the conservative rule: no similarity matching).
- Test: NSE "Shri Ramesh Agarwal" + BSE "RAMESH AGARWAL", same trade -> one primary row.

---

## M: misleading

### M1. Directors and KMP may now be filed as "Designated Person" (to confirm)
- `insiders_clean/insider.py:74-83`; fixture `tests/fixtures/nse_pit_real.json` (NSE's new system): 125 of 141 rows
  'Designated Person', none 'Director' or 'Key Managerial Personnel'. `designated_person` is not in
  `DECISION_ROLES`, so a director's buy filed this way is out of "Director or KMP buys", clusters and `officer_buy`.
- Production check: `person_role` share by month before/after 03 May 2026, and for one company the same filings on
  BSE's CSV.
- Fix: if confirmed, resolve roles from the company's board list or the filer's earlier filings
  (`_fill_missing_roles` pattern), labelled by source.

### M2. Token and the Rs 25 lakh floor are per trade, not per decision
- `insiders_clean/signals.py:45-46`, `insiders_clean/track.py:73`.
- A promoter who buys Rs 4 Cr in twenty Rs 20 lakh tranches in a Rs 6,000 Cr company is "token" twenty times, out
  of Spotlight, clusters and the track record. SIGNALS.md notes promoters split purchases (top 10% file 10+ trades).
- Fix: apply both floors to the person's 30-day sum (as `person_windows` already builds). Test: the 20-tranche case
  counts once as a Rs 4 Cr buy.

### M3. "Promoter selling" badge: 90-day net against the 30-day threshold
- `insiders_clean/signals.py:179-182,231`: `company_board(days=90)` then `if r['promoter_net_pct'] <= -SPOTLIGHT_PCT_30D`.
- The 0.15% threshold was calibrated on 30-day windows (SIGNALS.md). Fix: own constant or a 30-day net.

### M4. Tables call it "% of mcap on the disclosure day"
- `insiders_clean/trade_table.py:4-5,46`: "the equity column is the ESTIMATED value / market cap on the disclosure
  day". It is today's (W1). Fix the label until W1 lands.

### M5. "52-week high" is the highest close, not the highest price
- `insiders_clean/slim.py:205-208`, `insiders_clean/track.py:86`. NSE and every broker quote the intraday high, so
  "-14% from 52W high" differs from what the reader sees elsewhere; the "within 5% of high" preset fires late.
- Fix: adjust the `high` column with the same factors (`adjusted_panels` already scales `open`).

### M6. REIT/InvIT unit distributions are kept as dividends
- `collectors/nse_events/parsers.py:109-124`: `(r'dividend', 'dividend')` matches "Distribution - Rs 2.32 Per Unit
  Consist Of ... As Dividend ..." (11 such rows in `tests/fixtures/nse_events/corporate_actions.json`), against
  DATA_DICTIONARY ("Dropped ...: unit distributions"). `dividend_per_share` is then blank.
- Fix: `^distribution` -> dropped before the purpose rules. Test: those 11 subjects are dropped.

### M7. Rule lock-in ignores the 20% cap and the pre-issue holding lock
- `insiders_clean/issues.py:55,191-209`, `:549-554`.
- Coded: promoters 18 months, others 6, from trading approval.
- ICDR Reg 167(1) (as amended 2022): promoter allotment locked 18 months only up to 20% of the post-issue capital,
  the excess 6 months; Reg 167(6): the allottees' pre-preferential holding is locked from the relevant date to 90 days
  after trading approval. Only used when no lock-in line is filed, but then the "Shares about to come off lock-in"
  list dates promoter shares a year late in large promoter issues.
- Fix: when `shares_allotted / shares_listed` (post-issue) puts the promoter allotment above 20%, split the line.

### M8. Evidence shown beside a list that is not the measured rule
- Actions "Promoters buying" (`insiders_clean/actions.py:151-157`: 30-day person sums, no per-trade floor) shows the
  verdict of `promoter_buy` (per trade >= Rs 25 lakh, spaced 21 sessions). "Funds net buying small caps"
  (30-day, any client) shows `fund_deal_buy` (per day, any client). The reader is told a list "beat Nifty 500" when
  the list's own rule was never measured. Fix: one function defines each list and its track event.

### M9. Track record silently drops events with no close on the entry or exit day
- `insiders_clean/track.py:149-161`: `entry = close.at[...]`, `if ... not np.isfinite(e0)` -> NaN; exit `e1` NaN ->
  NaN return. Illiquid small caps that skip the next session, and stocks suspended or delisted later, vanish from the
  median: survivorship bias toward winners, uncounted. Fix: entry = first traded close after the broadcast day
  (record the gap), exit = last traded close at or before the horizon (marked), and report dropped counts per signal.

### M10. Trading window from the meeting date while the exact results time is collected
- `insiders_clean/trading_window.py:76`: `window_open_date = results_date + 2 days`. PIT Schedule B cl. 4: closed "till
  48 hours after the declaration of financial results". `results.py` already stores NSE's `broadcast_at` (IST, to the
  second) for each results filing; use it (window opens broadcast_at + 48h; first session on or after).

### M11. Handshakes pair sellers and buyers across exchanges
- `insiders_clean/signals.py:315-332`: `_sec = isin`, so an NSE seller is "absorbed" by a BSE buyer the same day.
  Fix: key on (exchange, isin, date); show cross-exchange as a separate, weaker line.

### M12. High-pledge badge ignores `shareholding_stale`
- `insiders_clean/signals.py:213-217,233` uses the carried-forward pledge; `actions.pledged` (`actions.py:183-185`)
  excludes it. The Screener can show "High pledge 40%" from last quarter's file. Fix: same stale rule in both.

### M13. Docs say NSE's prevAppId is not captured; it is
- `docs/CLEAN_LAYER.md:176` vs `scripts/nse_insider.py:131-137,183-187`. The stale sentence hides that W10 is
  fixable with data in hand.

---

## E: edge cases

| # | Where | Rule as coded | Problem and fix |
|---|---|---|---|
| E1 | `insiders_clean/slim.py:222-227`, `scripts/nse_market_cap.py:102-118` | rank of every symbol in the mcap file ("NOT filtered to Series == 'EQ'") | REITs/InvITs (series RR/IV) and other instruments take Large/Mid ranks. Check `mc['series'].value_counts()` among the top 500; rank only equity series. |
| E2 | `insiders_clean/adjust.py:93-99`, `slim.py:171-178` | per day, the series with the most traded value | If UDiFF prints a block-window series (e.g. 'BL') its single print can become the day's close and its stale prev close a false factor. Check `px['series'].unique()`; restrict to EQ/BE/BZ/SM/ST/SZ. |
| E3 | `adjust.py:109` | factor only when the previous print is `<= 10` days old | A split during a suspension longer than 10 days stays unadjusted (`unknown`). Use the actions table (W7) to place it. |
| E4 | `collectors/nse_events/run_daily.py:163-164`, `promoter_group.py:68-69` | `sort_values([... 'submission_date'])` then keep last | Original and revision filed the same day: tie broken by unstable sort / hashed `event_id`. Sort by `revised` too. |
| E5 | `insider.py:405-414` | latest broadcast wins, then CSV | Comment says the CSV row is kept; if the JSON's LetterDate is later, the JSON row (no to-date, no intimation) wins. Put `_bse_csv` first for BSE two-feed pairs. |
| E6 | `insider.py:74-83` | first match: `promoter\s*group`, `promoter`, ... | "Immediate relative of promoter" or "Non-promoter director" -> promoter. Anchor the rules on the exchanges' category lists. |
| E7 | `issues.py:438-452` | 90 / 10 of the stock's own traded days, all series | ICDR Reg 164(1) counts exchange trading days; illiquid stocks reach further back. Use the NSE calendar and EQ/BE only; mark Reg 165 (infrequent) cases. |
| E8 | `buybacks.py:190-195` | any tender opening within 60 days of a record date | One tender can be matched to two actions; exclude `used` from candidates. |
| E9 | `track.py:257-266` | `upto['series'].iloc[-1]` after an unstable sort by date | Same-day rows of two series give an arbitrary series; take the most traded. |
| E10 | `insider.py:370` | Reg 7(2)(a) clock from `trade_date_to` | The two days run from the trade that crosses Rs 10 lakh in the quarter; a long range is under-flagged. Label as "from the last trade day". |
| E11 | `signals.py:203-206,310,356`, `track.py:117` | deals filtered on market maker and primary only | `needs_review` deals (unmatched, >25% of mcap, missing price) still enter flows. Exclude, as for insider rows. |
| E12 | `parsers.py:139,156-158` | number after `premium|@|price` is the premium; issue price = FV + it | A subject "@ Rs 120 per share" (price, not premium) gives FV too much. Only add FV when the word Premium is present. |
| E13 | `scripts/precompute_slim.py:56` | `run_at = pd.Timestamp.now(tz='UTC')...` | Forward-record `recorded_at` and file names in UTC; owner's rule is IST. Store IST (or UTC with tz and render IST). |
| E14 | `basket.py:126-134` | NAV = daily mean of live positions' returns, cost spread over held + entering | Daily-rebalanced equal weight differs from the positions table's buy-and-hold `ret`; the two can disagree. State it or compute NAV from position values. |
| E15 | `insider.py:462-471` via W4 | BSE nightly rows checked against the first day only | A multi-day average price lands outside the first day's range -> `price_far_outside_day_range` holds back an honest filing. Fixed with W4. |

## P: performance

| # | Where | Note |
|---|---|---|
| P1 | `track.py:93-110` | Spotlight and clusters recomputed for every day on `t[t['seen'] <= end]` (full-frame filter + Python groupby per ISIN per day): O(days x rows). Compute rolling 30-day sums per (isin, person) once and diff. |
| P2 | `adjust.py:125-131` | One full-frame boolean mask per (exchange, ISIN) with a factor over ~all price rows. Group once, cumulative product of factors per group. |
| P3 | `signals.py:209-211` | `company_board` calls `spotlight`, `float_absorbers`, `clusters` and each rebuilds `person_windows`; compute once per page load. |

---

## Checked and correct (no defect)

Units: rupees throughout (`TOKEN_MAX_VALUE = 25e5`, `TOKEN_MIN_MCAP = 5000e7`, `LARGE_HANDSHAKE_VALUE = 10e7`),
BSE Mktcap crore x 1e7 (`scripts/bse_market_cap.py:66`), NSE mcap rupees; pledge % = pledged / promoter shares x 100
(Zee fixture 2,060,000 / 38,316,284 = 5.38%, equal to the filed `EncumberedShareUnderPledgedAsPercentageOfTotalNumberOfShares`
0.0538); SHP member % and QIP `pct_of_issue` filed as fractions, x100; `float_pct` base = mcap x public %.
Reg 7(2) lateness in NSE sessions with `(start, end]` (2 sessions allowed). Track entry = close of the first session
after the broadcast day, horizons complete only, 0.25 points cost, benchmark on the same sessions; spacing 21 sessions
per company per signal. Window edges (30/90 days, `seen > ref - n`, `<= ref`) identical on the site and in the replay.
ISO timestamps with Z converted to IST (`dates.parse_dates`). ICDR estimate: higher of 90- and 10-day VWAP before the
relevant date on the higher-volume exchange (Reg 164(1)); blanked across a split. Shareholding: revised filing replaces
original; carried-forward pledge marked stale. SAST: `is_market` only 'Open Market' (NSE) / 'Market' (BSE).

---

## Where XBRL (or a better structured source) should replace what is used

| # | Used now | Should use | Field |
|---|---|---|---|
| X1 | Latest market cap for every trade (`reference/market_cap/{day}`) | Point-in-time shares x close | NSE PR-zip `mcap*.csv` `Issue Size` / `Market Cap(Rs.)` on the trade date (already in `marketcap/daily/nse`); BSE-only: SHP XBRL `in-bse-shp:NumberOfShares` @ `ShareholdingPattern_ContextI` x close |
| X2 | Holding change % recomputed from share counts; tables say no post-trade % exists (`trade_table.py:4`) | The filed Form C percentages | PIT XBRL pre/post % of shareholding (tag names to confirm on one file; `nse_insider.to_row` drops every tag it does not map); already archived and unused: NSE history `history_befAcqSharesPer` / `history_afterAcqSharesPer`, BSE CSV `pct_before` / `pct_after`, BSE JSON `Fld_PercentofShareholdingPre/Post` |
| X3 | No security type (W12) | Instrument of the transaction | PIT XBRL `TypeOfInstrument` (`secType`), BSE `Fld_SecurityTypeName`, CSV "Type of Securities Acquired/Disposed" |
| X4 | Derivative trades not told apart | Derivative block of Form C | PIT XBRL derivative contract type / notional / units; NSE history `history_tdpDerivativeContractType`; BSE CSV `trading_in_derivatives`, `buy_units`, `sell_units` |
| X5 | Revisions by content only (W10) | NSE's revision markers | NSE list `typeOfSubmission`, `revisionRemark`, `prevAppId` (captured as `nse_submission_type`, `nse_revision_remark`, `prev_app_id`) |
| X6 | BSE nightly to-date = from-date (W4) | BSE JSON's own fields | `Fld_ToDate`, `Fld_DateIntimation` (present in `tests/fixtures/bse/insider_json_20261009.json`, dropped by `bse_raw_capture_v2.insider_row`) |
| X7 | Results date = board-meeting date from the meetings list (M10) | The results filing itself | NSE integrated-filing list `broadcast_Date` (stored as `results.broadcast_at`), XBRL `DateOfBoardMeetingWhenFinancialResultsWereApproved` |
| X8 | Split/bonus guessed from price resets (W7) | Corporate actions with ratios | NSE `/api/corporates-corporateActions` `subject` ratio, `faceVal`, `exDate` (clean `actions.ratio`, `face_value_from/to`); BSE `DefaultData` purpose text |
| X9 | `MIXED` preferential issues: both lock-ins, no shares split | Allottee names against the promoter list | In-principle XBRL `in-capmkt:NameOfAllottees` / `NumberOfSharesAllotted` joined by `entity_key` to `promoter_group.member_id` (SHP Table II) |
| X10 | Promoter shareholding % from NSE's listing JSON (`pr_and_prgrp`) | Same file's XBRL, already parsed | `ShareholdingAsAPercentageOfTotalNumberOfShares` @ promoter context (`promoter_holding_pct_xbrl`); use it when the listing and the XBRL disagree, and record which |
| X11 | Directors/KMP role from a free-text category (M1) | Company's KMP/director disclosures | Corporate-governance XBRL (Reg 27) director list, or the annual report; until then, roles from the same person's earlier filings |
