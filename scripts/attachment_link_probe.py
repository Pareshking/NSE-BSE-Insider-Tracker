"""Do old filing links still return the document? (read-only, to-do 2.7)

We keep no PDFs in R2, so a filing is readable only while the exchange still serves its link. For each exchange
and each month in the archive, three filings spread over the month are requested (first bytes only, the exchange as
referer, as the reader does): HTTP status, whether the body starts %PDF (or PK for a ZIP), size. A BSE link that fails
under AttachLive is tried under AttachHis, where BSE is said to move older attachments. Writes nothing; no model.
About 60 requests. Markdown to stdout and $GITHUB_STEP_SUMMARY.
"""
from __future__ import annotations

import io
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from r2_writer import BUCKET, r2_client  # noqa: E402

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/124.0 Safari/537.36')
PER_MONTH = 3


def probe(url):
    ref = 'https://www.bseindia.com/' if 'bseindia.com' in url else 'https://www.nseindia.com/'
    try:
        r = requests.get(url, headers={'User-Agent': UA, 'Referer': ref, 'Range': 'bytes=0-15'},
                         timeout=(15, 60), stream=True)
        head = next(r.iter_content(16), b'')
        total = r.headers.get('Content-Range', '').rsplit('/', 1)[-1] or r.headers.get('Content-Length', '?')
        kind = 'pdf' if head.startswith(b'%PDF') else 'zip' if head.startswith(b'PK') else f'other({head[:8]!r})'
        r.close()
        return r.status_code, kind, total
    except Exception as exc:  # noqa: BLE001 -- a failing link is a finding
        return type(exc).__name__, '-', '-'


def main() -> int:
    r2 = r2_client()
    out = ['## Do old filing links still return the document?', '',
           '| exchange | month | filing day | HTTP | body | size | AttachHis (BSE, only if AttachLive failed) |',
           '|---|---|---|---|---|---|---|']
    ok, bad = {}, {}
    for ex in ('nse', 'bse'):
        prefix = f'archive/announcements/{ex}/'
        keys = sorted(o['Key'] for p in r2.get_paginator('list_objects_v2').paginate(Bucket=BUCKET, Prefix=prefix)
                      for o in p.get('Contents', []) if o['Key'].endswith('.parquet'))
        for k in keys:
            df = pd.read_parquet(io.BytesIO(r2.get_object(Bucket=BUCKET, Key=k)['Body'].read()),
                                 columns=['event_id', 'file_url', 'file_type', 'broadcast_date'])
            df = df[df['file_url'].notna() & (df['file_type'] == 'pdf')
                    & ~df['event_id'].astype(str).str.startswith('nse:xbrl:')].sort_values('broadcast_date')
            if df.empty:
                continue
            month = k.rsplit('month=', 1)[-1][:2]
            pick = df.iloc[[len(df) // 6, len(df) // 2, len(df) * 5 // 6]] if len(df) >= 6 else df.head(PER_MONTH)
            for _, row in pick.iterrows():
                status, kind, size = probe(row['file_url'])
                his = ''
                good = status in (200, 206) and kind in ('pdf', 'zip')
                if not good and ex == 'bse' and 'AttachLive' in row['file_url']:
                    s2, k2, z2 = probe(row['file_url'].replace('AttachLive', 'AttachHis'))
                    his = f'{s2} {k2} {z2}'
                    good = s2 in (200, 206) and k2 in ('pdf', 'zip')
                (ok if good else bad).setdefault((ex, month), 0)
                (ok if good else bad)[(ex, month)] += 1
                out.append(f'| {ex} | {month} | {row["broadcast_date"]} | {status} | {kind} | {size} | {his} |')
                time.sleep(1.5)
    out += ['', '### Result by exchange and month (links that returned a document / links that did not)', '']
    for key in sorted(set(ok) | set(bad)):
        out.append(f'- {key[0]} {key[1]}: {ok.get(key, 0)} / {bad.get(key, 0)}')
    text = '\n'.join(out) + '\n'
    print(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as f:
            f.write(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
