# Streamlit frontend

Reads directly from the R2 bucket `scripts/r2_writer.py` writes to (no
separate API layer) -- manifests for run status, canonical Parquet for the
aligned NSE/BSE fields, raw JSON for evidence drill-down. Never writes to R2.

## Run locally

```bash
pip install -r streamlit_app/requirements.txt
cp streamlit_app/.streamlit/secrets.toml.example streamlit_app/.streamlit/secrets.toml
# fill in the 4 values -- same ones already in this repo's GitHub Actions
# secrets (CLOUDFLARE_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY,
# R2_BUCKET_NAME)
streamlit run streamlit_app/app.py
```

Env vars work the same as secrets.toml if you'd rather not create the file
(e.g. `export R2_BUCKET_NAME=...`).

## Tests

```bash
python streamlit_app/tests/test_pages.py            # every page renders, under odd data shapes
python streamlit_app/tests/test_overview_signals.py # Overview's rollups say what they claim
```

No credentials needed: every page runs headlessly (Streamlit's own
`AppTest`) against an in-memory fake bucket, under the data shapes real runs
produce -- including runs where an exchange didn't publish a canonical
field, and one where R2 itself is unreachable. Also checks that the date
parser resolves every format seen in `artifacts/` to the right day. Each
case is a bug that was live at some point, so add one here whenever you fix
another.

`test_overview_signals.py` covers the rollups rather than the rendering, and
is built from rows the deployed app actually showed: one bulk/block deal
arriving as four rows because both counterparties disclose it and it can land
in both feeds; 493 securities flagged "concentrated" at top3 100%, because a
security traded by three or fewer clients is trivially 100%; +13,981.7% as a
headline stake change off a 1,000-share base; and an ESOP filing summed into
promoter "accumulation" and ranked by % of market cap.

## Pages

- **Overview** -- category pulse strip, promoter accumulation ranked by % of
  market cap, biggest transactions across all 5 categories, concentration
  alerts, biggest stake changes.
- **Confluence Screener** -- per-ISIN join across insider / bulk / block /
  rights / preferential, ranked by Float Absorption Ratio.
- **Entity Tracker** -- reverse lookup of one person, fund or client name
  across every category.
- **Evidence & Drill-down** -- all 5 categories as tabs, exchange toggle,
  filters, row selection opens an evidence dialog (canonical fields, native
  source fields, cross-exchange match basis/confidence when flagged).
- **Promoter Activity** / **Bulk & Block Concentration** -- net-position and
  client-concentration rollups.
- **Data Quality** -- certification matrix straight from the manifest
  (including datasets skipped as `RATE-LIMITED`/`BLOCKED`/`MISSING` --
  never hidden), ISIN resolution rate, known limitations.

Evidence & Drill-down, Confluence Screener and Entity Tracker each export
exactly the rows on screen as CSV, with `canonical_*` values as stored --
raw numbers and source date strings, not this app's display formatting, so
an exported figure can be checked against the exchange's own filing.

## Reading the data safely

Two shared helpers exist because getting either wrong was a live bug, so
prefer them over raw pandas when touching a canonical field:

- `lib.fields.parse_dates` -- the exchanges publish three date conventions
  (NSE ISO `2026-08-28`, NSE IST-midnight-as-UTC `…T18:30:00.000Z`, BSE
  day-first `31/08/2026`). Any single blanket `dayfirst` setting reads one
  of them months off; this picks per value.
- `lib.fields.text_col` / `num_col` -- a canonical column an exchange didn't
  publish, accessed as `df.get(col, pd.Series(dtype=object))`, yields an
  unaligned mask and raises `IndexingError`. These stay aligned to
  `df.index`, so a missing field narrows a page instead of crashing it.

R2 read failures other than "object isn't there" raise
`r2_data.R2ReadError`; pages wrap their loads in `r2_data.page_gate()` /
`r2_data.guard()`, which show the reason and stop. Tracebacks stay
server-side (`.streamlit/config.toml` sets `showErrorDetails = "none"`)
because they carry the bucket name and endpoint URL.

## Known gaps vs. the design mockup

This intentionally does not chase the published design canvas's pixel
fidelity (see `FRONTEND_PRODUCT_SPEC.md` / the published Artifact) --
Streamlit was chosen for speed of iteration over exact visual match. What's
different: no true slide-in evidence drawer (a modal dialog instead), no
custom multi-select dropdown chips, simpler charts. Colors, type choices
(IBM Plex Sans/Mono) and information architecture (Overview / Transactions
/ Data Quality, canonical field names) follow the mockup directly.

## Not yet tested against the live bucket

Built and verified against a synthetic manifest/parquet shaped exactly like
what `r2_writer.py` produces (same keys, same `canonical_*` field names, the
same mixed NSE/BSE date conventions) -- no session so far has had R2
credentials to test against the real bucket. First real run should be
checked against actual data before relying on it; the date formats in
`tests/test_pages.py::DATE_CASES` were taken from `artifacts/`, but a format
neither that list nor `lib/fields.parse_dates` anticipates would show up as
an unparsed date string rather than a wrong one.
