# Announcement reader: state and plan (13 Oct 2026, evening)

Where the announcement reader stands, so any session can pick it up. TODO item 29 points here. All on
PR #56, branch `ccr-5fbf9503-x2spo0`, not merged (owner merges). Times are IST.

Code:
- Collectors (no model): `collectors/nse_events/announcements.py` (NSE main board and SME),
  `collectors/bse/announcements.py` (BSE), workflow `announcements.yml` (nightly, 3 days).
- Live reader: `scripts/announcement_reader.py`, lanes in `scripts/announcement_readers.txt`, workflow
  `announcement-reader.yml` (every 30 minutes on `main`; on a PR a 3-filing dry run, nothing written).
- Site: Brief card "Filings read" (`streamlit_app/screens/filings_read.py`) from
  `clean/current/announcement_reads.parquet`.
- Model test: `scripts/announcement_sample.py` (harness; prompts, clients and checks shared with the
  reader), `scripts/announcement_sample_expected.json` (24 filings read by hand),
  `scripts/announcement_sample_run.txt` (next test run), workflow `announcement-sample.yml`.

## Decisions (owner)

13 Oct, earlier:
- Models run only in the backend (GitHub Actions); the site never calls a model, it reads the tables the
  backend writes. No chat box on the site.
- Keys live only in GitHub Actions secrets: `GEMINI_API_KEY`, `GROQ_API_KEY`, `NVIDIA_API_KEY` (valid
  6 months from 13 Oct 2026: renew by early Apr 2027, same secret name; an expired key shows as "key
  refused (HTTP 401) ... renew the GitHub secret"), `ZAI_API_KEY`. Never in the repo or Streamlit secrets,
  so models cannot be called from a laptop.
- Only public filing text goes in a prompt; nothing personal. Models get extracted text
  (`pdftotext -layout`, ZIPs opened), never PDFs.
- Every value must carry a quote found in the PDF text, and prices and counts must have their digits in
  the quote; otherwise it is held back, never shown. The model gives numbers as written with their unit;
  our code converts (lakh, crore, million, billion) and computes every % change.
- Use free limits up to 95%, through the day (every 30 minutes), not only at night; today's filings first.
- The Brief (`/brief`) becomes the hub for critical and useful filings, crisp and tactical for the next
  day, with "before this" from our own data. No "impact" labels; gaps flagged neutrally.
- Concall announcements are not collected (08 Oct decision).
- Stocks below Rs 100 Cr market cap: their PDFs do not go to a model.

13 Oct, evening:
- **Readers for the first live version: Kimi K3 on NVIDIA (main), Gemma 4 on NVIDIA (backup in the same
  lane), GLM-4.5-Flash on Z.ai (free) as the second lane and cross-check.**
- Below Rs 100 Cr: keep these companies on the site for the time being (still never sent to a model).
- ADANIENT-type filings (reminder to pay call money on partly paid rights shares) count as `rights`.
- The reader reads whichever exchange's copy of a filing comes first and skips the other.
- Times are given in IST.

## Model test results (24 filings, 91 values)

A value counts only when it is right and backed by a quote found in the PDF. Scores are the runner's
(poppler `pdftotext`); a laptop with xpdf's `pdftotext` lays some PDFs out differently and finds fewer
quotes, so local rescoring is only a cross-check.

| Reader | Right | Held back | Errors | Seconds a filing | Run |
|---|---|---|---|---|---|
| NVIDIA `moonshotai/kimi-k3` | **88 of 91** | 4 | 0 | 29 | 38423386748 |
| NVIDIA `nvidia/nemotron-3-ultra-550b-a55b` | 87 of 91 | 4 | 0 | 106 | 38432331574 |
| NVIDIA `google/gemma-4-31b-it` | 85 of 91 | 6 | 0 | 40 | 38423386748 |
| Gemini 3.5 / 3.1 Flash-Lite | 80 of 91 | 12 | 0 | 76 (27 busy replies) | 38423386748 |
| Z.ai `glm-4.5-flash` (free) | 77 of 91 | 10 | 0 | 15 | 38440817065 |
| Groq `qwen/qwen3.8-27b` | 69 of 73 | 3 | 5 too big | 61 (paced) | 38423386748 |
| NVIDIA `nvidia/nemotron-3-super-120b-a12b` | 68 of 91 | 14 | 0 | 23 | 38423386748 |
| Groq `openai/gpt-oss-120b` | 62 of 73 | 6 | 5 too big | 61 (paced) | 38423386748 |
| NVIDIA `nvidia/nemotron-3.5-lightning-30b-a3b` | 24 of 58 | 5 | 7 (time used up) | 205 | 38423386748 |
| NVIDIA `deepseek-ai/deepseek-v4.1-flash` | 0 of 45 | 0 | 10 | 208 (replies empty) | 38423386748 |
| NVIDIA `z-ai/glm-5.3` | running | | | | 38432331574 |
| NVIDIA `z-ai/glm-5.3-flash`, `deepseek-ai/deepseek-v4.1-flash` (reasoning field read) | running | | | | 38440817065 |
| Z.ai `glm-4.7-flash`, thinking off and on (free) | running | | | | 38440817065 |

Not available to this key (13 Oct): NVIDIA `nvidia/llama-3.1-nemotron-ultra-253b-v1`,
`mistralai/mistral-large-2-instruct`, `moonshotai/kimi-k2.6`, `writer/palmyra-fin-70b-32k` all answer
HTTP 404 "Function ... Not found for account" on every call although `/v1/models` still lists them.
None is in NVIDIA's catalog (build.nvidia.com/models) any more; Kimi K2.6 and Mistral Large 2's pages are
gone, and other users report the same 404 for Kimi K2.6 since July 2026 (NVIDIA developer forums). So
NVIDIA's `/v1/models` is stale: **check a model against the catalog page, not only the list.** Current
free catalog (13 Oct): kimi-k3, glm-5.3, glm-5.3-flash, deepseek-v4.1-flash, gemma-4-31b-it,
nemotron-3-super, nemotron-3-ultra, nemotron-3.5-lightning.

Z.ai: the key's `/models` lists only paid models (GLM 4.5 to 5.3, 5.3-Flash and FlashX; GLM-5.3-Flash
is $0.15 / $0.50 per million tokens). The free models (GLM-4.7-Flash, GLM-4.5-Flash, GLM-4.6V-Flash,
under "Other Pricing" on docs.z.ai/guides/overview/pricing) are not listed but answer when called by name
(GLM-4.5-Flash read all 24 filings, no 429). The harness and the reader try only those three on Z.ai
(`FREE_ONLY`); any other Z.ai id is refused, so nothing is ever paid for.

