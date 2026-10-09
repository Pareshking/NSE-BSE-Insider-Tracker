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
| 2026-10-09 | H1/H2/H8 | v1 run, workflow run 37924031150 (main c5ce96b), development period 2026-01-01..2026-06-30, standard and conservative entry, vs equal-weighted market proxy and size buckets | first pre-registered run, no parameter tuning | yes, section H |

## H. Results, development sample (VERIFIED as computed; interpretation ESTIMATED)

Run 37924031150, 9 Oct 2026 (IST), events before 1 Jul 2026 only; the hold-out was not touched. Returns are **before transaction costs**. Abnormal return (AR) = stock return minus benchmark over 5/20/60 sessions from the entry point. CI = 95% date-clustered bootstrap. Full detail in the `research-results` artifact (kept 14 days). Rows below are standard entry (disclosure before 14:00 IST enters at that close, otherwise next open); conservative entry (next close) is in the artifact and gives the same conclusions.

| Test | Bench | Horizon | N | Clusters | Mean AR | Median AR | Hit rate | 95% CI | MDE |
|---|---|---|---|---|---|---|---|---|---|
| H1 insider market BUY | market | 5 | 1354 | 107 | -0.06% | -0.22% | 49.0% | -0.54%..+0.37% | 0.56% |
| | | 20 | 1343 | 108 | -0.54% | -1.05% | 45.0% | -1.21%..+0.12% | 1.07% |
| | | 60 | 1350 | 107 | +0.49% | -3.16% | 41.3% | -1.05%..+2.10% | 2.05% |
| | size | 5 | 1264 | 106 | -0.10% | -0.17% | 48.5% | -0.69%..+0.43% | 0.59% |
| | size | 20 | 1255 | 107 | -1.41% | -1.63% | 44.4% | -2.38%..-0.40% | 1.13% |
| | size | 60 | 1260 | 106 | -2.05% | -6.30% | 35.3% | -3.50%..-0.48% | 2.11% |
| H2 insider market SELL | market | 5 | 529 | 94 | -1.51% | -1.16% | 41.2% | -2.44%..-0.68% | 1.22% |
| | | 20 | 532 | 94 | -1.78% | -1.87% | 42.1% | -3.21%..-0.41% | 2.04% |
| | | 60 | 528 | 94 | -2.59% | -7.61% | 32.8% | -5.99%..+0.72% | 5.03% |
| | size | 5 | 486 | 93 | -1.68% | -1.17% | 38.3% | -2.61%..-0.80% | 1.29% |
| | size | 20 | 489 | 93 | -2.36% | -2.41% | 40.5% | -3.84%..-0.95% | 2.15% |
| | size | 60 | 485 | 93 | -2.34% | -7.66% | 35.7% | -6.09%..+1.37% | 5.36% |
| H8 deals net BUY | market | 5 | 944 | 120 | -0.56% | -1.76% | 42.6% | -1.31%..+0.27% | 1.02% |
| | | 20 | 928 | 120 | -1.18% | -2.60% | 42.1% | -2.46%..+0.15% | 1.76% |
| | | 60 | 915 | 120 | -2.08% | -7.76% | 38.5% | -4.35%..+0.28% | 3.44% |
| | size | 20 | 788 | 120 | -1.82% | -3.61% | 39.1% | -3.11%..-0.55% | 1.77% |
| | size | 60 | 785 | 120 | -4.04% | -9.91% | 33.0% | -6.45%..-1.48% | 3.75% |
| H8 deals net SELL | market | 5 | 1039 | 120 | -0.12% | -1.09% | 45.7% | -0.86%..+0.57% | 1.00% |
| | | 20 | 1024 | 120 | -1.81% | -2.83% | 42.0% | -2.91%..-0.71% | 1.75% |
| | | 60 | 1008 | 120 | -2.79% | -7.46% | 36.0% | -5.05%..-0.53% | 3.55% |
| | size | 20 | 918 | 120 | -2.12% | -3.13% | 40.7% | -3.32%..-0.92% | 1.84% |
| | size | 60 | 907 | 120 | -4.31% | -9.19% | 34.6% | -6.68%..-1.86% | 3.75% |

