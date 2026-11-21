# Insiders: what the site is for, and what has been decided

> **Site history.** The demo that ran at insiders.streamlit.app until
> October 2026 (the old `streamlit_app/views/` pages) was wrong at multiple
> levels. A second app merged on 09 Oct 2026 (PRs #15/#16) re-used those
> demo pages and was set aside the same day (owner); its useful data work was
> kept (raw layer, uncapped deals CSV, NSE revision markers, filing links,
> the price layer). The site now live is the one built from
> `docs/DATA_TO_PAGES.md` (PR #17).

This replaces the earlier frontend specification, UI blueprint and analytics
plan, which described pages the owner found not useful for decisions. Those
pages are gone (October 2026); this page and the documents it links are the
current source of truth.

| Topic | Document |
|---|---|
| Signal definitions and thresholds | `docs/SIGNALS.md` |
| Cleaning rules, storage, calendar | `docs/CLEAN_LAYER.md` |
| Every clean table and its columns | `docs/DATA_DICTIONARY.md` |
| What is still to do | `docs/TODO.md` (history to 20 Nov 2026: `docs/TODO_DONE.md`) |
| Pages and the tables behind them | `docs/DATA_TO_PAGES.md` |
| Look and theme | `docs/DESIGN.md` |
| The site's code | `streamlit_app/README.md` |

## Purpose

A data-first research tool that helps a small investor in Indian equities
decide, using NSE and BSE disclosures: spot a stock where insiders are putting real money in, and
avoid traps. NSE and BSE already publish every row for free, so a copy of
their tables is worth nothing. The site earns its place only by what a
reader can't get by scrolling the exchange pages:

1. **Size it**: every trade as a % of market cap and as a change in the
   person's own holding, not just rupees.
2. **Take out the noise**: ESOPs, gifts, inter-se transfers, pledges,
   schemes, preferential allotments and offers for sale are filed like
   buying but are not decisions to buy. Only open-market trades count.
3. **Connect it**: one person's many small buys are one decision; several
   insiders buying together is a cluster; a fund's footprint across stocks.
4. **Put the price next to it**: price paid vs today, distance from the
   52-week high and 200-day average, from our own NSE/BSE price layer.
5. **Show what happened next**: returns after each kind of signal, measured
   from the broadcast time, after costs, with the number of cases (Track
   record, measured nightly; a forward record that is never edited).
6. **Look ahead and warn**: board meetings to consider fund raising or a
   buyback, pledges, promoter selling, late filings.

## Decisions (with dates)

- **Raw retention: nothing deleted by age; every raw line also in the database** (owner, 21 Nov 2026). Raw answers
  in `raw_v2/` are not deleted because they are old; from now on every line a source sent must also be in the
  database (our tables), not only the lines a page uses today. The Raw coverage audit (`scripts/raw_coverage.py`,
  `docs/CLEAN_LAYER.md`) decides what may ever be deleted: only a dataset it finds fully captured, read whole and not
  from a sample. On 21 Nov the audit found 5 of 83 datasets fully captured
  (`docs/TODO.md`). Not yet matched by the code: the weekly Storage trim still deletes some raw by age (TODO 1).

- **Speed: parallel requests only to hosts that are slow to answer** (owner, Nov 2026, with the speed fixes
  #315-#318, after the BSE speed test of PR #313, 20 Nov). A host that is slow to answer but not slow to allow (BSE:
  3.5 s an answer one at a time, 0.13 s four at a time, 40 of 40 answered) is asked by at most 4 clients side by side, each with its own session and a 1-2 s pause;
  the first refusal (401/403/429) stops them all for the run, with no retry around it. NSE is never asked in
  parallel. Our own bucket (R2) and separate sites (one fund house each) are not covered by the limit: raw flush runs
  16 at a time, fund houses side by side with each house's own requests sequential (#317). In code:
  `scripts/industry.py` `BSE_WORKERS`, `collectors/bse/events.py` `XBRL_WORKERS`, `scripts/filing_text_extract.py`
  `PER_HOST` (TODO 10: it does not exempt NSE's archive host).

- **Filed demergers are adjusted at the ex-date close** (owner directive, 20 Nov 2026; it reverses "splits and bonuses
  only" for demergers): a demerger filed on NSE (`Demerger`) or BSE (`Spin Off`) is applied to the price line at the
  exchange's own base price where it reset one, else at ex-date close / previous close when that move is over 5%.
  The factor takes in the day's trading move too; the directive is the close. A scheme of arrangement or amalgamation is
  applied only where the exchange reset the base price (none did in the product window); a capital reduction is not
  adjusted (`docs/CLEAN_LAYER.md`, Price adjustment).

- **No pill shapes; one look for every control** (owner, 19 Nov 2026, #300: "Remove such large pill shapes from
  everywhere"; the grey pill around a label and its options "looked old"). Radius tokens `radius` 8 px, `radius-sm`
  6 px, `radius-pill` 4 px in `streamlit_app/ui/theme.py`; Streamlit's widgets follow through `baseRadius`
  (`scripts/sync_theme.py`). Option rows, chips, dropdowns and dates share one outlined 40 px look, the label above in
  small grey, the chosen option tinted with the accent. Circles (avatars, dots) stay round.

- **A dashboard first** (owner, 19 Nov 2026: "Why don't we have a beautiful dashboard?"): the Dashboard is the default
  page and first in the bar; Today stays as it is.

- **A date control on every dated page** (owner, 19 Nov 2026: "A date selector or a date range selector must be
  present on required pages"): presets and a custom range (`streamlit_app/ui/dates.py`), clamped to the data and to the
  product window, kept in the page address.

- **Company page is a decision page** (owner, 19 Nov 2026: "Completely useless design and not glance-worthy to take even a
  decision"): it answers "is smart money accumulating or leaving, and is anything wrong?" in one sentence at the top, built
  from chips that each name their window and evidence status (insiders 90 days, mutual funds at the month end, FPI and DII
  this quarter, deals, red flags); then the price with every decision marked, the checks as a scorecard, the ownership
  mix and the fund houses as charts, the business quarter by quarter, and the detail below. Logic in
  `streamlit_app/screens/company_glance.py`, tested in `tests/test_company_page.py`.

- **Redesign from blank** (owner, 12 Nov 2026): more pages, each one question (Insiders, Deals, Raises, Risks, Holders,
  Calendar beside Companies, Investors, Evidence, Filings); every item a 5W-2H story with the arithmetic done; noise
  (staff trades, ESOPs, gifts, transfers, small deals) clubbed and counted, not listed; fewer clicks; flat, minimal,
  subtle colours from one theme file (`docs/DESIGN.md`). Updates stay on the site (no email or messages, as on 12 Oct).

- **AI filing cards off; XBRL first** (owner, 21 Oct 2026): the AI announcement reader is
  stopped (workflows `announcement-reader`, `announcement-three-filing-sample`, `ai-health-check`
  disabled) and its cards are off the site (Filings read page, Morning brief section); the code,
  workflows and tables are kept for later. Numbers come from the exchanges' XBRL wherever it is filed.

- **One front page of actions, evidence beside each list** (owner, 12 Oct 2026:
  "clutter free website giving value to right signal"). The menu is three
  groups. A signal leads only if the measured record supports it: on 12 Oct
  clusters and promoter buys beat Nifty 500 so far, one person buying 0.15% of
  market cap showed no edge, and promoter sales and funds' small-cap net buys
  lagged it (`docs/SIGNALS.md`, Track record). Placeholders for data we do not
  have are not drawn.

- **Data correctness first.** Data is cleaned once, in the nightly
  pipeline (`insiders_clean/`); the site never cleans. (07 Oct 2026)
- **Sources: official disclosures beyond the exchanges** (owner, 19 Nov 2026: "find the data sources and have it", "don't
  restrict yourself to only mutual funds"): besides NSE and BSE, the official publishers of mandated disclosures are read
  directly: fund houses' month-end portfolios (SEBI rule, linked from AMFI), NPS pension funds' portfolios, NSDL's FPI
  reports, SEBI's mutual fund trends. Third-party re-packagers (Screener, Trendlyne, Value Research) stay out, as below.
  Aggregates with no stock (PMS monthly reports, AIF statistics, P-notes) are not collected: nothing per stock to act on.
- ~~**Sources: NSE and BSE only.**~~ (07 Oct 2026, widened 19 Nov above) Screener.in is not scraped: its
  robots.txt disallows the paginated URLs and its terms forbid copying or
  mirroring; it mostly re-presents exchange filings anyway. (07 Oct 2026)
- ~~Concall announcements are not collected~~ **Everything is captured from now on** (owner, 15 Oct 2026):
  quarterly results, conference calls and other filings, structured data (XBRL) first where the exchange
  files it. Results come from NSE's integrated-filing XBRL, read without a model (`docs/DATA_DICTIONARY.md`,
  results). Replaces the 08 Oct decision that concall announcements say nothing about buying or selling.
- **Never half a document** (owner, 15 Oct 2026: "half information is more poisonous for financial disaster"): a filing is read in
  full or shown as not read, with the reason; nothing is summarised from a part, and the pages say how many filings of the
  period were read in full and why the others were not.
- **Evidence decides what gets ranked.** A signal is shown as a fact until
  the signal lab has measured it on our own history. (07 Oct 2026)
- **No star or conviction score.** Factor badges only (Spotlight, Float
  absorber, Cluster, Promoter selling, High pledge). (07 Oct 2026)
- **Price context is neutral**: "-14% from 52W high", no "falling knife" or
  "breakout" labels; the lab measures both. (07 Oct 2026)
- **Market makers excluded** from deal signals (32 clients made 60% of
  bulk/block legs, buying and selling in equal measure). (07 Oct 2026)
- **Token buys** (under Rs.25 lakh in companies above Rs.5,000 Cr) are
  labelled and never ranked. (07 Oct 2026)
- **Copying "ace investor" bulk deals is not presented as a buy list**:
  studies find prices run up before such deals and give back from day two.
- **Streamlit stays**; two sister sites (this and paresh.streamlit.app),
  same family of design, each its own. (07 Oct 2026)
- ~~**Design**: light canvas #F6F7F9, white cards with 14px corners, Geist
  with tabular figures, indigo #4F46E5 for anything clickable, green/red
  only for buying/selling, amber for "needs a look". Inspired by Paresh,
  not copied. (08 Oct 2026)~~ Replaced by the theme file (12 Nov), the look of 19 Nov (`docs/DESIGN.md`) and the
  radius tokens above (19 Nov).
- **Storage**: every collected record kept once in `archive/`, clean
  tables rebuilt from it nightly; dated snapshots deletable once archived,
  but retention stays a dry run until the multi-year archive is stable.
  (08 Oct 2026) Since then: the dated `raw/` and `canonical/` snapshots older than 14 days were deleted
  once by hand (owner, 14 Nov: "Delete it"); raw results XBRL and filing text were deleted and raw text gzipped on 15 Nov
  (owner: "bring it to 1 GB or less"; 11.9 GB to 3.53 GB; 2.29 GB on 21 Nov 2026); raw retention as decided on 21 Nov above.
- **History**: only the last one year (from about 08 Oct 2025); the site
  grows daily from there. NSE insider filings up to 02 May 2026 come from
  the backfill (NSE's new system starts 03 May 2026 and the nightly job
  covers it); bulk and block deals up to the first nightly record. Proceed
  with the data in hand; don't wait for all of it. (08 Oct 2026)
- **Study universe: Rs 100 Cr market cap and up** (owner, 12 Oct 2026: about 30%
  of listed companies are ones the owner will never invest in or study). Collection
  and raw stay complete; the clean step writes `clean/current/universe.parquet` and
  the site cuts every table to it on read; the track record, forward record and
  basket use the same list, by latest market cap (owner, 18 Oct)
  (`insiders_clean/universe.py`).
- **Morning brief is a page on the site** (owner, 12 Oct 2026): no email or
  messages; the watchlist comes from Streamlit secrets or the page address.
- **Audience: the owner's own research tool** (owner, 09 Oct 2026). It runs
  on Streamlit Community Cloud, sized for one reader, not for heavy public
  traffic. The repo is public, so nothing personal (holdings, watchlists)
  is committed; a watchlist lives in Streamlit secrets or the browser.
- **Actionable, with evidence status.** Ranked candidates, plain labels and
  risk flags, no generic disclaimers; every label says whether it is
  measured on our data, supported by studies only, or exploratory.
- **Timing rules for every return we show** (from the 09 Oct brief, adopted):
  the clock starts at the exchange broadcast time, never the trade date or
  the insider's price. Entry is the first price a reader could have traded:
  that session's close for a filing broadcast well before the close,
  otherwise the next session's open; the next session's close is reported as
  the cautious variant. Nothing published after the broadcast may feed a
  signal; tests enforce it. Count only complete windows; show the number of
  cases beside every figure; deduct costs.
- **Every number traces to its filing.** Insider rows carry the NSE filing
  link (`source_url`); deals have no per-record link and the page says so.
- **Evidence status on every signal**: measured on our data / supported by
  published studies but not measured here / exploratory / did not work.
  The 09 Oct research run (no edge in Jan-Jun 2026, against Nifty 500) is not
  used: its benchmark was judged unsuitable for small caps by its own review.
- **Show how far the price has moved since the broadcast**, so a reader
  sees whether the news is already in the price.
- **Phone first**: every page works at phone width.

## Pages

As on `main`, 21 Nov 2026 (`streamlit_app/app.py`). The tables behind each: `docs/DATA_TO_PAGES.md`, "The site on
21 Nov 2026".

| Page | Question it answers |
|---|---|
| Dashboard (default, first in the bar, 19 Nov) | Who is buying what, and should I look? Insider net, FPI, DII, mutual funds, bulk/block deals, results profit up, SAST crossings as KPI cards; monthly flows; where insiders and funds agree; insider buying leaders; funds bought and sold; FPI sectors; the next 7 days |
| Today `/today` | What happened on one day (a past day can be picked), as questions and answers, with the market's flows in one line |
| Insiders | Which decision-makers bought or sold in the open market, sized as % of the company and × a day's trading |
| Funds | What mutual funds and NPS pension funds bought and sold at the month end, house by house and scheme by scheme, by size and industry |
| Deals | Bulk and block deals by real buyers and sellers, both sides of a block as one deal |
| Stakes | SAST crossings and pledges (netted per day, rollovers marked) |
| Situations | Tender offers you can tender into (spread against the last close), and capital raised: rights, QIPs, preferential listings |
| Results (More) | One financial-year quarter: who reported, revenue and profit year on year, by size and industry |
| Calendar (More) | What is ahead: board meetings on fund raising or buybacks, tender windows closing, lock-ins ending, record dates |
| Filings (More) | Every filing and deal, by day if wanted |
| Companies `/company?symbol=` (More) | A decision page: is smart money accumulating or leaving, and is anything wrong? |
| Investors (More) | Every mutual fund and large investor in deals, each a link |
| Data health (More) | Each source's last fetch, rows, removed and held back, NSE's own counts |
| People & funds `/entity?id=` (hidden) | Everything one insider or fund did, across companies |
| Data quality `/data` (footer) | What the last cleaning run removed, held back and could not place |

Out of the menu since 13 Nov, still at their addresses: Watchlist, Screener, Raises, Holders, Sectors, Risks, Investor
flows, Evidence (track record). Old addresses (`/brief`, `/actions`, `/filings` ...) redirect (`app.py` `MOVED`).

## What the research found (leads, not proof)

Gathered 07 Oct 2026; Indian evidence is mostly working papers, and no
Indian study measures returns from the broadcast time, which is why the
signal lab matters most.

- Stronger: open-market buys by promoters/directors who don't trade on a
  fixed yearly pattern (Cohen, Malloy & Pomorski 2012; Indian promoter
  evidence in Krishnan & Rangan 2016); insider buying in small companies
  (Lakonishok & Lee 2001); preferential allotments to promoters at or above
  market price (Anshuman, Panchapagesan & Subrahmanyam 2019).
- US only so far: cluster buying (Alldredge & Blank 2019).
- Avoid flags: preferential allotments below market (-8.6% around the
  event, same Indian study); pledges as a crash-risk filter (Kalia 2024).
- Weak or negative: copying bulk-deal "ace investors" (Rajvanshi, IIM
  Calcutta WP 863); routine/ESOP/gift trades; SME-board promoter buying
  (manipulation concerns).
- Practical: about 0.25% per round trip in costs at a zero-brokerage
  broker; exclude ASM/GSM and 5%-band stocks; spread across many small
  positions held 3-12 months.

## Decisions of 16 Oct 2026 (owner)

- **A card tells what the event means for this company**, not only what the filing says: relative size, before
  and after, growth, dilution, price against the market. Built by a context engine from our own tables
  (`docs/ANNOUNCEMENT_READER.md`, "Context on the card"); facts, calculations and interpretations are shown apart;
  missing data is never shown as zero; every comparison shows its dates; promoter holding appears only where it
  belongs (insider trades, fundraising where promoters take part), not on a deal or an order.
- **Collect concalls and annual reports**, and let management's own words enter the card as quoted, dated facts,
  never as our opinion. The model writes no "why it matters" or risks of its own.
- **Titles are short and carry the news**: "Ujjivan SFB approves ₹409 Cr preferential issue" with a subtitle.
- **The reader runs in supervised batches of 100, each card audited against its filing, until at least 1,000
  cards**; it is not left on a schedule before a batch audits clean or close to it.
