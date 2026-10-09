# CLAUDE.md

Standing instructions for agents. Read `docs/PROGRESS.md` first, then `docs/MISSION.md`.

## Repo map
- `scripts/` collectors and R2 writers (nightly), `insiders_clean/` cleaning + raw store, `collectors/nse_events/`, `streamlit_app/` (old demo app, deployed from `main`), `docs/` (see `docs/CLEAN_LAYER.md`, `docs/DATA_DICTIONARY.md`).

## Commands
- Setup: `pip install -r requirements.txt pytest` (pandas is pinned `<3`; tests also pass on 3.0).
- Test: `python -m pytest tests streamlit_app/tests -q`
- Clean tables / backfill / inventory run in GitHub Actions (R2 secrets live there, not in agent sessions): `NSE History Backfill`, `Clean only`, `Data inventory`.

## Hard rules (docs/MISSION.md section 3)
1. Never push or merge to `main` (it redeploys production); work on feature branches, PRs as drafts.
2. Never delete/overwrite data files, scrapers, workflows or branches; never rewrite shared history.
3. `Pareshking/Paresh` is read-only. Repo is public: no holdings, watchlists or personal data.
4. No pre-2026 transactions in the product (clean layer filters at 1 Jan 2026; raw archive keeps them).
5. Ask before: new secrets/paid services/wider Actions permissions, pre-2026 research data, final cut-over.
6. Label claims VERIFIED / ESTIMATED / CLAIMED / HYPOTHESIS; flag contradictions; never invent data.
7. Raw is write-once and never filtered (`raw_v2/`); filtering happens in the clean layer with counted reasons.
