# Reference data

## `security_master_20260901.csv`

Security-master crosswalk: ISIN ↔ NSE symbol ↔ BSE scrip code ↔ company
name, sector, industry, market-cap category. Extracted from a Value
Research stock-screener export (`stock-screener-01-Sep-2026--1932.xls`,
provided by the repo owner) taken on 2026-09-01 19:32 IST — 5,287
securities.

**Why this exists:** NSE (alpha tickers like `RELIANCE`) and BSE (numeric
scrip codes like `500325`) share no identifier space of their own — there
is no way to tell "these are the same company" from the acquisition data
alone except a fragile fuzzy match on company name text. This file's ISIN
column is the real, exchange-agnostic identifier that both sides can be
joined on. `scripts/r2_writer.py` uses it (via `load_security_master()`
/ `resolve_isin()`) as the primary key for cross-exchange same-event
matching, falling back to fuzzy company-name matching only when a security
isn't found here.

Data quality (verified before use): 0 duplicate ISINs, 0 duplicate BSE
scrip codes, 0 duplicate NSE symbols across all 5,287 rows; ISIN has 0
nulls. BSE scrip code is null for 706 rows and NSE symbol is null for 2,171
rows — this is real (not every security is cross-listed on both
exchanges), not a data defect.

**Known source-file quirk:** the original `.xls` fails to open in `xlrd`'s
default mode and in LibreOffice (`xlrd.compdoc.CompDocError`) despite being
a structurally valid, complete BIFF8/OLE2 file — confirmed by extracting
the raw `Workbook` stream via `olefile`, which reads it without error. Use
`xlrd.open_workbook(path, ignore_workbook_corruption=True)` to read the
original file; this CSV is already the clean, extracted result so nothing
downstream needs to deal with that.

**Staleness:** this is a point-in-time snapshot, not a live feed. ISIN
mappings for existing listed securities are effectively permanent, but new
IPOs, delistings, and ticker/scrip-code changes after 2026-09-01 won't be
in here. When cross-exchange match rates start silently dropping over time,
that's the signal to refresh this file (a new stock-screener export, same
extraction process) — this isn't wired into an automated refresh yet.
