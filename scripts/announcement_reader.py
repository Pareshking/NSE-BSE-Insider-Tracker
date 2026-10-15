"""The announcement reader: today's useful NSE and BSE filings read by a model, every value checked.

    python scripts/announcement_reader.py                 # collect today's filings, read the new ones, write R2
    python scripts/announcement_reader.py --dry-run --max 3   # read three, print, write nothing

Runs in GitHub Actions through the day (workflow Announcement reader); the site never calls a model, it
reads clean/current/announcement_reads.parquet. docs/ANNOUNCEMENT_READER.md has the decisions behind it.

1. Collect: yesterday's and today's NSE (main board and SME) and BSE filings into raw_v2/ and the archive,
   as the nightly collectors do (their count reports are left to the nightly run).
2. Choose: filings of today and yesterday, newest first, in a reading group (not routine, not concalls),
   with a PDF or ZIP. Read once: a filing already in the reads archive is skipped; the same filing on the
   other exchange (same ISIN, within six hours, subjects alike; the two copies are different files) and a
   file or text read before are copied, not read again. A company below Rs 100 Cr market cap is not sent.
3. Read: each lane of scripts/announcement_readers.txt reads every chosen filing, the lanes side by side.
   Within a lane the next model takes over when one is busy, refused or timing out; a model timing out
   twice running is left out for the rest of the run.
4. Check: a value is shown only when its quote is found in the filing's text, a number's digits are in
   its quote, and an amount's lakh, crore, million or billion is backed by the quote. Our code converts
   units; the model gives numbers as written. Entity labels are kept but not shown yet (the only field
   where wrong values passed the checks, 13 Oct). Everything else is held back with its reason.
5. Write: archive/announcement_reads/year=YYYY/month=MM.parquet by event_id, clean/current/
   announcement_reads.parquet (the last READ_DAYS days) and the day's usage log in
   clean/reports/announcement_reader/{date}.json (every call: model, answer, seconds).

Only public filing text goes in a prompt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import announcement_sample as s  # noqa: E402 -- prompts, model clients, document text and checks

IST = timezone(timedelta(hours=5, minutes=30))
PROMPT_VARIANT = os.environ.get('CARD_PROMPT_VARIANT', 'baseline').strip().lower()
if PROMPT_VARIANT not in ('baseline', 'v2'):
    raise ValueError('CARD_PROMPT_VARIANT must be baseline or v2')
PROMPT_COMPARE = os.environ.get('CARD_PROMPT_COMPARE', '0').strip() == '1'
PROMPT_VERSION = ('live-5' if PROMPT_VARIANT == 'v2' else
                  'live-4-ab' if PROMPT_COMPARE else 'live-4')  # comparison reads are dry-run only
LANES_FILE = HERE / 'announcement_readers.txt'
READS_PREFIX = 'archive/announcement_reads/'
CLEAN_KEY = 'clean/current/announcement_reads.parquet'
READ_DAYS = 60
COLLECT_DAYS = 2              # yesterday too: a filing made public after the nightly collection (22:45) and
                              # before midnight is read the same night; BSE stops at its first known page
MIN_MCAP = 100 * 1e7          # Rs 100 Cr: smaller companies' PDFs never go to a model
SAME_FILING_HOURS = 6
SAME_FILING_WORDS = 0.4       # share of the shorter subject's words found in the other
MAX_TRIES = 3                 # a filing that failed this often is left (counted in the report)
SLOW_STRIKES = 2              # timeouts in a row before a model is left out for the run
# Free calls a day (as listed 13 Oct), by provider:model or provider; a lane stops a model at 95% of it,
# counting today's earlier runs (usage log) and this one. NVIDIA's ~10K a day "may vary"; Z.ai lists none.
DAILY_CALLS = {'groq:qwen/qwen3.8-27b': 1000, 'gemini:gemini-3.5-flash-lite': 500,
               'gemini:gemini-3.1-flash-lite': 500, 'nvidia': 10_000}
DAILY_SHARE = 0.95
PROVIDERS = {**s.PROVIDERS, 'gemini': (s.API, 'GEMINI_API_KEY', None)}   # Gemini: its own client
# The live reader's categories (14 Oct, owner): the kinds of event listed companies file, after SEBI's LODR
# Schedule III (Regulation 30) and what the exchanges carry besides (results, monthly updates, ratings). The
# test harness keeps its shorter list (its "deal_or_dispute" is split here, as an acquisition filed under
# "dispute" read as trouble), so the 24-filing test stays comparable. Reads before live-3 keep their category.
ADDED = {
    'esop': 'shares allotted or options granted to employees (ESOP, ESPS)',
    'dividend': 'dividend declared or recommended, or its record date',
    'bonus_split': 'bonus issue, stock split or consolidation of shares',
    'acquisition': 'buying a company, a stake or a business, or setting up a subsidiary',
    'divestment': 'selling a company, a stake, a business, a unit or an asset',
    'merger_demerger': 'merger, demerger, amalgamation or another scheme of arrangement',
    'agreement': 'joint venture, partnership, MoU, licensing, shareholder or other strategic agreement',
    'delisting': 'voluntary delisting of the shares',
    'licence_approval': 'a licence, approval, patent or clearance granted, renewed, suspended or withdrawn',
    'operations_start': 'commercial production or operations started at a plant, unit or project',
    'financial_results': 'quarterly, half-year or annual financial results',
    'default': 'delay or default in paying interest or principal on loans or debt securities',
    'restructuring': 'one-time settlement, debt restructuring or a resolution plan with lenders',
    'insolvency': 'insolvency (CIRP), liquidation or winding-up proceedings',
    'legal_regulatory': 'litigation, arbitration, a tax or regulatory order, a penalty, a search or a seizure',
    'fraud': 'fraud, arrest of a promoter, director or officer, or a forensic audit',
    'disruption': 'fire, accident, strike, lockout, shutdown or natural calamity disrupting operations',
    'management_change': 'appointment, resignation or removal of a director, CEO, CFO or other key officer',
    'corporate_change': 'change of name, registered office, share transfer agent, or of the memorandum or articles',
}
CATEGORIES = {**{k: v for k, v in s.CATEGORIES.items() if k not in ('deal_or_dispute', 'routine')}, **ADDED,
              'routine': s.CATEGORIES['routine']}
KNOWN_CATEGORIES = set(CATEGORIES) | {'deal_or_dispute'}
COPY_STATUSES = ('same_file', 'same_text', 'same_filing_other_exchange')
COLUMNS = ('event_id', 'exchange', 'market', 'isin', 'symbol', 'company', 'subject', 'detail', 'group',
           'broadcast_at', 'broadcast_date', 'file_url', 'content_url', 'xbrl_url', 'xbrl_source_event_id', 'xbrl_source_url',
           'has_xbrl', 'market_cap_as_of', 'source_format', 'file_sha256', 'text_sha256', 'text_chars', 'status',
           'same_as', 'tries', 'reason', 'reader', 'reader_lane', 'prompt_version', 'category', 'fields',
           'metrics', 'second_reader', 'second_category', 'second_fields', 'shown', 'held', 'agreed',
           'seconds', 'read_at', 'headline', 'points', 'market_cap_match', 'market_cap')


def log(*parts):
    print(time.strftime('%H:%M:%S'), *parts, flush=True)


# --- lanes ---------------------------------------------------------------------------

def lanes_of(text: str) -> dict[str, list[str]]:
    """{'nvidia': ['nvidia:moonshotai/kimi-k3', ...], 'zai': [...], ...} from the lanes file, in its order."""
    out = {}
    for ln in text.splitlines():
        ln = ln.split('#', 1)[0].strip()
        m = re.match(r'([a-z][a-z0-9_-]*)\s*:\s*(\S.*)$', ln)
        if m and ':' in m.group(2):
            out[m.group(1)] = [x.strip() for x in m.group(2).split(',') if x.strip()]
    return out


class Lane:
    """One lane's models, each provider's in turn; slow models are left out after SLOW_STRIKES timeouts."""

    def __init__(self, name: str, entries: list[str], clients: dict, used_today: dict | None = None):
        self.name, self.entries, self.clients = name, list(entries), clients
        self.strikes, self.dropped = {}, []
        self.rate_limited, self.on_rate_limit = [], None
        self.used_today = used_today or {}   # calls by provider:model in today's earlier runs

    def calls_today(self, key: str) -> int:
        """Calls today under a DAILY_CALLS key (provider:model or provider), earlier runs and this one."""
        prov = key.split(':', 1)[0]
        earlier = sum(n for k, n in self.used_today.items() if k == key or k.startswith(f'{key}:'))
        c = self.clients.get(prov)
        now = sum(1 for m, *_ in getattr(c, 'attempts', []) if key in (prov, f'{prov}:{m}'))
        return earlier + now

    def at_daily_limit(self, entry: str) -> bool:
        keys = [k for k in (entry, entry.split(':', 1)[0]) if k in DAILY_CALLS]
        return any(self.calls_today(k) >= DAILY_SHARE * DAILY_CALLS[k] for k in keys)

    def models(self) -> list[tuple[str, str]]:
        return [tuple(e.split(':', 1)) for e in self.entries if e not in self.dropped and not self.at_daily_limit(e)]

    def providers(self) -> set[str]:
        return {e.split(':', 1)[0] for e in self.entries}

    def read(self, prompt: str) -> tuple[str, str, float]:
        """(reply text, entry that answered, seconds). RuntimeError when every model failed."""
        t0, errors = time.monotonic(), []
        for prov, model in self.models():
            client = self.clients.get(prov)
            if client is None:
                continue
            limit = s.MODEL_LIMITS.get(model.removesuffix('+thinking'), (None,))[0] or PROVIDERS[prov][2]
            if limit and len(prompt) > limit:
                errors.append(f'{prov}:{model}: {len(prompt):,} characters, over its limit')
                continue
            try:
                text, _, used = client.generate([model], prompt, 'read', json_mode=True)
                self.strikes[f'{prov}:{model}'] = 0
                return text, f'{prov}:{used}', round(time.monotonic() - t0, 1)
            except RuntimeError as exc:
                entry = f'{prov}:{model}'
                errors.append(f'{entry}: {exc}'[:200])
                if is_rate_limit_error(str(exc)):
                    if entry not in self.dropped:
                        self.dropped.append(entry)
                    if entry not in self.rate_limited:
                        self.rate_limited.append(entry)
                        log(f'{self.name}: {entry} rate-limited; circuit open for the rest of today')
                        if self.on_rate_limit:
                            self.on_rate_limit(entry, str(exc)[:500])
                if 'Timeout' in str(exc):
                    self.strikes[entry] = self.strikes.get(entry, 0) + 1
                    if self.strikes[entry] >= SLOW_STRIKES and entry not in self.dropped:
                        self.dropped.append(entry)
                        log(f'{self.name}: {entry} timed out {SLOW_STRIKES} times running; left out this run')
        raise RuntimeError('; '.join(errors) or f'{self.name}: no model available (slow, or at its daily limit)')


RATE_LIMIT_PREFIX = 'clean/reports/announcement_reader/rate-limits/'

def is_rate_limit_error(message: str) -> bool:
    """Recognize hard quota responses so a provider is not hammered after it says stop."""
    return bool(re.search(r'HTTP\s*429|rate.?limit|too many requests|tokens per day|quota exceeded|resource exhausted',
                          str(message or ''), re.IGNORECASE))

def load_rate_limited_models(r2, run_date: str) -> dict[str, str]:
    """Models blocked for the rest of a local calendar day, shared by live and history workers."""
    from clean_writer import get
    try:
        raw = get(r2, f'{RATE_LIMIT_PREFIX}{run_date}.json')
    except Exception as exc:  # noqa: BLE001 -- a circuit-breaker lookup must not stop the live reader
        log(f'Could not load provider circuit-breaker marker: {type(exc).__name__}: {exc}')
        return {}
    if not raw:
        return {}
    try:
        body = json.loads(raw)
    except (TypeError, ValueError):
        log(f'Ignoring invalid provider circuit-breaker marker for {run_date}')
        return {}
    if not isinstance(body, dict) or body.get('date') != run_date:
        return {}
    models = body.get('models', {})
    return models if isinstance(models, dict) else {}

def configure_rate_limit_circuit_breaker(lanes: dict[str, Lane], r2, run_date: str) -> None:
    """Restore today's provider blocks and persist new 429/quota blocks for live and historical runs."""
    from clean_writer import get, put
    lock = threading.Lock()
    blocked = load_rate_limited_models(r2, run_date)
    for lane in lanes.values():
        for entry in blocked:
            if entry in lane.entries and entry not in lane.dropped:
                lane.dropped.append(entry)
                lane.rate_limited.append(entry)
                log(f'{lane.name}: {entry} already rate-limited today; skipping it')
        def record(entry: str, reason: str) -> None:
            with lock:
                key = f'{RATE_LIMIT_PREFIX}{run_date}.json'
                try:
                    raw = get(r2, key)
                except Exception as exc:  # noqa: BLE001 -- do not let marker storage interrupt provider failover
                    log(f'Could not read provider circuit-breaker marker before update: {type(exc).__name__}: {exc}')
                    return
                try:
                    body = json.loads(raw) if raw else {'date': run_date, 'models': {}}
                except (TypeError, ValueError):
                    body = {'date': run_date, 'models': {}}
                if not isinstance(body, dict) or body.get('date') != run_date or not isinstance(body.get('models'), dict):
                    body = {'date': run_date, 'models': {}}
                body['models'][entry] = {'blocked_at': datetime.now(timezone.utc).isoformat(),
                                         'reason': reason[:300]}
                try:
                    put(r2, key, json.dumps(body, separators=(',', ':')).encode(), 'application/json')
                except Exception as exc:  # noqa: BLE001 -- this run still skips the limited model in memory
                    log(f'Could not persist provider circuit-breaker marker: {type(exc).__name__}: {exc}')
        lane.on_rate_limit = record

