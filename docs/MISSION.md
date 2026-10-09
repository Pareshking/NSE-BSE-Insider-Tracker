# Claude Code Master Prompt — Insiders Research Platform

Oct 9, 2026 · @Paresh Patel

## 1. Role, context and objective

Rebuild my Indian insider and institutional-activity app into an evidence-based research tool that helps a small investor make better risk-adjusted decisions.

Act as a quantitative researcher specialising in Indian market microstructure, a data engineer, a Python architect and a product designer. Meet the standards of all four.

- **Production app:** https://insiders.streamlit.app/
- **Work repository:** `Pareshking/NSE-BSE-Insider-Tracker` (https://github.com/Pareshking/NSE-BSE-Insider-Tracker). It is public, so never commit holdings, watchlists or other personal data to it. Before anything else, confirm with `git remote -v` that this is the repo open in Claude Code; if it isn't, stop and tell me.
- **Separate project, read-only data source only:** `Pareshking/Paresh` is my NSE momentum-ranking app and serves a different purpose. Never write to it. You may read its price snapshots, market-cap history and security mappings as an unverified candidate source; its NSE 750 universe probably misses many stocks in insider and bulk-deal disclosures.

I invest in NSE- and BSE-listed equities as an individual. The current app works, but its information architecture, naming, data cleaning, signal quality and presentation are poor.

**Objective.** Find out which publicly disclosed transaction information — alone, combined, or conditioned on market context — genuinely helps an individual investor decide better. Measure "better" as risk-adjusted, net-of-cost returns against appropriate benchmarks. Then present it so I can act with the right level of confidence.

This is a research objective, not a guaranteed outcome. "No reliable edge in X" is a valid and valuable result. Assume no signal works until our own evidence supports it.

**In scope (candidates, not obligations):**

- SEBI PIT disclosures by promoters, promoter group, directors, KMP and designated persons.
- SAST acquisitions and disposals; pledge and encumbrance creation, release and invocation.
- Bulk and block deals on NSE and BSE; identifiable institutional accumulation and exits.
- Shareholding-pattern changes and other public disclosures (buybacks, preferential allotments and warrants, open offers, results dates, surveillance lists) where they add decision value.

**Non-goals:** maximum transaction counts, maximum charts, or a generic financial dashboard.

You have broad creative and architectural freedom, including replacing most or all of the current implementation when evidence supports it. That freedom is not permission to discard working components, destroy data or make unverified production changes.

## 2. Operating standards

Every material claim you make must be traceable, labelled and checked against primary evidence.

1. **First principles.** Don't assume the current tabs, scripts, data model, scoring or naming are right — or that anything in this prompt is optimal. Establish what information exists, what can be reliably inferred, what is missing and what an individual can act on. Design around the questions the data can answer.
2. **Documentation is evidence, not a constraint.** Read docs, comments, configs and tests first, then verify their claims against code, data and production behaviour. Challenge, replace or extend them when evidence supports it.
3. **Label claims.** In every report and doc, tag material claims as VERIFIED (checked against a primary source, actual data or code), ESTIMATED (computed, with assumptions stated), CLAIMED (from docs or a secondary source, not yet checked) or HYPOTHESIS.
4. **Flag contradictions immediately** — between docs and code, code and data, two sources, or this prompt and the evidence. Never silently pick a side.
5. **Never build on unverified inputs.** Never invent column names, endpoints, regulation text, citations, sample sizes or results. If something can't be verified, say what is missing.
6. **Primary sources first.** For regulations and disclosure formats, use current SEBI, NSE and BSE texts plus amendments, not secondary summaries. Indian evidence outranks international evidence; international findings only generate hypotheses.
7. **Uncertainty stays visible.** Missing or ambiguous information never becomes a confident bullish or bearish conclusion.
8. **Simple and robust beats clever and fragile** — in code, in signals and in the UI.

## 3. Hard rules and approval gates

Decide routine matters yourself and log the reasoning in `docs/DECISIONS.md`; stop for my explicit approval only at these seven gates.

1. Leaving Phase 0 (section 5).
2. Pushing or merging to the branch Streamlit Community Cloud deploys from (every change there redeploys production), or changing deployment settings.
3. Deleting or overwriting existing data files, scrapers, workflows or branches. Never rewrite shared git history or force-push.
4. Creating tokens or secrets for read access to `Pareshking/Paresh`. Never write to that repo; it is a separate project.
5. Fetching or storing pre-2026 transaction disclosures (section 6.3).
6. Adding paid services, new secrets, broader GitHub Actions permissions, or dependencies that call new external services.
7. The final cut-over from the old app to the new one.

Always:

- Work on a dedicated branch with small, logical commits and clear messages; open PRs for review.
- Keep secrets out of code, logs and commits; use `st.secrets` and GitHub Actions secrets.
- Respect each source's terms of use and rate limits. If a source blocks requests (for example, exchange sites refusing cloud IP addresses), report it with evidence instead of escalating retries.
- Never present a partially failed data run as complete.

## 4. Working method for a long, multi-session project

Keep all project state on disk so a new session or a context compaction can resume without losing anything.

- `docs/MISSION.md` — this prompt, verbatim. If it is not in the repo yet, add it in your first commit after Phase 0 approval. Don't edit it; propose changes in `DECISIONS.md`.
- `CLAUDE.md` — short standing instructions only: repo map, setup, test, run and pipeline commands, the hard rules in section 3, and pointers to `MISSION.md` and `PROGRESS.md`. Keep it short; a bloated file gets ignored.
- `docs/AUDIT.md` — Phase 0 findings.
- `docs/RESEARCH.md` — regulatory and literature evidence, pre-registered hypotheses and results.
- `docs/DECISIONS.md` — each decision with alternatives considered, evidence, date and how to reverse it.
- `docs/PROGRESS.md` — current phase, done, next, blockers and open questions for me. Update it at the end of every work block; on resume, read `CLAUDE.md` and `PROGRESS.md` first.
- `docs/DATA_DICTIONARY.md` — every source and field: meaning, unit, timezone, provenance and known quirks.

Also:

- Run code against real data instead of reasoning about what the data probably looks like.
- Use parallel sub-agents for independent investigations if available (for example, literature search and source-format analysis). Verify and consolidate their output yourself.
- Ask me questions only at an approval gate or when the choice is genuinely mine (preferences, risk appetite, access). Batch them; don't drip them.

## 5. Phase 0 — Repository, deployment and data archaeology (read-only)

Understand the current system completely before changing anything; Phase 0 ends with a written audit and a stop.

Read-only means no edits, deletions, commits or pushes of tracked files, and no changes to GitHub or deployment settings. You may create new files under `docs/` (`AUDIT.md`, `PROGRESS.md`), use a local virtual environment, run existing code and tests, and keep exploratory scripts in a gitignored scratch folder.

**5.1 Git and GitHub**

- `git status` (staged, unstaged, untracked), current branch, `git branch -a`, remotes, default branch and tags.
- Significant history: merges, reverts and abandoned approaches.
- PRs in every state, review comments and linked issues — via `gh` if installed and authenticated; otherwise from local git evidence, stating what is missing.
- GitHub Actions: workflows, schedules, permissions, referenced secrets, artifacts and recent runs, including failures and their causes.
- Classify each branch and PR as canonical, useful unfinished work, duplicate, abandoned or risky. Compare conflicting implementations before choosing one.

**5.2 Deployment**

- Streamlit entrypoint, deployed branch, Python version, dependencies, `.streamlit/` config, and how data reaches the app (committed files, release assets, runtime fetch or external storage).
- If the deployed branch can't be determined from the repo, ask me — it is set in Streamlit Community Cloud, not in git.
- Compare what production shows with what the source should produce. Streamlit Cloud renders the app inside an iframe, so automated checks must read the inner frame.
- Record current Streamlit Community Cloud constraints from official documentation: resource limits, ephemeral filesystem, sleep behaviour and redeploy triggers.
- The repository is public; check whether the app is publicly reachable too. This is a personal tool for my use only, so report how to restrict access to me before any personal data is stored.

**5.3 Code and documentation**

- Read the existing planning and status documents first, including `PROJECT_PLAN.md`, `ANALYTICS_PLAN.md`, `DATA_ACQUISITION.md`, `DATA_VALIDATION_AND_DEDUP_PLAN.md`, `FRONTEND_PRODUCT_SPEC.md`, `FRONTEND_UI_BLUEPRINT.md`, `VALIDATION_STATUS.md`, the `BSE_*.md` notes and `docs/frontend-concepts/`. Then verify each claim against the code and data; they may be outdated or aspirational.
- Read the code, configs and automation: `scripts/`, `streamlit_app/`, `reference_data/`, `artifacts/`, `.github/workflows/`, `.streamlit/` and `requirements.txt` — scrapers, parsers, cleaning, scoring, UI, tests and CI.
- Establish the provenance and use of one-off committed files such as `stock-screener-01-Sep-2026--1932.xls`. A single dated snapshot must never stand in for point-in-time history.
- Trace the real flow: source → ingestion → parsing → entity resolution → cleaning → deduplication → classification → enrichment → analytics → storage → UI.
- Mark where raw values are lost, records duplicated, fields misread, assumptions applied silently or logic implemented twice.

**5.4 Actual data**

- Inventory every data file: format, size, date range, schema, row counts, completeness, update cadence and repository growth.
- Sample every disclosure category and every edge case you can find: amendments, the same filing on NSE and BSE, malformed rows, multi-day date ranges, zero or blank prices, unit errors and ambiguous entities.
- Separate fields genuinely present from fields the code merely expects.

**5.5 `Pareshking/Paresh` — separate project, read-only, optional**

- Establish access without modifying anything.
- Document what it actually holds: price and market-cap history, universe, date range, adjustment status (splits, bonuses, dividends), schema, cadence, provenance, and whether delisted names survive.
- Measure coverage against the securities in our 2026 disclosures: share of events and of traded value with usable price history. Evaluate alternatives for the gaps, such as official exchange bhavcopy archives.

**5.6 Sample size and statistical power**

- Count 2026 events by category, and how many have complete forward-return windows at each candidate horizon as of today.
- Estimate the smallest effect each horizon could detect. State plainly whether 2026-only data, covering a single market regime, can validate any signal yet.

**5.7 Deliverable, then stop**

Write `docs/AUDIT.md` and give me a summary covering:

1. Current architecture and end-to-end data flow.
2. Source inventory and actual field coverage.
3. Features and assets worth preserving.
4. Bugs, duplicate logic and data-quality weaknesses, with examples.
5. Relevant branches, PRs and prior attempts.
6. Deployment facts and constraints.
7. Price, market-cap and security-master data, including Paresh coverage.
8. Sample-size and power findings.
9. Research questions the data can and cannot answer.
10. Proposed target architecture, alternatives considered and why they lost.
11. Staged implementation and validation plan.
12. Risks, access limitations and the decisions you need from me.

Then stop and wait for my approval.

## 6. Scope and time boundaries

The app shows transactions from 1 January 2026 onwards; supporting market history may go further back, and pre-2026 disclosures need my approval.

**6.1 Product transaction scope**

- The product dataset holds transactions dated on or after 1 January 2026. No legacy transactions in the app, its aggregates, searches, exports or signals.
- Keep these distinct: transaction date or date range, date of intimation to the company, exchange dissemination timestamp (IST), source publication date, ingestion time and last update.
- Edge case: trades before 1 January 2026 that were disclosed in 2026. Apply the transaction-date rule by default, report how many records are affected, and recommend a rule.
- Test the boundary explicitly: 31 December 2025 versus 1 January 2026, and timestamps near midnight IST.

**6.2 Supporting market history**

- Supporting data is not limited to 2026. Use the minimum earlier price, corporate-action, market-cap, shareholding and pledge baseline, index and classification history needed for valid 2026 context: 52-week ranges, trailing returns, volatility and estimation windows.
- Never substitute today's values for historical ones. Label anything that is not genuinely point-in-time.

**6.3 Pre-2026 disclosures for research validation**

**My decision: NOT PERMITTED for now.** If your power analysis shows 2026 data cannot validate signals, recommend an option and ask me.

If I approve, that data is stored separately, used only offline to test pre-registered hypotheses, and never loaded into the app.

## 7. Research programme

Research before choosing any signal, threshold, score or page; the research must change design decisions, not decorate them.

**7.1 Questions (extend freely)**

- Are open-market purchases by insiders and promoters informative in India? Are sales?
- Do non-market acquisitions (ESOPs, preferential allotments, warrants, gifts, inter-se transfers) carry any information?
- Does breadth (several independent insiders) or persistence (repeat buying) matter, after collapsing promoter-group entities that act as one decision-maker?
- Does relative size matter: versus the insider's existing holding, market cap and average daily traded value?
- Does context matter: position in the 52-week range, drawdown, momentum, size, liquidity, proximity to results, market regime?
- Routine versus opportunistic trades: trading-plan or habitual trades versus unusual ones.
- Pledges: creation, release, invocation, and the level of pledged holdings.
- Bulk and block deals: participant type, net direction after same-day netting, short-term drift versus reversal, and supply overhang after block sales.
- Ownership context: distance to the 75% promoter ceiling implied by minimum public shareholding, creeping-acquisition headroom, and institutional trends in shareholding patterns.
- Disclosure timing: actual lags, late filings, and how much the price moved before dissemination.
- Indian candidate edges, as hypotheses only: promoter warrant or preferential subscriptions priced above market; promoters staying out of buybacks; steady creeping acquisitions; pledge release after promoter buying; insider buying right after the post-results trading window opens; "marquee investor" bulk deals followed by retail herding.
- What costs, liquidity and execution limits (circuits, trade-for-trade, SME lot sizes) do to any edge.

**7.2 Indian regulatory grounding — verify each against current primary text**

- SEBI (PIT) Regulations, 2015: continual disclosures (Reg 7, Form C), trading plans (Reg 5), trading-window and contra-trade rules (Schedule B), system-driven disclosures, and amendments in force during 2026.
- SEBI (SAST) Regulations, 2011: Reg 29 acquisition and disposal disclosures, Reg 31 encumbrance disclosures, Reg 10 exemptions including inter-se transfers, Reg 3(2) creeping acquisitions.
- SEBI LODR: quarterly shareholding patterns and pledge disclosures.
- Minimum public shareholding (SCRR Rule 19A) and its effect on promoter buying and selling.
- SEBI circulars on bulk and block deals, including any revisions to the block-deal window framework.
- NSE and BSE surveillance (ASM, GSM, ESM), price bands, trade-for-trade, SME platforms and market-making.
- Corporate actions, ISIN changes, mergers and demergers, buybacks, preferential issues and IPO lock-in expiries.
- Statutory transaction charges and taxes that affect net returns.

**7.3 Literature — search widely, verify everything, Indian evidence first**

Search SSRN, NSE and SEBI research publications, IIM and ISB working papers, and peer-reviewed journals. These starting anchors are mostly US evidence; confirm each exists and says what you cite before relying on it.

- Insider trading: Seyhun (1986); Lakonishok & Lee (2001); Jeng, Metrick & Zeckhauser (2003); Cohen, Malloy & Pomorski (2012) on routine versus opportunistic trades; Alldredge & Blank (2019) on clustering.
- Event-study methods: Brown & Warner (1985); MacKinlay (1997); Kolari & Pynnönen (2010); Barber & Lyon (1997); Mitchell & Stafford (2000) on calendar-time portfolios.
- Overfitting and multiple testing: Harvey, Liu & Zhu (2016); Bailey & López de Prado (2014) on the deflated Sharpe ratio.
- Indian factor data: IIM Ahmedabad's Indian Fama-French-Momentum factor library (Agarwalla, Jacob & Varma). Check it is available and current.

**7.4 `docs/RESEARCH.md` format**

For each entry record: question or hypothesis; source, date and URL or DOI; market and sample; method; findings, including contradictory evidence; applicability to India; implementation implication; validation needed.

Separate published findings from your interpretation. Keep an evidence table: hypothesis → literature → Indian evidence → our data → decision. Never fabricate papers, citations, returns or sample sizes.

## 8. Data sources

Add a source only when it answers a research question or supports a decision I make; document each in `docs/DATA_DICTIONARY.md`.

Candidates to evaluate after the audit:

- NSE and BSE PIT, SAST and pledge disclosures, including system-driven disclosures if published.
- Bulk and block deals from both exchanges.
- Quarterly shareholding patterns.
- Corporate announcements: results dates, buybacks, preferential issues and open offers.
- Corporate actions: splits, bonuses, rights, mergers, demergers, and symbol and ISIN changes.
- Surveillance lists: ASM, GSM, ESM and trade-for-trade.
- Daily bhavcopies (prices, volumes and delivery data) for complete NSE and BSE coverage.
- AMFI's semi-annual market-cap categorisation, as point-in-time size buckets.
- Index constituents and sector classification.
- Monthly mutual-fund portfolio disclosures, if feasible.

For each, record availability, history depth, format stability, reliability when fetched from GitHub Actions, terms of use and maintenance cost. Prefer official bulk files and archives over scraping rendered pages.

## 9. Canonical data model

Preserve every source faithfully, resolve entities conservatively, and make every analytic number traceable to its raw disclosure.

**9.1 Layers and provenance**

- Keep an immutable raw layer (exact payloads and files, with fetch metadata), a cleaned layer and an analytics layer. Never overwrite the only copy of an original disclosure.
- Retain where available: source and URL, filing ID, exchange, regulation and form type, security name, symbol, BSE code, ISIN, transaction date range, intimation date, dissemination timestamp, buy/sell and acquisition/disposal flags, quantity, price, value and units, mode, pre- and post-holdings (number and %), person or entity name, category and designation, relationship to the issuer, client name, amendment references, ingestion time and processing version.
- Keep source-specific fields. Don't force different disclosure types into one lossy schema.

**9.2 Security and entity resolution**

- Separate the issuer (company) from the security (listed instrument). Map ISIN, NSE symbol and BSE code with full history: symbol and name changes, mergers, demergers and ISIN changes (verify when these occur, for example after face-value changes).
- Normalise person and institution names conservatively. Never merge on name similarity alone; send uncertain matches to a review queue shown in the data-health view.
- Link promoter-group members using shareholding-pattern disclosures where available — as supported evidence, not assumption.

**9.3 Deduplication, amendments and idempotency**

- Re-ingesting the same data must give identical outputs and no duplicate signals.
- Detect the same disclosure filed on both NSE and BSE; keep one canonical record carrying both references.
- Never drop genuinely separate transactions because their fields match. Use source IDs first and carefully designed fingerprints second.
- Model originals, revisions, corrections and withdrawals by the actual source semantics, and keep lineage to the raw record.

**9.4 Classification confidence**

Tag each classification as confirmed by source, strongly supported, probable, ambiguous, missing information, or excluded with a reason code. A heuristic never masquerades as a source fact.

## 10. Cleaning, validation and false-positive control

Keep everything in the canonical data and exclude per analysis, with documented, reversible reason codes and visible counts.

**10.1 Validation checks (examples — design the full set from the data)**

- Holdings arithmetic: post-holding minus pre-holding should equal the reported quantity, with the right sign.
- Implied price (value ÷ quantity) against that day's traded range: flags off-market deals, unit errors (rupees versus lakhs or crores) and swapped fields.
- Zero or blank consideration, negative values, impossible dates (disclosure before trade, future dates) and multi-day date ranges.
- Holdings disclosures that are not trades (for example, on appointment) mistaken for transactions.
- Quantities and prices on either side of splits and bonuses.

**10.2 Insider and promoter transactions**

Distinguish where the data allows: open-market purchases and sales; ESOP grants, exercises and allotments; preferential allotments, warrants and conversions; gifts, inheritance, and family or inter-se promoter transfers; trust and holding-company restructuring; off-market deals; pledge creation, release, invocation and other encumbrances; buyback tenders; corporate-action and scheme-driven changes; and unknown consideration.

Directional-conviction research focuses on genuine open-market trades made with the insider's own money. Other categories stay available for ownership, governance and risk analysis.

Indian structural non-signals to identify: promoter sales made to meet minimum public shareholding; offers for sale; IPO lock-in expiries; inter-se transfers, often accompanied by SAST exemption filings; and several promoter-group entities executing one family decision — count that as one decision-maker in breadth metrics.

**10.3 Bulk and block deals**

- Detect intraday churn by behaviour: the same client, security and day on both sides with net quantity near zero, plus short multi-day round trips. Don't rely on a hard-coded list of firm names; keep a reviewable, data-derived classification of frequent two-sided participants.
- Bulk and block disclosures do not show whether a client took delivery. Netting a client's own disclosed trades, same-day and across nearby days, is the only client-level evidence; security-level delivery percentage is context, never attribution.
- Flag SME market-maker activity, listing-day deals and negotiated block sales (promoter or private-equity exits) separately.
- Normalise institution names (fund house versus scheme, FPI entities and sub-accounts) with an auditable mapping. Classify participant type — mutual fund, insurer, FPI, PMS/AIF, proprietary/HFT, corporate, individual — with confidence levels.
- Any "marquee investor" list is a hypothesis to test, not a default scoring input.

**10.4 Liquidity, tradability and surveillance**

Flag rather than silently drop: ASM, GSM and ESM stages, trade-for-trade, SME platform, circuit-locked or suspended days, low traded value and very small market caps. Thresholds must come from analysis, be documented, and live in configuration.

## 11. Signal research and validation

A signal reaches the app only with point-in-time inputs, honest benchmarks, net-of-cost results and a visible evidence status.

**11.1 Point-in-time discipline (mandatory)**

- Signal time is the exchange dissemination timestamp (IST). Entry is the first price I could realistically have traded at afterwards: with daily data, the same day's close for disclosures well before the close, otherwise the next session's open. Report the next session's close as a conservative variant. Never use the transaction date or the insider's price.
- No feature may use data published after the signal time. Write tests that enforce this.

**11.2 Evaluation design**

- Abnormal returns against several benchmarks: broad market (Nifty 500 or wider), size-matched (small- and micro-cap indices or size-sorted portfolios) and sector; factor-adjusted where Indian factor data is available. Report all of them; never cherry-pick.
- Horizons such as 5, 20, 60, 120 and 250 trading days. Count only complete windows and show N beside every statistic.
- Robust inference: handle overlapping windows and same-date event clustering, with calendar-time portfolios as a robustness check. Report confidence intervals, medians and dispersion, hit rates and drawdowns — not just means.
- Net of costs: verified statutory charges plus liquidity-dependent spread and impact estimates. Report gross and net; optionally illustrate the after-tax effect of short holding periods.
- Tradability: flag events where entry was infeasible.
- Survivorship: keep delisted and suspended securities.
- Time-ordered splits only, with a hold-out period left untouched until final evaluation.
- Pre-register each hypothesis and its test in `RESEARCH.md` before running it. Log every variant tried and adjust for multiple testing.
- Report power. When a test cannot detect a plausible effect, the result is "insufficient evidence", not "works" or "fails".

**11.3 From features to signals**

- Prefer a few robust, interpretable signals over a complex composite. A composite score is allowed only if it beats its simplest components out of sample, with transparent weights.
- Give every signal a visible status: validated in our data (out of sample), supported by literature but not yet validated here, exploratory, or rejected.

**11.4 Forward-test ledger**

- Keep an append-only ledger of every signal as generated: timestamp, rule version, input snapshot and reference entry price, with outcomes filled in later.
- Never edit past entries; a rule change starts a new series.
- This is our honest out-of-sample record, and the app must show it.

## 12. Product and UI

Design around my decisions, not around data sources or tabs; you choose the final pages, names and layout.

Likely jobs to serve:

1. What is new and noteworthy since I last looked — ranked by evidence strength, with the reason in plain language.
2. Alerts for stocks I hold or watch — from a watchlist or holdings list (symbols or ISINs) that persists between visits. Store it only where it stays private, such as Streamlit secrets or a private repository — never in a public repo or artifact.
3. Single-stock deep dive — the full 2026 disclosure timeline against price and ownership, each event linked to its source filing.
4. Signal evidence — how each signal has performed (N, horizons, benchmarks, costs, confidence intervals, status), plus the forward-test ledger.
5. Data health and methodology — freshness, coverage, exclusions by reason, unresolved entities, known limitations and exports.

Requirements:

- Plain, self-explanatory names. Every page answers one clear question; anything that doesn't support a decision goes.
- Every number traces back to its source disclosure.
- Show uncertainty: classification confidence, evidence status and sample sizes.
- Show how far the price has already moved since dissemination.
- This is a personal tool for my own investment decisions, not a public product. Make outputs directly actionable — ranked candidates, clear action labels and risk flags — without generic disclaimers. Every label still shows its evidence status, so an exploratory signal never looks validated.
- Fast, and comfortable on a phone as well as a desktop.

## 13. Engineering and deployment

Separate a scheduled data pipeline from a read-only app, and prove every change with tests before it reaches production.

- The pipeline runs on a schedule (for example, GitHub Actions) and publishes validated artifacts. The app only reads them and never scrapes on page load.
- Choose storage formats by measurement (for example, Parquet or DuckDB versus the current format): memory, cold-start time and repository growth. If committed data bloats the repo, consider a data branch or release assets.
- Classification rules and thresholds live in versioned, tested configuration, not scattered literals.
- Use `Pareshking/Paresh` data read-only, pinned to a documented schema and version, validated on read, with graceful degradation when it is unavailable.
- Tests: real-sample fixtures for every source and edge case; classification rules; idempotency (ingest twice, identical output); amendments; date boundary and timezone; no look-ahead; app smoke tests (for example, Streamlit's AppTest); production QA that reads the app's inner iframe. CI must pass before any merge.
- Observability: each run records counts in and out, exclusions by reason, failures and freshness. The app shows stale or failed data openly.
- Performance: measure cold start, page load and peak memory against current Streamlit Community Cloud limits.
- Migration: run old and new pipelines in parallel, write a reconciliation report explaining differences, test on a staging branch or app, cut over only at gate 7, and keep a rollback path.

## 14. Phases and definition of done

Work through six phases in order, each ending with a written report; only Phase 0's exit and the cut-over need my approval, plus any gate a step triggers.

1. **Phase 0 — Audit** (read-only), then stop for approval.
2. **Phase 1 — Data foundation:** sources, raw layer, canonical model, entity resolution, cleaning, validation, data-health reporting and tests.
3. **Phase 2 — Evidence:** market context, evaluation framework, pre-registered signal research and the forward-test ledger.
4. **Phase 3 — Product:** rebuild the app on a staging branch or staging app.
5. **Phase 4 — Launch:** reconciliation, performance, documentation, then cut-over at gate 7.
6. **Phase 5 — Operate:** a maintenance runbook and a schedule for re-evaluating signals.

Done means:

- The pipeline runs reliably on schedule, with tests and CI green.
- Every displayed number traces to a source disclosure.
- The app is fast and within resource limits.
- Research conclusions, including what didn't work, are documented with honest evidence strength.
- The forward-test ledger is running and visible.
- I can operate and maintain the system from the runbook alone.

## 15. Reporting and start

Report at the end of every phase, then begin Phase 0 immediately.

- Each phase report: what changed and why, evidence with VERIFIED / ESTIMATED / CLAIMED / HYPOTHESIS labels, test results, open issues and next steps. Concise, with no marketing language.
- Final report: file map, how to run and maintain everything, known limitations, and research conclusions including what failed.

**Start now:** Phase 0, read-only. First confirm with `git remote -v` that the open repo is `Pareshking/NSE-BSE-Insider-Tracker`. Then begin with `git status`, branches and recent history, followed by documentation, code, data and deployment, and finally `Pareshking/Paresh` as a read-only data source.
