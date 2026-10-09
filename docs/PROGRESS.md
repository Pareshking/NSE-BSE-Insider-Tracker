# Progress (09 Oct 2026, times IST)

## Where we are
Phase 0 audit: approved. Phase 1 data foundation: merged to `main` (PR #11, 14:17 IST). Phase 1 price layer: backfill complete; PR #12 merged. Phase 2 evidence: started (register + evaluation code), no results yet. Phases 3-5 (product, launch, operate): not started.

| Area | State |
|---|---|
| Raw layer (write-once `raw_v2/`) | In production. Run 2: 28/28 stored, 0 failed. Nightly flushes every run. Owner-side: object-lock on `raw_v2/` still to set |
| Nightly bulk/block (uncapped CSV) | In production; backfill recovered NSE bulk +13,853, block +908 rows |
| Clean layer (2026 window, counted reasons, round trips flagged) | In production. A rebuild with the recovered rows is queued (Clean only); the 23:30 IST nightly rebuilds it too |
| Insider revision markers | In production (prevAppId, typeOfSubmission, revisionRemark) |
| Price layer (NSE + BSE UDiFF, raw first) | Backfill from 1 Jan 2025 running; sample months verified; NSE prices complete, BSE and NSE market cap catching up (see backfill below) |
| Market cap | NSE daily `mcap` file parsed (shares in issue x close); indicative size buckets only (owner simplification). BSE-only names unbucketed |
| Price adjustment | Splits, bonuses, consolidations only (clean-ratio resets); other large resets counted, not applied; no dividend adjustment |
| Evaluation core | Built and tested (entry rule, forward returns, market and size-matched benchmarks, date-clustered bootstrap, MDE, hold-out split at 30 Jun 2026) |
| Pre-registration | `docs/RESEARCH.md` open: 9 hypotheses, literature register (unverified), power estimates, variant log |
| H1 / H2 / H8 results | Not run; waits for the price backfill and the PR #12 merge |
| Streamlit production | Not verified after the 14:17 IST deploy (no log access); please check the app loads |

## Price backfill: COMPLETE (17:00 IST)
NSE prices 437 of 437 days, BSE 437 of 437, NSE market cap 437 of 437 (100% each), every stored day has its raw file. Coverage of 2026 events: insider entry price 99.3% (250-session history 8,879 of 9,990), deals 97.9% (11,629 of 17,318). Details: `docs/AUDIT.md` addendum 3. BSE does not reset previous-close on splits, so dual-listed securities inherit the NSE factor and BSE-only securities stay on raw prices (flagged).

## Phase 2 first results (09 Oct 2026, IST)
PR #12 merged to main (c5ce96b). H1, H2, H8 ran on the development sample: see `docs/RESEARCH.md` section H. Summary: no evidence of an edge for insider market buys (negative vs size peers at 20/60 sessions); insider sells underperform 1.5 to 2.4% at 5 to 20 sessions (short side, before costs); deal buy and sell groups look alike (benchmark and micro-cap skew caveats). Costs not applied; hold-out untouched.

## Conditioned cuts (09 Oct 2026, IST)
H1 cuts C1..C9 (promoter, size, breadth, drawdown) were pre-registered and run: no cut shows an edge vs size-matched peers; large/relative-size purchases are significantly worse. See `docs/RESEARCH.md` section I. Phase 3 UI not started; product labels decided: insider buys and deals "no proven edge", insider sells a caution flag.

## Pending / next (autonomous order)
1. Backfill finishes -> coverage report -> record numbers here and in `docs/AUDIT.md`.
2. Remove temporary push triggers from `price-backfill.yml` and `price-coverage.yml`; pytest; squash-merge PR #12 (Gate 2 pre-approved).
3. Dispatch `research-run.yml` (development period): H1, H2, H8 with market and size-matched benchmarks; record in `docs/RESEARCH.md`.
4. Then: remaining hypotheses (H3-H7, H9), BSE market cap/shareholding, pledges, forward-test ledger, data-health view, then Phase 3 product on a staging branch.

## Known risks
- The 23:30 IST nightly shares a lock with the backfill and waits for it.
- Under-powered tests will be reported as "insufficient evidence".
- NSE circulars change Extranet formats from 12 Oct 2026 (HYPOTHESIS: public UDiFF CSV unaffected); the nightly price increment will show.
