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
- [ ] Is every "buy" a buy with the person's own money on the market? ESOP exercise, gift, inheritance, inter-se
      transfer, off-market, conversion of warrants, preferential allotment, pledge, bonus/split credits: which
      reach `is_market` and the signals?
- [ ] Value: as filed vs shares x price; units (rupees vs lakh); zero or missing values; price outside the
      day's range (power of ten, swapped quantity/value).
- [ ] The same trade counted twice: NSE + BSE copies, revisions, BSE's two feeds, multi-day filings.
- [ ] Who: promoter vs promoter group vs director vs KMP vs designated person vs immediate relative; one
      family split into many "decision-makers"; a company (promoter entity) vs an individual.
- [ ] Timing: trade date vs intimation vs exchange broadcast; late filings; trades inside a closed trading
      window; the date we mark on the chart.
- [ ] Holdings before/after vs shares traded (holding_check); % of the company basis.

Pledges
- [ ] Pledge vs encumbrance vs non-disposal undertaking vs invocation; renewals and top-ups; release then
      re-pledge; quantity missing on NSE rows; the quarterly XBRL vs the PIT flow.

Bulk / block deals
- [ ] Client classification (fund, FPI, broker, market maker, individual, promoter); intraday round trips;
      the same order on both exchanges; deals that are an insider's own filed trade.

SAST
- [ ] Acquirer type (investor vs lender's trustee vs promoter); instrument (shares vs warrants vs voting
      rights); "Acquisition" filed for an encumbrance; the % base (total voting capital).

Shareholding
- [ ] Retired ISINs; % base (total vs total less DR shares); stale quarters; pledge as % of promoter shares vs
      of the company; promoter group membership.

Issues (preferential, QIP, rights, warrants)
- [ ] Allottee category (promoter vs others vs mixed); warrants (25% upfront, 18 months) vs shares; the price
      against today's price on the same split basis; approved vs allotted vs listed; amounts in the wrong unit.

Buybacks, corporate actions, results
- [ ] Tender vs open market; premium at announcement vs now; split/bonus ratios applied to prices; results
      standalone vs consolidated, quarter vs year to date, rupee unit (lakh / crore / rupees).

Prices and market cap
- [ ] Split/bonus adjustment; market cap on the trade's day vs today; companies under Rs 100 Cr; SME and T2T.

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

## 4. Log

- 09:10 IST: inventory and checklist written; Chain stats workflow added; two audits started (trading data;
  corporate data).
- 20:30 IST: corporate data: C1-C4 fixed on audit/corporate-data. After merge: *Clean only* (issues, results),
  `python -m collectors.bse.events --from 2025-10-08 --dataset shareholding --max-xbrl 900` (repeat until no
  `pending`), then *Precompute slim assets* (adjusted prices, track record).
