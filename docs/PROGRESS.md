# Progress
- Phase 0 approved; Phase 1 in progress on `ccr-27a6c75f-o9ztpa` (PR #11 draft; nothing merged to main, per Gate 2).
- Done: acquisition-probe neutralised; pandas 3 fix; round trips flagged not dropped; 2026 product window in the clean layer; write-once raw store (insiders_clean/raw_store.py) + nightly raw capture/flush (unit-tested, not yet run in production); backfill `--redo`; deals recovered (+6,460 bulk, 0 block; flags verified); flag-as-text bug fixed; data inventory + power numbers recorded in docs/AUDIT.md (run 37902086767). 107 tests green.
- Known hazard: `main` nightly clean ignores the flag until this branch merges, so clean/deals will include recovered round-trip legs (old app does not read it).
- Open decisions for the owner: (1) run R2 Storage Write on this branch to exercise raw capture in production (writes to prod R2), (2) move nightly bulk/block to the CSV endpoint (70-row cap), (3) when to merge (Gate 2).
- Next: revision fields (prevAppId/typeOfSubmission) in the insider collector; native bhavcopy price layer + corporate-action adjustments; point-in-time market cap; data-health view.
