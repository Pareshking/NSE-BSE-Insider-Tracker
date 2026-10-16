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
import announcement_reader as ar  # noqa: E402
import announcement_sample as s  # noqa: E402
from clean_writer import read_parquet  # noqa: E402
from r2_writer import r2_client  # noqa: E402

from insiders_clean.filing_text import Cache as TextCache  # noqa: E402
from insiders_clean.text_clean import clean  # noqa: E402

HOURS = float(os.environ.get('HOURS', '6'))
EXCERPT = int(os.environ.get('EXCERPT', '3000'))
NUMBER = re.compile(r'\d[\d,]*\.?\d*')


def norm(t: str) -> str:
    return s._norm(str(t or ''))


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
    out += unit_problems(claim, quote)
    if not s.quote_found(quote, doc):
        out.append('QUOTE NOT IN TEXT')
    missing = numbers(claim) - numbers(quote)
    if missing:
        out.append(f'number(s) in the claim but not in its quote: {sorted(missing)}')
    return out


UNITS = {'crore': 'crore', 'crores': 'crore', 'cr': 'crore', 'lakh': 'lakh', 'lakhs': 'lakh', 'lac': 'lakh', 'lacs': 'lakh',
         'million': 'million', 'millions': 'million', 'mn': 'million', 'billion': 'billion', 'bn': 'billion',
         'thousand': 'thousand', 'thousands': 'thousand', 'trillion': 'trillion', 'tn': 'trillion',
         'percent': 'percent', 'per cent': 'percent', '%': 'percent'}
UNIT_RE = re.compile(r'(\d[\d,]*\.?\d*)\s*(crores?|cr\.?|lakhs?|lacs?|millions?|mn|billions?|bn|thousands?|trillion|tn|per cent|percent|%)(?![a-z])',
                     re.IGNORECASE)
CURRENCY = re.compile(r'(₹|\brs\.?|\binr\b|\busd\b|\bus\$|\$|\brupees?\b|\bdollars?\b)', re.IGNORECASE)


def amounts(text: str) -> set[tuple[str, str]]:
    """(number, unit) pairs written in `text`: 86.5 Crore -> ('86.5', 'crore'); lakh/crore/million kept apart."""
    out = set()
    for num, unit in UNIT_RE.findall(str(text or '')):
        out.add((num.strip(',.').replace(',', ''), UNITS[unit.lower().rstrip('.')]))
    return out


def currencies(text: str) -> set[str]:
    c = set()
    for m in CURRENCY.findall(str(text or '')):
        m = m.lower().rstrip('.')
        c.add('inr' if m in ('₹', 'rs', 'inr', 'rupee', 'rupees') else 'usd')
    return c


def unit_problems(claim: str, quote: str) -> list[str]:
    """A number must keep its unit and currency from the quote: 5 crore is not 50 lakh, Rs is not USD."""
    out = []
    q = amounts(quote)
    for num, unit in amounts(claim):
        if (num, unit) in q:
            continue
        same_num = sorted(u for n, u in q if n == num)
        out.append(f'UNIT: claim says {num} {unit}; the quote has ' + (f'{num} {same_num}' if same_num else
                   'that number with no unit beside it (unit may sit in a table header: check)'))
    cc, qc = currencies(claim), currencies(quote)
    if cc - qc and qc:
        out.append(f'CURRENCY: claim says {sorted(cc)}, quote says {sorted(qc)}')
    return out


def table_header(doc: str, quote, above: int = 7) -> list[str]:
    """The non-empty lines above the table row a quote is taken from (a line of three or more numbers that contains the
    quote, whole or cut short), where the period and unit headings sit."""
    q = re.sub(r'\s+', ' ', str(quote or '')).strip().casefold()
    if not q or not NUMBER.search(q):
        return []
    lines = doc.splitlines()
    for i, ln in enumerate(lines):
        flat = re.sub(r'\s+', ' ', ln).strip().casefold()
        if q in flat and len(NUMBER.findall(flat)) >= 3:
            return [re.sub(r'\s{2,}', '  ', x).strip()[:170] for x in lines[max(0, i - above):i] if x.strip()]
    return []


