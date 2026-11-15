"""Keep the R2 bucket small (owner, 15 Nov 2026: "bring it to 1 GB or less"; "delete results_xbrl and filing_text first").

Steps, each a dry run unless --delete is given (it lists what would go and the bytes):

  results_xbrl   raw_v2/nse/results_xbrl/: the raw XBRL of every results filing whose facts are already in the archive
                 (archive/nse_events/results, xbrl_status ok, facts present and parsed: checked by clean_peek
                 RESULTS_CHECK, 15 Nov: 25,815 of 25,815). Blobs and fetch records of filings NOT read (failed) are
                 kept, so they can be retried. The clean table is rebuilt from the archive every night, never from raw.
  filing_text    archive/filing_text/: day files older than FILING_TEXT_DAYS (0: all but today's) (by the day in the key, the broadcast day).
                 Only the switched-off announcement reader reads it.
  compress       raw_v2/ text blobs (json, csv, xml, html, bin), raw/ and reference/market_cap/ JSON kept plain: each is gzipped (mtime 0) to `{key}.gz`, the
                 gzip is checked to give back the exact bytes and their SHA-256 (the blob's own name), written, then
                 the plain copy is deleted. Nothing is lost: readers take `{key}.gz` when the plain key is gone
                 (insiders_clean.raw_store.read_blob). A blob that gzips to more than 90% of its size is left as it is.
  price_zips     raw_v2/exchange_files/nse_pr_zip/: blobs of NSE PR zips for days older than PRICE_ZIP_DAYS (30).
                 The fetch records stay (URL, day, SHA-256: NSE keeps the file at that URL), and a list of what went is
                 written to manifests/storage_trim/. The parsed market caps stay in marketcap/daily/nse/.
  report         objects and bytes per top folder, and the total against the target. With --limit-gb the job fails
                 when the bucket is above that (the weekly guard).

    python scripts/storage_trim.py results_xbrl filing_text compress report [--delete] [--limit-gb 5]
"""
from __future__ import annotations

import gzip
import hashlib
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

# 15 Nov 2026: 0 (owner: no announcement reader or AI reading planned; the text is deleted, the code kept). Set
# FILING_TEXT_DAYS to keep some again if the reader comes back.
FILING_TEXT_DAYS = int(os.environ.get('FILING_TEXT_DAYS', '0'))
PRICE_ZIP_DAYS = int(os.environ.get('PRICE_ZIP_DAYS', '30'))
TARGET_GB = float(os.environ.get('STORAGE_TARGET_GB', '1'))
DAY_KEY = re.compile(r'year=(\d{4})/month=(\d{2})/day=(\d{2})')
PACK_EXT = ('.json', '.csv', '.xml', '.html', '.bin')
# Our own snapshots, read through clean_writer.get / r2_data._get_bytes, which fall back to {key}.gz (15 Nov 2026).
PLAIN_GZ_PREFIXES = ('raw/', 'reference/market_cap/')
SHA_NAME = re.compile(r'/([0-9a-f]{64})\.[a-z]+$')


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
    why = {'failed_filing': 0, 'url_not_in_archive': 0, 'other_status': 0}
    samples = []

    def read(k):
        return k, json.loads(client.get_object(Bucket=BUCKET, Key=k)['Body'].read())
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=24) as pool:   # 33,000 small reads: one at a time took over half an hour
        for k, rec in pool.map(read, fetch_keys):
            if rec.get('url') in keep_urls or rec.get('url') not in done_urls:
                kept_blobs.add(rec.get('blob_key'))
                kind = ('failed_filing' if rec.get('url') in keep_urls else
                        'other_status' if rec.get('http_status') != 200 else 'url_not_in_archive')
                why[kind] += 1
                if kind != 'failed_filing' and len(samples) < 5:
                    samples.append({x: rec.get(x) for x in ('url', 'http_status', 'bytes', 'fetched_at_utc', 'content_check')})
                continue
            doomed.append((k, objs[k]))
    kept_blobs |= {b + '.gz' for b in kept_blobs if b}   # a blob compressed in place keeps its fetch record's name
    for k, sz in objs.items():
        if '/blobs/' in k and k not in kept_blobs:
            doomed.append((k, sz))
    orphans = sum(1 for k in objs if '/blobs/' in k and k in kept_blobs)
    print(f'  kept fetch records by reason: {why}; kept blobs {orphans:,}; archive urls {len(set(a["xbrl_url"].dropna())):,}')
    for x in samples:
        print(f'  kept example: {json.dumps(x, default=str)[:300]}')
    return doomed, len(objs) - len(doomed)


def filing_text_doomed(client, today: date) -> list[tuple[str, int]]:
    cutoff = today - timedelta(days=FILING_TEXT_DAYS)
    out = []
    for k, sz in listing(client, 'archive/filing_text/'):
        m = DAY_KEY.search(k)
        if m and date(int(m[1]), int(m[2]), int(m[3])) < cutoff:
            out.append((k, sz))
    return out