def clients_for(entries, env=os.environ) -> tuple[dict, list[str]]:
    """A client per provider named in the lanes (keys from the environment); notes for what is missing."""
    clients, notes = {}, []
    for prov in dict.fromkeys(e.split(':', 1)[0] for e in entries):
        if prov not in PROVIDERS:
            notes.append(f'{prov}: unknown provider')
            continue
        base, secret, _ = PROVIDERS[prov]
        key = env.get(secret, '').strip()
        if not key:
            notes.append(f'{secret} is not set; {prov} lanes skipped')
            continue
        clients[prov] = s.OpenAICompat(prov, base, key) if prov != 'gemini' else GeminiCalls(key)
    for e in entries:
        prov, model = e.split(':', 1)
        if prov in s.FREE_ONLY and model.removesuffix('+thinking') not in s.FREE_ONLY[prov]:
            notes.append(f'{e}: not one of {prov}\'s free models; never used')
    return clients, notes


class GeminiCalls(s.Gemini):
    """Gemini client; the base client records each actual HTTP generation attempt."""


def usable(entries: list[str]) -> list[str]:
    return [e for e in entries if not (e.split(':', 1)[0] in s.FREE_ONLY
                                       and e.split(':', 1)[1].removesuffix('+thinking') not in s.FREE_ONLY[e.split(':', 1)[0]])]


# --- checks ----------------------------------------------------------------------------

# Currency marks as filings write them, right before a number ('US$ 809mn', 'Rs. 165.65', '₹ 28,200.00').
CURRENCY_MARKS = (('CAD', r'CAD|C\$'), ('AUD', r'AUD|A\$'), ('SGD', r'SGD|(?<!U)S\$'),   # before the plain $
                  ('USD', r'US\s?\$|USD|\$'), ('INR', r'₹|Rs\.?|INR|Rupees'), ('EUR', r'€|EUR'), ('GBP', r'£|GBP'),
                  ('AED', r'AED'), ('ZAR', r'ZAR'), ('JPY', r'JPY|¥'))
MONEY_FIELDS = ('price_per_share', 'max_price_per_share', 'amount')


def currency_in_quote(value, quote) -> str | None:
    """The currency the quote writes right before the value's number; None when it writes none."""
    v = s._num(value)
    if v is None:
        return None
    q = str(quote or '')
    for m in re.finditer(s.NUMBER, q):
        if abs(float(m.group(0).replace(',', '')) - v) < 1e-6 * max(1, abs(v)):
            before = q[max(0, m.start() - 14):m.start()].rstrip()
            for code, pat in CURRENCY_MARKS:
                if re.search(r'(?:' + pat + r')$', before, re.IGNORECASE):
                    return code
    return None


def _bool(v):
    t = str(v).strip().lower()
    return True if t in ('true', 'yes') else False if t in ('false', 'no') else None


def validate(out, doc: str) -> tuple[str | None, list[dict], list[dict]]:
    """(category, fields, metrics), each value with its checks, `shown` and, when held back, `reason`."""
    out = out if isinstance(out, dict) else {}
    named = {}
    for f in out.get('fields') or []:
        if isinstance(f, dict) and f.get('name') in s.FIELDS and f['name'] not in named:
            named[f['name']] = f
    unit = (named.get('amount_unit') or {}).get('value')
    cur = named.get('currency') or {}
    filing_currency = str(cur.get('value')).strip().upper() if cur.get('value') and s.quote_found(cur.get('quote'), doc)         else None
    fields = []
    for name, f in named.items():
        if name == 'amount_unit':
            continue
        value, quote = f.get('value'), f.get('quote')
        qf = s.quote_found(quote, doc)
        rec = {'name': name, 'value': value, 'quote': quote, 'evidence': qf or None, 'reason': None}
        reasons = [] if qf else ['quote not found in the filing']
        if name in s.NUMERIC:
            if not s.digits_in_quote(value, quote):
                reasons.append('number not in its quote')
            rec['number'] = s.in_units(value, unit) if name == 'amount' else s._num(value)
            if rec['number'] is None:
                reasons.append('not one number')
            if name == 'amount':
                rec['unit'] = unit
                if s.unit_backed(value, unit, quote, qf) is False:
                    reasons.append('unit not backed by its quote')
        if name in MONEY_FIELDS:   # the site writes the currency only when the filing does
            rec['currency'] = currency_in_quote(value, quote) or filing_currency
        if name.endswith('_date'):
            rec['date'] = s.as_date(value)
            if rec['date'] is None:
                reasons.append('date not readable')
        elif name == 'allottee_is_promoter':
            rec['flag'] = _bool(value)
            if rec['flag'] is None:
                reasons.append('not yes or no')
        if name == 'entity':
            reasons.append('entity labels not shown yet')
        rec['shown'], rec['reason'] = not reasons, '; '.join(reasons) or None
        fields.append(rec)
    metrics = []
    for m in out.get('metrics') or []:
        if not isinstance(m, dict):
            continue
        value, quote, unit_m = m.get('value'), m.get('quote'), m.get('unit')
        qf = s.quote_found(quote, doc)
        reasons = [] if qf else ['quote not found in the filing']
        if not s.digits_in_quote(value, quote):
            reasons.append('number not in its quote')
        money = str(unit_m or '').strip().lower().rstrip('.') in s.UNIT
        number = s.in_units(value, unit_m) if money else s._num(value)
        if number is None:
            reasons.append('not one number')
        if money and s.unit_backed(value, unit_m, quote, qf) is False:
            reasons.append('unit not backed by its quote')
        metrics.append({'label': m.get('label'), 'period': m.get('period'), 'value': value, 'unit': unit_m,
                        'number': number, 'quote': quote, 'evidence': qf or None,
                        'currency': currency_in_quote(value, quote) if money else None,
                        'shown': not reasons, 'reason': '; '.join(reasons) or None})
    cat = out.get('category') if out.get('category') in KNOWN_CATEGORIES else None
    return cat, fields, metrics


# --- the card's words: a headline and a few points, every number in them found in their quote --------------

