# Design standard (owner, 21 Oct 2026)

The look of screener.in or Zerodha Kite: clean, minimal, corporate. Every page is checked
against this list before it merges. Tokens and rules live in `streamlit_app/ui/insiders.css`
and `ui/table.css`; pages never set their own colours, sizes or fonts.

## Layout
- A white top bar with four links (Today, Companies, Filings, Evidence) and a company search; no side menu
  on desktop (on a phone Streamlit's slide-out menu carries the same four links).
- The page uses the screen's width with 24 px gutters (12 px on a phone), as the owner's screener; cards are flat (1 px border, 8 px corners, no shadow).
- Filters: search and the main choice in sight, everything else in one "Filters & sort" popover. No CSV export.
- On a phone a table is a list of cards (each cell under its column's label); a tap anywhere on a row opens its facts.
- Links between pages stay in the session and change the address (ui/nav.py), so every company has its own URL.
- Two columns only where two things are compared or read together (the price chart and the money flow).

## Type
- One family: Geist; Geist Mono only for codes (NSE symbol, BSE code, ISIN).
- One scale: page title 24 px; section titles 12.5 px **uppercase**, letter-spaced; body 14 px; small 12.5 px;
  labels 11 px **uppercase**, letter-spaced.
- Titles say what the section is ("Worth a look", "Watch out", "Money in and out"); subtitles are one line.

## Numbers
- Tabular figures everywhere; numbers right-aligned in tables and stat rows.
- Money: `kit.rupees` (₹ x.xx Cr, ₹ x.xx L); prices `kit.price` (₹ 74.61); shares in Indian grouping
  (2,71,42,650); percentages with the unit (4.39%); dates `19 Oct 2026` (with the year in tables).
- "Big" is always a % of the company or of the person's own holding, not rupees alone.
- Green and red only for buying and selling (or up and down); amber only for "needs a look".

## Words
- No paragraph under a table or a list. A method note becomes a tag, a column help (hover) or one line.
- Sentences say what happened, active voice, with the number in them.
- Every signal shows its evidence status as a tag (ahead, behind, no edge, few cases, not measured).

## Alignment
- Repeated rows (ideas, tiles, table rows) share edges, baselines and padding; numbers line up in columns.
- A section with nothing to show says so in one line, or is not drawn; never an empty frame.
