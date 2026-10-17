"""Vision test on a few filings (read-only, nothing saved): page triage, then the chosen pages as images to a vision model.

1. Triage (no AI): every page is scored from its own text (pdftotext). Page 1 always goes. A page goes when it carries
   figures or the words that make a card (shares, %, Rs, crore, revenue, profit, rating, pledge, price, before/after) and is not
   only a disclaimer / signature / address page. A page with no text layer (a scan) goes too: the text cannot judge it.
   At most MAX_PAGES go; pages left out are named with the reason (CLAUDE.md rule 8: a filing is read in full or marked not read).
2. The chosen pages are drawn with pdftoppm and sent as PNGs to each model in VISION_MODELS ("provider:model, ...").
3. Each answer is checked against the pdftotext text: a quote the text does not contain is counted as not found.
Markdown to stdout and $GITHUB_STEP_SUMMARY; images and answers are written under OUT_DIR for the artifact.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pandas as pd
import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from r2_writer import BUCKET, r2_client  # noqa: E402
import announcement_sample as sample  # noqa: E402

MAX_PAGES = int(os.environ.get('MAX_PAGES', '6'))
COMPARE = os.environ.get('COMPARE', '') == '1'   # 1: every model reads every filing; else the first that answers
DPI = int(os.environ.get('DPI', '130'))
OUT_DIR = Path(os.environ.get('OUT_DIR', 'vision_out'))
BASES = {'zai': 'https://api.z.ai/api/paas/v4', 'nvidia': 'https://integrate.api.nvidia.com/v1'}
KEYS = {'zai': 'ZAI_API_KEY', 'nvidia': 'NVIDIA_API_KEY', 'gemini': 'GEMINI_API_KEY'}
KEY_TERMS = re.compile(r'\b(?:shares?|warrants?|%|per\s*cent|rs\.?|inr|₹|crore|cr\.?|lakh|million|revenue|sales|profit|income|rating|'
                       r'pledge\w*|encumb\w*|price|consideration|before|after|acquisition|allot\w*|capacity|order|facility|amount)\b', re.I)
BOILER = re.compile(r'yours\s+faithfully|thanking\s+you|for\s+and\s+on\s+behalf|company\s+secretary|disclaimer|registered\s+office|'
                    r'cin\s*[:\-]|website|email|e-mail|telephone|tel\.?\s*:', re.I)
NUMBER = re.compile(r'\d[\d,]*(?:\.\d+)?')

PROMPT = ('You are reading the pages of one stock-exchange filing by an Indian listed company (pages {pages} of {total}). '
          'Return ONLY JSON: {{"category": short snake_case kind of event, "headline": one plain sentence an investor needs, '
          'with the key number(s) and unit exactly as printed, "facts": [{{"name": ..., "value": ..., "quote": words copied exactly '
          'from the page, "page": n}}], "unclear": [things on the pages you could not read or are unsure of]}}. '
          'Copy numbers exactly with their unit (Rs, crore, lakh, %, shares). Do not guess; put anything unreadable in "unclear".')


def pages_of(data: bytes) -> list[str]:
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / 'f.pdf'
        src.write_bytes(data)
        out = subprocess.run(['pdftotext', '-layout', str(src), '-'], capture_output=True, timeout=180, check=False)
    pages = out.stdout.decode('utf-8', errors='replace').split('\f')
    if pages and not pages[-1].strip():
        pages = pages[:-1]
    return pages


def text_modes(data: bytes) -> dict[str, str]:
    """The same PDF as text in three ways: pdftotext -layout (what the reader sends now), pdftotext in reading order
    (no layout padding), and PyMuPDF blocks sorted top-to-bottom, left-to-right."""
    out = {}
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / 'f.pdf'
        src.write_bytes(data)
        for name, args in (('layout', ['-layout']), ('reading', [])):
            r = subprocess.run(['pdftotext', *args, str(src), '-'], capture_output=True, timeout=180, check=False)
            out[name] = r.stdout.decode('utf-8', errors='replace')
        try:
            import pymupdf as fitz  # PyMuPDF
            with fitz.open(str(src)) as pdf:
                out['sorted'] = '\f'.join(pg.get_text('text', sort=True) for pg in pdf)   # PyMuPDF's own reading-order sort (owner's hint), no AI
                out['blocks'] = '\f'.join('\n'.join(b[4] for b in sorted(pg.get_text('blocks'), key=lambda b: (round(b[1] / 8), b[0]))
                                                    if b[6] == 0) for pg in pdf)
        except Exception as exc:  # noqa: BLE001
            out['blocks'] = ''
            log_note(f'PyMuPDF unavailable: {exc}')
    if os.environ.get('OCR', '') == '1':
        out['ocr'] = ocr_text(data)
    return out


def ocr_text(data: bytes, max_pages: int = 8, dpi: int = 200) -> str:
    """OCR of the first pages with tesseract (the text a scan or a garbled text layer does not give): pages joined by form feeds."""
    out = []
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / 'f.pdf'
        src.write_bytes(data)
        subprocess.run(['pdftoppm', '-r', str(dpi), '-png', '-f', '1', '-l', str(max_pages), str(src), str(Path(d) / 'p')],
                       capture_output=True, timeout=300, check=False)
        for png in sorted(Path(d).glob('p-*.png')):
            r = subprocess.run(['tesseract', str(png), '-', '--psm', '6'], capture_output=True, timeout=180, check=False)
            out.append(r.stdout.decode('utf-8', errors='replace'))
    return '\f'.join(out)


def log_note(msg: str) -> None:
    print('NOTE', msg, flush=True)


def triage(pages: list[str]) -> tuple[list[int], dict[int, str]]:
    """(pages to send, 1-based; why each page was sent or left out)."""
    why, score = {}, {}
    for i, p in enumerate(pages, 1):
        n = len(re.sub(r'\s', '', p))
        nums = len(NUMBER.findall(p))
        terms = len(KEY_TERMS.findall(p))
        if n < 80:
            score[i], why[i] = 100, 'no text layer: a scan, the text cannot judge it'
        elif i == 1:
            score[i], why[i] = 1000, 'first page'
        elif BOILER.search(p) and nums < 8 and terms < 6:
            score[i], why[i] = -1, 'left out: signature / disclaimer / address page (few figures)'
        elif (nums >= 6 and terms >= 4) or nums >= 30:   # a table of figures continues on a page with few words (Paushak p3, Jindal Saw p5/7/9)
            score[i], why[i] = nums + terms, f'sent: {nums} numbers, {terms} key words'
        else:
            score[i], why[i] = -1, f'left out: {nums} numbers, {terms} key words'
    pick = sorted((i for i in score if score[i] > 0), key=lambda i: -score[i])[:MAX_PAGES]
    for i in score:
        if score[i] > 0 and i not in pick:
            why[i] = 'left out: over the page limit (lower score)'
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


LAST_USAGE: dict = {}


def ask(entry: str, prompt: str, images: dict[int, bytes]) -> tuple[str, float, str]:
    """(answer text, seconds, error). One request with all chosen pages."""
    prov, model = entry.split(':', 1)
    key = os.environ.get(KEYS[prov], '').strip()
    if not key:
        return '', 0, f'{KEYS[prov]} not set'
    t0 = time.monotonic()
    try:
        if prov == 'gemini':
            parts = [{'text': prompt}] + [{'inlineData': {'mimeType': 'image/png', 'data': base64.b64encode(b).decode()}} for b in images.values()]
            r = requests.post(f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',
                              headers={'x-goog-api-key': key}, timeout=120,
                              json={'contents': [{'role': 'user', 'parts': parts}], 'generationConfig': {'temperature': 0, 'responseMimeType': 'application/json'}})
            if r.status_code != 200:
                return '', time.monotonic() - t0, f'HTTP {r.status_code}: {r.text[:200]}'
            j = r.json()
            u = j.get('usageMetadata') or {}
            LAST_USAGE.update(prompt=u.get('promptTokenCount'), out=u.get('candidatesTokenCount'), images=len(images))
            return ''.join(p.get('text', '') for p in j['candidates'][0]['content']['parts']), time.monotonic() - t0, ''
        content = [{'type': 'text', 'text': prompt}] + [{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + base64.b64encode(b).decode()}} for b in images.values()]
        r = requests.post(f'{BASES[prov]}/chat/completions', headers={'Authorization': f'Bearer {key}'}, timeout=150,
                          json={'model': model, 'temperature': 0, 'max_tokens': 3000, 'messages': [{'role': 'user', 'content': content}]})
        if r.status_code != 200:
            return '', time.monotonic() - t0, f'HTTP {r.status_code}: {r.text[:200]}'
        u = r.json().get('usage') or {}
        LAST_USAGE.update(prompt=u.get('prompt_tokens'), out=u.get('completion_tokens'), images=len(images))
        return r.json()['choices'][0]['message']['content'] or '', time.monotonic() - t0, ''
    except Exception as exc:  # noqa: BLE001 -- a failing model is a finding
        return '', time.monotonic() - t0, f'{type(exc).__name__}: {exc}'[:200]


def squash(t: str) -> str:
    return re.sub(r'[\s"\'“”‘’]+', '', str(t)).lower()


def check(answer: str, doc: str) -> tuple[int, int, dict | None]:
    """(quotes found in the pdftotext text, quotes in all, parsed JSON)."""
    m = re.search(r'\{.*\}', answer, re.S)
    try:
        j = json.loads(m.group(0)) if m else None
    except ValueError:
        j = None
    if not j:
        return 0, 0, None
    d = squash(doc)
    qs = [str(f.get('quote', '')) for f in j.get('facts', []) if isinstance(f, dict) and f.get('quote')]
    return sum(1 for q in qs if squash(q) and squash(q) in d), len(qs), j


def list_models() -> list[str]:
    """Model ids each key can see (the ids the owner named - Gemini 3.6/3.7/3.8 Flash, GLM-4.6V, Nemotron VL - are checked here, not assumed)."""
    out = []
    if os.environ.get('GEMINI_API_KEY'):
        r = requests.get('https://generativelanguage.googleapis.com/v1beta/models', params={'pageSize': 1000},
                         headers={'x-goog-api-key': os.environ['GEMINI_API_KEY']}, timeout=60)
        ids = sorted(m['name'].removeprefix('models/') for m in r.json().get('models', []) if 'generateContent' in m.get('supportedGenerationMethods', []))
        out.append(f'gemini (HTTP {r.status_code}): ' + ', '.join(i for i in ids if 'gemini' in i))
    for prov in ('zai', 'nvidia'):
        key = os.environ.get(KEYS[prov], '').strip()
        if key:
            r = requests.get(f'{BASES[prov]}/models', headers={'Authorization': f'Bearer {key}'}, timeout=60)
            ids = sorted(m.get('id', '') for m in (r.json().get('data', []) if r.ok else []))
            out.append(f'{prov} (HTTP {r.status_code}): ' + ', '.join(ids)[:3000])
    return out


def main() -> int:
    for line in list_models():
        print('MODELS', line, flush=True)
    ids = [ln.split('#')[0].strip() for ln in Path(sys.argv[1]).read_text().splitlines() if ln.split('#')[0].strip()]
    if Path(sys.argv[1]).read_text().lstrip().startswith('# nomodel'):
        os.environ['VISION_MODELS'] = ''   # pages only: draw and keep the images, call no model
    models = [m.strip() for m in os.environ.get('VISION_MODELS', 'gemini:gemini-3.5-flash').split(',') if m.strip()]
    r2 = r2_client()
    rows = []
    for ex in ('nse', 'bse'):
        keys = sorted(o['Key'] for p in r2.get_paginator('list_objects_v2').paginate(Bucket=BUCKET, Prefix=f'archive/announcements/{ex}/')
                      for o in p.get('Contents', []) if o['Key'].endswith('.parquet'))
        for k in keys:
            df = pd.read_parquet(io.BytesIO(r2.get_object(Bucket=BUCKET, Key=k)['Body'].read()),
                                 columns=['event_id', 'file_url', 'subject'])
            rows.append(df[df['event_id'].isin(ids)])
    allr = pd.concat(rows).drop_duplicates('event_id') if rows else pd.DataFrame()
    urls = Path(HERE / 'vision_urls.txt')   # filings too new for the archive: id <TAB> file_url <TAB> subject
    if urls.exists():
        extra = pd.DataFrame([dict(zip(('event_id', 'file_url', 'subject'), ln.split('\t'))) for ln in urls.read_text().splitlines() if ln.count('\t') >= 2])
        if len(extra):
            allr = pd.concat([allr, extra]).drop_duplicates('event_id') if len(allr) else extra
    OUT_DIR.mkdir(exist_ok=True)
    md = ['## Vision test (page triage + page images)', '', f'models: {", ".join(models)}; {DPI} dpi; at most {MAX_PAGES} pages a filing', '']
    for _, f in allr.iterrows():
        title = f'{f["event_id"]} | {str(f["subject"])[:60]}'
        md += [f'### {title}']
        try:
            data = sample.download(f['file_url'])
        except Exception as exc:  # noqa: BLE001
            md += [f'download failed: {exc}', '']
            continue
        if data[:4] != b'%PDF':
            md += ['not a PDF (a ZIP or other): not tested', '']
            continue
        pages = pages_of(data)
        pick, why = triage(pages)
        md += [f'{len(pages)} pages; sent {pick}', ''] + [f'- p{i}: {why[i]}' for i in sorted(why)] + ['']
        imgs = render(data, pick)
        for p, b in imgs.items():
            (OUT_DIR / f'{str(f["event_id"]).replace(":", "_")}_p{p}.png').write_bytes(b)
        prompt = PROMPT.format(pages=', '.join(map(str, imgs)), total=len(pages))
        doc = '\n'.join(pages)
        tmodes = text_modes(data)
        for mname, mtxt in tmodes.items():   # the table pages as each mode shows them, for reading by eye
            (OUT_DIR / f'{str(f["event_id"]).replace(":", "_")}_text_{mname}.txt').write_text('\n=====PAGE=====\n'.join(mtxt.split('\f')))
        answered = False
        for entry in models:
            if answered and not COMPARE:
                break   # models are a fallback list: the first that answers reads the filing (each model has its own quota)
            for attempt in range(2):   # 429 / 503 'overloaded': one short wait, then the next model
                ans, secs, err = ask(entry, prompt, imgs)
                if not (err.startswith('HTTP 429') or err.startswith('HTTP 503')):
                    break
                time.sleep(10)
            answered = answered or bool(ans)
            found, n, j = check(ans, doc)
            modes = {k: check(ans, v)[0] for k, v in tmodes.items()} if ans else {}
            usage = dict(LAST_USAGE) if ans else {}
            LAST_USAGE.clear()
            (OUT_DIR / f'{str(f["event_id"]).replace(":", "_")}_{entry.replace(":", "_").replace("/", "_")}.txt').write_text(ans or err)
            md += [f'**{entry}** ({secs:.0f} s): ' + (f'ERROR {err}' if err else f'quotes found in the PDF text {found}/{n}; by text mode {modes}; tokens {usage}; 1 request, {len(imgs)} images')]
            if j:
                md += [f'- headline: {j.get("headline")}', f'- category: {j.get("category")}',
                       *[f'- {x.get("name")}: {x.get("value")}' for x in j.get('facts', [])[:12] if isinstance(x, dict)],
                       f'- unclear: {j.get("unclear")}']
            elif ans:
                md += [f'- not valid JSON: {ans[:300]}']
            md += ['']
        print('\n'.join(md[-40:]), flush=True)
    out = '\n'.join(md)
    print(out)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        Path(os.environ['GITHUB_STEP_SUMMARY']).write_text(out)
    (OUT_DIR / 'summary.md').write_text(out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
