"""Collector-side raw capture: save the exact response bytes the moment they
arrive, before any parsing, to a local folder (no credentials needed).

    from raw_capture import capture
    capture('nse', 'bulk_deals', response_bytes, url=url, params=..., status=200,
            content_type='application/json', covers={'from': ..., 'to': ...})

`scripts/raw_flush.py` then moves everything in that folder into the
write-once R2 raw layer (insiders_clean/raw_store.py) in one step that holds
the R2 secrets, so no collector needs them. Capture never raises: a failure to
write the local copy is logged and counted (the flush step reports the count)
and never changes what the collector parses.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

DIR = Path(os.environ.get('RAW_CAPTURE_DIR', 'artifacts/raw_capture'))
_failures = 0


def capture(source: str, dataset: str, body, *, url: str, params: dict | None = None, status: int = 200,
            content_type: str | None = None, covers: dict | None = None) -> str | None:
    global _failures
    try:
        if body is None:
            return None
        data = body.encode('utf-8') if isinstance(body, str) else bytes(body)
        digest = hashlib.sha256(data).hexdigest()
        now = datetime.now(timezone.utc)
        name = f'{now:%Y%m%dT%H%M%S%fZ}_{digest[:12]}'
        DIR.mkdir(parents=True, exist_ok=True)
        (DIR / f'{name}.body').write_bytes(data)
        meta = {'source': source, 'dataset': dataset, 'url': url, 'params': params or {}, 'status': status,
                'content_type': content_type, 'fetched_at_utc': now.isoformat(), 'sha256': digest,
                'bytes': len(data), 'covers': covers or {}}
        (DIR / f'{name}.json').write_text(json.dumps(meta, sort_keys=True))
        return name
    except Exception as e:  # noqa: BLE001
        _failures += 1
        print(f'raw_capture: could not save {source}/{dataset}: {type(e).__name__}: {e}', file=sys.stderr)
        return None
