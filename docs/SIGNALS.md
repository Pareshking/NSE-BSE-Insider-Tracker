# Signals: decisions and thresholds

Decided 07 Oct 2026, from the calibration run on real NSE data (13,749 insider
filings May 2025 - Apr 2026; 10,982 bulk/block rows 09 Jul - 07 Oct 2026; see
docs/CLEAN_LAYER.md for the cleaning). Market cap in that run was the
06 Oct 2026 figure, so "% of market cap" for older trades is approximate; the
thresholds are to be re-checked once the signal lab joins prices at trade date.

Only primary rows count: `is_market`, `is_primary`, not `needs_review`.

| Signal | Definition | Why this number |
|---|---|---|
| Spotlight buy | One person's open-market buys in a company summed over a rolling 30 days >= 0.15% of market cap | Single promoter buys: median 0.017% of market cap, top 10% from 0.155% (about 320 a year). Promoters split purchases: median 2 trades per person-year, top 10% 10+ |
| Float absorber | One person's open-market buys summed over 90 days >= 0.5% of market cap | Per person-year sum: median 0.07%, top 10% from 0.95%. A single filing that large is only the top ~3% |
| Token buy | Promoter buy < Rs.25 lakh in a company > Rs.5,000 Cr market cap: labelled "Token", never ranked | 89 of 496 promoter buys in companies above Rs.5,000 Cr |
| Cluster | 2+ distinct **decision-makers** buying within 30 days. Each director or KMP is one; a company's promoter group is one however many of its members buy (12 Oct 2026, below); promoter filers not linked to the group are one per family by surname, as before | 62 companies a year had 3+ distinct buyers, but only 12 included a director/KMP; the rest were one promoter family buying together |
| Market makers | Bulk/block clients with 40+ legs in a quarter and buys/sells within 20%: labelled, kept out of signals | 32 clients made 60% of deal legs (09 Jul - 07 Oct 2026) |
| Price context | Distance from 52-week high and from 200-day average, shown as neutral numbers ("-14% from 52W high") | Whether buying near highs or after falls works better is contested; the signal lab measures both before either becomes a rule |
| Scoring | No star score. Factor badges only (size, cluster, pledge, price distance) | Weights would be arbitrary until measured |

Display: 14px card radius, as on paresh.streamlit.app.

## One decision-maker per promoter group (12 Oct 2026, TODO item 21)

A company's promoter group often files as many people and companies (Asian
Paints names 117 members across the Vakil, Choksi and Dani families; Reliance
50). They act as one, so in clusters and breadth they count once.

| Rule | Value |
|---|---|
| Who is in the group | The members named in Table II of the company's latest shareholding pattern (`clean/current/promoter_group.parquet`) |
| Link | Identity only: the filer's `entity_key` equals a member's, or the name before a bracket does (HUF karta, trustees, former name). Never by similarity; unlinked filings stay as they were (`docs/CLEAN_LAYER.md`, "Promoter-group link") |
| Who counts as one | All linked members of one company's group; promoter-role filers sharing a surname (the 07 Oct rule, kept for filers not in the list); a linked member and an unlinked promoter with the same surname join. A director or KMP named in the list joins the group |
| Never easier | Links only merge, so a cluster under this rule is always one under the 07 Oct rule |
| Shown | Actions, "Several insiders buying together": under the company, e.g. "4 buyers, 2 decision-makers: promoter group (3), director", and a Deciders column; Latest session's cluster tile. Screener "Who bought": "· 2 decision-makers" when fewer than the people. `company_board` carries `decision_makers` next to `insiders` |
| Caveat | The latest list is applied to every filing of the year. Membership rarely changes, but a list published after a filing is later information; a company whose promoters changed (CRESTO, 2026) simply stays unlinked for the older filings |

On the 50-company sample (Jan-Mar 2026 filings, Jun 2026 lists): 20 companies
had two or more open-market buyers among promoters, directors and KMP over the
quarter; 17 had two or more decision-makers under the 07 Oct surname rule, 8
under this one (Gem Aromatics, Hindustan Construction, Orient Bell, Premier
Polyfilm and others: one group buying under different surnames or company
names). The Track record's cluster events change accordingly from the first
precompute after the lists are collected; `insiders_clean/track.py`
`RULES_VERSION` bumped to `2026-10-12.3`.

