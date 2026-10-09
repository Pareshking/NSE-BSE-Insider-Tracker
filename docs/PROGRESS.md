# Progress (09 Oct 2026, times IST)

## Where we are
Phase 0 audit: approved. Phase 1 data foundation: merged to `main` (PR #11, 14:17 IST). Phase 1 price layer: on PR #12, backfill running. Phase 2 evidence: started (register + evaluation code), no results yet. Phases 3-5 (product, launch, operate): not started.

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

## Price backfill
Run 37913910522 (started 15:21 IST, limit 120 min). GitHub hides the log of a running job, so progress is read from R2 by the coverage workflow. Latest reading in the section below.

## Pending / next (autonomous order)
1. Backfill finishes -> coverage report -> record numbers here and in `docs/AUDIT.md`.
2. Remove temporary push triggers from `price-backfill.yml` and `price-coverage.yml`; pytest; squash-merge PR #12 (Gate 2 pre-approved).
3. Dispatch `research-run.yml` (development period): H1, H2, H8 with market and size-matched benchmarks; record in `docs/RESEARCH.md`.
4. Then: remaining hypotheses (H3-H7, H9), BSE market cap/shareholding, pledges, forward-test ledger, data-health view, then Phase 3 product on a staging branch.

## Known risks
- The 23:30 IST nightly shares a lock with the backfill and waits for it.
- Under-powered tests will be reported as "insufficient evidence".
- NSE circulars change Extranet formats from 12 Oct 2026 (HYPOTHESIS: public UDiFF CSV unaffected); the nightly price increment will show.
