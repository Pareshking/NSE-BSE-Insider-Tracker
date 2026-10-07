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
| D1 | Insider trades (SEBI PIT) | person, role (19% blank), mode, side, shares, value, holding before/after, trade dates, intimation date (NSE only), broadcast time | NSE from 03 May 2026 nightly; BSE nightly (no intimation date) | In |
| D1h | Insider trades, history | same, older names | NSE 19 Nov 2015 - 02 May 2026 | Pending (PR 2 runner ready) |
| D2 | Bulk and block deals | client, side, shares, price, date, feed | NSE + BSE, 90-day window nightly | In |
| D2h | Bulk and block, history | same | NSE bulk 2004-, block Nov 2005- | Pending (PR 2) |
| D3 | SAST Reg 29 | acquirer, promoter flag, 29(1)/29(2), action, mode, shares and % acquired/sold, stake after | NSE, from 07 Oct 2026 (10-day windows) | In |
| D4 | Corporate actions | purpose (buyback, bonus, split, rights, dividend), ex/record date, ratio, rights premium, dividend | NSE, from 07 Oct 2026 | In (buyback price and route missing) |
| D5 | Board meetings | meeting date, purposes (results, dividend, buyback, bonus, fund raising, split, rights, preferential) | NSE, up to 60 days ahead | In |
| D6 | Shareholding pattern | promoter %, public % (free float), employee trusts %, promoter pledged and encumbered shares (XBRL) | NSE; only filings of the last 10 days so far | In, partial (TODO 5) |
| D7 | Preferential issues | in-principle: board date, allottee category, consideration, amount; listing: offer price, shares allotted, allotment date, listing and trading-approval dates, XBRL | NSE latest 100 per stage; history from May 2023; BSE stages | Raw (TODO 11) |
| D8 | Rights issues | in-principle: board date, amount, consideration; listing stage | as D7 | Raw (TODO 11) |
| D9 | Market cap | per symbol, daily | NSE PR file + BSE list | In |
| D10 | Securities | ISIN, NSE symbol, BSE code, name, sector, industry, size bucket | NSE/BSE lists nightly + VR export | In |
| D11 | Prices | adjusted daily close and volume | Paresh R2, NSE since 2010 | Pending (TODO 6; needs a read-only R2 token) |
| D12 | Trading calendar | NSE sessions, special sessions | from 30 Sep 2024, extends nightly | In |
| D13 | Measured outcomes | returns after each signal from broadcast time, after costs, with case counts | from D1h + D2h + D11 | Pending (TODO 7) |
| D14 | Named-investor aliases | curated list mapping spellings of known investors and funds to one name | — | Pending (to add to TODO) |

## Step 2: what the data can answer

| Investor question | From | Status |
|---|---|---|
| Is this insider trade a real decision to buy or sell? | D1 mode and side | In |
| Is it big for this company? | D1 value with D9 (% of mcap), D6 (% of float), D1 holding change | In; % of float partial |
| Is one person building a position over weeks? | D1 per person, 30/90 days | In |
| Are several decision-makers buying together? | D1 roles and families, 30 days | In |
| Is the buyer someone who trades every year at the same time (routine)? | D1h, 3 years per person | Pending (D1h) |
| Did they disclose on time? | D1 dates with D12 | In (NSE) |
| Who took the other side of a big sale, and was the seller a promoter? | D2 pairs with D1 roles | In |
| Which funds are accumulating, and in which small caps? | D2 without market makers, D9 | In |
| Is an outside fund or investor crossing 5% or adding 2%+? | D3 | In |
| Is the promoter borrowing against shares? Is it rising? | D6 pledge %; D1 pledge filings | Partial (D6 coverage) |
| Is the company about to raise money, buy back, split? | D5 | In |
| Did promoters get shares cheap or pay up? | D7 offer price with D11 (ICDR minimum, market price) | Pending (D7 clean, D11) |
| When can preferential shares be sold (supply overhang)? | D7 trading-approval date + lock-in rule (promoters 18 months, others 6) | Pending (D7 clean) |
| Rights issue terms and dates | D4 ratio/premium, D8 stages | D4 In, D8 pending |
| Buyback price vs market, tender or open market | D4 + offer documents + D11 | Pending |
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
| S6 Clusters: 2+ buyers incl. an officer or separate families | D1 | In |
| S7 Promoter selling | D1 | In |
| S8 Late filings, by X trading days, per step | D1, D12 | In (NSE) |
| S9 Handshakes: seller, absorbing buyers, promoter seller flag | D2, D1 | In |
| S10 Funds accumulating small caps | D2, D9 | In |
| S11 Fund / person footprint across companies | D1, D2 | In |
| S12 Outside 5% holders moving (SAST) | D3 | In |
| S13 Promoter holding and pledge, latest quarter and trend | D6 | Partial |
| S14 Upcoming catalysts: fund raising, preferential, buyback, bonus, split, results | D5 | In |
| S15 Corporate actions: rights (ratio, price), bonus, split, dividend, buyback | D4 | In |
| S16 Preferential pipeline: announced, approved, allotted, listed; promoter or not; amount | D7 | Pending |
| S17 Preferential price vs ICDR minimum and market | D7, D11 | Pending |
| S18 Lock-in expiry calendar | D7 | Pending |
| S19 Price context: CMP vs 52W high and 200-day average, price paid vs today | D1, D11 | Pending |
| S20 Price chart with filings marked at broadcast date | D11, D1-D5 | Pending |
| S21 Track record by signal, person and fund | D13 | Pending |
| S22 Data health: removed, held back, unmatched, calendar | cleaning report | In |
| S23 Held back for a look, with reasons | D1 flags | In |
| S24 Named-investor tracking | D2, D3, D14 | Pending |

## Step 4: pages, grouped by when and why an investor opens them

| Page | Why it is opened | Sections |
|---|---|---|
| Today | Every morning: what happened in the last session | S1 (session), S4 crossed today, S6 formed today, S9 (session), S12 (session), S14 (next days), S23 |
| Screener | Looking for ideas: which companies show accumulation now | One row per company combining S1, S4, S5, S6, S7, S13 badges; S19 columns when D11 is in |
| Insider trades | Checking filings in detail | S1, S2, S3, S8 |
| Deals & stakes | Following institutional money | S9, S10, S12, S24 later |
| Capital raises | Dilution and funding terms | S14, S15, S16-S18 when D7 is clean |
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
