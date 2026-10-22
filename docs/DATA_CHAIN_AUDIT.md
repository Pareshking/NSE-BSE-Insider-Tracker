# Data chain audit (owner, 22 Oct 2026)

The brief: which data we collect, how we clean it, the mistakes, and how best to present it so an
investor decides better, read as an investor looking at the raw filings. A well-designed site that
presents bad data, or data badly cleaned, is a financial disaster waiting for someone.

Method for every item: the exchange's own file is the truth; each claim below is checked on real rows
(`scripts/chain_stats.py` and `scripts/clean_peek.py`, read-only workflows *Chain stats* and *Clean peek*)
and recorded with its evidence; a mistake becomes a fix with a test, in a PR, verified on real data.
Status: open / checked (right) / fixed (PR) / not done (why).

## 1. What we collect

| Dataset | Source (raw, write-once in `raw_v2/`) | Clean table | Used on |
|---|---|---|---|
| Insider trades (SEBI PIT, Reg 7) | NSE `corporates-pit-gg` list + each filing's XBRL; BSE insider CSV and nightly JSON | `insider_trades` | Today, Company, Filings, Evidence |
| Pledges, releases, invocations | The same PIT filings (mode of acquisition) | `insider_trades` (`kind` pledge_*) | Today, Company, Filings |
| Bulk and block deals | NSE and BSE daily bulk/block files | `deals` | Today (funds), Company, Filings |
| Substantial acquisitions (SAST Reg 29) | NSE `corporate-sast-reg29`, BSE `Corporatesast` | `sast`, `bse_sast` | Today (big investors), Company, Filings |
| Shareholding pattern (quarterly) | NSE `corporate-share-holdings-master` + XBRL; BSE `Corp_Shareholding_ng` + inline XBRL | `shareholding`, `promoter_group`, `bse_shareholding`, `bse_promoter_group` | Today (promoters hold, pledge), Company (ownership) |
| Preferential issues, warrants | NSE further-issue lists (in-principle, listing) + XBRL | `preferential`, `preferential_allottees`, `preferential_lockins` | Today (promoters pay up / cheap shares), Company, Filings |
| QIPs, rights issues | NSE further-issue lists + XBRL | `qip`, `qip_allottees`, `rights` | Company, Filings |
| Buybacks | NSE tenders + daily buyback reports + corporate actions | `buybacks`, `tenders`, `daily_buybacks` | Today, Company |
| Corporate actions | NSE `corporates-corporateActions`, BSE `DefaultData` | `actions`, `bse_actions` | Company, Filings; split/bonus adjustment of prices |
| Board meetings, results dates | NSE `corporate-board-meetings`, BSE `boardmeeting_fno` | `meetings`, `bse_meetings` | Company; trading window |
| Financial results (XBRL) | NSE integrated filing financials + XBRL | `results` | Company timeline |
| Prices, market cap | NSE and BSE daily bhavcopy; NSE daily market-cap file | artifacts (prices, history), `market_cap*` columns | everywhere (CMP, % of company, universe) |
| Tradability | NSE ASM/GSM/ESM lists, sec_list, bhavcopy bands | `tradability` | flags on rows, Evidence's "tradable only" |
| Security master | VR export (01 Sep) + NSE/BSE lists | `securities`, `universe` | names, ISIN, the Rs 100 Cr universe |
| Announcements | NSE/BSE announcements (counts only; the AI reader is stopped) | archive | not shown |

## 2. Questions an investor would ask of each (the checklist)

Insider trades
- [x] (T3, T4, T8; right otherwise) Is every "buy" a buy with the person's own money on the market? ESOP exercise, gift, inheritance, inter-se
      transfer, off-market, conversion of warrants, preferential allotment, pledge, bonus/split credits: which
      reach `is_market` and the signals?
- [x] (checked; T8) Value: as filed vs shares x price; units (rupees vs lakh); zero or missing values; price outside the
      day's range (power of ten, swapped quantity/value).
