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
| **Encumbrances (SAST Reg 31), new 22 Oct** | NSE `corporate-pledgedata-sast3132` (page *Regulation 31(1) and 31(2)*) | `encumbrances` | to come: pledges with the lender (PR #199) |

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

### F1 The authoritative pledge data was not collected (missing data, fixed #199)
- Pledges came only from PIT filings (no lender; NSE rows carry no share count, D13) and the quarterly XBRL.
- NSE publishes every SAST Reg 31(1)/(2) disclosure: creation / release / invocation of a pledge, a non-disposal
  undertaking or another encumbrance, with the lender, shares and % of the company (`/api/corporate-pledgedata-sast3132`,
  seen in the page's own requests). 1 Sep-21 Oct 2026: 147 events, of which 15 NDUs and 17 "Others" the PIT kinds do
  not separate. Collected daily from #199 (raw kept), backfilled 400 days.
- **Present**: on Today and the Company page, a pledge row should name the lender and the kind (pledge / NDU / other),
  from this table first; the PIT filing is the corroboration.

### F2 A night's NSE filings lost to one timeout; the nightly NSE events run cancelled by the catch-up (reliability, fixed #199)
- R2 Storage Write of 9 Oct (run 37999495517): NSE Insider, Rights and Preferential failed on one read timeout; the
  steps now try three times. NSE Corporate Events of 12, 15 and 21 Oct were cancelled: the catch-up's guard looked
  only for queued runs, a run held by the concurrency group is pending.

### Leads from Chain stats (22 Oct, 09:15 IST), passed to the audits
- JB Chemicals 21 Jan 2026: the Tau Investment sale and Torrent's purchase (Rs 11,917 Cr) each appear twice as
  primary rows (one copy without market cap).
- Thyrocare 17 Aug 2026: Docon's release of 7,94,69,696 pledged shares filed with no mode: kind `missing`, valued Rs 4,916 Cr.
- `price_check`: 2,063 `far_below` and 1,047 `face_value` rows (ESOPs at exercise price are expected; market trades are not).
- Deals: 8,017 of 22,205 legs are market makers (prop/HFT), left out of every signal.

## 4. Log

- 09:10 IST: inventory and checklist written; Chain stats workflow added; two audits started (trading data;
  corporate data).
- 09:40 IST: nightly reliability reviewed (F2); the Reg 31 encumbrance stream added (F1), PR #199, backfill after merge.
