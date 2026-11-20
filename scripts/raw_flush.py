"""Move locally captured raw responses into the write-once R2 raw layer.

    python scripts/raw_flush.py [--dir artifacts/raw_capture] [--workers 16]

Run after the collectors, in a step that has the R2 secrets. Each capture is
stored byte for byte (insiders_clean/raw_store.py) with its original fetch
time; a capture is only deleted from the runner's disk after R2 confirmed it.
Exits non-zero if anything could not be stored, so the run is not shown as
fully successful. A missing or empty folder is not an error (a collector may
have fetched nothing).

Each capture costs up to five R2 calls (a HEAD or two and two PUTs), about a
second one after the other: 20 Nov 2026 the industry run's 3,000-odd answers
were still being stored after 48 minutes when the job's timeout cancelled it.
`workers` stores captures side by side (boto3 clients are thread-safe; every
object is write-once and named by content, so order does not matter). A
collector may also call `flush` while it is still capturing (scripts/industry.py
does, every few hundred answers): a capture's .json is renamed into place only
after its .body is written (scripts/raw_capture.py), so a listed .json always
has its body.
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

from insiders_clean.raw_store import RawStore  # noqa: E402


def _store_one(client, bucket, commit_label, meta_path: Path) -> tuple[int, int]:
    """Store one capture, then delete it from disk. Returns (blobs written, blobs reused)."""
    store = RawStore(client, bucket=bucket, collector=commit_label)
    body_path = meta_path.with_suffix('.body')
    m = json.loads(meta_path.read_text())
    body = body_path.read_bytes()
    store.put(m['source'], m['dataset'], body, url=m['url'], params=m.get('params'),
              status=m.get('status', 200), content_type=m.get('content_type'),
              covers=m.get('covers'), fetched_at=datetime.fromisoformat(m['fetched_at_utc']))
    meta_path.unlink()
    body_path.unlink()
    return store.written, store.reused


def flush(client, directory: Path, bucket=None, commit_label='nightly', workers: int = 1) -> dict:
    out = {'found': 0, 'stored': 0, 'failed': 0, 'errors': [], 'blobs_written': 0, 'blobs_reused': 0}
    paths = sorted(directory.glob('*.json')) if directory.exists() else []
    out['found'] = len(paths)

    def one(meta_path):
        try:
            return meta_path, _store_one(client, bucket, commit_label, meta_path), None
        except Exception as e:  # noqa: BLE001
            return meta_path, None, f'{meta_path.name}: {type(e).__name__}: {e}'

    if workers > 1 and len(paths) > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(one, paths))
    else:
        results = [one(p) for p in paths]
    for _, counts, err in results:
        if err:
            out['failed'] += 1
            out['errors'].append(err)
        else:
            out['stored'] += 1
            out['blobs_written'] += counts[0]
            out['blobs_reused'] += counts[1]
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', default='artifacts/raw_capture')
    ap.add_argument('--workers', type=int, default=1, help='captures stored side by side')
    args = ap.parse_args(argv)
    import r2_writer
    res = flush(r2_writer.r2_client(), Path(args.dir), bucket=r2_writer.BUCKET, workers=args.workers)
    print(json.dumps({k: v for k, v in res.items() if k != 'errors'}))
    for e in res['errors'][:20]:
        print('  FAILED', e)
    return 1 if res['failed'] else 0


if __name__ == '__main__':
    sys.exit(main())
