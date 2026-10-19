# Announcement reader: state and plan (updated 14 Oct 2026)

This document records the live reader and the historical AI backfill. Older dated notes below are an
engineering log, not the current rollout status. The agreed historical AI backfill starts **01 Jan 2026**.
The live reader prioritizes today/yesterday. After each successful live cycle, the same serialized workflow checks the eligible live queue; only when it is empty does it read at most one historical AI batch. Historical reading progresses month by month as soon as each month has a successful collection checkpoint; it does not wait for all requested months. For the current month, dates older than the live/nightly collection window are collected one day at a time during idle cycles, then read in bounded batches.

Current implementation paths:
- Collectors (no model): `collectors/nse_events/announcements.py` and `collectors/bse/announcements.py`;
  both support bounded `--from YYYY-MM-DD --to YYYY-MM-DD` historical windows.
- Live reader: `scripts/announcement_reader.py`; prompt receives earlier, source-linked company memory.
- Historical AI backfill: `scripts/announcement_backfill.py`; live-first continuous worker, one bounded batch per live cycle, oldest completed month first, and R2 checkpoints.
- Historical collection workflow: `.github/workflows/announcement-history-backfill.yml`; writes `archive/announcement_backfill/collection/YYYY-MM.json` only after both exchange collectors exit successfully. The live reader workflow consumes completed-month markers and reads one monthly partition per cycle. Current-month older dates use per-day collection markers under `archive/announcement_backfill/collection-days/`.
- Persistent company memory: `archive/company_memory/{ISIN}.json`, built only from quote-validated claims with
  event ID, date, exchange and source URL. Backfill state: `archive/announcement_backfill/state.json`.
- Site: Brief card "Filings read" from `clean/current/announcement_reads.parquet`.
- Model test: `scripts/announcement_sample.py` and `scripts/announcement_sample_expected.json`.
- Usage ledger (15 Oct): one file a run, `clean/reports/announcement_reader/{date}/runs/{run}.json`, holding that
  run's calls by model and answer. It is replaced (never appended to) every minute while calls are made and at the
  end, so a cancelled or timed-out run has already counted its calls and none is counted twice; dry runs (PR runs,
  the 3-filing sample) write it too. The daily limits add every run's file for the day (`used_today`). Before
  15 Oct the reader appended one entry per run at the end to `{date}.json`, which missed cancelled runs and dry
  runs and, in the historical backfill, could count a batch's earlier calls again; those days are past, and the
  limits are daily, so they no longer affect a limit. The AI health check (`scripts/ai_health_check.py`) is the
  only caller outside the ledger, a handful of calls when run by hand.
- Provider days (15 Oct): a daily limit counts the provider's own day, not IST's. Gemini's resets at midnight
  Pacific time (12:30 or 13:30 IST); Groq, NVIDIA and Z.ai publish no reset time, so their calls are counted over
  the last 24 hours (`RESET_TZ`, `window_start`). The ledger keeps each run's calls by the minute they were seen,
  and a running reader re-reads the other runs' calls every 5 minutes, so two runs at once (live and backfill)
  stop at the limit too: on 15 Oct the day file showed Gemini 3.5 Flash-Lite at 492 of its 500.
- What the exchanges send (read-only audit, `scripts/announcement_source_audit.py`, 15 Oct): NSE's `hasXbrl` is
  true on every row (2,600 of 2,600 in October), so it says nothing; NSE's `sm_isin` is empty on every row (the
  ISIN comes from the security master); 55 of 21,963 NSE filings link to `.../corporate/-`, which is no file and
  is now treated as none. NSE's XBRL announcement feed (`/api/XBRL-announcements`) carried 55 rows from 1 to
  15 Oct, all director/KMP changes: 35 XML files and 20 ZIPs of the filing's documents (the same ZIP the main
  feed links, so they are now kept as ZIPs, not XBRL). The XML rows often have no PDF of their own, and the
  nearest filing in time can be a different event, so they are not paired with PDFs. Announcement XBRL can
  therefore not save model calls in any number; the XBRL that would is the quarterly results' (not collected yet).

