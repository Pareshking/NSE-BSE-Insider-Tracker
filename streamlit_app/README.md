# Insiders: the site

```
streamlit run streamlit_app/app.py
```

The site reads only the clean tables (`clean/current/*.parquet` in R2), which
the nightly pipeline writes (`scripts/clean_writer.py`,
`collectors/nse_events/run_daily.py`). It never cleans data itself: every
rule lives in `insiders_clean/`, and signal thresholds in
`insiders_clean/signals.py` (decisions in `docs/SIGNALS.md`).

## Layout

| Path | What |
|---|---|
| `app.py` | Page setup, the top bar, routing (old addresses redirect) |
| `screens/` | One module per page; `ctx.py` loads the tables once per run |
| `ui/insiders.css`, `ui/theme.py` | The design system: tokens and every class the pages use |
| `ui/kit.py` | Page parts (bar, strip, head, tiles, cards, tags) and formatting (₹ L / ₹ Cr, dates) |
| `data/store.py` | Reads clean tables from R2, or from a local folder |
| `lib/r2_data.py` | R2 client and credentials (`.streamlit/secrets.toml` or env vars) |

Pages: Today, Screener, Insider trades, Deals & big stakes, Capital raises,
Track record, Data; Company (`/company?symbol=`) and Person or fund
(`/entity?id=`) are reached from links.

## Local work

Point the site at a folder with the same layout as the bucket
(`clean/current/*.parquet`, `clean/latest.json`):

```
python scripts/dev_ui.py PATH_TO_FOLDER
```

It serves on `localhost` only (`$PORT`, default 8501).

## Tests

`tests/test_ui_pages.py` builds a data folder from real fixtures through
the production pipeline and renders every page; any exception fails.
