# From data to pages

Pages are derived from the data, not the other way round (owner, 08 Oct 2026).
Step 1 lists every dataset, available or pending, with what it really holds.
Step 2 lists what each dataset (alone or joined) can tell an investor. Step 3
turns those answers into sections. Step 4 groups sections into pages by when
and why an investor opens them. A section is built only when its data is in;
until then it is listed here as pending, not replaced with something else.

Status: **In** = collected and cleaned; **Raw** = collected, not cleaned;
**Pending** = not collected yet (see `docs/TODO.md`).

## Step 1: datasets

| # | Dataset | Fields that matter | Coverage | Status |
|---|---|---|---|---|
| D1 | Insider trades (SEBI PIT) | person, role (19% blank), mode, side, shares, value, holding before/after, trade dates, intimation date (NSE; BSE from its insider CSV), broadcast time (BSE: day only) | NSE from 03 May 2026 nightly; BSE nightly (page capture + the last 10 days from BSE's insider CSV) | In |
| D1h | Insider trades, history | same, older names | NSE 08 Oct 2025 - 02 May 2026 (the one-year window); BSE from 08 Oct 2025 (BSE's insider CSV, `scripts/bse_history_backfill.py`) | NSE In (backfill 08 Oct); BSE coded 12 Oct, waits on the BSE History Backfill run |
| D2 | Bulk and block deals | client, side, shares, price, date, feed | NSE + BSE, 90-day window nightly | In |
| D2h | Bulk and block, history | same | NSE from 08 Oct 2025; nightly now reads the uncapped CSV. BSE from 08 Oct 2025 (`BulkDealData_ng`), and its last 10 days nightly | NSE In (backfill 08 Oct, redone 09 Oct); BSE coded 12 Oct, waits on the BSE History Backfill run |
| D3 | SAST Reg 29 | acquirer, promoter flag, 29(1)/29(2), action, mode, shares and % acquired/sold, stake after | NSE, from 07 Oct 2026 (10-day windows); BSE from 08 Oct 2025 (history run) and 30-day windows nightly, a disclosure on both shown once | NSE In; BSE coded 12 Oct |
| D4 | Corporate actions | purpose (buyback, bonus, split, rights, dividend), ex/record date, ratio, rights premium (NSE only), dividend | NSE, from 07 Oct 2026; BSE from 08 Oct 2025 (history run) and nightly, an action on both shown once | NSE In; BSE coded 12 Oct |
| D4b | Buybacks | tender offers: offer price, shares sought and tendered, offer dates (NSE tender-offer list, from 2015); open market: daily buyback reports (no price); matched to D4 by symbol and record date | NSE, nightly (12 Oct 2026) | In (open-market price only in PDFs) |
| D5 | Board meetings | meeting date, purposes (results, dividend, buyback, bonus, fund raising, split, rights, preferential) | NSE, up to 60 days ahead; past months by backfill (`--from`, from 01 Jul 2025) | In |
| D6 | Shareholding pattern | promoter %, public % (free float), employee trusts %, promoter pledged and encumbered shares (XBRL); promoter 0% as filed where a company has no promoter group | NSE, latest quarter of every company (TODO F) | In |
| D6m | Promoter-group members | every promoter and promoter-group member by name, sub-category (individual or HUF, body corporate, trust, government, foreign), shares, % (Table II of the same XBRL); insider filings linked by identity (`promoter_group_id`) | NSE; new filings nightly, latest quarter of every company after the catch-up | In (from 12 Oct 2026; catch-up run after merge) |
| D7 | Preferential issues | in-principle: board date, allottee category, consideration, amount; XBRL: instruments, securities proposed, ICDR minimum price and relevant date as filed, every proposed allottee; listing: offer price, shares allotted, allotment, listing and trading-approval dates; XBRL: filed lock-in lines | NSE latest 100 per stage a day as snapshots, plus every filing by date window from 12 Oct 2026 (NSE events job, history by a `--days 550` run); BSE has no amounts or prices | Clean (12 Oct, `insiders_clean/issues.py`); XBRL from the first issues run |
| D8 | Rights issues | in-principle: board date, amount, consideration; listing stage | as D7 (XBRL not read: it adds only the security type) | Clean (12 Oct) |
| D8q | QIPs | in-principle: board and shareholder approval dates, amount; listing: bid dates, relevant date, floor and issue price, discount, shares, allottee count, amount; XBRL: each allottee with category and % of the issue | NSE filings by date window (`corporate-further-issues-qip`, confirmed 12 Oct 2026) | Clean (12 Oct, `issues.clean_qip`) |
| D9 | Market cap | per symbol, daily | NSE PR file + BSE list | In |
| D10 | Securities | ISIN, NSE symbol, BSE code, name, sector, industry, size bucket | NSE/BSE lists nightly + VR export | In |
| D11 | Prices | daily OHLC, volume, value, prev close; split/bonus adjusted summary (close, 52-week high/low, 90/180-day change, size bucket) | NSE + BSE UDiFF bhavcopy from 1 Jan 2025, nightly; NSE daily market cap; Nifty 500 and other NSE index closes | In; not yet shown on pages (TODO G) |
| D12 | Trading calendar | NSE sessions, special sessions | from 30 Sep 2024, extends nightly | In |
| D13 | Measured outcomes | returns after each signal from broadcast time, after costs, with case counts | from D1h + D2h + D11 | Pending (TODO 7) |
| D15 | Tradability | NSE ASM / GSM / ESM stage, IBC code, trade for trade, SME, price band, circuit-locked days (20 sessions) | NSE, daily snapshots from 12 Oct 2026; series and circuit days from the bhavcopy | In (no suspended list: NSE's ends in 2012) |
| D16 | Announcements (Reg 30 and the rest) | subject, NSE one-line text / BSE category, subcategory and headline, attachment link and size, broadcast time, market (NSE main board, NSE SME, BSE) | NSE (both boards) and BSE, nightly 3 days and every 30 minutes for today; concalls not collected | Coded 13 Oct (PR #56), waits on merge |
| D16r | Announcement reads | per filing: category, values each with its quote and evidence (`exact` or `table`), values held back with the reason, second reader's agreement, reader and prompt version; read once across exchanges | useful groups of today and yesterday, companies of Rs 100 Cr and up | Live 14 Oct: Brief card "Filings read" (PR #56, #58, #59); page Filings read (`/filings`), filters by heading, period, exchange, size, search, 2 readers agree |
| D14 | Named-investor aliases | curated list mapping spellings of known investors and funds to one name | — | Pending (to add to TODO) |

## Step 2: what the data can answer

| Investor question | From | Status |
|---|---|---|
| Is this insider trade a real decision to buy or sell? | D1 mode and side | In |
| Is it big for this company? | D1 value with D9 (% of mcap), D6 (% of float), D1 holding change | In; % of float partial |
| Is one person building a position over weeks? | D1 per person, 30/90 days | In |
| Are several decision-makers buying together? | D1 roles, D6m (the promoter group counts once), 30 days | In |
| Is the buyer someone who trades every year at the same time (routine)? | D1h, 3 years per person | Pending (D1h) |
| Did they disclose on time? | D1 dates with D12 | In (NSE) |
| Who took the other side of a big sale, and was the seller a promoter? | D2 pairs with D1 roles | In |
| Which funds are accumulating, and in which small caps? | D2 without market makers, D9 | In |
| Is an outside fund or investor crossing 5% or adding 2%+? | D3 | In |
| Is the promoter borrowing against shares? Is it rising? | D6 pledge %; D1 pledge filings | Partial (D6 coverage) |
| Is the company about to raise money, buy back, split? | D5 | In |
| Did the insider buy as soon as the trading window reopened after results? | D1 with D5 results dates, D12 | In (marked; to be measured) |
| Did promoters get shares cheap or pay up? | D7 offer price with D11 (ICDR minimum, market price) | In vs the market price now; ICDR minimum pending (D11 VWAP) |
| When can preferential shares be sold (supply overhang)? | D7 trading-approval date + lock-in rule (promoters 18 months, others 6) | In, for allotments matched to their approval |

| Did promoters get shares cheap or pay up? | D7 offer price with the filed ICDR minimum, our VWAP estimate (D11) and the market price | In: filed minimum on matched allotments, our estimate where the relevant date is filed and 90 sessions are in D11 |
| Who gets the shares? | D7 In-Principle XBRL allottees | In (promoter status per allottee is not filed; the issue's category is shown) |
| When can preferential shares be sold (supply overhang)? | D7 filed lock-in lines, else the rule (promoters 18 months, others 6) from trading approval | In: filed lines for any allotment with a parsed XBRL; the rule for matched ones |
| Who bought a QIP, at what discount? | D8q | In |
| Rights issue terms and dates | D4 ratio/premium, D8 stages | D4 In, D8 pending |
| Buyback price vs market, tender or open market | D4b + D11 | In (tender price vs the market now; open-market price not in structured data) |
| Where is the price vs the 52-week high and 200-day average? What did the insider pay vs now? | D1 price with D11 | Pending (D11) |
| Has this kind of signal worked before? This person? This fund? | D13 | Pending |

## Step 3: sections (each from the answers above)

| Section | Built from | Status |
|---|---|---|
| S1 Open-market insider buys and sells, sized (% of mcap, % of float, holding change), tranches combined | D1, D9, D6 | In (float partial) |
| S2 Non-market filings archive (ESOP, gifts, transfers, preferential, schemes) | D1 | In |
| S3 Pledge filings | D1 | In |
| S4 Spotlight: one person 0.15%+ of mcap in 30 days | D1 | In |
| S5 Float absorbers: 0.5%+ in 90 days | D1 | In |
| S6 Clusters: 2+ decision-makers (the promoter group once, each director/KMP once) | D1, D6m | In |
| S7 Promoter selling | D1 | In |
| S8 Late filings, by X trading days, per step | D1, D12 | In (NSE) |
| S9 Handshakes: seller, absorbing buyers, promoter seller flag | D2, D1 | In |
| S10 Funds accumulating small caps | D2, D9 | In |
| S11 Fund / person footprint across companies | D1, D2 | In |
| S12 Outside 5% holders moving (SAST) | D3 | In |
| S13 Promoter holding and pledge, latest quarter and trend | D6 | Partial |
| S14 Upcoming catalysts: fund raising, preferential, buyback, bonus, split, results | D5 | In |
| S15 Corporate actions: rights (ratio, price), bonus, split, dividend, buyback (price vs market, route) | D4, D4b, D11 | In |
| S25 Window-open buys: open-market buys in the first 5 sessions after the trading window reopened | D1, D5, D12 | In (mark and filter on Insider trades, Company timeline) |
| S16 Preferential pipeline: announced, approved, allotted, listed; promoter or not; amount | D7 | In (NSE; allottee and amount only where the allotment is matched to its approval) |
| S17 Preferential price vs ICDR minimum and market | D7, D11 | In vs the market price now; ICDR minimum pending (needs VWAP) |
| S18 Lock-in expiry calendar | D7 | In (matched records only; promoters 18 months, others 6, from trading approval) |

| S15 Corporate actions: rights (ratio, price), bonus, split, dividend, buyback | D4 | In |
| S16 Preferential pipeline: announced, approved, allotted, listed; promoter or not; amount; proposed allottees | D7 | In (NSE; allottee category, amount and filed minimum only where the allotment is matched to its approval) |
| S17 Preferential price vs ICDR minimum and market | D7, D11 | In: filed minimum, our 90/10-session VWAP estimate beside it (labelled), market price now |
| S18 Lock-in expiry calendar | D7 | In: filed lock-in lines where the listing XBRL has them, the rule (promoters 18 months, others 6) on matched records otherwise, labelled |
| S18q QIPs: approvals, allotments (issue vs floor price, discount, amount), allottees by category | D8q | In (Capital raises page; not yet on the Company page) |
| S19 Price context: CMP vs 52W high and 200-day average, price paid vs today | D1, D11 | Pending |
| S20 Price chart with filings marked at broadcast date | D11, D1-D5 | Pending |
| S21 Track record by signal, person and fund | D13 | Pending |
| S22 Data health: removed, held back, unmatched, calendar | cleaning report | In |
| S23 Held back for a look, with reasons | D1 flags | In |
| S24 Named-investor tracking | D2, D3, D14 | Pending |
| S25 Tradability badges: amber flags under the company name on Screener, Actions, Latest session and Company; a column for signals, never a filter | D15 | In |

## Step 4: pages, grouped by when and why an investor opens them

| Page | Why it is opened | Sections |
|---|---|---|
| Today | Every morning: what happened in the last session | S1 (session), S4 crossed today, S6 formed today, S9 (session), S12 (session), S14 (next days), S23 |
| Screener | Looking for ideas: which companies show accumulation now | One row per company combining S1, S4, S5, S6, S7, S13 badges; S19 columns when D11 is in |
| Insider trades | Checking filings in detail | S1, S2, S3, S8, S25 |
| Deals & stakes | Following institutional money | S9, S10, S12, S24 later |
| Capital raises | Dilution and funding terms | S14, S15, S16-S18, S18q |
| Company | Deciding on one stock | S1, S7, S9, S12, S13, S14, S15, S16, S19, S20 for that company, one timeline |
| Person or fund | Judging who is buying | S11, S21 for that name |
| Track record | Trusting a signal | S21 |
| Data | Trusting the numbers | S22 |

## What this changes

- Today gains S12 (outside 5% holders) and S14 (catalysts in the next days):
  both are in, and neither was on the page.
- Capital raises waits for D7/D8 cleaning for its core (S16-S18); until then
  it shows S14 and S15 and states that the pipeline is pending.
- Cleaning D7/D8 (TODO 11) moves up: it unlocks three sections, and its data
  (offer price, allotment and trading-approval dates) is already collected.
- Shareholding coverage (TODO 5) moves up: % of float and pledge appear on
  four pages.

## Data the card context needs (16 Oct; design in `docs/ANNOUNCEMENT_READER.md`)

| Context | Data | Source | State |
|---|---|---|---|
| Size against revenue, growth, margins | Quarterly results, 12 quarters | NSE integrated-filing XBRL (Ind AS); banks, NBFCs, insurers and BSE-only companies still to do | Partial (one year) |
| Debt before and after, net worth, cash | Balance sheet lines with their dates | The same XBRL | Not extracted |
| Dilution, warrants | Shares outstanding, outstanding warrants and convertibles | Shareholding XBRL; preferential in-principle XBRL | Shares yes; convertibles not checked |
| Discount or premium to market | Price, market cap, volume-weighted reference price | Our price layer | Have (BSE-only names have no market cap) |
| Order book, capacity, ratings over time | Ledger of earlier cards | The reader's own cards | Not built |
| Management commentary, guidance | Concall transcripts, presentations | Exchange filings (archived since 15 Oct, text cached) | Collected, not read |
| Subsidiaries, segments, risks | Annual reports | Source not probed | Not collected |
