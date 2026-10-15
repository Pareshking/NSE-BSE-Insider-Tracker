"""What NSE and BSE actually send for announcements, and what our archive kept (read-only).

1. raw_v2 (the exact bytes): for every NSE and BSE dataset whose name mentions announcements, the latest fetch
   records (URL, HTTP status, bytes) and the latest successful body: its shape, every field name with how often
   it is filled, the fields that mention xbrl/xml/attach/file, and two sample rows.
2. archive/announcements/{nse,bse}/: the newest partition's columns, has_xbrl, xbrl_url and file_type counts.
3. The reader's saved state: today's usage ledger files, rate-limit markers, backfill and pipeline checkpoints.
Writes nothing; no model and no exchange is called. Markdown to stdout and $GITHUB_STEP_SUMMARY.
"""
from __future__ import annotations

import io
import json
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from r2_writer import BUCKET, r2_client  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
HINTS = ('xbrl', 'xml', 'attach', 'file', 'pdf', 'url')
out: list[str] = []


def say(*lines):
    out.extend(lines)


def short(v, n=160):
    s = json.dumps(v, default=str, ensure_ascii=False) if not isinstance(v, str) else v
    return s if len(s) <= n else s[:n] + '...'


def subdirs(r2, prefix):
    pages = r2.get_paginator('list_objects_v2').paginate(Bucket=BUCKET, Prefix=prefix, Delimiter='/')
    return [p['Prefix'] for page in pages for p in page.get('CommonPrefixes', [])]


def keys(r2, prefix):
    pages = r2.get_paginator('list_objects_v2').paginate(Bucket=BUCKET, Prefix=prefix)
    return [o['Key'] for page in pages for o in page.get('Contents', [])]


def body(r2, key):
    return r2.get_object(Bucket=BUCKET, Key=key)['Body'].read()


def rows_of(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ('data', 'Table', 'Table1', 'rows', 'result'):
            if isinstance(data.get(k), list):
                return data[k]
    return []


def raw_dataset(r2, prefix):
    say(f'#### `{prefix}`')
    days = sorted(subdirs(r2, prefix + 'fetches/'))
    if not days:
        say('No fetch records.', '')
        return
    recent = []
    for day in days[-3:]:
        recent += sorted(keys(r2, day))
    records = [json.loads(body(r2, k)) for k in recent[-40:]]
    status = Counter(r.get('http_status') for r in records)
    say(f'Fetch days {days[0].split("/")[-2]} to {days[-1].split("/")[-2]}; last {len(records)} fetches by HTTP '
        f'status: {dict(status)}')
    for r in records[-3:]:
        say(f'- {r.get("fetched_at_utc")} HTTP {r.get("http_status")} {r.get("bytes")} bytes `{short(r.get("url"), 200)}`')
    ok = [r for r in records if r.get('http_status') == 200 and r.get('bytes', 0) > 2]
    if not ok:
        say('No successful non-empty body among these fetches.', '')
        return
    rec = ok[-1]
    raw = body(r2, rec['blob_key'])
    try:
        data = json.loads(raw)
    except ValueError:
        say(f'Latest body is not JSON ({len(raw)} bytes): `{short(raw[:200].decode("utf-8", "replace"))}`', '')
        return
    rows = rows_of(data)
    top = list(data.keys())[:20] if isinstance(data, dict) else f'list of {len(data)}'
    say(f'Latest successful body: top level {short(top)}; {len(rows)} rows.')
    if not rows:
        say(f'Body: `{short(data, 400)}`', '')
        return
    filled = Counter()
    for row in rows:
        for k, v in (row.items() if isinstance(row, dict) else []):
            if v not in (None, '', '-', [], {}):
                filled[k] += 1
    names = sorted({k for row in rows if isinstance(row, dict) for k in row})
    say('Fields (filled in how many rows): ' + ', '.join(f'`{k}` {filled[k]}' for k in names))
    hinted = [k for k in names if any(h in k.lower() for h in HINTS)]
    for k in hinted:
        values = Counter(str(row.get(k))[:120] for row in rows if isinstance(row, dict))
        say(f'- `{k}`: {len(values)} distinct; most common {short(values.most_common(4), 400)}')
    flagged = [row for row in rows if isinstance(row, dict)
               and any('xbrl' in k.lower() and str(v).strip().lower() in ('true', '1', 'yes') for k, v in row.items())]
    if flagged:
        say(f'Rows with an xbrl flag true: {len(flagged)}; first: `{short(flagged[0], 900)}`')
    for row in rows[:2]:
        say(f'Sample row: `{short(row, 900)}`')
    say('')


def archive(r2, prefix):
    say(f'#### `{prefix}`')
    parts = sorted(k for k in keys(r2, prefix) if k.endswith('.parquet'))
    if not parts:
        say('No partitions.', '')
        return
    df = pd.read_parquet(io.BytesIO(body(r2, parts[-1])))
    say(f'{len(parts)} partitions; newest `{parts[-1]}`: {len(df)} rows, columns {list(df.columns)}')
    for col in ('has_xbrl', 'file_type', 'market', 'group', 'category', 'subcategory'):
        if col in df:
            say(f'- `{col}`: {short(df[col].astype(str).value_counts().head(10).to_dict(), 500)}')
    for col in ('xbrl_url', 'file_url', 'attachment'):
        if col in df:
            s = df[col].dropna().astype(str)
            say(f'- `{col}` filled {len(s)} of {len(df)}; e.g. {short(s.head(3).tolist(), 400)}')
    say('')


def state(r2):
    today = datetime.now(IST).date().isoformat()
    say('### 3. Reader state in R2', '')
    for k in ('archive/announcement_backfill/state.json', 'archive/announcement_pipeline/state.json'):
        try:
            say(f'- `{k}`: `{short(json.loads(body(r2, k)), 1500)}`')
        except Exception as exc:  # noqa: BLE001
            say(f'- `{k}`: not read ({type(exc).__name__})')
    for prefix in (f'clean/reports/announcement_reader/{today}', 'clean/reports/announcement_reader/rate-limits/'):
        ks = keys(r2, prefix)
        say(f'- `{prefix}*`: {len(ks)} objects; last {short(ks[-5:], 600)}')
    day = f'clean/reports/announcement_reader/{today}.json'
    try:
        runs = json.loads(body(r2, day)).get('runs', [])
        calls = Counter()
        for r in runs:
            for m, e in ((r.get('usage') or {}).get('models') or {}).items():
                calls[m] += int(e.get('calls') or 0)
        say(f'- `{day}`: {len(runs)} entries; calls by model {dict(calls)}')
    except Exception as exc:  # noqa: BLE001
        say(f'- `{day}`: not read ({type(exc).__name__})')
    say('')


def main() -> int:
    r2 = r2_client()
    say('## Announcement sources: what the exchanges send and what we keep', '', '### 1. Raw responses (raw_v2)', '')
    for source in ('nse', 'bse'):
        for ds in subdirs(r2, f'raw_v2/{source}/'):
            if 'announce' in ds.lower() or 'xbrl' in ds.lower():
                try:
                    raw_dataset(r2, ds)
                except Exception as exc:  # noqa: BLE001
                    say(f'`{ds}`: not read ({type(exc).__name__}: {exc})', '')
    say('### 2. Archive tables', '')
    for prefix in ('archive/announcements/nse/', 'archive/announcements/bse/'):
        archive(r2, prefix)
    state(r2)
    text = '\n'.join(out) + '\n'
    print(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as f:
            f.write(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
