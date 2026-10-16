# Card audit and the engineering loop

Owner, 16 Oct 2026 (18:50 IST): stop the batch runs, correct the framework first, audit as an investor, line by line
against the source files, 100 *different* announcements; right signal, right content, right context on the card, and what
is saved to company memory. Strict engineering loops. Cards that are true sentence by sentence but lead with a side
matter (a dividend on a results filing, "rating kept" when the limit rose, "reviewed by the auditors" with profit held)
fail the investor.

## The loop (no live batch until the golden set is clean)
A. **Corpus.** `scripts/golden_set.txt`: 100 different cards, stratified by category (results 14, orders 7, fund raises 7,
   acquisitions 7, management 7, ratings 6, debt 5, legal 6, ...), with the owner's problem cards in it (LTM, Paushak,
   Skipper, Jindal Saw, Nirlon, Lenskart, Swiggy, ASI, Affle, CCL, J.A. Finance, Crompton, Regency, Bharat Forge, Urban
   Company, Federal Bank). Fixed, so every change is judged on the same cards.
B. **Investor audit.** `card-audit.yml` with `ids_file=scripts/golden_set.txt excerpt=40000` prints each card next to the
   filing's whole text. Ten reviewers (opus), ten cards each, every card line by line against the source.
C. **Root causes.** Findings grouped; each claim verified in the code or text first (reviewers can be wrong or see cut text).
D. **Fix the framework**: deterministic checks, prompt, context engine, memory; each with a test; the audited card becomes a
   regression fixture where it can.
E. **Replay.** `announcement-reader.yml` with `dry_run=true replay=scripts/golden_set.txt` reads exactly those filings
   again with the new rules and saves nothing. Compare old and new card for card.
F. **Repeat** B to E until the set is clean (no PROBLEM of the kinds below). Only then a fresh unseen 100, then live
   supervised batches, then the schedule.

## What an investor reviewer must answer for every card
1. **Signal.** What is the one fact in this filing that moves the picture of the company? Is it the headline, with its
   size and direction? (Results: revenue and profit with QoQ and YoY, and the dividend or appointment only after.
   Rating: action, rating, any change in the size of the facilities. Fund raise: instrument, size, price, who, approvals.
   Order: value, customer, period, share of the order book if known. Management: who, role, from when, why.
   Dividend: per share, record date, payout against profit if known. Litigation: amount, stage, who wins what.)
   A card that leads with something else is a PROBLEM even if every word is true.
2. **Content.** Every figure, unit, period, party and condition against the source (up to, subject to, not less than,
   withdrawn, corrigendum); standalone vs consolidated; promoter vs non-promoter; face value vs price; projected vs actual;
   deal size vs capital/turnover/net worth.
3. **Shown vs held.** Is the important information held while boilerplate is shown? List each held item whose quote *is*
   in the text and what blocked it.
4. **Boilerplate** shown as news (auditor review, one reportable segment, regrouping, routine compliance).
5. **Context.** What would an investor need next to this card to judge it (size against market cap, order against revenue,
   change against the last period, an earlier related event of the same company)? Is that on the card, correct, and dated?
   Say what is missing; do not invent it.
6. **Memory.** What this card writes to company memory (`archive/company_memory/<ISIN>.json`: only the shown headline,
   points, fields, metrics, with the filing link). Anything wrong, trivial, or missing that a later filing will need
   (an open loop: approval pending, allotment to follow, order to be executed, guidance given)?
Verdict per card: **OK / MINOR (wording, small omission) / MAJOR (wrong figure, wrong party, wrong or missing signal,
important item held)**. "Cannot verify" when the text is cut; never guess.

## Findings turned into rules so far
Results headline is about the results; routine results statements are not points; a rating headline carries "enhanced
from / reduced from"; unit read from the nearest heading; scan misreads ("3Qth") do not hold a long quote; short table rows
match on whole tokens; unreadable text is not read; a headline with a deal amount does not use another figure; QoQ, YoY
and six-month changes from the results table's own columns (September quarter first).
