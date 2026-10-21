# Site layer audit: page inventory, duplicates, defects (Phase 1 + Phase 3, site files)

Read-only review of `streamlit_app/` on branch `revamp/plan` (= origin/main 066fb19), 21 Oct 2026.
Scope: `app.py`, `data/store.py`, `screens/*.py`, `ui/*.py`, `ui/*.css`. Functions in `insiders_clean/`
that the pages call (`signals`, `actions`, `evidence`, `issues.lock_in_lines`, `track.summary`) were read
only to know what a column holds; their own review is a separate Phase 3 item.

Conventions used below
- "eligible" = `ctx.eligible` = `signals.eligible(trades)`: `is_market & is_primary & ~needs_review`, with
  `seen` = `broadcast_date`, `date` = `trade_date_to`, `is_token` = promoter/promoter-group BUY under
  Rs 25 L in a company above Rs 5,000 Cr (`insiders_clean/signals.py:36-47`). Token buys are *in* eligible.
- `ref` = `ctx.ref` = `signals.as_of(ctx.trades)` = latest `broadcast_date` over **all** clean insider rows
  (held-back and non-primary rows included), normalised. Every "last N days" on the site counts back from it,
  and most "next N days" count forward from it.
- `pct_of_mcap` (trades and deals) is a percent (value / market_cap x 100); market_cap is the security
  master's value at clean time (`insiders_clean/insider.py:356,365`, `deals.py:157-159`), not the trade day's.
  `pct_off_high` and `vs_200d` are fractions; `promoter_*_pct`, `median_excess`, `beat_index`, QIP
  `pct_of_issue` are percents. Money columns are rupees; `kit.rupees` writes Rs x Cr / Rs x L.
- Every table is `kit.table` (`ui/table.py:214`): HTML in an `st.iframe`, first `limit` rows drawn,
  sortable, number columns with no value in the shown rows dropped (`table.py:223-224`).
- Severity: **W** wrong number, **M** misleading, **C** cosmetic (incl. crash risk), **P** perf/memory.

---------------------------------------------------------------------------------------------------

## 1. Page inventory

### Shell (every page) — `app.py`
| # | Shown | Source | Window / filters | Units |
|---|---|---|---|---|
| 1 | Sidebar pill "Filings to {date}" / "No clean data yet" (L111-113) | `ctx.ref` | max broadcast_date of all trades | date |
| 2 | Strip: 3 indices "Nifty 500 **24,500** +1.2% vs 200D" (L118-122) | `store.market_strip()` = `artifacts/market_strip.json` (`index`, `close`, `vs_200d`) | first 3 entries | close `,.0f`; vs_200d fraction x100 |
| 3 | Strip "**N** filings" (L123) | `len(ctx.trades)` | all rows, **both exchange copies, held-back included** | count |
| 4 | Strip "**N** open-market" (L124) | `ctx.eligible['is_market'].sum()` | eligible (primary, not held back) | count |
| 5 | Strip "**N** deals" (L125) | `len(ctx.deals)` | all rows, **both exchange copies, market makers included** | count |
| 6 | Footer text + "How clean is the data?" link (L130-132) | static | | |

### Signals > Actions (`screens/actions.py`, default page)
Head (L66-67), caption "Filings up to {ref}. Lists show the last 30 days unless they say otherwise." (L72). Each card is drawn only with rows; ROWS = 6; evidence line = `evidence.verdict(track_summary, signal)` (3M/6M median excess over Nifty 500, beat %, cases).
| Card (key) | Columns in order | Function / clean columns | Window, filters | Units |
|---|---|---|---|---|
| Several insiders buying together (`act_cluster`, L76-85) | Company (sub `who`), Deciders (`decision_makers`), Bought (`value`), % of mcap (`pct_of_mcap`), Last filed (`last_seen`), 52W range · price | `signals.clusters(eligible, ref)` + `with_prices` (prices summary `latest_close/low_52w/high_52w`) | 30 days to ref by `seen`; BUY; roles promoter/promoter_group/director/kmp; tokens out; >=2 decision-makers; sorted by summed pct_of_mcap | Rs; % (sum of per-trade %) |
| Promoters buying (`act_prom`, L87-92) aside "open market, Rs 25 L and up counted as real buying" | Company, Who (`person_name`), Bought (`value_30d`), % of mcap (`pct_30d`), Last filed, 52W range | `actions.buying(eligible, ref, PROMOTER_ROLES)` -> `signals.person_windows` | 30 days; tokens out (only the Rs 25 L / Rs 5,000 Cr rule); by pct_30d | Rs; % |
| Directors and KMP buying (`act_off`, L93-94) | same as above | `actions.buying(..., ('director','kmp'))` | 30 days | |
| Insiders buying after a big fall (`act_dip`, L96-105) | same | `actions.buying(all 4 roles, limit 60)` then `pct_off_high <= -0.25` | 30 days; today's close 25%+ under 52W high; top 60 by pct first | fraction compare |
| Promoters selling (`act_sell`, L108-112) | Company, Who, Sold (`value`), % of mcap, Last filed | `actions.selling(eligible, ref, PROMOTER_ROLES)` | 30 days; SELL; per person sum >= Rs 25 L | Rs; % |
| Heavily pledged promoters (`act_pledge`, L114-118) | Company, Pledged (`promoter_pledge_pct`), Promoters hold (`promoter_holding_pct`), Quarter (`quarter_end`) | `actions.pledged(shareholding, securities)` | latest quarter per **symbol**; `shareholding_stale` rows excluded; > 15% | % of promoter shares; % |
| Funds net buying small caps (`act_funds`, L120-125) | Company, Buyers (`net_buyers`), Net bought (`net_value`), % of mcap (`net_pct`), Last deal (`last`) | `signals.small_cap_accumulation(ctx.deals, ref, 30)` | 30 days to **insider ref**; deals primary, market makers out; mcap < Rs 5,000 Cr; **all client types**; net > 0 | Rs; % |
| Shares about to come off lock-in (`act_lock`, L128-135) | Free from (`expires`), Days (`days_left`), Company, Lock-in (`what`), Shares (`shares`), At market now (`at_market`) | `capital_raises.lock_in_calendar(preferential, prices, ref, preferential_lockins)` | expires in 0..60 days after ref | shares; Rs (shares x adjusted close) |
| Boards meeting on fund raising or a buyback (`act_meet`, L137-140) | Meeting, Company, To consider (`purposes`) | `_meetings` (L48-61) on `ctx.meetings` | `meeting_date` in [ref, ref+14]; fund_raising/preferential/buyback/rights | date |
| Closing caption (L145-147) | static | | | |

### Signals > Morning brief (`screens/brief.py`)
`day` = ref. Caption "From the filings made public on {day}, cleaned overnight." (L88).
| Section | Columns / value | Source | Window / filters | Units |
|---|---|---|---|---|
| Tile Open-market buys (L90-91) | sum value; note N insiders · N companies | eligible, `seen == day`, BUY | one broadcast day; **tokens included** | Rs |
| Tile Open-market sales (L92-93) | same for SELL | | | Rs |
| Tile Bulk and block deals (L94) | count of rows | `ctx.deals` `date == day`, primary, not MM | one trade date = insider ref | count |
| Your watchlist (`br_watch`, L99-118) | Company, What, Who, Value, Made public | `_warnings` (L43-72): `ctx.trades` primary (**held-back included**) with `seen >= day-7`: market SELL by any role; `kind == 'pledge_create'`; preferential `issue_rows` posted >= day-7, PROMOTER/MIXED, `vs_market < 0` | 8 calendar days (>=) | Rs |
| Filings read (`br_reads`) | cards | `filings_read.render(announcement_reads, day, ...)` | broadcast_date >= ref (can be several days), first 40 cards | see Filings read |
| Insiders buying together, joined last session (`br_cl`, L124-131) | Company (sub who), Deciders, Bought, 30 days (`value`), % of mcap | `signals.clusters(eligible, ref)` with `last_seen == day` | 30 days | Rs; % |
| Open-market trades of Rs 25 L and up (`br_big`, L132-137) | Company, Person, Side, Value, % of mcap (bar) | eligible `seen == day`, **per filing row (tranches not combined)**, value >= Rs 25 L | one day | Rs; % |
| Bulk and block deals (`br_deals`, L138-142) | Company, Client, Side, Value, % of mcap | same `dnew` as tile, by value | one day | |
| Board meetings this week (`br_meet`, L145-155) | Company, Meeting, To consider | `ctx.meetings` `day < meeting_date <= day+7`, **any purpose** | 7 days after ref | |
| Shares coming off lock-in this week (`br_lock`, L156-164) | Free from, Company, Whose shares (`who`), Shares (`shares_allotted`), At market now | `lock_in_calendar(preferential, prices, ref)` **without the lock-in lines table** | days_left 1..7 | |

