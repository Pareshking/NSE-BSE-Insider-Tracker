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
| Cluster | 2+ distinct buyers within 30 days, including at least one director/KMP, or promoter entities that are not one family | 62 companies a year had 3+ distinct buyers, but only 12 included a director/KMP; the rest were one promoter family buying together |
| Market makers | Bulk/block clients with 40+ legs in a quarter and buys/sells within 20%: labelled, kept out of signals | 32 clients made 60% of deal legs (09 Jul - 07 Oct 2026) |
| Price context | Distance from 52-week high and from 200-day average, shown as neutral numbers ("-14% from 52W high") | Whether buying near highs or after falls works better is contested; the signal lab measures both before either becomes a rule |
| Scoring | No star score. Factor badges only (size, cluster, pledge, price distance) | Weights would be arbitrary until measured |

Display: 14px card radius, as on paresh.streamlit.app.

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

Signals measured: promoter buy; promoter buy within 5% of / 30%+ below the
52-week high; spotlight; cluster; director or KMP buy; promoter sale;
director or KMP sale; real-fund net deal buy in small caps. Not yet: a
size-matched benchmark (small and micro caps against their own indices).

