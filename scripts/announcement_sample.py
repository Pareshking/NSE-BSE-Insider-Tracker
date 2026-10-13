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
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
API = 'https://generativelanguage.googleapis.com/v1beta'
PROMPT_VERSION = 'sample-1'
# Preferred model ids, first found in the account's model list wins.
READERS = ('gemini-3.5-flash-lite', 'gemini-3.1-flash-lite')
SORTERS = ('gemma-4-26b-it', 'gemma-4-31b-it')
PACE = {'read': 6.0, 'sort': 3.0}   # seconds between calls: 15 and 30 requests a minute allow 4 and 2
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
    'auditor_resignation': 'statutory auditor resigned',
    'rating_upgrade': 'credit rating raised',
    'rating_downgrade': 'credit rating lowered or put on watch negative',
    'rating_reaffirmed': 'credit rating kept unchanged',
    'deal_or_dispute': 'acquisition, sale, merger, litigation, arbitration or regulatory order',
    'routine': 'anything else (meetings, reminders, newspaper copies, compliance certificates)',
}
FIELDS = {
    'price_per_share': 'issue, offer or buyback price per share in rupees (a fixed price only)',
    'max_price_per_share': 'maximum price per share in rupees ("not exceeding"), for open-market buybacks',
    'shares': 'number of shares or warrants issued, allotted, converted, offered or bought back',
    'amount_rs': 'total size in rupees as a plain number (convert lakh, crore, million, billion)',
    'discount_pct': 'discount to the floor price, in percent',
    'allottee_is_promoter': 'true if the filing says the allottees or subscribers are promoters, false if it says not',
    'ratio': 'rights entitlement ratio as "new:held", e.g. "2:21"',
    'record_date': 'record date, YYYY-MM-DD',
    'offer_pct': 'open offer size as percent of share capital',
    'about_listed_company': 'false when the event concerns a subsidiary rather than the listed company itself',
}
NUMERIC = ('price_per_share', 'max_price_per_share', 'shares', 'amount_rs', 'discount_pct', 'offer_pct')
DIGITS_IN_QUOTE = ('price_per_share', 'max_price_per_share', 'shares')


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
    return (f'Below is the text of an announcement filed with NSE by {row["symbol"]} (subject: {row["subject"]}).\n'
            f'Categories:\n{cats}\n\nFields:\n{fields}\n\n'
            'Return only JSON: {"category": one category name, "fields": [{"name": field name, '
            '"value": number, true/false or text, "quote": the exact words from the document that state it}]}.\n'
            'Rules: include a field only if the document states it; never compute or guess; the quote must be '
            'copied character for character from the document, one sentence or table row at most; '
            'leave fields out rather than invent them.\n\n=== DOCUMENT ===\n' + doc)


# --- the model API -----------------------------------------------------------------

class Gemini:
    def __init__(self, key: str, session=None, sleep=time.sleep):
        self.s = session or requests.Session()
        self.s.headers['x-goog-api-key'] = key
        self.sleep = sleep
        self.last = {}

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

    def generate(self, model: str, prompt: str, kind: str, json_mode: bool) -> tuple[str, dict]:
        wait = PACE[kind] - (time.monotonic() - self.last.get(kind, -1e9))
        if wait > 0:
            self.sleep(wait)
        body = {'contents': [{'role': 'user', 'parts': [{'text': prompt}]}],
                'generationConfig': {'temperature': 0, **({'responseMimeType': 'application/json'} if json_mode else {})}}
        for attempt in range(3):
            self.last[kind] = time.monotonic()
            r = self.s.post(f'{API}/models/{model}:generateContent', json=body, timeout=120)
            log(f'{kind} {model}: HTTP {r.status_code}', '' if r.status_code == 200 else r.text[:300])
            if r.status_code == 400 and json_mode and 'mime' in r.text.lower():
                body['generationConfig'].pop('responseMimeType', None)   # a model without JSON mode
                json_mode = False
                continue
            if r.status_code in (429, 500, 503):
                if attempt == 2:
                    break
                self.sleep(20 * (attempt + 1))
                continue
            if r.status_code != 200:
                raise RuntimeError(f'{model}: HTTP {r.status_code}: {r.text[:300]}')
            j = r.json()
            parts = (j.get('candidates') or [{}])[0].get('content', {}).get('parts', [])
            return ''.join(p.get('text', '') for p in parts if not p.get('thought')), j.get('usageMetadata', {})
        raise RuntimeError(f'{model}: still refused after retries')


