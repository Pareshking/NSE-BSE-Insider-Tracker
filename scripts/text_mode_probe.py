"""Does PyMuPDF's sort=True (no AI) keep a table row together? (owner's hint, 17 Oct 2026; read-only, no model is called)

The same PDFs as text four ways (pdftotext -layout = what the reader sends now, pdftotext reading order, PyMuPDF get_text(sort=True),
PyMuPDF blocks sorted by position). For rows read off the page images in the audit (label and its numbers, in order), each mode is scored:
the row is intact when the label is followed by its numbers in order within WINDOW characters. Pages are written for reading by eye.
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
from r2_writer import BUCKET, r2_client  # noqa: E402
import announcement_sample as sample  # noqa: E402
import vision_probe as vp  # noqa: E402

WINDOW = 260
OUT_DIR = Path(os.environ.get('OUT_DIR', 'text_out'))
# event_id -> [(label, [numbers in the order the page shows them])], each read off the page image
ROWS = {
    'bse:e0983f88-a4d2-4e20-a0a0-372f8600fffa': [('Revenue from Operations', ['8,932', '8,355', '5,878', '17,287', '11,466', '21,860']),
                                                   ('Profit after tax', ['1,351', '1,510', '861', '2,862', '2,065', '3,933'])],
    'nse:106820217': [('Total Income', ['38,814', '37,557', '34,091', '76,371', '67,359']),
                      ('Profit after Tax', ['707', '1,098', '793', '1,805', '4,432']),
                      ('Total Income', ['45,231', '44,760', '42,640', '89,991', '83,670']),
                      ('PAT', ['353', '908', '1,386', '1,261', '5,540'])],
    'nse:106815713': [('Long-term', ['125.00', '100.00', 'BBB', 'A3+']), ('Long-term', ['525.00', '175.00', 'BBB'])],
    'nse:106820190': [('Allotment of', ['7,100', 'ESOS 2010']), ('Allotment of', ['90,869', 'ESOS 2017']), ('Allotment of', ['1,985', 'ESIS 2023'])],
    'nse:106820139': [('Amount for exercise of warrants on', ['3,325.10', '34.99', '29.81 million']), ('Total amount received', ['6,115.04', '64.49'])],
}


def intact(text: str, label: str, nums: list[str]) -> bool:
    flat = re.sub(r'\s+', ' ', text)
    for m in re.finditer(re.escape(label), flat, re.IGNORECASE):
        at, ok = m.end(), True
        for n in nums:
            i = flat.find(n, at)
            if i < 0 or i - m.end() > WINDOW:
                ok = False
                break
            at = i + len(n)
        if ok:
            return True
    return False


def main() -> int:
    ids = list(ROWS)
    r2 = r2_client()
    frames = []
    for ex in ('nse', 'bse'):
        keys = sorted(o['Key'] for p in r2.get_paginator('list_objects_v2').paginate(Bucket=BUCKET, Prefix=f'archive/announcements/{ex}/')
                      for o in p.get('Contents', []) if o['Key'].endswith('.parquet'))
        for k in keys:
            df = pd.read_parquet(io.BytesIO(r2.get_object(Bucket=BUCKET, Key=k)['Body'].read()), columns=['event_id', 'file_url', 'subject'])
            frames.append(df[df['event_id'].isin(ids)])
    allr = pd.concat(frames).drop_duplicates('event_id')
    OUT_DIR.mkdir(exist_ok=True)
    score, md = {}, ['## Text modes: is a table row kept together? (no AI)', '']
    for _, f in allr.iterrows():
        eid = f['event_id']
        data = sample.download(f['file_url'])
        modes = vp.text_modes(data)
        md.append(f'### {eid} | {str(f["subject"])[:60]}')
        for mode, text in modes.items():
            (OUT_DIR / f'{eid.replace(":", "_")}_{mode}.txt').write_text('\n=====PAGE=====\n'.join(text.split('\f')))
            res = [intact(text, label, nums) for label, nums in ROWS[eid]]
            score.setdefault(mode, []).extend(res)
            md.append(f'- {mode}: {sum(res)}/{len(res)} rows intact ' + ''.join('✓' if r else '✗' for r in res))
        md.append('')
    md += ['### Total', ''] + [f'- {m}: {sum(v)}/{len(v)}' for m, v in score.items()]
    out = '\n'.join(md)
    print(out)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        Path(os.environ['GITHUB_STEP_SUMMARY']).write_text(out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
