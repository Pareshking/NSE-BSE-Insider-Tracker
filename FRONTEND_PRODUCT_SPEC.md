# Frontend Product Specification — NSE + BSE Tracker

## Purpose

The web application is a quantitative research interface, not merely a scraper-output viewer. The frontend must make source provenance, freshness, date coverage, transaction semantics and validation status immediately understandable while keeping the raw exchange data available for audit.

The target is a **world-class, production-grade financial data frontend**: fast, clean, information-dense without being cluttered, mobile-friendly, keyboard-accessible, and explicit about what is verified versus merely acquired.

## Product principles

1. **Trust before decoration.** Every important number should have a source, timestamp and validation state.
2. **Exchange separation.** NSE and BSE are separate data systems. Never visually imply that a combined number is directly sourced from either exchange.
3. **Research-first workflow.** A user should reach a useful transaction/event table within seconds, then drill into evidence.
4. **Progressive disclosure.** Summary first; filters and advanced fields next; raw/native evidence on demand.
5. **No false precision.** If historical completeness is not certified, display that fact prominently.
6. **Native data preservation.** Advanced users must be able to inspect original exchange fields alongside normalized fields.
7. **Reproducibility.** Every result view should expose the effective date range, refresh timestamp and source/extraction status.
8. **Responsive by default.** Desktop gets dense research tables; mobile gets cards/compact rows with drill-down details rather than horizontal-table overload.

## Primary navigation

### 1. Overview

Landing dashboard showing:

- NSE status
- BSE status
- last successful acquisition timestamp
- requested versus actual coverage
- total records by category
- latest event date
- validation/certification badges
- warnings for incomplete or stale categories

The Overview must never present an uncertified dataset as production-ready.

### 2. Insider Activity

Dedicated NSE/BSE tabs, with an optional comparison mode only after cross-exchange matching is certified.

Default filters:

- date range
- exchange
- security/company
- ISIN/symbol/code
- person/entity
- person category
- acquisition/disposal
- buy/sell
- promoter-related category

Key table columns:

- transaction date
- disclosure/broadcast date
- company/security
- person/entity
- person category
- acquisition/disposal
- buy quantity
- sell quantity
- buy value
- sell value
- mode/type
- source

Promoter activity must be shown from the source classification, never inferred from positive quantity alone.

### 3. Bulk Deals

Separate NSE and BSE views.

Filters:

- date range
- security
- client
- BUY/SELL
- quantity/value thresholds

Default table:

- deal date
- security
- client
- direction
- quantity
- price
- value where available
- exchange
- source status

### 4. Block Deals

Same interaction model as Bulk Deals, but explicitly labelled as Block Deals.

The UI must not merge Bulk and Block executions simply because their fields look similar.

### 5. Rights Issues

Lifecycle-oriented interface rather than a transaction table.

Show:

- company/security
- ISIN/code
- issue status
- record date
- rights ratio
- offer price
- issue open/close
- entitlement dates
- allotment
- shares
- amount raised
- listing/trading approval
- submission date
- source update time

Multiple lifecycle records for one issue must be visually grouped so users do not mistake updates for multiple issues.

### 6. Preferential Issues

Lifecycle-oriented interface with:

- company/security
- ISIN/code
- board resolution
- allottee category
- consideration
- offer price
- shares/allotment
- amount
- lock-in
- listing/trading approval
- submission date
- source update time

Again, lifecycle updates must not inflate the apparent number of issues.

### 7. Data Quality / Validation

This is a first-class page, not a developer-only screen.

For each exchange/category show:

- acquisition status
- validation status
- source/API used
- requested range
- actual range
- distinct dates
- record count
- records by date
- duplicate count
- critical-null count
- last successful run
- last source comparison
- known limitations

Use clear states:

- **VERIFIED / CERTIFIED**
- **WORKING / PENDING VALIDATION**
- **FAILED / BLOCKED**

Do not show a green state merely because GitHub Actions succeeded.

## Evidence drill-down

Every table row should support an evidence drawer/modal containing:

- normalized fields
- native exchange fields
- source identifier
- raw source date fields
- acquisition/disclosure/broadcast dates separately
- source/API name
- extraction timestamp
- duplicate/match status where applicable

For advanced audit, expose the original raw payload or a safe structured representation rather than forcing users to inspect application logs.

## Global filter bar

A persistent filter bar should provide:

- Exchange: NSE / BSE / Both
- Category
- Date range
- Search
- Advanced filters
- Reset

The effective filters should remain visible when navigating between pages.

Do not silently retain filters that materially change the result set; provide a clear active-filter indicator.

## Data freshness and provenance

Every page should display a compact provenance strip:

`Source → Extraction time → Requested range → Actual coverage → Validation state`

Example concept:

`NSE API · 09:42 IST · 90-day request · 84 distinct dates · VERIFIED`

If actual coverage differs from requested coverage, show the discrepancy explicitly.

## Table design benchmark

The main research tables should support:

- sticky header
- sortable columns
- column visibility
- compact/dense mode
- readable number formatting
- date formatting with unambiguous locale-independent representation where appropriate
- export of the currently filtered dataset
- row expansion
- pagination or virtualization for large datasets
- empty-state explanations
- loading skeletons
- clear error states

Avoid decorative charts when a table or metric is more useful.

## Dashboard visual hierarchy

The first screen should answer five questions immediately:

1. Is the data fresh?
2. Which exchange/category is healthy?
3. What is the latest activity?
4. What period is actually covered?
5. Can I trust this dataset for analysis?

Recommended hierarchy:

**Header → data-health strip → key metrics → latest activity → category cards → validation/provenance → deeper analytics.**