### Signals > Screener (`screens/screener.py`)
| Section | Columns | Source | Window / filters | Units |
|---|---|---|---|---|
| Presets pills (L44) | All with promoter buying / Cluster / Float absorbers / Spotlight / Promoter selling / High pledge / near 52W high / 30%+ below high | `signals.company_board(eligible, deals, shareholding, ref)` badges; price presets on `pct_off_high` (fraction, -0.05 / -0.30) | 90 days to ref | |
| Card "{N} companies" (L85-98) | Company; Signals (`badges`); Promoter net (`promoter_net`, signed Rs); % of mcap (`promoter_net_pct`, bar); Avg paid (value-weighted, split-restated, promoter buys 90d, L70-75); CMP vs paid; Last buy; % of float (`float_pct(promoter_net, market_cap, public_holding_pct)`); 52W range; 1Y price spark; Who bought (`insider_details`, sub cap_sector "Rs x Cr · sector") | board columns are sums over eligible in window, **token buys included** in promoter_net/net_pct; badges from spotlight/float_absorbers/clusters (tokens out); pledge from `latest_shareholding` by ISIN (**stale included**) | 90 days | Rs; %; Rs/share |

### Signals > Track record (`screens/track_record.py`)
| Section | Value | Source | Notes |
|---|---|---|---|
| Tiles (L46-51): Events measured (`len(track_events)`, `day.min()` to `entry_date.max()`), Entry "Next close", Benchmark, Costs `track.COST_PCT` | `artifacts/track_events.parquet` | |
| Note "Early read" (L52-55) | months between first and last | | |
| Toggles: benchmark (Nifty 500 / size-matched), Tradable only (recomputes `track.summary(ev)`) (L56-66) | | |
| Scorecard (L67-88): per signal x `track.HORIZONS`: median excess (`median_excess` or `median_excess_sm`), "x% beat" (`beat_index` / `beat_size_index`), cases (**always Nifty `cases`**), "Before public" (`median_pre_move`, `median_lag`) | `artifacts/track_summary.parquet` | % ; few = cases < 30 |
| Forward record (L112-134): Company, Signal, Made public, Recorded, Close then, Entry, excess per horizon; aside = **median over all signals pooled** | `artifacts/forward_outcomes.parquet` | % |
| Model basket (L137-168): tiles Basket (nav-100), Nifty 500 same days, Open positions, Closed in profit; chart; table Company, Signal, Entry, Entry price, Status, Return after costs | `artifacts/basket_positions.parquet`, `basket_nav.parquet` | % |
| Every case (L94-109): Company, Made public, Entry, Value, Before public, Lag, Tradability, excess per horizon | track_events for the picked signal | % |

### Filings > Latest session (`screens/today.py`)
Window control: Latest session = 1 / Last 5 sessions = 5 / "Last 30 days" = **22 filing days** (L83); `first`..`day` = those filing days.
| Section | Value / columns | Source | Window / filters | Units |
|---|---|---|---|---|
| Tile Net open-market promoter flow (L190-192) | sum signed value of promoter/promoter-group rows | `_session` -> `session_by_company` per day (eligible) | window; **tokens included** | Rs |
| Tile Largest spotlight buy (L182-188) | symbol; value · float% or mcap% · day | window buys (tokens out) joined to `spotlight(eligible, end)` persons; sorted by `impact` = pct_of_float, else pct_of_mcap | 30-day spotlight line | |
| Tile Cluster formations (L194) | count | `clusters(eligible, end)` with `last_seen >= first` | | count |
| Tile Institutional handshakes (L195-197) | sum matched_value; N matches | `signals.handshakes(ctx.deals, trades, days=len(window))` ref = **deals' max date**; all non-MM clients | | Rs |
| Activity over 12 months (L200-211) | two monthly bar charts, Rs Cr | `charts.monthly_flow(eligible[~is_token], 'seen')`, deals non-MM primary by `date` | last 12 calendar months (current month partial) | Rs Cr |
| Spotlight buys (L213-218) | up to 6 cards: size/mcap, "bought Rs x (y% of float)", Paid vs now (+%), 52W range, "Buy #n in 14 days", pledge tag, flags | `_card` (L44-80): paid = value/qty (unadjusted), now = `latest_close` (adjusted); pledge `pledge_by_isin` (stale included); size `securities.mcap_category` | | |
| Insider trades and deals (L220-259) chip All / Promoter buys only | Company, Person, Side, Value, % of mcap, % of float, Made public (`day`), Tranches, 52W range, spark | `sess` tokens out, sorted by `impact` (float% else mcap%) | window | |
| chip Bulk deals (L237-248) | Company, Client, Side, Value, % of mcap, Price | `ctx.deals` non-MM, `date >= first`, **is_primary not applied** | | |
| chip Large handshakes (L249-257) | Company, Sold by, tag, Absorbed by, Matched, % of mcap sold | `hs[large]` (>= Rs 10 Cr or 0.5% of mcap) | | |
| Outside investors crossing 5% or moving 2%+ (L108-128) | Company, Investor (sub mode), Action, % traded, Stake after | `ctx.sast` (NSE + BSE-only), not promoter, latest `broadcast_ts` day | one day | % of capital |
| Coming up: boards considering capital moves (L131-151) | Meeting, Company, To consider | meetings in [ref, ref+10], CATALYSTS (fund_raising, preferential, buyback, bonus, split, rights) | 10 days | |
| Expander "Needs a look · N filings held back in the last 10 days" (L264-274) | company · person · value, reasons | `ctx.trades` `needs_review`, `seen > day-10`, **all exchange copies** | 10 days | Rs |

### Filings > Filings read (`screens/filings.py`, cards in `screens/filings_read.py`)
| Section | Value | Source | Window / filters |
|---|---|---|---|
| Filters (L107-122): Heading pills with counts, Period (1/7/30/60/From the start), Exchange, Company size (`prices.mcap_bucket`), search, "2 readers agree" | | `announcement_reads` (+ `announcement_reads_history` for > 60 days) | `since` = **IST wall-clock today** - days (L97) |
| Coverage line (L137, `filings_read.coverage_html`) | "Of N filings the reader looked at: x read in full; y not read (...); z at or below Rs 500 Cr (not sent to a model); k SME" | `status` counts | broadcast_date >= since |
| Card list "{N} filings" (L140-147), 50/100 per page | `filings_read.card_html`: name/symbol, market cap ("Rs x Cr · Largecap" from `prices.market_cap`, `mcap_bucket`), time IST · exchange, category tag + subject, headline/subtitle, points, "The figures" (metric, QoQ/YoY), "Before this" (`before_this`), Management said, Key terms, Still to come / Not in this filing, filing's own words, moves 1W/1M/1Y (`_moves` on price_history), Also filed, link | `recent()` -> `same_deal()` | newest first |
| "Before this" lines (`filings_read.py:443-522`) | price vs last close (own-share categories); size % of market cap; size % of last FY revenue (`context.last_year`); last quarter growth (`context.last_quarter`); promoter holding/pledge (latest quarter by ISIN, any date); insiders bought/sold Rs x in N filings in last 30 days (eligible); 3 earlier reads (90 days) | | see W15 |
| Caption (L148-150) | "... companies below Rs 100 Cr and concall notices are not read" | | |

### Filings > Insider & promoter trades (`screens/insider_trades.py`)
Filters: toggle "pure open-market" (default on), Period 7/30/90(default)/365/All (by `seen` from ref, L84-89), Who (roles), search, window-open toggle. Rows: `ctx.trades` primary only (L79).
Tabs with counts (L103-111): Open market buys (`is_market & BUY & ~needs_review`), Open market sells, and with toggle off: ESOPs & off-market archive (`~is_market & ~pledge`, held-back included), Pledges, Held back.
Columns (L58-69): Company (sub `window` text), Person, Side, Value (`value`, Rs), % of mcap (bar), Own holding Δ (`holding_change_pct`, % change of own holding), Paid (`price` = value/quantity, **unadjusted**), CMP vs paid (`latest_close / (price x split_since) - 1`, buys only), Made public (`seen`, sub "n sessions after the trade"), Before public (`pre_public_move`, adjusted closes), Mode as filed (sub late text, sessions over `DISCLOSURE_LIMIT_SESSIONS`=2), 52W range, spark. limit 150, CSV of all.