NVIDIA 429s: none in any run, with up to five NVIDIA jobs at once. DeepSeek v4.1 Flash leaves its answer
in `reasoning_content` with `content` empty (GitHub issues on DeepSeek; NVIDIA's card samples read that
field); the harness now reads it. Speed in one run depends on the hour and the provider's load: one run's
seconds only rule out the clearly slow (DeepSeek, Lightning, GLM 5.3 on 13 Oct, 10-15 minutes a filing
with timeouts). The reader logs every call so speed is judged over many runs.

### Wrong values that passed the checks

- Two `entity` labels from the weakest readers (Nemotron 3 Super: Hyundai "listed" for the parent group;
  gpt-oss: Jubilant "listed" for a subsidiary). Entity labels are kept but not shown on the site yet.
- Nemotron 3.5 Lightning: two amounts 10 million times too big (INOXGREEN `299,99,99,852.45` with unit
  "crore", the word coming from the amount in words; IIFL `95,00,00,000` "crore"). Now held back: a lakh,
  crore, million or billion must be backed by the quote (never on a number written in full, 7 or more
  digits; in an exact quote the unit's word follows the number).
- GLM-4.5-Flash: Hyundai's USD 15.5 billion given as 15.5 with no unit. Now held back: with no unit, a
  quote with a unit's word right after the number does not back it.
- Each new check was rescored over every saved reply of both runs: no right value was lost.
- The scorer compares dates as dates ("October 1, 2026" is 2026-10-01).

Earlier Gemini runs (A1-A3, B1, run 3): 48 of 48 values right on 14 filings; Gemini was busy on most
calls on 13 Oct.

## NSE and BSE: what each adds (measured 12 Oct 2026)

NSE's SME feed (`index=sme`) has the same fields and numbering as the main board's, and no filing in
both (6-12 Oct: 3,318 main board, 699 SME). BSE: `AnnSubCategoryGetData/w`, 50 filings a page, newest
first, with the day's count; attachments at `www.bseindia.com/xml-data/corpfiling/AttachLive/<name>`
(confirmed from a machine in India; the runner falls back to the in-page fetch if BSE refuses it).

12 Oct, concalls removed: BSE 1,103 filings from 894 companies (284 not routine), NSE 711 from 432
(188 not routine). Pairing by company, subject words and time (the two copies are different files:
each is addressed to its own exchange, so file size or hash cannot pair them):

| Useful filings, 12 Oct | |
|---|---|
| NSE, company also filed on BSE that day | 129 |
| NSE only: SME board (not on BSE at all) | 37 |
| NSE only: main board | 17 |
| BSE only: companies not on NSE (354 companies) | 83 |
| BSE only: codes missing from the 1 Sep security master | 40 |

Same filing on both (347 pairs): BSE first by over a minute 204 times, NSE 89, within a minute 54;
median BSE ahead by 2.0 minutes (useful filings: 91 pairs, 48 vs 21, median 1.2 minutes); over 30 minutes
ahead: BSE 13, NSE 3. So both exchanges stay: BSE adds about 120 useful filings a day and is usually a
minute or two ahead; NSE adds its SME board. Read once: same ISIN, within six hours, subjects alike.

Regulation heads (Reg 30, 74(5) ...) as a filter: NSE's feed names one on 75 of 576 filings, BSE's mostly
74(5) (already its own subcategory, routine) or 30 (on nearly everything). The subject lines already carry
the routine heads; inside the PDF the opening lines name the regulation, which the sorter can read later.
Exchange trading groups (BSE Z/T, NSE BE/BZ) could be a later filter, from the exchanges' own security
lists (not collected yet).

## The live reader (coded 13 Oct, `scripts/announcement_reader.py`)

Every 30 minutes (on `main`): collect today's NSE and BSE filings (BSE stops paging at the first page it
already has); choose today's and yesterday's filings in a reading group with a PDF or ZIP, newest first;
skip those read before, the same filing on the other exchange, companies below Rs 100 Cr; download, and
copy instead of reading when the same file or text was read before; both lanes read each filing side by
side; check every value; write. About 22 minutes of reading a run.