## Quantitative analytics layer

After source certification, the frontend may provide:

- promoter net acquisition
- promoter buying/selling trends
- largest bulk/block transactions
- concentration by security/client
- event counts over time
- rights/preferential issue pipeline
- cross-exchange matched events

These analytics must clearly distinguish:

- raw transaction count
- unique economic event count
- lifecycle update count

Do not calculate investment signals from uncertified or incomplete historical data without a visible warning.

## Cross-exchange UX

Before cross-exchange certification, do not present NSE+BSE as deduplicated combined truth.

After certification, comparison views may show:

- same economic event
- exchange-specific execution
- duplicate disclosure
- unmatched NSE record
- unmatched BSE record

The user must be able to drill from a matched event back to both native source records.

## Error and limitation UX

Errors must be actionable.

Bad:

`No data found.`

Preferred:

`No records were returned for this 30-day request. The source responded successfully, but historical date control has not been certified for this category.`

If an exchange blocks automated access, show:

- source unavailable
- last successful acquisition
- affected category
- whether cached data exists
- whether the dataset is safe for analysis

Never silently fall back to stale data.

## Performance target

The frontend should feel immediate for normal research interactions:

- cached dashboard render: target <2 seconds
- filter interaction: target <1 second where data is local/indexed
- large table: progressive rendering rather than blocking the whole page
- source refresh: asynchronous with visible status

These are product targets, not certification claims. Measure them once the frontend is implemented.

## Accessibility

Target WCAG 2.2 AA principles:

- keyboard navigation
- visible focus state
- semantic labels
- sufficient contrast
- non-colour-only status indicators
- screen-reader-friendly controls
- responsive text sizing
- accessible tables and expandable rows

## Mobile UX

On mobile:

- preserve the global filter/search controls
- convert dense tables into compact cards or expandable rows
- keep transaction date, company/security, direction/type and value visible first
- expose native fields through an expandable evidence section
- avoid requiring horizontal scrolling for core research tasks

## Visual design direction

The product should look like a professional institutional research terminal rather than a generic Streamlit demo.

Characteristics:

- restrained visual language
- strong typographic hierarchy
- generous spacing around major sections
- dense but readable data tables
- subtle borders/dividers
- consistent number/date formatting
- restrained use of colour only for semantic status
- no excessive gradients, oversized cards or decorative illustrations

The visual system should remain consistent across Overview, Insider, Bulk, Block, Rights, Preferential and Data Quality.

## Security and trust

Never expose:

- credentials
- cookies
- API secrets
- internal request headers containing sensitive tokens

Source evidence may show endpoint/service names and non-sensitive request metadata, but secrets must never reach the frontend.

## Frontend acceptance gates

Before calling the website production-ready:

[ ] all five categories have dedicated views
[ ] NSE/BSE separation is explicit
[ ] global filtering works
[ ] effective date range is visible
[ ] actual date coverage is visible
[ ] freshness is visible
[ ] certification status is visible
[ ] native/raw evidence is drillable
[ ] transaction semantics are explicit
[ ] promoter semantics use source categories
[ ] lifecycle events are grouped correctly
[ ] duplicate/match status is explainable
[ ] exports respect active filters
[ ] loading/error/empty states are polished
[ ] mobile layout is usable
[ ] keyboard/accessibility checks pass
[ ] no secrets are exposed
[ ] performance targets are measured
[ ] frontend displays warnings for uncertified/incomplete data

## Relationship to backend certification

The frontend must consume backend validation metadata rather than inventing trust states.

Backend certification remains the authority.

The frontend is responsible for making that evidence understandable and auditable.

No UI polish can upgrade a backend category from yellow/red to green.

## Visual reference concepts

Two visual concepts have been saved in the repository as design references. They are **directional mockups, not screenshots of the implemented application and not evidence of backend certification**.

### Concept A — Research Terminal

`docs/frontend-concepts/frontend-concept-a.svg`

Design intent:
- strong left navigation
- exchange/date controls at the top
- KPI strip
- dominant research table
- right-side date coverage and quality panel
- trend chart
- source/evidence panel
- explicit provenance and certification language

This is the more conservative institutional-terminal direction.

### Concept B — Analytics Terminal

`docs/frontend-concepts/frontend-concept-b.svg`

Design intent:
- faster visual scanning
- persistent search
- transaction/category tabs
- top-company analytics
- validation/evidence center
- date-coverage panel
- stronger separation between research data and analytics
- explicit pending/verified states

This is the more analytics-heavy direction.

### Recommended product direction

Use **Concept B as the starting visual benchmark**, while adopting Concept A's strongest evidence/provenance treatment.

The final implementation should not copy either mockup literally. It should combine their best properties into a coherent product system:

**institutional research-terminal discipline + modern analytics UX + first-class source evidence.**

The final UI should remain restrained. Avoid turning the product into a decorative dashboard. The primary interaction is research: find an event, understand it, verify it, and export it.

## Visual QA gates

Before frontend implementation is considered complete:

[ ] desktop layout reviewed at 1440px+ width
[ ] tablet layout reviewed
[ ] mobile layout reviewed
[ ] table density is readable at normal zoom
[ ] primary actions are visually obvious
[ ] source/certification status is impossible to confuse
[ ] warnings are visible without being alarmist
[ ] evidence drawer is usable without losing table context
[ ] charts never obscure the underlying data
[ ] no invented sample numbers are shown in production
[ ] loading/empty/error states follow the same design system
[ ] all colors have semantic meaning and are not the sole status signal
[ ] final UI matches the documented visual benchmark