(H8 BUY and SELL size-matched 5-session rows: -0.80% [-1.60%, +0.04%] and -0.33% [-1.10%, +0.44%].)

Gross (not abnormal) mean returns: H1 BUY +2.9% at 20 and +10.6% at 60 sessions, median +1.4% and +7.2%; H2 SELL +0.4% at 20 and +5.4% at 60; H8 BUY +1.2% and +5.1%; H8 SELL +0.3% and +3.6%.

### Reading (ESTIMATED, not a conclusion)

- **H1 (insider market buys): no evidence of an edge.** Against the market proxy no horizon is distinguishable from zero. Against size-matched peers the 20- and 60-session mean AR is *negative* (-1.4%, -2.1%) and the median is worse (-6.3% at 60), so the typical event underperformed. The large gross 60-session return (+10.6%) is the 2026 market and micro-cap rally, not insider information.
- **H2 (insider sells): no tradeable signal for a long-only investor.** Sellers' stocks underperformed by about 1.5 to 2.4% over 5 to 20 sessions (CIs exclude zero), which is the direction the hypothesis predicted, but it is a short signal and costs and shorting constraints are not applied.
- **H8 (bulk/block net direction): both BUY and SELL net-direction events show negative AR; the buy and the sell groups look alike.** That is not a directional signal. It suggests the benchmark is the problem or that all deal-flagged names are weak (micro caps; BUY 822 of 837 and SELL 919 of 957 sized events are micro).
- **Benchmark caveat (important).** The market proxy is an equal-weighted average of all our listed names and the size benchmark is dominated by micro caps. Micro-cap return distributions are right-skewed: mean beats median by 3 to 7 points at 60 sessions. Positive means with negative medians and hit rates of 33 to 45% mean a few large winners drive averages. Results are most informative about direction vs peers, not about a tradeable strategy.
- **Power:** 5-session tests can detect about 0.6% (H1) and 1.0 to 1.3% (H2, H8); 60-session tests are weaker (2 to 5%). Clusters are about 93 to 120 disclosure dates, so every result rests on one half-year; effective independent observations are fewer than N (date-clustered CIs account for that, not for a single regime).
- **Not done:** transaction costs and slippage (micro-cap impact would make these worse), a broad index or factor benchmark, per-bucket splits, insider category and value-size cuts, volume/liquidity filters.

Decision: nothing here supports a buy/sell signal in the product. The honest current result is "no reliable edge for insider market buys vs size-matched peers in the Jan-Jun 2026 sample". Hold-out is untouched; no tuning of rules after seeing these numbers.

## I. Conditioned cuts of H1 (registered 9 Oct 2026 IST, before any cut outcome was computed)

Owner directive: test whether conditioning isolates conviction from noise in insider market buys. Development sample only (events before 1 Jul 2026), standard entry. Nine cuts, fixed here:

| Cut | Rule |
|---|---|
| C1 | any filer in the day's event is Promoter or Promoter Group |
| C2 | no promoter filer (director, KMP, designated person, other, missing) |
| C3 | combined day value >= Rs 10 lakh |
| C4 | combined day value >= Rs 50 lakh |
| C5 | combined value >= 0.05% of market cap (market cap from the clean layer; proxy for share of equity) |
| C6 | breadth: 2+ distinct insiders that day, or another buy event in the same security in the prior 30 days (the clean layer starts 1 Jan 2026, so January events have a shorter look-back) |
| C7 | close at signal more than 20% below its trailing 252-session high (needs 250 sessions of history; others excluded and counted) |
| C8 | C1 and C5 |
| C9 | C1 and C7 |

Primary metric: 20-session abnormal return vs size-matched peers. Judged with a Bonferroni-adjusted interval for the 9 cuts (99.44% date-clustered bootstrap); the usual 95% intervals and all other horizons/benchmarks are reported but are secondary. Cuts overlap, so they are not independent tests. A cut is called a robust edge only if its primary adjusted interval is above zero, N and clusters are adequate versus the MDE, and the sign holds in the conservative-entry run and against the market proxy. Otherwise: "no edge" / "insufficient evidence". The hold-out is not scored here. Median-heavy skew caveat from section H applies.

