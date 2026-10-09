# Decisions

## 2026-10-09 Phase 1 start (owner approvals in session)
- Pre-2026 filings (8 Oct–31 Dec 2025) stay in the raw R2 archive (Gate 3: nothing deleted); the clean layer drops them by `insiders_clean.pipeline.PRODUCT_START` (1 Jan 2026) with counted reasons `before_product_start` / `no_readable_transaction_date`. Insider ranges use the last day of the range. Undated rows are held out (strict). Reverse: change `PRODUCT_START` and rerun clean-only.
- Production deploys from `main`: no merges to `main` (PR #11, #4 stay open). All work on `ccr-27a6c75f-o9ztpa`.
- `acquisition-probe.yml`: trigger = `workflow_dispatch` only, `contents: read`, the push-to-main step removed. Reverse: git revert.
- Round-trip deal legs are flagged (`intraday_round_trip` column written by `scripts/r2_writer.py`), never dropped; `clean_deals` excludes them with reason `intraday_round_trip`. Manifest: `intraday_round_trip_rows_dropped` is now 0, `..._flagged` carries the count.
- **Known loss:** rows already dropped before this change (nightly snapshots and the 8 Oct 2025–Jun 2026 backfill, 6,460 rows) are absent from the archive. Recover by re-running the backfill for deals (needs approval to run; Actions). Nightly rows from now on are complete.
- pandas 3: `insiders_clean/dates.py` fixed (read-only array; out-of-ns-range dates such as year 3034 become NaT as under pandas 2). 93 tests pass on pandas 2.x and 3.0.6; `requirements.txt` keeps `<3` until a deliberate upgrade.
