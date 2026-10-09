"""Write-once raw layer: the exact bytes an exchange sent, plus how we got them.

Layout (all under `raw_v2/`, which no retention job touches):

    raw_v2/{source}/{dataset}/blobs/{sha256[:2]}/{sha256}.{ext}
        the response body, byte for byte. Named by its own SHA-256, so the
        same bytes fetched twice are one object and a name can never point at
        different content.
    raw_v2/{source}/{dataset}/fetches/{YYYY-MM-DD}/{UTC timestamp}_{sha256[:12]}.json
        one small record per fetch: URL, parameters, HTTP status, content
        type, UTC time, byte length, SHA-256, collector and its git commit,
        and the date range the request covered.

Nothing here ever overwrites or deletes. A blob is written with an
`If-None-Match: *` condition (R2 and S3 refuse the write if the key exists);
if the client library does not support the condition, existence is checked
first. A fetch record has a unique name (timestamp + hash), so two runs never
collide. Raw is never filtered: round trips, duplicates, amendments and
unreadable dates are all kept here and handled only in the clean layer.

The bucket itself should also have R2 object lock / a lifecycle rule that
forbids deletes under `raw_v2/`; code cannot prove that on its own.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone

PREFIX = 'raw_v2'
_EXT = {'application/json': 'json', 'text/csv': 'csv', 'text/html': 'html', 'application/xml': 'xml',
        'text/xml': 'xml', 'application/zip': 'zip'}


def sha256_hex(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _ext(content_type: str | None, body: bytes) -> str:
    ct = (content_type or '').split(';')[0].strip().lower()
    if ct in _EXT:
        return _EXT[ct]
    head = body[:1].lstrip()
    return 'json' if head[:1] in (b'{', b'[') else 'bin'


def _missing(err: Exception) -> bool:
    resp = getattr(err, 'response', None) or {}
    code = str(resp.get('Error', {}).get('Code', ''))
    status = resp.get('ResponseMetadata', {}).get('HTTPStatusCode')
    return code in ('404', 'NoSuchKey', 'NotFound') or status == 404 or type(err).__name__ == 'NoSuchKey'


class RawStore:
    def __init__(self, client, bucket: str | None = None, collector: str = 'unknown', clock=None):
        self.client = client
        self.bucket = bucket or os.environ.get('R2_BUCKET_NAME')
        self.collector = collector
        self.commit = os.environ.get('GITHUB_SHA', 'unknown')
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.written = 0
        self.reused = 0

    def _exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception as e:  # noqa: BLE001 - a missing key is the normal answer
            if _missing(e):
                return False
            raise

    def _put_once(self, key: str, body: bytes, content_type: str) -> bool:
        """True if written now, False if the key already held it."""
        if self._exists(key):
            return False
        try:
            self.client.put_object(Bucket=self.bucket, Key=key, Body=body, ContentType=content_type,
                                   IfNoneMatch='*')
        except TypeError:  # an older client without the condition: the existence check above stands
            self.client.put_object(Bucket=self.bucket, Key=key, Body=body, ContentType=content_type)
        except Exception as e:  # noqa: BLE001
            if getattr(e, 'response', {}).get('Error', {}).get('Code') in ('PreconditionFailed', '412'):
                return False  # someone wrote it between our check and our put: same content by name
            raise
        return True

    def put(self, source: str, dataset: str, body: bytes, *, url: str, params: dict | None = None,
            status: int = 200, content_type: str | None = None, covers: dict | None = None) -> dict:
        """Store one response. Returns the fetch record (with `blob_key`, `fetch_key`)."""
        digest = sha256_hex(body)
        ext = _ext(content_type, body)
        now = self.clock()
        blob_key = f'{PREFIX}/{source}/{dataset}/blobs/{digest[:2]}/{digest}.{ext}'
        if self._put_once(blob_key, body, content_type or 'application/octet-stream'):
            self.written += 1
        else:
            self.reused += 1
        record = {
            'source': source, 'dataset': dataset, 'url': url, 'params': params or {}, 'http_status': status,
            'content_type': content_type, 'fetched_at_utc': now.isoformat(), 'bytes': len(body),
            'sha256': digest, 'blob_key': blob_key, 'collector': self.collector,
            'collector_commit': self.commit, 'covers': covers or {},
        }
        fetch_key = (f'{PREFIX}/{source}/{dataset}/fetches/{now:%Y-%m-%d}/'
                     f'{now:%Y%m%dT%H%M%S%fZ}_{digest[:12]}.json')
        self._put_once(fetch_key, json.dumps(record, sort_keys=True).encode(), 'application/json')
        record['fetch_key'] = fetch_key
        return record
