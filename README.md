# NSE-BSE Insider Tracker ("Insiders")

> The site at insiders.streamlit.app is built from `docs/DATA_TO_PAGES.md`
> on the clean tables (PR #17, 09 Oct 2026). Earlier versions (the old
> `streamlit_app/views/` demo and the 09 Oct 13-page app) were wrong and are
> gone; see `docs/PRODUCT.md`.

## What this is

A data-first research tool that helps a small investor in Indian equities use NSE and BSE
disclosures (insider trades, bulk and block deals, SAST stake changes,
corporate actions, shareholding and pledges) to make decisions, by sizing
each filing against the company, removing the noise, connecting filings
across people and time, and measuring what happened after similar signals.

## Where things are

| | |
|---|---|
| What the site is for and every decision taken | `docs/PRODUCT.md` |
| Signal definitions and thresholds | `docs/SIGNALS.md` |
| Cleaning rules, storage, trading calendar, backfill | `docs/CLEAN_LAYER.md` |
| Every clean table and column | `docs/DATA_DICTIONARY.md` |
| What is open and how we will know it's done | `docs/TODO.md` |
| Collection pipeline and its validation history | `PROJECT_PLAN.md`, `DATA_ACQUISITION.md`, `VALIDATION_STATUS.md` |
| The site's code | `streamlit_app/README.md` |

Agents: read `CLAUDE.md` first.

## Running

```
python -m pytest tests -q          # tests
python scripts/dev_ui.py FOLDER    # the site on localhost, reading a local copy of the clean tables
```

The nightly jobs run in GitHub Actions (`.github/workflows/`): R2 Storage
Write (collect, validate, archive, clean) and NSE Corporate Events.