- Concall filings (15 Oct, owner: capture everything): both collectors now archive them (`CONCALL`); they stay in the `routine` reading group, so the reader does not read them until to-do 4.6/4.9 decide how; `scripts/announcements_from_raw.py` rebuilds earlier months' concall rows from the saved exchange answers.
- Archive gaps (15 Oct, read-only report `scripts/archive_gaps_report.py`, to-do 1.1a). Weekdays from 1 Jan with no
  filing: NSE 29 (all of March; 2, 5-9 and 12 Oct), BSE 160 (March to September, same October days). Causes:
  (1) March: the month job of the 14 Oct history run (`collect-months (2026-03)`, run 38537438107) was cancelled
  by the next push (concurrency), so no marker and no rows; (2) BSE March to September: from 14 Oct 14:10 IST
  (#71) the history collection ran NSE-only to unblock NSE, and still wrote `collection_verified` markers
  (scope NSE, `bse_skipped` true), so the months look done and BSE was never fetched; (3) 2 to 12 Oct: the nightly
  collector started on 13 Oct (3-day window) and the history collection stopped at the month before; (4) the
  15 Oct unify commit (`4a6dde7`) deleted the nightly `announcements.yml` and the history workflow and left
  collection inside the reader workflow, which is disabled: nothing collected from then until
  `announcement-collect.yml` (collection alone, no model). 26 Jan is a holiday (34 NSE and 57 BSE filings), not a gap.
  Weekend filings exist (NSE 69 days, BSE 17).

Historical backfill acceptance is tracked separately as TODO item 30. A green workflow run means the code and bounded batch succeeded; the overall backfill is complete only when every completed collection month has been exhausted and the persisted state says `complete` and `remaining: 0`. A `running` or `paused` state is resumable, not completion. If the live queue has eligible unread filings, the historical worker defers until a later cycle.

Code:
- Collectors (no model): `collectors/nse_events/announcements.py` (NSE main board only; SME is out of scope),
  `collectors/bse/announcements.py` (BSE), workflow `announcement-collect.yml` (nightly, 3 days; any range by hand; no model).
- Live reader: `scripts/announcement_reader.py`, lanes in `scripts/announcement_readers.txt`, workflow
  `announcement-reader.yml` (every 15 minutes on `main`; on a PR a 3-filing dry run, nothing written).
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
  (`pdftotext -layout`, ZIPs opened), never PDFs. For PDF/ZIP text, the reader applies
  `insiders_clean.text_clean.clean` to the model input to remove repeated page furniture, exchange address
  lines and letterhead padding. The original extracted text remains untouched for quote validation, number/unit
  checks, hashes and duplicate detection. Structured XBRL facts bypass this layout cleaner; a cleaner failure
  or empty result falls back to the original text and is logged.
- The recurring production chain enables bounded Gemini batching for short filings (up to four per request).
  Each response is validated against its own filing; a missing/invalid batch answer and a long filing fall back
  to individual reads. Manual runs remain configurable.
- Every value must carry a quote found in the original extracted filing text, and prices and counts must have their digits in
  the quote; otherwise it is held back, never shown. The model gives numbers as written with their unit;
  our code converts (lakh, crore, million, billion) and computes every % change.
- Use free limits up to 95%, through the day (every 15 minutes), not only at night; today's filings first.
- The Brief (`/brief`) becomes the hub for critical and useful filings, crisp and tactical for the next
  day, with "before this" from our own data. No "impact" labels; gaps flagged neutrally.
- Concall announcements are not collected (08 Oct decision).
- Current eligibility gate (updated 19 Oct 2026): only companies with a verified market cap strictly above Rs 500 Cr are sent to a model. The reader uses the latest available exchange snapshot from the prior seven days; it does not reconstruct market cap as of each old announcement. Missing/stale market cap fails closed.

13 Oct, evening:
- **Readers for the first live version: Kimi K3 on NVIDIA (main), Gemma 4 on NVIDIA (backup in the same
  lane), GLM-4.5-Flash on Z.ai (free) as the second lane and cross-check.**
- The earlier Rs 100 Cr cutoff was replaced on 19 Oct 2026 with a strict > Rs 500 Cr gate. Older run counts in this document describe the old threshold and are historical only.
- ADANIENT-type filings (reminder to pay call money on partly paid rights shares) count as `rights`.
- The reader reads whichever exchange's copy of a filing comes first and skips the other.

14 Oct, 01:00 IST (after the first live run):
- **Four lanes in parallel, one per provider, each taking the next filing** (NVIDIA Kimi K3 with Gemma 4
  as backup; Z.ai GLM-4.5-Flash; Groq Qwen 3.8 for filings under ~20,000 characters; Gemini 3.5 / 3.1
  Flash-Lite), instead of two lanes reading every filing. Every reader is above the owner's 80% bar (in
  the test: 97%, 86%, 95%, 88%), and no wrong number passed the checks for any of them; a weaker reader
  shows fewer values, never unchecked ones. "2 readers agree" now comes from an idle lane reading again
  a filing another provider read.
- Each filing saved as read; a run every 15 minutes; the site keeps the reads table 3 minutes.
- Times are given in IST.

## Model test results (24 filings, 91 values)

A value counts only when it is right and backed by a quote found in the PDF. Scores are the runner's
(poppler `pdftotext`); a laptop with xpdf's `pdftotext` lays some PDFs out differently and finds fewer
quotes, so local rescoring is only a cross-check.

All runs on the same 24 filings, 91 values read by hand. Times IST, 13-14 Oct. "Right" counts a value
only when it is right and backed by its quote; "held back": a check failed, never shown. 429 / busy /
timeouts: answers to the job's calls. "Wrong values that passed": wrong yet past the checks (would have
reached the site). The first run's own `compare` table used the checks from before the 13 Oct fixes; its
rows here are rescored with the current checks (the rerun on the runner gave Kimi K3 and Gemma 4 the same
88 and 85).

