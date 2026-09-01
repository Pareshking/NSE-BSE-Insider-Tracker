# Frontend UI Blueprint — NSE + BSE Insider & Corporate Event Tracker

## Status

Design blueprint / implementation reference.

This document converts the approved visual direction into a sufficiently explicit specification that another AI, engineer or frontend team can implement the interface without needing access to the original mockup.

The reference direction is a **pure-white/light institutional research terminal** with restrained blue primary actions, subtle borders/shadows, high information density and first-class evidence/provenance.

The visual mockups are illustrative only. Sample numbers, company names, people and validation states shown in mockups must never be copied into production data.

---

# 1. Product character

The website should feel closer to a professional market-data/research terminal than a generic dashboard.

Primary qualities:

- white canvas
- clean blue primary accent
- dark navy/charcoal typography
- very light neutral panel backgrounds
- thin borders
- restrained shadows
- compact but readable tables
- semantic green/red/amber status accents
- minimal decoration
- high information density
- obvious source provenance
- evidence-first interaction

Do NOT use a dark dashboard as the default.

Do NOT use large decorative gradients.

Do NOT use excessive glassmorphism.

Do NOT use oversized KPI cards that consume the majority of the screen.

Do NOT make charts more prominent than the underlying data.

The interface should look credible to an equity researcher, quant, portfolio manager or data engineer.

---

# 2. Global application shell

Desktop target: 1440px–1920px wide.

