"""Card audit (read-only): every filing the reader read in the last N hours, its card next to the filing's own text.

For each read filing (status 'read' in clean/current/announcement_reads.parquet, read_at within the last N hours,
default 6) this prints the filing's subject, the category each reader gave, and every shown headline, point, field and
metric with its quote, then the start of the filing's text (cleaned) so the claim can be compared with the filing by
eye. It also re-checks, independently of the reader, that every shown quote is in the text (whitespace-normalised)
and that every number in a shown claim is in its quote. Writes nothing to R2. Markdown to stdout.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import announcement_sample as s  # noqa: E402
from clean_writer import read_parquet  # noqa: E402
from r2_writer import r2_client  # noqa: E402

from insiders_clean.text_clean import clean  # noqa: E402

HOURS = float(os.environ.get('HOURS', '6'))
EXCERPT = int(os.environ.get('EXCERPT', '2200'))
NUMBER = re.compile(r'\d[\d,]*\.?\d*')


def norm(t: str) -> str:
    return re.sub(r'\s+', ' ', str(t or '')).strip().casefold()


def load(v, default):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return default
    return default if v is None or (isinstance(v, float) and pd.isna(v)) else v


def numbers(t: str) -> set[str]:
    return {n.strip(',.').replace(',', '') for n in NUMBER.findall(str(t or '')) if re.search(r'\d', n)}


def problems(doc: str, claim: str, quote: str) -> list[str]:
    out = []
    if norm(quote) not in norm(doc):
        out.append('QUOTE NOT IN TEXT')
    missing = numbers(claim) - numbers(quote)
    if missing:
        out.append(f'number(s) in the claim but not in its quote: {sorted(missing)}')
    return out


def main() -> int:
    r2 = r2_client()
    df = read_parquet(r2, 'clean/current/announcement_reads.parquet')
    if df is None or df.empty:
        print('no reads table')
        return 1
    since = datetime.now(timezone.utc) - timedelta(hours=HOURS)
    df = df[df['status'] == 'read'].copy()
    df['_t'] = pd.to_datetime(df['read_at'], utc=True, errors='coerce')
    df = df[df['_t'] >= since].sort_values('_t')
    print(f'## Card audit: {len(df)} filings read in the last {HOURS:g} hours\n')
    flagged = 0
    for r in df.to_dict('records'):
        url = r.get('content_url') or r.get('file_url')
        try:
            doc, notes = s.text_of(s.download(url))
        except Exception as exc:  # noqa: BLE001
            doc, notes = '', [f'download failed: {type(exc).__name__}: {exc}']
        flags = []
        print(f"### {r['exchange']} {r.get('symbol')} | {r.get('subject')} | {r.get('company')}")
        print(f"- category **{r.get('category')}**; read by {r.get('reader')}; cross-check {r.get('second_reader')} "
              f"said **{r.get('second_category')}**; agreed {r.get('agreed')}; shown {r.get('shown')}, held {r.get('held')}")
        print(f"- filing: {r.get('file_url')} ({len(doc):,} characters; {'; '.join(notes)[:120]})")
        head = load(r.get('headline'), {})
        if head and head.get('shown'):
            print(f"- HEADLINE: {head.get('text')}\n  - quote: \"{head.get('quote')}\"")
            flags += problems(doc, head.get('text'), head.get('quote'))
        for p in load(r.get('points'), []):
            if p.get('shown'):
                print(f"- POINT: {p.get('text')}\n  - quote: \"{p.get('quote')}\"")
                flags += problems(doc, p.get('text'), p.get('quote'))
        for f in load(r.get('fields'), []):
            if f.get('shown'):
                print(f"- FIELD {f.get('name')} = {f.get('value')}\n  - quote: \"{f.get('quote')}\"")
                if norm(f.get('quote')) not in norm(doc):
                    flags.append(f"field {f.get('name')}: QUOTE NOT IN TEXT")
        for m in load(r.get('metrics'), []):
            if m.get('shown'):
                print(f"- METRIC {m.get('label')} [{m.get('period')}] = {m.get('value')} {m.get('unit')}\n  - quote: \"{m.get('quote')}\"")
                if norm(m.get('quote')) not in norm(doc):
                    flags.append(f"metric {m.get('label')}: QUOTE NOT IN TEXT")
        held = [x for k in ('points', 'fields', 'metrics') for x in load(r.get(k), []) if not x.get('shown')]
        for x in held:
            print(f"- held back ({x.get('reason')}): {str(x.get('text') or x.get('value') or x.get('label'))[:140]}")
        if flags:
            flagged += 1
            print('- **AUDIT FLAGS:** ' + '; '.join(flags))
        cleaned, _ = clean(doc, r.get('subject'))
        print(f"\n<details><summary>the filing's text</summary>\n\n```\n{cleaned[:EXCERPT]}\n```\n</details>\n")
    print(f'\n**Independent re-check: {flagged} of {len(df)} cards have a flag.**')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