CARD_ASK = (
    'Also return "headline": {"text": one line of at most 90 characters describing the actual corporate action, not the exchange filing label, '
    'with its key figure (e.g. "Shivam Autotech sets Rs 120 Cr rights issue at Rs 12 a share"), "quote": the words of '
    'the document that state it}, and "points": 2 to 4 of {"text": one sentence on a fact of the filing a '
    'shareholder needs (what, how much, at what price, to whom, when, on what condition), "quote": the exact '
    'words that state it}. For an acquisition, sale or merger, name the company bought or sold, the stake and '
    'the price; for a legal or regulatory matter, who acted, against whom, and the amount. Never use boilerplate such as "Submission of", "Outcome of Board Meeting", "Outcome of Meeting", "Intimation of", or "Pursuant to", and never copy the exchange subject as the headline. Lead with the approved or announced action and its key terms; if the board approved multiple actions, distinguish them in the points. In a metric of a monthly, quarterly or half-year update, also give "previous": the '
    'same measure for the year-earlier period as written, "previous_period" and "previous_quote". In the '
    'headline and points use only facts and numbers that their quote states, each number as written or '
    'converted exactly (12,000 lakh = 120 crore); no opinion, forecast or judgement of impact, and no growth '
    'rates you work out yourself.\n\n')
# Opt-in experimental prompt. Keep CARD_ASK unchanged as the control for a controlled comparison.
CARD_ASK_V2 = (
    'Also return "headline": {"text": one line of at most 90 characters describing the actual corporate action, '
    'not the exchange filing label, "quote": the exact words of the document that establish it}, and "points": '
    '2 to 4 of {"text": one concise sentence stating a material fact a shareholder needs, "quote": the exact words '
    'that support it}. First establish the event from the filing text; do not infer it from the exchange subject. '
    'For board outcomes, distinguish explicitly whether an action was approved, recommended, deferred, rejected, '
    'considered, or merely noted. Use only the status the document states; never upgrade a proposal or recommendation '
    'to approval, or approval to completion. For acquisitions, divestments and mergers, identify buyer/seller, target, '
    'stake and transaction value when disclosed. For fund-raising, identify instrument, size, price and whether it is '
    'proposed, approved, opened or allotted, as stated. For financial or operating updates, name the reporting period '
    'and principal reported measure. For legal, regulatory or credit events, identify the acting authority or '
    'counterparty, the action and disclosed amount or consequence. Lead with the substantive action or outcome, '
    'not the meeting or filing process. Never copy the exchange subject, use exchange-label boilerplate, or replace '
    'the event with a generic phrase such as "company announces update". If multiple decisions appear, put the '
    'most material supported decision in the headline and keep distinct decisions in separate points. In a metric '
    'of a monthly, quarterly or half-year update, also give "previous": the same measure for the year-earlier period '
    'as written, "previous_period" and "previous_quote". Every factual claim must be supported by its quote; every '
    'number must occur in that quote or be an allowed exact unit conversion (12,000 lakh = 120 crore). No opinion, '
    'forecast, impact claim, independently calculated growth rate, inferred consequence or unsupported completion '
    'claim. If the filing text does not establish an actual action or outcome, return an empty headline rather than '
    'invent one; preserve independently supported points. Return the existing JSON schema only.\n\n')

_NUM = re.compile(r'(?<![\w.])(\d[\d,]*(?:\.\d+)?)\s*(lakhs?|lacs?|crores?|crs?\b|million|mn\b|m\b|billion|bn\b'
                  r'|thousand|k\b)?', re.IGNORECASE)
_MULT = {'lakh': 1e5, 'lakhs': 1e5, 'lac': 1e5, 'lacs': 1e5, 'crore': 1e7, 'crores': 1e7, 'cr': 1e7, 'crs': 1e7,
         'million': 1e6, 'mn': 1e6, 'm': 1e6, 'billion': 1e9, 'bn': 1e9, 'thousand': 1e3, 'k': 1e3}


def card_prompt(row: dict, doc: str, variant: str | None = None) -> str:
    p = s.read_prompt({'exchange': row['exchange'], 'symbol': row.get('symbol') or row.get('company'),
                       'subject': row.get('subject')}, doc)
    head, rest = p.split('Categories:\n', 1)
    rest = rest.split('\n\nFields:', 1)[1]
    cats = '\n'.join(f'- {k}: {v}' for k, v in CATEGORIES.items())
    p = f'{head}Categories:\n{cats}\n\nFields:{rest}'
    selected = (variant or PROMPT_VARIANT).strip().lower()
    if selected not in ('baseline', 'v2'):
        raise ValueError('variant must be baseline or v2')
    ask = CARD_ASK_V2 if selected == 'v2' else CARD_ASK
    memory = str(row.get('_company_memory') or '').strip()
    context = ('Earlier verified company history (use only as context; the current filing remains the source for every new claim). '
               'Each prior item includes its date, filing ID and source URL:\n' + memory + '\n\n') if memory else ''
    return p.replace('=== DOCUMENT ===', ask + context + '=== DOCUMENT ===', 1)

def numbers_in(text) -> list[tuple[float, float]]:
    """Each number of a text as (as written, times its unit word when it has one): '120 Cr' -> (120, 1.2e9)."""
    out = []
    for m in _NUM.finditer(str(text or '')):
        try:
            n = float(m.group(1).replace(',', ''))
        except ValueError:
            continue
        out.append((n, n * _MULT.get((m.group(2) or '').lower().rstrip('.'), 1)))
    return out


def numbers_backed(text, quotes) -> bool:
    """Every number of `text` is one of the quotes' numbers, as written or with its unit applied (within 0.5%):
    the model may write 12,000 lakh as 120 crore, never a number of its own."""
    have = {v for q in quotes for pair in numbers_in(q) for v in pair}
    return all(any(abs(v - h) <= 0.005 * max(1.0, abs(h)) for h in have for v in pair) for pair in numbers_in(text))


def headline_quality_reason(text: str) -> str | None:
    """Reject exchange-subject boilerplate as a headline even when its quote is real."""
    value = re.sub(r'\s+', ' ', str(text or '')).strip()
    if not value:
        return 'headline is empty'
    # Exchange descriptions often prefix the boilerplate with the company name and a colon.
    lead = re.sub(r'^[^:\n]{1,90}:\s*', '', value, count=1)
    boilerplate = re.compile(
        r'^(?:submission\s+of\b|outcome\s+of\s+(?:(?:the\s+)?board\s+)?meeting\b|'
        r'board\s+meeting\s+outcome\b|intimation\s+of\b|pursuant\s+to\b|'
        r'proceedings\s+of\s+(?:the\s+)?board\s+meeting\b)', re.IGNORECASE)
    if boilerplate.search(lead) or boilerplate.search(value):
        return 'exchange filing-label boilerplate, not a corporate-action headline'
    return None


def check_words(item, doc: str, more_quotes=()) -> dict | None:
    """A headline or point: shown only when its quote is in the filing and every number in it is in that quote
    (it may also use the quotes of values already checked, and a headline those of the shown points)."""
    if not isinstance(item, dict) or not str(item.get('text') or '').strip():
        return None
    text, quote = str(item['text']).strip(), item.get('quote')
    qf = s.quote_found(quote, doc)
    reasons = [] if qf else ['quote not found in the filing']
    if not numbers_backed(text, [quote, *more_quotes]):
        reasons.append('a number not in its quote')
    return {'text': text, 'quote': quote, 'evidence': qf or None, 'shown': not reasons,
            'reason': '; '.join(reasons) or None}


def card_words(out, doc: str, fields: list[dict], metrics: list[dict]) -> tuple[dict | None, list[dict]]:
    out = out if isinstance(out, dict) else {}
    values = [f['quote'] for f in fields + metrics if f.get('shown')]   # quotes already checked in the filing
    points = [p for p in (check_words(x, doc, values) for x in (out.get('points') or [])[:4]) if p]
    backed = [p['quote'] for p in points if p['shown']] + values
    headline = check_words(out.get('headline'), doc, backed)
    if headline:
        quality_reason = headline_quality_reason(headline['text'])
        if quality_reason:
            headline['shown'] = False
            headline['reason'] = '; '.join(x for x in (headline.get('reason'), quality_reason) if x)
    return headline, points


def with_previous(m: dict, raw: dict, doc: str) -> dict:
    """A metric's year-earlier value, checked as the metric is; our own change in % when both are shown."""
    prev, q = raw.get('previous'), raw.get('previous_quote')
    if prev in (None, '') or not m.get('shown'):
        return m
    unit = m.get('unit')
    money = str(unit or '').strip().lower().rstrip('.') in s.UNIT
    n = s.in_units(prev, unit) if money else s._num(prev)
    ok = bool(s.quote_found(q, doc)) and s.digits_in_quote(prev, q) and n is not None
    m = {**m, 'previous': prev, 'previous_period': raw.get('previous_period'), 'previous_quote': q,
         'previous_number': n if ok else None}
    if ok and n and m.get('number') is not None:
        m['change_pct'] = round((m['number'] - n) / abs(n) * 100, 1)
    return m


def metric_agreement(main: list[dict], second: list[dict]) -> dict:
    """Per shown metric of the main read (key "metric:<position>"): True when the second read has a shown
    metric of the same number (within 0.5%), else None. Two models label one figure differently, so the
    number is what is compared; a figure the second read does not give is not counted against it."""
    theirs = [m.get('number') for m in second if m.get('shown') and isinstance(m.get('number'), (int, float))]
    out = {}
    for i, m in enumerate(main):
        n = m.get('number')
        if m.get('shown') and isinstance(n, (int, float)):
            out[f'metric:{i}'] = True if any(abs(n - t) <= 0.005 * max(1.0, abs(n)) for t in theirs) else None
    return out


def agreement(main: list[dict], second: list[dict]) -> dict:
    """Per shown field of the main read: True when the second read gives the same value, False when it
    gives another, None when it gives none."""
    other = {f['name']: f for f in second}
    out = {}
    for f in main:
        if not f['shown']:
            continue
        g = other.get(f['name'])
        if g is None:
            out[f['name']] = None
        elif 'number' in f:
            a, b = f.get('number'), g.get('number')
            out[f['name']] = a is not None and b is not None and abs(a - b) <= 0.005 * max(1.0, abs(a))
        else:
            key = 'date' if 'date' in f else 'flag' if 'flag' in f else 'value'
            out[f['name']] = str(f.get(key)).strip().lower() == str(g.get(key)).strip().lower()
    return out


