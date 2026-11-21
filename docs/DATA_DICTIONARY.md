# Data dictionary

What each clean table holds, where it comes from and how often it changes.
Cleaning rules for insider trades and deals are in `docs/CLEAN_LAYER.md`;
signal thresholds in `docs/SIGNALS.md`.

| Table (R2) | Grain | Source | Updated |
|---|---|---|---|
| `clean/current/insider_trades.parquet` | One SEBI PIT filing | NSE + BSE insider filings | Nightly (R2 Storage Write) |
| `clean/current/deals.parquet` | Client x security x day x side | NSE + BSE bulk and block deals | Nightly (R2 Storage Write) |
| `clean/current/securities.parquet` | One security | NSE/BSE equity lists + VR export | Nightly (R2 Storage Write) |
| `clean/current/universe.parquet` | One ISIN we know | Security master: latest NSE market cap, else BSE's (`insiders_clean/universe.py`) | Nightly (clean step). Columns: isin, company, nse_symbol, bse_code, market_cap, in_universe (Rs 100 Cr and up), why |
| `clean/current/sast.parquet` | One SAST Reg 29 disclosure line | NSE `/api/corporate-sast-reg29` | Daily (NSE Corporate Events) |
| `clean/current/actions.parquet` | One corporate action | NSE `/api/corporates-corporateActions` | Daily |
| `clean/current/bse_sast.parquet`, `bse_actions.parquet` | One BSE SAST disclosure line / corporate action, linked to NSE's | BSE `Corporatesast`, `DefaultData` | Nightly (R2 Storage Write) |
| `clean/current/bse_meetings.parquet` | One BSE board meeting, linked to NSE's | BSE `boardmeeting_fno` | Nightly (R2 Storage Write) |
| `clean/current/bse_shareholding.parquet` | One BSE-only company x quarter, in NSE's shareholding columns | BSE `Corp_Shareholding_ng` + each filing's inline XBRL | Nightly (R2 Storage Write) |
| `clean/current/bse_promoter_group.parquet` | One BSE-only company x quarter x promoter-group member | The same inline XBRL (Table II) | Nightly (R2 Storage Write) |
| `clean/current/meetings.parquet` | One board meeting | NSE `/api/corporate-board-meetings` | Daily |
| `clean/current/encumbrances.parquet` | One SAST Reg 31(1)/(2) disclosure: a promoter's pledge, non-disposal undertaking or other encumbrance created, released or invoked | NSE `/api/corporate-pledgedata-sast3132` (page *Regulation 31(1) and 31(2)*), raw kept in `raw_v2/nse/encumbrances/` | Daily (NSE Corporate Events, from 22 Oct 2026). Columns (no `isin`: NSE's feed carries the symbol only, so pages key it on the NSE symbol; corrected 12 Nov 2026): event_id, symbol, company, promoter_name, promoter_id, lender, event_type (Creation / Release / Invocation), encumbrance_type (Pledge / Non disposal undertaking / Others), event_from, event_to, shares and pct_of_company of the event, encumbered_shares / encumbered_pct (NSE `encumbHolding`/`encumbPerc`: the holder's encumbrance BEFORE the event), pre_event_holding / pre_event_holding_pct (the holder's shares) and post_event_holding / post_event_holding_pct (the encumbrance AFTER the event: before + created, or before − released; checked on NSE's rows 13 Nov 2026, Themis Medicare 4.89 + 2.71 = 7.60%), as filed, reporting_date, broadcast_date, attachment |
| `clean/current/shareholding.parquet` | One company x quarter | NSE `/api/corporate-share-holdings-master` + each filing's XBRL | Daily |
| `clean/current/promoter_group.parquet` | One company x quarter x promoter-group member | The same shareholding XBRL (Table II) | Daily (NSE Corporate Events) |
| `clean/current/public_holders.parquet` | One company x quarter x public shareholder named over 1% | The same shareholding XBRL (Tables III and IV) | Daily (NSE Corporate Events) |
| `clean/current/tradability.parquet` | One ISIN (NSE equity series, or on an NSE surveillance list) | NSE `/api/reportASM`, `/api/reportGSM`, `/api/reportESM`, `sec_list.csv`, NSE bhavcopy | Nightly (R2 Storage Write; also Tradability flags) |
| `clean/current/tenders.parquet` | One tender offer (buyback, takeover, delisting) | NSE `/api/liveTenderPast-issues` + `liveTenderActive-issues` | Daily |
| `clean/current/daily_buybacks.parquet` | One daily buyback report | NSE `/api/corporates-daily-buyback` | Daily |
| `clean/current/buybacks.parquet` | One buyback, with price and route | tenders + daily buyback reports + corporate actions (`insiders_clean/buybacks.py`) | Daily |

## insider_trades: data-check columns

Added by the data checks (`docs/CLEAN_LAYER.md`, "Data checks").

| Column | Meaning |
|---|---|
| `holding_check` | Holding after - before against the shares traded: `match`, `differs`, `against_side`, `against_side_and_differs`, `not_filed`, `not_applicable` |
| `price_check` | Implied price (`price` = value / shares) against the trade's sessions in our price layer: `inside`, `below`, `above`, `far_below`, `far_above`, `power_of_ten`, `swapped`, or why it was not checked |
| `day_low`, `day_high` | Lowest low and highest high printed on NSE or BSE over the trade's sessions, unadjusted; empty when not checked |
| `marks` | Comma list of checks that failed but hold nothing back (`price_outside_day_range`, `promoter_group_transfer`); `flags` holds those that do |
| `kind` = `holding_only` | A disclosure of a holding with no shares traded; never a trade (`is_market` false, no side) |
| `security_type_raw` | The security as filed (NSE `secType`, BSE `security_type`): Equity Shares, ADR/GDR/FCCB, Warrants, Derivative ... A filed type that is not equity flags the row `not_equity_shares` (held back) (audit 22 Oct) |
| `kind` = `inter_se` + mark `promoter_group_transfer` | A filed market buy by a promoter / promoter-group filer paired, on one exchange, with another's market sale of the same company, dates and shares (prices within 2%): shares moved inside the group, never a market decision (audit 22 Oct, T4) |
| `group_transfer_by_deal` (with `kind` = `inter_se`) | A promoter / promoter-group filer's market trade that is one side of a bulk/block deal pair between two promoter-group clients (`deals.matched_pair`, both `client_is_promoter`): same company and shares, the deal day within the trade dates. Needs only the exchange's deal pair, not both filings (13 Nov 2026: Gallantt Ispat) |
| `cross_with` | Where a promoter, director or KMP market trade is one side of a matched bulk/block deal pair (`deals.matched_pair`): the other side's name as the exchange filed it (a sale's buyer, a buy's seller). Blank otherwise. Gallantt Ispat, 03 Nov 2026: Dinesh R Agarwal → Suryalaxmi Infracon |
| `placement_buyers` | Where a promoter's market sale matches the promoter's own deal leg (same company, day and shares) and two or more non-promoter clients bought that company that day at the seller's price (within 0.05%): their names as filed. V2 Retail, 06 Nov 2026 (14 Nov) |
| `person_role` of a relative | "Directors / Employees Immediate Relative" -> `immediate_relative`; "Promoter(s) Immediate Relative" -> `promoter_group` (ICDR 2(1)(pp)(ii)) |
| `kind` from the transaction type | A blank mode with a transaction type of pledge / revoke / invoke takes that pledge kind (counted `kind_from_transaction_type`) |

## insider_trades and deals: market cap and copies (audit batch 2, 21 Oct 2026)

| Column | Table | Meaning |
|---|---|---|
| `market_cap` | both | Latest market cap (NSE's, else BSE's), rupees: the size of the company today (study universe, token rule, size filters) |
| `market_cap_at_trade` | both | Market cap on the trade's last day (insider: `trade_date_to`; deal: `date`), rupees, from NSE's daily mcap file (`marketcap/daily/nse`, issue size x close); the latest when no dated figure exists |
| `market_cap_date` | both | The session whose market cap was used; blank when the latest was used |
| `market_cap_basis` | both | `trade_date` (that session), `previous_session` (the last one before it, within 10 calendar days), `shares_x_close` (a company NSE does not list: shares in issue at the latest quarter end on or before the trade day, from the shareholding XBRL, times the BSE close of that day or of the last session before it within 10 days; the quarter's shares, so an issue since then is not in them), `latest` (no dated figure: trades after the layer's last day, or a BSE-only name with no close or no filed shares), `none` |
| `pct_of_mcap` | both | `value` / `market_cap_at_trade` x 100 |
| `is_primary`, `primary_id`, `listed_on` | insider_trades | A BSE row is a copy of an NSE row (is_primary false, `primary_id` = the NSE row's `trade_id`, both `listed_on` = `bse,nse`) only when person, ISIN, side, kind, shares and trade dates agree, one BSE row per NSE row; a BSE nightly row (one date filed) agrees when its date lies in the NSE row's span |
| `is_primary`, `listed_on` | deals | Every leg is primary and `listed_on` is its own exchange: NSE and BSE legs are separate executions |
| `same_size_on_other_exchange` | deals | True when the same client has a leg of the same ISIN, day, side and quantity on the other exchange (marked and counted, both kept) |

Cleaning-report counts: `tables.{insider_trades,deals}.market_cap_basis`, `market_cap_layer` (months read, missing,
unreadable), `tables.insider_trades.nse_bse_copies`, `tables.insider_trades.revision_marker`,
`tables.deals.same_size_on_both_exchanges`.

## Deal participants (columns on `deals`, from 12 Oct 2026)

Added by `insiders_clean/participants.py` in the clean step (TODO 23, 16). Read from the client's name only;
NSE and BSE publish nothing else about the client.

| Column | Meaning |
|---|---|
| `client_type` | mutual_fund, insurer, pension, bank, fpi (foreign investor, incl. sovereign funds and global banks), pms_aif, fund_other (a fund not told apart as AIF or foreign by its name), prop_hft (a measured market maker), broker, corporate, trust, individual, unknown |
| `client_type_confidence` | high (the name says it, or the behaviour was measured), medium (a strong marker), low (a weak marker or a person-like name) |
| `client_type_rule` | The rule that matched, e.g. `mutual fund`, `foreign vehicle form`, `looks like a person`, `measured two-way volume` |
| `client_is_promoter`, `client_promoter_basis` | The client is the company's promoter: in its latest promoter-group list (`promoter_group_list`) or filed under PIT as its promoter / promoter group (`pit_filing`). Never a fund, whatever `client_type` says (audit 22 Oct, T5: Fosun Pharma Industrial Pte for Gland Pharma). Counted in `tables.deals.promoter_clients` |
| `investor_group`, `investor_group_id` | One investor across spellings, share classes and series; never merges entity IDs. From `insiders_clean/investor_aliases.csv` (each line with its reason) or a suffix rule |
| `investor_group_rule` | `alias`, `share class`, `series`, or blank (the name itself) |
| `two_way_bought`, `two_way_sold` | (19 Nov 2026) Set when the client bought and sold this security the same day in amounts more than 1% apart: the day's gross shares bought and sold. The leg itself is then the net (larger side, scaled to the difference at its own price); the smaller side's legs are removed, reason `same_day_both_sides_netted` (`docs/CLEAN_LAYER.md`). Empty on one-sided legs and market makers |
| `matched_pair`, `matched_client` | (13 Nov 2026) One buyer and one seller, different clients, same exchange, security and day, the same quantity at the same price (within 0.05%): one transfer. Both legs carry the shared pair id and the other side's name. Pages call it a group transfer when both legs are `client_is_promoter`, else a negotiated cross. Counted in `tables.deals.matched_pairs` |

The cleaning report counts rows by type and confidence under `tables.deals.participants`.

## insider_trades: pledges netted per day (13 Nov 2026)

| Column | Meaning |
|---|---|
| `pledge_day_net` | On pledge rows: the company's net change in pledged shares on that filing day, primary rows only (created - released - invoked) |
| `pledge_rollover` | Shares were both pledged and released that day and the net is under 5% of the larger side (Embassy, 11 Nov 2026: 9.79 cr released, 6.79 cr + 3.00 cr pledged again). Counted in `tables.insider_trades.pledge_rollover_rows` |

## insider_trades: promoter-group link

Added by the clean step from `clean/current/promoter_group.parquet` (`insiders_clean/promoter_group.py`). Identity only:
the filer's `person_id` equals a member's key in the company's latest list, or the name before a bracket on either
side does. Never by similarity; counts in the cleaning report under `promoter_group_link`.

| Column | Meaning |
|---|---|
| `promoter_group_id` | `group:<ISIN>` when the filer is in that company's latest promoter-group list; blank otherwise (unlinked, or no list yet) |
| `promoter_group_quarter` | Quarter end of the list the filing was linked through |
| `promoter_group_key` | `name` (same key as filed) or `name_before_bracket` (HUF karta or trustees in brackets, or a former name) |

## NSE corporate events (`collectors/nse_events/`)

Every run fetches the last 10 days (board meetings: up to 60 days ahead as
well; the tender-offer list whole), so filings NSE adds late are still caught.
Board meetings, tender offers and daily buyback reports are also kept byte for
byte in `raw_v2/nse/{meetings|tenders|daily_buybacks}/` before parsing. Rows are merged into
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
| `holder_kind` | (19 Nov 2026, `insiders_clean/sast.py`) `lender` (a lender's trustee, security agent or bank branch by name: shares held as security; a mutual fund's trustee filing for a scheme is a `holder`), `filing_agent` (a named law firm, or advocates/solicitors, filing for someone), else `holder`. Also on `bse_sast` |
| `held_back_reason` | (19 Nov 2026) Why the row is held back from the signal pages; empty for a holder's move. `lender_or_trustee` and `encumbrance_mode` (mode says pledge, encumbrance, release, invocation, lien): an encumbrance event, shown as "Encumbrance" on Stakes, never "Bought"; `filed_by_law_firm`; `promoter_whole_stake_out_mode_others` (a promoter's 70%+ to 0% with mode Others). Rows are kept; counted per reason in the nightly report (`streams.sast.held_back`, BSE `held_back`). Also on `bse_sast` |

### actions — corporate actions

Kept: buyback, bonus, split, demerger, capital reduction, scheme of
arrangement or amalgamation, rights, dividend (demergers and schemes since
20 Nov 2026). Dropped and counted in the report: interest payments, unit
distributions and the like. Same purposes on `bse_actions`.

| Column | Meaning |
|---|---|
| `purpose` | `buyback`, `bonus`, `split`, `demerger` (NSE `Demerger`, BSE `Spin Off`), `capital_reduction` (BSE `Reduction of Capital`), `scheme` (`Scheme of Arrangement`, `Amalgamation`), `rights`, `dividend` |
| `subject` | NSE's text, e.g. `Rights 3:5 @ Premium Rs 45/-` |
| `ex_date`, `record_date`, `broadcast_date` | As filed |
| `ratio` | Bonus and rights ratio, e.g. `3:5` |
| `face_value`, `rights_premium`, `rights_issue_price` | NSE writes the premium over face value; issue price = face value + premium |
| `dividend_per_share` | Rupees; ordinary + special when both are in one action |
| `face_value_from`, `face_value_to` | Split |
| `needs_price_gap` | True for buybacks and rights. Buyback price and route are not in this feed: see `buybacks` |

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
| `nse_purpose` | NSE's purpose field (`bm_purpose`) as filed, every notice of the meeting joined with ` \| `. A flag can come from it alone while `description` says other things (from 13 Nov 2026; blank on rows written before) |
| `description`, `intimation_ts` | NSE's text and the latest notice time |

Past meetings: NSE's API answers past date ranges (checked 12 Oct 2026: Oct
2025 and Jan-Feb 2026; Feb 2026 whole = 3,472 rows = its two halves
together, so no cap at that size). `run_daily --dataset meetings --from
2025-07-01` fills the product year one month per call; the nightly window
then keeps it current. A postponed meeting arrives as a separate NSE row
("Board meeting Rescheduled") with the original date; it stays in
`raw_json` and the trading-window join skips that date.

