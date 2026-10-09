# CLAUDE.md

Standing instructions for agents. Read `docs/PRODUCT.md` (purpose and every
decision) and `docs/TODO.md` (where things stand, what is next) first.

## Repo map
- `scripts/`: collectors and R2 writers (nightly), backfill, price backfill, precompute.
- `insiders_clean/`: cleaning, archive, raw store, signals, prices.
- `collectors/nse_events/`: SAST, corporate actions, board meetings, shareholding.
- `streamlit_app/`: the site (`app.py`, `screens/` pages, `ui/` design kit, `data/store.py` reads R2). Deployed from `main` to insiders.streamlit.app.
- `docs/`: `PRODUCT.md`, `DATA_TO_PAGES.md`, `SIGNALS.md`, `CLEAN_LAYER.md`, `DATA_DICTIONARY.md`, `TODO.md`.

## Commands
- Setup: `pip install -r requirements.txt -r streamlit_app/requirements.txt pytest`
- Test: `python -m pytest tests -q`
- Site locally: `python scripts/dev_ui.py FOLDER` (a local copy of `clean/current/`); R2 secrets live only in GitHub Actions and Streamlit Cloud.
- Workflows (GitHub Actions): R2 Storage Write (nightly), Clean only, NSE History Backfill, Price backfill, Precompute slim assets, Site preview (screenshots on real data, runs on PRs).

## Rules
1. Data correctness first; the site never cleans, it reads the clean tables.
2. Pages follow the data (`docs/DATA_TO_PAGES.md`); a section waits for its data rather than being faked.
3. The site is public and the repo is public: nothing personal in either.
4. Facts and measured evidence, not buy/sell advice (`docs/PRODUCT.md`).
5. Raw is write-once (`raw_v2/`); filtering happens in the clean layer with counted reasons.
6. Product window: transactions from 8 Oct 2025 (`insiders_clean/pipeline.py`).
7. Never invent data, columns, endpoints or results; say what is missing.
