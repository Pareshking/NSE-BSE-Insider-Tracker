"""Is each AI model of the announcement reader answering, or at its limit?

One tiny request per model in scripts/announcement_readers.txt ("Reply with OK", a few tokens), printing the HTTP
status, the time taken, the start of the answer and any rate-limit headers the provider sends. Touches nothing
else: no filings, no R2, no usage ledger (these calls are not in it). Keys come from the environment, as in the
reader; a key that is missing is reported, not guessed.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
BASES = {'nvidia': ('https://integrate.api.nvidia.com/v1', 'NVIDIA_API_KEY'),
         'zai': ('https://api.z.ai/api/paas/v4', 'ZAI_API_KEY'),
         'groq': ('https://api.groq.com/openai/v1', 'GROQ_API_KEY'),
         'gemini': ('https://generativelanguage.googleapis.com/v1beta', 'GEMINI_API_KEY')}
PROMPT = 'Reply with the single word OK.'
LIMIT_HEADERS = ('ratelimit', 'retry-after', 'quota')


def models() -> list[tuple[str, str]]:
    """The reader's models, then any candidates in ai_health_candidates.txt (same line format)."""
    out = []
    files = [HERE / 'announcement_readers.txt', HERE / 'ai_health_candidates.txt']
    lines = [ln for f in files if f.exists() for ln in f.read_text(encoding='utf-8').splitlines()]
    for line in lines:
        line = line.split('#', 1)[0].strip()
        if ':' not in line:
            continue
        for entry in line.split(':', 1)[1].split(','):
            prov, _, model = entry.strip().partition(':')
            if model:
                out.append((prov, model))
    return out


def ask(prov: str, model: str, key: str) -> requests.Response:
    base = BASES[prov][0]
    if prov == 'gemini':
        return requests.post(f'{base}/models/{model}:generateContent', headers={'x-goog-api-key': key}, timeout=60,
                             json={'contents': [{'parts': [{'text': PROMPT}]}],
                                   'generationConfig': {'maxOutputTokens': 256}})
    return requests.post(f'{base}/chat/completions', headers={'Authorization': f'Bearer {key}'}, timeout=60,
                         json={'model': model, 'messages': [{'role': 'user', 'content': PROMPT}], 'max_tokens': 256})


def answer(prov: str, r: requests.Response) -> str:
    try:
        d = r.json()
        if prov == 'gemini':
            return ''.join(p.get('text', '') for p in d['candidates'][0]['content']['parts'])
        return d['choices'][0]['message'].get('content') or ''
    except Exception:   # an error body: show what the provider said
        return r.text


def main() -> int:
    rows, bad = [], 0
    for prov, model in models():
        key = os.environ.get(BASES.get(prov, ('', ''))[1] or '')
        if prov not in BASES or not key:
            rows.append((prov, model, 'no key', '', '', ''))
            bad += 1
            continue
        t = time.monotonic()
        try:
            r = ask(prov, model, key)
        except requests.RequestException as e:
            rows.append((prov, model, 'error', f'{time.monotonic() - t:.1f}s', type(e).__name__, ''))
            bad += 1
            continue
        took = f'{time.monotonic() - t:.1f}s'
        limits = '; '.join(f'{k}={v}' for k, v in r.headers.items() if any(h in k.lower() for h in LIMIT_HEADERS))
        text = ' '.join(answer(prov, r).split())[:120].replace('|', '/')
        rows.append((prov, model, str(r.status_code), took, text, limits))
        bad += r.status_code != 200
    out = ['### AI models: one tiny request each', '',
           '| provider | model | HTTP | time | answer (start) | rate-limit headers |', '|---|---|---|---|---|---|']
    out += [f'| {p} | `{m}` | {s} | {t} | {a} | {lim} |' for p, m, s, t, a, lim in rows]
    out += ['', f'{len(rows) - bad} of {len(rows)} answered with HTTP 200.']
    text = '\n'.join(out) + '\n'
    print(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as f:
            f.write(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