Recommended structure:

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ Global Header                                                                 │
│ Logo | NSE/BSE | Date Range | Search | Evidence | Alerts | Theme | User       │
├───────────────┬──────────────────────────────────────────────────────────────┤
│               │                                                              │
│ Persistent    │ Main Content                                                │
│ Sidebar       │                                                              │
│               │                                                              │
│ Overview      │ Page Header                                                  │
│ Transactions  │ KPI / health strip                                           │
│   Insider     │ Tabs                                                         │
│   Bulk        │ Filters                                                      │
│   Block       │ Main table / lifecycle view                                  │
│ Actions       │ Secondary analytics / evidence                              │
│   Rights      │                                                              │
│   Preferential│                                                              │
│               │                                                              │
│ Analytics     │                                                              │
│ Data Quality  │                                                              │
│ Validation    │                                                              │
│ Downloads     │                                                              │
│ API Docs      │                                                              │
│               │                                                              │
│ System Status │                                                              │
└───────────────┴──────────────────────────────────────────────────────────────┘
```

The sidebar is persistent on desktop and collapsible on tablet.

On mobile it becomes a drawer/bottom navigation pattern.

---

# 3. Header

The global header is always visible on desktop.

Left-to-right:

1. Product logo/name
2. Exchange selector
3. Date-range selector
4. Optional saved/custom range selector
5. Global search
6. Evidence Center
7. Alerts
8. Theme/preferences
9. User/settings

## Exchange selector

Use a segmented control:

`NSE | BSE`

Optional `Both` becomes available only when cross-exchange matching is sufficiently validated.

The selected exchange must be visually obvious.

Do not silently mix NSE and BSE records.

## Date selector

Display both the selected period and the duration.

Example:

`02 Jun 2026 – 31 Aug 2026 (90D)`

Support:

- 1D
- 7D
- 30D
- 90D
- custom

The application must separately display:

- requested range
- actual returned range

If these differ, show a warning.

## Global search

Placeholder:

`Search company, symbol, person, promoter, ISIN...`

Search should support:

- company
- symbol
- ISIN
- security code
- person/entity
- client
- promoter category
- source identifier

Keyboard shortcut may be `Ctrl/Cmd + K`.

## Evidence Center

Opens a centralized audit/evidence view containing recent source captures, validation results and source comparisons.

## Alerts

Only show meaningful data-quality or pipeline alerts.

Examples:

- historical range incomplete
- source unavailable
- stale data
- duplicate anomaly
- validation regression

---

# 4. Sidebar navigation

## Overview

Landing page / health summary.

## Transactions

### Insider Trading

Expandable navigation item.

Subfilters may include:

- Promoter Acquisition
- Promoter Disposal
- Other Insider Transactions

### Bulk Deals

### Block Deals

## Corporate Actions

### Rights Issues

### Preferential Issues

## Analytics

### Trends & Charts

### Top Movers / Top Companies

### Promoter Activity

### Cross-Exchange View

Cross-Exchange remains disabled or marked Beta/Unavailable until backend certification permits it.

## Data & Trust

### Data Quality

### Validation & Evidence

### Downloads

### API Documentation

## System Status

Compact card at the bottom of the sidebar:

- system operational state
- last data fetch
- link to details

The system status must distinguish application health from data certification.

---

# 5. Overview page

The Overview page is designed to answer five questions within seconds:

1. Is the data fresh?
2. Which categories are healthy?
3. What is the latest activity?
4. What period is actually covered?
5. Can I trust the data for analysis?

## Top health/KPI strip

Five category cards:

- Insider Trading
- Bulk Deals
- Block Deals
- Rights Issues
- Preferential Issues

Each card contains:

- record/event count
- comparison metric if meaningful
- freshness
- certification state
- small trend sparkline where appropriate

A sixth card:

`Overall Data Quality`

must NOT be a simple average unless the methodology is documented.

## Main overview region

Recommended layout:

```text
┌──────────────────────────────────────┬──────────────────────┐
│ Latest Activity / Primary Table      │ Date Range Coverage  │
│                                      │ Data Quality         │
│                                      │ Quick Filters        │
└──────────────────────────────────────┴──────────────────────┘
┌──────────────────────────┬────────────────────┬────────────────┐
│ Activity Trend           │ Top Companies      │ Recent Events  │
└──────────────────────────┴────────────────────┴────────────────┘
┌──────────────────────────┬────────────────────┬────────────────┐
│ Data Sources             │ Exchange Match     │ System Status  │
└──────────────────────────┴────────────────────┴────────────────┘
```

The latest-activity table remains the primary information surface.

---

# 6. Category page pattern

All five categories use the same shell but different domain-specific internals.

Standard sequence:

```text
Page title
↓
Provenance / health strip
↓
Category tabs/sub-tabs
↓
Filter bar
↓
Result count + active filters
↓
Primary data table or lifecycle board
↓
Analytics / summary panels
↓
Pagination / virtualization
```

---

# 7. Insider Trading page

## Category tabs

```text
Insider Trading | Bulk Deals | Block Deals | Rights Issues | Preferential Issues
```

Insider sub-tabs:

```text
Promoter Acquisition (Buying)
Promoter Disposal (Selling)
Other Insider Transactions
```

The first two are not inferred from quantity. They are driven by source person/category and transaction semantics.

## Filter row

Recommended controls:

1. Company
2. Person / Entity
3. Person Category
4. Mode
5. Transaction Type
6. Buy / Sell
7. Date Range
8. Advanced Filters

Advanced filter drawer:

- quantity min/max
- value min/max
- promoter / promoter group / PAC
- acquisition / disposal
- pledge / ESOP / gift where supported
- source
- verification state
- duplicate/match state

## Primary table

Column order:

1. Date
2. Company
3. Symbol / ISIN
4. Person / Entity
5. Person Category
6. Type
7. Buy/Sell
8. Quantity
9. Price
10. Value
11. Mode
12. Exchange
13. Source
14. Match
15. Row actions

Date columns must clearly distinguish transaction date from disclosure/broadcast date.

## Row interaction

Clicking a row opens an evidence drawer from the right.

The table remains visible behind the drawer.

---

# 8. Insider evidence drawer

Header:

`Insider Transaction Evidence`

Sections:

### Summary

- company
- security
- person/entity
- category
- transaction type
- buy/sell

### Dates

Display separately:

- transaction date
- disclosure date
- broadcast date
- source timestamp

### Quantities / values

- buy quantity
- sell quantity
- price
- buy value
- sell value

### Source

- exchange
- source endpoint/service
- source record identifier
- extraction timestamp

### Native fields

Expandable raw/native-field table.

### Validation

- validation state
- duplicate state
- cross-exchange match state if enabled
- explanation

### Raw evidence

Safe structured representation of the original payload where permitted.

Never expose credentials/cookies/secrets.

---

# 9. Bulk Deals page

Filters:

- date
- security
- client
- direction
- quantity
- value
- price range

Table:

- deal date
- security code
- security name
- symbol
- client
- BUY/SELL
- quantity
- price
- value
- exchange
- source
- evidence

Bulk and Block must remain visually and logically separate.

---

# 10. Block Deals page

Same shell as Bulk but with explicit Block Deal identity.

Additional UI:

- duplicate explanation
- execution grouping where source rendering creates repeated rows
- source row identity

Do not automatically treat repeated HTML-rendered rows as repeated economic transactions.

---

# 11. Rights Issues page

Rights are lifecycle objects, not simple transactions.

Primary visual model:

```text
Company / Issue
      ↓
