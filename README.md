# NSE-BSE Insider Tracker ("Insiders")

> **Read this first: the current website is a demo, and it is wrong.**
> The site live at insiders.streamlit.app (until the new site in PR #4 is
> merged) and the app code it ran (the old `streamlit_app/views/` pages and
> their in-app calculations) are a **demo only**. They are wrong at multiple
> levels: page structure, columns, and the calculations underneath. For
> example, preferential allotments were counted as open-market buying,
> duplicate filings were shown twice, an off-market transfer was ranked as
> the top "stake change", and a list labelled "biggest" was sorted by date.
> Do not use that site for investment decisions, and do not use its code or
> pages as a reference for new work.
>
> **The collected data is not the problem.** The NSE/BSE collection pipeline
> and the raw and canonical data it stores in R2 are sound. What replaces
> the demo is the clean layer (`insiders_clean/`, `docs/CLEAN_LAYER.md`) and
> the new site built to `docs/PRODUCT.md`.

## What this is

A free site that helps a small investor in Indian equities use NSE and BSE
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

## Project state and mission

`docs/MISSION.md` (the brief, verbatim), `docs/PROGRESS.md` (where we are),
`docs/DECISIONS.md` (each decision and how to reverse it), `docs/AUDIT.md`
(Phase 0 findings and data numbers). Agents: read `CLAUDE.md` first.
Note: `scripts/dev_ui.py` below does not exist on `main` (it is part of PR #4).

## Running

```
python -m pytest tests -q          # tests
python scripts/dev_ui.py FOLDER    # the site on localhost, reading a local copy of the clean tables
```

The nightly jobs run in GitHub Actions (`.github/workflows/`): R2 Storage
Write (collect, validate, archive, clean) and NSE Corporate Events.