- Lanes: `scripts/announcement_readers.txt`, one line each (`main`, `second`). Within a lane the next
  model takes over on busy, refusal or timeout; a model timing out twice running is left out for the run.
  Changing a reader is a one-line change to that file.
- Shown: the main lane's values that pass the checks; the second lane's same value marks
  "2 readers agree". When the main lane fails, the second lane's checked values are used.
- Written: `archive/announcement_reads/year=YYYY/month=MM.parquet` (by event_id; statuses `read`,
  `same_file`, `same_text`, `same_filing_other_exchange`, `below_100_cr`, `no_text`, `failed` with tries,
  given up after 3), `clean/current/announcement_reads.parquet` (last 60 days), and
  `clean/reports/announcement_reader/{date}.json` (each run: counts, outcomes, every call by model with
  its answers and median seconds, models left out as slow).
- Currency: a sum of money gets a currency only when the filing writes one, read from the value's own
  quote (US$, USD, Rs, INR, EUR ... right before the number) or from the filing's checked `currency`
  field; otherwise the site writes it as the filing does ("200.00 crore"), never with Rs assumed (the
  13 Oct dry run had Tristar's US$ 1.4 billion revenue about to show as Rs 140 Cr).
- Expected volume: the dry run on 13 Oct found 332 filings to read from that day alone (1,762 fetched;
  1,288 routine or without a file, 74 below Rs 100 Cr, 68 the same filing on the other exchange). At about
  40 filings a run, a day's filings take about 8 runs (4 hours). Cards appear only where a value passes.

### Dry run on real filings (PR, 13 Oct, 23:52-23:56 IST, run 38446158692)

Green. Collected 13 Oct from both exchanges and read three filings (the PR cap), writing nothing:

| Filing | Category | Shown | Held back | Notes |
|---|---|---|---|---|
| BSE ICICIPRULI, General | routine | 0 | 1 | director appointment; only an entity label, kept back |
| NSE AEGISLOG, Press Release | deal_or_dispute | 5 | 1 | Tristar stake for US$ 809 mn; revenue US$ 1.4 bn, EBITDA US$ 257 mn, net profit US$ 82 mn |
| NSE AEGISLOG, General Updates (board outcome) | deal_or_dispute | 4 | 4 | same deal; three table rows held (their unit is in the column heading) |

Kimi K3 answered all three (median 26 s), GLM-4.5-Flash all three (11 s); no 429, no error; the second
lane agreed on the currency. Found: the currency problem above (fixed before going live), and the same
deal filed twice on NSE by one company (press release and board outcome: two cards; one card per company
and deal is a later step).

## Runs on 13 Oct (IST)

| Run | What | Status |
|---|---|---|
| 38408604144 (19:22) | first 24-filing run | failed before any model call: Ubuntu's mirror answered 404 for poppler-utils; the workflow now refreshes the package list first |
| 38418368623, 38419069858, 38420120800, 38421224640 (20:30-20:50) | Gemini runs on parts of the sample | finished |
| 38423386748 (21:05-22:34) | nine readers on 24 filings | finished; rescored above |
| 38432331574 (22:34-00:14) | NVIDIA GLM 5.3, Nemotron 3 Ultra, four withdrawn NVIDIA models, Z.ai | Nemotron 3 Ultra 87 of 91; the four withdrawn models 404; Z.ai skipped (ids not on its list); GLM 5.3 running |
| 38440817065 (23:13-00:53) | DeepSeek v4.1 Flash (reasoning field), NVIDIA GLM 5.3 Flash, Z.ai GLM-4.5-Flash, GLM-4.7-Flash off and on | GLM-4.5-Flash 77 of 91; the rest running |
| 38446158568 (23:52-) | the chosen readers again, another hour (Kimi K3, Gemma 4, GLM-4.5-Flash) | running |
| 38446158692 (23:52) | live reader, dry run on 3 real filings | green |
| Twelve others | replaced by a newer push before starting (two duplicates cancelled by hand) | cancelled, no model called |

## Open questions for the owner

1. Merge PR #56 when ready (owner merges). Nothing runs on a schedule and the site shows nothing new
   until then.
2. NVIDIA's free API is a "trial service" under NVIDIA's API Trial Terms of Service; forum users read
   them as testing and evaluation only (the PDF itself not read). Daily automated reading may be outside
   them. Z.ai's free models carry no such label that was found.

## How to pick up (for a new session)

Start prompt: "Read CLAUDE.md, then docs/ANNOUNCEMENT_READER.md, then TODO 29. Collect the results of
the latest Announcement reader sample runs and the live reader's usage log, report one table for all
readers, update the split here and in TODO 29, ask the owner the open questions, then continue with Next
steps. Subscribe to PR #56 and keep CI green."

- The `compare` job of a sample run gives its combined table, rescored with the current checks on the
  runner. Job logs come only after a job finishes (the API answers 404 while it runs; the live log needs
  a signed-in browser). To rescore saved replies after a change to the checks without new calls: download
  each job's artifact into one folder and run `--combine <folder> --rescore` (on the runner for exact
  scores).
