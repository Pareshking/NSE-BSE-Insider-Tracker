# Data inventory (23 Oct 2026)

Every dataset we collect, what it holds in one line, and what it is for. Written as the
starting point of the next revamp. Built from `docs/DATA_DICTIONARY.md`,
`docs/DATA_TO_PAGES.md`, the collectors and the nightly jobs; R2 was not opened, so no row
counts. Column-level detail stays in `docs/DATA_DICTIONARY.md`.

## A. Trading by insiders and investors

| # | Data | What we get | Use |
|---|---|---|---|
| 1 | Insider trades (SEBI PIT, NSE and BSE) | Person, role, buy or sell, mode, shares, value, price, holdings before and after, trade dates, filing time, source link. From 8 Oct 2025. | Insider buys and sells sized against the company; pledges and gifts kept apart from market trades. |
| 2 | Bulk and block deals (NSE and BSE) | Client, buy or sell, shares, price, date, exchange; same-day round trips dropped. | Which funds and investors are accumulating. |
| 3 | Deal participant types (derived from names) | Mutual fund, insurer, foreign investor, PMS/AIF, market maker, promoter and so on, with a confidence level, plus a grouped investor name. | Tell funds from market makers and promoters. |
| 4 | SAST Reg 29 (NSE and BSE) | Acquirer, promoter or not, Reg 29(1) or 29(2), buy or sell, mode, shares and % moved, stake after. | Outside holders crossing 5% or moving 2% or more. |
| 5 | SAST Reg 31 encumbrances (NSE, from 22 Oct) | A promoter's pledge, non-disposal undertaking or other encumbrance: created, released or invoked, lender, shares, %. | Who lent against the promoter's shares, and whether it is rising. |

## B. Corporate events

| # | Data | What we get | Use |
|---|---|---|---|
| 6 | Corporate actions (NSE and BSE) | Buyback, bonus, split, rights, dividend: ex-date, record date, ratio, rights price, dividend per share. | Price adjustment, rights terms, what is coming. |
| 7 | Board meetings (NSE and BSE, up to 60 days ahead) | Date and purpose: results, dividend, buyback, bonus, fund raising, split, rights, preferential. | Upcoming catalysts; dates the trading window after results. |
| 8 | Tender offers (NSE, since 2015) | Buyback, takeover and delisting offers: price, shares sought and tendered, open and close dates, status. | Tender buyback price against market. |
| 9 | Daily buyback reports (NSE) | Which companies buy back on the open market each day, as free text with no number. | Spot open-market buybacks; the maximum price is only in the PDFs. |
| 10 | Buybacks (derived from 6, 8, 9) | One row per buyback with route (tender or open market), price, size, dates. | One buyback view. |
| 11 | Results (NSE integrated filing XBRL, from 15 Oct) | Quarter and year-to-date revenue, income, expenses, profit, EPS; audited or not; consolidated or not; revisions. | Size of a company's business behind an announcement. |

## C. Ownership

| # | Data | What we get | Use |
|---|---|---|---|
| 12 | Shareholding pattern (NSE, and BSE-only companies) | Per company and quarter: promoter %, public %, pledged and encumbered shares, ownership by investor type (MF, FPI, insurers, retail and others) from the XBRL. | Promoter holding and pledge trend; who owns the company. |
| 13 | Promoter-group members (same XBRL) | Every promoter-group member by name, category, shares, %, pledged. | Count one family once in clusters; link insider filings to the group. |

## D. Capital raises

| # | Data | What we get | Use |
|---|---|---|---|
| 14 | Preferential issues (NSE) | Approval (board date, amount, category, instruments, ICDR minimum price) and listing (offer price, shares allotted, allotment and trading-approval dates). | Did promoters get shares cheap or pay up; dilution. |
| 15 | Preferential allottees | Every proposed allottee with the securities proposed. | Who gets the shares. |
| 16 | Lock-in lines | Filed lock-in periods, else the rule (promoters 18 months, others 6). | Lock-in expiry calendar, supply overhang. |
| 17 | Rights issues | Ratio, rights price, record date, issue open and close, amount. | Rights terms. |
| 18 | QIPs | Issue and floor price, discount, shares, amount, bid dates. | Institutional placements and their discount. |
| 19 | QIP allottees | Allottee, category, shares, % of issue. | Who bought the QIP. |

## E. Market and price

| # | Data | What we get | Use |
|---|---|---|---|
| 20 | Prices (NSE and BSE bhavcopy, from 1 Jan 2025) | Daily open, high, low, close, volume, value, trades. | Price paid vs now, 52-week range, returns. |
| 21 | Daily market cap (NSE) | Issue size x close per symbol. | Trade value as % of market cap at the trade date; size buckets. |
| 22 | Index closes (Nifty 500 and others) | Daily index levels. | Benchmarks for the track record. |
| 23 | Tradability (NSE, from 12 Oct) | ASM, GSM, ESM stage, IBC, trade-for-trade, SME, price band, circuit-locked days. | Warning flags only, never a filter. |
| 24 | Trading calendar (NSE sessions) | Trading days and holidays. | Late-filing counts, window dating, return horizons. |

## F. Reference

| # | Data | What we get | Use |
|---|---|---|---|
| 25 | Securities master | ISIN, NSE symbol, BSE code, name, sector, industry, size bucket. | Join everything by company; search. |
| 26 | Universe (derived) | Whether the company is Rs 100 Cr market cap or more. | Every table is cut to it on read. |
| 27 | Investor alias list (curated CSV) | Spellings of known investors mapped to one name. | One investor across spellings. |

## G. Announcements and documents (collected; AI cards off the site since 21 Oct)

| # | Data | What we get | Use |
|---|---|---|---|
| 28 | Announcements (NSE main board and SME, BSE) | Subject, category, file link, size, broadcast time; concall filings included; BSE's own count reconciled. | Raw feed for the reader. |
| 29 | Filing text cache | Extracted PDF, ZIP and XBRL text with status and size; no PDFs kept. | Input to the reader. |
| 30 | AI announcement reads and company memory | Per filing: category, values each with a quote found in the PDF, values held back. Per company: quote-checked claims. | Filing cards (off the site, owner 21 Oct). |

## H. Computed from the above

Not collected, but they feed pages: signal track record (forward returns after each signal),
forward ledger (signals recorded as they fire, write-once), model basket and its value series,
price summary (latest close, 52-week range, size bucket per company), split- and
bonus-adjusted price history, and the Today ideas (Worth a look, Watch out).

## I. Storage and reports (not data for pages)

`raw_v2/` holds every exchange response byte for byte, write-once. `archive/` holds one
deduplicated row per record. `clean/reports/` holds nightly counts.

## Known gaps

- Open-market buyback maximum price: only in the PDFs.
- Tender buybacks run only on BSE: not in NSE's lists.
- BSE rights and preferential issues: no amounts or prices.
- BSE-only companies: no Company page (keyed by NSE symbol).
- BSE surveillance lists and suspended securities: not collected.
- Results before 15 Oct 2026: not backfilled.
- Balance sheet, concall transcripts read, annual reports, presentations: not collected, or collected but unread.

## Collected but barely shown

Items 5 (encumbrances), 11 (results), 24 (calendar) and the BSE board meetings and BSE
shareholding (from 22 Oct; the data dictionary says no page reads them yet) are cleaned but
reach few or no pages. Items 5, 11 and 24 were not checked against the pages in this pass.