| # | Model | Provider (cost) | Run | Right | Held back | Not read | Seconds a filing | 429 | Busy (5xx) | Timeouts | Wrong values that passed | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `moonshotai/kimi-k3` | NVIDIA (free trial) | 38423386748 (21:05) / rerun 38446158568 (23:52) | **88 of 91** / **88 of 91** | 4 / 2 | 0 | 29 / 33 | 0 | 0 | 0 | none | **Main reader (chosen)** |
| 2 | `nvidia/nemotron-3-ultra-550b-a55b` | NVIDIA (free trial) | 38432331574 (22:34) | 87 of 91 | 4 | 0 | 106 | 0 | 5 | 0 | none | Accurate but slow; spare |
| 3 | `google/gemma-4-31b-it` | NVIDIA (free trial) | 38423386748 / rerun 38446158568 | 85 of 91 / 85 of 91 | 6 / 4 | 0 | 40 / 29 | 0 | 0 | 0 | none | **Main lane's backup (chosen)** |
| 4 | Gemini 3.5 / 3.1 Flash-Lite | Google (free) | 38423386748 | 80 of 91 | 12 | 0 | 76 | 0 | 27 | 2 | none | Often busy; not used for now |
| 5 | `glm-4.5-flash` | Z.ai (free) | 38440817065 (23:13) / rerun 38446158568 | 77 of 91 / 78 of 91 | 10 / 11 | 0 | 15 / 13 | 0 | 0 | 0 | 1, now held back (Hyundai USD 15.5 billion as 15.5) | **Second lane, cross-check (chosen)** |
| 6 | `qwen/qwen3.8-27b` | Groq (free) | 38423386748 | 69 of 73 | 3 | 5 too big | 61 (paced) | 0 | 0 | 0 | none | Short filings only (8K tokens a minute) |
| 7 | `nvidia/nemotron-3-super-120b-a12b` | NVIDIA (free trial) | 38423386748 | 68 of 91 | 14 | 0 | 23 | 0 | 0 | 0 | 1 (Hyundai `entity` "listed" for the parent group) | Out (accuracy) |
| 8 | `openai/gpt-oss-120b` | Groq (free) | 38423386748 | 62 of 73 | 6 | 5 too big | 61 (paced) | 0 | 0 | 0 | 1 (Jubilant `entity` "listed" for a subsidiary) | Out (accuracy) |
| 9 | `glm-4.7-flash`, thinking off | Z.ai (free) | 38440817065 | 60 of 73 | 4 | 4 (model busy) | 26 | 36 for 9 and 10 together, all "service may be temporarily overloaded" (code 1305) | 4 | 0 | none | Out: below GLM-4.5-Flash, often busy |
| 10 | `glm-4.7-flash`, thinking on | Z.ai (free) | 38440817065 | 49 of 65 | 11 | 7 (model busy) | 86 | (same job) | | 0 | none | Out: lower and slower |
| 11 | `nvidia/nemotron-3.5-lightning-30b-a3b` | NVIDIA (free trial) | 38423386748 | 24 of 58 | 5 | 7 (time used up) | 205 | 0 | 0 | 0 | 2, now held back (INOXGREEN, IIFL amounts 10 million times too big) | Out (slow, wrong) |
| 12 | `z-ai/glm-5.3` | NVIDIA (free trial) | 38432331574 | 15 of 15 (4 filings only) | 0 | 20 (13 time up, 7 over 10 minutes each) | 474 | 0 | 0 | 0 | none | Out (8 minutes a filing) |
| 13 | `deepseek-ai/deepseek-v4.1-flash` | NVIDIA (free trial) | 38423386748 | 0 of 45 | 0 | 10 | 208 | 0 | 0 | 4 | none | Replies empty (answer in `reasoning_content`); retest below |
| 13r | `deepseek-ai/deepseek-v4.1-flash`, reasoning field read | NVIDIA (free trial) | 38440817065 | 51 of 53 (16 filings) | 2 | 8 (5 no reply within 5 minutes, twice each; 3 run time used up) | 174 | 0 | 0 | 10 | none | Out: right when it answers, but about 3 minutes a filing and a third of the filings not read |
| 14 | `z-ai/glm-5.3-flash` | NVIDIA (free trial) | 38440817065 | 80 of 82 | 2 | 3 (ADANIENT, FMGOETZE, 63MOONS: no reply within 5 minutes, twice each) | 114 | 0 | 0 | 8 | none | Out: accurate but about 2 minutes a filing and 8 timeouts; spare |
| 15 | `nvidia/llama-3.1-nemotron-ultra-253b-v1`, `mistralai/mistral-large-2-instruct`, `moonshotai/kimi-k2.6`, `writer/palmyra-fin-70b-32k` | NVIDIA | 38432331574 | - | | all 24 | | 0 | 0 | 0 | | Withdrawn: HTTP 404 on every call, gone from NVIDIA's catalog |

- No provider sent a 429 in any run except Z.ai's GLM-4.7-Flash, and those say the model was overloaded:
  GLM-4.5-Flash ran at the same hours on the same key with none, so Z.ai's one-request-at-a-time limit
  is not per account and each Z.ai model keeps its own job.
- Run to run: the rerun at another hour gave the same scores; only the speeds moved.
- Every wrong value found today is now caught by a check (rows 5, 11), except the `entity` labels
  (rows 7, 8), which are kept off the site.
- Earlier Gemini runs (A1-A3, B1, run 3): 48 of 48 values right on 14 filings.

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
(GLM-4.5-Flash and GLM-4.7-Flash both read the sample). The harness and the reader try only those three on Z.ai
(`FREE_ONLY`); any other Z.ai id is refused, so nothing is ever paid for.

NVIDIA 429s: none in any run, with up to five NVIDIA jobs at once. DeepSeek v4.1 Flash leaves its answer
in `reasoning_content` with `content` empty (GitHub issues on DeepSeek; NVIDIA's card samples read that
field); the harness now reads it. Speed in one run depends on the hour and the provider's load: one run's
seconds only rule out the clearly slow (DeepSeek, Lightning, GLM 5.3 on 13 Oct, 10-15 minutes a filing
with timeouts). The reader logs every call so speed is judged over many runs. The rerun at another hour
gave the same scores (Kimi K3 88, Gemma 4 85, GLM-4.5-Flash 77 then 78) with different speeds (Gemma 4: 40
then 29 seconds); no 429 from any provider in any run. No wrong value passed the checks in the rerun.

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


## NSE and BSE: what each adds (measured 12 Oct 2026)

Historical scope note: NSE's SME feed (`index=sme`) was measured separately (6-12 Oct: 3,318 main-board
filings, 699 SME), but SME listings are now explicitly out of the investment universe. The collector fetches
only `index=equities`; the reader filters historical NSE SME rows and BSE SME-group listings before XBRL pairing or AI processing. BSE: `AnnSubCategoryGetData/w`, 50 filings a page, newest
first, with the day's count; attachments at `www.bseindia.com/xml-data/corpfiling/AttachLive/<name>`
(confirmed from a machine in India; the runner falls back to the in-page fetch if BSE refuses it).

12 Oct, concalls removed: BSE 1,103 filings from 894 companies (284 not routine), NSE 711 from 432
(188 not routine). Pairing by company, subject words and time (the two copies are different files:
each is addressed to its own exchange, so file size or hash cannot pair them):

| Useful filings, 12 Oct | |
|---|---|
| NSE, company also filed on BSE that day | 129 |
| SME-board listings excluded from the reading universe | 37 |
| NSE only: main board | 17 |
| BSE only: companies not on NSE (354 companies) | 83 |
| BSE only: codes missing from the 1 Sep security master | 40 |

Same filing on both (347 pairs): BSE first by over a minute 204 times, NSE 89, within a minute 54;
median BSE ahead by 2.0 minutes (useful filings: 91 pairs, 48 vs 21, median 1.2 minutes); over 30 minutes
ahead: BSE 13, NSE 3. So both exchanges stay: BSE adds about 120 useful filings a day and is usually a
minute or two ahead. SME counts above are historical context only and are excluded from current collection/reading. Read once: same ISIN, within six hours, subjects alike.

