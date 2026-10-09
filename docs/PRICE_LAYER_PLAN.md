# Native point-in-time price layer — plan (09 Oct 2026)

Status: plan only; nothing built. Labels: VERIFIED / ESTIMATED / CLAIMED / HYPOTHESIS.

## Why
- VERIFIED (docs/AUDIT.md addendum): Paresh's adjusted-close table covers 1,184 of 3,116 NSE symbols (38%) with 2026 data, and only 28% of 2026 open-market insider *buy* events have price history in it. Its BSE file (`bse_daily`) covers 86.5% of the security master by ISIN but its adjustment status is unknown. Owner decision: Paresh data = secondary cross-check only.
- Needed (MISSION s11): signal-time entry prices, 52-week range, trailing returns, volatility and benchmark windows, delisted names kept, no look-ahead, net-of-cost returns.

## Sources (primary; availability to be verified from a GitHub Actions runner)
1. **NSE capital-market bhavcopy, UDiFF format** (all series incl. SME). CLAIMED: SEBI's Market Data Advisory Committee standardised exchange files as "UDiFF"; NSE circular NSE/MSD/62142 (22 May 2024) governs the rollout; archive file name pattern `BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip` under `nsearchives.nseindia.com` (the pattern is seen in a user forum post, not in an official text I could retrieve). Circular NSE/MSD/54028 (Oct 2022) names the older "common bhavcopy" `NSE_CM_bhavcopy_ddmmyyyy.csv`. Circulars NSE/MSD/74764 (June 2026) and NSE/MSD/75910 (Aug 2026) move the `.DAT` bhavcopy to the Extranet from 12 Oct 2026 and discontinue `.MS/.MD` formats: **HYPOTHESIS** that the public UDiFF CSV stays; verify before building.
2. **BSE equity bhavcopy, UDiFF** ("Equity (UDiFF)" on bseindia.com/markets/marketinfo/BhavCopy.aspx; older standardised files retired under BSE notice 20240610-33, per the page). Exact file name/columns: UNVERIFIED (MSE's pattern is `BhavCopy_MSE_CM_0_0_0_YYYYMMDD_F_0000`; BSE's is probably analogous: HYPOTHESIS).
3. **Corporate actions** (splits, bonus, rights, demerger, dividends, ISIN/symbol changes): we already collect NSE actions (`collectors/nse_events`, `clean/current/actions.parquet`, daily). Gap: BSE actions, mergers/demergers and ISIN changes need a second source; face-value changes alter ISIN (to verify).
4. **Index / benchmark series**: NSE index history (Nifty 500, Nifty Smallcap 250 / Microcap 250) from NSE's index archives. Source and licence terms: to verify. Indian factor data: IIMA Fama-French-Momentum library, availability/currency to verify (MISSION s7.3).
5. **Surveillance lists / price bands** (ASM, GSM, ESM, T2T): NSE/BSE circular files; verify formats.

## Depth needed
2026 events need ~1 year of history for 52-week ranges and 250-session windows: from about Jan 2025. UDiFF started July 2024 (CLAIMED), so Jan 2025 onward is entirely in one format; no old-format parser needed. Optional later: older formats for deeper research history (needs the owner's approval only if it pulls pre-2026 *disclosures*; prices are allowed, MISSION s6.2).

## Design
- **Raw**: every downloaded file stored byte for byte in `raw_v2/` (existing `RawStore`; collector uses `raw_capture` + `raw_flush`).
- **Clean `prices_daily`**: one row per (isin, exchange, date): open, high, low, close, prev_close, volume, traded value, trades, series/group, symbol and BSE code *as of that day*. Never adjusted in place.
- **Security master with history**: ISIN <-> NSE symbol <-> BSE code with valid-from/valid-to from the daily files themselves (a symbol on a date is an observed fact), so renames and ISIN changes are not guessed.
- **`adj_factor` table** from corporate actions, applied at query time (cumulative factor per ISIN and date) so a signal at time t uses only actions known by t. Splits/bonuses are easy; rights and demergers need explicit price-adjustment rules and are marked `approx` until validated against bhavcopy `prev_close` jumps.
- **Validation** (every run, in the data-health report): close-to-prev_close ratio breaks not explained by a known action; days with no print for a listed security (halts, circuit locks, suspension) kept as gaps, never forward-filled silently; cross-check against Paresh closes (secondary): report coverage and disagreement rate.
- **Point-in-time rule**: a feature at signal time T may only read rows with date <= the last session fully before T; tests enforce it (MISSION s11.1).
- **Market cap / free float**: PIT market cap = shares outstanding at date x close. Shares outstanding history is NOT available from bhavcopy: candidates are quarterly shareholding XBRL (already collected for NSE), AMFI half-yearly categorisation, and exchange market-cap files. Until a PIT series exists every market-cap-based ratio is labelled "as of 06 Oct 2026, not point in time" (as in docs/SIGNALS.md).

## Staged steps
1. Verify availability from an Actions runner: one-off probe workflow downloads one NSE and one BSE bhavcopy for a recent date and a date in Jan 2025, stores bytes in `raw_v2/`, prints column names/row counts (no secrets beyond existing R2). Gate check: any new external host is "dependencies that call new external services" -> ask first (Gate 6) if it is not already nseindia.com/bseindia.com.
2. Write parsers against the real files (fixtures from step 1), with tests.
3. Backfill Jan 2025 -> today, rate-limited, resumable (same pattern as `nse_history_backfill.py`); nightly increment.
4. Adjustment factors + validation report; coverage report vs the 2026 events (target: >=95% of events and >=99% of traded value have a usable entry price).
5. Benchmarks + factor data; then the evaluation framework (Phase 2).

## Risks
- NSE blocking GitHub runners (the home page already 403s; API and archives answer). Mitigation: same pacing and stop-on-403 rules as the backfill; report, never escalate.
- Format change at NSE (Extranet moves in Oct 2026). Mitigation: raw bytes kept; parsers versioned; probe workflow re-run on failure.
- Corporate-action coverage for BSE-only and SME names.

## Sources consulted (web, 09 Oct 2026)
- NSE forms & formats (UDiFF): https://www.nseindia.com/static/resources/forms-formats-members
- NSE circulars NSE/MSD/54028, NSE/MSD/74764, NSE/MSD/75910 (nsearchives.nseindia.com/content/circulars/)
- BSE bhavcopy page: https://bseindia.com/markets/marketinfo/BhavCopy.aspx and UDiFF page https://bseindia.com/static/members/udiff.aspx