| Date | Family | Variant | Reason | Reported? |
|---|---|---|---|---|
| 2026-10-09 | H1 | C0..C9 conditioned cuts (this section), run 37925660880 | owner directive | yes, section I.1 (SUPERSEDED benchmark, see J) |
| 2026-10-09 | H1/H2 | section J: promoter cuts P1-P5 at 60/120 sessions vs Nifty 500, run 37929257064. Benchmark was changed after earlier results were weak; the advisor counts that as a post-hoc choice | owner realignment | yes, section J.1 (descriptive only) |

### I.1 Results (run 37925660880, development sample, standard entry, before costs; VERIFIED as computed)

Mean 20-session abnormal return vs size-matched peers (N / date clusters; 95% CI; adjusted 99.44% CI is the primary test):

| Cut | N / clusters | Mean AR20 | Median | Hit | 95% CI | Adjusted 99.44% CI | AR60 mean (95% CI) |
|---|---|---|---|---|---|---|---|
| C0 baseline | 1255 / 107 | -1.41% | -1.63% | 44% | -2.4..-0.4 | -2.8..-0.0 | -2.05% (-3.5..-0.5) |
| C1 promoter | 970 / 104 | -1.50% | -1.94% | 44% | -2.5..-0.4 | -2.8..+0.1 | -3.22% (-4.7..-1.7) |
| C2 non-promoter | 285 / 74 | -1.13% | -0.53% | 47% | -2.9..+0.6 | -3.6..+1.4 | +1.99% (-1.7..+6.6) |
| C3 >= Rs 10 lakh | 850 / 94 | -1.85% | -1.96% | 44% | -3.2..-0.5 | -3.8..+0.2 | -2.09% (-4.0..+0.1) |
| C4 >= Rs 50 lakh | 436 / 80 | -3.01% | -2.52% | 43% | -4.8..-1.2 | -5.4..-0.5 | -2.89% (-5.5..-0.0) |
| C5 >= 0.05% of mcap | 460 / 96 | -3.32% | -3.60% | 39% | -5.0..-1.5 | -5.7..-0.7 | -7.16% (-9.7..-4.5) |
| C6 breadth | 948 / 99 | -2.18% | -2.07% | 42% | -3.3..-1.0 | -3.9..-0.6 | -3.75% (-5.2..-2.3) |
| C7 drawdown > 20% | 800 / 98 | -0.40% | -0.47% | 48% | -1.5..+0.7 | -2.0..+1.3 | -2.33% (-4.0..-0.6) |
| C8 promoter and >= 0.05% | 397 / 94 | -3.59% | -3.48% | 39% | -5.4..-1.6 | -6.1..-0.8 | -7.99% (-10.7..-5.0) |
| C9 promoter and drawdown > 20% | 579 / 96 | -0.40% | -0.49% | 48% | -1.8..+1.1 | -2.5..+1.8 | -2.95% (-4.8..-0.8) |

Against the market proxy: C7 +0.38% (-0.5..+1.4) and C9 +0.38% (-0.7..+1.6) are the only non-negative cut means; C2 is +0.20% (-1.5..+1.8); all others are negative. 5-session size-matched ARs are within about +-1.3% for every cut (C5, C8 negative with CIs excluding zero; the rest straddle zero). MDEs at 20 sessions are 1.1 to 2.8%.

**Verdict (ESTIMATED): no conditioned subset of insider open-market buys shows an edge.** None of the nine cuts has a positive primary interval; the best cuts (drawdown, C2) are indistinguishable from zero and C2/C7/C9 are underpowered relative to realistic effects. Counter to the conviction hypothesis, the cuts that select *larger* purchases (C4, C5, C8: Rs 50 lakh+, 0.05%+ of market cap) and breadth (C6) are significantly *worse* than peers (primary adjusted intervals below zero, 60-session -7% to -8% for C5/C8). HYPOTHESIS, not tested: large purchases relative to market cap in illiquid micro caps are dominated by promoter creeping accumulation and price-support, which show up as a disclosed rise followed by mean reversion; the size-matched benchmark also remains equal-weighted micro-cap. Both need liquidity data (volume, impact) and the non-market-modes split to examine; they are not tuned here.

