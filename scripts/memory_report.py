"""What the company memory holds and whether a filing finds it (read-only, to-do 1.2).

archive/company_memory/{ISIN}.json: files, events a file, the 100-event cap, which parts of an event are kept,
dates, categories. Then against the reads table (archive/announcement_reads/): of the filings read, how many had an
ISIN, and how many had at least one earlier event in memory when read (the rule of with_company_memory: same ISIN,
earlier broadcast date, last 8). Three prompt blocks exactly as the reader builds them. Writes nothing; no model,
no exchange. Markdown to stdout and $GITHUB_STEP_SUMMARY.
"""
from __future__ import annotations

import io
import json
import os
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from r2_writer import BUCKET, r2_client  # noqa: E402

out: list[str] = []


def keys(r2, prefix):
    pages = r2.get_paginator('list_objects_v2').paginate(Bucket=BUCKET, Prefix=prefix)
    return [(o['Key'], o['Size']) for p in pages for o in p.get('Contents', [])]


def pct(a, b):
    return f'{a / b:.1%}' if b else 'n/a'


def main() -> int:
    r2 = r2_client()
    out.extend(['## Company memory: what it holds', ''])
    files = [(k, s) for k, s in keys(r2, 'archive/company_memory/') if k.endswith('.json')]
    mem, bad = {}, 0
    for k, _ in files:
        try:
            body = json.loads(r2.get_object(Bucket=BUCKET, Key=k)['Body'].read())
            mem[k.rsplit('/', 1)[-1][:-5]] = body
        except Exception:  # noqa: BLE001
            bad += 1
    sizes = pd.Series([s for _, s in files])
    n_ev = pd.Series({i: len(m.get('events', [])) for i, m in mem.items()})
    out.append(f'- Files: {len(files)} ({bad} unreadable); bytes median {int(sizes.median())}, max {int(sizes.max())}, '
               f'total {int(sizes.sum()) / 1e6:.1f} MB')
    out.append(f'- Events a file: median {int(n_ev.median())}, mean {n_ev.mean():.1f}, max {int(n_ev.max())}; '
               f'files at the 100 cap: {int((n_ev >= 100).sum())}; with 1 event: {int((n_ev == 1).sum())}')
    events = [dict(e, isin=i) for i, m in mem.items() for e in m.get('events', [])]
    ev = pd.DataFrame(events)
    out.append(f'- Events: {len(ev)}, dates {ev["date"].min()} to {ev["date"].max()}')
    for part in ('headline', 'points', 'fields', 'metrics'):
        have = ev[part].map(lambda v: bool(v)).sum() if part in ev else 0
        out.append(f'  - with {part}: {have} ({pct(have, len(ev))})')
    out.append(f'- Events by month: {ev["date"].astype(str).str[:7].value_counts().sort_index().to_dict()}')
    out.append(f'- Events by category: {ev["category"].value_counts().head(15).to_dict()}')
    out.append(f'- Schema versions: {Counter(m.get("schema_version") for m in mem.values())}')
    out.append('')
    out.append('### Does a filing find its memory?')
    ks = sorted(k for k, _ in keys(r2, 'archive/announcement_reads/') if k.endswith('.parquet'))
    reads = pd.concat([pd.read_parquet(io.BytesIO(r2.get_object(Bucket=BUCKET, Key=k)['Body'].read()),
                                       columns=['event_id', 'status', 'isin', 'broadcast_date', 'category', 'symbol'])
                       for k in ks], ignore_index=True)
    out.append(f'- Reads table: {len(reads)} rows, statuses {reads["status"].value_counts().to_dict()}')
    r = reads[reads['status'] == 'read'].copy()
    has_isin = r['isin'].notna() & (r['isin'].astype(str).str.lower() != 'nan') & (r['isin'].astype(str) != '')
    out.append(f'- Read filings: {len(r)}; with an ISIN: {int(has_isin.sum())} ({pct(has_isin.sum(), len(r))}); '
               f'without: {int((~has_isin).sum())} (no memory possible)')
    by_isin = {i: sorted(str(e.get('date')) for e in m.get('events', []) if e.get('date')) for i, m in mem.items()}
    found = 0
    for isin, day in zip(r.loc[has_isin, 'isin'], r.loc[has_isin, 'broadcast_date'].astype(str)):
        if any(d < day for d in by_isin.get(isin, [])):
            found += 1
    out.append(f'- Read filings with at least one earlier event in memory: {found} ({pct(found, int(has_isin.sum()))} '
               f'of those with an ISIN; {pct(found, len(r))} of all)')
    out.append(f'- Memory ISINs not in the reads table with an ISIN: {len(set(mem) - set(r.loc[has_isin, "isin"]))}')
    out.append('')
    out.append('### Three prompt blocks as the reader builds them (public filings)')
    shown = 0
    for isin, m in sorted(mem.items(), key=lambda kv: -len(kv[1].get('events', [])))[:60]:
        evs = m.get('events', [])
        if len(evs) < 3 or shown >= 3:
            continue
        lines = []
        for e in evs[-8:]:
            h = e.get('headline') if isinstance(e.get('headline'), dict) else {}
            s = h.get('text') or '; '.join(p.get('text', '') for p in e.get('points', [])[:2] if p.get('text'))
            if s:
                lines.append(f"- {e.get('date')} [{e.get('event_id')}] {s} (source: {e.get('source_url')})")
        out.append(f'`{isin}` ({len(evs)} events), {len(lines)} lines, {sum(len(x) for x in lines)} characters:')
        out.append('```')
        out.extend(x[:260] for x in lines[:4])
        out.append('```')
        shown += 1
    text = '\n'.join(out) + '\n'
    print(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as f:
            f.write(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
