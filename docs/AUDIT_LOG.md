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