Regulation heads (Reg 30, 74(5) ...) as a filter: NSE's feed names one on 75 of 576 filings, BSE's mostly
74(5) (already its own subcategory, routine) or 30 (on nearly everything). The subject lines already carry
the routine heads; inside the PDF the opening lines name the regulation, which the sorter can read later.
Exchange trading groups (BSE Z/T, NSE BE/BZ) could be a later filter, from the exchanges' own security
lists (not collected yet).

## The live reader (coded 13 Oct, `scripts/announcement_reader.py`)

Every 15 minutes (on `main`, at :07, :22, :37 and :52; GitHub may start a run a few minutes late): collect yesterday's and today's NSE and BSE filings (BSE stops paging at the
first page it already has; yesterday too, so a filing made public between the nightly collection at 22:45
and midnight is read the same night); choose today's and yesterday's filings in a reading group with a PDF or ZIP, newest first;
skip those read before, the same filing on the other exchange, SME listings, companies at or below Rs 500 Cr, and companies without a recent verified market-cap snapshot; download, and
copy instead of reading when the same file or text was read before (also when two lanes take one file at
once: the second waits for the first's read); the lanes read different filings at the same time; check
every value; save. A run takes new filings for 11 minutes (`READER_MINUTES` in the workflow),
so it ends before the next starts; what it does not reach waits for the next run.

- Continuous (14 Oct, owner): each run starts the next when it ends (job `next` in the workflow, by
  `workflow_dispatch`, which GitHub lets a workflow start with its own token), at least 10 minutes after
  the last one started and 30 after a failure; a cancelled run ends the chain. GitHub's schedule (every 15
  minutes) is kept only to restart the chain: on 13-14 Oct it started no run in the first hour after the
  merge, and the nightly jobs start 3.5-6.5 hours late (measured 15 Oct on 1-14 Oct runs). **Off switch:** set the repository variable
  `READER_LOOP` to `off` (Settings, Secrets and variables, Actions, Variables) or disable the workflow in
  the Actions tab; on again: remove the variable and run the workflow by hand once. The public repo's
  Actions minutes are free; each cycle collects NSE and BSE once (about 2 minutes).
- Schedule (18 Oct): live filings by day; old announcements (company history) only 22:30-09:00 IST after the live queue is clear (`READER_HISTORY=night`); runs read 100 filings or 40 minutes; page-image requests are held 12 s apart per Gemini model. See BLUEPRINT_TODO 12.26.
- A new prompt version re-reads once the filings of today and yesterday read with an older one (and their
  copies), so every card has every part; an older read is never the source of a copy.
- Saved as read: each filing's row goes to R2 as soon as it is read (at most one write every 15 seconds;
  a failed write keeps its rows for the next one, and only the run's last write fails the run). A run
  cut short keeps what it read. The site keeps this one table for 3 minutes instead of 10
  (`FRESH` in `streamlit_app/data/store.py`), so a filing shows on the Brief about 5 to 20 minutes after
  the exchange publishes it. The usage log is still written once, at the end of a run.

- Lanes: `scripts/announcement_readers.txt`, one line a lane, one provider a line (`nvidia`, `zai`,
  `groq`, `gemini`). Each lane is a worker taking the next filing, newest first, so a slow provider holds
  up only its own filing. Within a lane the next model takes over on busy, refusal or timeout; a model
  timing out twice running is left out for the run. A filing a lane cannot read (every model busy, too
  slow, the reply not JSON, too long for Groq) goes to a lane that has not tried it; it is `failed` only
  when every lane still running has tried it. A lane without its key is left out. Changing a reader is a
  one-line change to that file.
- Daily limits: `DAILY_CALLS` in the reader (Groq Qwen 1,000, each Gemini Flash-Lite 500, NVIDIA ~10,000
  "may vary"; Z.ai lists none). A lane stops a model at 95% of it, counting today's earlier runs from the
  usage log and this run's calls; a lane with no model left stops and hands its work on.
- Shown: the reading lane's values that pass the checks (`reader_lane` says which). When nothing is left
  to read, an idle lane reads again a filing another provider read this run; the values both give alike
  are marked "2 readers agree" (`second_reader`, `agreed`). A failed cross-check changes nothing.
