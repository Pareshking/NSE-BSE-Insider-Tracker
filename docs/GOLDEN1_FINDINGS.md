# Golden set 1: investor audit of 100 cards (16 Oct 2026, 21:50 IST)

100 different announcement cards (`scripts/golden_set.txt`), ten opus reviewers, each card line by line against the
whole filing text, judged as an investor (`docs/AUDIT_METHOD.md`). **3 OK, 48 MINOR, 49 MAJOR.** Not ready for live batches.

## Root causes, by cards affected
| # | Root cause | Cards (about) | Fix step | Status |
|---|---|---|---|---|
| A | Checks hold correct content and leave no headline: a claim may cite one quote only; lakh/crore/Indian grouping, FY forms, ordinals, ISO dates, period tokens (Q2, 9M) read as numbers; table cells, wrapped lines and scan noise break quote matching; the unit in a table heading is missed; legal-name and symbol rules hold the whole headline | 40 | 1, 2, 3 | 1 done (period labels stripped, checked deal/metric numbers back a headline, name rewritten); 2, 3 open |
| B | Wrong signal: no QoQ/YoY on results; side matter first; company named as actor (rating agency, acquirer, person); annual tariff shown as project value; yearly amount as deal | 30 | 3, 4, 7 | QoQ/YoY and importance checks done (live-14); actor and tariff rules open |
| C | Wrong category: pledge as routine; Reg 29 as divestment/agreement/open offer; call recording or newspaper copy as results; ESG score as rating upgrade; intra-group infusion as acquisition; capital reduction as merger | 20 | 4 | stake_change, pledge, routine-by-subject and ESG done; others open |
| D | Context and open loops not captured or stored (approval pending, allotment to follow, hearing dates, commissioning dates, closing conditions, guidance, earlier related event) | 40 | 5, 7 | open |
| E | Boilerplate shown as points; repeated points; template placeholders reaching cards | 15 | 3 | results boilerplate done; repeat filter open |
| F | Enclosure not read but card written (cover letter of GFL, String Metaverse, Texmo, Avishkar, Tips Music) | 6 | 6 | open |
| G | Units: "units" for MW/MMBTU/MT/kg/employees; doubled units; currency missing or mixed (USD/INR) | 10 | 2 | open |
| H | "Not disclosed" never stated when the category expects a size | 8 | 7 | open |

## Fix plan (strict loop: sample test, code and tests, replay the 100, compare)
1. Multi-quote claims and normalised numbers. 2. Unit and header lookup; table-, wrap- and OCR-aware quote matching.
3. Never a blank headline (rebuild from XBRL / table / fields; placeholders never shown; repeat filter).
4. Category and actor rules. 5. Open-loop extractor into company memory, linking earlier events.
6. Enclosure-not-read marker. 7. Context slots per category (results columns QoQ/YoY, SAST before/after, debt terms,
litigation stage, "not disclosed").

Reviewer reports are in the session scratchpad (`golden/g/chunks`, agents' hand-backs); each claim is verified in code or
text before a rule is written. Some claims were wrong earlier (pipes), so none is applied unchecked.