Announcement
      ↓
Record Date
      ↓
Rights Ratio / Price
      ↓
Issue Open
      ↓
Issue Close
      ↓
Entitlement
      ↓
Allotment
      ↓
Listing / Trading Approval
```

Each issue should have a lifecycle card/timeline.

## List columns

- company
- symbol/code
- ISIN
- issue status
- record date
- rights ratio
- offer price
- issue open
- issue close
- shares
- amount
- latest lifecycle date
- source

## Detail drawer

Show every lifecycle stage separately.

Do not count each stage as a separate Rights Issue.

---

# 12. Preferential Issues page

Same lifecycle concept as Rights.

Primary detail sections:

- company/security
- ISIN/security code
- board resolution
- allottee category
- consideration
- offer price
- shares/allotment
- amount
- lock-in
- listing
- trading approval
- submission date
- latest source update

Use a lifecycle timeline and event history.

Do not inflate issue counts from repeated lifecycle updates.

---

# 13. Persistent provenance strip

Every category page must have a compact provenance strip near the top.

Structure:

`Source → Last Fetch → Requested Range → Actual Coverage → Validation`

Example:

`NSE API · 31 Aug 2026 07:15 IST · 90D requested · 84 dates returned · VERIFIED`

This example is illustrative only.

If the actual range is incomplete:

`Requested: 90D | Actual: 12D | INCOMPLETE`

The warning should be visible without opening another page.

---

# 14. Data Quality page

This page is a first-class user feature.

Matrix:

| Exchange | Category | Records | Requested | Actual | Distinct Dates | Duplicates | Critical Nulls | Freshness | Validation |
|---|---|---:|---|---|---:|---:|---:|---|---|
| NSE | Insider | ... | ... | ... | ... | ... | ... | ... | ... |
| NSE | Bulk | ... | ... | ... | ... | ... | ... | ... | ... |
| BSE | Insider | ... | ... | ... | ... | ... | ... | ... | ... |

Each row opens detailed evidence.

## Quality dimensions

- completeness
- accuracy/source agreement
- consistency
- timeliness
- duplicate rate
- critical-field completeness

Do not manufacture an overall quality score if the underlying methodology is not defined.

---

# 15. Validation & Evidence page

This is the audit centre.

Tabs:

```text
Runs | Source Comparison | API Evidence | Schema | Duplicates | Coverage | Errors
```

## Runs

Show:

- workflow
- run ID
- commit
- start/end
- status
- categories tested
- artifact links

## Source Comparison

For each category:

- source record count
- pipeline record count
- count difference
- date distribution difference
- representative row comparisons
- explanation

## API Evidence

Show first-party service names and non-sensitive request metadata.

BSE examples:

- BulkDeal_Beta
- BlockDeal_Beta
- getCorp_Regulation_ng
- Pubissues_FurtherIssuesummary_RI_isd_ng
- Pubissues_FurtherIssuesummary_Pref_isd_ng
- Pubissues_FurtherXbrlview_pref_ng

The UI must distinguish:

`Discovered`
`Integrated`
`Tested`
`Validated`

These are not interchangeable states.

---

# 16. Analytics pages

Analytics are secondary to raw research.

Potential modules:

### Promoter Activity

- net buy value
- gross buy value
- gross sell value
- transaction count
- company ranking
- time trend

### Trends

- daily/weekly/monthly event count
- buy vs sell
- transaction value
- category mix

### Top Companies

Rank by:

- transaction value
- transaction count
- promoter net activity
- bulk/block activity

### Cross-Exchange

Only enabled after both exchanges are certified and matching logic is validated.

---

# 17. Cross-exchange view

When enabled, use explicit labels:

- Matched economic event
- Exchange-specific execution
- Duplicate disclosure
- NSE only
- BSE only
- Partial match

A matched event should expand into:

```text
Economic Event
├── NSE native record
└── BSE native record
```

Never destroy the original exchange records.

---

# 18. Downloads

Export controls should respect active filters.

Formats:

- CSV
- JSON

Optional later:

- Excel

Export metadata should include:

- exchange
- category
- requested date range
- actual date range
- extraction timestamp
- validation state
- applied filters

Do not imply that an uncertified export is production-certified.

---

# 19. Search results

Global search should show grouped results:

```text
Companies
Persons / Entities
Insider Transactions
Bulk Deals
Block Deals
Rights Issues
Preferential Issues
```

Each result displays:

- exchange
- category
- date
- key identifier
- validation state

---

# 20. Status language

Use consistent status labels.

### Green

`VERIFIED`

or

`CERTIFIED`

### Amber

`WORKING`

`PENDING VALIDATION`

### Red

`FAILED`

`BLOCKED`

### Informational

`DIAGNOSTIC`

`SOURCE UPDATE`

Never use green merely because acquisition succeeded.

---

# 21. Colour system

Default visual system should be white/light.

Recommended semantic roles:

- primary action: blue
- primary text: dark navy/charcoal
- secondary text: muted slate
- border: very light grey/blue-grey
- verified/success: restrained green
- warning/pending: amber
- failure: red
- information: blue

Colour must never be the only status signal.

Every status should also have:

- text
- icon where useful
- accessible label

---

# 22. Typography

Use a modern, highly legible sans-serif.

Hierarchy:

- page title: strong but not oversized
- section title: medium/semibold
- table header: compact uppercase or strong small text
- body: highly readable
- numeric columns: tabular numerals

Numbers should align consistently.

Currency should use Indian formatting where appropriate:

`₹1,23,45,678`

but raw machine values must remain accessible in evidence/export.

---

# 23. Tables

Tables are the most important UI component.

Requirements:

- sticky header
- sortable columns
- filterable columns where useful
- column visibility
- compact mode
- row hover state
- keyboard row navigation
- expandable/evidence action
- pagination or virtualization
- selected-row state
- loading skeleton
- empty state
- error state

Do not hide critical source/semantic information behind excessive interaction.

Recommended default visible columns should fit a 1440px viewport without requiring horizontal scrolling for the primary research fields.

Secondary/native fields can be exposed through evidence.

---

# 24. Empty states

Never simply say:

`No data.`

Use contextual explanations.

Example:

`No records returned for this period.`

Then show:

- source
- requested range
- actual range
- last successful fetch
- whether historical date control is certified

If the source returned zero legitimately, say so only when that has been established.

---

# 25. Loading states

Use skeletons that preserve page geometry.

For long source refreshes:

- show acquisition stage
- show elapsed state
- do not freeze the entire application

Example:

`Fetching BSE Bulk Deals...`

then:

`Parsing 90-day response...`

then:

`Validating date coverage...`

---

# 26. Error states

Errors should explain:

- what failed
- source
- last successful result
- whether cached data is available
- whether cached data is safe to use
- recommended next action

Never silently replace failed live data with stale data.

---

# 27. Mobile layout

Mobile is a research companion, not a miniature desktop table.

Keep visible first:

- date
- company/security
- transaction type
- BUY/SELL or lifecycle status
- quantity/value
- validation state

Then expandable details:

- person
- category
- source
- native fields
- dates
- evidence

Core workflows must not require horizontal scrolling.

---

# 28. Responsive breakpoints

Suggested behaviour:

### Large desktop

Persistent sidebar + dense tables + multi-panel dashboard.

### Tablet

Collapsible sidebar + fewer simultaneous secondary panels.

### Mobile

Drawer navigation + cards/expandable rows + single-column analytical modules.

Do not merely shrink desktop components.

---

# 29. Accessibility

Target WCAG 2.2 AA.

Required:

- keyboard navigation
- focus indicators
- semantic controls
- accessible tables
- accessible drawers/modals
- screen-reader labels
- non-colour status indicators
- sufficient contrast
- touch targets large enough for mobile

---

# 30. Performance

Targets:

- cached overview: <2s perceived render
- local filter interaction: <1s target
- table virtualization for large datasets
- lazy-load heavy analytics
- asynchronous source refresh
- avoid blocking the UI on validation jobs

Measure these after implementation.

---

# 31. Trust model

The frontend must expose three separate concepts:

### Acquisition

Did we receive data?

### Validation

Does the data satisfy the source/date/schema/semantic checks?

### Certification

Has the category passed all defined acceptance gates?

These must never collapse into one generic `Success` badge.

---

# 32. Backend-to-frontend contract

The frontend should receive explicit metadata such as:

```text
exchange
category
requested_start
requested_end
actual_start
actual_end
distinct_dates
record_count
duplicate_count
critical_null_count
source
source_service
last_fetched_at
validation_state
certification_state
limitations
```

For records:

```text
native_fields
normalized_fields
source_record_id
transaction_date
disclosure_date
broadcast_date
match_state
duplicate_state
```

The frontend must not calculate certification itself from record count.

---

# 33. Security

Never expose:

- cookies
- authentication headers
- API keys
- secrets
- private infrastructure identifiers

Source evidence may expose safe endpoint/service names and non-sensitive request metadata.

---

# 34. Visual benchmark

The final frontend should visually resemble a **clean white institutional market-data terminal**.

Reference composition:

```text
Header
────────────────────────────────────────────────────────────────
KPI cards: Insider | Bulk | Block | Rights | Preferential | Quality
────────────────────────────────────────────────────────────────
Category tabs                                      Coverage panel
Filter row                                         Quality panel
────────────────────────────────────────────────────────────────
                    PRIMARY DATA TABLE
