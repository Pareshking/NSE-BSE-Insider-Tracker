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

## Pages

- **Overview** -- KPI strip per category, latest insider-trading activity,
  system status (from the run manifest), validation summary.
- **Transactions** -- all 5 categories as tabs, exchange toggle, filters,
  row selection opens an evidence dialog (canonical fields, native source
  fields, cross-exchange match basis/confidence when flagged).
- **Data Quality** -- certification matrix straight from the manifest
  (including datasets skipped as `RATE-LIMITED`/`BLOCKED`/`MISSING` --
  never hidden), ISIN resolution rate, known limitations.

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
what `r2_writer.py` produces (same keys, same `canonical_*` field names) --
this session had no R2 credentials to test against the real bucket. First
real run should be checked against actual data before relying on it.