def revalidate(r: dict, doc: str) -> list[str]:
    """Run today's rules over the stored card and say which shown items they would now hold back."""
    fields = [{'name': f.get('name'), 'value': f.get('value'), 'quote': f.get('quote')} for f in load(r.get('fields'), [])]
    for f in load(r.get('fields'), []):
        if f.get('name') == 'amount' and f.get('unit'):
            fields.append({'name': 'amount_unit', 'value': f.get('unit'), 'quote': None})
    metrics = [{k: m.get(k) for k in ('label', 'period', 'value', 'unit', 'quote')} for m in load(r.get('metrics'), [])]
    head, points = load(r.get('headline'), {}) or {}, load(r.get('points'), [])
    out = {'fields': fields, 'metrics': metrics, 'headline': head,
           'points': [{'text': p.get('text'), 'quote': p.get('quote')} for p in points]}
    _, nf, nm = ar.validate(out, doc)
    new_head, new_points = ar.card_words(out, doc, nf, nm)
    was = {('f', f.get('name'), str(f.get('value'))): f.get('shown') for f in load(r.get('fields'), [])}
    lines = []
    for f in nf:
        if not f['shown'] and was.get(('f', f['name'], str(f['value']))):
            lines.append(f"field {f['name']} = {f['value']} now held: {f['reason']}")
    old_m = {(m.get('label'), m.get('period'), str(m.get('value'))): m.get('shown') for m in load(r.get('metrics'), [])}
    for m in nm:
        if not m['shown'] and old_m.get((m['label'], m['period'], str(m['value']))):
            lines.append(f"metric {m['label']} [{m['period']}] = {m['value']} {m['unit']} now held: {m['reason']}")
    if head.get('shown') and new_head and not new_head.get('shown'):
        lines.append(f"headline now held: {new_head.get('reason')}: {head.get('text')}")
    for old, new in zip(points, new_points or []):
        if old.get('shown') and new and not new.get('shown'):
            lines.append(f"point now held: {new.get('reason')}: {old.get('text')}")
    return lines


