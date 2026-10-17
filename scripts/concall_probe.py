"""Which companies have earnings-call transcripts in our text cache, and which of them also have Q2 FY27 results (read-only).

Lists, per company (ISIN), the concall / transcript filings in the archive from 1 Jul to now with their cached text size and
whether the text looks like a transcript (a moderator, "question-and-answer"), and whether the XBRL results table holds the
quarter ended 30 Sep 2026. Writes nothing; no model, no exchange. Markdown to stdout and $GITHUB_STEP_SUMMARY.
"""
from __future__ import annotations

import io
import os
import re
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from r2_writer import r2_client  # noqa: E402
from clean_writer import get, read_parquet  # noqa: E402
from insiders_clean import filing_text  # noqa: E402

CALLISH = re.compile(r'con(?:ference)?\.?\s*call|earnings call|transcript|analyst|institutional investor', re.I)
LOOKS = re.compile(r'moderator|question[- ]and[- ]answer|q\s*&\s*a|ladies and gentlemen', re.I)


def main() -> int:
    r2 = r2_client()
    rows = []
    for ex in ('nse', 'bse'):
        for m in (5, 6, 7, 8, 9, 10):
            df = read_parquet(r2, f'archive/announcements/{ex}/year=2026/month={m:02d}.parquet')
            if df is None or df.empty:
                continue
            df = df.assign(exchange=ex)
            blank = pd.Series('', index=df.index)
            hit = df[df.get('subject', blank).astype(str).str.contains(CALLISH) | df.get('text', blank).astype(str).str.contains('transcript', case=False)]
            rows.append(hit)
    arch = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    out = ['## Concall filings in the archive, May to Oct 2026', '', f'{len(arch)} rows (subject or text mentions a call / transcript)', '']
    if arch.empty:
        print('\n'.join(out)); return 0
    arch['broadcast_date'] = arch['broadcast_date'].astype(str).str[:10]
    days = {}
    import pyarrow.parquet as pq
    for (ex, d) in set(zip(arch['exchange'], arch['broadcast_date'])):   # the cache's day files without their text column: sizes only
        body = get(r2, filing_text.key(ex, d))
        cols = [c for c in ('event_id', 'status', 'chars', 'pages') if body]
        days[(ex, d)] = {r['event_id']: r for r in pq.read_table(io.BytesIO(body), columns=cols).to_pandas().to_dict('records')} if body else {}
    info = []
    for r in arch.to_dict('records'):
        rec = days[(r['exchange'], r['broadcast_date'])].get(r['event_id']) or {}
        info.append({'isin': r.get('isin'), 'company': r.get('company'), 'symbol': r.get('symbol'), 'date': r['broadcast_date'],
                     'exchange': r['exchange'], 'subject': str(r.get('subject'))[:60], 'chars': int(rec.get('chars') or 0),
                     'pages': rec.get('pages'), 'status': rec.get('status'),
                     'transcript_like': bool(rec.get('chars') or 0) and int(rec.get('chars') or 0) > 15000 and bool(CALLISH.search(str(r.get('subject')))),
                     'event_id': r['event_id']})
    t = pd.DataFrame(info)
    t = t[t['isin'].astype(str).str.len() > 5]
    body = get(r2, 'clean/current/results.parquet')
    res = pd.read_parquet(io.BytesIO(body)) if body else pd.DataFrame()
    q2 = set()
    if len(res):
        end = pd.to_datetime(res['period_end'], errors='coerce')
        q2 = set(res.loc[end == pd.Timestamp('2026-09-30'), 'isin'].astype(str))
    out += [f'Transcript-like with cached text: {int(((t.transcript_like) & (t.chars > 0)).sum())} of {len(t)}', '',
            f'Companies with Q2 FY27 XBRL results (30 Sep 2026): {len(q2)}', '']
    tr = t[t.transcript_like & (t.chars > 10000)]
    g = tr.groupby('isin').agg(company=('company', 'first'), calls=('date', lambda s: sorted(set(s))), n=('date', 'nunique'))
    g['q2_results'] = [i in q2 for i in g.index]
    g = g.sort_values(['q2_results', 'n'], ascending=False)
    out += ['### Companies with transcripts (>10,000 characters), those with Q2 results first', '',
            '| ISIN | company | transcript dates | Q2 XBRL |', '|---|---|---|---|']
    for isin, r in g.head(40).iterrows():
        out.append(f'| {isin} | {r.company} | {", ".join(r.calls)} | {"yes" if r.q2_results else "no"} |')
    out += ['', '### All concall-ish rows by size (largest 25)', '', t.sort_values('chars', ascending=False).head(25).to_markdown(index=False)]
    text = '\n'.join(out)
    print(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        Path(os.environ['GITHUB_STEP_SUMMARY']).write_text(text, encoding='utf-8')
    return 0


if __name__ == '__main__':
    sys.exit(main())