def pick(models: list[dict], wanted: tuple[str, ...]) -> str | None:
    names = {m['name'].split('/', 1)[-1] for m in models
             if 'generateContent' in m.get('supportedGenerationMethods', [])}
    return next((w for w in wanted if w in names), None)


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
        out = subprocess.run(['pdftotext', str(src), '-'], capture_output=True, timeout=180, check=False)
        return out.stdout.decode('utf-8', errors='replace')


def document(url: str, session=None) -> tuple[str, list[str]]:
    """(text, notes). A ZIP's PDFs are read in name order, each under a header line."""
    s = session or requests
    log('download', url.rsplit('/', 1)[-1])
    r = s.get(url, headers={'User-Agent': UA, 'Referer': 'https://www.nseindia.com/'}, timeout=(15, 120))
    log('download: HTTP', r.status_code, f'{len(r.content):,} bytes')
    r.raise_for_status()
    data, notes = r.content, [f'{len(r.content) / 1024 ** 2:.1f} MB']
    if data[:2] == b'PK':
        z = zipfile.ZipFile(io.BytesIO(data))
        pdfs = sorted(n for n in z.namelist() if n.lower().endswith('.pdf'))
        notes.append(f'zip: {len(pdfs)} PDFs of {len(z.namelist())} entries')
        text = '\n'.join(f'=== file: {n} ===\n{pdf_text(z.read(n))}' for n in pdfs)
    else:
        text = pdf_text(data)
    if not text.strip():
        notes.append('no text layer (scanned?)')
    if len(text) > MAX_CHARS:
        notes.append(f'cut to {MAX_CHARS:,} of {len(text):,} characters')
        text = text[:MAX_CHARS]
    return text, notes


# --- checks ------------------------------------------------------------------------

def _norm(s: str) -> str:
    s = str(s).lower().translate(str.maketrans({'’': "'", '‘': "'", '“': '"', '”': '"',
                                                '–': '-', '—': '-', ' ': ' '}))
    return re.sub(r'\s+', '', s)


def quote_found(quote, doc: str) -> bool:
    """The quote is in the document, ignoring case and all whitespace (pdftotext breaks lines and columns)."""
    q = _norm(quote or '')
    return len(q) >= 8 and q in _norm(doc)


def digits_in_quote(value, quote) -> bool:
    """A price or count is backed by its quote: its digits (Indian or Western commas, '.00' allowed) appear."""
    try:
        v = float(str(value).replace(',', ''))
    except ValueError:
        return False
    numbers = [float(n.replace(',', '')) for n in re.findall(r'\d[\d,]*(?:\.\d+)?', str(quote or ''))]
    return any(abs(n - v) < 1e-6 * max(1, abs(v)) for n in numbers)


def _num(v):
    try:
        return float(str(v).replace(',', '').replace('%', '').strip())
    except (TypeError, ValueError):
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
    return str(got).strip() == str(expected)


def check(row: dict, sort_out, read_out, doc: str) -> dict:
    exp = row['expected']
    fields = {}
    for f in (read_out or {}).get('fields') or []:
        if isinstance(f, dict) and f.get('name') in FIELDS and f['name'] not in fields:
            fields[f['name']] = f
    lines, ok, total = [], 0, 0
    for name in ['category'] + [k for k in exp if k != 'category'] + [k for k in fields if k not in exp]:
        if name == 'category':
            got, quote, qf, digits = (read_out or {}).get('category'), None, None, None
        else:
            f = fields.get(name, {})
            got, quote = f.get('value'), f.get('quote')
            qf = quote_found(quote, doc) if f else None
            digits = digits_in_quote(got, quote) if f and name in DIGITS_IN_QUOTE else None
        backed = qf is not False and digits is not False
        if name in exp:
            total += 1
            match = same(name, exp[name], got) if name != 'category' else got == exp[name]
            ok += bool(match and backed)
        else:
            match = None   # the model gave a field the hand reading did not list
        lines.append({'field': name, 'expected': exp.get(name), 'model': got, 'match': match,
                      'quote_found': qf, 'digits_in_quote': digits, 'quote': quote})
    s = sort_out or {}
    return {'symbol': row['symbol'], 'subject': row['subject'], 'score': [ok, total], 'fields': lines,
            'sort_category': s.get('category'), 'sort_read_pdf': s.get('read_pdf'),
            'sort_category_right': s.get('category') == exp['category']}


def _cell(v) -> str:
    return '' if v is None else ('yes' if v is True else 'no' if v is False else str(v).replace('|', '/')[:90])


