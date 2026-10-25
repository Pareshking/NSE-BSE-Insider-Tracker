# Site audit log (from 21 Oct 2026)

Plan: `docs/REVAMP_PLAN.md`. Each defect: what the page shows, what the exchange's
own source says, the cause, the fix and the test. Status: open / fixed (PR).

## Part 2: numbers checked against the source

### D1 Clusters count one promoter group as several decision-makers (wrong number, fixed 21 Oct: the filed category decides, `signals.decision_makers`, `ideas.decisions`)
- **Shown** (Actions, "Several insiders buying together", 21 Oct): Electrosteel Castings, 7 buyers,
  5 decision-makers, ₹194.95 Cr, 4.23% of market cap; first in the list.
- **Source**: NSE PIT filing appId 3856, broadcast 01 Oct 2026 16:32 (XBRL
  `IT_780_WebXMLFile_20261001_163242545.xml`): 7 market purchases on 28-29 Sep, every one filed as
  Promoter or Promoter Group (Mayank, Asha, Madhav Kejriwal; Nityangi Kejriwal Jaiswal; Priya Sakhi
  Kejriwal Mehta; Tulsi Highrise Pvt Ltd; Wilcox Merchants Pvt Ltd). Total ₹1,94,95,01,538: the value
  is right. The 30 Sep 2026 shareholding XBRL (SHP_1739556, filed 16 Oct) names all of them among its
  34 promoter-group members, whose shares add up to the promoter total.
- **Should be**: 1 decision-maker (the promoter group), so not a cluster at all.
- **Cause**: unlinked filers fall back to the surname rule (Kejriwal / Jaiswal / Mehta / two companies
  = 5). Production check: whether `promoter_group` holds the 30 Sep list for ELECTCAST and how many of
  the 7 linked.
- **Fix**: a filer whose own filing says Promoter or Promoter Group counts in the company's promoter
  group (the filing's category is the exchange's own word), the member list adds the rest (relatives
  filed under other categories). Test on this filing.

### D2 Creeping-acquisition room uses rupees over today's market cap, not shares (wrong number, fixed 21 Oct: shares over total shares)
- **Shown** (Company, Electrosteel): "4.23% bought on market since 01 Apr 2026", room 0.77%.
- **Source**: the same filing: 2,71,42,650 shares bought; total shares 61.81 Cr (promoter 33,70,67,952 =
  54.53%) -> 4.39%, room 0.61%.
- **Cause**: `company.py` sums `pct_of_mcap` (value / latest market cap) as if it were % of shares.
- **Fix**: shares bought / total shares in issue (or the filed post-minus-pre % of shareholding in each
  PIT XBRL), net of nothing (Reg 3(2) counts gross acquisitions). Test.

### D3 The same promoter / directors / deals net shown twice on the Company page (duplicate, fixed 23 Oct: one "Money in and out" card)
- Tiles "Promoter net, 12 months", "Directors & KMP net", "Deals net, 12 months" and the card "Net
  open-market flow by who" repeat the same three figures.

### D4 Empty card drawn (cosmetic, fixed 23 Oct: the card is gone)
- Company, Electrosteel: "Handshakes in this stock" shows only "Click a column to sort." with no rows.

### To verify
- "Filings to 19 Oct 2026" on 21 Oct: 20 Oct 2026 may be an NSE holiday (Dussehra); check NSE's list.

### Checked and right (21 Oct)
- Electrosteel: value of the cluster ₹194.95 Cr (to the rupee); market cap ₹4,612 Cr (61.81 Cr shares x
  ₹74.61); promoter holding 54.53% and pledge 9.7% of promoter shares (2 x 1,63,37,635 pledged, as filed);
  deals net −₹73.40 Cr against NSE's own bulk/block list (each trade once though NSE prints it in both
  lists); CMP vs paid +3.88% (₹71.82 average paid).
- "Filings to 19 Oct" on 21 Oct: 20 Oct 2026 was Dussehra, an NSE trading holiday (holiday-master).

