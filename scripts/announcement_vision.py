"""Vision repair for the announcement reader (17 Oct 2026, owner's design).

A card the text read could not make safe (headline held, or fields held) is read again from the PAGE IMAGES of its PDF:
1. page triage, no AI: the pages that carry the card (page 1, pages of figures, scans) are chosen, signature / disclaimer
   pages are left out, and every page left out is named (rule 8: never half a document, the card says what was not sent);
2. the chosen pages go to the first Gemini model of the list that answers (each model has its own quota), one request;
3. the answer goes through the SAME checks as a text read (reader.result_of): every quote must be words of the filing's
   PDF text, every number backed, headline rules applied. The model extracts; the code decides.
The vision result replaces the text result only if it is better (headline shown, at least as many fields shown). Off unless
READER_VISION=1. Nothing here writes anywhere.
"""
from __future__ import annotations

import base64
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

import requests

MAX_PAGES = int(os.environ.get('VISION_MAX_PAGES', '8'))
DPI = int(os.environ.get('VISION_DPI', '130'))
DEFAULT_MODELS = ('gemini:gemini-3.5-flash,gemini:gemini-3.6-flash,gemini:gemini-3.7-flash,gemini:gemini-3.8-flash,'   # ids checked against the key's model list, 17 Oct
                  'gemini:gemini-3.5-flash-lite,gemini:gemini-3.1-flash-lite')
API = 'https://generativelanguage.googleapis.com/v1beta'

KEY_TERMS = re.compile(r'\b(?:shares?|warrants?|%|per\s*cent|rs\.?|inr|₹|crore|cr\.?|lakh|million|revenue|sales|profit|income|rating|'
                       r'pledge\w*|encumb\w*|price|consideration|before|after|acquisition|allot\w*|capacity|order|facility|amount)\b', re.I)
BOILER = re.compile(r'yours\s+faithfully|thanking\s+you|for\s+and\s+on\s+behalf|company\s+secretary|disclaimer|registered\s+office|'
                    r'cin\s*[:\-]|website|email|e-mail|telephone|tel\.?\s*:', re.I)
NUMBER = re.compile(r'\d[\d,]*(?:\.\d+)?')


COOL: dict[str, float] = {}   # model -> time (monotonic) it may be tried again


def models() -> list[str]:
    return [m.strip() for m in os.environ.get('READER_VISION_MODELS', DEFAULT_MODELS).split(',') if m.strip().startswith('gemini:')]


def enabled() -> bool:
    return os.environ.get('READER_VISION', '0') == '1' and bool(os.environ.get('GEMINI_API_KEY', '').strip())


def pages_of(data: bytes) -> list[str]:
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / 'f.pdf'
        src.write_bytes(data)
        out = subprocess.run(['pdftotext', '-layout', str(src), '-'], capture_output=True, timeout=180, check=False)
    pages = out.stdout.decode('utf-8', errors='replace').split('\f')
    return pages[:-1] if pages and not pages[-1].strip() else pages


def triage(pages: list[str], max_pages: int = MAX_PAGES) -> tuple[list[int], dict[int, str]]:
    """(1-based pages to send, why each page was sent or left out)."""
    why, score = {}, {}
    for i, p in enumerate(pages, 1):
        n, nums, terms = len(re.sub(r'\s', '', p)), len(NUMBER.findall(p)), len(KEY_TERMS.findall(p))
        if n < 80:
            score[i], why[i] = 100, 'no text layer (a scan)'
        elif i == 1:
            score[i], why[i] = 1000, 'first page'
        elif BOILER.search(p) and nums < 8 and terms < 6:
            score[i], why[i] = -1, 'left out: signature / disclaimer / address page'
        elif (nums >= 6 and terms >= 4) or nums >= 30:
            score[i], why[i] = nums + terms, f'{nums} numbers, {terms} key words'
        else:
            score[i], why[i] = -1, f'left out: {nums} numbers, {terms} key words'
    pick = sorted((i for i in score if score[i] > 0), key=lambda i: -score[i])[:max_pages]
    for i in score:
        if score[i] > 0 and i not in pick:
            why[i] = 'left out: over the page limit'
    return sorted(pick), why


def render(data: bytes, pages: list[int]) -> dict[int, bytes]:
    out = {}
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / 'f.pdf'
        src.write_bytes(data)
        for p in pages:
            base = Path(d) / f'p{p}'
            subprocess.run(['pdftoppm', '-r', str(DPI), '-png', '-singlefile', '-f', str(p), '-l', str(p), str(src), str(base)],
                           capture_output=True, timeout=180, check=False)
            f = Path(str(base) + '.png')
            if f.exists():
                out[p] = f.read_bytes()
    return out


def ask_gemini(model: str, prompt: str, images: dict[int, bytes], session=requests, sleep=time.sleep) -> tuple[str, dict]:
    """(reply text, usage). RuntimeError('HTTP 429 ...') when the model cannot answer now: the caller tries the next model."""
    key = os.environ.get('GEMINI_API_KEY', '').strip()
    parts = [{'text': prompt}] + [{'inlineData': {'mimeType': 'image/png', 'data': base64.b64encode(b).decode()}} for b in images.values()]
    for attempt in range(2):
        r = session.post(f'{API}/models/{model}:generateContent', headers={'x-goog-api-key': key}, timeout=150,
                         json={'contents': [{'role': 'user', 'parts': parts}],
                               'generationConfig': {'temperature': 0, 'responseMimeType': 'application/json'}})
        if r.status_code in (429, 503) and attempt == 0:
            sleep(10)
            continue
        if r.status_code != 200:
            raise RuntimeError(f'{model}: HTTP {r.status_code}: {r.text[:120]}')
        j = r.json()
        u = j.get('usageMetadata') or {}
        text = ''.join(p.get('text', '') for p in j['candidates'][0]['content']['parts'])
        return text, {'prompt_tokens': u.get('promptTokenCount'), 'out_tokens': u.get('candidatesTokenCount'),
                      'images': len(images), 'requests': attempt + 1}
    raise RuntimeError(f'{model}: no answer')


