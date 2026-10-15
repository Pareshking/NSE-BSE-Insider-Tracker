"""What does cleaning save, and is any number lost? (read-only, to-do 4.14)

Takes a fixed random sample (seed 1) of filings from the newest days of the text cache (archive/filing_text/), runs
insiders_clean.text_clean.clean on each with its real subject, and reports: characters before and after (mean,
median, p90), the saving by rule, an estimate of tokens a day for 1,000 and 1,700 filings (4 characters a token, an
estimate), and the numbers that the cleaning removed: how many documents lost any number, and the commonest lost
numbers with a line of context. Writes nothing; no download, no model. Markdown to stdout and $GITHUB_STEP_SUMMARY.
"""
from __future__ import annotations

import io
import os
import re
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from r2_writer import BUCKET, r2_client  # noqa: E402

from insiders_clean.text_clean import clean_with_lines  # noqa: E402

N = 400
NUMBER = re.compile(r'\d[\d,]*\.?\d*')


def keys(r2, prefix):
    pages = r2.get_paginator('list_objects_v2').paginate(Bucket=BUCKET, Prefix=prefix)
    return sorted(o['Key'] for p in pages for o in p.get('Contents', []) if o['Key'].endswith('.parquet'))


def main() -> int:
    r2 = r2_client()
    days = keys(r2, 'archive/filing_text/')
    frames = []
    for k in days[-24:]:
        df = pd.read_parquet(io.BytesIO(r2.get_object(Bucket=BUCKET, Key=k)['Body'].read()),
                             columns=['event_id', 'exchange', 'broadcast_date', 'status', 'text'])
        frames.append(df[df['status'] == 'ok'])
    cache = pd.concat(frames, ignore_index=True)
    sample = cache.sample(min(N, len(cache)), random_state=1)
    subject = {}
    for ex, pre in (('nse', 'archive/announcements/nse/'), ('bse', 'archive/announcements/bse/')):
        for k in keys(r2, pre)[-2:]:
            a = pd.read_parquet(io.BytesIO(r2.get_object(Bucket=BUCKET, Key=k)['Body'].read()), columns=['event_id', 'subject'])
            subject.update(dict(zip(a['event_id'], a['subject'])))
    rows, by_rule, lost_all, lost_docs, examples, intended_docs = [], Counter(), Counter(), 0, {}, 0
    for r in sample.to_dict('records'):
        raw = r['text'] or ''
        out, removed, lines = clean_with_lines(raw, subject.get(r['event_id']))
        by_rule.update(removed)
        in_raw, in_clean = set(NUMBER.findall(raw)), set(NUMBER.findall(out))
        gone = in_raw - in_clean                               # a number that appears nowhere in the cleaned text
        intended = {n for ln in sum((lines.get(k, []) for k in ('exchange address', 'letterhead contacts', 'page number')), [])
                    for n in NUMBER.findall(ln)}
        unexplained = gone - intended
        intended_docs += bool(gone & intended)
        if unexplained:
            lost_docs += 1
            lost_all.update(unexplained)
            for num in unexplained:
                if num not in examples:
                    cand = [ln for k in lines for ln in lines[k] if num in ln]
                    examples[num] = re.sub(r'\s+', ' ', (cand or ['(not in a removed line)'])[0])[:110]
        rows.append({'raw': len(raw), 'clean': len(out)})
    d = pd.DataFrame(rows)
    saving = 1 - d['clean'].sum() / max(d['raw'].sum(), 1)
    per_doc = 1 - d['clean'] / d['raw'].replace(0, pd.NA)
    out = ['## Cleaning the cached text: saving and number check', '',
           f'Sample {len(d)} filings of the newest {len(frames)} day files (seed 1). Characters: raw mean {d["raw"].mean():,.0f}, '
           f'cleaned mean {d["clean"].mean():,.0f}; median {d["raw"].median():,.0f} to {d["clean"].median():,.0f}; '
           f'p90 {d["raw"].quantile(.9):,.0f} to {d["clean"].quantile(.9):,.0f}. Total saving {saving:.1%}; '
           f'per filing median {per_doc.dropna().median():.1%}.', '',
           '| rule | characters removed | share of the saving |', '|---|---|---|']
    total = sum(by_rule.values()) or 1
    for k, v in by_rule.most_common():
        out.append(f'| {k} | {v:,} | {v / total:.0%} |')
    for per_day in (1000, 1700):
        out.append('')
        out.append(f'- {per_day:,} filings a day, 4 characters a token (estimate): raw {d["raw"].mean() * per_day / 4 / 1e6:.1f}M '
                   f'tokens, cleaned {d["clean"].mean() * per_day / 4 / 1e6:.1f}M tokens a day')
    out += ['', '### Numbers that appear nowhere in the cleaned text', '',
            f'A number is lost when it is in the raw text and in no line of the cleaned text. Documents where numbers were '
            f'lost only in the intended lines (exchange address, letterhead contacts, page numbers): {intended_docs} of {len(d)}. '
            f'**Documents that lost a number outside those lines: {lost_docs} of {len(d)}** '
            f'({sum(lost_all.values()):,} distinct numbers in all).', '',
            '| number | documents | the removed line it was in |', '|---|---|---|']
    for num, n in lost_all.most_common(25):
        out.append(f'| `{num}` | {n} | {examples.get(num, "")} |')
    text = '\n'.join(out) + '\n'
    print(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as f:
            f.write(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