# --- choosing what to read ---------------------------------------------------------------

def _words(text) -> set[str]:
    return set(re.findall(r'[a-z]{4,}', str(text or '').lower())) - {
        'limited', 'company', 'regulation', 'regulations', 'sebi', 'listing', 'obligations', 'disclosure',
        'requirements', 'informed', 'exchange', 'regarding', 'pursuant'}


def same_filing(a: dict, b: dict) -> bool:
    """The same filing sent to both exchanges: same ISIN, within SAME_FILING_HOURS, subjects alike."""
    if not a.get('isin') or a.get('isin') != b.get('isin') or a.get('exchange') == b.get('exchange'):
        return False
    ta, tb = pd.Timestamp(a['broadcast_at']), pd.Timestamp(b['broadcast_at'])
    if abs((ta - tb).total_seconds()) > SAME_FILING_HOURS * 3600:
        return False
    wa, wb = _words(f"{a['subject']} {a['detail']}"), _words(f"{b['subject']} {b['detail']}")
    return bool(wa and wb) and len(wa & wb) / min(len(wa), len(wb)) >= SAME_FILING_WORDS


def candidates(nse: pd.DataFrame | None, bse: pd.DataFrame | None, master) -> pd.DataFrame:
    """Normalize NSE/BSE filings and use a verified related NSE XBRL attachment when available."""
    from collectors.bse import announcements as bann
    from collectors.nse_events import announcements as nann

    def clean(value):
        if value is None:
            return None
        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):
            pass
        value = str(value).strip()
        return None if value.casefold() in ('', 'nan', 'none', '<na>') else value

    rows = []
    for r in (nse.to_dict('records') if nse is not None else []):
        symbol = clean(r.get('symbol'))
        isin = clean(r.get('isin'))
        if not isin and master and symbol:
            resolved = master.resolve('nse', symbol)
            isin = clean(resolved[0] if resolved else None)
        url = clean(r.get('file_url'))
        xbrl_url = clean(r.get('xbrl_url'))
        xbrl_feed_row = str(r.get('event_id') or '').startswith('nse:xbrl:')
        rows.append({'event_id': r['event_id'], 'exchange': 'NSE', 'market': r.get('market') or 'equities',
                     'isin': isin, 'symbol': symbol, 'company': clean(r.get('company')),
                     'subject': clean(r.get('subject')), 'detail': clean(r.get('text')),
                     # Dedicated XBRL rows are companion payloads, never standalone user-facing cards.
                     'group': 'routine' if xbrl_feed_row else nann.group_of(clean(r.get('subject')), clean(r.get('text'))),
                     'file_url': url, 'content_url': xbrl_url or url, 'xbrl_url': xbrl_url,
                     'xbrl_source_event_id': r['event_id'] if xbrl_url and not xbrl_feed_row else None,
                     'xbrl_source_url': xbrl_url if not xbrl_feed_row else None, 'market_cap_match': None,
                     'has_xbrl': r.get('has_xbrl'), 'market_cap_as_of': getattr(master, 'market_cap_as_of', None),
                     'file_type': r.get('file_type'), 'broadcast_at': r.get('broadcast_at'),
                     'broadcast_date': r.get('broadcast_date')})
    for r in (bse.to_dict('records') if bse is not None else []):
        bse_code = clean(r.get('bse_code'))
        resolved = master.resolve('bse', bse_code) if master and bse_code else None
        isin = clean(resolved[0] if resolved else None)
        rec = (master.record(isin) or {}) if master and isin else {}
        url = clean(r.get('file_url'))
        rows.append({'event_id': r['event_id'], 'exchange': 'BSE', 'market': 'bse', 'isin': isin,
                     'symbol': clean(rec.get('nse_symbol')) or bse_code, 'company': clean(r.get('company')),
                     'subject': clean(r.get('subcategory')) or clean(r.get('category')), 'detail': clean(r.get('headline')),
                     'group': bann.group_of(clean(r.get('subcategory')) or clean(r.get('category')), clean(r.get('category'))), 'file_url': url,
                     'content_url': url, 'xbrl_url': None, 'xbrl_source_event_id': None, 'xbrl_source_url': None, 'market_cap_match': None,
                     'has_xbrl': None, 'market_cap_as_of': getattr(master, 'market_cap_as_of', None),
                     'file_type': r.get('file_type'), 'broadcast_at': r.get('broadcast_at'),
                     'broadcast_date': r.get('broadcast_date')})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # Prefer the exact ISIN's official cap; if that ISIN is absent from the snapshot, retry the
    # exchange symbol/code mapping. NSE feeds can carry stale ISINs while the listed symbol remains valid.
    market_caps, cap_matches = [], []
    def valid_cap(value):
        number = pd.to_numeric(pd.Series([value]), errors='coerce').iloc[0]
        return pd.notna(number) and number > 0
    for row in df.to_dict('records'):
        isin = clean(row.get('isin'))
        record = master.record(isin) if master and isin else None
        cap = record.get('market_cap') if record else None
        match = 'isin' if valid_cap(cap) else None
        if not valid_cap(cap) and master:
            exchange = 'nse' if row.get('exchange') == 'NSE' else 'bse'
            symbol = clean(row.get('symbol'))
            resolved = master.resolve(exchange, symbol) if symbol else None
            mapped_isin = clean(resolved[0] if resolved else None)
            mapped = master.record(mapped_isin) if mapped_isin else None
            mapped_cap = mapped.get('market_cap') if mapped else None
            if valid_cap(mapped_cap):
                cap, match = mapped_cap, 'exchange_symbol'
        market_caps.append(cap if valid_cap(cap) else None)
        cap_matches.append(match)
    df['market_cap'] = market_caps
    df['market_cap_match'] = cap_matches

    # The upstream hasXbrl boolean is not an attachment URL and can be present on ordinary
    # PDF rows. Never use it as proof that a companion exists or as a prerequisite for pairing.
    # Pair only an independently observed XML/XBRL attachment (or explicitly XBRL-labelled ZIP)
    # with a same-issuer/date candidate under the strict subject/ambiguity gates below. Never
    # synthesize an exchange URL.
    def subject_base(value):
        value = str(value or '').strip().casefold()
        value = re.sub(r'\s*[-–—]\s*xbrl\s*$', '', value)
        value = re.sub(r'\s*\(xbrl\)\s*$', '', value)
        return re.sub(r'[^a-z0-9]+', ' ', value).strip()

    def day(value):
        parsed = pd.to_datetime(value, errors='coerce')
        return None if pd.isna(parsed) else parsed.date()

    records = df.to_dict('records')
    structured_rows = []
    for idx, row in enumerate(records):
        # XML/XBRL files are reliable structured companions even when their subject omits
        # "XBRL". A generic ZIP is not: these feeds also use ZIP for ordinary documents
        # (for example KMP resignation attachments). Accept ZIP only when its subject or
        # URL explicitly identifies XBRL; otherwise leave the PDF as the safe fallback.
        file_type = str(row.get('file_type') or '').strip().lower()
        xbrl_hint = re.search(r'\bxbrl\b', f"{row.get('subject') or ''} {row.get('file_url') or ''}", re.IGNORECASE)
        is_xbrl_payload = file_type in ('xml', 'xbrl') or (file_type == 'zip' and bool(xbrl_hint))
        if row.get('exchange') == 'NSE' and is_xbrl_payload and row.get('file_url'):
            structured_rows.append((idx, row))
    used_xbrl = set()
    for idx, row in enumerate(records):
        if row.get('exchange') != 'NSE':
            continue
        if str(row.get('file_type') or '').lower() not in ('pdf', 'zip') or not row.get('file_url'):
            continue
        identifier = str(row.get('isin') or row.get('symbol') or '').strip().upper()
        subject = subject_base(row.get('subject'))
        broadcast_day = day(row.get('broadcast_date'))
        if not identifier or not subject or broadcast_day is None:
            continue
        matches, nearby_structured = [], []
        for xidx, xrow in structured_rows:
            if xidx in used_xbrl or xidx == idx:
                continue
            xidentifier = str(clean(xrow.get('isin')) or clean(xrow.get('symbol')) or '').strip().upper()
            xday = day(xrow.get('broadcast_date'))
            if xidentifier != identifier or xday is None or abs((xday - broadcast_day).days) > 1:
                continue
            candidate = (abs((xday - broadcast_day).days), str(xrow.get('broadcast_at') or ''), xidx, xrow)
            nearby_structured.append(candidate)
            if subject_base(xrow.get('subject')) == subject:
                matches.append(candidate)
        # Pair only when the issuer/date window has one eligible PDF and one eligible
        # XBRL payload. Repeated generic subjects are common for separate KMP filings;
        # choosing the first exact-subject match can cross-wire distinct disclosures.
        other_pdfs, other_same_subject_pdfs = [], []
        for pidx, prow in enumerate(records):
            if pidx == idx or prow.get('exchange') != 'NSE':
                continue
            if str(clean(prow.get('file_type')) or '').lower() not in ('pdf', 'zip') or not prow.get('file_url'):
                continue
            pidentifier = str(clean(prow.get('isin')) or clean(prow.get('symbol')) or '').strip().upper()
            pday = day(prow.get('broadcast_date'))
            if pidentifier == identifier and pday is not None and abs((pday - broadcast_day).days) <= 1:
                other_pdfs.append(pidx)
                # An unrelated disclosure by the same issuer/date is not ambiguity by itself.
                # Another PDF with the same normalized subject is ambiguous, because generic
                # exchange subjects are often reused for distinct KMP/director filings.
                if subject_base(prow.get('subject')) == subject:
                    other_same_subject_pdfs.append(pidx)
        if len(matches) == 1 and not other_same_subject_pdfs:
            _, _, xidx, xrow = matches[0]
        elif matches:
            # More than one exact XBRL match or another same-subject PDF is ambiguous; do not guess.
            continue
        else:
            # Never pair solely because issuer/date match: a company can file unrelated disclosures
            # on the same day, and the XBRL feed often uses a broad event category. If subjects differ,
            # require the XBRL appId to appear as a whole numeric token in this PDF/ZIP URL, and require
            # that exactly one eligible PDF for this issuer/date carries that appId.
            def xbrl_app_id(item):
                event_id = str(item[3].get('event_id') or '')
                match = re.match(r'^nse:xbrl:[^:]+:([^:]+):', event_id)
                return match.group(1) if match else ''

            id_matches = []
            for item in nearby_structured:
                app_id = xbrl_app_id(item)
                if app_id and re.search(rf'(?<![A-Za-z0-9]){re.escape(app_id)}(?![A-Za-z0-9])', str(row.get('file_url') or '')):
                    id_matches.append(item)
            if len(id_matches) != 1:
                continue
            app_id = xbrl_app_id(id_matches[0])
            id_pdfs = []
            for pidx in [idx] + other_pdfs:
                purl = str(records[pidx].get('file_url') or '')
                if re.search(rf'(?<![A-Za-z0-9]){re.escape(app_id)}(?![A-Za-z0-9])', purl):
                    id_pdfs.append(pidx)
            if len(id_pdfs) != 1:
                continue
            _, _, xidx, xrow = id_matches[0]
        row['content_url'] = xrow['file_url']
        row['xbrl_source_event_id'] = xrow.get('event_id')
        row['xbrl_source_url'] = xrow['file_url']
        # This XML event now supplies the PDF event's content; suppress a duplicate model read.
        records[xidx]['group'] = 'routine'
        used_xbrl.add(xidx)
    return pd.DataFrame(records)