### Filings > Bulk & block deals (`screens/deals.py`)
| Tab | Columns | Source / filters | Units |
|---|---|---|---|
| Handshakes (L29-46) | Company, Date, Sold by, Seller tag, Absorbed by, Matched (`matched_value` = min of net sides), % of mcap sold, Large tag, spark | `signals.handshakes(d, trades, days)` 7/30/90 to deals max date; MM out; primary; optional only promoter sellers | Rs; % |
| Small caps being accumulated (L49-65) | Company, Net buyers, Net bought, % of mcap (`net_pct`), Mkt cap (deal-day `market_cap`, last), Last deal, 52W range, spark | `small_cap_accumulation(d)` 30 days to **deals max date**; all non-MM clients unless "Institutions only" (default off) | Rs; % |
| All deals (L67-93) | Company, Date, Client (sub counterparties), Type (`client_type` + "(by name, unsure)"), Side, Shares, Price, Value, % of mcap, Feed | `ctx.deals` 7/30/90 days to deals max date, primary, MM optional, type filter | Rs |

### Filings > Other filings (`screens/other_filings.py`)
Tab "Stake changes (5%+)" = `sast.render(head=False)`:
- Tiles (sast.py L28-36): Disclosures (all SAST rows, NSE + BSE-only, date span of `broadcast_ts`), Outside investors (`~is_promoter`, acquisitions vs "sales" = not starting with "acq", so `Both` counts as sale), Promoter group, "Crossed 5% or more" (= `post_stake_pct >= 5`).
- Table (L45-52): Company, Made public, Acquirer/seller (sub mode), Action, Transaction, Shares (`shares_traded`), % traded (`percent_equity_traded`, signed %), Stake after (`post_stake_pct`), Rule. No date window; limit 300.
Tab "Gifts, off-market and pledges" = `transfers.render(head=False)`:
- `ctx.trades` primary & `~is_market` (held-back and `holding_only` included), grouped by `kind` (transfers.py L14-37).
- Tiles (L40-41): first 4 groups: count, note = sum of `value` (NaN -> Rs 0).
- Tabs per group: Company, Person, Side, Mode as filed, Shares, Value, Own holding Δ, Made public. limit 200.

### Companies > Company (`screens/company.py`, `/company?symbol=`)
Rows: `t` = `ctx.trades` by `nse_symbol` (all copies); `e` = eligible by symbol; `win` = e with `seen > ref-365`; deals `d` = by symbol, non-MM, primary, `date > ctx.deals.date.max()-365`.
| Section | Value | Source | Units |
|---|---|---|---|
| Head = `display_name` (securities) | | | |
| Ident line (L49-59) | symbol · BSE code · ISIN · sector · industry · "Mkt cap Rs x" | `securities` row (`market_cap` = security master, no date) | Rs |
| Flags (L60-63) | tradability badges + notes | `tradability` | |
| Tile Price (L80-89) | latest_close; "+x (+y%) on {last hist day} · z% from 52W high {high}" | prices summary + last two closes of `price_history` | Rs; `pct_off_high` x100 |
| Tile Promoter net, 12 months (L92-94) | sum signed_value; "x% of market cap, open market only" (sum of signed pct_of_mcap, 3 dp) | `win` promoter roles (tokens included) | Rs; % |
| Tile Directors & KMP net (L95) | sum signed_value; N people | `win` director/kmp | Rs |
| Tile Deals net, 12 months (L96-97) | sum signed_value | `d` | Rs |
| Tile Promoter holding · pledge (L98-101) | promoter_holding_pct · promoter_pledge_pct; free float = public_holding_pct | `latest_shareholding` by symbol (**stale included**) | % |
| Overview: Room to the 75% ceiling (L132-134) | 75 - promoter % | latest shareholding | pts |
| Overview: Creeping-acquisition room, this FY (L135-138) | min(5 - used, 75 - ph), used = sum pct_of_mcap of promoter open-market buys since 1 Apr (by `seen`) | e | % |
| Price and insider trades chart (L140-145) | 1y closes + every eligible trade on its broadcast day | `charts.price_with_trades(price_history, e)` | Rs; size by Rs Cr |
| Net open-market flow by who, 12 months (L147-159) | Promoters, Directors & KMP, Other insiders, "Bulk/block buyers (no market makers)" | win sums; `d.signed_value.sum()` (net buys minus sells) | Rs |
| Handshakes in this stock (L161-168) | Date, Sold by, Seller, Absorbed by, Matched, % of mcap sold | `handshakes(own deals, trades, 365, ref=deals max)` | |
| Timeline tab (L170-231) | trades (primary; market only unless toggled), deals `d`, SAST (all), buybacks, corporate actions, meetings; up to 80 events | each event's meta: traded dates, made public (lag), late tag, window-open, "q sh @ price" (unadjusted), own holding %, "% since" (latest close / close on broadcast day) | |
| Insider trades tab "Insider trades · len(t)" (L233-240) | Person, Side, Mode as filed, Shares, Price, Value, Own holding Δ, Traded, Made public | primary rows of t, all kinds | |
| Deals tab "Deals · len(d)" (L241-247) | Date, Client, Side, Shares, Price, Value, % of mcap, Feed | d (12 months, no MM) | |
| Shareholding tab (L248-269) | all quarters: Quarter, Promoter, Public, Pledged, Encumbered, Filed; Promoter group card: Member, Category, Shares, % of company, Pledged | `shareholding` by symbol; `promoter_group` latest quarter | % |
| Capital raises tab (L270-278) | per kind: Posted, Stage, Offer price, Amount, Shares, Trading approval | `issue_rows` / `rights_rows` / `qip_rows` (offer_price := issue_price) | Rs |
| NSE links (L279-284) | | | |