────────────────────────────────────────────────────────────────
Trend chart              Top companies              Alerts
────────────────────────────────────────────────────────────────
Sources                  Match status               Recent activity
```

The table is the hero component.

The right-side panels are trust/context components.

Charts are supporting analytical components.

---

# 35. Design principles borrowed from both concepts

Concept A contributes:

- institutional restraint
- evidence drawer emphasis
- strong source/provenance hierarchy
- clear date-coverage presentation

Concept B contributes:

- faster analytics scanning
- stronger category tabs
- better global search
- stronger top-company/trend modules
- more visible validation/evidence centre

The final product combines both.

---

# 36. Pure-white theme decision

The pure-white/light theme is now the preferred default.

Reasoning:

- better long-session readability
- more familiar for financial/research web applications
- stronger table contrast
- cleaner printed/exported screenshots
- easier distinction between data and status colours
- more professional and less visually heavy than the earlier dark concept

A dark theme may be offered later as an optional user preference, but it is not the primary design benchmark.

---

# 37. Implementation order

Frontend implementation should proceed in this order:

1. Application shell
2. Header
3. Sidebar
4. Overview
5. Insider table + evidence drawer
6. Bulk table
7. Block table
8. Rights lifecycle view
9. Preferential lifecycle view
10. Data Quality
11. Validation & Evidence
12. Downloads
13. Analytics
14. Cross-exchange view only after backend gate
15. Mobile optimisation
16. Accessibility audit
17. Performance audit
18. Visual regression testing

Do not implement cross-exchange analytics as trusted production functionality before backend cross-exchange certification.

---

# 38. Frontend acceptance test

A frontend implementation is not complete until a reviewer can answer the following without reading source code:

- Which exchange am I viewing?
- What date range did I request?
- What date range was actually returned?
- How fresh is this data?
- Is this category certified?
- Where did this row come from?
- What does BUY/SELL or acquisition/disposal actually mean?
- Is this person a promoter according to the source?
- Is this row duplicated?
- Is this event matched to the other exchange?
- Can I see the native source fields?
- Can I export exactly what I filtered?
- What happens if the source is unavailable?
- What happens if historical coverage is incomplete?

If the interface cannot answer these questions, it is not yet a world-class research frontend.
