"""Sample check of the announcement reader: 12 real NSE filings, model output vs what the PDF says.

    GEMINI_API_KEY=... python scripts/announcement_sample.py [--only SYMBOL]

The filings and the values read from each PDF by hand are in
scripts/announcement_sample_expected.json. For each filing:

1. sort: the sorting model sees only NSE's subject and one-line text (what
   the nightly feed carries) and names a category and whether the PDF is
   worth reading;
2. read: the reading model gets the text of the attachment (PDFs extracted
   with pdftotext; a ZIP is opened and its PDFs read in order) and returns a
   category and fields, each field with a verbatim quote;
3. check: a quote counts only if it is found in the extracted text, and a
   price or share count only if its digits are in the quote; then each
   value is compared with the hand-read one.

Prints a markdown report (also to $GITHUB_STEP_SUMMARY) and writes
announcement_sample_results.json. Nothing is written to R2. Without a key it
says so and exits 0. Filings are public; nothing personal goes in a prompt.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import unicodedata
import signal
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import time
import zipfile
from datetime import datetime
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
API = 'https://generativelanguage.googleapis.com/v1beta'
PROMPT_VERSION = 'sample-1'
# Preferred model ids, first found in the account's model list wins.
READERS = ('gemini-3.5-flash-lite', 'gemini-3.1-flash-lite')
SORTERS = ('gemma-4-26b-a4b-it', 'gemma-4-31b-it')   # ids as listed by the API on 13 Oct 2026
PACE = {'read': 6.0, 'sort': 3.0, 'groq:read': 62.0, 'nvidia:read': 10.0, 'zai:read': 3.0}   # Groq: 8K tokens a minute   # seconds between calls: 15 and 30 requests a minute allow 4 and 2
PER_FILING_SECONDS = 600           # one filing never holds up the rest
CALL_SECONDS = 180                 # Flash-Lite took 55-110 s a filing on 13 Oct
RUN_SECONDS = int(os.environ.get('SAMPLE_MINUTES', '24')) * 60   # stop taking new filings before the job's limit
MAX_CHARS = 300_000                 # about 75K tokens, under Flash-Lite's 250K a minute
def log(*parts):
    """Progress on the run log, at once (a step that stalls must show where)."""
    print(time.strftime('%H:%M:%S'), *parts, flush=True)


UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

CATEGORIES = {
    'buyback_open_market': 'buyback of shares from the open market through the stock exchanges',
    'buyback_tender': 'buyback of shares by tender offer',
    'qip': 'qualified institutions placement of shares',
    'preferential': 'preferential issue of shares or warrants (approval or allotment)',
    'warrant_conversion': 'warrants converted into shares',
    'rights': 'rights issue of shares',
    'open_offer': 'open offer under the SAST takeover regulations',
    'debt_issue': 'debentures, bonds, commercial paper or other debt',
    'capex': 'investment in new or expanded capacity, a plant, or approval to run more capacity',
    'product_launch': 'a new product or product line launched',
    'order_win': 'orders or contracts received or won',
    'business_update': 'periodic operating or financial figures (monthly sales, quarterly update, order book, guidance)',
    'auditor_resignation': 'statutory auditor resigned',
    'rating_upgrade': 'credit rating raised',
    'rating_downgrade': 'credit rating lowered or put on watch negative',
    'rating_reaffirmed': 'credit rating kept unchanged',
    'deal_or_dispute': 'acquisition, sale, merger, litigation, arbitration or regulatory order',
    'routine': 'anything else (meetings, reminders, newspaper copies, compliance certificates)',
}
FIELDS = {
    'entity': 'whose event it is: "listed" (the filing company), "subsidiary" (any subsidiary or step-down '
              'subsidiary) or "parent_group" (a parent or group company)',
    'price_per_share': 'issue, offer or buyback price per share, as written (a fixed price only)',
    'max_price_per_share': 'maximum price per share ("not exceeding"), for open-market buybacks, as written',
    'shares': 'number of shares or warrants issued, allotted, converted, offered or bought back, as written',
    'amount': 'the total size or investment, the number exactly as written (e.g. 28,200.00 for "Rs 28,200.00 Lakhs")',
    'amount_unit': 'unit of that number: rupees, thousand, lakh, crore, million or billion',
    'currency': 'currency of the amount: INR, USD, CAD, EUR ...',
    'discount_pct': 'discount to the floor price, in percent',
    'allottee_is_promoter': 'true if the filing says the allottees or subscribers are promoters, false if it says not',
    'ratio': 'rights entitlement ratio as "new:held", e.g. "2:21"',
    'record_date': 'record date, YYYY-MM-DD',
    'offer_pct': 'open offer size as percent of share capital',
    'capacity_from': 'capacity before, with its unit, as written',
    'capacity_to': 'capacity after or of the new facility, with its unit, as written',
}
# Operating figures go in "metrics": [{"label", "period", "value", "unit", "quote"}] (business updates, orders).
UNIT = {'rupees': 1, 'rs': 1, 'units': 1, 'thousand': 1e3, 'lakh': 1e5, 'lakhs': 1e5, 'crore': 1e7, 'crores': 1e7,
        'cr': 1e7, 'million': 1e6, 'mn': 1e6, 'billion': 1e9, 'bn': 1e9}
NUMERIC = ('price_per_share', 'max_price_per_share', 'shares', 'amount', 'discount_pct', 'offer_pct', 'capacity_from',
           'capacity_to')   # 16 Oct: capacity_from was shown as 0 for "initial capacity of 5000": a number must be in its quote
DIGITS_IN_QUOTE = ('price_per_share', 'max_price_per_share', 'shares', 'amount', 'capacity_from', 'capacity_to')


def sort_prompt(row: dict) -> str:
    cats = '\n'.join(f'- {k}: {v}' for k, v in CATEGORIES.items())
    return (f'An Indian listed company filed this announcement with NSE.\nSubject: {row["subject"]}\n'
            f'Description: {row["text"]}\n\nCategories:\n{cats}\n\n'
            'Answer only with JSON: {"category": one of the category names, '
            '"read_pdf": true if the attached document should be read to get prices, sizes or names}. '
            'If the subject and description do not say enough, give your best category and read_pdf true.')


def read_prompt(row: dict, doc: str) -> str:
    cats = '\n'.join(f'- {k}: {v}' for k, v in CATEGORIES.items())
    fields = '\n'.join(f'- {k}: {v}' for k, v in FIELDS.items())
    return (f'Below is the text of an announcement filed with {row.get("exchange", "NSE")} by {row["symbol"]} '
            f'(subject: {row["subject"]}).\n'
            f'Categories:\n{cats}\n\nFields:\n{fields}\n\n'
            'Return only JSON: {"category": one category name, "fields": [{"name": field name, '
            '"value": number, true/false or text, "quote": the exact words from the document that state it}], '
            '"metrics": [{"label": what is measured, "period": e.g. "Sep 2026" or "H1 FY27", "value": the number '
            'as written, "unit": rupees/lakh/crore/million/units/percent, "quote": the exact words}]}.\n'
            'Rules: include a field or metric only if the document states it; never compute, convert or guess '
            '(give numbers exactly as written, with their unit); the quote must be copied character for '
            'character from the document, one sentence or table row at most; put the most important figures '
            'of a business update, order announcement or capex in metrics; leave things out rather than '
            'invent them.\n\n=== DOCUMENT ===\n' + doc)


# --- the model API -----------------------------------------------------------------

class Gemini:
    def __init__(self, key: str, session=None, sleep=time.sleep):
        self.s = session or requests.Session()
        self.s.headers['x-goog-api-key'] = key
        self.sleep = sleep
        self.last = {}
        self.attempts = []   # (model, HTTP status or error name, seconds) for each generation request

    def models(self) -> list[dict]:
        out, token = [], None
        while True:
            r = self.s.get(f'{API}/models', params={'pageSize': 1000, **({'pageToken': token} if token else {})},
                           timeout=60)
            log('models list: HTTP', r.status_code)
            r.raise_for_status()
            j = r.json()
            out += j.get('models', [])
            token = j.get('nextPageToken')
            if not token:
                return out

    def generate(self, models: list[str], prompt: str, kind: str, json_mode: bool) -> tuple[str, dict, str]:
        """(text, usage, model that answered); record every actual generation request."""
        body = {'contents': [{'role': 'user', 'parts': [{'text': prompt}]}],
                'generationConfig': {'temperature': 0, **({'responseMimeType': 'application/json'} if json_mode else {})}}
        last = ''
        for round_ in range(2):
            if round_:
                self.sleep(45)
            for model in models:
                wait = PACE[kind] - (time.monotonic() - self.last.get(kind, -1e9))
                if wait > 0:
                    self.sleep(wait)
                self.last[kind] = time.monotonic()
                try:
                    r = self.s.post(f'{API}/models/{model}:generateContent', json=body, timeout=CALL_SECONDS)
                except requests.RequestException as exc:
                    self.attempts.append((model, type(exc).__name__, round(time.monotonic() - self.last[kind], 1)))
                    log(f'{kind} {model}: {type(exc).__name__}')
                    last = f'{model}: {type(exc).__name__}'
                    continue
                self.attempts.append((model, r.status_code, round(time.monotonic() - self.last[kind], 1)))
                log(f'{kind} {model}: HTTP {r.status_code}', '' if r.status_code == 200 else r.text[:200])
                if r.status_code == 429:
                    # A hard quota/rate-limit response is a stop signal, not a retry hint.
                    raise RuntimeError(f'{model}: HTTP 429: {r.text[:300]}')
                if r.status_code in (500, 503):
                    last = f'{model}: HTTP {r.status_code}'
                    continue
                if r.status_code != 200:
                    raise RuntimeError(f'{model}: HTTP {r.status_code}: {r.text[:300]}')
                j = r.json()
                parts = (j.get('candidates') or [{}])[0].get('content', {}).get('parts', [])
                text = ''.join(p.get('text', '') for p in parts if not p.get('thought'))
                return text, j.get('usageMetadata', {}), model
        raise RuntimeError(f'all {kind} models busy or refused ({last})')


class OpenAICompat:
    """Groq and NVIDIA's free endpoints (the OpenAI chat-completions form), with Gemini's interface:
    models() for the live list, generate() trying the given models in order."""

    def __init__(self, name: str, base: str, key: str, session=None, sleep=time.sleep):
        self.name, self.base, self.sleep = name, base, sleep
        self.s = session or requests.Session()
        self.s.headers['Authorization'] = f'Bearer {key}'
        self.last = {}
        self.call_seconds = CALL_SECONDS_OF.get(name, CALL_SECONDS)
        self.attempts = []   # (model, HTTP status or error name, seconds) for every call: the reader's usage log

    def models(self) -> list[dict] | None:
        """The live model list; None when the provider has no list (models are then tried, not checked)."""
        r = self.s.get(f'{self.base}/models', timeout=60)
        log(f'{self.name} models list ({self.base}): HTTP', r.status_code)
        if r.status_code == 401:
            raise RuntimeError(f'{self.name}: key refused (HTTP 401) - expired or wrong; renew the GitHub secret')
        if r.status_code == 404:
            return None
        r.raise_for_status()
        log(f'{self.name} models:', ', '.join(sorted(m['id'] for m in r.json().get('data', []))))
        return [{'name': m['id'], 'supportedGenerationMethods': ['generateContent']} for m in r.json().get('data', [])]

    def generate(self, models: list[str], prompt: str, kind: str, json_mode: bool) -> tuple[str, dict, str]:
        last = ''
        for round_ in range(2):
            if round_:
                self.sleep(45)
            for model in models:
                wait = PACE.get(f'{self.name}:{kind}', PACE[kind]) - (time.monotonic() - self.last.get(kind, -1e9))
                if wait > 0:
                    self.sleep(wait)
                model_id, thinking = model.removesuffix('+thinking'), model.endswith('+thinking')
                body = {'model': model_id, 'temperature': 0, 'max_tokens': MODEL_LIMITS.get(model_id, (0, MAX_TOKENS.get(self.name, 4096)))[1],
                        'messages': [{'role': 'user', 'content': prompt}],
                        **({'response_format': {'type': 'json_object'}} if json_mode else {}),
                        # Z.ai's switch for its reasoning step; "model+thinking" in the readers line turns it on
                        **({'thinking': {'type': 'enabled' if thinking else 'disabled'}} if self.name == 'zai' else {})}
                self.last[kind] = t0 = time.monotonic()
                try:
                    r = self.s.post(f'{self.base}/chat/completions', json=body, timeout=self.call_seconds)
                except requests.RequestException as exc:
                    self.attempts.append((model, type(exc).__name__, round(time.monotonic() - t0, 1)))
                    log(f'{kind} {self.name}:{model}: {type(exc).__name__}')
                    last = f'{model}: {type(exc).__name__}'
                    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
                        # no second round for a model that did not answer: the reader rests it and moves on
                        raise RuntimeError(f'all {self.name} {kind} models busy or refused ({last})') from exc
                    continue
                self.attempts.append((model, r.status_code, round(time.monotonic() - t0, 1)))
                if r.status_code == 400 and json_mode and 'response_format' in r.text:
                    body.pop('response_format')   # a model without JSON mode: the prompt asks for JSON anyway
                    t_retry = time.monotonic()
                    try:
                        r = self.s.post(f'{self.base}/chat/completions', json=body, timeout=self.call_seconds)
                    except requests.RequestException as exc:
                        self.attempts.append((model, type(exc).__name__, round(time.monotonic() - t_retry, 1)))
                        log(f'{kind} {self.name}:{model}: retry {type(exc).__name__}')
                        last = f'{model}: {type(exc).__name__}'
                        continue
                    self.attempts.append((model, r.status_code, round(time.monotonic() - t_retry, 1)))
                log(f'{kind} {self.name}:{model}: HTTP {r.status_code}', '' if r.status_code == 200 else r.text[:200])
                if r.status_code == 429:
                    # Do not retry after the provider explicitly reports a rate limit/quota response.
                    raise RuntimeError(f'{self.name}:{model}: HTTP 429: {r.text[:300]}')
                if r.status_code in (500, 502, 503, 504):
                    last = f'{model}: HTTP {r.status_code}'
                    continue
                if r.status_code != 200:
                    raise RuntimeError(f'{self.name}:{model}: HTTP {r.status_code}: {r.text[:300]}')
                j = r.json()
                msg = (j.get('choices') or [{}])[0].get('message') or {}
                text = msg.get('content') or ''
                if not text.strip():   # some reasoning models (DeepSeek v4.1 Flash) leave the answer in their notes
                    text = msg.get('reasoning_content') or msg.get('reasoning') or ''
                    if text:
                        log(f'{kind} {self.name}:{model}: content empty, reply taken from reasoning_content')
                text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)   # reasoning models' notes
                u = j.get('usage') or {}
                return text, {'promptTokenCount': u.get('prompt_tokens')}, model
        raise RuntimeError(f'all {self.name} {kind} models busy or refused ({last})')


MAX_TOKENS = {'groq': 2048, 'nvidia': 16384, 'zai': 16384}   # Groq counts the reply in its 8K a minute; reasoning models need room
CALL_SECONDS_OF = {'nvidia': 90, 'zai': 120}   # 16 Oct: Z.ai answers in 20-35 s; a slower call is a model in trouble

PROVIDERS = {   # name: (base url, key secret, extra input limit in characters or None)
    'groq': ('https://api.groq.com/openai/v1', 'GROQ_API_KEY', 20_000),   # 8K tokens a minute on the free plan
    'nvidia': ('https://integrate.api.nvidia.com/v1', 'NVIDIA_API_KEY', None),
    'zai': ('https://api.z.ai/api/paas/v4', 'ZAI_API_KEY', None),   # free Flash models: one request at a time
}
# Z.ai: only the models its pricing page lists as Free (docs.z.ai pricing, 13 Oct 2026); its /models answer
# leaves them out (13 Oct: only paid GLM 4.5-5.3 listed), so these are tried as named and nothing else is.
FREE_ONLY = {'zai': ('glm-4.7-flash', 'glm-4.5-flash', 'glm-4.6v-flash')}
SERIAL = {'zai'}   # free tier: one request at a time (per model or per account: not known), so one job per model
OTHER_BASES = {'zai': ('https://open.bigmodel.cn/api/paas/v4', 'https://api.z.ai/v1')}   # bigmodel.cn keys work there
# Models with a small context: (characters of input at most, reply tokens). Palmyra Fin takes 32K tokens in all.
MODEL_LIMITS = {'writer/palmyra-fin-70b-32k': (75_000, 4096)}


def parse_readers(text: str) -> list[str]:
    """'readers:' line of the run file: gemini (3.5 then 3.1 Flash-Lite) or provider:model entries."""
    for ln in text.splitlines():
        if ln.strip().lower().startswith('readers:'):
            return [x.strip() for x in ln.split(':', 1)[1].split(',') if x.strip()]
    return ['gemini']


DEFAULT_READERS = ('gemini, groq:openai/gpt-oss-120b, groq:qwen/qwen3.8-27b, '
                   'nvidia:nvidia/nemotron-3-ultra-550b-a55b, nvidia:nvidia/nemotron-3-super-120b-a12b, '
                   'nvidia:nvidia/nemotron-3.5-lightning-30b-a3b, nvidia:deepseek-ai/deepseek-v4.1-flash, '
                   'nvidia:google/gemma-4-31b-it, nvidia:moonshotai/kimi-k3, nvidia:z-ai/glm-5.3')


def matrix(text: str) -> list[dict]:
    """One workflow job per reader (the run file's readers: line, else DEFAULT_READERS); only gemini sorts."""
    line = text if any(ln.strip().lower().startswith('readers:') for ln in text.splitlines()) \
        else 'readers: ' + DEFAULT_READERS
    jobs: dict[str, list[str]] = {}
    for r in parse_readers(line):   # one request at a time (Z.ai free): one job per model, its thinking variant in it
        jobs.setdefault(r.removesuffix('+thinking') if r.split(':')[0] in SERIAL else r, []).append(r)
    return [{'slug': re.sub(r'[^a-z0-9.]+', '-', '-'.join(rs).lower()).strip('-'), 'reader': ', '.join(rs),
             'flags': '' if 'gemini' in rs else '--no-sort'} for rs in jobs.values()]


def available_of(models: list[dict], wanted: tuple[str, ...]) -> list[str]:
    """The wanted model ids this key can call, in order of preference."""
    names = {m['name'].split('/', 1)[-1] for m in models
             if 'generateContent' in m.get('supportedGenerationMethods', [])}
    return [w for w in wanted if w in names]


def parse_json(text: str):
    """The model's JSON, also when wrapped in a ``` fence; None if unreadable."""
    t = text.strip()
    m = re.search(r'```(?:json)?\s*(.*?)```', t, re.DOTALL)
    t = m.group(1) if m else t
    start = min([i for i in (t.find('{'), t.find('[')) if i >= 0], default=-1)
    if start < 0:
        return None
    try:
        return json.loads(t[start:])
    except ValueError:
        try:
            return json.JSONDecoder().raw_decode(t[start:])[0]
        except ValueError:
            return None


# --- the document ------------------------------------------------------------------

def pdf_text(data: bytes) -> str:
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / 'f.pdf'
        src.write_bytes(data)
        # -layout keeps a table's row on one line with its headers above (SML Mahindra's sales table)
        out = subprocess.run(['pdftotext', '-layout', str(src), '-'], capture_output=True, timeout=180, check=False)
        return out.stdout.decode('utf-8', errors='replace')


def download(url: str, session=None) -> bytes:
    """The attachment's bytes, asked for with its own exchange as referer."""
    s = session or requests
    referer = 'https://www.bseindia.com/' if 'bseindia.com' in url else 'https://www.nseindia.com/'
    log('download', url.rsplit('/', 1)[-1])
    r = s.get(url, headers={'User-Agent': UA, 'Referer': referer}, timeout=(15, 120))
    log('download: HTTP', r.status_code, f'{len(r.content):,} bytes')
    if r.status_code == 404 and 'bseindia.com' in url and '/AttachLive/' in url:
        # BSE moves a filing's PDF to AttachHis after a while (15 Oct probe: filings from January to April and some
        # of 1 Oct answer 404 under AttachLive and the PDF under AttachHis; filings of the last 2 days only AttachLive).
        later = s.get(url.replace('/AttachLive/', '/AttachHis/'), headers={'User-Agent': UA, 'Referer': referer},
                      timeout=(15, 120))
        log('download: BSE AttachHis HTTP', later.status_code, f'{len(later.content):,} bytes')
        if later.ok:
            r = later
    r.raise_for_status()
    return r.content


def document(url: str, session=None) -> tuple[str, list[str]]:
    """(text, notes). A ZIP's PDFs are read in name order, each under a header line."""
    return text_of(download(url, session))


def xbrl_text(data: bytes) -> str:
    """Turn an XBRL instance into source-backed facts; return empty for non-XBRL or invalid XML."""
    try:
        root = ET.fromstring(data)
    except (ET.ParseError, ValueError, TypeError):
        return ''

    def local(tag):
        return str(tag).rsplit('}', 1)[-1].split(':')[-1]

    contexts, units = {}, {}
    for node in root.iter():
        kind = local(node.tag)
        if kind == 'context':
            ident = node.attrib.get('id')
            if ident:
                dates = [f'{local(child.tag)}={str(child.text or "").strip()}'
                         for child in node.iter() if local(child.tag) in ('startDate', 'endDate', 'instant')]
                if dates:
                    contexts[ident] = ', '.join(dates)
        elif kind == 'unit':
            ident = node.attrib.get('id')
            measures = [str(child.text or '').strip() for child in node.iter() if local(child.tag) == 'measure']
            if ident and measures:
                units[ident] = ' * '.join(measures)

    facts = []
    excluded = {'context', 'unit', 'schemaRef', 'roleRef', 'arcroleRef', 'footnote', 'period', 'entity'}
    for node in root.iter():
        context_ref = node.attrib.get('contextRef')
        if not context_ref or local(node.tag) in excluded:
            continue
        value = ' '.join(''.join(node.itertext()).split())
        if not value:
            continue
        context = contexts.get(context_ref, context_ref)
        unit_ref = node.attrib.get('unitRef')
        unit = units.get(unit_ref, unit_ref) if unit_ref else None
        line = f'{local(node.tag)} = {value} [context: {context}'
        if unit:
            line += f'; unit: {unit}'
        if node.attrib.get('decimals'):
            line += f'; decimals: {node.attrib["decimals"]}'
        facts.append(line + ']')
    if not facts:
        return ''
    return 'XBRL FACTS (exchange-provided structured data; use exact values and contexts):\n' + '\n'.join(facts)


def text_of(data: bytes, limit: int | None = MAX_CHARS) -> tuple[str, list[str]]:
    """Prefer usable XBRL facts in XML or ZIP attachments; fall back to PDF text when absent or invalid."""
    notes = [f'{len(data) / 1024 ** 2:.1f} MB']
    text = ''
    if data[:2] == b'PK':
        z = zipfile.ZipFile(io.BytesIO(data))
        names = z.namelist()
        for name in sorted(n for n in names if n.lower().endswith(('.xml', '.xbrl'))):
            structured = xbrl_text(z.read(name))
            if structured:
                text = structured
                notes.append(f'xbrl: {name}; {len(structured.splitlines()) - 1} structured facts; preferred over PDF')
                break
        if not text:
            pdfs = sorted(n for n in names if n.lower().endswith('.pdf'))
            notes.append(f'zip: {len(pdfs)} PDFs of {len(names)} entries')
            text = '\n'.join(f'=== file: {n} ===\n{pdf_text(z.read(n))}' for n in pdfs)
    else:
        text = xbrl_text(data) if data.lstrip().startswith(b'<') else ''
        if text:
            notes.append(f'xbrl: standalone XML; {len(text.splitlines()) - 1} structured facts')
        else:
            text = pdf_text(data)
    if not text.strip():
        notes.append('no text layer (scanned?)')
    if limit and len(text) > limit:
        notes.append(f'cut to {limit:,} of {len(text):,} characters')
        text = text[:limit]
    return text, notes


# --- checks ------------------------------------------------------------------------

def _norm(s: str) -> str:
    s = unicodedata.normalize('NFKC', str(s)).lower().translate(str.maketrans({'’': "'", '‘': "'", '“': '"', '”': '"',
                                                '–': '-', '—': '-', ' ': ' '}))
    return re.sub(r'\s+', '', s)


def _loose(s) -> str:
    """Lower-case letters and digits only, except that a comma or point between two digits stays."""
    s = re.sub(r'[^a-z0-9.,]', '', _norm(s))
    return re.sub(r'(?<!\d)[.,]|[.,](?!\d)', '', s)


NUMBER = r'\d[\d,]*(?:\.\d+)?'
_OCR = str.maketrans({'o': '0', 'q': '0', 'd': '0', 'l': '1', 'i': '1', 's': '5', 'b': '8', 'z': '2', 'c': 'e'})


def _ocr(text: str) -> str:
    """Letters a scan confuses with digits or each other, folded together (applied to both texts, so it only widens
    what counts as the same string by those look-alikes; the quote still has to be long)."""
    return str(text).translate(_OCR)
_LIGS = re.compile(r'ffi|ffl|ti|tt|ft|fi|fl|ff')


def _unlig(text: str) -> str:
    return _LIGS.sub('', text)
_TOKEN = re.compile(r'[a-z]+|\d+(?:[.,]\d+)*')


def _tokens(text) -> list[str]:
    return _TOKEN.findall(unicodedata.normalize('NFKC', str(text or '')).lower())


def _spread_run(quote, doc, slack: int = 3) -> bool:
    """Every token of the quote, in order, within a stretch of the document no longer than slack times the quote (plus 20
    tokens): the quote's words with other columns' words between them. Needs 6 or more tokens, so that two sentences
    cannot meet by chance; the card shows such a quote as a table row, not as in the filing."""
    q = _tokens(quote)
    if len(q) < 6:
        return False
    d = _tokens(doc)
    span = slack * len(q) + 20
    for i, t in enumerate(d):
        if t != q[0]:
            continue
        j, k = i + 1, 1
        while k < len(q) and j < len(d) and j - i <= span:
            if d[j] == q[k]:
                k += 1
            j += 1
        if k == len(q):
            return True
    return False


def _token_run(quote, doc) -> bool:
    """The quote's words and numbers as one unbroken run of the document's tokens (a "|" or spaces between cells
    do not matter; 110 is not 11070). Needs two tokens, one of them a number."""
    q = _tokens(quote)
    if len(q) < 2 or not any(t[0].isdigit() for t in q):
        return False
    d = _tokens(doc)
    n = len(q)
    return any(d[i:i + n] == q for i, t in enumerate(d) if t == q[0])


def quote_found(quote, doc: str) -> str | bool:
    """'exact': the quote is in the document, ignoring case and all whitespace (pdftotext breaks lines and
    columns). 'table': not word for word, but a number in it stands on a line of the document and every other
    word of the quote is within that line's table block (6 lines above, 2 below), as when a model joins a row
    to its column headings. False otherwise."""
    q = _norm(quote or '')
    if len(q) < 8:   # a short table row ("PAT 110") is found on whole tokens, so 110 is never found inside 11070
        return 'exact' if _token_run(quote, doc) else False
    flat_doc = _norm(doc)
    if q in flat_doc:
        return 'exact'
    # A quote the model joined with "..." (two or more passages of the document): every passage must be in it.
    parts = [x for x in re.split(r'\.{3,}|…', str(quote)) if len(_norm(x)) >= 8]
    if len(parts) >= 2 and all(_norm(x) in flat_doc or (len(_loose(x)) >= 8 and _loose(x) in _loose(doc)) for x in parts):
        return 'exact'
    # The same words with other punctuation (a "|" between table cells, curly quotes, a colon for "=", commas):
    # numbers keep their commas and points, so 4.5 is never read as 45.
    lq = _loose(quote)
    if len(lq) >= 12 and lq in _loose(doc):
        return 'exact'
    # A scan's misread characters ("3Qth" for 30th, "Sccond"): the same text once the look-alikes are one character,
    # on both sides, for a quote long enough that two different sentences cannot meet by chance.
    if len(lq) >= 24 and _ocr(lq) in _ocr(_loose(doc)):
        return 'exact'
    # A PDF font's ligature lost in the text layer ("addi onal", "es mated", "Mee ng": ti, tt, ft, fi, fl, ff are missing):
    # the same text once those letter pairs are dropped on both sides.
    if len(lq) >= 24 and _unlig(lq) in _unlig(_loose(doc)):
        return 'exact'
    # A model that writes the unit and currency into the row ("Revenue from operations ₹118,076 Mn" for a row that has 118,076 under a
    # "in million" heading, LTM): the same words and figures without the currency and unit words.
    bare = re.sub(r'[₹$€£]|\b(?:Rs|INR|USD|EUR|US\$)\b\.?|\b(?:mn|million|crores?|cr|lakhs?|lacs?|bn|billion)\b\.?', ' ', str(quote), flags=re.IGNORECASE)
    lb = _loose(bare)
    if bare != str(quote) and len(lb) >= 14 and lb in _loose(doc):
        return 'exact'
    if _spread_run(quote, doc):   # a table's text with another column interleaved line by line (Minda Corp, Om Galaxy, TFCI)
        return 'table'
    words = [w for w in re.findall(r'[a-z]{2,}|' + NUMBER, str(quote).lower())]
    numbers = {w.replace(',', '') for w in words if w[0].isdigit()}
    if not numbers or len(words) < 2:
        return False
    lines = doc.lower().splitlines()
    for i, ln in enumerate(lines):
        if numbers & {n.replace(',', '') for n in re.findall(NUMBER, ln)}:
            block = _norm(' '.join(lines[max(0, i - 6):i + 3]))
            if all(_norm(w) in block for w in words):
                return 'table'
    return False


def digits_in_quote(value, quote) -> bool:
    """A price or count is backed by its quote: its digits (Indian or Western commas, '.00' allowed) appear."""
    v = _num(value)
    if v is None:
        return False
    numbers = [float(n.replace(',', '')) for n in re.findall(r'\d[\d,]*(?:\.\d+)?', str(quote or ''))]
    return any(abs(n - abs(v)) < 1e-6 * max(1, abs(v)) for n in numbers)   # (7.9%) is -7.9


# The words that may follow a number for each unit in UNIT ('Rs. 300 Cr.', '28,200.00 Lakhs', 'ZAR 238 mn').
UNIT_WORDS = {1e3: r'thousand', 1e5: r'lakhs?|lacs?', 1e7: r'crores?|crs?\.?', 1e6: r'million|mn', 1e9: r'billion|bn'}


def unit_backed(value, unit, quote, found, doc: str | None = None) -> bool | None:
    """A lakh, crore, million or billion is backed by its quote (None when the unit multiplies nothing).
    Not backed when the number is already written in full (7 or more digits before the point: '95,00,00,000'
    crore would be 9.5e16), or, in an exact quote, when the unit's word does not follow the number: a
    filing's amount in words ('Rupees Two Hundred Ninety-Nine Crore ...') does not make 299,99,99,852.45
    a number of crores. A table quote keeps its unit in the column heading, so only the first test applies.
    The other way round: a reply with no unit (or rupees) is not backed when the quote puts a unit's word right
    after the number ('USD 15.5 billion' read as 15.5, 13 Oct)."""
    mult = UNIT.get(str(unit or 'rupees').strip().lower().rstrip('.'), 1)
    if mult == 1:
        v = _num(value)
        any_unit = '|'.join(UNIT_WORDS.values())
        for m in re.finditer(NUMBER, str(quote or '')):
            if v is not None and abs(float(m.group(0).replace(',', '')) - v) < 1e-6 * max(1, abs(v)) and re.match(
                    r'\s*(?:' + any_unit + r')(?![a-z])', quote[m.end():], re.IGNORECASE):
                return False
        return None
    v = _num(value)
    if v is None:
        return False
    if len(str(int(abs(v)))) >= 7:
        return False
    if found != 'exact':
        return table_unit(quote, mult, doc) if doc is not None else True
    for m in re.finditer(NUMBER, str(quote or '')):
        if abs(float(m.group(0).replace(',', '')) - v) < 1e-6 * max(1, abs(v)) and re.match(
                r'\s*(?:' + UNIT_WORDS[mult] + r')(?![a-z])', quote[m.end():], re.IGNORECASE):
            return True
    here = {m for m, rx in _UNIT_WORDS_ANY.items() if rx.search(str(quote or ''))}
    if here == {mult}:
        # the row names its own unit just before the figure ("Total Income (Rs Cr)  88  137  +57%"): the unit word
        # stands before the number with nothing but punctuation between them; a unit word after it is another number's
        for m in re.finditer(NUMBER, str(quote or '')):
            if abs(float(m.group(0).replace(',', '')) - v) < 1e-6 * max(1, abs(v)):
                head = str(quote)[:m.start()]
                u = list(_UNIT_WORDS_ANY[mult].finditer(head))
                if u and not re.search(r'[\w]', head[u[-1].end():]):
                    return True
    if doc is not None and not here:
        return table_unit(quote, mult, doc)   # a table row copied whole: its unit is in the heading above it
    return False


_UNIT_WORDS_ANY = {m: re.compile(r'(?<![a-z])(?:' + w + r')(?![a-z])', re.IGNORECASE) for m, w in UNIT_WORDS.items()}


def table_unit(quote, mult, doc: str) -> bool:
    """A table quote keeps its unit in the heading ('Rs. Crore | Quarter ended ...'): the unit word must be in the
    table block of the number's line (14 lines above, 2 below), and no other unit word of a different size beside it."""
    numbers = {n.replace(',', '') for n in re.findall(NUMBER, str(quote or ''))}
    lines = str(doc).splitlines()
    for i, ln in enumerate(lines):
        if numbers & {n.replace(',', '') for n in re.findall(NUMBER, ln)}:
            block = ' '.join(lines[max(0, i - 14):i + 3])
            if _UNIT_WORDS_ANY[mult].search(block) and not any(
                    rx.search(block) for m, rx in _UNIT_WORDS_ANY.items() if m != mult):
                return True
    # A text with few line breaks (LTM, 16 Oct: 123,000 characters in a handful of lines) has no "block" of lines: the
    # unit word nearest before the number, within 2,500 characters, is the table's unit.
    text = str(doc)
    for n in numbers:
        for m in re.finditer(r'(?<![\d,.])' + ',?'.join(re.escape(c) for c in n) + r'(?![\d])', text):
            before = text[max(0, m.start() - 2500):m.start()]
            near = [(u.end(), mm) for mm, rx in _UNIT_WORDS_ANY.items() for u in rx.finditer(before)]
            if near and max(near)[1] == mult:
                return True
    return False


def nearest_unit(quote, doc: str, value=None) -> float | None:
    """The size of the unit word nearest before the quote's number in the document, within 2,500 characters (the table's
    own heading: "tin million" in LTM, where the model said lakh), or None when there is none or the numbers are not found."""
    text = str(doc)
    best = None
    v = _num(value)
    nums = {n.replace(',', '') for n in re.findall(NUMBER, str(quote or ''))}
    if v is not None:      # the metric's own number, not the column numbers and note numbers beside it in the quote
        nums = {n for n in nums if abs(float(n) - abs(v)) < 1e-6 * max(1, abs(v))}
    for n in nums:
        for m in re.finditer(r'(?<![\d,.])' + ',?'.join(re.escape(c) for c in n) + r'(?![\d])', text):
            before = text[max(0, m.start() - 2500):m.start()]
            near = [(u.end(), mm) for mm, rx in _UNIT_WORDS_ANY.items() for u in rx.finditer(before)]
            if near:
                unit = max(near)[1]
                if best not in (None, unit):
                    return None      # two numbers, two answers: no repair
                best = unit
    return best


def _num(v):
    """A number, also when written with its currency or unit ('₹162/-', 'Rs. 29/-', '1,81,10,473 Equity
    Shares'); None when there is no number or more than one (our code never picks between two)."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    found = re.findall(NUMBER, str(v))
    if len(found) != 1:
        return None
    n = float(found[0].replace(',', ''))
    return -n if re.match(r'\s*[-−]\s*\d', str(v)) else n


def in_units(value, unit) -> float | None:
    """A number as written times its unit ('28,200.00' lakh -> 2,820,000,000). Our code converts, not the model."""
    v = _num(value)
    if v is None:
        return None
    return v * UNIT.get(str(unit or 'rupees').strip().lower().rstrip('.'), 1)


DATE_FORMATS = ('%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y', '%d.%m.%Y', '%d %B %Y', '%d %b %Y', '%d-%b-%Y', '%d-%B-%Y',
                '%B %d, %Y', '%b %d, %Y', '%B %d %Y')   # Indian filings write the day first: 01/10/2026 is 1 Oct


def as_date(v) -> str | None:
    """'October 1, 2026', '1st October, 2026', '01.10.2026' -> '2026-10-01'; None when not one of DATE_FORMATS."""
    s = re.sub(r'(\d)(st|nd|rd|th)\b', r'\1', str(v or '').strip(), flags=re.IGNORECASE).replace(',', ', ')
    s = re.sub(r'\s+', ' ', s).replace(' ,', ',')
    for fmt in DATE_FORMATS:
        for text in (s, s.replace(',', '')):
            try:
                return datetime.strptime(text, fmt).date().isoformat()
            except ValueError:
                pass
    return None


def same(name: str, expected, got) -> bool:
    if got is None:
        return False
    if name in NUMERIC:
        e, g = _num(expected), _num(got)
        return e is not None and g is not None and abs(e - g) <= 0.005 * max(1.0, abs(e))
    if isinstance(expected, bool):
        return str(got).strip().lower() in (('true', 'yes') if expected else ('false', 'no'))
    if name == 'ratio':
        return re.sub(r'\s', '', str(got)) == expected
    if name.endswith('_date'):
        return as_date(got) is not None and as_date(got) == as_date(expected)
    if name in ('capacity_from', 'capacity_to'):
        return _norm(expected) in _norm(got)
    return str(got).strip().lower() == str(expected).strip().lower()


def check(row: dict, sort_out, read_out, doc: str) -> dict:
    exp = row['expected']
    out = read_out if isinstance(read_out, dict) else {}
    fields = {}
    for f in out.get('fields') or []:
        if isinstance(f, dict) and f.get('name') in FIELDS and f['name'] not in fields:
            fields[f['name']] = f
    unit = (fields.get('amount_unit') or {}).get('value')
    lines, ok, total = [], 0, 0
    names = ['category'] + [k for k in exp if k not in ('category', 'metrics')]
    names += [k for k in fields if k not in exp and k not in ('amount_unit',)]
    for name in names:
        if name == 'category':
            got, quote, qf, digits, units = out.get('category'), None, None, None, None
        else:
            f = fields.get(name, {})
            got, quote = f.get('value'), f.get('quote')
            qf = quote_found(quote, doc) if f else None
            digits = digits_in_quote(got, quote) if f and name in DIGITS_IN_QUOTE else None
            units = unit_backed(got, unit, quote, qf) if f and name == 'amount' else None
            if name == 'amount' and f:
                got = in_units(got, unit)   # compared in rupees (or the filing's currency), as our code converts
        backed = qf is not False and digits is not False and units is not False
        if name in exp:
            total += 1
            match = same(name, exp[name], got) if name != 'category' else got == exp[name]
            ok += bool(match and backed)
        else:
            match = None   # the model gave a field the hand reading did not list
        lines.append({'field': name, 'expected': exp.get(name), 'model': got, 'match': match,
                      'quote_found': qf, 'digits_in_quote': digits, 'unit_backed': units, 'quote': quote})
    metrics = [m for m in out.get('metrics') or [] if isinstance(m, dict)]
    for want in exp.get('metrics', []):
        total += 1
        hit = next((m for m in metrics if (v := in_units(m.get('value'), m.get('unit'))) is not None
                    and abs(v - want['value']) <= 0.005 * max(1.0, abs(want['value']))), None)
        qf = quote_found(hit.get('quote'), doc) if hit else None
        digits = digits_in_quote(hit.get('value'), hit.get('quote')) if hit else None
        units = unit_backed(hit.get('value'), hit.get('unit'), hit.get('quote'), qf) if hit else None
        good = bool(hit) and qf is not False and digits is not False and units is not False
        ok += good
        lines.append({'field': f"metric: {want['label']}", 'expected': want['value'],
                      'model': (f"{hit.get('value')} {hit.get('unit') or ''} ({hit.get('label')}, {hit.get('period')})"
                                if hit else None), 'match': good, 'quote_found': qf, 'digits_in_quote': digits,
                      'unit_backed': units, 'quote': hit.get('quote') if hit else None})
    s = sort_out if isinstance(sort_out, dict) else {}
    return {'symbol': row['symbol'], 'subject': row['subject'], 'score': [ok, total], 'fields': lines,
            'metrics_given': len(metrics), 'sort_category': s.get('category'), 'sort_read_pdf': s.get('read_pdf'),
            'sort_category_right': s.get('category') == exp['category']}


def _cell(v) -> str:
    return '' if v is None else ('yes' if v is True else 'no' if v is False else str(v).replace('|', '/')[:90])


def _summary(results: list[dict]) -> tuple[int, int, int]:
    ok = sum(r['score'][0] for r in results if 'score' in r)
    total = sum(r['score'][1] for r in results if 'score' in r)
    held = sum(f['quote_found'] is False or f['digits_in_quote'] is False or f.get('unit_backed') is False
               for r in results for f in r.get('fields', []))
    return ok, total, held


def report_markdown(results: list[dict], models: dict) -> str:
    readers = list(dict.fromkeys(r.get('reader', 'gemini') for r in results))
    out = [f"### Announcement reader sample ({PROMPT_VERSION})", '',
           f"Sorter `{models.get('sort')}`. A value counts only when it is right and backed by a quote found in the PDF.", '']
    out += ['| Reader | Right | Held back | Errors | Seconds a filing (median) |', '|---|---|---|---|---|']
    for rd in readers:
        rs = [r for r in results if r.get('reader', 'gemini') == rd]
        ok, total, held = _summary(rs)
        secs = sorted(r['seconds'] for r in rs if 'score' in r and r.get('seconds') is not None)
        med = secs[len(secs) // 2] if secs else '-'
        out.append(f"| {rd} | **{ok} of {total}** | {held} | {sum('error' in r for r in rs)} | {med} |")
    symbols = list(dict.fromkeys(r['symbol'] for r in results))
    out += ['', '| Filing | ' + ' | '.join(readers) + ' |', '|---|' + '---|' * len(readers)]
    for sym in symbols:
        cells = []
        for rd in readers:
            r = next((x for x in results if x['symbol'] == sym and x.get('reader', 'gemini') == rd), None)
            cells.append('-' if r is None else (f"error: {_cell(r['error'])[:40]}" if 'error' in r
                                                 else f"{r['score'][0]}/{r['score'][1]}"))
        out.append(f"| {sym} | " + ' | '.join(cells) + ' |')
    out += ['', '| Filing | Sorter (subject only) | Notes |', '|---|---|---|']
    for r in results:
        if 'score' in r:
            out.append(f"| {r['symbol']} ({_cell(r.get('reader', 'gemini'))}) | {_cell(r.get('sort_category'))}"
                       f"{' ✓' if r.get('sort_category_right') else ' ✗'}{' (sorter busy)' if r.get('sort_error') else ''}"
                       f", read PDF: {_cell(r.get('sort_read_pdf'))} | {_cell('; '.join(r.get('notes', [])))} |")
    for r in results:
        if 'fields' not in r:
            continue
        out += ['', f"**{r['symbol']}**, {r.get('reader', 'gemini')}", '',
                '| Field | From the PDF | Model | Right | Quote in PDF | Digits in quote | Unit in quote |',
                '|---|---|---|---|---|---|---|']
        out += [f"| {f['field']} | {_cell(f['expected'])} | {_cell(f['model'])} | {_cell(f['match'])} | "
                f"{_cell(f['quote_found'])} | {_cell(f['digits_in_quote'])} | {_cell(f.get('unit_backed'))} |"
                for f in r['fields']]
    return '\n'.join(out) + '\n'


def rescore(results: list[dict], rows: list[dict]) -> None:
    """The saved replies scored again with the current checks: a fix to the checks needs no new model calls.
    A reply that no longer parses (saved cut at 4,000 characters) keeps its old score, marked as such."""
    by_symbol, docs = {r['symbol']: r for r in rows}, {}
    for res in results:
        row = by_symbol.get(res['symbol'])
        if row is None or 'read_raw' not in res:
            continue
        out = parse_json(res['read_raw'])
        if out is None:
            res.setdefault('notes', []).append('not rescored: saved reply cut short')
            continue
        if row['symbol'] not in docs:
            docs[row['symbol']] = document(row['file_url'])[0]
        sort = {k: res.get(k) for k in ('sort_category', 'sort_read_pdf', 'sort_category_right')}
        res.update(check(row, None, out, docs[row['symbol']]), **sort)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--only', help='symbols from the sample, comma-separated (default: announcement_sample_run.txt, '
                                   'else all)')
    ap.add_argument('--readers', help='readers, comma-separated, as on the run file\'s readers: line (overrides it)')
    ap.add_argument('--no-sort', action='store_true', help='skip the sorter (another job in the same run sorts)')
    ap.add_argument('--matrix', action='store_true', help='print the workflow\'s job list as JSON, call nothing')
    ap.add_argument('--rescore', action='store_true', help='with --combine: score the saved replies again with '
                                                           'the current checks (downloads each filing once)')
    ap.add_argument('--combine', help='folder of results files from parallel jobs: print one report, call nothing')
    args = ap.parse_args(argv)
    summary = os.environ.get('GITHUB_STEP_SUMMARY')

    def emit(text):
        print(text)
        if summary:
            with open(summary, 'a', encoding='utf-8') as f:
                f.write(text)

    if args.matrix:
        run_file = HERE / 'announcement_sample_run.txt'
        print(json.dumps(matrix(run_file.read_text() if run_file.exists() else '')))
        return
    if args.combine:
        files = sorted(Path(args.combine).rglob('*.json'))
        merged = [json.loads(f.read_text(encoding='utf-8')) for f in files]
        results = [r for m in merged for r in m.get('results', [])]
        if args.rescore:
            rescore(results, json.loads((HERE / 'announcement_sample_expected.json').read_text(encoding='utf-8')))
        models = next((m['models'] for m in merged if m.get('models', {}).get('sort')), {})
        emit(report_markdown(results, models) if results else f'No results files in {args.combine}.\n')
        return
    key = os.environ.get('GEMINI_API_KEY', '').strip()
    if not key:
        emit('GEMINI_API_KEY is not set (Settings → Secrets and variables → Actions); nothing was sent.\n')
        return
    rows = json.loads((HERE / 'announcement_sample_expected.json').read_text(encoding='utf-8'))
    run_file = HERE / 'announcement_sample_run.txt'
    only = args.only or (run_file.read_text().strip() if run_file.exists() else '')
    lines = [ln for ln in only.splitlines()
             if not ln.strip().startswith('#') and not ln.strip().lower().startswith('readers:')]
    wanted = {x.strip() for x in ','.join(lines).split(',') if x.strip()}
    rows = [r for r in rows if not wanted or r['symbol'] in wanted]
    log('filings this run:', ', '.join(r['symbol'] for r in rows))
    g = Gemini(key)
    available = g.models()
    readers, sorters = available_of(available, READERS), available_of(available, SORTERS)
    models = {'read': ', '.join(readers), 'sort': ', '.join(sorters)}
    names = sorted(m['name'].split('/', 1)[-1] for m in available
                   if 'generateContent' in m.get('supportedGenerationMethods', []))
    log('models with generateContent:', ', '.join(names))
    log('reader', models['read'], 'sorter', models['sort'])
    if not readers:
        emit(f'None of {READERS} is in this key\'s model list: {", ".join(names)}\n')
        sys.exit(1)
    # Who reads each filing: "gemini" (3.5 then 3.1 Flash-Lite) and/or provider:model entries, each scored alone.
    lanes, clients = [], {}
    if args.no_sort:
        sorters, models['sort'] = [], ''
    chosen = (parse_readers('readers: ' + args.readers) if args.readers
              else parse_readers(run_file.read_text() if run_file.exists() else ''))
    for entry in chosen:
        if entry == 'gemini':
            lanes.append(('gemini', g, readers, None))
            continue
        prov, _, model = entry.partition(':')
        if prov not in PROVIDERS:
            log('unknown reader', entry)
            continue
        base, secret, limit = PROVIDERS[prov]
        pkey = os.environ.get(secret, '').strip()
        if not pkey:
            emit(f'{secret} is not set; {entry} skipped.\n')
            continue
        try:
            if prov not in clients:
                found, unlisted, err = None, None, None
                for b in (base, *OTHER_BASES.get(prov, ())):   # the first address that lists its models wins
                    client = OpenAICompat(prov, b, pkey)
                    try:
                        listed = client.models()
                    except Exception as exc:  # noqa: BLE001 -- the next address, if any
                        err = exc
                        continue
                    if listed is not None:
                        found = (client, {m['name'] for m in listed})
                        break
                    unlisted = unlisted or client
                if found is None and unlisted is None:
                    raise err
                if found is None:
                    log(f'{prov}: no address lists its models; trying {unlisted.base} with the models as named')
                    found = (unlisted, None)
                clients[prov] = found
        except Exception as exc:  # noqa: BLE001
            emit(f'{prov}: {exc}\n')
            continue
        client, ids = clients[prov]
        if prov in FREE_ONLY and model.removesuffix('+thinking') not in FREE_ONLY[prov]:
            emit(f'{entry}: not one of {prov}\'s free models ({", ".join(FREE_ONLY[prov])}); skipped, never paid for.\n')
            continue
        if ids is not None and model.removesuffix('+thinking') not in ids:
            if prov not in FREE_ONLY:
                emit(f'{entry}: not in {prov}\'s model list ({", ".join(sorted(ids))[:600]}).\n')
                continue
            log(f'{entry}: not in {prov}\'s model list but on its free pricing list; tried as named')
        small = MODEL_LIMITS.get(model.removesuffix('+thinking'), (None,))[0]
        lanes.append((entry, client, [model], min(x for x in (limit, small) if x) if (limit or small) else None))
    log('readers:', ', '.join(lane[0] for lane in lanes))
    results, started = [], time.monotonic()
    per_filing = PER_FILING_SECONDS * max(1, len(lanes))

    def save():
        """Results so far, after every filing: a stall or a cancelled run keeps what was read."""
        Path('announcement_sample_results.json').write_text(
            json.dumps({'prompt_version': PROMPT_VERSION, 'models': models, 'results': results}, indent=1,
                       ensure_ascii=False, default=str))

    def too_long(signum, frame):
        raise TimeoutError('gave up: the filing took too long')

    signal.signal(signal.SIGALRM, too_long)
    for row in rows:
        if time.monotonic() - started > RUN_SECONDS:
            results += [{'symbol': row['symbol'], 'subject': row['subject'], 'reader': lane[0],
                         'error': 'not read: run time used up'} for lane in lanes]
            continue
        log('---', row['symbol'], row['subject'])
        signal.alarm(per_filing)
        try:
            sort_res = {}
            if sorters:   # sorting failing never stops the reading
                try:
                    text, usage, used = g.generate(sorters, sort_prompt(row), 'sort', json_mode=True)
                    sort_res = {'out': parse_json(text), 'raw': text[:500], 'model': used}
                except RuntimeError as exc:
                    sort_res = {'error': str(exc)[:200]}
            doc, doc_notes = document(row['file_url'])
        except Exception as exc:  # noqa: BLE001 -- one filing failing must not stop the sample
            signal.alarm(0)
            results.append({'symbol': row['symbol'], 'subject': row['subject'],
                            'error': f'{type(exc).__name__}: {exc}'[:300]})
            save()
            continue
        for name, client, models_, limit in lanes:
            res = {'symbol': row['symbol'], 'subject': row['subject'], 'reader': name,
                   **({'sort_error': sort_res['error']} if 'error' in sort_res else {})}
            t0 = time.monotonic()
            try:
                prompt = read_prompt(row, doc)
                if limit and len(prompt) > limit:
                    raise RuntimeError(f'{len(prompt):,} characters, over {name}\'s free limit per call')
                text, usage, used = client.generate(models_, prompt, 'read', json_mode=True)
                read_out = parse_json(text)
                notes = doc_notes + [f"{used}, {usage.get('promptTokenCount', '?')} tokens in"]
                if read_out is None:
                    notes.append('reply was not JSON')
                res.update(check(row, sort_res.get('out'), read_out, doc), notes=notes, read_raw=text[:4000],
                           read_model=used)
            except Exception as exc:  # noqa: BLE001
                res['error'] = f'{type(exc).__name__}: {exc}'[:300]
            res['seconds'] = round(time.monotonic() - t0, 1)
            results.append(res)
            save()
            log(row['symbol'], name, res.get('score'), res.get('error', ''))
        signal.alarm(0)
    save()
    emit(report_markdown(results, models))


if __name__ == '__main__':
    main()
