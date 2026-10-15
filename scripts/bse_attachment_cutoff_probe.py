"""After how many days does BSE move a filing's PDF from AttachLive to AttachHis? (read-only, to-do 2.7a)

For each broadcast day from 1 Oct 2026 to today, up to 4 BSE filings from the archive are requested under both
AttachLive and AttachHis (first bytes only): HTTP status and whether the body is a PDF. Prints the day-by-day table
and the first day on which AttachLive still works. Writes nothing; no model. About 100 requests.
"""
from __future__ import annotations

import io
import os
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from attachment_link_probe import probe  # noqa: E402
from r2_writer import BUCKET, r2_client  # noqa: E402


def main() -> int:
    r2 = r2_client()
    df = pd.read_parquet(io.BytesIO(r2.get_object(Bucket=BUCKET, Key='archive/announcements/bse/year=2026/month=10.parquet')['Body'].read()),
                         columns=['event_id', 'file_url', 'file_type', 'broadcast_date', 'broadcast_at'])
    df = df[df['file_url'].notna() & (df['file_type'] == 'pdf')]
    out = ['## BSE: AttachLive vs AttachHis by filing age', '',
           '| filing day | age (days) | AttachLive ok / tried | AttachHis ok / tried |', '|---|---|---|---|']
    first_live = None
    today = date.today()
    for day, rows in sorted(df.groupby('broadcast_date')):
        pick = rows.iloc[[0, len(rows) // 3, 2 * len(rows) // 3, len(rows) - 1]] if len(rows) >= 4 else rows
        live = his = tried = 0
        for url in pick['file_url']:
            tried += 1
            s, k, _ = probe(url)
            live += s in (200, 206) and k == 'pdf'
            s2, k2, _ = probe(url.replace('AttachLive', 'AttachHis'))
            his += s2 in (200, 206) and k2 == 'pdf'
            time.sleep(1)
        age = (today - date.fromisoformat(str(day))).days
        out.append(f'| {day} | {age} | {live}/{tried} | {his}/{tried} |')
        if live and first_live is None:
            first_live = (day, age)
    out += ['', f'First day (oldest) on which AttachLive still returns a PDF: {first_live}']
    text = '\n'.join(out) + '\n'
    print(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as f:
            f.write(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