- The card on the Brief (14 Oct, owner's examples from equisense; prompt `live-2`): the symbol, market cap
  and size (from the price summary), date and exchange; the category; a headline and 2 to 4 points the
  model writes from the filing; the figures of a periodic update with our own change on a year ago; the key
  terms (price a share, shares, size, record date ...); the filing's own words behind a click; the stock's
  1W, 1M and 1Y moves; the filing's link and its reader. The headline and each point carry a quote, and
  every number in them must be one of the quote's numbers, as written or with its lakh, crore, million or
  billion applied (12,000 lakh may be written 120 crore, within 0.5%): a number of the model's own, a growth
  rate it worked out, or a quote not in the filing holds the sentence back. A point may also use the
  numbers of the filing's values already checked (a floor price and its discount from two quotes); a
  headline those of the shown points too. First trial on real filings (PR #59, 14 Oct 01:40): 3 of 3
  headlines and 5 of 9 points shown before this, the rest held back for joining numbers of two quotes. A metric's year-earlier value
  (`previous`, with its own quote) is checked the same way; the % change is ours. No "impact" label (13
  Oct decision); "why it matters" waits for our own history ("before this", a next step): equisense's
  draws on concalls and annual reports; concall filings are archived since 15 Oct but not yet read, annual reports are not collected, so it would be invented here. Reads
  before `live-2` show a plain headline (company: category, size). The site's CSS hides every `footer`
  element (Streamlit's), so the card's foot is a `div`; the first cards' link and reader never showed.
- "Before this" on the card (our own tables, every figure computed by us): the issue price against the last
  close; the size against market cap; promoter holding and pledge (latest quarter); insiders' open-market
  buys and sells in the last 30 days; the company's earlier filings read in the last 90 days (their
  headline). Nothing from a model and nothing we do not collect.
- One card per deal: different files on one deal (Aegis: a press release and the board's outcome, both
  US$ 809M for 89.8% of Tristar) fold into one card when they are the same company and category, made
  public within 24 hours, and share a number of 100 or more, or two numbers. The card with the most shown
  values leads; the others are listed under "Also filed" with their subject and a link.
- Cross-check of figures: an idle lane's second read now also marks a business update's figures "2 readers
  agree" when it gives the same number (labels differ between models, so the number is compared).
- Categories (prompt `live-3`, 14 Oct, owner): the live reader's list (`CATEGORIES` in
  `announcement_reader.py`, 35 besides `routine`) follows what listed companies file, after SEBI's LODR
  Schedule III (Regulation 30) and what the exchanges carry besides: the harness's list without
  `deal_or_dispute` (an acquisition under a "dispute" label read as trouble), plus ESOP, dividend, bonus
  or split, acquisition, divestment, merger or demerger, agreement or JV, delisting, licence or approval,
  operations started, financial results, default, debt settlement, insolvency, legal or regulatory,
  fraud or forensic audit, disruption, management change, corporate change. The page groups them in 11
  headings (Fund raising; Buybacks & payouts; Acquisitions & restructuring; Orders & business; Capex &
  capacity; Results; Ratings; Debt & distress; Legal & regulatory; Disruption; Management & governance), a
  test keeps every category labelled and headed. Reads before `live-3` keep `deal_or_dispute` ("Deal or
  legal matter", under Other); today's and yesterday's are read again. The harness keeps its shorter list,
  so the 24-filing test stays comparable.
- Which filings are read at all is still the collector's subject-line groups (`READING_GROUPS`, NSE and
  BSE): board outcomes, general updates, press releases, fund raising, takeovers, ratings, auditor and
  director resignations, fraud and insolvency subjects, BSE's acquisition and scheme subjects. Subjects
  outside them (NSE's own subjects for orders, acquisitions, results, dividends and the like) are routine
  and never read. **Next:** extend the groups from the real subject counts in
  `clean/reports/announcements/{date}.json` (exact names only; the volume of results season to be weighed).
- Owner's review of the live cards (14 Oct, 02:03): the first reads (before `live-2`) said only "Company:
  deal or dispute"; GTPL's "Before this" set Rs 937.50, the price a share of the company GTPL buys, against
  GTPL's own close (1,551% "above"). Fixed: a price is set against the close only for the company's own
  shares (preferential, QIP, rights, warrants, buybacks, open offers); a card without a checked headline
  shows the exchange's own one-line description; a BSE-only company shows its name, not its number; the
  prompt asks an acquisition, sale or merger for the company bought or sold, the stake and the price, and
  a legal matter for who acted, against whom and the amount.
- Page "Filings read" (`/filings`, menu Filings; owner, 14 Oct): every filing read in the last 60 days as the
  Brief's cards, filtered by heading (Fund raising, Buybacks, Acquisitions & deals, Capex & capacity,
  Orders, Business updates, Ratings, Governance, Other for a category not mapped yet), period (2, 7, 30,
  60 days), exchange, company size, search and "2 readers agree"; each heading shows its count, and the
  address keeps the headings and period. The Brief's card links to it.
- The card on the Brief: one card per file. The same file filed again (on the other exchange or under
  another subject) is folded into it as "Also filed: BSE 13 Oct, 21:12". Entity labels, not shown by
  design, are not counted as held back; repeated reasons are counted ("number not in its quote ×2"); a
  metric's empty period ("N/A") is not written. Different files on one deal (Aegis: press release and
  board outcome) are still two cards: one card per company and deal is a next step.
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

Green. (A second dry run at 00:02 on 14 Oct read nothing: it fetched only the new day, which had no filings
yet; the reader now collects yesterday too.) Collected 13 Oct from both exchanges and read three filings (the PR cap), writing nothing:

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
| 38432331574 (22:34-00:07) | NVIDIA GLM 5.3, Nemotron 3 Ultra, four withdrawn NVIDIA models, Z.ai | finished: Nemotron 3 Ultra 87 of 91; GLM 5.3 4 filings in 85 minutes; the four withdrawn models 404; Z.ai skipped (ids not on its list) |
| 38440817065 (23:13-00:53) | DeepSeek v4.1 Flash (reasoning field), NVIDIA GLM 5.3 Flash, Z.ai GLM-4.5-Flash, GLM-4.7-Flash off and on | GLM-4.5-Flash 77 of 91; GLM-4.7-Flash 60 of 73 off, 49 of 65 on (36 "overloaded" 429s); NVIDIA GLM 5.3 Flash 80 of 82 (114 s a filing, 8 timeouts); DeepSeek v4.1 Flash 51 of 53 (174 s a filing, 10 timeouts); neither beats the chosen readers |
| 38446158568 (23:52-00:10) | the chosen readers again, another hour (Kimi K3, Gemma 4, GLM-4.5-Flash) | finished: 88, 85, 78 of 91 |
| 38446158692 (23:52) | live reader, dry run on 3 real filings | green; found the currency problem |
| 38447392891 (00:02) | dry run with the currency fix | green, but read nothing (the new day had no filings; fetched only today) |
| 38448018056 (00:08) | dry run, yesterday collected too | green: the same 3 filings, every shown US$ value with USD |
| 38447393120, 38448018013 | sample runs on pushes that did not touch the sample | skipped by the gate, no model called |
| Twelve others | replaced by a newer push before starting (two duplicates cancelled by hand) | cancelled, no model called |

## First live run (14 Oct, IST)

Run 38452625630 (00:39-01:06, started by hand after PR #56 merged; two lanes reading every filing, saved
at the end). Collecting took 3 minutes, reading 23; it ended 4 minutes before the job's 30-minute limit.

| | |
|---|---|
| Filings found, yesterday and today, NSE and BSE | 1,685 |
| Routine or no file (no model) | 1,226 |
| Below Rs 100 Cr | 73 |
| Same filing on the other exchange | 68 |
| Chosen | 318 |
| Read / same file copied | 17 / 7 |
| Not reached, left for later runs | 294 |

