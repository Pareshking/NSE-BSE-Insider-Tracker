# Announcement reader: state and plan (13 Oct 2026)

Where the announcement reader stands, so any session can pick it up. TODO item
29 points here. Code: `collectors/nse_events/announcements.py` (collector, no
model), `scripts/announcement_sample.py` (model test harness),
`scripts/announcement_sample_expected.json` (24 filings read by hand),
`scripts/announcement_sample_run.txt` (what the next test run reads),
workflows `announcements.yml` (nightly counts) and `announcement-sample.yml`
(model test). All on PR #56, branch `ccr-5fbf9503-x2spo0`, not merged.

## Decisions (owner, 13 Oct)

- Models run only in the backend (GitHub Actions); the site never calls a
  model, it reads the tables the backend writes. No chat box on the site.
- Keys live only in GitHub Actions secrets: `GEMINI_API_KEY` (its own AI
  Studio project), `GROQ_API_KEY`, `NVIDIA_API_KEY` (valid 6 months from
  13 Oct 2026: renew by early Apr 2027, same secret name; an expired key
  shows as "key refused (HTTP 401) ... renew the GitHub secret"),
  `ZAI_API_KEY` (added 13 Oct). Never in the repo or Streamlit secrets.
- Only public filing text goes in a prompt; nothing personal.
- Models get extracted text (`pdftotext -layout`, ZIPs opened), never PDFs.
- Every value must carry a quote found in the PDF text, and prices and counts
  must have their digits in the quote; otherwise it is held back, never shown.
  The model gives numbers as written with their unit; our code converts
  (lakh, crore, million, billion) and computes every % change.
- Use free limits up to 95%, through the day (every 30 minutes), not only
  at night; today's filings first with ~150 reads in reserve.
- The Brief (`/brief`) becomes the hub: every critical and useful filing,
  crisp and tactical for the next day (style: equisense cards), with "before
  this" from our own archive and our own data (dilution, promoter holding and
  pledge, issue price vs CMP, size vs market cap, insider and deal activity).
  No "impact" labels; gaps flagged neutrally (Avonmore: filing says ~214%,
  its own numbers give +114%).
- Concall announcements are not collected (08 Oct decision).
- Stocks below Rs 100 Cr market cap: their PDFs do not go to a model.
  **Open:** should they also be hidden across the site? (owner to answer)

## Model test results (13 Oct, 24 filings, 91 values)

Run 38423386748, one job per model in parallel, rescored with the 13 Oct
checks (numbers written with their currency read once; table quotes marked
`table`, weaker than `exact`, since they cannot prove the column).

| Reader | Right | Held back | Not sent | Seconds a filing |
|---|---|---|---|---|
| NVIDIA `moonshotai/kimi-k3` | **88 of 91** | 1 | 0 | 29 |
| NVIDIA `google/gemma-4-31b-it` | 85 of 91 | 4 | 0 | 40 |
| Groq `qwen/qwen3.8-27b` | 69 of 73 | 3 | 5 too big | 61 (paced) |
| NVIDIA `nvidia/nemotron-3-super-120b-a12b` | 68 of 91 | 13 | 0 | 23 |
| Groq `openai/gpt-oss-120b` | 62 of 73 | 5 | 5 too big | 61 (paced) |
| Gemini 3.5 / 3.1 Flash-Lite, DeepSeek v4.1 Flash, Nemotron 3.5 Lightning | still running at handoff | | | |

Earlier Gemini runs (A1-A3, B1, run 3): 48 of 48 values right on 14 filings;
Hyundai not read because both Flash-Lite models were 503 "busy" for 3 minutes.
Gemini was busy on most calls on 13 Oct; NVIDIA gave no 429/503 in 72 calls.

Queued next (run file): NVIDIA `z-ai/glm-5.3`,
`nvidia/nemotron-3-ultra-550b-a55b`, `writer/palmyra-fin-70b-32k` (a finance
model, 32K context), `mistralai/mistral-large-2-instruct`,
`moonshotai/kimi-k2.6`, `nvidia/llama-3.1-nemotron-ultra-253b-v1`; Z.ai
`glm-4.7-flash` thinking off and on (one job, its free tier takes one request at a time). Z.ai claims
(unlimited, 60 RPM, 200K context) are not verified; the run will show.

To see the combined table of any run: the `compare` job's log. To rescore
saved replies after a change to the checks, without new calls:
`python scripts/announcement_sample.py --combine <folder of results json> --rescore`.

Findings to act on:
- ADANIENT (call-money reminder on partly paid rights shares): hand reading
  says `routine`, every model says `rights`. Likely needs its own category
  (rights call money) rather than a miss.
- AEQUS promoter allottee: every model right, no quote found; held back (safe).
- Gemma sorter from the subject line alone: about 6 of 11 and 1 of 4 right.
  Sort from subject plus the first ~1,500 characters of text instead; useful
  groups are always read in full.
- Groq's 8K tokens a minute: filings over ~20,000 characters are not sent.

## Plan: divide the work, one lane per provider

Each provider runs as its own job with its own spacing between calls, so
three or four run at once without coordinating; each stops at 95% of its
daily limit (usage log in R2, to build).

| Lane | Free limits (as listed 13 Oct) | Use |
|---|---|---|
| NVIDIA (Kimi K3 if it holds) | ~40 a minute, ~10K a day "may vary"; terms for regular automated use not yet confirmed | main reader, long filings, backlog |
| Gemini 3.5 + 3.1 Flash-Lite | 15 a minute, 500 a day each, 250K tokens a minute; resets midnight Pacific | second reader |
| Gemma 4 on the Gemini key | 30 a minute, 14.4K a day, 16K tokens a minute | sorting |
| Groq (Qwen 3.8 27B) | 30 a minute, 1K a day, 8K tokens a minute, 200K a day | short filings only (~50 a day per model) |
| Z.ai GLM 4.7 Flash | one request at a time | to be decided by the queued run |

Many NVIDIA models do not mean many times the limit: whether NVIDIA's ~40 a
minute is per account or per model is not confirmed (watch for 429s when
several NVIDIA jobs run at once). Their worth is a ready fallback when a
model is busy or retired, and a cross-check: two models agreeing on a value.

Before any model: subject-line groups drop routine; same file or same text
read once (file hash, then text hash; ~963 a month repeat a file); concall
and below-100 Cr filings skipped. A busy or full lane puts the filing back in
the queue for the next lane. Order: today, then past filings of companies
that get a card today, then the backlog newest first. Each result stores its
model and prompt version (`PROMPT_VERSION`). Weekly check of each provider's
model list (models get renamed and retired).

## Next steps, in order

1. Read the final table of run 38423386748 and of the queued run; pick the
   readers.
2. Decide ADANIENT's category; record the split above in TODO 29.
3. Collector: add NSE's SME feed (`index=sme`, works), file hash dedup,
   BSE-only companies (BSE endpoint not confirmed; BSE refuses the dev
   container, probe from the runner); probe XBRL (`hasXbrl` true on all rows,
   no URL given).
4. The all-day reader with the usage log and lanes; results table per filing.
5. Brief cards and per-company history from the results table.
6. Owner merges PR #56.