### Companies > Person or fund (`screens/entity.py`, `/entity?id=`)
| Section | Value | Source | Window |
|---|---|---|---|
| Search (L18-29) | names matching | trades person_id/name + deals client_id/name | |
| Market maker note; type line (L37-49) | client_type, confidence, rule, sibling ids by `investor_group_id` | deals | |
| Tile Capital deployed, 12 months (L75-76) | insider open-market buys + deal buys | `mk` = eligible by person_id; `yr` = `seen > seen.max()-365` (**person's own last filing**); `dy` = `d.date > d.date.max()-365` (**own last deal**) | see W7/W8 |
| Tile Active companies, 12 months (L77) | distinct ISINs in yr + dy | | |
| Tile Net, all data (L78-79) | eligible signed_value + all deals signed_value; note "len(t) insider filings · len(d) deals" (t = all primary filings incl. non-market) | | |
| Tile Open-market buys, P&L (L60-73) | value-weighted % (shares/factor x latest close vs shares x paid x factor); % of buys in profit | eligible BUY + prices + split_since | all data |
| Insider filings table (L82-90) | Company, Side, Value, % of mcap, Made public, Mode, spark | primary filings | limit 100 |
| Deals table (L91-98) | Company, Date, Side, Shares, Price, Value, % of mcap, Feed | primary deals (MM included) | limit 100 |

### Companies > Capital raises & actions (`screens/capital_raises.py`)
| Card | Columns | Source / rules | Units |
|---|---|---|---|
| Preferential issues (L160-172) | Posted, Company, Stage, Shares go to (`allottee_category`), Instrument, Amount (`amount_total` fillna `amount_raised`), Shares allotted, ICDR minimum (filed), Trading approval; caption `link_summary` | `issue_rows(preferential)`: listing records + unlinked approvals | Rs; Rs/share |
| Offer price against the ICDR minimum and the market (L173-186) | Posted, Company, Shares go to, Offer price, ICDR minimum filed, Offer vs minimum (`vs_icdr_min`), Minimum our estimate (`icdr_min_ours`), Market price now (`latest_close`, adjusted), Offer vs market now (`offer/latest_close - 1`) | allotted with offer_price | % |
| Who gets the shares (L187-197) | Posted, Company, Allottee (sub security_type), Securities, Promoter (Yes/No/blank) | `preferential_allottees`; link only if id in trades/deals | |
| Lock-in expiries (L198-207) | Expires, Days, Company, Lock-in, Shares, At market now, Note | `lock_in_calendar(..., preferential_lockins)`; from ref-30 days on | shares; Rs |
| Rights issues (L208-219) | Posted, Company, Stage, Ratio, Rights price (`offer_price`), Market price now, Rights vs market now, Record date, Closes, Amount | `rights_rows` | |
| QIPs (L220-233) | Posted, Company, Stage, Issue price, Floor price, Discount/share, Issue vs market now, Amount (`amount_raised` fillna `amount_total`), Allottees, Trading approval | `qip_rows(qip)` | |
| Who bought the QIPs (L234-240) | Allotted, Company, Allottee (sub category), Shares, % of issue | `qip_allottees` (% converted from fraction in clean) | % |
| Upcoming board meetings on capital moves (L242-259) | Meeting, Company, To consider, As filed (description) | meetings with chosen purposes, `meeting_date >= ref-7` | |
| Buybacks (`buybacks.card`, buybacks.py L194-209) | Starts (offer_open / record_date / first_report), Company, Route (sub note), Offer price, Market price now, Offer vs market now, Size (`offer_value`), Tendered x, Record date | `buybacks` table | Rs; % |
| Corporate actions (L264-284) | Ex-date, Company, Type, As filed, Ratio, Rights price, Dividend/share, Record date | `actions` NSE + BSE-only, kinds pills (default includes buyback) | Rs |

### Companies > Shareholding & pledges (`screens/shareholding.py`)
| Section | Value | Source | Notes |
|---|---|---|---|
| Tiles (L35-42): Companies covered (count, latest quarter max), With promoter pledge (>0), Pledge above 15%, Promoter stake up/down vs quarter before | latest row per symbol (stale included) | % |
| Table (L51-59): Company, Quarter, Promoter, Δ QoQ (pp shown with "%"), Public, Pledged, Δ pledge (pp, "%"), Encumbered, spark | `last - prev` per symbol | limit 300 |

### Hidden: Data quality (`screens/data_status.py`) and Coming next (`screens/coming.py`)
- Data quality: tiles Insider filings (`output_rows`, in, removed), Deal rows (out, in, market-maker legs), Unmatched securities, Calendar confirmed to; Removed / Held back bar lists per table (`report.tables.*.removed/flagged`); Data checks paragraphs (holding, price range, dates, holding-only); notes; caption run date + ref. All from `store.report()` (`clean/latest.json` -> report key).
- Coming next: static list; 3 of its 6 items are already built (ICDR minimum, QIPs, buyback price and route are on Capital raises) - stale page (M25).

---------------------------------------------------------------------------------------------------

## 2. Duplicate map

| # | Data | Copies (page: code) | Computed differently? |
|---|---|---|---|
| 1 | Insider clusters | Actions `act_cluster` (actions.py:76); Brief `br_cl` (brief.py:124, last_seen == ref); Latest session tile "Cluster formations" (today.py:177-178, `end` = window end, last_seen >= first); Screener preset "Cluster buys" (badge from company_board, 90-day board) | Same function; Actions labels `value` "Bought", Brief "Bought, 30 days"; Latest session counts clusters as of window end, so it differs from Actions when window > 1 day |
| 2 | Promoter / insider buying | Actions "Promoters buying", "Directors and KMP buying", "after a big fall" (person_windows 30d, tokens out, per person); Screener "All with promoter buying" (company_board 90d **net**, tokens in, per company); Latest session feed (session_by_company per day, tranches combined, tokens out) and tile "Net promoter flow" (tokens in); Brief "Rs 25 L and up" (per filing row, not combined) and tiles (tokens in); Company tiles (12 m net, tokens in); Person tiles | Five windows (1 day, 5/22 filing days, 30, 90, 365 days), three token rules, two grains (per person vs per company, tranches combined vs not) |
| 3 | Spotlight (0.15% in 30 days) | Latest session tile + card grid (today.py:173-218); Screener preset "Spotlight" (badge) | Latest session ranks by `impact` (float% else mcap%); Screener by promoter_net_pct |
| 4 | Promoter selling | Actions `act_sell` (30 d, per person, >= Rs 25 L, by % sold); Screener "Promoter selling" badge (90 d net promoter_net_pct <= -0.15, net of buys, tokens in); Brief watchlist "sold on the market" (7-8 d, any role, any size, held-back included) | Three different rules for the same words |
| 5 | High pledge | Actions `act_pledge` (by symbol, stale **excluded**); Screener "High pledge" badge (by ISIN, stale included, only companies with insider activity in 90 d); Shareholding page tiles/table (by symbol, stale included); Company tile (stale included); Latest session spot-card pledge tag (`pledge_by_isin`, stale included); Filings card "Promoters hold ... pledged" (`holdings` by ISIN, any quarter) | A company whose latest quarter is `shareholding_stale` is absent on Actions but shown elsewhere with last quarter's pledge under the new quarter's date |
| 6 | Board meetings ahead | Actions (ref..ref+14, fund_raising/preferential/buyback/rights); Brief (ref < date <= ref+7, any purpose incl. results); Latest session (ref..ref+10, + bonus/split); Capital raises (>= ref-7, pills); Company timeline (all) | Four windows and three purpose sets |
| 7 | Lock-in expiries | Actions (with lock-in lines, 0..60 d); Brief (**without** lines -> rule-only, 1..7 d, Shares column blank); Capital raises (with lines, from -30 d) | Brief's dates and share counts differ from the other two for any allotment whose listing XBRL files its own lock-in lines |
| 8 | Small caps net-bought in deals | Actions "Funds net buying small caps" (ref = insider ref); Deals tab "Small caps being accumulated" (ref = deals max date; Institutions toggle) | Different 30-day windows whenever insider and deal data end on different days; neither filters to funds by default |
| 9 | Handshakes | Deals tab (7/30/90 d to deals max); Latest session tile + "Large handshakes" chip (days = insider window length, anchored to deals max); Company card (365 d) | Latest session's labelled dates are the insider window, the matches are from the deals' latest days |
| 10 | Bulk/block deal rows | Brief tile + `br_deals` (date == ref, primary, no MM); Latest session chip "Bulk deals" (date >= first, no MM, **no primary filter**); Deals "All deals" (primary, MM optional); Company Deals tab (12 m, primary, no MM); Person deals (primary, MM included); app strip count (all rows) | Latest session and the strip count NSE+BSE copies twice |
| 11 | Insider filing lists | Insider trades page (primary, tabs); Company "Insider trades" tab (primary, but tab label counts all copies); Person "Insider filings" (primary); Other filings > Gifts, off-market and pledges (primary, ~market, grouped by kind) vs Insider trades > "ESOPs & off-market archive" + "Pledges" + "Held back" tabs (same rows, other grouping) | Same rows in two pages with different group boundaries (pledges, holding-only, held back) |
| 12 | Held-back filings | Latest session expander (10 d, all copies); Insider trades "Held back" tab (primary); Data quality "Held back for a look" (report counts) | three counts for one set |
| 13 | SAST | Other filings tab (all); Latest session "Outside investors" (latest day, non-promoter); Company timeline (by symbol) | same table |
| 14 | Preferential / rights / QIP | Capital raises cards; Company "Capital raises" tab (same builders); Brief watchlist warning (`issue_rows.vs_market`) | "Amount" = approved amount first for preferential and rights, raised amount first for QIP; Company tab shows both kinds under one "Amount" header |
| 15 | Buybacks | Capital raises "Buybacks" card and "Corporate actions" card (default kinds include `buyback`) on the same page; Company timeline (de-duplicated, company.py:221-223) | the same buyback appears twice on Capital raises |
| 16 | Price paid vs now | Insider trades "CMP vs paid" (per trade, split-adjusted); Screener "CMP vs paid" (90 d average, split-adjusted); Latest session spot card "Paid · now (+%)" (**not adjusted**); Person P&L (adjusted); Company timeline "% since" (from the broadcast-day close, not the price paid) | one unadjusted copy |
| 17 | Market cap | Company ident (`securities.market_cap`); Screener "Rs x Cr" (trades `market_cap`, security master, `,.0f` western grouping); Latest session card (`sess.market_cap`); Filings cards (`prices.market_cap`, NSE last session); Deals "Mkt cap" (deal row) | up to three values for one company; only the price-summary one has a known date |
| 18 | Size class | Latest session card: `securities.mcap_category` (today.py:36-41); Filings cards and filter: `prices.mcap_bucket` (our NSE rank, filings_read.py:120,162); Track size-matched: "today's size bucket" | two classifications on the site |
| 19 | 1-year move | Table spark "1Y price" % = last / first close inside the last 365 days of history (table.py:102), so a 3-month-old listing shows a 3-month move; Filings cards "1Y" needs a close 365+ days back (filings_read.py:145-156) | same label, different number |
| 20 | Net promoter flow | Latest session tile (window), Company tile (12 m), Screener `promoter_net` (90 d) | all include token buys; fine as long as labelled |
| 21 | "As of" date | Sidebar pill, Actions caption, Brief caption, Data quality caption: `ctx.ref`; Filings read: IST wall clock (filings.py:97); Track record: its own artifact dates | two anchors |

---------------------------------------------------------------------------------------------------

## 3. Defects, line by line

Counts: **W 20 · M 25 · C 23 · P 10 = 78.** IDs are referenced in the duplicate map and summary.

### 3.1 Wrong number (W)

| ID | file:line | Shown | Should be | Fix |
|---|---|---|---|---|
| W1 | app.py:123 | "N filings" = `len(ctx.trades)` on every page | one per filing: NSE and BSE copies and held-back rows are counted, so the count is inflated by every dual-listed filing | `int(ctx.trades['is_primary'].astype('boolean').fillna(False).sum())` (and say "incl. held back" or exclude them) |
| W2 | app.py:125 | "N deals" = `len(ctx.deals)` | deal rows counted once, without market-maker legs (the rest of the site leaves them out) | count `is_primary & ~client_is_market_maker`, or label "deal rows incl. market makers" |
| W3 | company.py:116 | tab "Insider trades · len(t)" with `t` = every copy (L39) | the table under it shows only primary rows (L233) | use the primary count |
| W4 | today.py:239 | chip "Bulk deals": `d[~MM & date >= first]` | a deal printed on NSE and BSE appears twice; every other deals list filters `is_primary` | add `& d['is_primary'].astype('boolean').fillna(False)` |
| W5 | today.py:264-267 | "Needs a look · N filings held back in the last 10 days" over `ctx.trades` | both exchange copies counted and listed | filter `is_primary` (as Insider trades "Held back" does) |
| W6 | brief.py:156,163 | "Shares coming off lock-in this week": Shares column reads `shares_allotted`, which `issues.lock_in_lines` does not output (`LOCKIN_COLUMNS` has `shares`, issues.py:491); the call passes no `lines`, so rule dates (18/6 months) replace the filed lock-in lines | Shares = `shares`; dates = the filed lines, as on Actions and Capital raises | `lock_in_calendar(ctx.preferential, ctx.prices, ref, store.table('preferential_lockins'))`; `Col('shares', ...)` |
| W7 | entity.py:55-57, 75-79 | "Capital deployed, 12 months" = insider open-market buys + deal buys; "Net, all data" = insider + deals | a promoter's large on-market buy is filed as a PIT disclosure and printed as a bulk/block deal under the same id (person_id and client_id share one key space: `signals.handshakes` matches `(isin, client_id)` to `(isin, person_id)`, signals.py:318-341), so the same rupees are counted twice | match deals to insider trades (isin, date within the trade span, side, quantity) and count once, or show the two sums side by side without adding them |
| W8 | entity.py:54, 56 | "12 months" = 365 days back from the person's own last filing (`seen.max()`) and own last deal (`d['date'].max()`) | 12 months back from the data's as-of date | anchor to `ctx.ref` (insider) and `ctx.deals['date'].max()` (deals) |
| W9 | capital_raises.py:54, 97, 110; buybacks.py:187-188; brief.py:66-69 | "Offer vs market now", "Rights vs market now", "Issue vs market now", buyback "Offer vs market now", Brief warning "at x% vs today's price": filed price (unadjusted) / `latest_close` (split and bonus adjusted) - 1 | after a split or bonus following the issue, the filed price must be put on the adjusted basis first (a 1:10 split turns -5% into +850%) | multiply the offer by the split factor since the allotment / record date (`split_since` with the issue date), or compare with the close at pricing |
| W10 | capital_raises.py:84 | lock-in "At market now" = filed lock-in shares (pre-split count) x adjusted close | shares restated for any split/bonus since allotment | divide shares by the factor since `trading_approval_date` |
| W11 | capital_raises.py:48-49, 94-95 vs 108 | Preferential/Rights "Amount" = `amount_total` (In-Principle approved size) first, `amount_raised` only as fallback; QIP "Amount" = `amount_raised` first | an allotted/listed record should show what was raised; the same header means two things on one page and in the Company "Capital raises" tab (company.py:276) | two columns, "Approved" and "Raised", from their own fields |
| W12 | screener.py:54 (+ signals.company_board:189-192) | Default preset "All with promoter buying" = `promoter_net > 0`, ranked by `promoter_net_pct`, both summed over every eligible promoter row including `is_token` | decision of 07 Oct (PRODUCT.md): token buys are labelled and never ranked; a company whose only promoter buying is token buys is listed and ranked | exclude `is_token` from the promoter sums (in company_board, or pass `eligible[~is_token]`), and say so in the help text |
| W13 | today.py:168-169 | Tile "Net open-market promoter flow" includes token buys | page subtitle (L155) says token buys are left out | `prom = prom[~prom['is_token']]` or drop the claim |
| W14 | today.py:179 | `handshakes(ctx.deals, ctx.trades, days=window)` with `ref` defaulting to the deals' max date; tile text says "· {when}" (insider dates) | matches inside the labelled dates | pass `ref=day` (and use the same first..day span) |
| W15 | filings_read.py:494-501 | "Insiders bought Rs x on the market in N filings in the last 30 days" under "Before this": filter is `seen >= at - 30 d` with no upper bound | trades made public before the filing only; on any older card (Filings read 7/30/60 days/From the start) later trades are added in | add `& (insiders['seen'] <= at_ist_date)` |
| W16 | track_record.py:26-32 | Size-matched scorecard: `n = cases` (count of `excess_{h}`, track.py:178-181) beside `median_excess_sm` (median over the rows that have a size index) | the size-matched case count; the "few" flag uses the wrong n; `beat` NaN prints "nan% beat" | add `cases_sm` to `track.summary` and use it when `sized` |
| W17 | today.py:175-176, 229 | "Largest spotlight buy" and the feed "largest impact first" sort by `impact = pct_of_float.fillna(pct_of_mcap)` | one measure per ranking: a company without a shareholding pattern ranks on a smaller denominator's number (mcap% < float%), so the order is wrong | rank by `pct_of_mcap`; show % of float as its own column |
| W18 | actions.py:120-125; deals.py:53-55 | "Funds net buying small caps" / "No small caps net-bought by real funds": `small_cap_accumulation` over every non-market-maker client (individuals, corporates, promoters, brokers) | funds only, per the title | filter `client_type.isin(participants.INSTITUTIONAL)` on Actions and default the Deals toggle on, or retitle "Real buyers net buying small caps" |
| W19 | today.py:52, 65-68 | Spot card "Paid Rs x · now Rs y (+z%)": paid = value/qty as filed, now = adjusted close | both on the same basis (every other "vs paid" uses `split_since`) | multiply paid by `split_since` |
| W20 | ctx.py:65 via signals.as_of (signals.py:27-33) | `ref` = max `broadcast_date` over all trades, including held-back rows (the cleaning flags `disclosure_dated_in_future`, data_status.py:23, and keeps them) | the as-of date of usable data; one future-dated held-back row moves every window on the site and the "Filings to" pill forward | compute `as_of` on `~needs_review` primary rows and cap it at today (IST) |

### 3.2 Misleading (M)

| ID | file:line | What is shown | What it should say / be | Fix |
|---|---|---|---|---|
| M1 | actions.py:57, brief.py:148, today.py:141-143, capital_raises.py:159, 199, 253, actions.py:128-130 | Forward windows ("next 14 days", "this week", "next 10 days", lock-in "Days") start at `ref`, the last filing day, not today. On 21 Oct with filings to 19 Oct, meetings of 20-21 Oct are still "coming", lock-in days are 2 too many | backward windows from `ref`, forward windows from IST today | `today = pd.Timestamp.now(tz='Asia/Kolkata').normalize().tz_localize(None)` for forward lists |
| M2 | actions.py:91 | aside "open market, Rs 25 L and up counted as real buying" | the code drops only buys under Rs 25 L in companies above Rs 5,000 Cr (`is_token`); a Rs 1 L buy in a Rs 300 Cr company is listed | say "token buys (under Rs 25 L in companies above Rs 5,000 Cr) left out", or apply a Rs 25 L floor |
| M3 | company.py:152 | bar "Bulk/block buyers (no market makers)" | it is the net of all non-MM deal buys and sells | label "Bulk/block deals, net (no market makers)" |
| M4 | sast.py:34-35 | tile "Crossed 5% or more" = rows with `post_stake_pct >= 5` | that is "stake after 5%+" (every Reg 29(2) move by a 5%+ holder counts); "crossed" = Reg29(1) rows | count `regulation == 'Reg29(1)'`, or relabel |
| M5 | shareholding.py:29-32, company.py:73-75, screener (company_board pledge), today.py:54, filings_read.py:536-537 | latest quarter's pledge where `shareholding_stale` is true: the figures are the previous quarter's, shown under the new quarter's date | mark stale (Actions excludes it, actions.py:46-48) | carry `shareholding_stale` to a "previous quarter" tag; one helper for "latest pledge" used by every page |
| M6 | shareholding.py:54, 57 | "Δ QoQ", "Δ pledge" written "+1.20%" (kit.pct) while the caption says percentage points | "+1.20 pts" | a `pts` kind in table.py |
| M7 | today.py:83 | window "Last 30 days" = last 22 filing days | other pages use 30 calendar days | 30 calendar days from ref, or label "Last 22 filing days" |
| M8 | company.py:72 | Deals window = 365 days to `ctx.deals['date'].max()` while insider flow = 365 days to `ref`; tiles side by side say "12 months" | one anchor | anchor both to their own as-of and print it |
| M9 | brief.py:49 | watchlist warnings from `ctx.trades` primary, **held-back rows included**: a sale held back for "value off by a power of ten" is shown with that value | exclude `needs_review`, or tag "held back" | |
| M10 | insider_trades.py:63 | "Paid" = filed price (unadjusted) next to "CMP vs paid" and the 52W range (adjusted) | paid on the adjusted basis, or a "pre-split" note | show `price * split_since` with the filed price in the sub line |
| M11 | filings_read.py:334, 347 vs filings.py:148-150 | coverage "x at or below Rs 500 Cr (not sent to a model)" (sums `below_500_cr` + `below_100_cr`); page caption "companies below Rs 100 Cr ... are not read" | one threshold, as the reader applies it | read the threshold from the reader's config; keep the two statuses apart |
| M12 | filings_read.py:290-291 | "Still to come" list: `''.join(...)[:1800]` cuts an HTML string at 1,800 characters: broken tags, items silently dropped (against "never half a document") | cut by item count and say how many are left out | `items[:N]` + "and k more" |
| M13 | brief.py:121; filings_read.py:595-600 | Brief "Filings read" uses `since = ref` (insider as-of); reads are written through the day, so the card holds several days; only the first 40 cards drawn (LIMIT), no "40 of N" | "since {date}, 40 of N" | pass the brief's session window; print the count |
| M14 | store.py:71, 81, 89, 103; ctx.py:54 | ctx is a `cache_resource` (600 s) built from `cache_data` tables (600 s), prices (600 s), price history and artifacts (1,800 s): after the nightly write a page can mix new trades with prices / track summary from the previous run for up to 30 minutes, and ctx itself can be up to 20 minutes behind R2 | one cache generation keyed on `clean/latest.json` (run id) | key every cached read on the run id from `latest()` |
| M15 | filings.py:97 | Filings read period counts from IST wall clock; every other page counts from `ref` | one rule (as M1: backward windows from the data's date) | |
| M16 | track_record.py:124-127 | Forward record header "median excess 1M x% (n cases)" pools every signal (buy and sell signals together) | per signal, or drop the pooled figure | |
| M17 | track_record.py:48, 3-5 | Tile "Entry: Next close" | PRODUCT.md (timing rules): entry = that session's close when broadcast well before the close, else next open; next close is the cautious variant. Either track.py measures only the cautious variant (then say so) or the page understates | check in the `track.py` review; label "cautious entry (next close)" |
| M18 | track_record.py:83-84 | size-matched benchmark uses "today's size bucket" (look-ahead on size), disclosed only in a caption | bucket at the event date | upstream (`track.py`) |
| M19 | company.py:57-58; screener.py:66, 81; today.py:47; filings_read.py:159-164 | market cap from three sources (security master with no date, trade-row market cap, NSE last session) | one market cap with its date | use `prices.market_cap` + `last_date` everywhere, fall back with a tag |
| M20 | today.py:36-41 vs filings_read.py:120, 162 | size class from `securities.mcap_category` on Latest session, from `prices.mcap_bucket` (our NSE rank) on Filings read | one size class | `mcap_bucket` everywhere |
| M21 | ui/table.py:76-106 | spark "1Y price · insider trades" and its % = last / first close of the history inside 365 days (a recent listing shows a short-period move as 1Y) | "1Y" only with a close 365+ days back (as `_moves`) | return None for chg when `d[0] > d[-1] - 330 days` |
| M22 | transfers.py:40-41 | tiles: sum of `value` per group; ESOP / gift rows often have no value, so NaN sums print "Rs 0"; Pledges group has no tile (`[:4]`) | "—" when no row has a value; count of rows with value | `min_count=1` and kit.rupees(None) |
| M23 | actions.py:96-100 | "Insiders buying after a big fall" takes the top 60 buyers by % of mcap, then filters price: qualifying buyers beyond 60 are missed | filter, then rank | `actions.buying(..., limit=None)` then filter |
| M24 | brief.py:132-137 | "Open-market trades of Rs 25 L and up" per filing row: three Rs 20 L tranches of one person (Rs 60 L) are left out, one person can take three rows | tranches combined per person and side, as Latest session does (`session_by_company`) | reuse `session_by_company(e, day)` |
| M25 | coming.py:8-18 | "Coming next" lists ICDR minimum, QIPs and buyback price/route as not collected | they are built (Capital raises) | remove the page or update items (page is hidden; low traffic) |

### 3.3 Cosmetic, incl. crash risk (C)

| ID | file:line | Issue | Fix |
|---|---|---|---|
| C1 | brief.py:110 | "last 7 days" uses `seen >= day - 7`: 8 days | `>` |
| C2 | company.py:86 | `pct_off_high` NaN prints "+nan% from 52W high" | guard with `_finite` |
| C3 | company.py:230 | aside "{len(events)} events" while `timeline(limit=80)` draws 80 | "80 of N" |
| C4 | company.py:92-96 | tiles show "Rs 0" and "0.000%" when there is no activity (no activity reads as zero net); "Directors & KMP net" lacks "12 months" | "No open-market trades in 12 months"; add the window |
| C5 | capital_raises.py:242-253 | "Upcoming board meetings" includes meetings from 7 days before ref | title "Board meetings, from last week" or start at today |
| C6 | capital_raises.py:271 + 262 | default Corporate actions kinds include buyback, so each buyback shows in the Buybacks card and again here | drop buyback from the default |
| C7 | insider_trades.py:57 | lag "1 sessions after the trade", "0 sessions after the trade" | `kit.sessions_text` |
| C8 | screener.py:81 | market cap `f'₹{m / 1e7:,.0f} Cr'` (western grouping) beside kit.rupees (Indian grouping above Rs 1,000 Cr) | `kit.rupees(m)` |
| C9 | ui/table.py:223-224 | a number column with no value in the shown rows is dropped silently (headers change with filters); a column whose key is missing entirely is kept as all dashes (W6) | keep the header, show "—"; assert keys exist |
| C10 | ui/table.py:240 + table.css:19, 67 | iframe height = 40 + 53 px x rows (+18 per flagged row); rows with a sub line or wrapped tags are taller and on phones the padding changes, so frames get inner scroll or blank space | let the frame size itself (postMessage height) or move tables out of iframes (section 5) |
| C11 | today.py:242, 252 | empty texts "in the latest session" / "latest deal session" while the window can be 5 sessions or 22 days | use `when` |
| C12 | brief.py:148 vs actions.py:57; brief.py:158 vs actions.py:130 | Brief excludes the ref day from meetings (`>`) and lock-ins (`> 0`), Actions includes it | one rule |
| C13 | sast.py:27, 30-33 | `action_type == 'Both'` counted as a sale | three-way split |
| C14 | track_record.py:44-47 | "Events measured" span = first `day` to last `entry_date` (two different columns) | one column |
| C15 | company.py:22-27 | company picker lists only companies with an open-market trade; deal-only / SAST-only / shareholding-only companies only by URL | list from securities |
| C16 | filings_read.py:466 | `price.get('market_cap') or r.get('market_cap')`: NaN is truthy, so the read's own market cap is never the fallback and the size line silently disappears | `_finite(...)` check |
| C17 | filings_read.py:495 | `at.tz_convert(None).normalize()` normalises in UTC; `seen` is an IST date: a filing between 00:00 and 05:30 IST shifts the 30-day window by a day | convert to IST first |
| C18 | brief.py:86; today.py:205, 239; company.py:71; deals.py:76; entity.py:37 | `d['client_is_market_maker']` used without the `if ... in d` guard `signals` uses: KeyError if the column is absent (crash risk) | one `ctx.real_deals` frame built once |
| C19 | filings_read.py:229, 299, 520 | `pd.Timestamp(x).tz_convert(...)` assumes tz-aware `broadcast_at`; one naive value raises and the whole card grid fails (crash risk) | `pd.to_datetime(..., utc=True)` then convert |
| C20 | track_record.py:32 | `beat:.0f` with `beat` None raises (sized, missing column) | guard |
| C21 | ui/insiders.css:16 vs table.css:3-4 vs charts.py:9-10 | `--buy` #0F7B4F in the page, #067647 in tables and charts; `--subtle` #F3F4F7 vs #F4F5F8, although table.css says "keep them equal" | one token source injected into both |
| C22 | ui/insiders.css:38, 42, 43, 240 | `stMainBlockContainer` padding set four times (one `!important`); `.rds` defined twice with different gap/min width (251, 269); empty rule (71) | dedupe |
| C23 | dead code / CSS: kit.topbar (kit.py:201-215) and its CSS (insiders.css:47-60), `kit.blank_text` (kit.py:28-33), `.tl-row`/`.tl-dot` (126-133), `.rd` card styles (251-267, only `.rd-held` used), `[data-testid="stDataFrame"]` (142, no st.dataframe on the site), `ctx.value_cr` (ctx.py:43-44, no page reads it) | remove |

### 3.4 Perf / memory on Streamlit Community Cloud (P)

| ID | file:line | Pattern | Fix |
|---|---|---|---|
| P1 | store.py:89-100 | `price_history()` is `st.cache_data` returning a dict of numpy arrays for every ISIN: each call unpickles the whole dict; it is called by every `with_sparks`, `pre_public_move`, company page, Brief, and Filings cards (several times per page run) | `st.cache_resource` (read-only) |
| P2 | store.py:71-73 + ctx.py:132-135 | `store.table()` (cache_data) returns a fresh deserialised copy per call; `with_flags` calls `store.table('tradability')` for every table (Actions up to 9x, Brief 5x, Latest session 4x); `preferential_lockins`, `qip`, `buybacks`, `promoter_group` likewise | put them in the shared ctx (cache_resource) once |
| P3 | insider_trades.py:47-57 | for the whole filtered set (Period "All" = every primary filing): two `iterrows` passes (late_text, window_text), `pre_public_move` Python loop, `with_sparks` builds an SVG per row, though 150 rows are drawn | sort, `head(150)`, then decorate; CSV from the undecorated frame |
| P4 | shareholding.py:52 | `with_sparks` over every company with a pattern (all rows), 300 drawn | head first |
| P5 | screener.py:77; deals.py:38, 57; entity.py:85 | same pattern, smaller sets | head first |
| P6 | ui/table.py:251-255 | `rows.to_csv()` plus a per-column `map(isinstance)` scan runs on every rerun for every table with `download=` (insider trades, deals, shareholding, capital raises x6) | `st.download_button(data=callable)` or a cached CSV per run id |
| P7 | filings.py:91-101, 145; filings_read.py:543-572 | every rerun (any filter click) concatenates the history table for long periods, sorts and groups all reads, all eligible trades and all results by company, then builds cards | cache the indexes per run id; only the page's cards |
| P8 | ui/table.py:241-246 | each table is a separate iframe document with the full table.css and a Google Fonts `<link>` (Actions: up to 9 frames; Capital raises: 9) | one CSS + font load (section 5) |
| P9 | brief.py:101-105 | text input value -> query param -> `st.rerun()` when the typed text differs from the normalised join; with a secrets watchlist (merged back into `watch`) or spaces after commas, the comparison can stay unequal on every run. Whether it loops depends on widget identity with a fixed `key` and a changing `value` on Streamlit 1.65: verify in a browser | compare normalised lists; set the param in an `on_change` callback, no `st.rerun()` |
| P10 | entity.py:22-25 | search concatenates all trades + deals id/name columns on every keystroke | cache the name index |

---------------------------------------------------------------------------------------------------

## 4. Verbosity (paragraph-length text that could be a tag or one line)

| file:line | First words | Could become |
|---|---|---|
| actions.py:66-67 | "What deserves a look now, from every filing we read. Each list gives..." | one line |
| actions.py:104-105 | "People who know the business paying up while the price is down..." | tag "Not measured" + one line |
| actions.py:118 | "Not measured on our data. Published studies treat heavy pledging..." | tag "Studies only" |
| actions.py:125 | "Shown so you can see where the crowd went, not as a buy list." | tag |
| actions.py:135 | "Lock-in lines as the company filed them, else the rule..." | tags "filed" / "rule" per row (already in `what`) |
| actions.py:140 | "A meeting is not a decision. Not measured on our data." | tag |
| actions.py:145-147 | "The evidence line is what happened to stocks after this kind of filing..." (3 sentences) | link to Track record |
| insiders_clean/evidence.py:20 (`CAVEAT`, on every Actions card) | ". Under a year of history, so a hint, not proof; the reasons below matter more." | the tag "Early read" already says it |
| brief.py:77 | "What the last session brought, before the 09:15 open, and anything..." | fine (one line) |
| brief.py:99-100 | aside "warnings from the last 7 days: insider sales, pledges, preferential shares to promoters below today's price" | three tags |
| brief.py:107-108 | "Add NSE symbols above; the page address keeps them, so bookmark it. Or set..." | placeholder text |
| screener.py:36-37 | "Where promoters are buying with their own money: 90 days, open market only, ranked..." | one line |
| screener.py:99-101 | "% of float is blank where the shareholding pattern is not loaded yet; the range is blank..." | column help |
| track_record.py:37-38 | "What stocks did after each kind of filing was made public: median return..." | one line |
| track_record.py:54-55 | note "Early read. Our measured history is about N months (...), one market phase. Treat every row..." | tag "Early read · N months" |
| track_record.py:61-62 | help "Leave out events where, on the day made public, the stock was trade for trade..." | fine as help |
| track_record.py:83-88 | "Size-matched: large caps against Nifty 100, ... Before public: ... Medians, not means: ... One year of history ..." (5 sentences) | column help + one tag |
| track_record.py:126-127, 149-151 | asides "recorded the night each signal fired since ..., never edited · median excess ..." / "paper portfolio, rules fixed in advance (version x): every forward-record signal with an "ahead" early read, no surveillance ..." | tags; rules behind a "Rules" disclosure |
| today.py:155-156 | "What insiders and big money did in the market lately. ESOPs, gifts, pledges and token buys are left out." | one line + tag |
| today.py:258-259 | "Token buys (under Rs 25 L in companies above Rs 5,000 Cr) and market makers are left out. % of float needs..." | tags |
| today.py:128, 274 | "Filed {d}. Promoters are left out here: their trades are in the insider filings above." / "Held back from every ranking and total until checked..." | tags |
| filings.py:89-90 | "NSE and BSE announcements read by the backend: what happened, the key terms and the figures, every number checked..." | one line |
| filings.py:148-150 | "Read by free models in the backend (NVIDIA, Z.ai, Groq, Gemini); a value is shown only when..." | footer link |
| filings_read.py:350-351 (coverage) | "Of N filings the reader looked at: ... A filing that was not read in full is never summarised from a part." | KPI strip (read / not read / below threshold) |
| filings_read.py:525-527 (LEGEND, on every card list) | "in the filing quoted word for word, table row found in one table of the filing, column not proven..." | tag tooltips |
| insider_trades.py:74 | "Every SEBI PIT filing, one row per trade: repeats and corrections removed." | fine |
| insider_trades.py:112-114 | "Lateness counts NSE trading sessions, not calendar days: the insider has 2 sessions..." | help on the "Filed late" tag |
| deals.py:22-23 | "Who sold, who absorbed it, and where real funds are accumulating. Market makers, who buy..." | one line + tag "no market makers" |
| deals.py:45-46, 63-65, 92-93 | "A promoter seller is recognised when ..." / "Companies under Rs 5,000 Cr market cap, last 30 days ... Studies find prices often run up ..." / "Same client, stock, day and side are one row; ..." | column help / tags |
| other_filings.py:13-14 | "Stake changes of 5% or more, and gifts, inter-se transfers, off-market deals, ESOPs and pledges. None of these..." | one line |
| sast.py:45 | aside "newest first · % of share capital as filed · NSE and BSE, a disclosure filed on both shown once" | tags |
| transfers.py:55-56 | "A gift or inter-se transfer moves shares between members of the promoter group..." | tab help |
| capital_raises.py:150-151 | "Who is about to raise money or buy back shares, and on what terms: dilution risk and..." | one line |
| capital_raises.py:133-137 (`link_summary`, under two tables) | "N allotment records: x matched to their approval (same ISIN, one approval in the 180 days before), y with more than one..." | a "matched x/N" tag |
| capital_raises.py:184-186 | "The filed minimum comes from the In-Principle XBRL and shows only on allotments matched..." | column help |
| capital_raises.py:196-197 | "The XBRL names each proposed allottee but not whether that allottee is a promoter..." | column help |
| capital_raises.py:205-207 | ""As filed": the lock-in lines in the company's listing XBRL, counted from..." | tags |
| capital_raises.py:232-233 | "From NSE's QIP filings, both stages. Floor price and discount are as filed..." | column help |
| capital_raises.py:281-284 | "Rights price = face value + the premium NSE lists; BSE's list gives no rights ratio or price. An action on both exchanges..." | column help |
| buybacks.py:206-209 | "Tender offers: price, shares sought and times tendered from NSE's tender-offer list. Open market: ..." (4 sentences) | route tag tooltips |
| company.py:133, 137-138 (tile notes) | "promoters hold x%, quarter ending ... · minimum public shareholding (SCRR 19A)" / "of 5% a year (SAST 3(2)) · x% bought on market since ..., estimated" | shorter notes, rule in help |
| company.py:264-265 | aside "N members named in the filing for the quarter ending ...; counted as one decision-maker in clusters" | one line |
| entity.py:38-39 | note "Market maker. This client buys and sells in near-equal amounts at high volume; its deals are liquidity..." | tag "Market maker" |
| data_status.py:45-68 | four "Data checks" paragraphs | a table: check / passed / held back / not checked |
| shareholding.py:16-17, 60-61 | "Each company's latest quarterly pattern: promoter and public holding, and how much..." / "Coverage grows nightly as more companies file and their XBRL is read (at most 300 a night)..." | one line; coverage as a KPI |
| coming.py:22-23 | "Datasets on the way. Each page is built once its data is collected and cleaned, never filled with guesses." | page can go (M25) |
| app.py:130-131 | footer "NSE and BSE disclosures, cleaned nightly · prices from the NSE and BSE daily bhavcopy, split and bonus adjusted · check the exchange filing before acting." | fine as footer |
| ctx.py:73-76 | "No clean data yet. The nightly cleaning step writes clean/current/ in R2; this page fills in after its first run." | fine (empty state) |

---------------------------------------------------------------------------------------------------

## 5. UI structure notes

How pages are built today
- One stylesheet `ui/insiders.css` (309 lines), injected per run by `theme.inject()` through `st.markdown` (st.html strips `<style>`), with comments and blank lines removed (theme.py:18-31). Tokens on `:root` (colours, radius, shadow, font, a 5-step type scale), no spacing scale.
- Page = vertical stack: `kit.head` (h1 + p via st.html), `kit.tiles` (CSS grid `repeat(auto-fit, minmax(200px,1fr))`, borders by `border-right`, so wrapped rows get wrong borders), `kit.card` = `st.container(key='card_x')` styled by the attribute selector `[class*="st-key-card_"]` (insiders.css:91), content inside cards with st.html strings.
- Tables: `kit.table` builds a full HTML document per table and renders it with `st.iframe` (table.py:241-246); the frame carries its own copy of tokens (`ui/table.css`), its own Google Fonts link, a click-to-sort script and a script that forwards link clicks to the parent page (SORT_JS) because the frame cannot navigate the top window. Height is computed in Python from a fixed 53 px row.
- Filters: `st.columns` (8 places: data_status.py:92, deals.py:71, filings.py:77, 107, 113, insider_trades.py:83, sast.py:37, today.py:201, plus table.py:248 for the caption + download row), `st.pills`, `st.segmented_control`, `st.toggle`, `st.selectbox`, `st.multiselect`, `st.text_input`, `st.tabs`, `st.expander`; charts are Altair (`ui/charts.py`, hard-coded colours, not the tokens).
- Card bodies are hand-written HTML in screens: Latest session spot cards (today.py:44-80), company ident/flags (company.py:49-63) and flow bars (company.py:153-159), timeline (`ui/timeline.py`), Filings read cards (`filings_read.py`, ~300 lines of f-string HTML with `rc-*` classes), track scorecard table (track_record.py:69-82), data checks rows, entity search list, coming list.
- Sidebar navigation is Streamlit's (`st.navigation`), restyled dark by `data-testid` selectors (insiders.css:218-239).

What blocks a flex/grid design system
1. Tables in iframes: a table cannot use the page tokens, page grid, or page fonts; every rule is duplicated (and already drifted, C21); inline row detail (plan Phase 5: "row detail that opens inline") needs frame resizing; links need the parent-click hack; heights are guessed (C10). Replacing iframes with st.html tables (sorting by a small component, or server-side sort via a control) is the largest single unblocker.
2. No page-level layout: each Streamlit element is its own block in Streamlit's flex column; a "header / KPI strip / main / side panel" grid cannot wrap Streamlit widgets (filters, tabs) together with st.html content. Grids exist only inside one st.html string (tiles, spot-grid, rds). A two-column desktop layout needs `st.columns` or keyed containers styled as grid via `st-key-*` selectors.
3. Styling hangs on Streamlit internals: `data-testid` selectors (stMainBlockContainer, stSidebarNavLink, stHeader, stToolbarActions, stPills ...) and the `st-key-*` class Streamlit derives from widget keys. Streamlit is pinned to 1.65.0 (streamlit_app/requirements.txt:4), which keeps this working, but any upgrade can break layout silently.
4. Three breakpoints (720 px insiders.css, 980 px topbar CSS, 640 px table.css and `.rds`) against the plan's single 768 px.
5. Hard-coded colours outside the tokens: #EDEFF3, #F0F2F5, #0B1324, #7C8AA5, #C8D1E3, #8A97B1, #E8F1FB, #1D4E89, #D9902A, #F4F2FF, #F8F9FD, #EEF0F4, #B5BCC7, #64748B, #94A3B8, gradient #F2D4D0/#E6E9EE/#CBEAD9, and in charts.py INK/INK3/LINE/BUY/SELL/PRICE, #F0F2F5, #C9CFD8.
6. Duplicate and dead CSS (C22, C23); `.spot .rg*` (insiders.css:160-166) duplicates table.css `.rg*` for the cards.
7. Inline CSS in screens is limited to data-driven widths (company.py:156 flow bars, kit.py:236 bar list, table.py:66, 151 range/size bars, table.py:244 frame height); no inline colours. The real scattering is HTML structure: class names invented per screen (`fl-*`, `spot-*`, `rc-*`, `tlx-*`, `sc-*`, `cm-r`, `q-row`, `evl`, `ident`) with no shared component for "card header", "KPI", "tag row", "list row".
8. Repeated building blocks a component set should own: page header with as-of date (each page writes its own caption with `kit.day(ref)`), real-deals frame (non-MM, primary: built in 6 places), latest shareholding / pledge (5 helpers), meetings ahead (4), lock-in calendar (3 calls), "vs market" (4 implementations: capital_raises._vs_market, buybacks.rows, today._card, filings_read.before_this).
9. Fonts loaded twice per page plus once per table frame, with different weight ranges (theme.py:12-15 Geist Mono 400..700; table.py:21-23 400..600).

Upstream notes (outside site scope, for the insiders_clean review)
- `pct_of_mcap` for trades and deals divides by the security master's market cap at clean time (insider.py:356, 365; deals.py:157-159), not the market cap on the trade day; every "% of mcap" on the site inherits it.
- `signals.company_board` promoter sums include token buys (W12); `as_of` includes held-back rows (W20); `track.summary` has no size-matched case count (W16).
