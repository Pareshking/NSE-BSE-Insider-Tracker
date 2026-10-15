"""How big is a filing's extracted text, and how much of it is padding or repeated page furniture? (read-only, to-do 2.8)

A fixed random sample (seed 1) of PDF filings broadcast in the last 2 days, 40 a exchange, from the archive: each is
downloaded (as the reader does, BSE with the AttachHis fallback), turned into text with `pdftotext -layout`, and
measured: pages, characters, characters without spaces, gzip bytes of the text, pages with under 80 characters
(scanned-page rule), share of characters that are only layout padding, and the share of lines repeated on 3 or more
pages (headers and footers). Then the size of a year of text for 1,000 and 1,700 filings a day. Nothing is written
and no model is called. Markdown to stdout and $GITHUB_STEP_SUMMARY.
"""
from __future__ import annotations

import gzip
import io
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from r2_writer import BUCKET, r2_client  # noqa: E402
import announcement_sample as sample  # noqa: E402

N = 40
MAX_BYTES = 15 * 1024 ** 2


def newest(r2, ex):
    prefix = f'archive/announcements/{ex}/'
    keys = sorted(o['Key'] for p in r2.get_paginator('list_objects_v2').paginate(Bucket=BUCKET, Prefix=prefix)
                  for o in p.get('Contents', []) if o['Key'].endswith('.parquet'))
    df = pd.read_parquet(io.BytesIO(r2.get_object(Bucket=BUCKET, Key=keys[-1])['Body'].read()),
                         columns=['event_id', 'file_url', 'file_type', 'broadcast_date', 'subject'])
    df = df[df['file_url'].notna() & (df['file_type'] == 'pdf') & ~df['event_id'].astype(str).str.startswith('nse:xbrl:')]
    days = sorted(df['broadcast_date'].astype(str).unique())[-2:]
    df = df[df['broadcast_date'].astype(str).isin(days)]
    return df.sample(min(N, len(df)), random_state=1)


def measure(data: bytes) -> dict | None:
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / 'f.pdf'
        src.write_bytes(data)
        out = subprocess.run(['pdftotext', '-layout', str(src), '-'], capture_output=True, timeout=180, check=False)
    text = out.stdout.decode('utf-8', errors='replace')
    pages = text.split('\f')
    if pages and not pages[-1].strip():
        pages = pages[:-1]
    if not pages:
        return None
    nonspace = [len(re.sub(r'\s', '', p)) for p in pages]
    lines_by_page = [{ln.strip() for ln in p.splitlines() if ln.strip()} for p in pages]
    seen = Counter(ln for s in lines_by_page for ln in s)
    total_lines = sum(len(s) for s in lines_by_page) or 1
    repeated = sum(1 for s in lines_by_page for ln in s if seen[ln] >= 3 and len(pages) >= 3)
    chars = len(text)
    return {'pages': len(pages), 'chars': chars, 'nonspace': sum(nonspace), 'gz': len(gzip.compress(text.encode())),
            'thin_pages': sum(1 for n in nonspace if n < 80), 'pad': 1 - sum(nonspace) / max(chars, 1),
            'repeat': repeated / total_lines}


def main() -> int:
    r2 = r2_client()
    rows = []
    for ex in ('nse', 'bse'):
        for _, f in newest(r2, ex).iterrows():
            try:
                data = sample.download(f['file_url'])
                if len(data) > MAX_BYTES:
                    rows.append({'ex': ex, 'event': f['event_id'], 'note': f'skipped, {len(data) / 1e6:.0f} MB'})
                    continue
                m = measure(data) if data[:4] == b'%PDF' else None
                rows.append({'ex': ex, 'event': f['event_id'], 'subject': str(f['subject'])[:40], 'bytes': len(data),
                             **(m or {'note': 'not a PDF or no text'})})
            except Exception as exc:  # noqa: BLE001 -- a failing file is a finding
                rows.append({'ex': ex, 'event': f['event_id'], 'note': f'{type(exc).__name__}: {str(exc)[:60]}'})
    df = pd.DataFrame(rows)
    out = ['## Extracted-text size of a random sample of filings (last 2 days, `pdftotext -layout`)', '']
    ok = df[df['chars'].notna()] if 'chars' in df else df.iloc[0:0]
    out.append(f'Sampled {len(df)}; measured {len(ok)}; not measured: {len(df) - len(ok)} '
               f'{df[df["chars"].isna()]["note"].value_counts().to_dict() if "chars" in df else ""}')
    out += ['', '| exchange | n | pages median | chars median | chars mean | chars p90 | gzip bytes mean | gzip median | '
            'padding share | repeated-line share | filings with a page under 80 chars | PDF bytes mean |',
            '|---|---|---|---|---|---|---|---|---|---|---|---|']
    for ex, g in list(ok.groupby('ex')) + [('both', ok)]:
        out.append(f'| {ex} | {len(g)} | {g["pages"].median():.0f} | {g["chars"].median():,.0f} | {g["chars"].mean():,.0f} | '
                   f'{g["chars"].quantile(.9):,.0f} | {g["gz"].mean():,.0f} | {g["gz"].median():,.0f} | {g["pad"].mean():.0%} | '
                   f'{g["repeat"].mean():.1%} | {(g["thin_pages"] > 0).mean():.0%} | {g["bytes"].mean():,.0f} |')
    if len(ok):
        mean_gz = ok['gz'].mean()
        out += ['', '### A year of text kept as gzip (sample mean gzip bytes x filings a day x 365; an estimate)', '']
        for per_day in (1000, 1700, 4000):
            out.append(f'- {per_day:,} filings a day: {mean_gz * per_day * 365 / 1024 ** 3:.2f} GB a year '
                       f'({mean_gz * per_day / 1024 ** 2:.1f} MB a day)')
        out.append(f'- Free R2 storage: 10 GB. Largest sampled file: {ok["chars"].max():,.0f} characters, {ok["pages"].max():.0f} pages.')
    out += ['', 'Sample rows:', '']
    for _, r in ok.sort_values('chars', ascending=False).head(6).iterrows():
        out.append(f'- {r["ex"]} `{r["event"]}` {r["subject"]}: {r["pages"]:.0f} pages, {r["chars"]:,.0f} chars, '
                   f'padding {r["pad"]:.0%}, repeated lines {r["repeat"]:.0%}')
    text = '\n'.join(out) + '\n'
    print(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as f:
            f.write(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
