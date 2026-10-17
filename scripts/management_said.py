"""Earnings-call transcripts into management's own words, saved per company for the next quarter's cards (owner, 18 Oct 2026).

A transcript filing is read in sections. A fact is kept only when its exact quote is in the transcript (code check) and every number of
its statement is in its quote. Saved to archive/management_said/{ISIN}.json (the latest four calls); the site pairs the forward-looking
facts of the last call with the figures of the next results (insiders_clean/said.py). No number comes from a model: the figure of a fact
is the one in its quote."""
from __future__ import annotations

import json
import re
import time
from datetime import date

import pandas as pd

import announcement_sample as s
from insiders_clean import said as said_rules

PREFIX = 'archive/management_said/'
SECTION = 13_000
KEEP_CALLS = 4
KEEP_FACTS = 14
SUBJECT = re.compile(r'con(?:ference|\.)?\s*call|analyst|investor meet', re.IGNORECASE)
TRANSCRIPT_HEAD = re.compile(r'transcript', re.IGNORECASE)
HELD_ON = re.compile(r'(?:held|conducted)\s+on\s+([A-Z][a-z]+\.?\s+\d{1,2},?\s+\d{4}|\d{1,2}(?:st|nd|rd|th)?\s+[A-Z][a-z]+,?\s+\d{4})')
TOPICS = 'guidance or outlook, demand, deal wins or order book, margins, headcount or attrition, pricing, capital allocation, risks'


def is_transcript(subject, doc) -> bool:
    """A call transcript, not the notice of a call or its audio link: the subject names a call and the filing's opening says transcript,
    and it is long enough to hold a conversation."""
    return bool(SUBJECT.search(str(subject or ''))) and len(str(doc or '')) >= 15_000 and bool(TRANSCRIPT_HEAD.search(str(doc)[:2500]))


def call_date(doc, filed: str) -> str:
    """The day of the call as the filing says ("held on July 16, 2026"), else the filing date."""
    m = HELD_ON.search(str(doc)[:3000])
    if m:
        for fmt in ('%B %d, %Y', '%B %d %Y', '%b %d, %Y', '%d %B, %Y', '%d %B %Y'):
            try:
                text = re.sub(r'(\d)(?:st|nd|rd|th)', r'\1', m.group(1).replace('.', ''))
                return time.strftime('%Y-%m-%d', time.strptime(text, fmt))
            except ValueError:
                continue
    return str(filed)[:10]