### D5 Companies under ₹100 Cr lead the Screener (owner rule not live, fixed: study universe live; Screener retired into Today)
- Screener top rows on 21 Oct: Swashthik Plascon, Dangee Dums (≈₹47 Cr), NAPS Global. Fixed by the study
  universe (PR #55) once merged.

### D6 Promoters' own bulk buys counted in both "Promoter net" and "Deals net" (misleading, fixed 23 Oct: a deal that is a filed insider's own trade counts once, under the insider)
- Electrosteel: Asha and Mayank Kejriwal and Wilcox Merchants appear in the PIT filing and in NSE's bulk
  list for the same trades; the Company tiles add them to both nets. Fix with D3: one flow card where a
  deal by a filed insider is shown once, under the insider.

### D7 Paragraph captions under tables (verbosity, fixed on Today and Evidence; Company in progress)
- Screener, Actions, Track record and others end with multi-sentence captions; to become one-line tags.

## Part 4: Today on real data (PR #184, 21 Oct), checked against the exchanges' own files

### D8 Lenders' trustees shown as "Big investor in" (wrong signal, fixed #184)
- **Shown**: Horizon Industrial Parks (Deutsche Bank AG, Singapore Branch, 75.40%), five Vedanta companies (GLAS Agency
  (Hong Kong) as trustee and security agent for the tap bonds, 56.38% / 54.72%), Orient Green Power (Catalyst Trusteeship
  as debenture trustee, 22.67%).
- **Source**: NSE SAST Reg 29, 90 days to 21 Oct (1,441 filings): mode "Others"; 72 of 159 non-promoter "Others" filings
  are trustees, agents or bank branches holding shares as security (and their release).
- **Fix**: `ideas.SECURITY_HOLDER` leaves them out of big investors; a filing seen on both exchanges counted once. Test.

### D9 Aequs pledge summed across a release and a re-pledge (wrong number, fixed #184)
- **Shown**: "Promoters pledged 59.95% of the company (6 filings)".
- **Source**: NSE PIT XBRL appIds 3471, 3969, 3985: Melligeri Private Family Foundation pledged 10,05,13,070 shares on 21 Sep,
  released the same 10,05,13,070 on 08 Oct, pledged them again on 14 Oct.
- **Fix**: PIT pledges netted per company (created minus released). Test on these three filings.

### D10 Akme Fintrade warrants shown as Rs 9,10,200 Cr (wrong number, fixed #184, live after Clean only 21 Oct)
- **Cause**: preferential and rights amounts checked only on the approved amount, under Rs 10 lakh crore; the documented
  ceiling is Rs 1 lakh crore and QIPs were also checked against shares x price.
- **Fix**: both amounts checked, the raised one against shares x offer price (2x), under Rs 1 lakh crore. Test.

### D11 Evidence: company names blank, flags drawn letter by letter (wrong display, fixed #186)
- Names were read from a `company` column the securities list does not have (`display_name`); "ESM I, T2T, 5% band"
  arrived as one string. Forward record now cut to the Rs 100 Cr universe (24 rows counted, not shown).

### Checked and right (21 Oct, real data)
- Thyrocare "Pledge released": Docon Technologies released 1,75,00,000 and 7,94,69,696 pledged shares (PIT appIds 2183,
  2325, Aug 2026), all 9,69,69,696 promoter shares.
- Race Eco Chain "Pledge rising": the 30 Sep 2026 shareholding XBRL (filed 07 Oct) shows 50,20,000 + 27,10,100 promoter
  shares pledged, 100% of the category; none in June.
- Paramount Syntex "Funds selling": BSE bulk deals of 09 Oct 2026 at Rs 115: Minerva Ventures, Rigel Global, Sunrise
  Investment Opportunities, MGO High Conviction, Al Maha Onyx and two 31 Degrees North funds sold 25,60,000 shares
  (Rs 29.44 Cr), as shown.
- Thyrocare "Big investor in": HSBC Mutual Fund bought 1.88% to 6.63% (SAST Reg 29(1)).

## Part 5: strict investor audit of the live site (22 Oct), checked against NSE's and BSE's own files

Clean rows read with `scripts/clean_peek.py` (workflow *Clean peek*, read-only).

### D12 Retired ISINs hid companies' shareholding (wrong number, fixed #190; 2,820 rows re-keyed 08:19 IST)
- **Shown**: Electrosteel, Kapston, T T, HCL Tech and others with no promoter holding, no pledge, no ownership table; their
  % of the company on value over market cap (Electrosteel 4.21% for 4.39%).
- **Source**: NSE's shareholding list files Electrosteel under INE086A01011 (the ISIN before its split; now INE086A01029),
  HCL Tech under "IN9860A01017"; the site cuts every table to the universe by ISIN, so those rows were dropped.
- **Fix**: `add_identity`: a filed ISIN the security master does not know gives way to the symbol's current one
  (`isin_filed` kept, `isin_replaced` counted: 2,820 in the first run).

### D13 Pledges counted up to three times (wrong number, fixed #190; live after Clean only)
- **Shown**: Aequs "pledged a net 29.97% of the company"; the 30 Sep 2026 XBRL: 10,05,13,070 of 67,06,65,635 = 14.99%.
- **Cause**: NSE's nightly mapper kept no quantity for a pledge (only buys and sales), so NSE rows never paired with their
  BSE copies; BSE's CSV and nightly feeds disagreed on a pledge's side (ACQUISITION vs none), so its two copies stayed.
- **Fix**: a pledge has no side; an NSE pledge takes its shares from its BSE copy before pairing; NSE's mapper keeps them
  (`otherQuantity`, out of the row id); nobody nets more pledged than they hold. Tests on the Aequs rows.

### D14 SAST stakes in warrants or voting rights called "bought" (misleading, fixed #190)
- Craft Emerging's 5.79% of Jindal Supreme is "Voting Rights other than by shares"; the filed `acqType` is now the clean
  column `instrument` (from raw for stored rows: 424 equity shares, 4 others, 3 warrants, 1 voting rights).

### D15 Funds' net % on value over market cap (inconsistent, fixed #190)
- Every other kind is shares over total shares; RHI Magnesita's funds: 10.09% shown, 2,19,41,224 / 20,65,00,000 = 10.62%.

### D16 Results labelled "Year to" and always "consolidated" (wrong label, fixed #190, #191)
- HCL Tech's two 30 Sep filings: NSE's `consolidated` is text, so both read as consolidated; the figures were six months.
  The timeline now shows the quarter (the year to date in its facts); the store loads the quarter columns.

### D17 Links reloaded the app; no company had an address (wrong behaviour, fixed #193)
- A link inside the app's frame on streamlit.app loaded the whole site again inside the frame: a new session, the address
  bar unchanged. `ui/nav.py` switches page in the session; the address changes and back works.

### D18 Phone tables: one column visible, rows opened by a small arrow, all detail rows drawn up front (fixed #193)
- Filings drew 200 hidden detail rows (about 10,000 elements, 375 KB) on every visit; on a phone only the company column
  showed. Rows are cards on a phone, a tap opens them, facts are drawn on the first open.

### Checked and right (22 Oct)
- Bliss GVS pledge 0% to 95.8%: Anupam Rasayan, the new promoter (47.95%), pledged 5,09,84,595 of 5,32,36,264 shares.
- RattanIndia Power 43.1%: 1,02,03,20,114 of 2,36,61,03,603 promoter shares pledged (30 Sep XBRL).
- AXISCADES and RHI Magnesita fund buying: the promoter's (Jupiter Capital) and Dalmia Bharat Refractories' block sales
  went to the funds named, on 29 and 22 Sep, at Rs 1,824 and Rs 360.

## Part 3: data layer (`docs/audit/data_layer.md`), batch 2

Each item: before and after on the test fixture (`tests/test_audit_data_layer.py`), the rule, the test.

### DL-W1 % of market cap used today's market cap for every row (wrong number, fixed, batch 2)
- Before: two Rs 1 Cr ZEEL buys on 01 and 07 Sep, NSE market cap Rs 10,000 Cr and Rs 20,000 Cr those days:
  both shown at 0.0145% (value / the latest cap, Rs 6,900 Cr in the fixture).
- After: 0.0100% and 0.0050% (value / that day's cap; 07 Sep takes Friday 04 Sep's). `market_cap_at_trade`,
  `market_cap_date`, `market_cap_basis` added on insider trades and deals; `market_cap` stays the latest. A
  trade after the layer's last day keeps the latest, labelled `latest`.
- Tests: `test_pct_of_mcap_uses_the_trade_dates_market_cap`, `test_deal_pct_of_mcap_on_the_deal_day`,
  `test_clean_step_reads_the_daily_market_cap_layer`.
- BSE-only names: fixed 23 Oct (`shares_x_close`, see `docs/CLEAN_LAYER.md`); D2 above (creeping room) still sums rupees, not shares.

### DL-W3 NSE/BSE copy link demoted a distinct trade (wrong number, fixed, batch 2)
- Before: NSE buy 50,000 and NSE sale 50,000 on 02 Sep, each also on BSE: the NSE sale became a copy; Rs 7.55 Cr
  of promoter selling left every signal.
- After: both NSE rows primary, each BSE row linked to the NSE row of its own side and kind.
- Tests: `test_buy_and_sale_of_one_size_on_one_day_are_two_trades`, `test_a_pledge_and_a_buy_of_one_size_both_stay`.

### DL-W4 Multi-day NSE filing and its BSE nightly copy counted twice (wrong number, fixed, batch 2)
- Before: NSE 01-03 Sep buy of Rs 7.5 Cr and BSE's nightly row (one date, 01 Sep): both primary, Rs 15 Cr.
- After: linked on the span, Rs 7.5 Cr, `listed_on` = `bse,nse`.
- Tests: `test_multi_day_nse_filing_links_to_the_bse_nightly_copy`, `test_bse_nightly_row_outside_the_span_is_its_own_trade`.

### DL-W5 An individual folded into his HUF (wrong number, fixed, batch 2)
- Before: "Ramesh Kumar Agarwal" and "Ramesh Kumar Agarwal HUF" both `ramesh-kumar-agarwal-huf`.
- After: two IDs; names cut mid-word ("Vama Sundari Investments (Delh") still merge.
- Tests: `test_person_and_his_huf_stay_two_people`, `test_cut_names_still_merge`, `test_whole_name_and_his_company_stay_apart`.

### DL-W7 Bonus 1:6, 1:10, 3:10, 7:10, 11:10 not adjusted; a special dividend adjusted as a bonus (wrong number, fixed, batch 2)
- Before: a 1:10 bonus (factor 0.909) was `other_large`, prices unadjusted (a false 9% drop); a 20% special
  dividend (0.8) was adjusted as a 1:4 bonus.
- After: the ratio guess covers bonus n:h for h of 6 or 10; a filed action decides where there is one (a 1:20
  bonus under the 5% line is applied; a dividend-only date is never a bonus; a factor off the filed ratio is not
  applied). `kind_basis` says which.
- Tests: `test_bonus_ratios_with_six_and_ten_held_are_adjusted`, `test_special_dividend_with_a_filed_dividend_is_not_a_bonus`,
  `test_filed_bonus_classifies_even_under_five_percent_and_checks_the_ratio`, `test_expected_factors_from_bonus_and_split`.

### DL-W8 Deals: a BSE leg demoted as a copy of an NSE leg (wrong number, fixed, batch 2)
- Before: one client buys 1,00,000 on NSE at 100.0 and 1,00,000 on BSE at 100.4: BSE leg not primary, net Rs 1.00 Cr.
- After: both primary, net Rs 2.004 Cr; marked `same_size_on_other_exchange`. Rule and sources in
  `docs/CLEAN_LAYER.md` (each exchange publishes deals executed on its own platform).
- Test: `test_same_client_same_size_on_both_exchanges_counts_twice`.

### DL-W10 Revision without prevAppId kept beside its original (wrong number, fixed, batch 2)
- Before: original 10,000 sh / Rs 1.0 Cr, then a 'Revision' 12,000 sh / Rs 1.2 Cr without prevAppId, plus the
  BSE copy of the original: Rs 2.2 Cr counted.
- After: one row, the revision (Rs 1.2 Cr); removed `superseded_by_revision_marker` 1 and
  `bse_copy_of_replaced_filing` 1. Two candidate originals: nothing removed, counted `ambiguous`.
- Tests: `test_revision_marker_replaces_the_original_and_its_bse_copy`,
  `test_revision_marker_with_two_candidates_removes_nothing`, `test_original_typed_as_original_is_never_replaced_by_content`.