Not found: drawdown or promoter conviction signals. Not done: costs/impact, liquidity filter, broad index/factor benchmark, regime split (one half-year). No buy signal is generated. Hold-out remains unscored.

## J. Realignment: multi-quarter horizons, one baseline (registered 9 Oct 2026 IST, before any section J outcome was computed)

Owner directive: purchases should be judged over one to two quarters, not days, because promoters and designated persons face SEBI (PIT) contra-trade restrictions and fundamentals take quarters to show. (The regulatory description is CLAIMED, from the owner; not independently verified here.) Benchmarks are simplified to two numbers: absolute return and excess return vs **Nifty 500** closing values from NSE's index archive (`ind_close_all_*.csv`, stored raw in `raw_v2/` and parsed to `indices/daily/nse/`). The equal-weighted market proxy and size-matched benchmarks were removed from the code. Sections H and I used them and remain as the earlier record, now **superseded for decisions**. My earlier reading that micro-cap skew distorted those benchmarks is ESTIMATED, not proven; the new baseline tests it directly.

Fixed rules: development sample (disclosures 1 Jan to 30 Jun 2026), open-market purchases only, standard entry (same close if disclosed before 14:00 IST, otherwise next open), benchmark window from the entry close (previous close for open entries). 60 sessions on all complete windows; 120 sessions on January to April disclosures only, labelled PRELIMINARY — SAMPLE MATURING. 250 sessions not run (no mature sample). Reported: N, date clusters, mean, median, hit rate (absolute: share above 0; excess: share beating Nifty 500), standard deviation, date-clustered bootstrap 95% CI of the mean, MDE.

| Cut | Rule (promoter filings only, day combined) |
|---|---|
| P1 | Promoter / Promoter Group open-market buys (excludes directors, KMP, designated persons) |
| P2 | P1 with combined day value >= Rs 25 lakh |
| P3 | P1 with combined day value >= Rs 50 lakh |
| P4 | P1 with another buy event in the same security in the prior 30 days (clean layer starts 1 Jan 2026, so early January sees a short look-back) |
| P5 | P4 and >= Rs 25 lakh |
| R0 | reference: all insider open-market buys |
| H2 | insider open-market sells at 20/60/120 sessions (risk flag check on the new baseline) |

Five related cuts are not independent; the primary reading is P2 and P3 excess return at 60 sessions, and a cut is called an edge only if its excess-return CI is above zero at both 60 and 120 sessions or is clearly above zero at 60 with 120 pending. Otherwise: "no edge" or "insufficient evidence". Hold-out untouched.

### J.1 Results vs Nifty 500 (run 37929257064, development sample, before costs; VERIFIED as computed)

Excess return = stock return minus Nifty 500 return over the same window. Mean / median, N (date clusters), 95% CI of the mean. 120 sessions: **PRELIMINARY — SAMPLE MATURING IN 2026** (January to April disclosures only).

| Cut | 60s absolute | 60s excess | 60s hit vs Nifty | 120s excess [PRELIMINARY] | 120s hit vs Nifty |
|---|---|---|---|---|---|
| P1 promoter buys | +9.3% / +5.9% | +7.3% / +3.2%, N 1039 (103), CI +5.7..+8.9 | 59% | +11.8% / +2.6%, N 861 (84), CI +8.9..+14.8 | 56% |
| P2 >= Rs 25 lakh | +11.8% / +7.2% | +9.2% / +4.5%, N 488 (89), CI +7.0..+11.4 | 60% | +12.3% / +3.3%, N 396 (71), CI +8.1..+16.0 | 57% |
| P3 >= Rs 50 lakh | +11.6% / +7.0% | +8.8% / +3.0%, N 344 (80), CI +6.3..+11.6 | 58% | +10.7% / +2.2%, N 272 (62), CI +6.3..+15.3 | 54% |
| P4 repeat in 30 days | +7.5% / +5.3% | +5.4% / +2.3%, N 721 (95), CI +4.0..+6.8 | 56% | +9.8% / +2.3%, N 626 (78), CI +7.0..+12.9 | 55% |
| P5 repeat and >= Rs 25 lakh | +9.9% / +6.4% | +6.9% / +2.0%, N 301 (74), CI +4.6..+9.5 | 57% | +9.4% / +0.7%, N 256 (59), CI +5.6..+13.6 | 53% |
| R0 all insider market buys | +10.6% / +7.2% | +8.7% / +4.8%, N 1350 (107), CI +7.1..+10.2 | 61% | +14.6% / +6.7%, N 1124 (86), CI +11.6..+17.5 | 60% |
| H2 control: insider market SELLS | +5.4% / +1.0% | +4.4% / -0.2%, N 528 (94), CI +1.1..+7.7 | 50% | +6.9% / +3.8%, N 326 (68), CI +2.7..+11.1 | 57% |