def report_markdown(results: list[dict], models: dict) -> str:
    ok = sum(r['score'][0] for r in results if 'score' in r)
    total = sum(r['score'][1] for r in results if 'score' in r)
    sorted_right = sum(bool(r.get('sort_category_right')) for r in results)
    held = sum(f['quote_found'] is False or f['digits_in_quote'] is False
               for r in results for f in r.get('fields', []))
    head = (f"Reader `{models.get('read')}`, sorter `{models.get('sort')}`. "
            f"Values right and backed by a quote found in the PDF: **{ok} of {total}**. "
            f"Sorter's category right from the subject line alone: **{sorted_right} of {len(results)}**. "
            f"Fields held back (quote not in the PDF, or its digits not in the quote): **{held}**.")
    out = [f"### Announcement reader sample ({PROMPT_VERSION})", '', head, '',
           '| Filing | Score | Sorter (subject only) | Notes |', '|---|---|---|---|']
    for r in results:
        if 'error' in r:
            out.append(f"| {r['symbol']} | - | - | error: {_cell(r['error'])} |")
            continue
        out.append(f"| {r['symbol']} ({_cell(r['subject'])}) | {r['score'][0]}/{r['score'][1]} | "
                   f"{_cell(r['sort_category'])}{' ✓' if r['sort_category_right'] else ' ✗'}, read PDF: "
                   f"{_cell(r['sort_read_pdf'])} | {_cell('; '.join(r.get('notes', [])))} |")
    for r in results:
        if 'fields' not in r:
            continue
        out += ['', f"**{r['symbol']}**", '', '| Field | From the PDF | Model | Right | Quote in PDF | Digits in quote |',
                '|---|---|---|---|---|---|']
        out += [f"| {f['field']} | {_cell(f['expected'])} | {_cell(f['model'])} | {_cell(f['match'])} | "
                f"{_cell(f['quote_found'])} | {_cell(f['digits_in_quote'])} |" for f in r['fields']]
    return '\n'.join(out) + '\n'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--only', help='one symbol from the sample')
    args = ap.parse_args(argv)
    summary = os.environ.get('GITHUB_STEP_SUMMARY')

    def emit(text):
        print(text)
        if summary:
            with open(summary, 'a', encoding='utf-8') as f:
                f.write(text)

    key = os.environ.get('GEMINI_API_KEY', '').strip()
    if not key:
        emit('GEMINI_API_KEY is not set (Settings → Secrets and variables → Actions); nothing was sent.\n')
        return
    rows = json.loads((HERE / 'announcement_sample_expected.json').read_text(encoding='utf-8'))
    rows = [r for r in rows if not args.only or r['symbol'] == args.only]
    g = Gemini(key)
    available = g.models()
    models = {'read': pick(available, READERS), 'sort': pick(available, SORTERS)}
    names = sorted(m['name'].split('/', 1)[-1] for m in available
                   if 'generateContent' in m.get('supportedGenerationMethods', []))
    log('models with generateContent:', ', '.join(names))
    log('reader', models['read'], 'sorter', models['sort'])
    if not models['read']:
        emit(f'None of {READERS} is in this key\'s model list: {", ".join(names)}\n')
        sys.exit(1)
    results = []
    for row in rows:
        log('---', row['symbol'], row['subject'])
        res = {'symbol': row['symbol'], 'subject': row['subject']}
        try:
            sort_out = None
            if models['sort']:
                text, usage = g.generate(models['sort'], sort_prompt(row), 'sort', json_mode=True)
                sort_out = parse_json(text)
                res['sort_raw'], res['sort_tokens'] = text[:500], usage.get('promptTokenCount')
            doc, notes = document(row['file_url'])
            text, usage = g.generate(models['read'], read_prompt(row, doc), 'read', json_mode=True)
            read_out = parse_json(text)
            notes.append(f"{usage.get('promptTokenCount', '?')} tokens in")
            if read_out is None:
                notes.append('reply was not JSON')
            res.update(check(row, sort_out, read_out, doc), notes=notes, read_raw=text[:4000])
        except Exception as exc:  # noqa: BLE001 -- one filing failing must not stop the sample
            res['error'] = f'{type(exc).__name__}: {exc}'[:300]
        results.append(res)
        log(row['symbol'], res.get('score'), res.get('error', ''))
    Path('announcement_sample_results.json').write_text(
        json.dumps({'prompt_version': PROMPT_VERSION, 'models': models, 'results': results}, indent=1,
                   ensure_ascii=False, default=str))
    emit(report_markdown(results, models))


if __name__ == '__main__':
    main()
