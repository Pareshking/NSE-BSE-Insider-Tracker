"""How many announcements a day are routine, by our own reading groups (read-only, blueprint item 1.1).

Reads archive/announcements/{nse,bse}/ and applies each collector's group_of exactly as the reader does.
Per exchange and month: days, filings a day (median and busiest), the share in each group, filings without a
file; then the 30 commonest routine subjects of the last 60 days, the candidates for reading (item 4.6).
Concall filings are not in the archive (NOT_COLLECTED), so they are not counted here.
Writes nothing; no model, no exchange. Markdown to stdout and $GITHUB_STEP_SUMMARY.
"""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from r2_writer import BUCKET, r2_client  # noqa: E402
from collectors.nse_events import announcements as nse  # noqa: E402
from collectors.bse import announcements as bse  # noqa: E402

out: list[str] = []


def load(r2, prefix):
    pages = r2.get_paginator('list_objects_v2').paginate(Bucket=BUCKET, Prefix=prefix)
    keys = sorted(o['Key'] for p in pages for o in p.get('Contents', []) if o['Key'].endswith('.parquet'))
    frames = [pd.read_parquet(io.BytesIO(r2.get_object(Bucket=BUCKET, Key=k)['Body'].read())) for k in keys]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def report(name, df, groups, subject_col):
    out.append(f'### {name}: {len(df):,} filings, {df["broadcast_date"].min()} to {df["broadcast_date"].max()}')
    df = df.assign(group=groups, month=df['broadcast_date'].astype(str).str[:7])
    names = [g for g in list(nse.READING_GROUPS) + ['debt', 'routine'] if (df['group'] == g).any()]
    out.append('| month | days | a day (median) | busiest day | ' + ' | '.join(names) + ' | read share | no file |')
    out.append('|' + '---|' * (6 + len(names)))
    for month, m in df.groupby('month'):
        per_day = m.groupby('broadcast_date').size()
        share = m['group'].value_counts(normalize=True)
        read = 1 - share.get('routine', 0) - share.get('debt', 0)
        out.append(f'| {month} | {len(per_day)} | {int(per_day.median())} | {int(per_day.max())} | '
                   + ' | '.join(f'{share.get(g, 0):.1%}' for g in names)
                   + f' | {read:.1%} | {m["file_url"].isna().mean():.1%} |')
    recent = df[pd.to_datetime(df['broadcast_date'], errors='coerce') >= pd.to_datetime(df['broadcast_date']).max()
                - pd.Timedelta(days=60)]
    top = recent.loc[recent['group'] == 'routine', subject_col].fillna('(none)').value_counts().head(30)
    out.extend(['', f'Commonest routine {subject_col} in the last 60 days ({len(recent):,} filings):', ''])
    out.append('| subject | filings | a day |')
    out.append('|---|---|---|')
    days = max(recent['broadcast_date'].nunique(), 1)
    for s, n in top.items():
        out.append(f'| {s} | {n:,} | {n / days:.1f} |')
    out.append('')


def main() -> int:
    r2 = r2_client()
    out.extend(['## Routine share of announcements (our reading groups)', ''])
    n = load(r2, nse.PREFIX)
    n = n[~n['event_id'].astype(str).str.startswith('nse:xbrl:')]
    report('NSE', n, [nse.group_of(s, t) for s, t in zip(n['subject'], n['text'])], 'subject')
    b = load(r2, bse.PREFIX)
    out.append(f'BSE archive columns: {list(b.columns)}')
    for col in ('subcategory', 'category'):
        if col not in b:
            b[col] = None
    report('BSE', b, [bse.group_of(s, c) for s, c in zip(b['subcategory'], b['category'])], 'subcategory')
    text = '\n'.join(out) + '\n'
    print(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as f:
            f.write(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
