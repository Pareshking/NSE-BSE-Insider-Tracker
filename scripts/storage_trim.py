"""Keep the R2 bucket small (owner, 15 Nov 2026: "bring it to 1 GB or less"; "delete results_xbrl and filing_text first").

Steps, each a dry run unless --delete is given (it lists what would go and the bytes):

  results_xbrl   raw_v2/nse/results_xbrl/: the raw XBRL of every results filing whose facts are already in the archive
                 (archive/nse_events/results, xbrl_status ok, facts present and parsed: checked by clean_peek
                 RESULTS_CHECK, 15 Nov: 25,815 of 25,815). Blobs and fetch records of filings NOT read (failed) are
                 kept, so they can be retried. The clean table is rebuilt from the archive every night, never from raw.
  filing_text    archive/filing_text/: day files older than FILING_TEXT_DAYS (by the day in the key, the broadcast day).
                 Only the switched-off announcement reader reads it.
  report         objects and bytes per top folder, and the total against the target.

    python scripts/storage_trim.py results_xbrl filing_text report [--delete]
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

from clean_writer import read_parquet  # noqa: E402
from r2_writer import BUCKET, r2_client  # noqa: E402

FILING_TEXT_DAYS = int(os.environ.get('FILING_TEXT_DAYS', '90'))
TARGET_GB = float(os.environ.get('STORAGE_TARGET_GB', '1'))
DAY_KEY = re.compile(r'year=(\d{4})/month=(\d{2})/day=(\d{2})')


def listing(client, prefix: str):
    token = None
    while True:
        kw = {'Bucket': BUCKET, 'Prefix': prefix}
        if token:
            kw['ContinuationToken'] = token
        resp = client.list_objects_v2(**kw)
        for o in resp.get('Contents', []):
            yield o['Key'], o['Size']
        if not resp.get('IsTruncated'):
            return
        token = resp['NextContinuationToken']


def delete(client, keys: list[str]) -> None:
    for i in range(0, len(keys), 1000):
        client.delete_objects(Bucket=BUCKET, Delete={'Objects': [{'Key': k} for k in keys[i:i + 1000]], 'Quiet': True})


def results_xbrl_doomed(client) -> tuple[list[tuple[str, int]], int]:
    """(objects to delete, objects kept): fetch records and blobs of filings whose facts are in the archive."""
    import pandas as pd
    frames = [f for f in (read_parquet(client, f'archive/nse_events/results/year={y}.parquet') for y in (2025, 2026, 2027))
              if f is not None]
    if not frames:
        raise SystemExit('no results archive: nothing is deleted')
    a = pd.concat(frames, ignore_index=True)
    ok = a[a['xbrl_status'].astype(str).eq('ok') & a['xbrl_json'].astype(str).str.len().ge(50)]
    done_urls = set(ok['xbrl_url'].dropna())
    keep_urls = set(a.loc[~a['xbrl_url'].isin(done_urls), 'xbrl_url'].dropna())
    objs = dict(listing(client, 'raw_v2/nse/results_xbrl/'))
    doomed, kept_blobs = [], set()
    fetch_keys = [k for k in objs if '/fetches/' in k]

    def read(k):
        return k, json.loads(client.get_object(Bucket=BUCKET, Key=k)['Body'].read())
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=24) as pool:   # 33,000 small reads: one at a time took over half an hour
        for k, rec in pool.map(read, fetch_keys):
            if rec.get('url') in keep_urls or rec.get('url') not in done_urls:
                kept_blobs.add(rec.get('blob_key'))
                continue
            doomed.append((k, objs[k]))
    for k, sz in objs.items():
        if '/blobs/' in k and k not in kept_blobs:
            doomed.append((k, sz))
    return doomed, len(objs) - len(doomed)


def filing_text_doomed(client, today: date) -> list[tuple[str, int]]:
    cutoff = today - timedelta(days=FILING_TEXT_DAYS)
    out = []
    for k, sz in listing(client, 'archive/filing_text/'):
        m = DAY_KEY.search(k)
        if m and date(int(m[1]), int(m[2]), int(m[3])) < cutoff:
            out.append((k, sz))
    return out


def report(client) -> float:
    top = {}
    for k, sz in listing(client, ''):
        t = k.split('/')[0]
        n, b = top.get(t, (0, 0))
        top[t] = (n + 1, b + sz)
    total = sum(b for _, b in top.values()) / 1e9
    for t, (n, b) in sorted(top.items(), key=lambda kv: -kv[1][1]):
        print(f'  {t + "/":<14}{n:>9,} objects {b / 1e9:>8.3f} GB')
    print(f'  TOTAL {total:.3f} GB (target {TARGET_GB:g} GB)')
    return total


def main(argv: list[str]) -> int:
    do_delete = '--delete' in argv
    steps = [a for a in argv if not a.startswith('--')] or ['report']
    client = r2_client()
    today = date.today()
    for step in steps:
        if step == 'results_xbrl':
            doomed, kept = results_xbrl_doomed(client)
            print(f'results_xbrl: {len(doomed):,} objects, {sum(s for _, s in doomed) / 1e9:.3f} GB to delete; '
                  f'{kept:,} kept (filings not read)')
        elif step == 'filing_text':
            doomed = filing_text_doomed(client, today)
            print(f'filing_text: {len(doomed):,} day files older than {FILING_TEXT_DAYS} days, '
                  f'{sum(s for _, s in doomed) / 1e9:.3f} GB to delete')
        elif step == 'report':
            report(client)
            continue
        else:
            raise SystemExit(f'unknown step {step}')
        if do_delete and doomed:
            delete(client, [k for k, _ in doomed])
            print(f'  deleted {len(doomed):,} objects')
        elif doomed:
            print('  dry run: add --delete to delete')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