- [x] (T2, T3; JB Chemicals open) The same trade counted twice: NSE + BSE copies, revisions, BSE's two feeds, multi-day filings.
- [x] (T1, T4, T5) Who: promoter vs promoter group vs director vs KMP vs designated person vs immediate relative; one
      family split into many "decision-makers"; a company (promoter entity) vs an individual.
- [x] (timing, 23 Oct) Timing: trade date vs intimation vs exchange broadcast; late filings; trades inside a closed trading
      window; the date we mark on the chart.
- [x] (holding, 23 Oct) Holdings before/after vs shares traded (holding_check); % of the company basis.

Pledges
- [x] (T2, T6; Reg 31 #199) Pledge vs encumbrance vs non-disposal undertaking vs invocation; renewals and top-ups; release then
      re-pledge; quantity missing on NSE rows; the quarterly XBRL vs the PIT flow.

Bulk / block deals
- [x] (T5; desks open) Client classification (fund, FPI, broker, market maker, individual, promoter); intraday round trips;
      the same order on both exchanges; deals that are an insider's own filed trade.

SAST
- [x] (T7, D8, D14) Acquirer type (investor vs lender's trustee vs promoter); instrument (shares vs warrants vs voting
      rights); "Acquisition" filed for an encumbrance; the % base (total voting capital).

Shareholding
- [x] (C4, #204; checked and right) Retired ISINs; % base (total vs total less DR shares); stale quarters; pledge as % of promoter shares vs
      of the company; promoter group membership.

Issues (preferential, QIP, rights, warrants)
- [ ] Allottee category (promoter vs others vs mixed); warrants (25% upfront, 18 months) vs shares; the price
      against today's price on the same split basis; approved vs allotted vs listed; amounts in the wrong unit.

Buybacks, corporate actions, results
- [x] (C1, C3, #211, #212; checked and right) Tender vs open market; premium at announcement vs now; split/bonus ratios applied to prices; results
      standalone vs consolidated, quarter vs year to date, rupee unit (lakh / crore / rupees).

Prices and market cap
- [x] (C1; checked and right) Split/bonus adjustment; market cap on the trade's day vs today; companies under Rs 100 Cr; SME and T2T.

Presentation
- [ ] Every number says what it is (as filed vs estimated, % of company vs of market cap), its date, and its
      source filing one click away; evidence shown as a tag, never a filter; nothing estimated looks filed.

## 3. Findings

(each: what the site shows, what the exchange's file says, the cause, the fix, the PR)

### Corporate data (branch audit/corporate-data, 22 Oct)

Real rows read with `scripts/corporate_peek.py` (workflow *Corporate peek*, read-only; runs 39718688857, 39790656627,
39792143641); the exchanges' own files fetched with the repo's clients (8 NSE calls). Tests: `tests/test_audit_corporate.py`
and `tests/test_bse_meetings_shareholding.py`.

#### C1 Bonuses and splits were not adjusted: 169 of 170 since May 2025 (wrong number, fixed)
- **Site**: every price line, 52-week range, "vs paid", "vs the price now" of an issue or buyback and the track record's
  forward returns read a bonus or split as a crash. HDFC AMC (1:1 bonus, ex 26 Nov 2025): history 5,336.50 then 2,679;
  Thyrocare (1:2, 28 Nov 2025) 1,475.10 then 495.70; Metropolis (1:4, 20 Mar 2026) 1,823.80 then 441.10; MCX (Rs 10 to
  Rs 2, 02 Jan 2026), Kotak Bank (Rs 5 to Re 1, 14 Jan 2026), BLSE, Buildpro, Bansal Wire (Oct 2026): the line starts on
  the ex-date.
- **Exchange**: NSE's UDiFF bhavcopy of 26 Nov 2025 (`BhavCopy_NSE_CM_0_0_0_20251126_F_0000.csv.zip`): HDFCAMC EQ
  INE127D01025 PrvsClsgPric 5,336.50, ClsPric 2,679.00; of 28 Nov 2025: THYROCARE PrvsClsgPric 1,475.10, ClsPric 495.70.
  The previous close is NOT reset on the ex-date. A split comes with a new ISIN: BLSE INE0NLT01010 to 03 Oct 2026,
  INE0NLT01028 from 06 Oct (97 of the 170 filed splits and bonuses changed ISIN).
- **Cause**: `insiders_clean/adjust.py` `implied_factors` measured the factor as prev_close / last close (always 1 here)
  and per ISIN (a new ISIN has no last close): kinds on the 170 ex-dates were none 70, unknown 98, split_bonus 1.
- **Fix**: `adjust.bridge_isins` carries the old ISIN's prints under the new one (same symbol and exchange, same first
  nine characters of the ISIN, within 10 days; `slim.adjusted_panels`); a filed bonus or split whose day moved by its
  factor (close / last close within 1.25x of it) is applied at the filed factor (`kind_basis` `action_price`). On the
  real prices (run 39792143641): 150 ISINs bridged, 157 of the 170 adjusted; the 12 left have no print within 10 days
  before the ex-date (BSE-only, illiquid). Tests: `test_filed_bonus_is_applied_when_the_bhavcopy_keeps_the_old_base_price`,
  `test_split_with_a_new_isin_carries_the_old_prints_and_is_adjusted`, and two negatives.
- **Investor**: the chart should mark the ex-date ("1:1 bonus, prices before adjusted") so a halving never reads as a fall.

#### C2 Preferential approvals filed a power of ten off (wrong number, fixed)
- **Site**: an approval no allotment points to shows its approved amount: R K Forge Rs 2.00 Cr for 34,00,000 warrants.
- **Exchange**: the in-principle XBRL `PREF_ISSUE_IP_1588704_23122025121455_WEB.xml` (appId 63777): NumberOfSecurities
  3,400,000, MinimumIssuePricePerUnit 586.77, AmountToBeRaised 19,992,000 (Rs 199.92 Cr is 100x that; the same file
  gives TermsOfPaymentInPercentage 0.0025 for 25%). Also Kaya (70976, 100x low), OLIL (69150), RNPL (63835), Affordable
  (70342, 10x low), Sanginita (67204, 10x high).
- **Cause**: `issues.normalise` checks the amount only against a Rs 1 lakh crore ceiling.
- **Fix**: `issues.check_approved_amount`: an approval within 3% of 10^k (k not 0) times securities x ICDR minimum of
  its own XBRL is blanked and `amount_unreliable` (counted `amount_power_of_ten`). An issue priced above the minimum
  (R K Forge's earlier one, appId 59198, 2.9x) is kept. Test: `test_approved_amount_a_power_of_ten_off_is_held_back`.

#### C3 A revised result listed beside its original (duplicate, fixed)
- **Site**: Company timeline, HCL Tech: "Quarter to 31 Mar 2026, standalone" twice (Original 21 Apr, Revision 23 Apr).
- **Data**: 1,639 results rows share a company, period end and basis; 891 are revisions.
- **Fix**: `results.mark_superseded` (`superseded` column; rows kept for cards dated before the revision); the Company
  timeline shows the latest filing only. Test: `test_a_revision_supersedes_its_original_and_the_other_basis_stays`.

#### C4 1,165 universe companies have no shareholding at all (missing data, fixed in code; needs a BSE catch-up)
- **Site**: "Promoters hold —", no pledge, no ownership for MCX (Rs 78,716 Cr), Abbott India (Rs 54,568 Cr), Bayer
  Cropscience, NSDL, JSW Dulux, Kirloskar Ferrous, Novartis, Timex ... (574 NSE-listed, 591 BSE-only).
- **Exchange**: NSE `/api/corporate-share-holdings-master?index=equities&symbol=ABBOTINDIA` answers 0 rows; the
  01-22 Oct 2026 window answers 2,410 filings, none of Abbott's or MCX's (their filings are on BSE).
- **Cause**: `collectors/bse/events.py` `shareholding` and `insiders_clean/bse_events.clean` left every company with an
  NSE symbol to NSE's collector; `clean/current/bse_shareholding.parquet` did not exist yet (the nightly of 22 Oct 02:58
  IST ran BSE SAST and actions only) and the site never read it.
- **Fix**: only a company whose ISIN is in NSE's shareholding table is left to NSE (`dual_listed_kept` counted); the
  site reads `bse_shareholding` beside NSE's (`insiders_clean.bse_events.with_bse`). Test:
  `test_a_dual_listed_company_nse_does_not_list_is_read_from_bse`. Needs a BSE history run (below).

#### Checked and right
- **Promoter % base**: NSE's listing % is of total shares less DR shares (SEBI's base): 0 of 2,120 latest XBRLs differ by
  more than 0.05 pt on that base (12 differ on the plain total: Infosys 13.90 vs 12.73, Reliance, SBI, all DR issuers).
- **Pledge**: `promoter_pledge_pct` is pledged / promoter shares (0 of 2,122 off), labelled "of promoter shares". NSE's
  own `/api/corporate-pledgedata` (1,558 rows, fetched 22 Oct): our latest promoter pledged shares equal NSE's
  `totPromoterShares` (promoter shares encumbered, last pattern) for 1,471 of 1,473 companies on the same quarter; the 2
  are Jain Irrigation's DVR and ordinary lines joined by one name. NSE's `numSharesPledged` / `percSharesPledged` is a
  different number: every pledged share in the depositories, of demat shares (within 0.005 pt), any holder (Yes Bank
  4,24,99,79,189 with no promoter): never to be shown as a promoter pledge. NSE's `totPromoterHolding` differs from our
  promoter shares for 159 (Ashok Leyland by its 4,73,40,000 DR shares); ours sums to the XBRL's Table II members.
- **Stale quarters**: 2,339 of 2,417 companies' latest is 30 Sep 2026; one carried pledge (Wonderla, Jun 2026 XBRL failed,
  0% carried from Mar). 3 universe companies' latest is before Jun 2026 (Hercules Sep 2025, Gencon and Supreme Infra Mar 2026).
- **Buybacks**: route right for all 34 (26 tender at the filed price, 5 open market with daily reports, 3 record dates in
  Oct 2026 not yet in NSE's tender list). Tender price = NSE's `band` = `allocatedPrice` on every past offer.
- **Results units**: values are rupees as filed, the XBRL's LevelOfRounding (Lakhs 3,945, Crores 1,142, Millions 849)
  already applied: HCL Tech 30 Sep 2026 consolidated revenue Rs 35,620 Cr, Reliance Jun 2026 Rs 3,11,850 Cr. Quarter vs
  year to date read apart (YTD months 12: 4,789, 9: 706, 6: 323).
- **Market cap**: `securities.market_cap` equals NSE's daily file (issue size x close) for all 2,153 NSE names; 822 take
  BSE's, 29 none. 415 companies sit between Rs 80 and 125 Cr (the cut-off moves them day to day).
- **Corporate action parsing**: every split's face values and every bonus's ratio read (NSE 4 + 3, BSE 79 + 92).

#### Open
- Preferential rows keep the ISIN NSE filed: 265 carry an ISIN the security master does not know (retired, e.g. before a
  split), so the universe cut drops them; `issues` needs `add_identity` as the NSE events tables have (D12).
- Warrant conversions: 30 listing records raise 75% of shares x price (the balance on warrants; the 25% came at
  allotment). Shown as the amount raised, as filed; the label should say "balance on conversion of warrants".
- Buybacks show the offer against today's close only; the premium at announcement (close before the board meeting)
  is what an investor weighs. 869 large resets since Oct 2025 with no filed action stay unadjusted (demergers,
  rights, Sanofi's special dividend), as designed.
- Results: Rajesh Exports' quarterly revenue Rs 2.35-4.72 lakh crore against a Rs 1,614 Cr market cap; 8 rows with the
  quarter above the year to date. Not checked against the filings yet.

### Trading data (insider trades, pledges, deals, SAST): audit of 22 Oct, branch `audit/trading-data`

Read on real rows with the read-only workflow *Trading audit* (`scripts/trading_audit.py`, sections `insider`,
`dups`, `dups2`, `roles`, `price`, `deals`, `sast`, `pledge`, `intra`, `fundpromoter`, `pgroup`, `enc`, `after`), clean
tables as of 21 Oct; NSE's own files fetched for appIds 2325, 2427, 3934, 3962 (`corporates-pit-gg` + XBRL). The
`after` section applies this branch's rules to the same rows: the changes quoted below are its counts. Tests:
`tests/test_trading_audit.py`, fixtures shaped like the rows named.

#### T1 A director's relative counted as a director (wrong signal, fixed)
- **Shown**: Today, "Cluster: Director Padma Bahety and 3 more bought 4.26% of the company" (Mkventures Capital, BSE
  514238, 23 Sep 2026, four market buys at Rs 1,000).
- **Exchange**: every one of the four filed as "Directors Immediate Relative" (BSE's category); NSE XBRL 3934 (Innova
  Captab, 03 Oct 2026) files Gian Parkash Aggarwal and Veena Devi the same way.
- **Cause**: `insider._ROLE_RULES` matched "director" before "relative": 246 rows were directors (41 eligible buys, 88
  sales); "Promoter(s) Immediate Relative" (124) read as promoter.
- **Fix**: relatives first; a promoter's immediate relative is promoter group (ICDR 2(1)(pp)(ii)), anyone else's an
  immediate relative (no decision role). After: 245 rows director -> immediate_relative, 124 promoter -> promoter group;
  Mkventures leaves Clusters and Insiders buying.
- **Present**: "relative of a director" in the row, never "Director".

#### T2 Pledge releases filed without a mode kept as trades of no kind (wrong number, fixed)
- **Shown**: Thyrocare, Docon Technologies, 17 Aug 2026: a BSE row of kind `missing` worth Rs 4,916 Cr (held back);
  its NSE row (appId 2325) a release with no shares; 171 more rows (NSE `PLEDGE REVOKE` 111, BSE `REVOKE` 60) `missing`.
- **Exchange**: XBRL 2325: TransactionType Pledge, Mode "Pledge Release", 7,94,69,696 shares, held 8,12,00,000 before.
  SAST Reg 31 (#199) agrees: Release, Pledge, 7,94,69,696 (49.93%) on 17 Aug and 1,75,00,000 on 11 Aug (appId 2183).
- **Cause**: `kind` came from the mode only; BSE's nightly feed files some pledges with neither mode nor type, so the
  NSE row found no BSE copy of its kind to take the shares from (`_pledge_quantity_from_bse`).
- **Fix**: a blank mode takes the kind from the transaction type (`kind_from_type`); a BSE row with no mode, no side and
  an unchanged holding is the copy of the NSE pledge of the same person and dates and takes its kind; done before the
  removals and flags. Against Reg 31: of 244 PIT promoter pledge rows matched to an event, 37 were `missing` and every
  one is a Release; after the fix 232 of 244 agree with Reg 31's type (10 create/release crossed: open).
- **Present**: a pledge row says pledged / released / invoked, shares and % of the company, the lender from Reg 31.

#### T3 One trade kept two or more times (wrong number, fixed)
- **VIP Industries, 24 Dec 2025** (BSE 507880): Multiples Private Equity Fund IV and Gift Fund IV bought 1,26,17,212 and
  1,39,14,505 shares (Rs 489.55 and 539.88 Cr); BSE carries each twice, holdings typed 8,049 and 8,876 shares apart: both
  eligible, 9.31% + 9.31% of the company. No NSE row of these.
- **Info Edge, Kapil Kapoor** (NSE 2427 Original, 20 Aug; 3962 Revision, 08 Oct, prevAppId 47977): 5,00,000 sold for
  Rs 68,04,78,416, holding before 1,12,55,795 in 2427 and 1,15,55,795 in 3962 (XBRL of both read): counted twice, and
  BSE's two copies too. NSE's prevAppId is not an appId of its list, so the `superseded` link never fires.
- **Vikram Solar, 19 Feb 2026**: one release of 7,30,86,090 shares from NSE's two files, valued a rupee apart
  (Rs 15,775,632,527 / ...526), one with no mode (Reg 31: one Release).
- **Cause**: the content match (`clean_insider`, removals) needed equal holdings and an equal value to the rupee;
  `_revision_marked` only took revisions with no prevAppId.
- **Fix**: value compared to the nearest Rs 10, the copy with a filed mode kept on a tie; a trade filed again with other
  holdings (same person, security, side, shares, value, dates; not a chain of tranches) keeps the latest broadcast
  (`refiled_with_other_holdings`, counted); a revision whose prevAppId we do not hold goes through the marker match.
  After: 44 primary rows removed (NSE 26, BSE 18), Rs 1,106.7 Cr, 30 of them in the signals.
- **Also**: BSE (and NSE 2183) "Block Deal" was `unrecognised`, so the NSE "Market Sale" and BSE copies never paired and
  Docon's 1,31,68,657-share block sale (Rs 815 Cr, 13 Aug) was out of the signals: a block or bulk deal is a market
  trade. "Procter &amp; Gamble Home Products" (HTML entity as filed) was a second filer beside "Procter & Gamble":
  entities are unescaped.
- **Present**: each trade once, "on NSE and BSE" as a tag; a re-filed trade shows the filing kept and the one replaced.

#### T4 Shares moved inside the promoter group shown as a promoter buying and a promoter selling (wrong signal, fixed)
- **Shown**: P&G Hygiene 19 Jun 2026, P&G Home Products bought 6,19,683 at Rs 8,995.50 (Rs 557 Cr) and Temple Trees
  Impex sold the same; Bajaj Finserv 27 Apr 2026, Bajaj Holdings & Investment bought 20,90,050 from Bajaj Auto Holdings
  (block window); Dalmia Bharat 25 Sep 2026 (Dalmia Bharat Refractories from Rama Investment). 41 such pairs in 23
  companies (Rs 1,745 Cr) on the eligible rows; 80 primary rows, 24 companies, Rs 2,322.5 Cr after T3's fixes.
- **Cause**: each side is a filed market trade; nothing paired them.
- **Fix**: `_promoter_group_transfers`: on one exchange, a promoter / promoter-group market buy and another's market sale
  of the same company, dates and shares, prices within 2%, paired one to one: kind `inter_se`, mark
  `promoter_group_transfer`. After: Dalmia Bharat, Jhaveri Credits, Nalin Lease, Orbit Exports and Sodhani Academy leave
  Insiders buying (and three of them Promoters selling).
- **Present**: "moved within the promoter group" in Filings, never on Worth a look / Watch out.

#### T5 A promoter's own bulk/block sale read as "Funds selling" (wrong signal, fixed)
- **Shown**: Gland Pharma, "Funds selling 6.16%"; EPL "Funds selling 17.51% (Epsilon Bidco Pte)".
- **Exchange**: BSE block deals 04 Sep 2026: Fosun Pharma Industrial Pte sold 1,74,02,500 shares at Rs 2,827.84
  (Rs 4,921 Cr); mutual funds and insurers bought. Gland's 30 Sep shareholding XBRL names Fosun Pharma Industrial Pte as
  promoter; EPL's 30 Jun names Epsilon Bidco. No PIT filing of either sale is in our data (open: missing filing or
  collection gap). The client type rule read "PTE" as a foreign investor.
- **Fix**: `promoter_group.mark_deal_promoters`: `deals.client_is_promoter` (and `client_promoter_basis`) from the
  company's promoter-group list or a PIT promoter filing; such legs leave fund events, and `ideas.promoter_deal_events`
  shows "X (promoter) sold N% in bulk/block deals; no insider filing of it in the data" where no PIT promoter market
  trade of the company is in the period. After: 518 legs are promoters' (398 by the list, 120 by PIT); EPL and Gland turn
  to Fund buying (8.83%, 4.38%), and 20 companies get a promoter line (EPL 26.33%, Gland 10.55%, Kfin 8.76%...).
- **Present**: the promoter's deal under Promoters, the funds that took the shares under Funds.

#### T6 Pledge invocations shown nowhere (missing signal, fixed)
- 159 PIT rows of kind `pledge_invoke` (forced sales by lenders: Mangalam Industrial Finance 9 Cr shares, Mar 2026;
  Sigachi 1,15,03,000, Jan 2026; Hubtown 27 Mar 2026, which Reg 31 lists as Invocation 14,00,000 + 17,11,170) reached no
  list: `pledge_events` read only create and revoke. Now "Pledge invoked" in Watch out, Pledges group (in the last 90
  days: Vishnu Prakash R Punglia, 2.33%, 9 filings).
- **Present**: an invocation leads the Pledges group: it is the risk a pledge stands for, realised.

#### T7 SAST rows that are encumbrances could read as "Big investor in" (fragile, fixed); allotments said "bought"
- BSE's Reg 29 list has 224 non-promoter rows whose mode is Pledge / Creation Of Encumbrance / Release ...; 37 by names
  the trustee pattern misses ("Deutsche Bank AG," for Horizon Industrial Parks, Piramal Pharma, Manipal; Comfort Fincap
  "Pledge Creation" 0.33%). None passed the size test on 21 Oct, by chance. `ideas.stake_events` now leaves out any row
  whose mode says pledge, encumbrance, release, invocation or NDU.
- Off-market modes are said: "Amit Kumar Saraogi took 21.42% of the company (pref. allotment)", not "bought".
- **Present**: big investors by how they came in: market, allotment, off market, open offer.

#### T8 Trades in ADRs, warrants, debentures counted as share trades (wrong signal, fixed)
- The filed security type was never read: NSE's archive has ADR/GDR/FCCB 220 rows, warrants 102, derivatives 45,
  debentures 12; among the eligible rows 30 NSE "ADR/GDR/FCCB", 12 "Any other instrument", 2 "Convertible Debenture",
  25 BSE "Any other instrument". Now `security_type_raw` is kept and a type that is not equity flags `not_equity_shares`
  (held back, counted). A blank type is taken as shares, as before.
- **Present**: an instrument other than shares is said in the row and never sized as % of the company.

#### Checked and right (22 Oct)
- Market only: `is_market` is true for "Market Purchase" / "Market Sale" (and now block/bulk deals) and nothing else;
  ESOP/ESOS (3,780), gift, inter-se, off-market, conversion, preferential, allotment, scheme, buyback, rights, bonus,
  transmission never reach the signals. Employee trusts' market buys (category Trust, role other) are not decision-makers.
- Units: of the eligible rows' value, 93.1% is inside the day's traded range; 257 "value filed as price per share", 53
  powers of ten, 1 swap and 131 far outside are held back; 1.5% (no print) and 4.5% (span over the limit, e.g. BHEL
  "11 Feb 2025-12 Feb 2026", a typo of the from-date) are unchecked.
- Thyrocare 17 Aug (Reg 31 and XBRL 2325), Vikram Solar 19 Feb (Reg 31), Paradeep Phosphates 19 Aug (Reg 31 Release
  4,00,00,000 = BSE REVOKE row), Aequs 21 Sep / 14 Oct (Reg 31 Creation 10,05,13,070 twice): PIT and Reg 31 agree.
- Deals: market makers measured (8,017 legs); same client both sides one day (4,548 legs) netted per client in fund
  events; equal legs on both exchanges: 2 (Ohana India Growth Fund, Shankara Buildpro, 04 Sep), kept as two (DL-W8).

#### Open (trading data)
- JB Chemicals, 21-23 Jan 2026 (Tau -> Torrent, Rs 11,917 Cr): NSE (JBCHEPHARM) and BSE (506943) copies both primary
  because neither has an ISIN (`security_match` unmatched; 117 such NSE+BSE groups). Held back (`unmatched_security`),
  so out of signals; the fix is the security master's (a delisted or merged symbol), the other audit's scope.
- ~~13 NSE revision + BSE pairs left unpaired~~ Found 23 Oct (section `unpaired`): BSE files the trade twice (a revision,
  a value filed as 0 corrected: Gateway Distriparks 04 Dec 2025 again on 23 Jan 2026; Khandwala, C.E. Info, Indo-mim);
  NSE's row paired with one copy and the other stood primary. 28 groups, 64 rows, Rs 43 Cr read twice by the signals.
  Fixed: a BSE row left over that is a copy of an NSE row already paired is its copy too (`bse_refiled` in the report).
  Left: a BSE-only company whose re-filing changes the value (no NSE row to pair with).
- 90 market rows whose other exchange's copy files another kind (BSE "ESOP" vs NSE "Market Sale", Shaily Engineering,
  Jubilant Ingrevia trust; Rs 2,612 Cr, mostly held back by other flags): which copy is right needs the filing's PDF.
- 10 of 244 PIT pledges whose create/release is the reverse of Reg 31's (open). The lender and type from Reg 31 are on
  the pledge rows of Today and the Company page (#208).
- Global banks' trading desks: a bank's Financial / Global Markets arm is a dealer (#207); Integrated Core Strategies and
  Societe Generale ODI still typed `fpi` (open).

#### Timing and holdings (23 Oct, sections `timing`, `holding`, on the clean data of 22 Oct)
- Trade to public, the 10,957 open-market rows the signals read: median 1 session, 90% within 4, 95% within 9; 239 rows
  more than 30 sessions late (GNG Electronics, a promoter's Rs 175 Cr sale of 11 Jun made public 18 Sep). The signals,
  the period and the chart marks all take the day made public (`seen` = broadcast date), so a late filing is never
  dated before anyone could read it; the card shows the trade dates in its sentence and "Made public". Right.
- Closed trading window (quarter end to 48 hours after that quarter's results): 114 rows of 9,829 with the results date
  known, Rs 34,366 Cr. Mostly not insiders bound by the window: the Government's offers for sale (LIC, Cochin
  Shipyard), promoter companies moving shares inside the group (Bajaj Finserv 27 Apr), employee trusts (Sonata,
  Jindal Steel). Not flagged on the site: the exchange data cannot tell a designated person from an exempt seller.
- Holding before / after: every row the signals read matches its shares (10,956 `match`, 1 `not_filed`); the 56 that
  differ are held back. `holding_change_pct` is the person's own holding change (labelled so), not a % of the company.

#### Leads from Chain stats (22 Oct, 09:15 IST)
- JB Chemicals -> Open (no ISIN on either copy); Thyrocare -> T2; `price_check`: of the
  2,063 `far_below` primaries 81 are market trades, all held back; the rest are ESOP (595), off-market (286),
  preferential (128) and allotments (116), priced off the market by design; `face_value` 23 market rows, held back.

## 4. Log

- 09:10 IST: inventory and checklist written; Chain stats workflow added; two audits started (trading data;
  corporate data).
- 20:30 IST: corporate data: C1-C4 fixed on audit/corporate-data. After merge: *Clean only* (issues, results),
  `python -m collectors.bse.events --from 2025-10-08 --dataset shareholding --max-xbrl 900` (repeat until no
  `pending`), then *Precompute slim assets* (adjusted prices, track record).
- 19:20-20:15 IST: trading data audited (T1-T8 above) on real rows with *Trading audit*; NSE XBRL 2325, 2427, 3934,
  3962 fetched; PIT pledges compared with Reg 31 (#199). Fixes and tests on `audit/trading-data`.
