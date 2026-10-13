# Announcement reader: state and plan (14 Oct 2026, 00:15 IST)

Where the announcement reader stands, so any session can pick it up. TODO item 29 points here. All on
PR #56, branch `ccr-5fbf9503-x2spo0`, not merged (owner merges). Times are IST.

Code:
- Collectors (no model): `collectors/nse_events/announcements.py` (NSE main board and SME),
  `collectors/bse/announcements.py` (BSE), workflow `announcements.yml` (nightly, 3 days).
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
  (`pdftotext -layout`, ZIPs opened), never PDFs.
- Every value must carry a quote found in the PDF text, and prices and counts must have their digits in
  the quote; otherwise it is held back, never shown. The model gives numbers as written with their unit;
  our code converts (lakh, crore, million, billion) and computes every % change.
- Use free limits up to 95%, through the day (every 15 minutes), not only at night; today's filings first.
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

Every 15 minutes (on `main`, at :07, :22, :37 and :52; GitHub may start a run a few minutes late): collect yesterday's and today's NSE and BSE filings (BSE stops paging at the
first page it already has; yesterday too, so a filing made public between the nightly collection at 22:45
and midnight is read the same night); choose today's and yesterday's filings in a reading group with a PDF or ZIP, newest first;
skip those read before, the same filing on the other exchange, companies below Rs 100 Cr; download, and
copy instead of reading when the same file or text was read before (also when two lanes take one file at
once: the second waits for the first's read); the lanes read different filings at the same time; check
every value; save. A run takes new filings for 11 minutes (`READER_MINUTES` in the workflow),
so it ends before the next starts; what it does not reach waits for the next run.

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
  rate it worked out, or a quote not in the filing holds the sentence back. A metric's year-earlier value
  (`previous`, with its own quote) is checked the same way; the % change is ours. No "impact" label (13
  Oct decision); "why it matters" waits for our own history ("before this", a next step): equisense's
  draws on concalls and annual reports, which we do not collect, so it would be invented here. Reads
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