Nifty 500 itself returned +1.9% (mean) over the 60-session windows and +3.8% over the 120-session windows. Standard deviations of excess return are 24 to 41%. 20-session H2: excess +0.5% (CI -1.0..+1.8). The 120-session Nifty 500 hit-rate and spread are not meaningful (windows overlap heavily in one regime).

### J.2 Opus advisor review (Opus agent following `.claude/agents/quant-advisor.md`; verbatim; model output, not a user decision)

The `/advisor` command and the registered `quant-advisor` subagent type were not available mid-session (the agent file is read only at session start), so the same persona was run as an Opus general-purpose agent. Report, verbatim:

> **Verdict: the result is not recordable as an insider edge.** Excess return vs Nifty 500 measures how micro caps did against large caps in H1 2026. It does not isolate what the insiders knew. The sells control comes out positive (+4.4% at 60 sessions, CI +1.1..+7.7; +6.9% at 120 sessions), and on its own that is enough to show segment beta or a micro-cap rally running through the whole sample (ESTIMATED). The superseded equal-weighted and size-matched runs gave about zero or negative for the same buys (−2.1% vs size-matched at 60 sessions). That points the same way. Record the numbers as descriptive returns only. The Section J rule ("CI above zero" means edge) should be treated as invalid, because its benchmark cannot separate signal from segment.
>
> **(1) Is Nifty 500 a valid test?** No, not for the inference. About 85% of events are micro caps, and Nifty 500 holds almost none of them. Under no information, the expected excess is micro-cap minus large-cap return plus any extra beta, not zero. Sells lose to the market but buys rise even more, so a buys-minus-sells gap of about +3–4 points at 60 sessions might be real. Its CI has not been computed (HYPOTHESIS). Mean far above median (+7.3% vs +3.2%) means a few big winners drive the mean, so it is fragile.
>
> **(2) Biases.**
> - Survivorship: if the price table only has ISINs still trading, delisted or suspended names are silently dropped. `evaluate.py` returns NaN for incomplete windows, so they are dropped rather than marked down. That pushes returns upward.
> - Look-ahead: rankings by market cap, any later-dated listing data, and the 14:00 cut-off timestamp source all need checking.
> - Overlapping windows: repeat buys in the same stock overlap. Clustering by date does not handle the same stock across dates, so CIs are too narrow.
> - One regime, about 100 dates, five cuts plus R0/H2, and benchmarks swapped after weak results all count as data snooping. The benchmark change was a post-hoc choice and must be logged as a variant.
>
> **(3) Minimal fix.** The UI keeps absolute and Nifty 500 excess. Research adds one control:
> - (a) Matched excess: AR_i = r_i − mean(r_j over K=5 non-event stocks in the same market-cap decile and turnover tercile, same entry date and horizon), with the ranks taken at month-end before the event.
> - (b) Buys minus sells: D = mean(AR_buys) − mean(AR_sells). Use a bootstrap clustered by date and resample both groups together.
> - (c) Optional robustness check: r_i − r_f = a + b·(Nifty500 − r_f) + s·(SmallMinusBig) + e, run on daily returns over the window. Report a.
>
> Call it an edge only if (a) and (b) both have CI > 0 at 60 sessions.
>
> **(4) Labels.**
> - May conclude: "Promoter buys in H1 2026 beat Nifty 500 on average (VERIFIED as computed); so did insider sells."
> - May not conclude: insider information, an edge, tradability (results are before costs and in illiquid names), or anything negative.
> - 120-session results: "PRELIMINARY — SAMPLE MATURING IN 2026", N≈861 from Jan–Apr only, no inference.
>
> **(5) SEBI PIT.** What I can confirm from memory (CLAIMED until checked): the PIT Regulations 2015 Schedule B (Minimum Standards for the Code of Conduct) has a contra-trade clause. Designated persons who buy or sell may not do the opposite trade for 6 months, the compliance officer can grant a waiver, and profits from a breach go to the SEBI IPEF. What I cannot confirm: whether promoters are covered unless they are designated persons, current amendments, and exemptions such as ESOP exercise.
>
> Check these in the current consolidated PIT Regulations on sebi.gov.in: Reg 9 and Schedule B, the clause on contra trades; the definition of "designated person" in Reg 9(4); the amendments from 2019 onward. Until then, keep the description labelled CLAIMED in Section J. The rule supports 1–2 quarter horizons, but it is not a reason for a Nifty 500 benchmark.
>
> **Directives for the executor:** (1) RESEARCH.md §J: add results subsection with the conclusion text below; mark the edge rule superseded and log the benchmark change in §G as a variant; append only. (2) `insiders_clean/evaluate.py`: add `matched_excess()` per (a) and `buys_minus_sells()` per (b) as research-only outputs; keep the UI on absolute and Nifty 500 excess. (3) Price table: count events whose window is cut short by delisting or suspension; report N dropped by reason and, as a sensitivity check, value the exit at the last price or −100%. (4) `scripts/research_run.py`: add a robustness cluster by ISIN alongside the date-clustered bootstrap; report how many windows overlap. (5) Hold-out untouched, no pre-2026 data, no pushes to main, PR stays a draft.
>
> **Recommended conclusion text:** "J.1 Reading (ESTIMATED). Over the development sample, promoter open-market buys beat Nifty 500 at 60 sessions (P1 +7.3% mean, +3.2% median, CI +5.7..+8.9; VERIFIED as computed, before costs). Insider sells also beat Nifty 500 (+4.4%, CI +1.1..+7.7), and about 85% of events are micro caps, so this excess mainly reflects how the segment performed in one half-year, not insider information. Earlier size-matched results were about zero or negative. Conclusion: insufficient evidence of an edge; the Nifty 500 excess is descriptive only. Next test: size- and liquidity-matched excess and buys minus sells. 120-session figures: PRELIMINARY — SAMPLE MATURING IN 2026. Possible survivorship bias (delisted names missing) not yet measured."

