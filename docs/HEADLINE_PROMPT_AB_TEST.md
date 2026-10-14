# Announcement headline prompt A/B evaluation

## Purpose

Compare the existing `live-4` headline instructions (baseline) with the opt-in `live-5` prompt (v2) on the same current NSE/BSE filing candidates. This is an evaluation only: do not publish v2 output to R2 before it has been reviewed and accepted.

## Run the comparison

1. Open **Actions → Announcement reader → Run workflow** on branch `experiment/headline-prompt-v2`.
2. Set `max` to `3` for the initial low-cost comparison.
3. Set `dry_run` to `true`.
4. Run once with `prompt_variant = baseline`; wait for the run and download its `announcement-reader-dry-run` artifact.
5. Run again immediately with `prompt_variant = v2`; keep `max = 3` and `dry_run = true`; download the second artifact.
6. Compare the records by `event_id`. If the selected event IDs differ, do not score the pair as a controlled A/B; rerun close together with the same settings.
7. Review each filing's source quote and headline/points, not just the generated wording. The workflow summary and artifact include model answers, shown/held-back reasons and prompt version.

The workflow rejects a v2 dispatch unless `dry_run=true`. Dry runs do not write the reads archive, clean parquet or usage log to R2. Baseline comparison runs use the temporary prompt version `live-4-ab`; v2 uses `live-5`. These versions only force re-reading for the experiment and are not written to production during a dry run.

## Scorecard

Score each headline against the filing text, without seeing which prompt produced it where practical:

- **Action clarity (0–2):** does it say what actually happened, rather than describe the filing process?
- **Decision-status accuracy (0–2):** does it preserve approved/recommended/proposed/deferred/rejected/noted status?
- **Evidence fidelity (0–2):** is the headline supported by its attached quote?
- **Numerical fidelity (0–2):** are amount, price, stake, dates and units supported?
- **Specificity (0–2):** does it include the most material disclosed terms without becoming cluttered?
- **Abstention correctness (0–2):** does it leave the headline empty rather than invent an event when the text is insufficient?

Record unsupported claims and material omissions separately. A prompt is not better if it improves style while introducing any material factual error. Three filings are a smoke test only; expand to a reviewed sample spanning board outcomes, fund-raising, acquisitions/divestments, operating updates/results, dividend/capital actions and legal/regulatory events before deciding to adopt v2.

## Safety and acceptance gates

- The current `CARD_ASK` remains the baseline; v2 is opt-in via `CARD_PROMPT_VARIANT=v2`.
- Existing quote, number and unit validators remain unchanged.
- No change to category taxonomy, candidate selection, read-once logic, model lanes, or production R2 writes is part of this experiment.
- Do not merge or change the production default solely because the v2 wording looks better. Require green CI, matching event IDs for each A/B pair, human review of source evidence, and no regression in factual accuracy or coverage.