def xbrl_audit(cands: pd.DataFrame | None) -> dict:
    """Dry-run diagnostics proving whether XBRL companions are present and being used."""
    if cands is None or cands.empty:
        return {'candidates': 0, 'has_xbrl_flagged': 0, 'has_xbrl_flagged_pdf_rows': 0,
                'flagged_without_direct_xbrl_url': 0, 'direct_xbrl_urls': 0, 'xbrl_attachments': 0,
                'structured_attachments': 0, 'zip_attachments': 0, 'xbrl_labelled_zip_attachments': 0,
                'xbrl_subject_labels': 0, 'xbrl_linked': 0,
                'flagged_samples': [], 'direct_xbrl_samples': [], 'attachment_samples': [],
                'structured_samples': [], 'zip_samples': [], 'linked_samples': []}
    has_flag = cands.get('has_xbrl', pd.Series(index=cands.index, dtype=object)).map(
        lambda value: str(value).strip().casefold() in ('true', '1', 'yes'))
    subject_xbrl = cands.get('subject', pd.Series(index=cands.index, dtype=str)).fillna('').astype(str).str.contains(
        r'\bxbrl\b', case=False, regex=True)
    file_type = cands.get('file_type', pd.Series(index=cands.index, dtype=str)).fillna('').astype(str).str.lower()
    zip_attachment = file_type.eq('zip')
    # XML/XBRL is a positive structured-format signal without a subject label.
    # ZIP is only an archive format: it is not evidence of XBRL unless its subject or URL says XBRL.
    xbrl_hint = (
        cands.get('subject', pd.Series(index=cands.index, dtype=str)).fillna('').astype(str)
        + ' ' + cands.get('file_url', pd.Series(index=cands.index, dtype=str)).fillna('').astype(str)
    ).str.contains(r'\bxbrl\b', case=False, regex=True)
    structured_attachment = file_type.isin(('xml', 'xbrl'))
    xbrl_labelled_zip = zip_attachment & xbrl_hint
    attachment = structured_attachment | xbrl_labelled_zip
    direct = cands.get('xbrl_url', pd.Series(index=cands.index, dtype=object)).map(
        lambda value: bool(str(value).strip()) and str(value).strip().casefold() not in ('nan', 'none', '<na>'))
    linked = cands.get('xbrl_source_event_id', pd.Series(index=cands.index, dtype=object)).notna()
    fields = [field for field in ('event_id', 'exchange', 'symbol', 'isin', 'subject', 'broadcast_date',
                                  'file_type', 'has_xbrl', 'file_url', 'content_url', 'xbrl_url',
                                  'xbrl_source_event_id', 'xbrl_source_url') if field in cands]
    def sample(mask):
        return cands.loc[mask, fields].head(50).to_dict('records')
    return {'candidates': int(len(cands)), 'has_xbrl_flagged': int(has_flag.sum()),
            # These are diagnostics, not proof of XBRL availability: the upstream boolean can be
            # true while its row only exposes a PDF and no direct XBRL URL.
            'has_xbrl_flagged_pdf_rows': int((has_flag & file_type.eq('pdf')).sum()),
            'flagged_without_direct_xbrl_url': int((has_flag & ~direct).sum()),
            'direct_xbrl_urls': int(direct.sum()), 'xbrl_attachments': int(attachment.sum()),
            'structured_attachments': int(structured_attachment.sum()),
            'zip_attachments': int(zip_attachment.sum()),
            'xbrl_labelled_zip_attachments': int(xbrl_labelled_zip.sum()),
            'xbrl_subject_labels': int((attachment & subject_xbrl).sum()),
            'xbrl_linked': int(linked.sum()), 'flagged_samples': sample(has_flag),
            'direct_xbrl_samples': sample(direct), 'attachment_samples': sample(attachment),
            'structured_samples': sample(structured_attachment), 'zip_samples': sample(zip_attachment),
            'linked_samples': sample(linked)}


