"""Which days of the announcement archive are present, and why the others are not (read-only, to-do 1.1a).

For NSE and BSE, from 1 Jan 2026 to today: filings per broadcast day in archive/announcements/{nse,bse}/, the days
with none or a thin count (weekdays first), the partitions that exist, the collection markers
(archive/announcement_backfill/collection/ and collection-days/), the daily collection reports
(clean/reports/announcements/ and announcements_bse/) and the raw_v2 fetch days. Writes nothing; no model, no
exchange. Markdown to stdout and $GITHUB_STEP_SUMMARY.
"""
from __future__ import annotations

import io
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from r2_writer import BUCKET, r2_client  # noqa: E402

START = date(2026, 1, 1)
out: list[str] = []


def keys(r2, prefix):
    pages = r2.get_paginator('list_objects_v2').paginate(Bucket=BUCKET, Prefix=prefix)
    return [o['Key'] for p in pages for o in p.get('Contents', [])]


def runs(days):
    """'1-9, 12' style ranges of consecutive dates."""
    days = sorted(days)
    if not days:
        return 'none'
    spans, a, b = [], days[0], days[0]
    for d in days[1:]:
        if d - b == timedelta(days=1):
            b = d
        else:
            spans.append((a, b))
            a = b = d
    spans.append((a, b))
    return ', '.join(f'{x:%d %b}' if x == y else f'{x:%d %b}-{y:%d %b}' for x, y in spans)


def archive_days(r2, prefix):
    ks = sorted(k for k in keys(r2, prefix) if k.endswith('.parquet'))
    out.append(f'Partitions: {[k[len(prefix):] for k in ks]}')
    frames = [pd.read_parquet(io.BytesIO(r2.get_object(Bucket=BUCKET, Key=k)['Body'].read()),
                              columns=['event_id', 'broadcast_date']) for k in ks]
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=['event_id', 'broadcast_date'])
    df = df[~df['event_id'].astype(str).str.startswith('nse:xbrl:')]
    return df['broadcast_date'].astype(str).value_counts().to_dict()


def main() -> int:
    r2 = r2_client()
    today = date.today()
    every = [START + timedelta(days=i) for i in range((today - START).days + 1)]
    weekdays = [d for d in every if d.weekday() < 5]
    out.extend(['## Announcement archive: which days exist', ''])
    for name, prefix, report_prefix in (('NSE', 'archive/announcements/nse/', 'clean/reports/announcements/'),
                                        ('BSE', 'archive/announcements/bse/', 'clean/reports/announcements_bse/')):
        out.append(f'### {name}')
        counts = archive_days(r2, prefix)
        have = {d for d in every if counts.get(d.isoformat(), 0) > 0}
        thin = {d for d in have if counts[d.isoformat()] < 100 and d.weekday() < 5}
        missing = [d for d in weekdays if d not in have]
        out.append(f'Weekdays {len(weekdays)}; with filings {len([d for d in weekdays if d in have])}; '
                   f'weekdays with none: {len(missing)}; weekdays under 100 filings: {len(thin)}')
        out.append(f'- Weekdays with none: {runs(missing)}')
        out.append(f'- Weekdays under 100: {runs(thin)} (counts {[counts[d.isoformat()] for d in sorted(thin)][:20]})')
        out.append(f'- Weekend days with filings: {len([d for d in have if d.weekday() >= 5])}')
        reports = {k[len(report_prefix):-5] for k in keys(r2, report_prefix) if k.endswith('.json')}
        rep_days = {date.fromisoformat(x) for x in reports if len(x) == 10}
        out.append(f'- Daily collection reports ({report_prefix}): {len(rep_days)} days, {runs(rep_days)}')
        out.append('')
    out.append('### Markers and state')
    for prefix in ('archive/announcement_backfill/collection/', 'archive/announcement_backfill/collection-days/',
                   'archive/announcement_backfill/ai-days/'):
        ks = keys(r2, prefix)
        out.append(f'- `{prefix}`: {len(ks)} objects; first {[k[len(prefix):] for k in ks[:3]]} last {[k[len(prefix):] for k in ks[-3:]]}')
    for k in ks_state(r2):
        out.append(k)
    out.append('')
    out.append('### raw_v2 fetch days (the exact exchange answers)')
    for source in ('nse', 'bse'):
        pages = r2.get_paginator('list_objects_v2').paginate(Bucket=BUCKET, Prefix=f'raw_v2/{source}/', Delimiter='/')
        for p in pages:
            for c in p.get('CommonPrefixes', []):
                ds = c['Prefix']
                if 'announce' not in ds.lower():
                    continue
                dpages = r2.get_paginator('list_objects_v2').paginate(Bucket=BUCKET, Prefix=ds + 'fetches/', Delimiter='/')
                days = {date.fromisoformat(x['Prefix'].rstrip('/').split('/')[-1]) for dp in dpages
                        for x in dp.get('CommonPrefixes', []) if len(x['Prefix'].rstrip('/').split('/')[-1]) == 10}
                out.append(f'- `{ds}`: {len(days)} fetch days, {runs(days)}')
    text = '\n'.join(out) + '\n'
    print(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as f:
            f.write(text)
    return 0


def ks_state(r2):
    for k in ('archive/announcement_backfill/state.json', 'archive/announcement_pipeline/state.json'):
        try:
            body = json.loads(r2.get_object(Bucket=BUCKET, Key=k)['Body'].read())
            yield f'- `{k}`: `{json.dumps(body, default=str)[:900]}`'
        except Exception as exc:  # noqa: BLE001
            yield f'- `{k}`: not read ({type(exc).__name__})'


if __name__ == '__main__':
    sys.exit(main())
