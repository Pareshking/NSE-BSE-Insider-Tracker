"""Worked example (owner, 18 Oct): last quarter's call transcript becomes context for this quarter's results card (read-only).

Company, transcript and results filings come from env: ISIN, SYMBOL, COMPANY, PRIOR_TRANSCRIPT (event_id), RESULTS (event_id), as NSE ids.
1. The prior transcript is read in sections; each fact is management's own words with an exact quote, kept only if the quote is in the
   transcript (code check) and every number of the statement is in its quote.
2. The results filing is read twice by the reader's own card prompt: without context, and with the XBRL previous quarter plus the
   transcript facts as context.
3. The page's "Management said last quarter" block is built by code from the verified facts (quote, call date, source), never by the card model.
Writes nothing (no R2 write); prints Markdown to stdout and $GITHUB_STEP_SUMMARY.
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import announcement_reader as ar  # noqa: E402
import announcement_sample as s  # noqa: E402
from r2_writer import r2_client  # noqa: E402
from clean_writer import get  # noqa: E402
from insiders_clean import filing_text, context  # noqa: E402

SECTION = 13_000
TOPICS = 'guidance or outlook, demand, deal wins or order book, margins, headcount or attrition, pricing, capital allocation, risks'


def fact_prompt(company: str, date: str, section: str, k: int, n: int) -> str:
    return (f'This is part {k} of {n} of the transcript of {company}\'s earnings conference call, filed {date}. Extract up to 8 statements MADE BY '
            f'THE COMPANY\'S MANAGEMENT that an investor will want to remember when the next quarter\'s results come out: {TOPICS}. '
            'A question from an analyst is not a fact. Return only JSON: {"facts": [{"topic": one of guidance, demand, deals, margins, people, '
            'pricing, capital, risk; "statement": one plain sentence of at most 200 characters that repeats only numbers found in the quote; '
            '"speaker": the manager\'s name as the transcript gives it, or null; "quote": the exact words of the transcript, at most 300 '
            'characters, copied character for character}]}. Leave a statement out rather than paraphrase a number.\n\n=== TRANSCRIPT ===\n' + section)


def sections(text: str) -> list[str]:
    out, i = [], 0
    while i < len(text):
        j = min(len(text), i + SECTION)
        if j < len(text):   # end at a sentence
            k = text.rfind('. ', i + SECTION // 2, j)
            j = k + 1 if k > 0 else j
        out.append(text[i:j])
        i = j
    return out


def digits(t: str) -> set[str]:
    return {x.replace(',', '') for x in re.findall(r'\d[\d,]*(?:\.\d+)?', t or '')}


def verified_facts(lanes, company: str, date: str, doc: str, out: list[str]) -> list[dict]:
    parts = sections(doc)
    kept, dropped = [], {'quote not in transcript': 0, 'number not in quote': 0, 'no answer': 0}
    for k, part in enumerate(parts, 1):
        raw = None
        for lane in lanes.values():
            try:
                text, used, secs = lane.read(fact_prompt(company, date, part, k, len(parts)))
                raw = s.parse_json(text)
                if isinstance(raw, dict):
                    out.append(f'- section {k}/{len(parts)} read by {used} in {secs:.0f}s')
                    break
            except Exception as exc:  # noqa: BLE001
                out.append(f'- section {k}: {type(exc).__name__}: {str(exc)[:120]}')
        if not isinstance(raw, dict):
            dropped['no answer'] += 1
            continue
        for f in raw.get('facts') or []:
            if not isinstance(f, dict) or not f.get('quote') or not f.get('statement'):
                continue
            if not s.quote_found(f['quote'], doc):
                dropped['quote not in transcript'] += 1
                continue
            if not digits(f['statement']) <= digits(f['quote']):
                dropped['number not in quote'] += 1
                continue
            kept.append({k2: f.get(k2) for k2 in ('topic', 'statement', 'speaker', 'quote')})
    out.append(f'- facts kept {len(kept)}; dropped {dropped}')
    return kept


def card_lines(res: dict) -> list[str]:
    if not res.get('ok'):
        return [f'- no card: {res.get("error")}']
    h = res.get('headline') or {}
    lines = [f'- category **{res.get("category")}**; read by {res.get("reader")}',
             f'- HEADLINE{"" if h.get("shown") else " (held: " + str(h.get("reason")) + ")"}: {h.get("text")}']
    sub = h.get('subtitle')
    if isinstance(sub, dict):
        lines.append(f'- SUBTITLE{"" if sub.get("shown") else " (held)"}: {sub.get("text")}')
    for p in res.get('points') or []:
        lines.append(f'- POINT{"" if p.get("shown") else " (held)"}: {p.get("text")}')
    for m in res.get('metrics') or []:
        lines.append(f'- METRIC{"" if m.get("shown") else " (held)"} {m.get("label")} [{m.get("period")}] = {m.get("value")} {m.get("unit")}')
    return lines


def main() -> int:
    r2 = r2_client()
    isin, symbol, company = os.environ['ISIN'], os.environ['SYMBOL'], os.environ['COMPANY']
    prior_id, results_id = os.environ['PRIOR_TRANSCRIPT'], os.environ['RESULTS']
    meta = {}
    for m in (7, 8, 9, 10):
        df = pd.read_parquet(io.BytesIO(get(r2, f'archive/announcements/nse/year=2026/month={m:02d}.parquet')))
        for r in df[df['event_id'].isin([prior_id, results_id])].to_dict('records'):
            meta[r['event_id']] = r
    cached = {}
    for ev, r in meta.items():
        day = str(r['broadcast_date'])[:10]
        rec = {x['event_id']: x for x in filing_text.load_day(r2, 'nse', day).to_dict('records')}.get(ev) or {}
        cached[ev] = (day, str(rec.get('text') or ''), r)
    out = [f'## {company}: last quarter\'s transcript as context for this quarter\'s results', '']
    for ev in (prior_id, results_id):
        day, text, r = cached[ev]
        out.append(f'- `{ev}` {day} | {r.get("subject")} | {len(text):,} characters | {r.get("file_url")}')
    out.append('')
    lane_spec = ar.lanes_of(ar.LANES_FILE.read_text(encoding='utf-8'))
    clients, _ = ar.clients_for([e for es in lane_spec.values() for e in es])
    health = {}
    lanes = {n: ar.Lane(n, [e for e in ar.usable(es) if e.split(':', 1)[0] in clients], clients, health=health) for n, es in lane_spec.items()}
    lanes = {n: ln for n, ln in lanes.items() if ln.entries}
    pday, ptext, _ = cached[prior_id]
    out += ['### 1. Management\'s own words from the prior call, checked against the transcript', '']
    facts = verified_facts(lanes, company, pday, ptext, out)
    out.append('')
    for f in facts:
        out.append(f'- **{f["topic"]}**: {f["statement"]}' + (f' ({f["speaker"]})' if f.get('speaker') else ''))
        out.append(f'  > "{f["quote"]}"')
    out.append('')
    rday, rtext, rrow = cached[results_id]
    body = get(r2, 'clean/current/results.parquet')
    results = pd.read_parquet(io.BytesIO(body)) if body else None
    xbrl = ar.xbrl_context_lines(results, isin, f'{rday}T00:00:00Z')
    memory = '\n'.join(xbrl + [f'- {pday} [{prior_id}] Management said ({f["topic"]}): {f["statement"]} (source: {meta[prior_id].get("file_url")})' for f in facts[:10]])
    row = {'exchange': 'NSE', 'symbol': symbol, 'company': company, 'subject': rrow.get('subject'), 'broadcast_date': rday, 'event_id': results_id}
    out += ['### 2. The results card without and with the context', '']
    for label, mem in (('WITHOUT context', ''), ('WITH XBRL previous quarter and the prior call', memory)):
        lane = next(iter(lanes.values()))
        res = None
        for lane in lanes.values():
            prompt = ar.card_prompt({**row, '_company_memory': mem}, rtext)
            try:
                text, used, secs = lane.read(prompt)
                res = ar.result_of(s.parse_json(text), rtext, used, secs, lane.name, (symbol, company), rrow.get('subject') or '')
                break
            except Exception as exc:  # noqa: BLE001
                res = {'ok': False, 'error': f'{type(exc).__name__}: {str(exc)[:150]}'}
        out += [f'**{label}**', ''] + card_lines(res) + ['']
    out += ['### 3. "Management said last quarter" block for the page (built by code, from the verified facts only)', '']
    pick = [f for f in facts if f['topic'] in ('guidance', 'margins', 'demand', 'deals')][:5]
    for f in pick:
        out.append(f'- {f["statement"]} — {f.get("speaker") or "management"}, call of {pday}. Source: {meta[prior_id].get("file_url")}')
    text = '\n'.join(out)
    print(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        Path(os.environ['GITHUB_STEP_SUMMARY']).write_text(text, encoding='utf-8')
    return 0


if __name__ == '__main__':
    sys.exit(main())
