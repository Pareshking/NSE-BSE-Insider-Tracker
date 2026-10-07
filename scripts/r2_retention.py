"""Weekly: delete dated NSE/BSE snapshots the archive has already absorbed.

What can go: raw/{exchange}/{category}/{date}/ and canonical/{exchange}/
{category}/{date}/ older than KEEP_DAYS, and NSE equity-list copies
(reference/security_lists/{date}/) older than LIST_KEEP_DAYS. Each dated
snapshot repeats a 90-day window, so once archive/ holds every record
(insiders_clean/archive.py) they are copies.

What stays, always: archive/, clean/, manifests/, cache/, the trading
calendar, and the market-cap history (reference/market_cap/, needed for "%
of market cap on the trade date").

Safety:
* Dry run unless R2_RETENTION_DELETE=1 -- it lists what it would delete and
  the bytes saved, and deletes nothing.
* A dataset's snapshots are only eligible when its archive exists and was
  last updated on or after the snapshot's date; with no archive, nothing of
  that dataset is touched.
* The newest KEEP_DAYS of snapshots are kept regardless, so the current
  site (which still reads dated canonical files) and a re-run of the
  archive both keep working.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

from clean_writer import CATEGORIES, archive_state_key, get
from r2_writer import BUCKET, TARGET_DATE, r2_client

KEEP_DAYS = int(os.environ.get('R2_RETENTION_KEEP_DAYS', '14'))
LIST_KEEP_DAYS = 30
ALL_CATEGORIES = CATEGORIES + ('rights_issue', 'preferential_issue')
DELETE = os.environ.get('R2_RETENTION_DELETE') == '1'


def eligible(keys_with_size, prefix, cutoff: date, absorbed_through: date | None):
    """Dated keys under `prefix` older than cutoff and covered by the archive."""
    out = []
    for key, size in keys_with_size:
        day = key[len(prefix):].split('/')[0]
        try:
            d = date.fromisoformat(day)
        except ValueError:
            continue
        if d < cutoff and (absorbed_through is None or d <= absorbed_through):
            out.append((key, size))
    return out


def list_with_size(client, prefix):
    out, token = [], None
    while True:
        kw = {'Bucket': BUCKET, 'Prefix': prefix}
        if token:
            kw['ContinuationToken'] = token
        resp = client.list_objects_v2(**kw)
        out += [(o['Key'], o['Size']) for o in resp.get('Contents', [])]
        if not resp.get('IsTruncated'):
            return out
        token = resp['NextContinuationToken']


def archive_through(client, exchange, category) -> date | None:
    """Last run date merged into this dataset's archive, from its state file."""
    body = get(client, archive_state_key(exchange, category))
    if body is None:
        return None
    last = json.loads(body).get('last_merged')
    return date.fromisoformat(last) if last else None


def main():
    client = r2_client()
    today = date.fromisoformat(TARGET_DATE)
    cutoff = today - timedelta(days=KEEP_DAYS)
    doomed = []
    for ex in ('nse', 'bse'):
        for cat in ALL_CATEGORIES:
            # Rights/preferential aren't archived yet (later PR): their
            # snapshots are kept until they are.
            through = archive_through(client, ex, cat) if cat in CATEGORIES else None
            if through is None:
                print(f'  keep all {ex}/{cat}: no archive')
                continue
            for top in ('raw', 'canonical'):
                prefix = f'{top}/{ex}/{cat}/'
                doomed += eligible(list_with_size(client, prefix), prefix, cutoff, through)
    prefix = 'reference/security_lists/'
    doomed += eligible(list_with_size(client, prefix), prefix, today - timedelta(days=LIST_KEEP_DAYS), None)

    total = sum(s for _, s in doomed)
    print(f'  {len(doomed)} objects, {total / 1e6:.1f} MB older than the kept window '
          f'({KEEP_DAYS} days) and already in the archive')
    if not DELETE:
        for key, _ in doomed[:20]:
            print(f'    would delete {key}')
        print('  dry run: set R2_RETENTION_DELETE=1 to delete')
        return
    for i in range(0, len(doomed), 1000):
        batch = [{'Key': k} for k, _ in doomed[i:i + 1000]]
        client.delete_objects(Bucket=BUCKET, Delete={'Objects': batch, 'Quiet': True})
    print(f'  deleted {len(doomed)} objects, {total / 1e6:.1f} MB')


if __name__ == '__main__':
    main()
