# Design standard (owner, 12 Nov 2026: redesign from blank)

"Flat, minimal and subtle colours across the theme is key for consistent design across pages. Use theme.py and bring
everything there so in future one line change would work across the website." Every page is checked against this list
before it merges.

## Controls and corners, 19 Nov 2026 (owner: "Remove such large pill shapes from everywhere", #300)
- No pill shapes. Radius tokens in `ui/theme.py`: `radius` 8 px, `radius-sm` 6 px, `radius-pill` 4 px; Streamlit's
  widgets follow through `baseRadius` (`scripts/sync_theme.py`). Circles (avatars, dots) stay round.
- Option rows, chips, dropdowns and dates share one look: a 1 px edge, the small radius, 40 px high, the label above in
  small grey, the chosen option tinted with the accent; a row of controls lines up on its bottom edge and the date row
  wraps on a phone. One date control on every dated page (`ui/dates.py`).

## Look of 19 Nov 2026 (owner: "why can't we have such beautiful site", after paresh.streamlit.app)
- A white page; a section is a question set off by a strong rule (`rule-strong`), not a grey card; tables have no box,
  a strong rule under the head and hairlines between rows; KPI figures sit in one ruled strip.
- A serif (`display`, Source Serif 4) for the headline, the section questions and their one-line answers; Inter for
  everything else; tabular figures for numbers. Muted blue for links, muted green and rust for buying and selling.
- All in `ui/look.css`, loaded last, tokens only: no page code changed. Remove it from `CSS_FILES` to go back.

## One theme
- Every colour, font, type size, radius and spacing is a token in `streamlit_app/ui/theme.py`. The stylesheets
  (`ui/insiders.css`, `ui/table.css`, `ui/ds.css`) use `var(--token)` only; the charts read `theme.C`.
- Streamlit's widgets read `.streamlit/config.toml`; `python scripts/sync_theme.py` writes its `[theme]` from theme.py.
- `tests/test_theme.py` fails on a colour outside theme.py, a CSS variable that is not a token, or a config that drifted.

## Look (owner, 12 Nov 2026: "build it and make sure to have minimalist theme", after the Dribbble-style mock)
- ~~Soft white cards (18 px corners, no border, no shadow) on a light grey page~~ (white page and ruled sections
  since 19 Nov, corners from the radius tokens); generous padding.
- KPI cards: an icon only where the number has a direction (up, down, needs a look), a grey label, one big number, one grey line.
- Rows: an initials badge, the name and one grey line (who did what, when), the value and one chip on the right
  (the move since the trade, or the share of the company). The full sentence is on hover and on the topic pages.
- No paragraphs on a page: a section's explanation is its title's hover text; the measured record and what was left
  out are one or two small grey lines at the foot of the card.
- ~~Controls are pills~~ (outlined, 19 Nov, above). Inter for text, Geist Mono for codes; tabular figures.
- Green and red for buying and selling only; amber for "needs a look"; one indigo accent for links and the brand.

## Every page has the same shape (ui/ds.py)
1. **Head**: a small grey line (the date or what the page is), the headline with its numbers, at most one grey line.
2. **KPI cards**: the page's numbers, each a link to the page that lists them.
3. **Cards** (`ds.section` opens one; what follows goes in it), titled as questions or short names.
4. **Stories**: one decision each, with its 5W-2H in sight, no click and no arithmetic left to the reader:
   who, what, when (traded, made public, days between), where, how, how much (₹, % of the company, % of the person's own
   holding), price (paid, now, the move), why it matters (the measured record, or the published study, or the rule), and
   what to watch (pledge, surveillance flags, a late filing).
5. **Left out as noise**: what the page did not list, counted and summed (staff trades, ESOPs, gifts, transfers,
   small deals, market makers), so nothing is hidden and nothing trivial takes a row.

## Pages
The menu of 12 Nov (Today, Watchlist, Screener in sight; Money, Watch out, Research groups) was replaced on 13 Nov
(9 dense pages) and since 19-20 Nov reads: Dashboard (default), Today, Insiders, Funds, Deals, Stakes, Situations; More:
Results, Calendar, Filings, Companies, Investors, Data health. The 12 Nov pages stay at their addresses. The list with
the question each answers: `docs/PRODUCT.md`, Pages. None of them needs an AI model.

## Numbers and words
- Money `kit.rupees` (₹ x.xx Cr, ₹ x.xx L); prices `kit.price`; shares in Indian grouping; dates `19 Oct 2026`.
- "Big" is always a % of the company or of the person's own holding, not rupees alone.
- Sentences say what happened, active voice, with the number in them. Never our opinion: the "why" is a measured
  record, a cited study or a rule.
- A section with nothing to show says so in one line.