def excerpt(text: str, quotes, head: int = None, around: int = 700) -> str:
    """The opening of the filing plus a window around every quote shown from it (merged), so that a long filing is
    never cut off before the words a card rests on. A short filing is given whole."""
    head = EXCERPT if head is None else head
    if len(text) <= 3 * EXCERPT:
        return text
    spans = [(0, head)]
    flat = re.sub(r'\s+', ' ', text)
    # positions in `flat` map back approximately through the same collapse; windows are taken from `flat`
    for q in quotes:
        key = re.sub(r'\s+', ' ', str(q or '')).strip()[:60]
        at = flat.find(key) if len(key) >= 12 else -1
        if at >= 0:
            spans.append((max(0, at - around), at + len(key) + around))
    spans.sort()
    merged = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
        else:
            merged.append((a, b))
    return '\n[...]\n'.join(flat[a:b] for a, b in merged)


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
    text_cache = TextCache(r2)
    for r in df.to_dict('records'):
        url = r.get('content_url') or r.get('file_url')
        cached = text_cache(r) if text_cache is not None and url == r.get('file_url') else None
        if cached is not None and str(cached.get('text') or '').strip():   # the very text the reader was given
            doc, notes = str(cached['text']), ['from the text cache']
        else:
            try:
                doc, notes = s.text_of(s.download(url))
            except Exception as exc:  # noqa: BLE001
                doc, notes = '', [f'download failed: {type(exc).__name__}: {exc}']
        flags = []
        print(f"### {r['exchange']} {r.get('symbol')} | {r.get('subject')} | {r.get('company')}")
        print(f"- event_id `{r.get('event_id')}`")
        print(f"- category **{r.get('category')}**; read by {r.get('reader')}; cross-check {r.get('second_reader')} "
              f"said **{r.get('second_category')}**; agreed {r.get('agreed')}; shown {r.get('shown')}, held {r.get('held')}")
        print(f"- filing: {r.get('file_url')} ({len(doc):,} characters; {'; '.join(notes)[:120]})")
        head = load(r.get('headline'), {})
        if head and head.get('shown'):
            print(f"- HEADLINE: {head.get('text')}\n  - quote: \"{head.get('quote')}\"")
            flags += problems(doc, head.get('text'), head.get('quote'))
        if head and not head.get('shown'):
            print(f"- HELD HEADLINE ({head.get('reason')}): {head.get('text')}\n  - quote: \"{head.get('quote')}\"")
            sub = head.get('subtitle') or {}
        elif head and (head.get('subtitle') or {}).get('text'):
            sub = head['subtitle']
            print(f"- SUBTITLE{'' if sub.get('shown') else ' (held: ' + str(sub.get('reason')) + ')'}: {sub.get('text')}\n  - quote: \"{sub.get('quote')}\"")
        for p in load(r.get('points'), []):
            if p.get('shown'):
                print(f"- POINT: {p.get('text')}\n  - quote: \"{p.get('quote')}\"")
                flags += problems(doc, p.get('text'), p.get('quote'))
        for f in load(r.get('fields'), []):
            if f.get('shown'):
                unit = f" {f.get('unit')}" if f.get('unit') else ''
                cur = f" [{f.get('currency')}]" if f.get('currency') else ''
                print(f"- FIELD {f.get('name')} = {f.get('value')}{unit}{cur}\n  - quote: \"{f.get('quote')}\"")
                if not s.quote_found(f.get('quote'), doc):
                    flags.append(f"field {f.get('name')}: QUOTE NOT IN TEXT")
        for m in load(r.get('metrics'), []):
            if m.get('shown'):
                print(f"- METRIC {m.get('label')} [{m.get('period')}] = {m.get('value')} {m.get('unit')}\n  - quote: \"{m.get('quote')}\"")
                if not s.quote_found(m.get('quote'), doc):
                    flags.append(f"metric {m.get('label')}: QUOTE NOT IN TEXT")
                header = table_header(doc, m.get('quote'))
                if header:
                    print('  - TABLE HEADING above the row (check period and unit):')
                    for h in header:
                        print(f'    | {h}')
                if m.get('previous') not in (None, ''):
                    print(f"  - PREVIOUS [{m.get('previous_period')}] = {m.get('previous')} (change {m.get('change_pct')}%)\n"
                          f"    - previous quote: \"{m.get('previous_quote')}\"")
                mu = str(m.get('unit') or '').lower()
                qa = amounts(m.get('quote'))
                if mu in UNITS and mu and UNITS[mu] not in {u for _, u in qa}:
                    flags.append(f"metric {m.get('label')}: unit '{m.get('unit')}' is not beside a number in its quote: "
                                 f"check the table header")
                if mu in ('rupees', 'rs', '₹') and currencies(m.get('quote')) == {'usd'}:
                    flags.append(f"metric {m.get('label')}: unit is rupees but the quote is in dollars")
        changed = revalidate(r, doc) if doc else []
        for line in changed:
            print(f'- **NOW HELD BY CURRENT RULES:** {line}')
        held = [x for k in ('points', 'fields', 'metrics') for x in load(r.get(k), []) if not x.get('shown')]
        for x in held:
            print(f"- held back ({x.get('reason')}): {str(x.get('text') or x.get('value') or x.get('label'))[:140]}")
            if x.get('quote'):
                print(f"  - held quote: \"{str(x.get('quote'))[:400]}\"")
        if flags:
            flagged += 1
            print('- **AUDIT FLAGS:** ' + '; '.join(flags))
        cleaned, _ = clean(doc, r.get('subject'))
        if not doc.strip():
            print('- **AUDIT FLAGS:** the audit could not get the filing text, so nothing of this card can be checked here')
        quotes = [head.get('quote')] if head else []
        quotes += [p.get('quote') for p in load(r.get('points'), []) if p.get('shown')]
        quotes += [f.get('quote') for f in load(r.get('fields'), []) if f.get('shown')]
        quotes += [m.get('quote') for m in load(r.get('metrics'), []) if m.get('shown')]
        print(f"\n<details><summary>the filing's text</summary>\n\n```\n{excerpt(cleaned, quotes)}\n```\n</details>\n")
    print(f'\n**Independent re-check: {flagged} of {len(df)} cards have a flag.**')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