def choose(cands: pd.DataFrame, done: pd.DataFrame | None, today: date, *,
           date_from: date | None = None, date_to: date | None = None) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Choose recent filings, or an explicit inclusive historical date range; no model calls here."""
    counts = {}
    if cands is None or cands.empty:
        return pd.DataFrame(), pd.DataFrame(), {'candidates': 0}
    if date_from is not None or date_to is not None:
        first, last = date_from or date.min, date_to or today
        dates = pd.to_datetime(cands['broadcast_date'], errors='coerce').dt.date
        c = cands[(dates >= first) & (dates <= last)].copy()
    else:
        days = {today.isoformat(), (today - timedelta(days=1)).isoformat()}
        c = cands[cands['broadcast_date'].isin(days)].copy()
    counts['candidates'] = len(c)
    finished = set()
    tries = {}
    if done is not None and not done.empty:
        # Quota-deferred filings are deliberately retryable without consuming the failure budget.
        retryable = done['status'].isin(('failed', 'market_cap_unverified', 'quota_deferred'))
        failed = done['status'] == 'failed'
        # A read with an older prompt is reread once; missing cap data is re-evaluated next run, not retired.
        stale = done['status'].isin(('read', 'same_file', 'same_text')) & \
            (done['prompt_version'] != PROMPT_VERSION if 'prompt_version' in done else True)
        exhausted_failures = failed & (pd.to_numeric(done['tries'], errors='coerce').fillna(0) >= MAX_TRIES)
        # Only genuine repeated filing failures consume MAX_TRIES. Quota-deferred work and
        # missing-cap rows remain retryable, even if a prior status carried a large tries count.
        finished = set(done.loc[(~retryable & ~stale) | exhausted_failures, 'event_id'])
        tries = done.loc[failed].set_index('event_id')['tries'].to_dict()
    keep = c['group'].ne('routine') & c['file_url'].notna() & c['file_type'].isin(['pdf', 'zip', 'xml', 'xbrl'])
    counts['routine_or_no_file'] = int((~keep).sum())
    c = c[keep & ~c['event_id'].isin(finished)]
    counts['already_done'] = int(keep.sum()) - len(c)
    c = c.sort_values(['broadcast_date', 'broadcast_at'], ascending=False)
    c['tries'] = c['event_id'].map(tries).fillna(0).astype(int)
    status_rows, read_rows = [], []
    earlier = [] if done is None or done.empty else done[done['status'].isin(('read',) + COPY_STATUSES)] \
        .to_dict('records')
    for r in c.sort_values('broadcast_at').to_dict('records'):   # oldest first, so the first copy is read
        mcap = pd.to_numeric(pd.Series([r.get('market_cap')]), errors='coerce').iloc[0]
        if pd.isna(mcap) or mcap <= 0:
            status_rows.append({**r, 'status': 'market_cap_unverified',
                                'reason': 'no verified market-cap value in the latest snapshot dated on or before yesterday'})
            continue
        if mcap < MIN_MCAP:
            status_rows.append({**r, 'status': 'below_100_cr', 'reason': f'market cap Rs {mcap / 1e7:,.2f} Cr'})
            continue
        twin = next((e for e in earlier + read_rows if same_filing(r, e)), None)
        if twin is not None:
            status_rows.append({**r, 'status': 'same_filing_other_exchange', 'same_as': twin['event_id']})
            continue
        read_rows.append(r)
    counts['below_100_cr'] = sum(x['status'] == 'below_100_cr' for x in status_rows)
    counts['market_cap_unverified'] = sum(x['status'] == 'market_cap_unverified' for x in status_rows)
    counts['same_filing_other_exchange'] = sum(x['status'] == 'same_filing_other_exchange' for x in status_rows)
    to_read = pd.DataFrame(read_rows)
    if not to_read.empty:
        to_read = to_read.sort_values(['broadcast_date', 'broadcast_at'], ascending=False)
    counts['to_read'] = len(to_read)
    return to_read, pd.DataFrame(status_rows), counts


# --- reading ---------------------------------------------------------------------------

def read_one(lane: Lane, row: dict, doc: str) -> dict:
    """One lane's read of one filing: {'ok': True, reader, seconds, category, fields, metrics} with every value
    checked, or {'ok': False, 'error'} (every model of the lane busy, refused, too slow, or the reply not JSON)."""
    prompt = card_prompt(row, doc)
    try:
        text, used, secs = lane.read(prompt)
    except RuntimeError as exc:
        return {'ok': False, 'error': f'{lane.name}: {exc}'[:300]}
    out = s.parse_json(text)
    if out is None:
        return {'ok': False, 'error': f'{lane.name}: {used}: reply was not JSON'}
    cat, fields, metrics = validate(out, doc)
    raw = [m for m in (out.get('metrics') or []) if isinstance(m, dict)] if isinstance(out, dict) else []
    if len(raw) == len(metrics):
        metrics = [with_previous(m, r, doc) for m, r in zip(metrics, raw)]
    headline, points = card_words(out, doc, fields, metrics)
    return {'ok': True, 'reader': used, 'seconds': secs, 'category': cat, 'fields': fields, 'metrics': metrics,
            'headline': headline, 'points': points}


def _sha(b) -> str:
    return hashlib.sha256(b if isinstance(b, bytes) else str(b).encode('utf-8')).hexdigest()


def finish(rec: dict) -> dict:
    """JSON columns and counts for the archive."""
    rec = dict(rec)
    rec['shown'] = sum(f['shown'] for f in rec.get('fields') or []) + sum(m['shown'] for m in rec.get('metrics') or [])
    rec['held'] = sum(not f['shown'] for f in rec.get('fields') or []) + \
        sum(not m['shown'] for m in rec.get('metrics') or [])
    for k in ('fields', 'metrics', 'second_fields', 'agreed', 'points'):
        rec[k] = json.dumps(rec.get(k) or ([] if k != 'agreed' else {}), ensure_ascii=False, default=str)
    rec['headline'] = json.dumps(rec['headline'], ensure_ascii=False, default=str) if rec.get('headline') else None
    return {c: rec.get(c) for c in COLUMNS}


def run(to_read: pd.DataFrame, lanes: dict[str, Lane], earlier: pd.DataFrame | None, budget_seconds: float,
        fetch=s.download, max_filings: int | None = None, now=time.monotonic, on_row=None,
        idle_wait: float = 1.0) -> tuple[list[dict], dict]:
    """Read the chosen filings, newest first, until the time budget is used; (rows, notes).

    Each lane is a worker taking the next filing, so the providers read different filings at once and a slow
    one holds up only its own. A filing a lane cannot read (busy, refused, too slow, too long for it) goes to a
    lane that has not tried it; it fails only when every lane has. When nothing is left to read, an idle lane
    reads again a filing another provider read this run: values both give alike are marked "2 readers agree".
    `on_row` gets each filing's row as soon as it is done, and again when a cross-check adds to it."""
    started, notes = now(), {'not_reached': 0, 'cross_checked': 0}
    lock = threading.Lock()
    rows, index = [], {}                    # rows in the order done; event_id -> position
    fresh = list(to_read.to_dict('records')) if to_read is not None else []
    taken = 0                               # fresh filings handed out
    retry = []                              # jobs a lane could not read: {'row', 'base', 'doc', 'tried', 'errors'}
    busy = set()                            # lanes reading now
    by_file, by_text, waiting, docs = {}, {}, {}, {}   # waiting: hash -> twins held until its read is done
    if earlier is not None and not earlier.empty:
        current = earlier['prompt_version'] == PROMPT_VERSION if 'prompt_version' in earlier else False
        for r in earlier[(earlier['status'] == 'read') & current].to_dict('records'):
            by_file.setdefault(r.get('file_sha256'), r)
            by_text.setdefault(r.get('text_sha256'), r)
    checked = set()                         # event_ids cross-checked, or being cross-checked
    alive = set(lanes)                      # lanes still taking work

    def add_row(rec: dict) -> None:
        with lock:
            if rec['event_id'] in index:
                rows[index[rec['event_id']]] = rec
            else:
                index[rec['event_id']] = len(rows)
                rows.append(rec)
        if on_row is not None:
            on_row(rec)

    def copy_of(twin: dict, base: dict) -> dict:
        status = 'same_file' if twin.get('file_sha256') == base['file_sha256'] else 'same_text'
        copied = {k: twin.get(k) for k in ('reader', 'reader_lane', 'category', 'fields', 'metrics', 'headline',
                                           'points', 'second_reader', 'second_category', 'second_fields', 'agreed')}
        return {c: {**base, **copied, 'status': status, 'same_as': twin['event_id'],
                    'shown': twin.get('shown'), 'held': twin.get('held')}.get(c) for c in COLUMNS}

    def take(lane: Lane):
        """('read', job) / ('fail', job) / ('check', rec) / ('wait', None) / ('stop', None), under the lock."""
        nonlocal taken
        if now() - started > budget_seconds or not lane.models():   # time up, or every model slow or at its limit
            alive.discard(lane.name)
            return 'stop', None
        for job in retry:
            if lane.name not in job['tried']:
                retry.remove(job)
                return 'read', job
        for job in retry:
            if not alive - job['tried']:    # the lanes that had not tried it have stopped
                retry.remove(job)
                return 'fail', job
        if fresh and (max_filings is None or taken < max_filings):
            taken += 1
            return 'read', {'row': fresh.pop(0), 'tried': set(), 'errors': []}
        for rec in rows:
            if (rec['status'] == 'read' and rec['event_id'] in docs and rec['event_id'] not in checked
                    and not rec.get('second_reader') and str(rec.get('reader')).split(':', 1)[0] not in lane.providers()):
                checked.add(rec['event_id'])
                return 'check', rec
        if retry or (busy - {lane.name}):
            return 'wait', None             # another lane may yet hand back a filing this one can take
        alive.discard(lane.name)
        return 'stop', None

    def prepare(job: dict):
        """Download and text of a fresh filing; a row when it needs no reading (failed, copied, no text)."""
        row = job['row']
        base = {**row, 'tries': int(row.get('tries') or 0) + 1, 'prompt_version': PROMPT_VERSION,
                'read_at': datetime.now(timezone.utc).isoformat()}
        log('---', row['exchange'], row.get('symbol'), row.get('subject'))
        try:
            content_url = row.get('content_url') or row['file_url']
            data = fetch(content_url)
            doc, doc_notes = s.text_of(data)
            # If the linked structured attachment is invalid/incomplete, fall back to the original PDF.
            if content_url != row['file_url'] and not any(str(note).lower().startswith('xbrl:') for note in doc_notes):
                xbrl_error = '; '.join(doc_notes)[:180]
                fallback_data = fetch(row['file_url'])
                fallback_doc, fallback_notes = s.text_of(fallback_data)
                if fallback_doc.strip():
                    data, doc, doc_notes = fallback_data, fallback_doc, [f'XBRL fallback to original attachment ({xbrl_error})', *fallback_notes]
                    content_url = row['file_url']
        except Exception as exc:  # noqa: BLE001 -- one filing failing never stops the run
            reason = f'download: {type(exc).__name__}: {exc}'[:300]
            # A missing document is not a transient model/network failure. Retire it now rather than
            # spending three historical batches rediscovering the same dead BSE/NSE PDF URL.
            if re.search(r'HTTP\s*(?:404|410)\b', str(exc), re.IGNORECASE):
                base['tries'] = MAX_TRIES
                reason = f'{reason} (permanent missing document; no retry)'
            return finish({**base, 'status': 'failed', 'reason': reason})
        source_format = ('xbrl' if any(str(note).lower().startswith('xbrl:') for note in doc_notes)
                         else 'zip' if data[:2] == b'PK' else 'pdf')
        base.update(content_url=content_url, file_sha256=_sha(data), text_sha256=_sha(re.sub(r'\s+', ' ', doc).strip()),
                    text_chars=len(doc), source_format=source_format)
        if not doc.strip():
            return finish({**base, 'status': 'no_text', 'reason': '; '.join(doc_notes)})
        with lock:
            twin = by_file.get(base['file_sha256']) or by_text.get(base['text_sha256'])
            if twin is None:
                for h in (base['file_sha256'], base['text_sha256']):
                    if h in waiting:        # the same file is being read right now: wait for that read
                        waiting[h].append(base)
                        return 'held'
                waiting[base['file_sha256']] = []
                waiting.setdefault(base['text_sha256'], [])
        if twin is not None:
            return copy_of(twin, base)
        job.update(base=base, doc=doc)
        return None

    def done_reading(job: dict, rec: dict | None) -> list:
        """Registers a finished read; the twins that waited for it, now to be copied (or failed with it)."""
        base = job['base']
        with lock:
            if rec is not None and rec['status'] == 'read':
                by_file.setdefault(base['file_sha256'], rec)
                by_text.setdefault(base['text_sha256'], rec)
            return waiting.pop(base['file_sha256'], []) + waiting.pop(base['text_sha256'], [])

    def worker(lane: Lane):
        while True:
            with lock:
                what, item = take(lane)
                if what in ('read', 'check'):
                    busy.add(lane.name)
            if what == 'stop':
                return
            if what == 'wait':
                time.sleep(idle_wait)
                continue
            try:
                if what == 'check':
                    cross_check(lane, item)
                elif what == 'fail':
                    fail_job(item)
                else:
                    read_job(lane, item)
            except Exception as exc:  # noqa: BLE001 -- a bug on one filing never stops the lane
                log(f'{lane.name}: {type(exc).__name__}: {exc}')
                if what == 'read':
                    add_row(finish({**item.get('base', {**item['row'], 'tries': int(item['row'].get('tries') or 0) + 1}),
                                    'status': 'failed', 'reason': f'reader error: {type(exc).__name__}: {exc}'[:300]}))
            finally:
                with lock:
                    busy.discard(lane.name)

    def fail_job(job: dict):
        reason = '; '.join(job['errors'])[:500]
        # A quota response is not a filing failure. Keep it visible but retryable and do not
        # spend MAX_TRIES: the next scheduled cycle may have another provider/model available.
        quota_deferred = is_rate_limit_error(reason) or 'at its daily limit' in reason.lower() or 'no model available' in reason.lower()
        base = dict(job['base'])
        if quota_deferred:
            base['tries'] = max(0, int(base.get('tries') or 1) - 1)
        status = 'quota_deferred' if quota_deferred else 'failed'
        rec = finish({**base, 'status': status, 'reason': reason})
        for twin in done_reading(job, None):
            add_row(finish({**twin, 'status': status,
                            'tries': max(0, int(twin.get('tries') or 1) - 1) if quota_deferred else twin.get('tries'),
                            'reason': f"its twin {job['row']['event_id']} {status.replace('_', ' ')}"}))
        add_row(rec)

    def read_job(lane: Lane, job: dict):
        if 'base' not in job:
            out = prepare(job)
            if out == 'held':
                return
            if out is not None:
                add_row(out)
                return
        res = read_one(lane, job['row'], job['doc'])
        if not res['ok']:
            job['tried'].add(lane.name)
            job['errors'].append(res['error'])
            with lock:
                if alive - job['tried']:
                    retry.insert(0, job)
                    return
            fail_job(job)
            return
        rec = finish({**job['base'], 'status': 'read', 'reader': res['reader'], 'reader_lane': lane.name,
                      'category': res['category'], 'fields': res['fields'], 'metrics': res['metrics'],
                      'headline': res['headline'], 'points': res['points'], 'seconds': res['seconds']})
        with lock:
            docs[rec['event_id']] = (job['row'], job['doc'], res['fields'], res['metrics'])
        add_row(rec)
        for twin in done_reading(job, rec):
            add_row(copy_of(rec, twin))
        log(job['row'].get('symbol'), 'read', res['reader'], f"shown {rec.get('shown')}, held {rec.get('held')}")

    def cross_check(lane: Lane, rec: dict):
        row, doc, fields, metrics = docs[rec['event_id']]
        res = read_one(lane, row, doc)
        if not res['ok']:
            return                          # a missing cross-check is not an error; the values stand as read
        agreed = {**agreement(fields, res['fields']), **metric_agreement(metrics, res['metrics'])}
        with lock:
            notes['cross_checked'] += 1
        add_row({**rec, 'second_reader': res['reader'], 'second_category': res['category'],
                 'second_fields': json.dumps(res['fields'], ensure_ascii=False, default=str),
                 'agreed': json.dumps(agreed, ensure_ascii=False, default=str)})
        log(row.get('symbol'), 'cross-checked by', res['reader'], f"{sum(v is True for v in agreed.values())} agree")

    threads = [threading.Thread(target=worker, args=(lane,), name=f'lane-{n}', daemon=True)
               for n, lane in lanes.items()]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    notes['not_reached'] = len(fresh) + len(retry) + sum(len(v) for v in waiting.values())
    return rows, notes