### tenders — NSE tender offers

NSE's tender-offer list (market data, "Tender Offer", past and active):
every buyback, takeover and delisting tender since Aug 2015 (225 on 12 Oct
2026, 131 of them buybacks). No date parameters; the whole list each night.

| Column | Meaning |
|---|---|
| `offer_type` | `buyback`, `takeover`, `delisting` or `other`; `offer_type_raw` keeps NSE's spelling (`Buy back`, `BuyBack`, `Buyback`, ...) |
| `offer_price` | NSE's `band` (past) or `floorPrice` (active): the fixed buyback price, or a reverse book building's floor |
| `shares_sought`, `shares_tendered`, `times_tendered` | `issueSize`, `totQty`, `numberOfTimes` |
| `accepted_price` | `allocatedPrice`, where NSE has it |
| `offer_open`, `offer_close`, `status` | Tender window; `past` or `active` |

### daily_buybacks — daily buyback reports

Filed each day a company buys back shares on the market (open-market
route). NSE's answer held the last two months whatever dates were asked
(12 Oct 2026: 153 reports from 13 Aug, 6 companies), so the archive builds
the history night by night. The share count is only in NSE's free text, which
does not say whether it is the day's or the running total, so `text` is kept
as filed and no number is read from it.

### buybacks — one row per buyback

`insiders_clean/buybacks.py`, rebuilt each night from the three sources.

| Column | Meaning |
|---|---|
| `route` | `tender offer` (an NSE tender record), `open market` (daily buyback reports filed), or empty: a 'Buy Back' corporate action with no NSE tender record (e.g. TEAMLEASE, record date 03 Jul 2026) |
| `offer_price`, `shares_sought`, `offer_value` | Tender offers only; `offer_value` = price x shares sought. An open-market buyback's maximum price is only in its PDF announcement, so it is empty |
| `shares_tendered`, `times_tendered`, `offer_open`, `offer_close` | From the tender record |
| `record_date`, `ex_date` | From the corporate action, when there is one. A tender is matched to it when it is the same symbol and opens on or after the record date, within 60 days |
| `daily_reports`, `first_report`, `last_report` | Open market: reports in one run (a gap over 90 days starts a new buyback) |
| `source` | Which of the three lists the row comes from |

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
| `xbrl_error` | Why a file failed, in the parser's words (e.g. `total shares not found`); counted in the run report's coverage |
| `no_promoter_group` | True when the filing has no promoter section at all and public plus non-promoter non-public shares are the whole total (ITC, L&T, ICICI Bank): promoter shares 0 as filed, pledge % blank |
| `members_status`, `promoter_members`, `members_check` | Whether the promoter-group member list was parsed (`ok`, `pending`, `failed: ...`; blank for an older quarter fetched before lists existed), how many members, and whether their shares add up to the promoter total (`match` / `mismatch`) |
| `shareholding_stale` | True when this quarter's XBRL isn't parsed and the pledge figures shown are the company's previous quarter's |
| `{type}_shares`, `{type}_pct` | Ownership by investor type, from the same XBRL (Tables III and IV; `parsers.parse_shp_categories`), for the types below. Shares as filed; % of `pct_base_shares`, SEBI's base, so they add up to 100 and match the filing's own % column and NSE's `promoter_holding_pct` (to 4 decimals instead of 2). Blank until the quarter's own XBRL is read; never carried forward from another quarter. `promoter_shares` is the column above |
| `dr_shares` | Shares a custodian holds against depository receipts (Table IV C1, `CustodianOrDRHolder`): outside the % base, as SEBI's form computes it (HDFC Bank, SBI, Infosys, Reliance, L&T, ITC have some) |
| `pct_base_shares` | `total_shares - dr_shares`, the denominator of every `_pct` (SBI, Sep 2026: 9,230,766,786 - 70,396,990 = 9,160,369,796; promoter 55.45% as filed and listed, 55.03% of all shares) |
| `categories_status` | `ok`, `pending` (not fetched yet), `no_xbrl`, `failed: ...`, or blank (fetched before these columns existed and no raw copy read yet) |
| `categories_check` | `match` when every filed subtotal (domestic institutions, foreign institutions, government, non-institutions, public, non-promoter non-public) equals the sum of its filed sub-categories and the types plus `dr_shares` add up to `total_shares`, within one share; else `mismatch` |
| `categories_unmapped` | What didn't map, as text: a subtotal's shares in none of its filed sub-categories, or a category context the parser doesn't know (named with its shares, never put in a type). Blank when nothing. Nothing is filled by difference |

