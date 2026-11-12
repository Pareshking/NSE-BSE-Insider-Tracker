# Design standard (owner, 12 Nov 2026: redesign from blank)

"Flat, minimal and subtle colours across the theme is key for consistent design across pages. Use theme.py and bring
everything there so in future one line change would work across the website." Every page is checked against this list
before it merges.

## One theme
- Every colour, font, type size, radius and spacing is a token in `streamlit_app/ui/theme.py`. The stylesheets
  (`ui/insiders.css`, `ui/table.css`, `ui/ds.css`) use `var(--token)` only; the charts read `theme.C`.
- Streamlit's widgets read `.streamlit/config.toml`; `python scripts/sync_theme.py` writes its `[theme]` from theme.py.
- `tests/test_theme.py` fails on a colour outside theme.py, a CSS variable that is not a token, or a config that drifted.

## Look (owner, 12 Nov 2026: "build it and make sure to have minimalist theme", after the Dribbble-style mock)
- Soft white cards (18 px corners, no border, no shadow) on a light grey page; generous padding.
- KPI cards: an icon only where the number has a direction (up, down, needs a look), a grey label, one big number, one grey line.
- Rows: an initials badge, the name and one grey line (who did what, when), the value and one chip on the right
  (the move since the trade, or the share of the company). The full sentence is on hover and on the topic pages.
- No paragraphs on a page: a section's explanation is its title's hover text; the measured record and what was left
  out are one or two small grey lines at the foot of the card.
- Controls are pills (menu, period, filters, search). Inter for text, Geist Mono for codes; tabular figures.
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

## Pages (menu: three in sight, the rest in three groups)
- In sight: **Today** (the top of every page below), **Watchlist** (`?watch=A,B` or secrets; never stored), **Screener**
  (ready-made filters over the nightly company snapshot).
- Money: **Insiders**, **Deals**, **Raises**, **Holders**, **Sectors** (insider and fund money by sector), **Results**
  (results XBRL from 15 Oct 2026, the quarter before where held, insiders in the 30 days after, buys after the window
  reopened, exploratory).
- Watch out: **Risks** (pledges, cheap issues, red flags with every flag counted, lenders against promoter shares),
  **Calendar**.
- Research: **Companies**, **Investors**, **Evidence**, **Filings**. Data quality from the footer.
- None of them needs an AI model. The look (cards, colours) is parked for the owner's decision (12 Nov).

## Numbers and words
- Money `kit.rupees` (₹ x.xx Cr, ₹ x.xx L); prices `kit.price`; shares in Indian grouping; dates `19 Oct 2026`.
- "Big" is always a % of the company or of the person's own holding, not rupees alone.
- Sentences say what happened, active voice, with the number in them. Never our opinion: the "why" is a measured
  record, a cited study or a rule.
- A section with nothing to show says so in one line.
