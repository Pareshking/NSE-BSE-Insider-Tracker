# Progress (09 Oct 2026)
- Phase 0 approved. Phase 1 (data foundation) merged to `main` as PR #11 (5b53079) under the owner's Gate 2 pre-approval, after R2 test run 2 passed.
- In production now: write-once raw layer (`raw_v2/`), nightly bulk/block via the uncapped CSV endpoint, revision markers on insider filings, 2026 product window and counted exclusion reasons in the clean layer, round trips flagged not dropped, pandas 3 fix.
- Recovery backfill done: NSE bulk +13,853 rows, block +908 rows (2025-10-08 to 2026-10-09). Clean tables rebuilt by `Clean only` (see DECISIONS).
- Bhavcopy probe VERIFIED: NSE and BSE UDiFF files work from Actions for Jan 2025 and Oct 2026, same layout.
- Price layer started on the working branch: parser + validation (`insiders_clean/prices.py`), resumable backfill (`scripts/price_backfill.py`, workflow `price-backfill.yml` with a temporary push trigger). First run from 2025-01-01 is in flight.
- Not verified: Streamlit Cloud redeploy start (no log access).
- Next: confirm price coverage vs 2026 events; corporate-action adjustment factors (NSE actions already collected); security master with history; benchmarks; point-in-time market cap (open problem); nightly price increment; then the evaluation framework.
- Owner-side: set object-lock/delete protection on `raw_v2/`.