# Card kinds whose numbers live in tables or several rows: the text read can pass its own checks with the wrong row (17 Oct replay: Federal
# Bank 7,100 shares for a 99,954 total; Affle 29.81 million shares for 74 lakh warrants). The page image is a second, independent reading.
TABLE_CATEGORIES = {'financial_results', 'stake_change', 'pledge', 'esop', 'warrant_conversion', 'preferential', 'qip', 'rights',
                    'rating_upgrade', 'rating_downgrade', 'rating_reaffirmed', 'rating_assigned', 'debt_issue', 'open_offer',
                    'buyback_open_market', 'buyback_tender', 'dividend', 'bonus_split', 'capex', 'business_update'}


def needs_vision(res: dict) -> str | None:
    """Why the text read of a filing should be tried again from the page images; None when the card is safe as it is."""
    if not res.get('ok'):
        return None
    head = res.get('headline')
    held = sum(not f.get('shown') for f in (res.get('fields') or [])) + sum(not m.get('shown') for m in (res.get('metrics') or []))
    if not head or head.get('shown') is False:
        return 'the headline was held' + (f' ({held} values held)' if held else '')
    if held >= 2:
        return f'{held} values held'
    if res.get('category') in TABLE_CATEGORIES:
        return f'a table card ({res.get("category")}): the page image is read as a second opinion'
    return None


def shown_count(res: dict) -> int:
    """Values shown, not counting `entity` (held on every card until entity labels are shown on the site)."""
    return (sum(bool(f.get('shown')) for f in (res.get('fields') or []) if f.get('name') != 'entity')
            + sum(bool(m.get('shown')) for m in (res.get('metrics') or [])))


def better(vision: dict, text: dict) -> bool:
    """The vision result replaces the text result when it passes every check (shown headline) and either shows at least as many
    values or the card is a table card: there the page image is the better reader, and a true general headline (Federal Bank: "allots
    shares under stock option schemes", the three allotments as points) beats a specific wrong one (7,100 shares of a 99,954 total)."""
    head = vision.get('headline')
    if not (vision.get('ok') and head and head.get('shown') is not False and head.get('text')):
        return False
    return shown_count(vision) >= shown_count(text) or (text.get('category') in TABLE_CATEGORIES and bool(vision.get('points')))


_NUM = re.compile(r'\d[\d,]*(?:\.\d+)?')


def numbers_of(text) -> set[float]:
    """The figures a text states that matter: not a day, a month or a year (an integer up to 31, or 1990-2040 without a decimal)."""
    out = set()
    for tok in _NUM.findall(str(text or '')):
        try:
            v = float(tok.replace(',', ''))
        except ValueError:
            continue
        if '.' not in tok and (v <= 31 or (',' not in tok and 1990 <= v <= 2040)):
            continue
        out.add(v)
    return out


def _all_text(res: dict) -> str:
    h = res.get('headline') or {}
    parts = [h.get('text'), (h.get('subtitle') or {}).get('text'), h.get('quote')]
    parts += [p.get('text') for p in (res.get('points') or [])]
    parts += [f'{f.get("value")} {f.get("quote")}' for f in (res.get('fields') or [])]
    parts += [f'{m.get("value")} {m.get("quote")}' for m in (res.get('metrics') or [])]
    return ' '.join(str(x) for x in parts if x)


def unsupported_numbers(text_res: dict, vision_res: dict) -> list[float]:
    """Figures in the text read's headline (and subtitle) that the page-image read does not state anywhere (to 0.5 %): the two readers
    disagree on them, so neither can be taken. Two independent readings agreeing is the evidence; one alone is not."""
    h = text_res.get('headline') or {}
    mine = numbers_of(f'{h.get("text")} {(h.get("subtitle") or {}).get("text")}')
    theirs = numbers_of(_all_text(vision_res))
    return sorted(n for n in mine if not any(abs(n - t) <= 0.005 * max(abs(n), 1) for t in theirs))


def vision_text(prompt_for, data: bytes, ask=ask_gemini) -> tuple[str, str, float, dict, str] | None:
    """(answer, model, seconds, usage, pages note) from the first model that answers; None when the PDF has no pages to draw or
    no model answers. `prompt_for(note)` builds the reader's prompt with the note in place of the document text."""
    pages = pages_of(data)
    pick, why = triage(pages)
    imgs = render(data, pick) if pick else {}
    if not imgs:
        return None
    left = [f'p{i} ({why[i]})' for i in sorted(why) if i not in imgs]
    note = (f'(The filing has {len(pages)} pages. Its pages {", ".join(map(str, imgs))} are attached as images: read the images; '
            f'copy every quote and number exactly as printed.' + (f' Not sent: {"; ".join(left)}.' if left else '') + ')')
    for entry in models():
        model = entry.split(':', 1)[1]
        if COOL.get(model, 0) > time.monotonic():
            continue
        t0 = time.monotonic()
        try:
            text, usage = ask(model, prompt_for(note), imgs)
        except (RuntimeError, requests.RequestException) as exc:
            print(f'vision: {model} did not answer: {str(exc)[:160]}', flush=True)
            # a model that is out of quota or overloaded rests, so the next filings go straight to the next model
            COOL[model] = time.monotonic() + (1800 if '429' in str(exc) else 300)
            continue
        return text, model, round(time.monotonic() - t0, 1), usage, note
    return None
