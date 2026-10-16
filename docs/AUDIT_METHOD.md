# Card audit method (supervised batches)

Written 16 Oct 2026 after the owner's findings on LTM, Paushak and Skipper: the audit must judge **importance**, not only
correctness. A card whose every sentence is true can still fail (a dividend leading a results filing; "reviewed by the
auditors" shown while profit is held; "rating kept" when the news is a bigger limit).

## Cycle
Run a batch of 100 (max=100, minutes=80, history=false, chain=false, batch=false, prompt_variant=v2, dry_run=false) ->
`card-audit.yml` (hours=N) prints every card with the filing text -> **every** new card is checked by independent
reviewers (5 chunks, opus) -> findings grouped by root cause and **verified against code or text** (reviewer claims can
be wrong) -> deterministic rule + test, or a line in `scripts/card_holds.txt` for stored cards -> PR, merge -> next batch.
Report card by card in IST. Aim: at least 1,000 audited cards, and clean or close to it before schedule/chain/history go on.

## What a reviewer must answer for every card
1. **The news.** What is the single most important fact of this filing for someone following the company? Is it in the
   headline? Results: revenue, profit, growth. Rating: the action, the rating, and any change in the size of the
   facilities. Fund raise: instrument, size, price, who. Order: value, customer, period. Management: who, role, when.
   A card that leads with a side matter (dividend, appointment, boilerplate) is a PROBLEM even if true.
2. **Shown vs held.** Is the main information held back while boilerplate is shown? List each held item whose quote **is**
   in the text (wrongly held, with the quote and what blocked it).
3. **Boilerplate shown as news** (auditor review, one reportable segment, regrouping, routine compliance).
4. Correctness: category, headline figures and units, acting party, conditions kept (up to, subject to, not less than),
   withdrawn/corrigendum stated, promoter vs non-promoter, face value vs price, projected vs actual, deal size vs
   capital/turnover/net worth, metric label = its quote's row, period (fiscal year = year it ends), standalone vs
   consolidated, duplicate label+period.
5. Missing: anything important in the filing that the card lacks.
Verdict per card: OK / PROBLEM(minor) / PROBLEM(wrong or missing news). Say "cannot verify" when the text is cut.

## Findings turned into rules (16 Oct)
Results headline must be about the results; routine results statements are not points; a rating headline must carry
"enhanced from / reduced from"; unit read from the nearest heading even in text with few line breaks; scan misreads
("3Qth") do not hold a long quote; short table rows match on whole tokens; unreadable text is not read.
