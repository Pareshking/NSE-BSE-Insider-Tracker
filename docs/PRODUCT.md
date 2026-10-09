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
| What is still to do | `docs/TODO.md` |
| The site's code | `streamlit_app/README.md` |

## Purpose

A free, public, data-first site to help lakhs of small investors in Indian
equities decide, using NSE and BSE disclosures: spot a stock where insiders are putting real money in, and
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
   52-week high and 200-day average (pending the price join).
5. **Show what happened next**: returns after each kind of signal, measured
   from the broadcast time, after costs, with the number of cases (pending
   the backfill and the signal lab).
6. **Look ahead and warn**: board meetings to consider fund raising or a
   buyback, pledges, promoter selling, late filings.

## Decisions (with dates)

- **Data correctness first.** Data is cleaned once, in the nightly
  pipeline (`insiders_clean/`); the site never cleans. (07 Oct 2026)
- **Sources: NSE and BSE only.** Screener.in is not scraped: its
  robots.txt disallows the paginated URLs and its terms forbid copying or
  mirroring; it mostly re-presents exchange filings anyway. (07 Oct 2026)
- **Concall announcements are not collected**: they say nothing about
  buying or selling. (08 Oct 2026)
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
- **Design**: light canvas #F6F7F9, white cards with 14px corners, Geist
  with tabular figures, indigo #4F46E5 for anything clickable, green/red
  only for buying/selling, amber for "needs a look". Inspired by Paresh,
  not copied. (08 Oct 2026)
- **Storage**: every collected record kept once in `archive/`, clean
  tables rebuilt from it nightly; dated snapshots deletable once archived,
  but retention stays a dry run until the multi-year archive is stable.
  (08 Oct 2026)
- **History**: only the last one year (from about 08 Oct 2025); the site
  grows daily from there. NSE insider filings up to 02 May 2026 come from
  the backfill (NSE's new system starts 03 May 2026 and the nightly job
  covers it); bulk and block deals up to the first nightly record. Proceed
  with the data in hand; don't wait for all of it. (08 Oct 2026)
- **Audience: the public** (owner, 09 Oct 2026). The site is free and open
  to anyone; it is not a personal tool. Consequences: nothing personal is
  stored in the repo (it is public) or on the server; a watchlist, if built,
  lives in the reader's own browser.
- **Facts and measured evidence, not advice** (09 Oct 2026). The site shows
  what was disclosed, sized and cleaned, and what happened after similar
  filings with case counts. It does not tell readers to buy or sell, set
  targets or publish a portfolio to copy. HYPOTHESIS, to check with the SEBI
  (Research Analysts) Regulations, 2014 before anything like a model basket
  (TODO 10) is built: recommendations to the public may need registration.
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

| Page | Question it answers |
|---|---|
| Today | What did insiders and big money do in the latest session? High-conviction buys, session feed, what was held back |
| Screener | Which companies show insider accumulation or distribution now? One row per company, badges |
| Insider trades | Every filing, open-market by default; ESOP/off-market and pledges in their own tabs; late filings marked |
| Deals & big stakes | Bulk/block deals by real buyers and sellers, the most active buyers, SAST Reg 29 stake changes |
| Capital raises | Upcoming board meetings (fund raising, preferential, buyback), corporate actions |
| Track record | What happened after each signal (shows nothing until measured) |
| Data | What the last cleaning run removed, held back and could not place |
| Company `/company?symbol=` | Everything about one company on one page |
| Person or fund `/entity?id=` | Everything one insider or fund did, across companies |

Still to add (see `docs/TODO.md`): price chart with filings marked, price
context columns, morning brief and watchlist warnings, a public model
basket, the measured track record.

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