Investor types (`{type}`), each the sum of the XBRL contexts `<Context>_ContextI` (element `NumberOfShares`) on `CategoryOfShareholdersAxis` listed; SEBI's row in brackets. A category with no holders is left out of the file and counts 0.

| Type | Contexts |
|---|---|
| `promoter` | `ShareholdingOfPromoterAndPromoterGroup` (A); 0 as filed for a company with no promoter group |
| `mf` | `MutualFundsOrUTI` (B1a) |
| `insurance` | `InsuranceCompanies` (B1e) |
| `banks_fi` | `Banks` (B1d), `NBFCsRegisteredWithRBI` (B1i), `OtherFinancialInstitutions` (B1j) |
| `aif` | `AlternativeInvestmentFunds` (B1c) |
| `other_dii` | `VentureCapitalFunds` (B1b), `ProvidentFundsOrPensionFunds` (B1f), `AssetReconstructionCompanies` (B1g), `SovereignWealthFundsDomestic` (B1h), `OtherInstitutionsDomestic` (B1k) |
| `fpi` | `InstitutionsForeignPortfolioInvestorCategoryOne` (B2d), `...CategoryTwo` (B2e) |
| `other_foreign` | `ForeignDirectInvestment` (B2a), `ForeignVentureCapitalInvestors` (B2b), `SovereignWealthFundsForeign` (B2c), `OverseasDepositories` (B2f; ICICI Bank files its ADRs here, 15.8%), `OtherInstitutionsForeign` (B2g) |
| `govt` | `CentralGovernmentOrPresidentOfIndia` (B3a), `StateGovernmentsOrGovernors` (B3b), `ShareholdingByCompaniesOrBodiesCorporateWhereCentralOrStateGovernmentIsPromoter` (B3c) |
| `retail` | `ResidentIndividualShareholdersHoldingNominalShareCapitalUpToRsTwoLakh` (B4g) |
| `hni` | `ResidentIndividualShareholdersHoldingNominalShareCapitalInExcessOfRsTwoLakh` (B4h) |
| `corporate` | `BodiesCorporate` (B4l) |
| `other_public` | `AssociateCompaniesOrSubsidiaries` (B4a), `DirectorsAndDirectorsRelatives` (B4b), `KeyManagerialPersonnel` (B4c), `RelativesOfPromotersOtherThanPromoterGroup` (B4d), `TrustsWhereAnyPersonBelongingToPromoterAndPromoterGroupIsTrusteeOrBeneficiaryOrAuthorOfTrust` (B4e), `InvestorEducationAndProtectionFund` (B4f), `NonResidentIndians` (B4i), `ForeignNationals` (B4j), `ForeignCompanies` (B4k), `OtherNonInstitutions` (B4m: HUF, trusts, LLPs, clearing members; the L&T Employees Trust is here, 14.6% in Sep 2026) |
| `non_public_other` | `EmployeeBenefitsTrusts` (C2), NSE's `employee_trust_pct` to 4 decimals |

Subtotals checked: `InstitutionsDomestic` (B1), `InstitutionsForeign` (B2), `Governments` (B3), `NonInstitutions` (B4), `PublicShareholding` (B), `SharesHeldByNonPromoterNonPublicShareholders` (C), `ShareholdingPattern` (total). Confirmed on 44 real filings, taxonomies 2025-05-31 and 2025-10-31, Jun 2025 to Sep 2026 (HDFCBANK, RELIANCE, SBIN, LT, ITC, INFY, ICICIBANK, ASIANPAINT, COALINDIA, LICI, ZEEL, MOTILALOFS and 21 more companies): all `match`, and every category's filed % equals shares / `pct_base_shares` to the filing's 4 decimals.

### promoter_group — promoter and promoter-group members (TODO item 21)

From Table II of each shareholding XBRL, the same download as the pledge figures. One row per member of one
company's filing for one quarter; a revised filing replaces the original, a later parse of the same filing replaces
the earlier. Parsed rows are first written once to `archive/nse_events/promoter_group/batch=<run time>.parquet`
(never rewritten); this table is rebuilt from all batches. Only the published name is kept: no PAN (NSE masks it
anyway) and no promoter/promoter-group split (NSE masks `TypeOfPromoterShareholding` too).

| Column | Meaning |
|---|---|
| `event_id`, `record_id`, `symbol`, `isin`, `company`, `quarter_end`, `submission_date`, `xbrl_url` | The filing (as in `shareholding`) |
| `member_no` | Order in the filing (individuals first, then bodies corporate, trusts and others, then foreign) |
| `member_name_filed`, `member_name`, `member_id` | Name as filed; display spelling; `entity_key` of the name (the link key) |
| `member_alt_id` | `entity_key` of the name before its first bracket, when different ("VAKIL HUF (VARUN AMAR VAKIL)") |
| `section` | The XBRL section: `IndividualsOrHUF`, `OthersIndianShareholders`, `CentralGovernmentOrStateGovernments`, `NonResidentIndividualsOrForeignIndividuals`, `OtherForeignShareholders` |
| `sub_category` | Plain words: `Individual or HUF`, `Central or state government`, `Non-resident or foreign individual`, or the category the company filed (`Bodies Corporate`, `Trusts`, `Person Acting in Concert`, `Overseas Corporate Bodies`, ...) |
| `shares`, `pct_of_company`, `pledged_shares` | As filed; % of total shares. Members with 0 shares are listed by the filing and kept |
| `members_check` | The filing's members add up to its promoter total: `match` or `mismatch` |
| `xbrl_sha256`, `parsed_on` | SHA-256 of the XBRL bytes NSE sent (the raw copy's `sha256_as_sent`); run date of the parse |

### public_holders — public shareholders over 1% (19 Nov 2026)

SEBI's form names every public shareholder holding more than 1% of the company under its sub-category (Table III
institutions, Table IV non-institutions). From the same shareholding XBRL as `promoter_group`
(`parsers.parse_shp_public_holders`, `insiders_clean/public_holders.py`). One row per holder named in one company's
filing for one quarter; a revised filing replaces the original, a later parse of the same filing replaces the earlier.
Parsed rows go first to `archive/nse_events/public_holders/batch=<run time>.parquet` (never rewritten); this table is
rebuilt from all batches. No PAN (NSE masks it). Only NSE filings so far (not `bse_shareholding`).

