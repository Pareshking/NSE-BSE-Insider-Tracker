# Site audit log (from 21 Oct 2026)

Plan: `docs/REVAMP_PLAN.md`. Each defect: what the page shows, what the exchange's
own source says, the cause, the fix and the test. Status: open / fixed (PR).

## Part 2: numbers checked against the source

### D1 Clusters count one promoter group as several decision-makers (wrong number, open)
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

### D2 Creeping-acquisition room uses rupees over today's market cap, not shares (wrong number, open)
- **Shown** (Company, Electrosteel): "4.23% bought on market since 01 Apr 2026", room 0.77%.
- **Source**: the same filing: 2,71,42,650 shares bought; total shares 61.81 Cr (promoter 33,70,67,952 =
  54.53%) -> 4.39%, room 0.61%.
- **Cause**: `company.py` sums `pct_of_mcap` (value / latest market cap) as if it were % of shares.
- **Fix**: shares bought / total shares in issue (or the filed post-minus-pre % of shareholding in each
  PIT XBRL), net of nothing (Reg 3(2) counts gross acquisitions). Test.

### D3 The same promoter / directors / deals net shown twice on the Company page (duplicate, open)
- Tiles "Promoter net, 12 months", "Directors & KMP net", "Deals net, 12 months" and the card "Net
  open-market flow by who" repeat the same three figures.

### D4 Empty card drawn (cosmetic, open)
- Company, Electrosteel: "Handshakes in this stock" shows only "Click a column to sort." with no rows.

### To verify
- "Filings to 19 Oct 2026" on 21 Oct: 20 Oct 2026 may be an NSE holiday (Dussehra); check NSE's list.

### Checked and right (21 Oct)
- Electrosteel: value of the cluster ₹194.95 Cr (to the rupee); market cap ₹4,612 Cr (61.81 Cr shares x
  ₹74.61); promoter holding 54.53% and pledge 9.7% of promoter shares (2 x 1,63,37,635 pledged, as filed);
  deals net −₹73.40 Cr against NSE's own bulk/block list (each trade once though NSE prints it in both
  lists); CMP vs paid +3.88% (₹71.82 average paid).
- "Filings to 19 Oct" on 21 Oct: 20 Oct 2026 was Dussehra, an NSE trading holiday (holiday-master).

### D5 Companies under ₹100 Cr lead the Screener (owner rule not live, open)
- Screener top rows on 21 Oct: Swashthik Plascon, Dangee Dums (≈₹47 Cr), NAPS Global. Fixed by the study
  universe (PR #55) once merged.

### D6 Promoters' own bulk buys counted in both "Promoter net" and "Deals net" (misleading, open)
- Electrosteel: Asha and Mayank Kejriwal and Wilcox Merchants appear in the PIT filing and in NSE's bulk
  list for the same trades; the Company tiles add them to both nets. Fix with D3: one flow card where a
  deal by a filed insider is shown once, under the insider.

### D7 Paragraph captions under tables (verbosity, open)
- Screener, Actions, Track record and others end with multi-sentence captions; to become one-line tags.

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
- Still open: BSE-only names have no dated cap (shares from the shareholding XBRL x BSE close would give one);
  D2 above (creeping room) still sums rupees, not shares.

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