Data not yet collected that the blueprint needs: free float %, promoter
holding %, promoter pledge % (NSE shareholding pattern, quarterly).

## Price presets on the Screener (exploratory, 09 Oct 2026)

Price context from our own NSE/BSE bhavcopy layer (split and bonus adjusted).
Shown as facts, not ranked as signals, until the signal lab measures them.

| Preset | Rule |
|---|---|
| Breakout buyers | Promoter net open-market buying over 90 days, latest close within 5% of its 52-week high |
| Turnaround accumulation | Promoter net open-market buying over 90 days, latest close 30% or more below its 52-week high |

## Track record (measured nightly, 09 Oct 2026)

`insiders_clean/track.py`, run by the precompute job; the site only reads
`artifacts/track_summary.parquet` and `artifacts/track_events.parquet`.

| Rule | Value |
|---|---|
| Clock | Day the filing was made public (`broadcast_date`) |
| Entry | Close of the first session after that day (cautious: not every filing has a time of day) |
| Horizons | 5, 21, 63, 126 sessions (1W, 1M, 3M, 6M); complete windows only |
| Benchmark | Nifty 500, same sessions (excess = stock minus index) |
| Costs | 0.25 percentage points off every return |
| De-duplication | One event per company per signal per 21 sessions |
| Minimum size | Rs 25 lakh per trade; token buys excluded |
| Shown | Median excess, share that beat the index, cases; "few" under 30 cases |

## Window-open buys (exploratory, 12 Oct 2026)

SEBI PIT closes the trading window from the end of each quarter until 48
hours after the results. An open-market buy in the first
`WINDOW_OPEN_SESSIONS` = 5 NSE sessions after it reopens is marked
(`window_open_buy`, `insiders_clean/trading_window.py`). Results day = the
NSE board meeting on results; the window is taken to reopen on that day + 2
calendar days. Shown as a fact and a filter on Insider trades; not measured
yet, so not ranked and no edge claimed. Track record can measure it from the
`window_open_buy` column.

Signals measured: promoter buy; promoter buy within 5% of / 30%+ below the
52-week high; spotlight; cluster; director or KMP buy; promoter sale;
director or KMP sale; real-fund net deal buy in small caps. Not yet: a
size-matched benchmark (small and micro caps against their own indices).


## Forward record (12 Oct 2026)

The Track record backtest is re-measured nightly on the whole history, so a rule
change rewrites the past. The forward record does not: after each nightly the
precompute job appends every event made public in the last 5 sessions and not
yet recorded to a new write-once file `ledger/forward/<run time>.parquet`, with
the run time, the rules version (`insiders_clean/track.py` `RULES_VERSION`,
bumped whenever a rule, threshold, spacing or cost changes) and the latest close
known then. Rows are never edited; their returns are derived by the same rules
as the backtest (`artifacts/forward_outcomes.parquet`).

## Model basket (12 Oct 2026)

A paper portfolio on rules fixed in advance (`insiders_clean/basket.py`,
`BASKET_VERSION`), built only from the forward record so nothing in it was
picked with hindsight. Each forward-record row is stamped, the night it fires,
with its signal's evidence verdict (`insiders_clean/evidence.py`) and the
stock's tradability flags. A position opens for a row whose verdict was
"leaning positive" and whose stock had no surveillance, trade-for-trade, SME,
tight-band or circuit flag; entry the next close, equal weight, held 63
sessions, 0.25 points of cost each, one position per company at a time.
Shown on Track record against Nifty 500 over the same sessions.

## Tradable only (12 Oct 2026)

Each Track record event carries `restriction`, judged from the NSE bhavcopy as it
stood on the day made public (no hindsight): trade-for-trade or SME series that
day, or a band lock (one price all day, a move of 1.9% or more) in the 20
sessions up to it. "Tradable only" on Track record re-measures the scorecard on
the events with no restriction. Surveillance stages (ASM/GSM/ESM) are not used
here: our snapshots of those lists start on 12 Oct 2026.
