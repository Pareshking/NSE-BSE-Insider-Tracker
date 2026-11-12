# Design standard (owner, 12 Nov 2026: redesign from blank)

"Flat, minimal and subtle colours across the theme is key for consistent design across pages. Use theme.py and bring
everything there so in future one line change would work across the website." Every page is checked against this list
before it merges.

## One theme
- Every colour, font, type size, radius and spacing is a token in `streamlit_app/ui/theme.py`. The stylesheets
  (`ui/insiders.css`, `ui/table.css`, `ui/ds.css`) use `var(--token)` only; the charts read `theme.C`.
- Streamlit's widgets read `.streamlit/config.toml`; `python scripts/sync_theme.py` writes its `[theme]` from theme.py.
- `tests/test_theme.py` fails on a colour outside theme.py, a CSS variable that is not a token, or a config that drifted.

## Look
- Flat: no boxes, no shadows. Hairlines between rows, one dark rule above each section, type contrast for hierarchy.
- Warm-neutral page, near-black ink, one muted steel-blue accent for links and the selected control.
- Muted green and red for buying and selling only; muted amber for "needs a look". Tints for backgrounds only.
- One family, Geist; Geist Mono for codes (symbol, BSE code, ISIN). Tabular figures everywhere.

## Every page has the same shape (ui/ds.py)
1. **Masthead**: a kicker (what and which period), the headline is the news with its numbers, one or two lines under it.
2. **Stat strip**: the page's numbers, each a link to the page that lists them.
3. **Sections titled as questions** ("Who is buying?"), each with one line under it.
4. **Stories**: one decision each, with its 5W-2H in sight, no click and no arithmetic left to the reader:
   who, what, when (traded, made public, days between), where, how, how much (₹, % of the company, % of the person's own
   holding), price (paid, now, the move), why it matters (the measured record, or the published study, or the rule), and
   what to watch (pledge, surveillance flags, a late filing).
5. **Left out as noise**: what the page did not list, counted and summed (staff trades, ESOPs, gifts, transfers,
   small deals, market makers), so nothing is hidden and nothing trivial takes a row.

## Pages
Today (the top of every page below), Insiders, Deals, Raises, Risks, Holders, Calendar, Companies (list and one
company), Investors, Evidence, Filings (every filing, for audit). Data quality from the footer.

## Numbers and words
- Money `kit.rupees` (₹ x.xx Cr, ₹ x.xx L); prices `kit.price`; shares in Indian grouping; dates `19 Oct 2026`.
- "Big" is always a % of the company or of the person's own holding, not rupees alone.
- Sentences say what happened, active voice, with the number in them. Never our opinion: the "why" is a measured
  record, a cited study or a rule.
- A section with nothing to show says so in one line.