def compress(client, do_delete: bool) -> None:
    objs = dict(listing(client, 'raw_v2/'))
    todo = [(k, sz) for k, sz in objs.items() if '/blobs/' in k and k.endswith(PACK_EXT) and sz >= 1024]
    for prefix in PLAIN_GZ_PREFIXES:   # not named by hash: the round trip is the check
        todo += [(k, sz) for k, sz in listing(client, prefix) if k.endswith('.json') and sz >= 1024]
    print(f'compress: {len(todo):,} plain text objects, {sum(s for _, s in todo) / 1e9:.3f} GB')
    if not todo:
        return
    if not do_delete:
        todo = todo[::max(1, len(todo) // 300)]   # dry run: a sample, to say what it would save
    counts = {'packed': 0, 'kept_poor_ratio': 0, 'kept_name_mismatch': 0, 'bytes_before': 0, 'bytes_after': 0}

    def one(item):
        key, size = item
        data = client.get_object(Bucket=BUCKET, Key=key)['Body'].read()
        if key.startswith('raw_v2/'):
            m = SHA_NAME.search(key)
            if not m or hashlib.sha256(data).hexdigest() != m[1]:
                return 'kept_name_mismatch', size, size
        packed = gzip.compress(data, 9, mtime=0)
        if len(packed) > 0.9 * len(data):
            return 'kept_poor_ratio', size, size
        if gzip.decompress(packed) != data:   # never: checked before anything is deleted
            return 'kept_name_mismatch', size, size
        if do_delete:
            client.put_object(Bucket=BUCKET, Key=key + '.gz', Body=packed, ContentType='application/gzip')
            head = client.head_object(Bucket=BUCKET, Key=key + '.gz')
            if int(head['ContentLength']) != len(packed):
                raise SystemExit(f'{key}.gz: written size differs; the plain copy is kept')
            client.delete_object(Bucket=BUCKET, Key=key)
        return 'packed', size, len(packed)

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=24) as pool:
        for state, before, after in pool.map(one, todo):
            counts[state] += 1
            counts['bytes_before'] += before
            counts['bytes_after'] += after
    ratio = counts['bytes_after'] / max(1, counts['bytes_before'])
    word = 'done' if do_delete else f'dry run on a sample of {len(todo):,}; about {ratio:.0%} of the size would remain'
    print(f'  {word}: ' + ', '.join(f'{k} {v:,}' for k, v in counts.items()))


def price_zips_doomed(client, today: date) -> tuple[list[tuple[str, int]], list[dict]]:
    """(blobs to delete, what each was): a blob goes when every fetch record naming it covers a day before the cutoff."""
    prefix = 'raw_v2/exchange_files/nse_pr_zip/'
    objs = dict(listing(client, prefix))
    cutoff = (today - timedelta(days=PRICE_ZIP_DAYS)).isoformat()

    def read(k):
        return json.loads(client.get_object(Bucket=BUCKET, Key=k)['Body'].read())
    from concurrent.futures import ThreadPoolExecutor
    newest: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=24) as pool:
        for rec in pool.map(read, [k for k in objs if '/fetches/' in k and k.endswith('.json')]):
            b, day = rec.get('blob_key'), (rec.get('covers') or {}).get('day') or ''
            if b and day >= str((newest.get(b) or {}).get('day', '')):
                newest[b] = {'blob_key': b, 'day': day, 'url': rec.get('url'), 'sha256': rec.get('sha256')}
    gone = [v for v in newest.values() if v['day'] and v['day'] < cutoff and v['blob_key'] in objs]
    return [(v['blob_key'], objs[v['blob_key']]) for v in gone], gone


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
    limit = float(argv[argv.index('--limit-gb') + 1]) if '--limit-gb' in argv else None
    steps = [a for i, a in enumerate(argv) if not a.startswith('--') and argv[i - 1:i] != ['--limit-gb']] or ['report']
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
        elif step == 'price_zips':
            doomed, gone = price_zips_doomed(client, today)
            print(f'price_zips: {len(doomed):,} NSE PR zips for days before the last {PRICE_ZIP_DAYS}, '
                  f'{sum(s for _, s in doomed) / 1e9:.3f} GB to delete (fetch records kept)')
            if do_delete and gone:
                client.put_object(Bucket=BUCKET, Key=f'manifests/storage_trim/nse_pr_zip_pruned_{today.isoformat()}.json',
                                  Body=json.dumps(gone, indent=1).encode(), ContentType='application/json')
        elif step == 'compress':
            compress(client, do_delete)
            continue
        elif step == 'report':
            total = report(client)
            if limit is not None and total > limit:
                print(f'::error::bucket is {total:.2f} GB, above the {limit:g} GB limit')
                return 1
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
