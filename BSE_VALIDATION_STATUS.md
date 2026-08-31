# BSE Validation Status

## Active rule
BSE validation is independent of NSE. The legacy combined workflow is diagnostic only.

## Current gate
Run BSE Insider, Bulk and Block over a 90-day window. Certify only after inspecting actual distinct dates, row counts, native source columns, completeness/pagination behaviour and intra-BSE duplicates.

Current acquisition evidence from prior runs: Insider 146 unique records, Bulk 73 records, Block 17 unique records, Rights 50 records, Preferential 125 records. These are not historical certification.

Rights and Preferential remain pending-detail extraction and do not block testing/carrying forward the working Insider/Bulk/Block acquisition.

## Mandatory loop
**test -> inspect real output -> identify defect -> fix -> retest -> verify -> update documents -> continue**.