In the XBRL each holder is `D_<Section>_Context<n>` (`NameOfTheShareholder`) with `<Section>_Context<n>`
(`NumberOfShares`). Sections read, each seen in real filings (123 of Sep 2026, 5 of Jun 2026): `MutualFundsOrUTI`,
`AlternativeInvestmentFunds`, `InsuranceCompanies`, `ProvidentFundsOrPensionFunds`, `NBFCsRegisteredWithRBI`,
`OverseasDepositories`, `OtherNonInstitutions`, and `DetailsOfSharesHeldBy` + `Banks`, `OtherFinancialInstitutions`,
`OtherInstitutionsDomestic`, `ForeignDirectInvestment`, `InstitutionsForeignPortfolioInvestorOne` / `Two`,
`OtherInstitutionsForeign`, `CentralGovernmentOrPresidentOfIndia`, `StateGovernmentsOrGovernors`,
`ShareholdingByCompaniesOrBodiesCorporateWhereCentralOrStateGovernmentIsPromoter`, `DirectorsAndDirectorsRelatives`,
`KeyManagerialPersonnel`, `TrustsWhere...Trust`, `InvestorEducationAndProtectionFund`,
`ResidentIndividualShareholdersHoldingNominalShareCapitalInExcessOfRsTwoLakh`, `NonResidentIndians`,
`ForeignCompanies`, `BodiesCorporate`. Not seen in any filing, so not read (a name there is counted in the run
report's `public_holders_unmapped` and a note, never typed): venture capital, asset reconstruction, sovereign wealth
funds, foreign venture capital, associate companies, relatives of promoters, foreign nationals, individuals up to
Rs 2 lakh. An "any other" row marked `WhetherACategoryOrMoreThan1PercentageOfShareholding` = `Category` is a
sub-category total typed as a name ("Foreign Institutional Investors", "HUF"), not a holder: left out, counted.
Table IV C (depository-receipt custodian, employee benefit trusts) is not public and not read.

| Column | Meaning |
|---|---|
| `event_id`, `record_id`, `symbol`, `isin`, `company`, `quarter_end`, `submission_date`, `xbrl_url` | The filing (as in `shareholding`) |
| `holder_no` | Order in the filing (domestic institutions, foreign, government, non-institutions) |
| `holder_name_filed`, `holder_name` | Name as filed; display spelling |
| `holder_key` | The name for joining across companies and quarters: lower case, punctuation out, `&` as `and`, Ltd / Limited / Pvt / Private and a leading "The" dropped, Co / Corp / Intl / Funds spelled one way; "A/c ..." kept (written `ac`), so each scheme account stays its own holder. Joined by `-`, so it is also an `/entity` id. Never by similarity |
| `type` | The `{type}` of `shareholding` the section belongs to: `mf`, `insurance`, `banks_fi`, `aif`, `other_dii`, `fpi`, `other_foreign`, `govt`, `hni`, `corporate`, `other_public` |
| `category`, `section`, `sub_category` | SEBI's sub-category context (as `parse_shp_categories` reads it), the XBRL section as filed, and the filed category of an "any other" row (`Clearing Members`, `Trusts`, `LLP`, ...) |
| `shares`, `pct_of_company` | Shares as filed; % of `pct_base_shares` (total less depository-receipt shares), computed from the shares: taxonomy 2025-05-31 files the % as a percentage, 2025-10-31 as a fraction |
| `holders_check` | `ok`; `unmapped` (the filing also names holders in a section not read); `over_category` (a category's named holders add up to more than its filed total; never seen in 128 real filings) |
| `xbrl_sha256`, `parsed_on` | As in `promoter_group` |

Change since the last quarter (`public_holders.changes`, computed on the page, not stored): per company and
`holder_key`, its latest quarter in the table against the one before: `new` (named now, not before: crossed 1%),
`exited` (named before, not now: under 1% or sold out; the filing does not say which), `added`, `cut`, `same`, or
`no_previous` (only one quarter read: nothing compared); `shares_change` in shares, `pct_change` in points of the
company. A quarter whose filing names nobody adds no rows, so the page says when the shareholding table has a newer
quarter than the holder list.

### preferential and rights — NSE issue records, one row per stage record

Two sources are stacked, newest copy per record winning: NSE's latest-100 lists kept as daily snapshots (`canonical/nse/{preferential,rights}_issue/`), and, from 12 Oct 2026, every filing NSE posted in a date window with its parsed XBRL (`archive/nse_events/issues/`, below). Records posted before 8 Oct 2025 are kept (counted in the report): their lock-ins run into the product window. An issue has two records, **In-Principle** (board date, amount, consideration; preferential also the allottee category) and **Listing Stage** (offer price, shares allotted, allotment, listing and trading-approval dates; rights also ratio, record date, issue open and close). They have separate `app_id`s and no shared key, so a listing record is linked to its approval by ISIN: the one In-Principle record filed in the 180 days before it, if there is exactly one.

| Column | Meaning |
|---|---|
| `stage` | `in_principle` or `listing` |
| `posted_on`, `submitted_on` | NSE posting date (`systemDate`/`sysDateTime`; the fields NSE calls `boardResDate` hold this too, not the board meeting) and the date filed |
| `board_date`, `amount_total`, `consideration`, `allottee_category` | In-Principle fields (`PROMOTER`, `NON_PROMOTER`, `MIXED`); on a listing record they are copied from its linked approval |
| `offer_price`, `shares_allotted`, `shares_listed`, `allotment_date`, `listing_date`, `trading_approval_date`, `amount_raised` | Listing-stage fields |
| `ratio`, `record_date`, `issue_open_date`, `issue_close_date` | Rights, listing stage |
| `link_status`, `linked_app_id` | `linked`, `ambiguous` (more than one possible approval; nothing copied), `no_in_principle_in_data` (its approval is not in the filings we hold), `more_shares_than_approved` (the only candidate approval's XBRL proposed fewer securities than were allotted, so it is another issue; nothing copied) |
| `xbrl_status` | Preferential: `ok`, `pending`, `failed: <error>`, `no_xbrl`, or blank when the record is only in the snapshots |
| `instruments`, `securities_proposed` | Preferential In-Principle XBRL: security types filed (`Equity Shares; Warrants`) and the total number proposed; copied to a linked listing record |
| `icdr_min_price`, `relevant_date` | Preferential In-Principle XBRL: the minimum issue price under SEBI ICDR and the relevant date, **as filed**; blank when the issue's instruments state different ones. Copied to a linked listing record |
| `vs_icdr_min` | Offer price vs the filed minimum, % |
| `icdr_min_ours`, `icdr_ours_exchange`, `icdr_ours_note` | **Our estimate** of the minimum: the higher of the 90- and 10-session VWAP (traded value / volume, all series) before the filed relevant date, on the exchange with more volume, from our bhavcopy. Blank with a reason (`no_prices`, `under_90_sessions`, `split_or_bonus_in_window`) |
| `lock_in_filed`, `lock_in_basis` | Listing records: whether the listing XBRL has lock-in lines, and whether the lock-in table uses them (`filed`) or the rule (`rule`) |
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

### preferential_allottees — proposed allottees, one row per name in a preferential In-Principle XBRL

| Column | Meaning |
|---|---|
| `app_id`, `isin`, `symbol`, `company`, `posted_on`, `board_date` | The approval |
| `allottee`, `allottee_id` | Name as filed (display form) and its entity key (`insiders_clean/entities.py`) |
| `security_type`, `securities` | Instrument and number proposed for that allottee |
| `issue_category`, `promoter` | The XBRL gives no promoter status per allottee: `promoter` is True for a promoter issue, False for a non-promoter one, blank for `MIXED` |

### preferential_lockins — lock-in lines, one or more per allotment (listing record)

| Column | Meaning |
|---|---|
| `basis` | `filed`: a line of the listing XBRL (period and shares as the company filed them, possibly more shares than this allotment, e.g. an older lock-in); `rule`: none filed, so promoters 18 months and others 6, on linked records only |
| `period_filed`, `months`, `who` | Filed text (`Equity shares for 18 months`), months read from it, and `Promoters`/`Others` for rule lines |
| `shares` | Filed lock-in shares; for a rule line the shares allotted when the issue has one category, blank for `MIXED` |
| `trading_approval_date`, `expires` | Lock-in counts from trading approval; `expires` blank when the period is not in whole months |

### qip — NSE QIP records, one row per stage record (window filings only)

| Column | Meaning |
|---|---|
| `stage`, `posted_on` | `in_principle` or `listing`; NSE's posting date (`boardResolutionDate` in NSE's QIP lists holds the posting date) |
| `board_date`, `shareholder_approval_date`, `amount_total`, `listed_at`, `discount_in_notice_filed` | In-Principle fields; the last is NSE's `prcntagePerSecrtyProDiscNotice` as filed (values seen 0, 0.0005, 0.05; unit not stated, not shown) |
| `bid_open_date`, `bid_close_date`, `relevant_date`, `floor_price`, `issue_price`, `discount_per_share`, `allotment_date`, `shares_allotted`, `allottees`, `amount_raised`, `listing_date`, `trading_approval_date` | Listing fields as filed. `floor_price` is NSE's minimum issue price; some filings give the issue price there |
| `shares_listed` | As filed; some filings give the shares of this issue, others the company's total, so no % of equity is derived from it |
| `issue_vs_floor` | Issue price vs the filed floor, % |
| `amount_unreliable` | Amount zero, above ₹1 lakh crore, or more than 2x away from shares x issue price: blanked |
| `link_status`, `linked_app_id` | As for preferential |

### qip_allottees — allottees named in a QIP listing XBRL

`app_id`, `isin`, `symbol`, `company`, `posted_on`, `allotment_date`, `allottee`, `allottee_id`, `category` (as filed: `Foreign Portfolio Investor`, `Mutual Fund`, `Systemically important NBFC` ...), `shares`, `pct_of_issue` (filed as a fraction, shown as %).

### results — financial results from NSE's integrated filing, read from their XBRL (from 15 Oct 2026)

`collectors/nse_events/run_daily.py` stream `results`, parser `insiders_clean/results.py`. NSE's
`/api/integrated-filing-results` (type `Integrated Filing- Financials`, confirmed 15 Oct 2026) lists each filing; its
XBRL is fetched once (raw in `raw_v2/nse/results_xbrl/`, the lists in `raw_v2/nse/results_list/`) and every fact
kept in the archive (`archive/nse_events/results/year=YYYY.parquet`, `xbrl_json`). No model reads results.
`clean/current/results.parquet` is one row per filing (standalone and consolidated are separate filings; a
revision is its own row, with `revision` `Revision`). Amounts are rupees as filed; the XBRL has no prior-year
quarter, so year-on-year comparisons need our own history.

| Column | Meaning |
|---|---|
| `event_id`, `seq_id` | `nse:result:{seq_Id}`, NSE's id of the filing |
| `symbol`, `company`, `isin`, `company_display`, `unmatched_security` | As listed; ISIN from the XBRL, else the security master |
| `period_end`, `audited`, `consolidated`, `revision`, `revised_at`, `revision_remark` | As NSE lists them |
| `broadcast_at`, `broadcast_date` | NSE's broadcast time (IST), else the filing's creation time |
| `kind` | XBRL layout from its file name: `INDAS`, `NBFC_INDAS`, `BANKING`, `GI`, `LI` |
| `xbrl_url`, `ixbrl_url`, `pdf_url` | Links; `pdf_url` blank when NSE shows `.../corporate/null` |
| `xbrl_status` | `ok`, `pending` (refused or over the night's cap of 500; retried), `no_xbrl`, `failed: <error>` |
| `bse_code`, `xbrl_symbol`, `rounding`, `reporting_quarter`, `period_type`, `period_start`, `period_end_xbrl`, `board_meeting`, `audit_opinion`, `segments` | From the XBRL |
| `quarter_*`, `ytd_*` (`revenue`, `other_income`, `total_income`, `total_expenses`, `finance_costs`, `depreciation`, `profit_before_exceptional_and_tax`, `exceptional_items`, `profit_before_tax`, `tax`, `profit`, `profit_owners`, `eps_basic`, `eps_diluted`), `ytd_start` | The quarter and the year to date under the INDAS names; blank where the layout files a line under other names (all facts are in the archive). `revenue`, `profit` and `profit_owners` are read under each layout's own names (20 Nov 2026, `results.TOP_LINE`): see `revenue_basis` |
| `revenue_basis` | Which line `revenue` is: `ind_as_revenue` (INDAS, NBFC_INDAS: `RevenueFromOperations`), `igaap_revenue` (NONINDAS: `RevenueFromOperations`), `bank_total_income` (BANKING: `Income`, interest earned plus other income; profit `ProfitLossForThePeriod`, owners' `ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates`), `insurer_net_premium` (LI: `NetPremiumIncome`; profit `ProfitLossAfterTaxAndExtraordinaryItems`), `insurer_premium_earned` (GI: `PremiumEarned`; profit `ProfitLossAfterTax`). Blank when the filing has no such line. Comparisons (year ago, derived quarters) are made only within one basis and one of standalone / consolidated |
| `ytd_disagrees` | True where the filing's quarter revenue is above its own year to date (neither is used) |
| `superseded` | A later filing of the same company, period end and basis was broadcast |
| `quarter_derived` | True where the filing gives only its year to date (a half year: no quarter context of about three months) and the `quarter_*` lines are that less the previous filing on the same basis covering the same year to the quarter before (13 Nov 2026); EPS is not derived |

## Archive and raw layer columns (not clean tables)

| Column | Where | Meaning |
|---|---|---|
| `intraday_round_trip` | `archive/canonical/.../bulk_deals`, `block_deals` | True when the row is a leg of a same-day, same-client, equal-size buy+sell. Absent on rows written before 09 Oct 2026; may be boolean or text, read with `as_flag` |
| `canonical_prev_app_id`, `canonical_submission_type`, `canonical_revision_remark` | archive, NSE insider | NSE's own revision markers from the filing list (clean table: `prev_app_id`, `nse_submission_type`, `nse_revision_remark`). Not part of the row id |
| `first_seen`, `last_seen` | archive | Run dates a row was first and last collected |
| `event_id`, `kind`, `stage`, `app_id`, `posted_on`, `xbrl_url`, `xbrl_status`, `xbrl_json`, `raw_json` | `archive/nse_events/issues/year=YYYY.parquet` | One row per further-issue filing (`{kind}:{stage}:{appId}`), NSE's list row as JSON, and the parsed XBRL facts (`{'main': ..., 'groups': ...}`) for preferential filings and QIP listings |
| `kept`, `drop_reason` | `archive/nse_events/{actions,meetings}/`, `archive/bse_events/{sast,actions,meetings}/` | (21 Nov 2026, owner: every raw row reaches the database) Every row the exchange sent is archived; `kept` false marks a row the clean table leaves out and `drop_reason` says why: `purpose not kept (action_purpose)` (an action that is not a buyback, bonus, split, demerger, capital reduction, scheme, rights or dividend: `purpose` is `other`, `subject` the exchange's text), `no kept purpose (_BM_FLAGS)` / `no kept purpose (BM_FLAGS)` (a meeting with none of the flagged purposes: the purpose text in `nse_purpose` / `description`, flags false), `no symbol or meeting date` (NSE) / `no scrip code or meeting date` (BSE) (a row that cannot be keyed to a meeting, stored on its own), `regulation 10(5) not kept (SAST_KEPT)` and the like (BSE SAST of another regulation; `regulation` is `Reg10(5)`), `repeat of a disclosure in the same answer (same event_id, fields outside the id differ)` (BSE SAST: a second row of one disclosure, e.g. Company_Name with BSE's `-$`, under its own id). Empty on rows archived before then (all kept). The clean step takes the kept rows and drops both columns (`insiders_clean/archive.clean_view`), counting the rest by reason (`archive_not_kept` in the run reports); a not-kept meeting has its own `event_id` (`bm_other`, `bse_bm_other`), so it never takes the place of a kept one. Older rows: `scripts/raw_reparse.py` |
| `bids_json` | `archive/nse_events/tenders/` | (21 Nov 2026) NSE's bid book of an open offer (`demand`, `bidDetails`), as sent; `raw_json` leaves it out as before. Archive only: not on `clean/current/tenders.parquet` |
| `raw_json` | `archive/announcements/{nse,bse}/`, `archive/canonical/bse/{bulk,block}_deals/` (history rows) | (21 Nov 2026) The exchange's row as sent, every field: NSE's `difference`, `voiceSummary`, `voiceUrl`; BSE's `AGENDA_ID`, `ANNOUNCEMENT_TYPE`, `ATTACHMENTNAME`, `AUDIO_VIDEO_FILE`, `CRITICALNEWS`, `DataInsDate`, `FILESTATUS`, `Investor_Presentation`, `NSURL`, `OLD`; the deal history's `Security_Name`. Not part of a deal's `canonical_event_id`. A row seen again without it keeps the archived copy (`archive.merge`, `KEEP_IF_MISSING`). Empty on rows archived before then until `scripts/raw_reparse.py` fills it |
| `raw_v2/...` | R2 | Exact response bytes and one fetch record each: see `docs/CLEAN_LAYER.md` ("Raw layer") |
| `raw_v2/nse/shareholding_xbrl/` | R2 | Each shareholding XBRL fetched from 12 Oct 2026, gzip-compressed (`.gz`, no timestamp, so the same file is one blob); the fetch record's `params.sha256_as_sent` is the hash of the uncompressed bytes |
| `event_id` (`nse:{seq_id}`), `seq_id`, `symbol`, `isin`, `company`, `industry`, `subject`, `text`, `file_url`, `file_type`, `file_size`, `file_bytes`, `has_xbrl`, `broadcast_at`, `disseminated_at`, `broadcast_date` | `archive/announcements/nse/year=YYYY/month=MM.parquet` | One row per NSE announcement from 13 Oct 2026 (`collectors/nse_events/announcements.py`), values as filed: `subject` is NSE's subject line, `text` its one-line description, `broadcast_at` NSE's broadcast time in IST. `file_url` is empty where NSE shows `-` (no attachment); `file_type` is `pdf` or `zip` (several PDFs, or a PDF and its XML); `file_bytes` is read from NSE's size text (`0` where NSE shows "0 Bytes"). Concall announcements are archived since 15 Oct. `raw_json` (21 Nov 2026): NSE's row as sent. No clean table yet |

## Insider trades: results dates and the trading window

Added by `scripts/clean_writer.py` from `clean/current/meetings.parquet` plus the BSE meetings NSE has not got
(`bse_meetings.parquet` rows with `on_nse` false, e.g. BSE-only companies; `insiders_clean/trading_window.py`),
joined on ISIN, or on NSE symbol where a meeting has no ISIN; blank when the company has no results meeting in
our data in the 100 days before the trade. The cleaning report's `trading_window.meetings_read` counts both parts.

| Column | Meaning |
|---|---|
| `results_date` | The latest board meeting on results (not postponed) whose window had reopened by the first trade day |
| `window_open_date` | `results_date` + 2 calendar days: SEBI PIT closes the window until 48 hours after the results. NSE gives the meeting date, not the time results were filed; results filed after midnight reopen it a day later than this |
| `sessions_since_window_open` | NSE sessions from `window_open_date` to the first trade day; 0 = the first session the window was open |
| `window_open_buy` | An open-market buy with `sessions_since_window_open` below 5 (`WINDOW_OPEN_SESSIONS`) |

## BSE events (`collectors/bse/`)

SAST Reg 29 and corporate actions from BSE, in NSE's columns (`collectors/nse_events/parsers.py`) plus `exchange` =
`BSE` and `bse_code`. Archive: `archive/bse_events/{sast|actions}/year=YYYY.parquet` by `event_id` (Company_Name left
out of the SAST hash: BSE appends `-$` to it on some days). Raw: `raw_v2/bse/{sast|corporate_actions}/`. Report:
`clean/reports/bse_events/{date}.json` (calls, fetched, added, dropped, windows split, weekdays with no row, linked).
Pages read NSE's table plus the BSE rows with `on_nse` false (`insiders_clean/bse_events.py::with_bse`).

| Column | Meaning |
|---|---|
| `bse_code`, `isin`, `nse_symbol` | BSE scrip code as filed; ISIN and NSE symbol from the security master |
| `symbol` | The NSE symbol when the company has one (pages and the Company page are keyed by it), else the BSE code |
| `on_nse`, `nse_event_id` | The same disclosure or action is in NSE's table: SAST on ISIN, last trade date, direction and shares within 1% or 1 share; actions on ISIN, purpose and ex-date. Shown once, as NSE's row |
| `listed_on` | `bse` or `bse,nse` |
| SAST `regulation` | `Reg29(1)` or `Reg29(2)`; BSE's Reg 10(5)/10(6) and other notes in the same list are dropped and counted |
| SAST `broadcast_ts` | BSE's dissemination day (no time) |
| SAST `is_promoter` | BSE's promoter-group column (Yes/No) |
| SAST `diluted_post_pct` | % after on a diluted basis, as filed |
| actions `ratio`, `dividend_per_share`, `face_value_from/to` | From BSE's purpose text (`Bonus issue 1:2`, `Final Dividend - Rs. - 5.0000`, `Stock Split From Rs.5/- to Rs.1/-`). BSE gives no rights ratio or price |

### bse_meetings — BSE board meetings (from 22 Oct 2026)

NSE's `meetings` columns (`results`, `dividend`, `buyback`, `bonus`, `fund_raising`, `split`, `rights`,
`preferential`, `purposes`, `description`, `intimation_ts`) plus the BSE columns above. Archive:
`archive/bse_events/meetings/year=YYYY.parquet`; raw: `raw_v2/bse/board_meetings/`. Kept when a purpose flag is set;
meetings on other business only (`General`, authorised capital, ...) are dropped and counted
(`dropped_other_purposes`).

| Column | Meaning |
|---|---|
| `meeting_date` | BSE's `MEETING_BOARD_DATE` |
| flags | From BSE's purpose names (`PURPOSE_NAME`, joined by `;`): `Quarterly Results`, `Audited Results` -> results; `Issue Of Warrants` -> preferential; a rights issue of NCDs is not `rights`. BSE's purpose list has no fund-raising name (a QIP meeting is filed as `General`), so `fund_raising` is set only when a purpose says so |
| `description` | BSE's purposes, joined by ` \| ` |
| `intimation_ts` | BSE's `DT_TM`, the time the meeting was intimated |
| `moved` | Archive only: a date BSE lists in `Table1` as moved away from (`CancelFla` `Revised`). The clean step drops these rows and the meeting listed on that date when it was intimated no later than the move (`moved_away`) |
| `on_nse`, `nse_event_id` | NSE's table has a meeting of the same ISIN on the same day |

Each window is read whole and in 15-day pieces, the rows united (`collectors/bse/events.py::meetings_window`): on
22 Oct 2026 October 2026 asked as one month answered 892 meetings (twice), its two halves 916, the 24 missing being
recent listings. The report counts `rows_only_in_whole_window` and `rows_only_in_pieces`.

### bse_shareholding — shareholding patterns of BSE-only companies (from 22 Oct 2026)

NSE's filing wins for a company on both exchanges: BSE's filing is neither read nor shown when the security master
gives the company an NSE symbol, or its ISIN is in NSE's `shareholding` table. So the two tables never hold the same
company and can be stacked (`insiders_clean/bse_events.py::with_bse(nse, bse)`). One row per company and quarter
(the newest submission; older ones are `superseded` and never read). Same columns and meaning as NSE's `shareholding`
above, read from each filing's inline XBRL (SEBI's `in-bse-shp` taxonomy, the contexts NSE's XBRL uses) by NSE's own
parsers through `collectors/bse/parsers.py::ixbrl_facts`, with these differences:

| Column | Meaning |
|---|---|
| `promoter_holding_pct`, `public_holding_pct`, `employee_trust_pct` | BSE's list has no holdings: computed from the XBRL as % of `pct_base_shares` (SEBI's base, as NSE's listing), to 4 decimals. `employee_trust_pct` = `non_public_other_pct` |
| `xbrl_status` | As NSE's, plus `superseded` (a later submission of the quarter exists) and `on_nse` (an archive row whose company NSE's table has since got) |
| `symbol`, `bse_code`, `isin`, `nse_symbol`, `listed_on`, `on_nse` | `symbol` is the BSE code (BSE-only); `listed_on` `bse` |
| `quarter_id`, `revised` | BSE's quarter number (`nqtrid`); a fraction (`129.01`) marks a revised filing |
| `exchange` | `BSE` |

A filing whose XBRL is not read yet holds no figure and is left out (`not_parsed_yet`; it waits in the archive as
`pending`, at most 150 read a night). Run-report counts (`clean/reports/bse_events/{date}.json`, stream
`shareholding`): `listed`, `dual_listed_skipped`, `isin_in_nse_table_skipped`, `xbrl_fetched`, `xbrl_status`,
`categories_status`, and in `clean`: `dual_listed_left_out`, `isin_in_nse_table_left_out`, `not_parsed_yet`,
`unmatched_securities`; `coverage` is NSE's coverage block. Archive: `archive/bse_events/shareholding/year=YYYY.parquet`;
raw: `raw_v2/bse/shareholding_filings/` (the lists) and `raw_v2/bse/shareholding_xbrl/` (each file gzip-compressed with
no timestamp, `params.sha256_as_sent` the hash of the bytes BSE sent). Checked live on 22 Oct 2026: Oscar Global
(530173) and BKM Industries (539043), Sep 2026: investor types `match`, members add up to the promoter total.

### bse_promoter_group — promoter-group members of BSE-only companies

NSE's `promoter_group` columns, from the same inline XBRL; write-once batches in
`archive/bse_events/promoter_group/batch=<run time>.parquet`, the table rebuilt from all of them. The clean step adds
these lists to NSE's for the insider filings' promoter-group link (`promoter_group_id` = `group:<ISIN>`).

## BSE insider and deals history (archive columns)

`scripts/bse_history_backfill.py` writes BSE rows into `archive/canonical/bse/{insider_trading|bulk_deals|block_deals}/`
with `source` = `bse_insider_csv` or `bse_deals_history` (not part of the row id). Insider rows carry, beyond the
nightly fields, `transaction_date_to`, `intimation_date`, `pct_before`, `pct_after`, `security_type_prior`,
`security_type_post`, `buy_units`, `sell_units`, `derivative_specification`, `trade_exchange` (where the trade was
executed: `BSE`, `NSE` or blank). Clean insider rows from BSE's CSV therefore get the intimation date and both Reg 7(2)
deadline checks; rows from the nightly page capture still don't.

## BSE day reconciliation (`clean/reports/announcements_bse/reconciliation/`)

BSE states its own count of filings for a day. `{day}.json` is written by every full fetch of the day: `bse_count`,
`fetched_unique`, `rows_without_id` (rows BSE sends without a NEWSID, which the archive cannot key; `without_id` lists
up to 50 of them), `pages`, `retries` (repeat fetches after a short answer), `short`, `checked_at_utc`,
`workflow_run_id`. `check/{day}.json` is written by `scripts/bse_reconcile.py`: `bse_count` against `archived` with a
`status` of `ok`, `one_short` (usually one row without an ID), `short`, `over` or `not_checked`. NSE gives no count: its
windows are fetched twice (whole, then in two halves) and the report names any difference.

## Filing text cache (`archive/filing_text/{nse|bse}/year=YYYY/month=MM/day=DD.parquet`)

One file per exchange and broadcast day, one row per announcement file (`event_id` of `archive/announcements/`; the
NSE XBRL-feed rows `nse:xbrl:*` are left out). Written by `scripts/filing_text_extract.py`, no model. The text is what
the reader receives from `announcement_sample.text_of` (PDF text with `pdftotext -layout`, a ZIP's PDFs under
`=== file: name ===` lines, XBRL facts where the attachment is XBRL) without the model length cut. Raw: cleaning
for a model comes later. We keep no PDFs.

| column | meaning |
|---|---|
| `event_id`, `exchange`, `broadcast_date`, `file_url` | the announcement and its file link |
| `status` | `ok`, `no_text` (no text layer, scanned?) or `failed` |
| `tries`, `reason` | attempts so far (a missing file, HTTP 404 or 410, counts as final); the error of a failure |
| `file_bytes`, `file_sha256` | size and SHA-256 of the downloaded file |
| `extractor`, `extracted_at` | version of the extraction and when it ran (UTC) |
| `pages`, `chars`, `notes` | pages (form feeds) and characters of the text; the extraction's notes |
| `text` | the extracted text |

## Market flows (`clean/current/market_flows.parquet`, from 19 Nov 2026)

What foreign portfolio investors, domestic institutions and mutual funds bought and sold across the market, for a
context line (`streamlit_app/screens/market_flows.py: flows_line`). `scripts/market_flows.py`, parsers in
`insiders_clean/market_flows.py`. Official sources only (the exchange, the depository, the regulator; NSDL and SEBI
asked for by the owner, 19 Nov 2026), each fetched and read on 19 Nov 2026 (fixtures in `tests/fixtures/market_flows/`).

| Source (`source`) | Where | Segments | History | Lag |
|---|---|---|---|---|
| `nse` | `www.nseindia.in/api/fiidiiTradeReact` (NSE, BSE and MSEI) and `/api/fiidiiTradeNse` (NSE alone); the page `/reports/fii-dii` | `cash_nse_bse_msei`, `cash_nse`; categories `fpi` (NSE's "FII/FPI"), `dii` | **None**: the latest day only, date parameters ignored. Rows exist from the first nightly run | Same evening (T) |
| `nsdl` | `fpi.nsdl.co.in/web/Reports/Archive.aspx` (form post, one month to the date asked) | per asset class (`equity`, `debt_general`, `debt_vrr`, `debt_far`, `hybrid`, `mutual_funds`, `aif`, their sub-total) and route (`{asset}_exchange`, `{asset}_primary`, `mutual_funds_{equity,debt,hybrid,solution_oriented,other}_schemes`), `total`; category `fpi` | Years (read from Oct 2025 on 19 Nov 2026: 273 reporting days, 01 Oct 2025 - 18 Nov 2026) | Reporting date T+1 (custodians' reports of the previous trading day(s)) |
| `sebi` | `sebi.gov.in/sebiweb/other/OtherAction.do?doMfdTrendsSearch=yes` (form post `date=DD-MM-YYYY`, one month to the date) | `equity`, `debt`; category `mf` | Read from 01 Oct 2025 (270 dates); exchange holidays are printed as zero rows and kept | About two weeks: on 19 Nov 2026 the newest day was 04 Nov |

| Column | Meaning |
|---|---|
| `date` | NSE and SEBI: the trading date. NSDL: the **reporting** date (`date_basis`) |
| `source`, `segment`, `category` | As above |
| `buy_cr`, `sell_cr`, `net_cr` | Gross purchases, gross sales and net in Rs crore, as printed (NSDL and SEBI print negatives in brackets). A row whose buy less sell is not its net (more than Rs 0.02 Cr) is dropped and noted |
| `provisional` | True for NSE (the exchanges compile it from trading members' client categories on T day); False for NSDL and SEBI (custodians' reports) |
| `date_basis` | `trade` or `reported` |

Checks: each NSDL month's equity days against NSDL's own "Total for {month}" and each SEBI month against its Total
(within Rs 1 Cr); a month that does not add up is named `short` in the report. Not kept: NSDL's net in USD and RBI
rate, NSDL's and SEBI's derivative tables, NSDL's DII pages (`DIIGenerateReport.aspx`, not read yet).

### fpi_sector_flows — NSDL fortnightly sector-wise FPI investment (`clean/current/fpi_sector_flows.parquet`)

From `fpi.nsdl.co.in/web/StaticReports/Fortnightly_Sector_wise_FII_Investment_Data/FIIInvestSector_*.html` (listed
on `FPI_Fortnightly_Selection.aspx` from 2012; file names are not regular, so the list is read, not guessed). One row
per fortnight (15th and month-end) and BSE sector (24 and `Grand Total`), from 15 Oct 2025. Published a few days
after the fortnight; the nightly reads the newest two not stored.

| Column | Meaning |
|---|---|
| `fortnight_end`, `period_start` | The fortnight the net investment is for |
| `sector` | NSDL's sector (BSE's industry classification; `Sovereign`, `Others`, `Grand Total`) |
| `net_equity_cr`, `net_total_cr`, `net_equity_usd_mn`, `net_total_usd_mn` | Net FPI investment in the fortnight: equity, and all segments (debt, hybrid, mutual funds, AIF); whole crores / USD mn as printed |
| `auc_equity_cr`, `auc_total_cr` | Assets under custody at the fortnight end |
| `prev_net_equity_cr`, `prev_period_start`, `prev_period_end` | The previous fortnight's equity net as restated in this report |

A report whose sectors do not add to its Grand Total (more than Rs 24 Cr, the rounding of 24 rows) is not kept.
Archive: `archive/market_flows/{nse|nsdl|sebi|nsdl_sector}/year=YYYY.parquet` (the columns above and `fetched_at`; a
later fetch of a key replaces it). Raw: `raw_v2/nse/fiidii_{all|nse}/`, `raw_v2/nsdl/{fpi_daily|fpi_sector_list|fpi_sectors}/`,
`raw_v2/sebi/mf_trends/`. Report: `clean/reports/market_flows/{date}.json`.

## Fund month-end portfolios (`archive/mf_holdings/month=YYYY-MM/{house}.parquet` and `clean/current/mf_*.parquet`)

`scripts/mf_portfolios.py` (houses in `collectors/mf_portfolios/houses.py`, parser `insiders_clean/mf_holdings.py`).
Two kinds of house, kept in the same tables and told apart by `kind` (holdings) and `house_kind` (changes, per stock):

- `mf`: mutual fund houses (SEBI; AMFI's Portfolio Disclosure list), the SEBI-format workbook, value in Rs lakh.
- `pension` (from 19 Nov 2026; keys `nps_...`): NPS pension fund managers (PFRDA; NPS Trust's list at
  `npstrust.org.in/scheme-portfolio`), the PFRDA form (a sheet or file per scheme: E, C, G in Tier I and II, central
  and state government, corporate CG, NPS Lite, APY, Vatsalya ...; Particulars, ISIN No., Quantity or No of Units,
  Market Value **in rupees**, converted to lakh on reading). Collected: SBI, LIC, ICICI, Aditya Birla Sun Life, Axis.
  Not collected (19 Nov 2026, reasons in `houses.py`): UTI and Max Life (expired site certificates), HDFC (Akamai
  403 to scripted clients), Kotak (bot check), Tata (list never loads headless). PFRDA's rules keep NPS equity to large
  listed companies and the schemes largely follow the index, so a pension fund "adding" is pension money flowing in,
  not a stock pick; NPS scheme names match none of the index-fund words, so all their shares count as active.

| Table | Columns |
|---|---|
| `mf_holdings` (one row per house, month, ISIN; equity shares only) | `amc` (house key), `month`, `isin`, `name`, `shares`, `active_shares` (held outside index funds and ETFs), `value_lakh`, `schemes`, `active_schemes`, `kind` (`mf` / `pension`; an archive month written before the column existed reads as `mf`) |
| `mf_changes` (house, month, ISIN; houses present in both months) | the above plus `shares_before`, `active_before` (after any split or bonus `factor`), `change`, `active_change`, `kind` (`new` / `added` / `cut` / `exit` / `held` / `passive`), `isin_before` (an ISIN change bridged), `house_kind` (`mf` / `pension`) |
| `mf_stock_month` (month, `house_kind`, ISIN: mutual funds and pension funds never summed together) | `houses_adding`, `houses_cutting`, `houses_new`, `houses_exit`, `active_net`, `all_net`, `active_shares`, `active_before`, `price` (filed value over shares), `active_net_cr`, `houses_holding`, `month`, `house_kind`, `total_shares` (the company's shares on the month-end's basis: its last filing at or before the month-end with any split or bonus since applied; what "% of the company" divides by), `total_shares_quarter`, `total_shares_factor` |
| `mf_coverage` (quarter-end months) | `month`, `houses`, `companies`, `median_ratio`, `weighted_ratio`: mutual fund houses only, against the mutual-fund shares companies filed |
| `mf_scheme_changes` (house, scheme, month, ISIN; houses read scheme by scheme at both month-ends) | `amc`, `month`, `scheme_key` (the scheme's name without the house's name, plan and option words: one scheme across months and AMFI's list), `scheme` (as filed), `isin`, `isin_before`, `name`, `passive` (`PASSIVE` on the scheme name), `scheme_seen` (`both` / `end_only` / `start_only`: in the house's file at one month-end only), `factor`, `shares_start` (split or bonus applied), `shares_end`, `change`, `value_lakh` (end), `status` (`new` / `added` / `cut` / `exit` / `held`), `house_kind`, `change_cr` (at the `mf_stock_month` price). Summed over schemes it is `mf_changes` (checked each run, `not_adding_up` in the run report) |
| `mf_scheme_month` (month, house, scheme) | `scheme`, `passive`, `scheme_seen`, `net_cr`, `bought_cr`, `sold_cr`, `adding`, `cutting`, `new`, `exits`, `holdings`, `unvalued` |
| `mf_scheme_moves` (the site's cut) | `month`, `amc`, `house_kind`, `scheme_key`, `isin`, `shares_start`, `shares_end`, `change_cr`, `scheme_seen`: active schemes, rows that moved, last 12 months |
| `mf_scheme_coverage` (house-month) | `schemes_read` (every scheme in the file), `equity_schemes_read`, `active_equity_read` (equity, not index funds or ETFs; hybrids in), `amfi_date`, `amfi_equity` (AMFI's open-ended equity schemes for the house on its NAV report for the month-end's last working day; blank when not read or the house is not on it), `amfi_matched` (by `scheme_key`), `amfi_not_matched`, `flag` (`fewer schemes read`: under 80% of AMFI's count; `not read scheme by scheme`: archived before the scheme archive and not yet backfilled) |

Scheme archives: `archive/mf_schemes/month=YYYY-MM/{house}.parquet` (scheme x ISIN), `archive/mf_scheme_list/...` (every
scheme read), `archive/amfi_schemes/month=YYYY-MM.parquet` (AMFI's list; raw in `raw_v2/amfi/nav_history/`). House-months
archived before 19 Nov 2026 are added by `--schemes` (workflow input `schemes`): from raw where stored, else fetched again,
written only when they add up to the archived house rows.

## Industry classification (`clean/current/industry.parquet`, from 19 Nov 2026)

The official four-level classification (macro-economic sector > sector > industry > basic industry), one row per
ISIN, so pages can filter by industry. `scripts/industry.py`, parsers in `insiders_clean/industry.py`, workflow
`.github/workflows/industry.yml` (nightly 08:13 IST, about 400 symbols per exchange; Run workflow with `full`
ticked for the first run). Raw answers in `raw_v2/nse/quote_equity/`, `raw_v2/bse/comheadernew/`,
`raw_v2/bse/scrip_list/`; the latest answer per symbol in `archive/industry/{nse,bse}.parquet` (with `status`:
`ok`, `no_industry`, `not_found`, `error`, and `fetched_at`). An answer is fetched again after 30 days (`ok`) or 7
(anything else); a symbol never fetched comes first. While it runs, the fetch stores its raw answers and a
checkpoint of its answers so far, `staging/industry/{run}/{nse,bse}.parquet`, every 200 answers or 10 minutes (no
lock: raw is write-once, the key is the run's own); the next fetch skips what any checkpoint or the archive holds, and
the build merges every checkpoint into the archive (deleting checkpoints older than two days). With neither an archive
nor a checkpoint, both re-read the answers already in `raw_v2/` (19 and 20 Nov 2026: two full runs were cancelled
during their end-of-run flush and the table fell back to the VR export alone). `build_only` rebuilds without asking
an exchange.

| Source (`source`) | Where | Levels |
|---|---|---|
| `nse` | `www.nseindia.in/api/quote-equity?symbol=SYM`, key `industryInfo` (one call per symbol of `securities` with an INE ISIN). **Not answering yet**: HTTP 403 from the dev container and from GitHub's runners on both `www.nseindia.com` and `www.nseindia.in` (19 Nov 2026, the workflow's probe job); the collector keeps asking and stops NSE for the night on a refusal | `macro`, `sector`, `industry`, `basicIndustry` |
| `bse` | `api.bseindia.com/BseIndiaAPI/api/ComHeadernew/w?quotetype=EQ&scripcode=CODE&seriesid=` (the quote page header), for BSE's active equity scrips (`ListofScripData/w`, 4,849 with an INE ISIN), those NSE cannot cover first, then the rest (so every company has BSE's words while NSE refuses). Plain requests answer from GitHub's runners. Fetched 19 Nov 2026 (`tests/fixtures/industry/`) | `Sector`, `IndustryNew`, `IGroup`, `ISubGroup`: the same scheme and words as NSE's (ABB: Industrials / Capital Goods / Electrical Equipment / Heavy Electrical Equipment on both) |
| `vr_master` | The Value Research export (`reference_data/security_master_20260901.csv`), placed by NSE symbol or BSE code as in `securities`; only where neither exchange classifies the ISIN | Its own two levels, in `sector` and `industry`; `macro` and `basic_industry` empty. Its words are not the exchanges' ("Financial", not "Financial Services") |

BSE's scrip master (`ListofScripData/w` and its CSV `LitsOfScripCSVDownload/w`) answered with every industry field
empty for all 5,141 active scrips on 19 Nov 2026, so it gives the list of scrips only.

| Column | Meaning |
|---|---|
| `isin` | The company's ISIN (INE...; fund units and partly paid lines are left out). One row each |
| `nse_symbol`, `bse_code` | From `securities` where it knows the ISIN, else from the answer (or the VR export) |
| `macro`, `sector`, `industry`, `basic_industry` | The four levels as the source printed them; a level left blank is empty, never filled from another level or source |
| `source` | `nse` (wins when both exchanges classify the ISIN), `bse`, or `vr_master` |
| `as_of` | The day the answer was fetched (UTC date); for `vr_master` the export's date (2026-09-01) |

A company no source classifies has no row; `clean/reports/industry/{date}.json` counts them
(`securities_without_class`). Site: `store.industry_of(isin)` and `store.with_industry(df)` (joins the four levels
and `industry_source` by ISIN; `prefix='ind_'` beside a table that already has `sector`, such as `securities`).

## Not yet collected

BSE-only companies have no Company page (it is keyed by NSE symbol).
Results filed before 15 Oct 2026's first run in the integrated format beyond the nightly window (NSE's
`corporates-financial-results` answers only for the old format; integrated filing is collected from 15 Oct 2026,
`results` above, and can be backfilled by date range). The trading window is still dated from the meeting day.
A buyback's maximum price on the open-market route, and tender buybacks run
only on BSE: neither is in NSE's structured lists.

## Prices (derived, `prices/daily/{nse|bse}/{YYYY-MM}.parquet`)

One row per exchange, date, ISIN, symbol, series, as printed in the exchange's UDiFF bhavcopy. Never adjusted. Raw files: `raw_v2/exchange_files/{nse_udiff_cm|bse_udiff_cm}/`.

| Column | Meaning |
|---|---|
| `date`, `exchange`, `isin`, `symbol`, `series`, `name`, `instrument_id` | Identity as printed that day (symbols and ISINs can change) |
| `open`, `high`, `low`, `close`, `last`, `prev_close`, `settle` | Prices in rupees, unadjusted; `prev_close` is the exchange's own previous close |
| `volume`, `value`, `trades` | Traded quantity, traded value, number of trades |

### UDiFF columns the price layer leaves out (`prices/udiff_extra/{nse|bse}/{YYYY-MM}.parquet`, from 21 Nov 2026)

One row per line of a day's UDiFF file (`insiders_clean/prices.udiff_extra`, written by `scripts/price_backfill.py`
beside the layer; days before then from raw by `scripts/raw_reparse.py udiff_nse,udiff_bse`). Not read by any page or
clean step: a table of its own because the price layer is read whole by the nightly price steps (a synthetic month of
3,000 lines a day: 37 KB on disk with zstd against the layer's 3.1 MB, but 69 MB in memory against 27 MB).

| Column | Meaning |
|---|---|
| `date`, `exchange`, `isin`, `symbol`, `series` | The price layer's key for the line |
| `line` | The line's place in the file, from 0 (with `date` and `exchange` it identifies the row) |
| `BizDt`, `Sgmt`, `FinInstrmTp`, `XpryDt`, `FininstrmActlXpryDt`, `StrkPric`, `OptnTp`, `UndrlygPric`, `OpnIntrst`, `ChngInOpnIntrst`, `SsnId`, `NewBrdLotQty`, `Rmks`, `Rsvd1`-`Rsvd4` | As printed (text), and any column a later file adds |

### PR zip members (`archive/nse_pr/{kind}/{YYYY-MM}.parquet`, from 21 Nov 2026)

Every member of NSE's PR zip, line by line (`insiders_clean/market_cap.pr_members`): the corporate-action file
(`bc_csv`), the announcements text (`an_txt`), the mcap file (`mcap_csv`, with the `Last Trade Date` parse_mcap leaves
out) and the rest (`pd_csv`, `pr_txt`, `gl_csv`, `hl_csv`, `tt_csv`, `etf_csv`, `sme_csv`, `corpbond_csv`, ...: `kind`
is the file name without digits, with its extension). Written by `scripts/price_backfill.py` (NSE_PR); older days from
raw by `scripts/raw_reparse.py nse_pr`, or fetched again with Price backfill `extras_only` where
`scripts/storage_trim.py` had deleted the zip (it now deletes a zip only once its day is here).

| Column | Meaning |
|---|---|
| `date` | The session the zip was fetched for |
| `member`, `line` | File name in the zip and line number from 0 (the header is line 0) |
| `text` | The line exactly as filed (decoded as Latin-1, `\r` kept) |
| (header fields) | For a CSV member, each field under its header name, as text (empty on line 0); `extra_fields` a JSON list of values past the header |

## Indices (derived, `indices/daily/nse/{YYYY-MM}.parquet`)

NSE's daily index closing file (`ind_close_all_DDMMYYYY.csv`), one row per index and session. `date`, `symbol` (index
name), `open`, `high`, `low`, `close`, `volume`, `turnover_cr`; from 21 Nov 2026 also `points_change`, `change_pct`
(NSE's day change), `pe`, `pb`, `div_yield` as printed (empty where NSE prints `-`, and on months written before then
until `scripts/raw_reparse.py index_close` fills them).

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
Prices adjusted for splits, bonuses and filed demergers (a demerger at its ex-date close, owner directive 20 Nov 2026).

| Column | Meaning |
|---|---|
| `isin`, `symbol`, `name`, `exchange` | Latest identity; NSE preferred, BSE fills the gaps |
| `last_date`, `latest_close` | Last session with a print and its adjusted close |
| `high_52w`, `low_52w`, `pct_off_high` | Range over the 365 days to the last stored session; `pct_off_high` = close / high - 1 |
| `ret_90d`, `ret_180d` | Price change over 90 and 180 calendar days |
| `last_split_date`, `last_split_factor`, `n_splits` | Splits and bonuses seen in the price table |
| `adv_20d`, `adv_sessions` | Average traded value (₹) per session over the stock's last 20 sessions with a print, NSE + BSE summed per day (`slim.average_daily_value`), and how many sessions it rests on. A decision's value over it is the "× a day's trade" column (19 Nov 2026) |
| `market_cap`, `mcap_rank`, `mcap_bucket` | NSE market cap on the last stored day; bucket by rank (1-100 Large, 101-250 Mid, 251-500 Small, rest Micro), computed by us, not AMFI's list. BSE-only names have none |

## Company snapshot (derived, `artifacts/company_snapshot.parquet`)

One row per company of the study universe (Rs 100 Cr and up), rewritten after each nightly run by `scripts/precompute_slim.py`
(`insiders_clean/snapshot.py`), so a page joins one small table instead of the price summary, the shareholding table and the
insider table on every rerun. Read by `store.snapshot()`. A figure the data lacks is blank, never filled.

| Column | Meaning |
|---|---|
| `isin`, `symbol`, `company` | Identity; `company` is the security master's display name, else the price file's name |
| `price_date`, `latest_close`, `high_52w`, `low_52w`, `pct_off_high`, `ret_90d` | From the price summary (adjusted for splits and bonuses) |
| `range_pos` | Where the close sits in the 52-week range: 0 at the low, 100 at the high; blank for a flat range |
| `market_cap`, `mcap_bucket` | NSE's market cap on the last stored day and the size bucket by rank (as the price summary) |
| `promoter`, `pledge`, `mf`, `fpi`, `insurance`, `aif`, `retail` | The latest filed value of each, in % (promoter holding, pledge as % of promoter shares, and the share of the company held by mutual funds, foreign portfolio investors, insurers, AIFs, retail), from NSE's shareholding table plus BSE-only companies |
| `*_quarter` | The quarter end each value is from (a newer filing without that figure leaves the older one, and says so here) |
| `*_change_pts` | The change in points from the quarter before; blank when the two quarters are more than 120 days apart |
| `insider_buy_90d`, `insider_sell_90d`, `insider_net_90d` | Open-market buying and selling by decision-makers (promoter, promoter group, director, KMP; never designated persons) made public in the last 90 days to the data's as-of day, in rupees; token buys are not buying; zero when none |
| `promoter_buy_90d`, `promoter_sell_90d` | The promoter group's part of those |
| `last_insider_buy`, `last_insider_sell` | The latest day such a buy or sale was made public (any time, not only the last 90 days) |

## Adjustment factors (computed, not stored yet)

`insiders_clean/adjust.py` derives `factor = prev_close / previous close` per exchange and ISIN from the price table; `kind` is `split_bonus` (the only kind applied), `other_large`, `minor`, `none` or `unknown`; `kind_basis` says how a large reset was classified: `action` (a filed bonus or split in `actions` / `bse_actions`, factor within 1.5% of the filed ratio), `action_mismatch` (filed, but the factor differs: not applied), `action_not_split_bonus` (only a dividend, rights or buyback filed that day: not applied), `ratio` (nothing filed; the clean-ratio guess). Adjusted price at T uses only factors dated up to T.

### Investors page (read from `deals`; `insiders_clean/investors.py`, `fund_managers.py`)

Real deals only: primary legs (NSE and BSE legs are separate executions, both counted), market makers out. An investor is one `investor_group` (same investor, different spellings), never a fund family. Net = bought minus sold in rupees over 7, 30 or 90 days, with gross beside it; listed at Rs 25 Cr net or 0.25% of one company. Type comes from the name only; low-confidence types are left out of the default view and counted. `fund_managers.csv` (`pattern`, `manager`, `sub_advised`, `reason`; first match wins) maps a fund name to the manager the name itself names; a name with no line has no manager, and a sponsor's fund that names the manager inside is marked likely sub-advised.