- Sample runs go side by side; only the same reader waits for its own job in an earlier run. A PR push
  starts a sample run only when the sample's own files changed in that push, and the reader's 3-filing dry
  run only when the reader's files (or the shared harness) changed. Put `[skip ci]` in doc-only commits.
- Within one reader's job the filings go one at a time (free limits; Z.ai takes one request at a time).
  Each Z.ai model has its own job (a model and its `+thinking` variant share one).
- Check every model id against the provider's catalog page and the live list each job prints; a wrong or
  withdrawn id is skipped, never guessed. Small-context models get their own limits in `MODEL_LIMITS`.
- Z.ai key is from z.ai (`https://api.z.ai/api/paas/v4`, tried first; the harness falls back to
  bigmodel.cn and `api.z.ai/v1`). Only Z.ai's free models.
- No model identifiers in commit messages or PR text.

## Next steps, in order

1. Add the results of the runs still going (GLM 5.3, GLM 5.3 Flash, DeepSeek with its reasoning field,
   GLM-4.7-Flash thinking off and on) and of the rerun of the chosen readers (another hour, run-to-run
   variance) to the table above; change `scripts/announcement_readers.txt` if they say so.
2. The reader's PR dry run on real filings: green on 13 Oct (above); green again with the currency fix;
   then the owner merges PR #56.
3. After the merge: the first live runs; check the usage log (calls, 429s, seconds), the Brief card, and
   the BSE step from the runner (plain requests or in-page fetch).
4. Brief cards: "before this" from our own data (dilution, promoter holding and pledge, issue price vs
   CMP, size vs market cap, insider and deal activity); per-company history on the Company page.
5. Sorter for `to_sort` filings from the subject plus the first ~1,500 characters (with the regulation
   cited there), so routine board outcomes are not read in full.
6. XBRL of announcements: `hasXbrl` is true on all NSE rows but no URL is given; not probed yet.
