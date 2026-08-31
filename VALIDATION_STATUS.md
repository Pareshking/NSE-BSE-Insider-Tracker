# Validation Status — NSE + BSE

Last updated: 2026-09-01

## Operating rule

No one-year R2 backfill and no production-schema freeze until the pipeline phases are cleared and the user explicitly authorizes the next stage.

## Acquisition architecture

NSE and BSE acquisition engines are intentionally separate:

- `scripts/nse_acquisition.py` — NSE transport, CSV parsing, date-window tests and NSE package acquisition.
- `scripts/bse_acquisition.py` — BSE browser rendering, BSE-specific tables and pagination.
- `scripts/acquisition_probe.py` — orchestration/reporting only; it must not contain exchange-specific acquisition logic.

The 5-page limit is a diagnostic cap only. It is not evidence of full-day completeness.

## Latest verified baseline

Target date: `2026-08-31`

### NSE

| Dataset | Raw | Unique | Native date observed | Status |
|---|---:|---:|---|---|
| Insider | 0 parsed in prior probe | 0 | unresolved | **BLOCKED / unresolved** |
| Bulk | 70 | 70 | `31-AUG-2026` | acquisition proven |
| Block | 11 | 11 | `31-AUG-2026` | acquisition proven |

NSE Insider is **not** considered empty. The official NSE page exposes multiple windows and Archive Data. A valid CSV header was previously returned but no records parsed for the tested request; the corrected NSE engine now tests native JSON first and multiple windows. This remains blocked until a real non-empty result and its date semantics are verified.

### BSE

| Dataset | Raw | Unique | Date interpretation | Status |
|---|---:|---:|---|---|
| Insider | 154 | 146 | broadcast `31/08/2026`; acquisition dates earlier | acquisition + dedup proven for tested page; completeness unresolved |
| Bulk | 73 | 73 | deal date `31/08/2026` | acquisition proven; completeness unresolved |
| Block | 19 | 17 | deal date `31 Aug 26` | acquisition proven; duplicate classification unresolved |
| Rights | 50 in 5-page test | 50 | issue-stage/company rows | incomplete; actual termination unresolved |
| Preferential | 5-page test | not production-certified | issue-stage/company rows | incomplete; actual termination unresolved |

## Latest infrastructure defect found

The standalone `NSE-BSE Data Validation` workflow previously ran `data_validation_v4.py` without first creating the required BSE raw capture file. Run `33441200777` failed with `FileNotFoundError: artifacts/data_validation_v4/bse_raw.json`; this was a workflow orchestration defect, not a source-data conclusion. The workflow has been corrected to acquire fresh BSE and NSE evidence before validation. The correction is commit `86bd2ee28b7039fa61333c48fd32de383763281b` and is awaiting fresh-run verification.

## Critical date rule

Dates are source-specific and semantic. Do not collapse them into one `event_date`.

Potential fields include:

- transaction/deal date
- acquisition/allotment date
- disclosure/filing date
- broadcast date
- retrieval timestamp

BSE Insider already demonstrates that a disclosure broadcast on 31-Aug can report an acquisition occurring several days earlier. NSE and BSE also use different textual date formats. Each source must be parsed with its own date rules before canonical normalization.

## Deduplication rule

Perform deduplication in three distinct stages:

1. within NSE;
2. within BSE;
3. across NSE↔BSE only where evidence supports the same underlying disclosure/event.

Bulk/Block rows must remain exchange-aware. A visually similar NSE and BSE execution is not automatically one transaction.

## Mandatory validation loop

1. Test NSE and BSE independently.
2. Inspect real raw records and native columns.
3. Verify every relevant date field and date-window behavior.
4. Identify defects and incomplete pagination.
5. Fix the source-specific acquisition/parser.
6. Retest.
7. Inspect actual output, not only workflow status.
8. Deduplicate within each exchange and classify duplicates.
9. Cross-match exchanges with evidence-based rules.
10. Update this document and the AI handover/task document.
11. Repeat until all acquisition/data-quality gates pass.
12. Only then propose production schema/backfill; wait for explicit authorization.

## Hard rule

A green GitHub workflow means the code path completed. It is **not** data-quality certification. A dataset is PASS only after records, dates, native schema, completeness/pagination and duplicate behavior have been inspected.
