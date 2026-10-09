# Research register and pre-registration (opened 09 Oct 2026)

Phase 2 per `docs/MISSION.md` s7 and s11. Nothing here has been run on outcome data yet. Labels: VERIFIED / ESTIMATED / CLAIMED / HYPOTHESIS. "Insufficient evidence" is a valid result.

## A. Literature register (to be verified before any is relied on)

Status of every row: CLAIMED (named in the mission brief; existence and content not yet checked by me). I will not quote findings until each is opened and checked against its source. Indian evidence is searched first.

| Anchor | Topic | Verified? | Use here |
|---|---|---|---|
| Seyhun (1986) | Insider trading information content (US) | no | motivates H1/H2 only as a prior |
| Lakonishok & Lee (2001) | Insider trading and market returns (US) | no | size and purchase/sale asymmetry prior |
| Jeng, Metrick & Zeckhauser (2003) | Insider purchase profits (US) | no | prior for H1 |
| Cohen, Malloy & Pomorski (2012) | Routine vs opportunistic trades | no | H6 |
| Alldredge & Blank (2019) | Clustering of insider trades | no | H3 |
| Brown & Warner (1985); MacKinlay (1997); Kolari & Pynnonen (2010); Barber & Lyon (1997); Mitchell & Stafford (2000) | Event-study and calendar-time methods | no | method section C |
| Harvey, Liu & Zhu (2016); Bailey & Lopez de Prado (2014) | Multiple testing, deflated Sharpe | no | method section D |
| IIM Ahmedabad Indian Fama-French-Momentum factors | Factor adjustment | availability not checked | benchmark option |

Next literature step: search SSRN, SEBI/NSE research, IIM/ISB papers for Indian insider and bulk/block evidence; record question, source/URL/DOI, market and sample, method, findings (including contradictions), applicability to India, validation needed.

## B. Data available and power (VERIFIED/ESTIMATED from `docs/AUDIT.md` and this week's runs)

- 2026 product window only (owner decision; pre-2026 research data NOT permitted). Open-market insider buys in 2026 are a few hundred to low thousands of events across ~1,000 company-months (see `docs/AUDIT.md` addendum for the exact counts).
- ESTIMATED minimum detectable effect, 5% two-sided, 80% power, company-months as effective n: about 1-2% at 5-20 sessions, about 4-5% at 60-120 sessions; no complete 250-session windows exist before Dec 2026. Plausible published effects in other markets are of this order, so several tests will be under-powered. They will be reported as "insufficient evidence", not "works" or "fails".
- Option for the owner (only if the above proves too thin): approve pre-2026 disclosures for offline research only (mission 6.3). I will recommend it with numbers once the evaluation framework has produced real power figures; I will not use such data without approval.

## C. Evaluation design (fixed before running)

- Signal time = exchange dissemination timestamp (IST). Entry = same-day close if disclosure is well before the close, else next session's open; next-session close is the conservative variant. Never the transaction date or the insider's price.
- Prices: UDiFF bhavcopy, unadjusted, with adjustment factors implied by `prev_close` (`insiders_clean/adjust.py`), using only factors dated up to the signal time. Structural events (splits, bonuses, consolidations, rights-driven base changes) are adjusted; ordinary cash dividends are NOT, so returns are price returns; a dividend-inclusive series is a stated variant, not the default.
- Horizons: 5, 20, 60, 120, 250 sessions; only complete windows; N shown beside every statistic.
- Benchmarks, all reported: broad market (Nifty 500 or wider), size-matched, sector; factor-adjusted if factor data is available. No cherry-picking.
- Inference: event-clustering by date and by company, overlapping windows handled (calendar-time portfolios as robustness), confidence intervals, medians, dispersion, hit rates, drawdowns.
- Costs: verified statutory charges plus liquidity-dependent spread/impact; gross and net both reported; entries that were not tradable (circuit, T2T, suspended, SME lot) flagged.
- Survivorship: delisted/suspended securities kept (the price tables are built from daily files, so removed names stay).
- Time split: development = events dated 2026-01-01 to 2026-06-30; **hold-out = 2026-07-01 onward, untouched until the final evaluation** (forward events after this register opens go to the forward ledger, section F).

## D. Multiple testing and variant log

- Every hypothesis below is a family; the number of variants tried is logged in section G and test statistics are adjusted (Holm within family; deflated Sharpe where a strategy return series exists). A variant not in section G does not get reported as a finding.
- Thresholds (size cut-offs, windows) are set on the development period only and frozen before the hold-out is read.

## E. Pre-registered hypotheses (all HYPOTHESIS until tested)

Population for each: 2026 clean insider and deal events with a usable entry price. Open-market means mode Market Purchase/Sale as classified by the clean layer; promoter-group entities acting as one decision-maker are collapsed.

| ID | Hypothesis | Test | Primary horizon | Primary benchmark |
|---|---|---|---|---|
| H1 | Open-market insider/promoter purchases are followed by positive abnormal returns | mean and median abnormal return vs 0 | 60 | size-matched |
| H2 | Open-market sales show no or weaker abnormal returns than purchases (asymmetry) | difference H1 purchases vs sales | 60 | size-matched |
| H3 | Breadth matters: purchases by 2+ independent insiders within 30 days beat single-insider purchases | difference | 60 | size-matched |
| H4 | Relative size matters: purchases above the median of value / market cap beat the rest (market cap point in time, NSE names only; BSE-only excluded and counted) | difference | 60 | size-matched |
| H5 | Context: purchases near the 52-week low beat those near the high | difference | 60 | size-matched |
| H6 | Routine vs opportunistic (Cohen et al. definition, subject to verification) differ | difference | 60 | size-matched |
| H7 | Non-market acquisitions (ESOP, preferential, warrants, gifts, inter-se) carry no abnormal return | mean vs 0 per type | 60 | size-matched |
| H8 | Bulk/block deals: net buyer direction after same-day netting predicts drift; large block sales show supply overhang | mean by direction | 5 and 20 | broad market |
| H9 | Disclosure lag: price moves before dissemination are large for late filings | pre-signal return by lag bucket | -5..0 | broad market |

Not testable yet (need data not yet built): pledges, 75%-ceiling / creeping headroom, post-results trading-window timing, buyback participation. They stay in `docs/TODO.md`.

## F. Forward-test ledger

Append-only (mission 11.4). Each generated signal: timestamp, rule version, input snapshot reference, reference entry price, outcome filled later. A rule change starts a new series. Storage: `ledger/` in R2, written by a dedicated job; entries never edited. Not built yet.

## G. Variant log (append only)

| Date | Family | Variant | Reason | Reported? |
|---|---|---|---|---|
| (none run) | | | | |
