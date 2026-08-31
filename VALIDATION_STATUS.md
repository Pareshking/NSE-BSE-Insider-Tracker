# Validation Status — NSE + BSE

Last updated: 2026-09-01

## Latest verified artifact

Artifact: `nse-bse-acquisition-validation-v4.zip`
Target date: `2026-08-31`

### NSE

| Dataset | Raw | Unique | Native date observed | Status |
|---|---:|---:|---|---|
| Insider | 0 parsed | 0 | unresolved | **BLOCKED / unresolved** |
| Bulk | 70 | 70 | `31-AUG-2026` | acquisition proven |
| Block | 11 | 11 | `31-AUG-2026` | acquisition proven |

NSE Insider is **not** considered empty. The endpoint returned a valid CSV header with 29 native columns but no parsed data for the tested request. The official NSE page exposes 1D, 1W, 1M, 3M, 6M, 1Y, Custom and Archive Data, so the request/date-window logic is being retested rather than treating zero rows as a valid result.

## BSE

| Dataset | Raw | Unique | Date interpretation | Status |
|---|---:|---:|---|---|
| Insider | 154 | 146 | broadcast `31/08/2026`; acquisition dates earlier | acquisition + dedup proven for tested page |
| Bulk | 73 | 73 | deal date `31/08/2026` | acquisition proven |
| Block | 19 | 17 | deal date `31 Aug 26` | acquisition proven; 2 duplicates require classification |
| Rights | 50 in 5-page test | 50 | issue-stage/company rows | incomplete test; pagination unresolved |
| Preferential | 125 raw in artifact; 250 DOM rows observed in earlier 5-page representation | not production-certified | issue-stage/company rows | incomplete test; pagination unresolved |

The BSE five-page cap is a **testing limit**, not a claim of complete daily coverage.

## Critical date finding

BSE Insider demonstrates why the model needs separate dates. A disclosure broadcast on 31-Aug can report an acquisition occurring on 26-Aug or 27-Aug. `broadcast_date` and `transaction_date/acquisition_date` must never be collapsed into one `event_date`.

NSE Bulk/Block use native dates such as `31-AUG-2026`, while BSE Bulk uses `31/08/2026` and BSE Block uses `31 Aug 26`. Date parsing must be source-specific before canonical normalization.

## Cross-exchange deduplication

Not yet production-certified. NSE Insider being unresolved means the current comparison cannot establish whether NSE and BSE insider disclosures are mirrored. Bulk/Block matching must remain exchange-aware; identical-looking rows are not automatically duplicates because they can represent exchange-specific executions.

## Next mandatory loop

1. Retest NSE Insider with multiple date windows and actual CSV parsing.
2. Validate NSE Insider against the official NSE page/archive behavior.
3. Inspect BSE Insider duplicate rows individually.
4. Determine actual BSE pagination/termination for Rights and Preferential rather than assuming five pages is complete.
5. Run multi-date historical tests for NSE and BSE.
6. Normalize native schemas without discarding source fields.
7. Perform intra-source deduplication.
8. Perform evidence-based NSE↔BSE matching.
9. Freeze canonical schema only after the above passes.
10. Then begin the one-year R2 backfill.

## Hard rule

A green workflow is a test-run status, not a data-quality certification. A dataset is only marked **PASS** after its actual records, dates, schema, completeness and duplicate behavior have been inspected.