def sections(text: str) -> list[str]:
    out, i = [], 0
    while i < len(text):
        j = min(len(text), i + SECTION)
        if j < len(text):
            k = text.rfind('. ', i + SECTION // 2, j)
            j = k + 1 if k > 0 else j
        out.append(text[i:j])
        i = j
    return out


def fact_prompt(company: str, filed: str, section: str, k: int, n: int) -> str:
    return (f'This is part {k} of {n} of the transcript of {company}\'s earnings conference call, filed {filed}. Extract up to 8 statements MADE BY '
            f'THE COMPANY\'S MANAGEMENT that an investor will want to remember when the next quarter\'s results come out: {TOPICS}. '
            'A question from an analyst is not a fact. Return only JSON: {"facts": [{"topic": one of guidance, demand, deals, margins, people, '
            'pricing, capital, risk; "statement": one plain sentence of at most 200 characters that repeats only numbers found in the quote; '
            '"speaker": the manager\'s name as the transcript gives it, or null; "quote": the exact words of the transcript, at most 300 '
            'characters, copied character for character}]}. Leave a statement out rather than paraphrase a number.\n\n=== TRANSCRIPT ===\n' + section)


def digits(t) -> set[str]:
    return {x.replace(',', '') for x in re.findall(r'\d[\d,]*(?:\.\d+)?', str(t or ''))}


def verified_facts(lanes, company: str, filed: str, doc: str, log=print) -> tuple[list[dict], dict]:
    """(facts that passed both checks, counts). A section no lane can answer is counted and the rest is still used."""
    parts = sections(doc)
    kept, count = [], {'sections': len(parts), 'unanswered': 0, 'quote_not_in_transcript': 0, 'number_not_in_quote': 0}
    for k, part in enumerate(parts, 1):
        raw = None
        for lane in lanes.values():
            try:
                text, used, secs = lane.read(fact_prompt(company, filed, part, k, len(parts)))
                raw = s.parse_json(text)
            except Exception as exc:  # noqa: BLE001 -- one lane failing never stops the others
                log(f'management_said: {lane.name}: {type(exc).__name__}: {str(exc)[:100]}')
                continue
            if isinstance(raw, dict):
                break
        if not isinstance(raw, dict):
            count['unanswered'] += 1
            continue
        for f in raw.get('facts') or []:
            if not isinstance(f, dict) or not f.get('quote') or not f.get('statement'):
                continue
            if not s.quote_found(f['quote'], doc):
                count['quote_not_in_transcript'] += 1
            elif not digits(f['statement']) <= digits(f['quote']):
                count['number_not_in_quote'] += 1
            else:
                kept.append({k2: f.get(k2) for k2 in ('topic', 'statement', 'speaker', 'quote')})
    return kept, count


def choose(facts: list[dict]) -> list[dict]:
    """The facts worth keeping: the forward-looking ones first (they are what a later result is set beside), then the rest, once each."""
    fwd = said_rules.forward_facts(facts)
    seen, out = set(), []
    for f in fwd + [f for f in facts if f not in fwd]:
        key = re.sub(r'\W+', ' ', str(f.get('statement'))).lower()
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out[:KEEP_FACTS]


def read_doc(r2, isin: str) -> dict:
    from clean_writer import get
    body = get(r2, f'{PREFIX}{isin}.json')
    try:
        return json.loads(body) if body else {}
    except ValueError:
        return {}


def save_call(r2, isin: str, company: str, row: dict, doc: str, facts: list[dict], counts: dict) -> dict:
    from clean_writer import put
    cur = read_doc(r2, isin)
    calls = [c for c in cur.get('calls') or [] if c.get('event_id') != row['event_id']]
    calls.append({'event_id': row['event_id'], 'filed': str(row.get('broadcast_date'))[:10], 'call_date': call_date(doc, row.get('broadcast_date')),
                  'source_url': row.get('file_url'), 'facts': choose(facts), 'facts_total': len(facts), 'counts': counts,
                  'saved_at': pd.Timestamp.now(tz='UTC').isoformat()})
    calls = sorted(calls, key=lambda c: c['call_date'])[-KEEP_CALLS:]
    out = {'isin': isin, 'company': company, 'calls': calls}
    put(r2, f'{PREFIX}{isin}.json', json.dumps(out, ensure_ascii=False).encode('utf-8'), 'application/json')
    return out


def transcript_rows(r2, months: list[tuple[int, int]]) -> pd.DataFrame:
    """The archive rows (NSE and BSE) of the given (year, month)s whose subject names a call, newest first."""
    from clean_writer import read_parquet
    frames = []
    for ex in ('nse', 'bse'):
        for y, m in months:
            df = read_parquet(r2, f'archive/announcements/{ex}/year={y}/month={m:02d}.parquet')
            if df is not None and not df.empty:
                frames.append(df.assign(exchange=ex))
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df = df[df['subject'].astype(str).str.contains(SUBJECT) & df['isin'].astype(str).str.len().ge(10) & df['file_url'].notna()]
    df['broadcast_date'] = df['broadcast_date'].astype(str).str[:10]
    return df.sort_values('broadcast_date', ascending=False).reset_index(drop=True)


def stage(r2, today: date, lanes: dict, max_transcripts: int, months_back: int = 1, results_isins: set | None = None,
          deadline: float | None = None, log=print) -> dict:
    """Read up to `max_transcripts` transcripts not yet read, newest first (companies with results in hand first). The text comes from the
    text cache; a transcript not cached yet waits for the next run."""
    from insiders_clean.filing_text import Cache
    cache = Cache(r2)
    months = []
    y, m = today.year, today.month
    for _ in range(months_back + 1):
        months.append((y, m))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    rows = transcript_rows(r2, months)
    report = {'candidates': len(rows), 'read': 0, 'not_cached': 0, 'not_transcript': 0, 'already': 0, 'facts': 0}
    if rows.empty:
        return report
    if results_isins:
        rows = rows.assign(_p=~rows['isin'].isin(results_isins)).sort_values(['_p', 'broadcast_date'], ascending=[True, False])
    docs = {}
    for r in rows.to_dict('records'):
        if report['read'] >= max_transcripts or (deadline and time.monotonic() > deadline):
            break
        isin = str(r['isin'])
        if isin not in docs:
            docs[isin] = read_doc(r2, isin)
        if any(c.get('event_id') == r['event_id'] for c in docs[isin].get('calls') or []):
            report['already'] += 1
            continue
        rec = cache(r)
        text = str((rec or {}).get('text') or '')
        if not text:
            report['not_cached'] += 1
            continue
        if not is_transcript(r.get('subject'), text):
            report['not_transcript'] += 1
            continue
        facts, counts = verified_facts(lanes, str(r.get('company')), str(r['broadcast_date']), text, log)
        if not facts:
            log(f'management_said: {r.get("symbol")} {r["event_id"]}: no verified fact ({counts}); tried again next run')
            continue
        docs[isin] = save_call(r2, isin, str(r.get('company')), r, text, facts, counts)
        report['read'] += 1
        report['facts'] += len(facts)
        log(f'management_said: {r.get("symbol")} {r["event_id"]}: {len(facts)} facts kept {counts}')
    return report