### J.3 Conclusion (supersedes the edge rule in section J; ESTIMATED)

Insufficient evidence of an edge. Promoter buys beat Nifty 500 (VERIFIED as computed, before costs), but insider sells beat it too, about 85% of events are micro caps, and the earlier size-matched results were about zero or negative. The Nifty 500 excess is descriptive of the micro-cap segment in one half-year, not of insider information. The "CI above zero means edge" rule written in section J is withdrawn. 120-session figures are PRELIMINARY — SAMPLE MATURING IN 2026. The 6-month contra-trade description stays CLAIMED until Reg 9 / Schedule B and the "designated person" definition are read in the current SEBI text; it supports 1 to 2 quarter horizons but is not a reason for the Nifty 500 benchmark. Earlier sections H and I (equal-weighted and size-matched benchmarks, 5 to 60 sessions) are kept as the record; their near-zero or negative abnormal returns are consistent with this reading but were not designed as the final test.

Next tests, not yet run (advisor directives 2 to 4): size- and turnover-matched excess (K=5 non-event stocks, ranks at the prior month-end), buys minus sells with a date-clustered bootstrap, delisting/suspension sensitivity, ISIN-clustered CIs and a count of overlapping windows. An edge is called only if matched excess and buys-minus-sells both have a CI above zero at 60 sessions.
