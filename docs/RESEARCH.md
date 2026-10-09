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
| 2026-10-09 | H1 | C0..C9 conditioned cuts (this section) | owner directive | section I results |
