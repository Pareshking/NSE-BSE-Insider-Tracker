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
import threading
from datetime import datetime, timezone
from pathlib import Path

DIR = Path(os.environ.get('RAW_CAPTURE_DIR', 'artifacts/raw_capture'))
_failures = 0
# Collectors that fetch side by side (scripts/mf_portfolios.py: a thread per fund house) capture from several threads:
# one at a time, so two captures never share a name and the failure count is exact.
_LOCK = threading.Lock()


def capture(source: str, dataset: str, body, *, url: str, params: dict | None = None, status: int = 200,
            content_type: str | None = None, covers: dict | None = None) -> str | None:
    with _LOCK:
        return _capture(source, dataset, body, url=url, params=params, status=status, content_type=content_type,
                        covers=covers)


def _capture(source, dataset, body, *, url, params, status, content_type, covers) -> str | None:
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
        # the .json last and renamed into place: a flush running while the collector still captures
        # (scripts/industry.py) lists *.json, so it never sees a half-written record or a record without its body
        tmp = DIR / f'{name}.json.part'
        tmp.write_text(json.dumps(meta, sort_keys=True))
        os.replace(tmp, DIR / f'{name}.json')
        return name
    except Exception as e:  # noqa: BLE001
        _failures += 1
        print(f'raw_capture: could not save {source}/{dataset}: {type(e).__name__}: {e}', file=sys.stderr)
        return None