| Model | Calls | Answers | Median seconds |
|---|---|---|---|
| NVIDIA Kimi K3 | 18 | 17 OK, one 429 (NVIDIA's first) | 76.7 (29-33 in the tests) |
| Z.ai GLM-4.5-Flash | 17 | 17 OK | 10.6 |

- Every filing waited for Kimi K3 while Z.ai had answered in about 10 seconds: hence the parallel lanes.
- BSE works from the runner: 9 of the 17 read came from BSE; a filing on both exchanges was read once.
- On the Brief (owner, 01:15): 43 values on 11 filings; every number checked by hand against its quote
  was right (Aurum 51,00,000 x Rs 231.42 = Rs 118.02 Cr; Oil India 50,000 x Rs 10 = Rs 5 lakh; Reliance
  Power Rs 2,026.65 Cr; Aegis US$ 809M, 89.8%). Cards to fix: the same file shown 2-3 times (Hero
  Motors, Anlon, Reliance Power, Aegis), "entity labels not shown yet" on every card, a "(N/A)" period.

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

1. Add the last two rows of run 38440817065 (finishing by 00:53 IST on 14 Oct: NVIDIA GLM 5.3 Flash and
   DeepSeek v4.1 Flash with its reasoning field read; GLM-4.7-Flash is in) to the table above
   (its `compare` job's log); change `scripts/announcement_readers.txt` only if one beats a chosen reader
   at a usable speed (about a minute a filing at most).
2. Done: the reader's PR dry run on real filings is green with the currency fix (run 38448018056). The
   owner merges PR #56.
3. After the merge: the first live runs; check the usage log (calls, 429s, seconds), the Brief card, and
   the BSE step from the runner (plain requests or in-page fetch).
4. Brief cards: "before this" from our own data (dilution, promoter holding and pledge, issue price vs
   CMP, size vs market cap, insider and deal activity); per-company history on the Company page.
5. Sorter for `to_sort` filings from the subject plus the first ~1,500 characters (with the regulation
   cited there), so routine board outcomes are not read in full.
6. XBRL of announcements: `hasXbrl` is true on all NSE rows but no URL is given; not probed yet.

### Evidence-backed card narrative (18 Oct 2026)

Each new read may include a short narrative in addition to the checked headline, points, fields and metrics. The narrative can connect a previously verified management-call statement or company event with the current filing, and can surface explicit forward guidance from the current filing. Every narrative sentence must cite verbatim evidence from the current filing or persistent company memory; the reader verifies source membership and number support before it is stored or shown. Claims that guidance was met/missed require both historical and current evidence for the same measure, and simple percentage-margin comparisons are checked deterministically. Unsupported claims are held back. The prompt version is bumped so eligible recent filings are reread once.

The deterministic semantic gate also holds claims that turn a cancellation into a win, promote a proposal to an approval/completion, reverse the direction of a measure, or name a counterparty absent from the supporting quote. It is deliberately conservative and must be judged on false positives as well as false negatives in the reviewed card set.

### Headline format (16 Oct, owner's rule)

A reader should know the news from the title alone. The headline is the company's short trading name, a plain verb and the one
figure that matters, in rupees ("Ujjivan SFB approves ₹409 Cr preferential issue", "Aurum PropTech Q2 income rises 57% to ₹137 Cr",
"Onward Technologies raises FY27 growth outlook"), at most 70 characters; ₹ and Cr from one crore up, Lakh below, rounded to three
significant digits and never more than 0.4% from the filing's figure; a foreign currency as the filing writes it. A subtitle
(one line, "Up to 6.32 crore equity shares") carries the second fact. The subtitle is stored inside the headline (`headline.subtitle`),
is checked like the headline (its quote in the filing, its figures in its own quote) and shows under it only when the headline shows.
Prompt `live-10`; earlier reads are read again once.

### Context on the card (16 Oct, owner's request; design, not built)

The card should tell what the event means for this company, not only what the filing says. Rules:

1. **Our code computes every context figure from our own tables; the model writes none.** A figure carries its
   source and date ("TTM revenue, 4 quarters to 30 Jun 2026, NSE XBRL"). A block shows only when every input it
   needs exists; otherwise it is left out, never estimated (CLAUDE.md rules 2 and 7).
2. **Each category gets its own blocks.** Promoter holding belongs to insider trades and to fundraising where
   promoters take part; it is not shown on a deal or an order.
3. **A condition the filing states is kept** (subject to approval, up to, proposed); a change is shown as the
   filing's two numbers and our difference (59.67% to 58.23% is -1.44 percentage points; a stake still above 50%
   is "remains a subsidiary", never a loss of control).

| Category | Blocks (inputs) | Have today | To collect |
|---|---|---|---|
| Order or contract win | Order size against TTM revenue; order book before and after; orders this FY | Order size (card); market cap | TTM revenue (quarterly results XBRL, `insiders_clean/results.py`, in progress); order book from our earlier cards for the company ("as stated on date") |
| Preferential, rights, QIP, warrants | Price against last close and against the SEBI ICDR reference price (needs the relevant date from the filing and our volume and value for a VWAP); issue size against market cap; dilution (new shares / shares outstanding); promoter participation; warrants converted, outstanding | Last close, market cap, issue price and shares (card) | Shares outstanding and outstanding convertibles (shareholding XBRL, partly there) |
| Debt repaid or raised | Borrowings before; after = before - or + amount, marked as pro forma | Amount (card) | Borrowings from the results XBRL balance sheet |
| Quarterly results | Quarter against year-ago quarter and previous quarter: revenue, EBITDA, margins, PAT, exceptional items; growth accelerating or not; PAT with and without exceptional items | Card metrics from the press release | Results XBRL for 8 quarters back; EBITDA is derived (profit before tax + finance costs + depreciation - other income), labelled as ours |
| Acquisition, divestment, stake change | Value against acquirer's market cap and TTM revenue; stake before, after, change in percentage points; cash or shares; funding source; expected completion | Fields from the filing | Acquirer size from the tables above |
| Capacity and capex | Existing, new, increase %; project cost; spent and remaining; commissioning date; phase (Jindal Paradip: 12.5 MTPA entering operation, 25 MTPA across two phases) | Card fields (capacity_to) | Earlier capacity cards for the company; phase needs a field of its own in the prompt |

Shape (owner's proposal, 16 Oct): a reusable **context engine** between the stored facts and the card, not more
model prose. `insiders_clean/context.py`: pure functions `context_for(event, tables)` returning blocks; each block has
`kind`, `label`, `value`, `unit`, `inputs` (name, value, as-of date, source table) and `status` (`ok` or
`unavailable` with the reason). Computed in the precompute step and stored beside the card, so the site only renders
and a rule change needs no re-read. Three layers on the card, always labelled apart:

- **Reported fact**: from the filing, with its quote (an order of Rs 500 Cr).
- **Calculation**: ours, from dated inputs (order / TTM revenue = 50%; debt after = before - repaid, pro forma).
- **Interpretation**: only from a written rule with its threshold (an order of 25% or more of TTM revenue is "large
  for the company"), never a model's guess. The model writes no "why it matters" (13 Oct decision stands: it would
  be invented without concalls and annual reports; owner, 16 Oct: collect them, and management's own words may then enter the card as reported facts with their quote and date, never as our opinion). A fixed "Unknowns" line lists, from the code, which inputs were
  missing.

Rules: missing is never zero (no baseline, no comparison: "not available: no debt figure since 31 Mar 2026"); every
comparison shows both dates (a March debt figure is labelled March, with its age); facts, calculations and
interpretations are never mixed in one sentence.

Build order, each step behind its own tests and a sample on real cards: (1) fundraising blocks (all inputs in
hand but shares outstanding); (2) quarterly results XBRL for the last 8 quarters, then results and order blocks;
(3) debt; (4) capacity and M&A blocks that need only the filing and earlier cards.

### Supervised batches and the audit (16 Oct)

- **Runs 1 to 4** (100 filings each; run 4: 77 cards, 66 read plus copies) and **run 5** (live-10, 14:04 IST). After each,
  every card is audited: `card-audit.yml` (hours=N), then ten independent reviewers each check about eight cards
  against the filing (every headline, point, field, metric and year-ago value; units, period, standalone or
  consolidated, status words, held claims that were right). My own pass found 4 to 5 problems in run 4; the
  reviewers found about 60. Never audit alone.
- **Rules added from the run-4 audit (#131, #132)**: a face value ("shares of Rs N each", also in dollars) is not a
  price; share capital is not a deal size; a projection or estimate is not a metric; the promoter flag must agree
  with its quote (promoters named: not "non-promoter"; non-promoters named: not "promoter"); a withdrawn deal's
  terms are not shown as live fields; an answer with no category and nothing to show is a failed read so another
  lane reads the filing; amounts keep their unit and currency in the audit. 26 stored cards got lines in
  `scripts/card_holds.txt` (claims beyond their quote, dropped conditions, wrong-entity fields).
- **Lesson**: the audit dump cut filing text at 2,200 characters and re-downloaded files (some came back empty), so
  reviewers could not verify items. It now reads the same cached text as the reader and shows a window round every
  quote. A wrong hold of mine (D&H and Afcons amounts, which were right) came from an audit that hid the unit.
- **Open**: `docs/BLUEPRINT_TODO.md` 12.4 (no headline on about 12 of 77 cards, wrong categories, duplicate
  events, instalment amounts, dropped hedges).

### Headline patterns by category (16 Oct; drafted by Claude on the owner's delegation, owner may veto any)

Company is the short trading name; one verb that keeps the filing's status word (approves, proposes, completes; a
hedge or condition such as "up to", "subject to approval", "appears to be" stays); one figure in rupees as in the
owner's rule; at most 70 characters. The subtitle holds the second most useful fact.

| Category | Headline | Subtitle |
|---|---|---|
| Preferential issue | Ujjivan SFB approves ₹409 Cr preferential issue | Up to 6.32 crore shares at ₹64.73 |
| Rights issue | Shivam Autotech sets ₹120 Cr rights issue | ₹12 a share; record date 23 Oct |
| Order win | Admach Systems wins ₹7.9 Cr steel-plant order | Order book now ₹76.25 Cr |
| Results | Aurum PropTech Q2 income rises 57% to ₹137 Cr | PBT margin 4.8% against a loss a year ago |
| Dividend | Garuda Construction declares ₹0.03 interim dividend | Record date 23 Oct; paid by 14 Nov |
| Buyback | {Co} proposes buyback of up to ₹X Cr at ₹Y a share | Record date; tender or open market |
| Acquisition | Mankind Pharma to buy 70% of ACTx for EUR 48 Mn | Through Mankind Netherlands, in instalments |
| Stake change | Trident Lifeline's stake in Trident Mediquip falls to 58.23% | Down from 59.67% after a private placement |
| Management change | Jyoti Structures names Deepak Salunke CFO | Abdul Hameed Khan stays Whole-time Director |
| Resignation | EPW India's CFO resigns, effective 12 Jan 2027 | Personal reasons |
| Credit rating | CARE upgrades {Co} to A1+ | Commercial paper of ₹25 Cr |
| Debt | Sammaan Capital pays ₹18.6 Cr NCD interest | Due 16 Oct, paid 15 Oct |
| Warrants | Viji Finance lists 1 crore shares from warrant conversion | Issued at ₹2.80, to non-promoters |
| Withdrawal | D&H India withdraws ₹32.6 Cr warrant issue | Price rise and approval delay cited |
| Legal or tax | Afcons: GST appeal order confirms ₹38.82 Cr demand | Company will appeal to GSTAT |
| Regulatory fine | Arvee Labs fined ₹10,000 by NSE | Late XBRL filing |
| Capacity | Aegis commissions 35,000 MT LPG plant at JNPA | To move to Aegis Vopak Terminals |
| Capex | Jindal Paradip port starts 12.5 MTPA of 25 MTPA | Phase I; project cost ₹3,393 Cr |
| Board meeting date | {Co} board meets 5 Nov for Q2 results | |
| Routine | No headline; the card is one line | |

### Decisions on the three offers (16 Oct; owner delegated)

1. **Held items' text is not shown on the site**: it is unverified (CLAUDE.md rules 1 and 4); counts and reasons stay.
2. **A card with nothing shown collapses to one line** (company, subject, link, reason); nothing is deleted or hidden.
3. **Stored cards are re-checked against new deterministic rules without re-reading**, as a clean-step pass (no AI),
   built after run 5's audit.

### More context specs from the owner (16 Oct, second message; design, not built)

- **Lifecycle state on every event**: announced, approved, signed, completed, operational (commenced). Stored as a
  field with the quote that shows it; a proposal is never shown as a completed deal. Later filings are **linked to
  the first event** of the same company, instrument or project (the Jindal Paradip plan, then its commissioning),
  so the card can show the progression and the dates of each step. Needs an event key (company, kind, counterparty
  or ISIN, project name) and a link table; the reader's company memory is the first source.
- **More event types and what each must show**: operational disruption (affected capacity, duration, revenue
  contribution, cause, remediation, restart status); new customer or supplier (concentration, contract size,
  dependency, terms, termination risk); management guidance (previous against revised guidance, actual against
  earlier guidance, remaining period); insolvency or default (amount overdue, creditor, days overdue, resolution
  status, legal proceedings, recovery implications); debt, rating, order, results, fundraising, M&A, capacity and
  management/promoter events as in the earlier section.
- **Earnings quality** on results: PAT growth against operating profit growth, other income share, receivables and
  inventory against sales, operating cash flow against PAT, organic against acquired growth; several periods, the
  same quarter of the year before first for seasonal companies.
- **Sector playbooks** (banks and NBFCs by capital adequacy, asset quality, cost of funds; EPC and capital goods by
  executable order book; pharma by regulatory status and product mix; and so on) chosen by the company's industry
  profile; industrial debt tests never applied to lenders.
- **Order firmness** kept apart: firm order, letter of intent, preferred bidder, framework agreement; never added up
  as one order book.
- **Last reported is not current**: a balance sheet item carries its date and age on the card.

### Build order of the context work (owner, 16 Oct, third message)

Three foundations first, in this order, before sector playbooks and adaptive headlines: (1) a **reliable historical
company profile** (results over 12 quarters, balance sheet lines, share count and ownership, each value with
source, period, publication date, unit, basis and whether reported, calculated or estimated); (2) a
**deterministic context engine** for before and after comparisons and materiality; (3) an **event-linked memory**
of transactions, projects and financial changes over time. The rule for every material announcement: what
happened, what changed, how significant it is for this company, and what evidence is still needed to understand
its consequences. Sector analysis and adaptive headlines come only once these work, so that they cannot produce
confident but unsupported conclusions.

### Run 5 audit and the fixes (16 Oct, live-11)

Run 5 (live-10, 14:04 IST): 80 read, 67 cards audited by ten reviewers. 20 of 67 had no shown headline; in 18 the
headline was held for "a number not in its quote", and the holds were right: the model put the wrong figure in the
new ₹ Cr format (Benares H1 profit "₹148.1 Cr" for 1,480.59 lakh = ₹14.8 Cr, Federal Bank "₹1,35 Cr", Amal
"₹401 Cr" for 401 lakh, a growth rate it worked out itself). Fix, **the model no longer types a money amount, a share
count or a growth percentage**: it writes a token ({amount}, {price}, {shares}, {m1}, {m1_pct}) and our code
(`fill_tokens`, `money_text`) puts in the value already checked in the right unit (₹ Cr from a crore, ₹ Lakh below,
a foreign currency as filed); the growth percentage is our own calculation from the metric's previous value and a
rise word against a fall (or the reverse) holds the headline. Also: a metric's label must be the row of its quote
(profit before tax is not EBITDA); two values for one measure and period are both held (basis not stated); a
percentage is not a count of shares; "subject to approval" in the quote must stay in the headline or point, and
"up to" in a point; the mangled-scan hold is judged where the quote stands, not for the whole filing; quote
matching reads ligatures (NFKC) and joined table cells; the prompt names the company and asks for the sentence that
holds every number, the total row, the exercise price row, the fiscal year of the period, and the acting party of a
shareholder filing. 29 more stored cards got lines in `scripts/card_holds.txt`. Prompt `live-11`.

### Run 7 audit and the fixes (16 Oct, IST; live-11 read, live-13 prompt after)

Run 7 (16:27 to 17:01 IST): 71 filings read, 1 failed; it stopped after 34 of 80 minutes because nvidia timed out
twice (10-minute rests) and the cards left over were not reached (326 candidates not reached). 43 of the 71 cards were
new to the audit; five independent reviewers checked every one: **13 OK, 30 with problems** (run 5 and 6 numbers are
above). Fixed in code, each with a test: a short table row quote ("PAT 110") now matches on whole tokens (it never
matched before: quotes under 8 characters were always "not found"); two different values for one measure take their
standalone or consolidated basis from the heading above the quote instead of being held; text that did not extract
(more than a fifth replacement characters) is not read (J.A. Finance: the model wrote a headline from the subject
line); the exchange-symbol check no longer fires when the symbol is the first word of the legal name (KEC, BASF, CCL);
a target's total voting or equity share capital is never a deal amount (Nirlon); a unit the model types after a figure
token is not doubled ("Cr Cr"); rounding is half up (23.25 lakh). Prompt `live-13` adds: tokens only for listed
metrics, the rating agency is the actor in a rating, name acquirer and seller, the person is the subject of a
resignation, "not exceeding" and "up to" stay, duty plus penalty is called both, number words are numbers. 13 stored
cards got lines in `scripts/card_holds.txt`. **Not fixed yet (checked against the code, or not verifiable here):**
OCR typos in quotes ("Sccond", "Redecmable") and two-column interleaving; accounting negatives "₹(144) Cr";
a sum of quoted parts for a headline; categories (press release read as preferential, a new subsidiary as
acquisition, SAST Reg 29 attachment, results deck as business update); "consolidated" missing from metric labels;
approximate ("nearly") and ceiling flags on fields; point quotes joined with "..." across paragraphs; rated facility
amounts shown as period figures; "FY24-25" style in headlines; whether the pipe-table claims of the reviewers hold on
the full text (the audit shows a truncated text; the loose matcher already ignores pipes).
