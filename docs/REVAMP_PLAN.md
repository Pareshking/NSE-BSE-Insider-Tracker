# Site audit and revamp: plan (21 Oct 2026)

Owner's brief (21 Oct): many numbers are wrong; full audit; whole-site revamp for
UI/UX and ease of reading details; less verbose, more information; professional
custom CSS (flex/grid); no duplicate items across pages; a line-by-line review of
the code; XBRL where it is the better source; then improvement, verification and
delivery in continuous engineering loops.

Rules stay as in `CLAUDE.md`: data correctness first, the site never cleans,
pages follow the data, nothing invented, raw write-once.

## What "done" means

1. Every number on every page has a written source (table, column, rule) and was
   checked against the exchange's own filing or file on a sample, with the result
   recorded (`docs/AUDIT_LOG.md`). No open "wrong number" defect.
2. Each page answers one question; no list, tile or table appears on two pages
   (a page may link to another's list, not repeat it).
3. One design system (`streamlit_app/ui/`): tokens, grid/flex layout, a small set
   of components, used by every page. Phone (390 px) and desktop (1440 px) both
   clean in the Site preview screenshots.
4. Text: page subtitles one line; no paragraph of caveats on a page (evidence
   status stays, as a tag).
5. Tests cover each fixed defect; CI and screenshots green on every PR.

## Phase 1: baseline (inventory)

- Page inventory: for each page, every section, tile, column and the function and
  clean column it comes from. Output: `docs/AUDIT_LOG.md` part 1, a table per page.
- Duplicate map: which list/tile appears on more than one page (Actions, Morning
  brief, Latest session, Screener and Company overlap today).
- Screenshots of every page at 1440 and 390 px on real data (live site), kept as
  the "before" set.
- Freshness: the "as of" date on every page against the last trading session
  (21 Oct: the site says filings up to 19 Oct).

## Phase 2: numbers audit

Truth source per kind of number:

| Number | Checked against |
|---|---|
| Insider trade value, shares, price, dates, mode, holdings before/after | The NSE/BSE PIT filing (`source_url`), its XBRL where filed |
| % of market cap, market cap | NSE daily market-cap file of that date (issue size x close) |
| Promoter %, public %, pledge %, members | Shareholding-pattern XBRL of the quarter |
| Bulk/block deal client, side, shares, price | NSE/BSE bulk/block CSV of the day |
| CMP, 52-week high/low, 200-day average, returns | Bhavcopy, split/bonus adjusted (checked on a stock with a split) |
| Preferential/QIP/rights terms, ICDR minimum, lock-in | The issue's XBRL |
| Results figures on cards | Results XBRL |
| Track record, forward record, basket | A second, independent computation on a sample of events |
| Tiles and totals | Recomputed from the clean tables; NSE/BSE copies counted once |

Sample: 30 companies across size, NSE-only, BSE-only, a split or bonus, heavy
pledge, preferential issue, a cluster, a market maker, a late filing. Every number
on their Company page and every row they appear in elsewhere is checked. Plus
invariants over all rows (each trade once, sides sum, no future dates, no value
on a holding-only disclosure).

Each defect: page, number, expected (with the source), shown, root cause
(file:line), severity, fix. Logged in `docs/AUDIT_LOG.md` part 2.

## Phase 3: code review, line by line

Every file under `streamlit_app/screens/`, `streamlit_app/ui/`, and the parts of
`insiders_clean/` the site reads (`signals`, `actions`, `evidence`, `track`,
`basket`, `slim`, `participants`, `trading_window`, `universe`) and
`scripts/precompute_slim.py`. Checklist: units (rupees, lakh, crore, percent vs
fraction), NSE/BSE copies (`is_primary`), window edges and time zone (IST),
split/bonus basis, market makers and token buys, NaN and empty handling, a number
computed twice in two places, dead code, memory on Streamlit Cloud.

## Phase 4: information architecture (owner approved 21 Oct, blueprint artifact "Insiders Blueprint")

From the individual investor's side: follow people with skin in the game, look where funds cannot go,
avoid the traps. Four links in a top bar:

| Page | What it holds |
|---|---|
| Today | A dashboard (owner, 21 Oct): period chips (Today, 7, 30, 90 days), a headline count, tiles, filters (size, sector, name), group pills, and a trend panel counting companies per group in each period. Worth a look and Watch out across every listed company, in groups (`ideas.GROUPS`), one row per company, by % of the company (`insiders_clean/ideas.py`): insider buys and promoter sales (per decision-maker over the period, tranches combined: Rs 25 L and 0.05%, or 0.25% alone, or 10+ buying days), preferential shares or warrants to promoters at a premium or a discount to the price now, big investors in or out (SAST 5% / 2%, lenders' trustees and security agents left out), funds' net bulk/block buying or selling, pledges (PIT net of releases, or a 5+ point quarterly move made public in the period), tender buybacks at a premium. Evidence is a tag on every kind, never a filter: promoters buy for the quarters and years ahead (owner, 21 Oct). |
| Companies | The dossier: header, for/against with numbers, risks always shown, price with each decision, ownership by quarter from the XBRL, one timeline, filings that open to their facts. |
| Evidence | One small table of what has worked, with case counts. |
| Filings | Every filing and deal, filters, rows that open (where the noise lives). |

People & funds pages open from links only. No watchlist (owner, 21 Oct).

## Phase 5: design system (the written standard: docs/DESIGN.md, checked on every page before merge)

- Tokens in one place (colour, type scale, spacing, radius, shadow); light theme
  as decided on 08 Oct (canvas #F6F7F9, white cards, indigo for links, green/red
  only for buy/sell, amber for "needs a look"), Geist with tabular figures.
- Layout: CSS grid for the page (header, KPI strip, main, side panel on desktop),
  flex rows inside cards; one breakpoint at 768 px.
- Components: page header (title, one-line purpose, as-of date), KPI strip,
  data table (sticky header, sort, row detail that opens inline instead of a new
  page, sparkline, badges), company header, tag, empty state.
- Detail on demand: rows expand to the filing's facts and link; long lists page.

## Phase 6: build loops (one page group per PR)

Order: design system and Company (the page everything links to), then Today,
Ideas, Filings, Deals, Person, Evidence, Capital raises, Data quality.
Each loop: fix that page's audit defects, rebuild it on the design system, tests
for each defect, Site preview screenshots at 1440 and 390 px on real data,
re-check its numbers on the sample, merge, then the next.

## Phase 7: verification and delivery

A final pass of Phase 2 on all pages, the before/after screenshots, the closed
defect log, and a short delivery note to the owner.

## Constraints and risks

- Another session works on the announcement reader on `main` daily
  (`scripts/announcement_reader.py`, Filings read): the revamp keeps out of the
  reader's files and rebases often.
- Pushing needs the Pareshking GitHub account active on this machine.
- Streamlit Community Cloud memory: tables are cut to the needed columns and the
  study universe (PR #55) before any page reads them.
