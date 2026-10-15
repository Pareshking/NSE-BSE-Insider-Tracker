"""What the R2 bucket holds, by prefix, and whether any raw PDFs are in it (read-only, to-do 2.7).

Lists every object once: total size and count, size by the first two path levels (raw_v2/nse, archive/announcements ...),
the ten biggest prefixes at three levels, objects by extension, and every key ending .pdf (any other file kind a
filing could be: .zip, .bin, .doc*, .xls*, .htm*). Writes nothing; no model, no exchange. Markdown to stdout and
$GITHUB_STEP_SUMMARY.
"""
from __future__ import annotations

import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from r2_writer import BUCKET, r2_client  # noqa: E402

DOC_EXT = ('.pdf', '.zip', '.bin', '.doc', '.docx', '.xls', '.xlsx', '.htm', '.html', '.txt')


def mb(n):
    return f'{n / 1024 ** 2:,.1f} MB' if n < 1024 ** 3 else f'{n / 1024 ** 3:,.2f} GB'


def main() -> int:
    r2 = r2_client()
    by2, by3, ext = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    docs, total, count = [], 0, 0
    for page in r2.get_paginator('list_objects_v2').paginate(Bucket=BUCKET):
        for o in page.get('Contents', []):
            k, s = o['Key'], o['Size']
            total += s
            count += 1
            parts = k.split('/')
            for table, n in ((by2, 2), (by3, 3)):
                key = '/'.join(parts[:n]) if len(parts) > n else '/'.join(parts[:-1]) or '(root)'
                table[key][0] += s
                table[key][1] += 1
            e = os.path.splitext(k)[1].lower() or '(none)'
            ext[e][0] += s
            ext[e][1] += 1
            if e in DOC_EXT:
                docs.append((k, s))
    out = ['## R2 bucket contents', '', f'Total {mb(total)} in {count:,} objects.', '',
           '### By first two path levels', '', '| prefix | size | objects |', '|---|---|---|']
    for k, (s, n) in sorted(by2.items(), key=lambda kv: -kv[1][0])[:25]:
        out.append(f'| `{k}` | {mb(s)} | {n:,} |')
    out += ['', '### Biggest prefixes (three levels)', '', '| prefix | size | objects |', '|---|---|---|']
    for k, (s, n) in sorted(by3.items(), key=lambda kv: -kv[1][0])[:12]:
        out.append(f'| `{k}` | {mb(s)} | {n:,} |')
    out += ['', '### By extension', '', '| extension | size | objects |', '|---|---|---|']
    for k, (s, n) in sorted(ext.items(), key=lambda kv: -kv[1][0])[:12]:
        out.append(f'| `{k}` | {mb(s)} | {n:,} |')
    pdfs = [x for x in docs if x[0].lower().endswith('.pdf')]
    out += ['', f'### Document-like objects ({", ".join(DOC_EXT)})', '',
            f'Objects ending .pdf: {len(pdfs)} ({mb(sum(s for _, s in pdfs))}). All document-like: {len(docs)} '
            f'({mb(sum(s for _, s in docs))}).']
    kinds = Counter(os.path.splitext(k)[1].lower() for k, _ in docs)
    out.append(f'By kind: {dict(kinds)}')
    for k, s in sorted(docs, key=lambda x: -x[1])[:15]:
        out.append(f'- `{k}` {mb(s)}')
    text = '\n'.join(out) + '\n'
    print(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as f:
            f.write(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
