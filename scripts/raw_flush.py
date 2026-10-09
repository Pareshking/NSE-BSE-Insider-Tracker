"""Move locally captured raw responses into the write-once R2 raw layer.

    python scripts/raw_flush.py [--dir artifacts/raw_capture]

Run after the collectors, in a step that has the R2 secrets. Each capture is
stored byte for byte (insiders_clean/raw_store.py) with its original fetch
time; a capture is only deleted from the runner's disk after R2 confirmed it.
Exits non-zero if anything could not be stored, so the run is not shown as
fully successful. A missing or empty folder is not an error (a collector may
have fetched nothing).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

from insiders_clean.raw_store import RawStore  # noqa: E402


def flush(client, directory: Path, bucket=None, commit_label='nightly') -> dict:
    store = RawStore(client, bucket=bucket, collector=commit_label)
    out = {'found': 0, 'stored': 0, 'failed': 0, 'errors': []}
    for meta_path in sorted(directory.glob('*.json')) if directory.exists() else []:
        out['found'] += 1
        body_path = meta_path.with_suffix('.body')
        try:
            m = json.loads(meta_path.read_text())
            body = body_path.read_bytes()
            store.put(m['source'], m['dataset'], body, url=m['url'], params=m.get('params'),
                      status=m.get('status', 200), content_type=m.get('content_type'),
                      covers=m.get('covers'), fetched_at=datetime.fromisoformat(m['fetched_at_utc']))
            meta_path.unlink()
            body_path.unlink()
            out['stored'] += 1
        except Exception as e:  # noqa: BLE001
            out['failed'] += 1
            out['errors'].append(f'{meta_path.name}: {type(e).__name__}: {e}')
    out['blobs_written'], out['blobs_reused'] = store.written, store.reused
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', default='artifacts/raw_capture')
    args = ap.parse_args(argv)
    import r2_writer
    res = flush(r2_writer.r2_client(), Path(args.dir), bucket=r2_writer.BUCKET)
    print(json.dumps({k: v for k, v in res.items() if k != 'errors'}))
    for e in res['errors'][:20]:
        print('  FAILED', e)
    return 1 if res['failed'] else 0


if __name__ == '__main__':
    sys.exit(main())