# --- R2 ---------------------------------------------------------------------------------

def months_back(today: date) -> list[str]:
    first = today.replace(day=1)
    prev = (first - timedelta(days=1)).replace(day=1)
    return [f'year={d.year}/month={d.month:02d}' for d in (prev, first)]


def load_archive(r2, prefix: str, today: date) -> pd.DataFrame | None:
    from clean_writer import read_parquet
    frames = [f for f in (read_parquet(r2, f'{prefix}{m}.parquet') for m in months_back(today))
              if f is not None and not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else None


def with_company_memory(r2, candidates: pd.DataFrame) -> pd.DataFrame:
    """Attach concise, source-linked prior company events to prompts when a memory exists in R2."""
    from clean_writer import get
    if candidates is None or candidates.empty:
        return candidates
    out = candidates.copy()
    cache, contexts = {}, []
    for row in out.to_dict('records'):
        isin = str(row.get('isin') or '').strip()
        memory = {}
        if isin and isin.lower() != 'nan' and re.fullmatch(r'[A-Za-z0-9._-]{2,32}', isin):
            if isin not in cache:
                raw = get(r2, f'archive/company_memory/{isin}.json')
                try:
                    cache[isin] = json.loads(raw) if raw else {}
                except (TypeError, ValueError):
                    cache[isin] = {}
            memory = cache[isin]
        current_date = str(row.get('broadcast_date') or '')
        lines = []
        for event in [e for e in memory.get('events', []) if e.get('date') and e.get('date') < current_date][-8:]:
            headline = event.get('headline') if isinstance(event.get('headline'), dict) else {}
            summary = headline.get('text') or '; '.join(p.get('text', '') for p in event.get('points', [])[:2] if p.get('text'))
            if summary:
                lines.append(f"- {event.get('date')} [{event.get('event_id')}] {summary} (source: {event.get('source_url')})")
        contexts.append('\\n'.join(lines))
    out['_company_memory'] = contexts
    return out


def write(r2, rows: list[dict], run_date: str, today: date) -> int:
    """Rows merged into the reads archive by event_id (a filing read again replaces its row), then the clean
    table rebuilt from it. Returns the number of filings new to the archive."""
    from clean_writer import put_parquet, read_parquet
    new = pd.DataFrame(rows, columns=list(COLUMNS))
    added = 0
    if not new.empty:
        new = new.drop_duplicates('event_id', keep='last')
        part = pd.to_datetime(new['broadcast_date'], errors='coerce')
        for key, g in new.groupby(part.dt.strftime('year=%Y/month=%m').fillna('month=unknown')):
            k = f'{READS_PREFIX}{key}.parquet'
            old = read_parquet(r2, k)
            if old is not None and not old.empty:
                added += int((~g['event_id'].isin(old['event_id'])).sum())
                cols = list(dict.fromkeys([*old.columns, *g.columns]))   # empty columns left out of the concat
                parts = [p.dropna(axis=1, how='all') for p in (old[~old['event_id'].isin(g['event_id'])], g)]
                g = pd.concat(parts, ignore_index=True).reindex(columns=cols)
            else:
                added += len(g)
            for c in ('tries', 'text_chars', 'seconds', 'shown', 'held'):
                g[c] = pd.to_numeric(g[c], errors='coerce')
            put_parquet(r2, k, g.reset_index(drop=True))
    arch = load_archive(r2, READS_PREFIX, today)
    if arch is not None:
        recent = arch[pd.to_datetime(arch['broadcast_date'], errors='coerce')
                      >= pd.Timestamp(today - timedelta(days=READ_DAYS))]
        put_parquet(r2, CLEAN_KEY, recent.reset_index(drop=True))
    return added


class Saver:
    """Rows written to R2 as the run reads them (at most one write every `every` seconds), so a filing reaches
    the site minutes after it is read and a run cut short keeps what it has read. A write that fails keeps its
    rows for the next one; only the last write, at the end of the run, raises."""

    def __init__(self, r2, run_date: str, today: date, every: float = 15.0, now=time.monotonic, writer=None):
        self.r2, self.run_date, self.today, self.every, self.now = r2, run_date, today, every, now
        self.writer = writer or write
        self.pending: list[dict] = []
        self.added, self.writes, self.last = 0, 0, None
        self.lock = threading.RLock()        # the lanes add from their own threads

    def add(self, rec: dict) -> None:
        with self.lock:
            self.pending.append(rec)
            if self.last is None or self.now() - self.last >= self.every:
                self.flush()

    def flush(self, final: bool = False) -> None:
        with self.lock:
            self._flush(final)

    def _flush(self, final: bool) -> None:
        if not self.pending:
            return
        try:
            self.added += self.writer(self.r2, self.pending, self.run_date, self.today)
        except Exception as exc:  # noqa: BLE001 -- kept for the next write
            if final:
                raise
            log('save failed, kept for the next write:', type(exc).__name__, exc)
            return
        finally:
            self.last = self.now()
        self.writes += 1
        log(f'saved {len(self.pending)} filings to R2')
        self.pending = []


def usage(clients: dict, lanes: dict[str, Lane], since: dict[str, int] | None = None) -> dict:
    """Per-model calls since each client's attempt offset; default is the full process run."""
    out = {}
    since = since or {}
    for prov, c in clients.items():
        # Historical batches share client instances. Persist only this batch's delta, not
        # the cumulative process history, or the daily quota ledger counts old calls again.
        for model, status, secs in c.attempts[since.get(prov, 0):]:
            e = out.setdefault(f'{prov}:{model}', {'calls': 0, 'by_status': {}, 'seconds': []})
            e['calls'] += 1
            e['by_status'][str(status)] = e['by_status'].get(str(status), 0) + 1
            if status == 200:
                e['seconds'].append(secs)
    for e in out.values():
        secs = sorted(e.pop('seconds'))
        e['median_seconds_ok'] = secs[len(secs) // 2] if secs else None
    return {'models': out,
            'left_out_as_slow': {n: [e for e in lane.dropped if e not in lane.rate_limited]
                                 for n, lane in lanes.items() if any(e not in lane.rate_limited for e in lane.dropped)},
            'left_out_as_rate_limited': {n: lane.rate_limited for n, lane in lanes.items() if lane.rate_limited}}


def used_today(r2, run_date: str) -> dict:
    """Calls by provider:model in today's earlier runs, from the usage log (the daily limits count them)."""
    from clean_writer import get
    body = get(r2, f'clean/reports/announcement_reader/{run_date}.json')
    out = {}
    for run_ in (json.loads(body).get('runs', []) if body else []):
        for m, e in ((run_.get('usage') or {}).get('models') or {}).items():
            out[m] = out.get(m, 0) + int(e.get('calls') or 0)
    return out


def append_usage(r2, run_date: str, entry: dict):
    from clean_writer import get, put
    key = f'clean/reports/announcement_reader/{run_date}.json'
    body = get(r2, key)
    day = json.loads(body) if body else {'date': run_date, 'runs': []}
    day['runs'].append(entry)
    put(r2, key, json.dumps(day, indent=1, default=str).encode(), 'application/json')


def summary_markdown(counts: dict, rows: list[dict], notes: dict, use: dict, setup: list[str]) -> str:
    st = pd.Series([r['status'] for r in rows]).value_counts().to_dict() if rows else {}
    lines = ['### Announcement reader', '',
             f"Candidates today and yesterday: {counts.get('candidates', 0)}; routine or no file "
             f"{counts.get('routine_or_no_file', 0)}; done before {counts.get('already_done', 0)}; below Rs 100 Cr "
             f"{counts.get('below_100_cr', 0)}; same filing on the other exchange "
             f"{counts.get('same_filing_other_exchange', 0)}; chosen {counts.get('to_read', 0)}, "
             f"not reached this run {notes.get('not_reached', 0)}; cross-checked by a second provider "
             f"{notes.get('cross_checked', 0)}.", '',
             '| Outcome | Filings |', '|---|---|'] + [f'| {k} | {v} |' for k, v in st.items()]
    lines += ['', '| Model | Calls | Answers | Median seconds |', '|---|---|---|---|']
    lines += [f"| {m} | {e['calls']} | {', '.join(f'{k}: {v}' for k, v in e['by_status'].items())} | "
              f"{e['median_seconds_ok']} |" for m, e in use.get('models', {}).items()]
    read = [r for r in rows if r['status'] == 'read']
    if read:
        lines += ['', '| Filing | Category | Reader | Seconds | Shown | Held back | Cross-check |',
                  '|---|---|---|---|---|---|---|']
        lines += [f"| {r['exchange']} {r.get('symbol')} | {r.get('category')} | {r.get('reader')} | {r.get('seconds')} | "
                  f"{r.get('shown')} | {r.get('held')} | {r.get('second_reader') or ''} |" for r in read]
    lines += [f'- note: {n}' for n in setup]
    return '\n'.join(lines) + '\n'


def collect(r2, today: date, dry_run: bool, notes: list):
    """Today's filings of both exchanges. Live: into raw and the archive, then read back from it."""
    from collectors.bse import announcements as bann
    from collectors.bse.client import BSEClient
    from collectors.nse_events import announcements as nann
    from collectors.nse_events.client import Blocked, NSEClient
    yesterday = today - timedelta(days=1)
    if dry_run:
        nse = NSEClient()
        frames = []
        nse_blocked = False
        for market in nann.FEEDS:
            try:
                frames.append(nann.parse(nse.announcements(yesterday, today, market), market))
            except Blocked as exc:
                notes.append(f'NSE {market}: {type(exc).__name__}: {exc}; stopped further NSE requests'[:200])
                nse_blocked = True
                break
            except Exception as exc:  # noqa: BLE001
                notes.append(f'NSE {market}: {type(exc).__name__}: {exc}'[:200])
        # Exercise the dedicated NSE XBRL-announcements feed in dry-runs as well as production.
        # Its client timeout is bounded to 10 seconds/one attempt; failures never block PDF reads.
        # Respect NSE's hard-stop rule on 401/403/429; never probe another endpoint after a block.
        if not nse_blocked:
            for market in nann.FEEDS:
                try:
                    frames.append(nann.parse_xbrl(nse.xbrl_announcements(yesterday, today, market), market))
                except Blocked as exc:
                    notes.append(f'NSE XBRL {market}: {type(exc).__name__}: {exc}; stopped further NSE requests'[:200])
                    break
                except Exception as exc:  # noqa: BLE001
                    notes.append(f'NSE XBRL {market}: {type(exc).__name__}: {exc}'[:200])
        bse, bframes = BSEClient(), []
        try:
            for day in (today, yesterday):
                bframes.append(bann.parse(bann.fetch_day(bse, day)[0]))
        except Exception as exc:  # noqa: BLE001
            notes.append(f'BSE: {type(exc).__name__}: {exc}'[:200])
        finally:
            bse.close()
        return (pd.concat(frames, ignore_index=True) if frames else None),             (pd.concat(bframes, ignore_index=True) if bframes else None)
    from insiders_clean.raw_store import RawStore
    from r2_writer import BUCKET
    try:
        nann.run(r2, NSEClient(), today, days=COLLECT_DAYS, raw=RawStore(r2, bucket=BUCKET, collector='nse_announcements'),
                 write_report=False)
    except Exception as exc:  # noqa: BLE001 -- the archive may still hold earlier filings
        notes.append(f'NSE collect: {type(exc).__name__}: {exc}'[:200])
    bse = BSEClient(raw=RawStore(r2, collector='bse_announcements'))
    try:
        bse_report = bann.run(r2, bse, today, days=COLLECT_DAYS, write_report=False, incremental=True)   # stops at known pages
        # run() records per-day Blocked/Failed/short-page problems in its report rather than raising;
        # surface those warnings in the live run summary instead of silently using a partial archive.
        for warning in bse_report.get('notes', []):
            notes.append(f'BSE collect: {warning}'[:200])
        if not bse_report.get('days') and not bse_report.get('notes'):
            notes.append('BSE collect: no day was successfully collected')
    except Exception as exc:  # noqa: BLE001
        notes.append(f'BSE collect: {type(exc).__name__}: {exc}'[:200])
    finally:
        bse.close()
    return load_archive(r2, nann.PREFIX, today), load_archive(r2, bann.PREFIX, today)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--dry-run', action='store_true', help='fetch today\'s lists, read, print; write nothing')
    ap.add_argument('--max', type=int, default=None, help='read at most this many filings')
    ap.add_argument('--minutes', type=float, default=float(os.environ.get('READER_MINUTES', '22')),
                    help='stop taking new filings after this long')
    args = ap.parse_args(argv)
    today = datetime.now(IST).date()
    setup = []
    lane_spec = lanes_of(LANES_FILE.read_text(encoding='utf-8'))
    entries = [e for es in lane_spec.values() for e in es]
    clients, notes = clients_for(entries)
    setup += notes
    lanes = {n: Lane(n, [e for e in usable(es) if e.split(':', 1)[0] in clients], clients)
             for n, es in lane_spec.items()}
    lanes = {n: lane for n, lane in lanes.items() if lane.entries}
    if not lanes:
        # Still collect and archive filings when keys are missing or every configured model is
        # temporarily unavailable. No model calls will occur; eligible filings remain pending for
        # the next cycle instead of making the collector exit before saving today's source data.
        setup.append('No AI lane has a configured key/model; source collection continues and AI reads remain pending.')
        log(setup[-1])
    r2 = None
    try:
        from r2_writer import r2_client
        r2 = r2_client()
    except Exception as exc:  # noqa: BLE001
        if not args.dry_run:
            raise
        setup.append(f'no R2 ({type(exc).__name__}); reads before this run not known')
    master = None
    if r2 is not None:
        from collectors.nse_events.run_daily import security_master
        try:
            cap_as_of = today - timedelta(days=1)  # last available exchange snapshot on or before yesterday
            master = security_master(r2, cap_as_of.isoformat(), setup)
            log(f'market-cap eligibility snapshot requested as of {cap_as_of.isoformat()} or earlier; '
                f'actual snapshot={getattr(master, "market_cap_as_of", None) or "unavailable"}')
        except Exception as exc:  # noqa: BLE001
            setup.append(f'no security master ({type(exc).__name__}); market cap and BSE-NSE links unknown')
    if r2 is not None:
        used = used_today(r2, today.isoformat())
        for lane in lanes.values():
            lane.used_today = used
        configure_rate_limit_circuit_breaker(lanes, r2, today.isoformat())
    nse, bse = collect(r2, today, args.dry_run, setup)
    done = load_archive(r2, READS_PREFIX, today) if r2 is not None else None
    current_candidates = candidates(nse, bse, master)
    to_read, status_rows, counts = choose(current_candidates, done, today)

    # Live-first: read and persist eligible current filings before spending any model capacity
    # on company-history enrichment. Historical work is gated again after the live results are saved.
    if r2 is not None:
        to_read = with_company_memory(r2, to_read)
    saver = None if args.dry_run else Saver(r2, today.isoformat(), today)
    rows, notes_run = run(to_read, lanes, done, args.minutes * 60, max_filings=args.max,
                          on_row=saver.add if saver else None)
    status = [finish({**r, 'prompt_version': PROMPT_VERSION, 'read_at': datetime.now(timezone.utc).isoformat()})
              for r in status_rows.to_dict('records')]
    rows += status
    use = usage(clients, lanes)
    text = summary_markdown(counts, rows, notes_run, use, setup)
    print(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as f:
            f.write(text)
    if args.dry_run:
        Path('announcement_reader_dry_run.json').write_text(json.dumps(rows, indent=1, ensure_ascii=False, default=str),
                                                            encoding='utf-8')
        xbrl_report = xbrl_audit(current_candidates)
        Path('announcement_reader_xbrl_audit.json').write_text(
            json.dumps(xbrl_report, indent=2, ensure_ascii=False, default=str), encoding='utf-8')
        log('XBRL audit', json.dumps({k: xbrl_report[k] for k in ('candidates', 'has_xbrl_flagged', 'direct_xbrl_urls', 'xbrl_attachments', 'xbrl_linked')}))
        return 0
    saver.pending += status
    saver.flush(final=True)
    # Update memory from live reads first. Only after the live results are durable may the
    # same serialized workflow spend any remaining capacity on targeted historical company history.
    from announcement_backfill import upsert_company_memories, unified_company_history_stage
    memories_written = upsert_company_memories(r2, rows)
    log(f'updated persistent company memory for {memories_written} companies')

    done_after_live = load_archive(r2, READS_PREFIX, today)
    live_remaining, _, live_counts = choose(current_candidates, done_after_live, today)
    if live_remaining.empty:
        current_isins = set()
        if not current_candidates.empty and 'isin' in current_candidates:
            dates = current_candidates.get('broadcast_date', pd.Series(index=current_candidates.index, dtype=str)).astype(str)
            groups = current_candidates.get('group', pd.Series(index=current_candidates.index, dtype=str)).astype(str)
            urls = current_candidates.get('file_url', pd.Series(index=current_candidates.index, dtype=str)).fillna('').astype(str)
            caps = pd.to_numeric(current_candidates.get('market_cap', pd.Series(index=current_candidates.index, dtype=float)),
                                  errors='coerce').fillna(0)
            eligible_today = current_candidates[
                (dates == today.isoformat()) & (groups != 'routine') & (urls != '') & (caps >= MIN_MCAP)
            ]
            current_isins.update(eligible_today['isin'].dropna().astype(str))
        try:
            history_result = unified_company_history_stage(
                r2, current_isins, today, master, lanes, clients, setup,
                batch_size=8, batch_minutes=2.0,
            )
            log('unified company-history stage (live queue clear)', json.dumps(history_result, default=str))
        except Exception as exc:  # noqa: BLE001 -- history must never suppress current-day cards
            message = f'unified company-history stage failed: {type(exc).__name__}: {exc}'[:500]
            setup.append(message)
            log(message)
    else:
        log(f'Deferring company-history AI work: {len(live_remaining)} eligible live filings remain; '
            f'live queue counts={json.dumps(live_counts, default=str)}')

    added = saver.added
    append_usage(r2, today.isoformat(), {'at': datetime.now(timezone.utc).isoformat(), 'counts': counts,
                                         'outcomes': pd.Series([r['status'] for r in rows]).value_counts().to_dict()
                                         if rows else {}, 'added': added, 'usage': usage(clients, lanes), 'notes': setup})
    return 0


if __name__ == '__main__':
    sys.exit(main())
