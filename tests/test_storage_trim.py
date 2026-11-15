"""scripts/storage_trim.py: compress in place, and the results XBRL trim never deletes raw of a filing not read."""
from __future__ import annotations

import gzip
import json

import pandas as pd
import storage_trim as st
from test_archive_and_writer import FakeR2, parquet

from insiders_clean import raw_store
from insiders_clean.raw_store import sha256_hex


class R2(FakeR2):
    def head_object(self, Bucket, Key):
        super().head_object(Bucket, Key)
        return {'ContentLength': len(self.objects[Key])}

    def delete_object(self, Bucket, Key):
        self.objects.pop(Key)


def blob(r2, dataset, body, ext):
    d = sha256_hex(body)
    key = f'raw_v2/nse/{dataset}/blobs/{d[:2]}/{d}.{ext}'
    r2.objects[key] = body
    return key


def test_compress_keeps_exact_bytes_and_skips_poor_ratio_and_wrong_names():
    r2 = R2()
    text = b'{"rows": [' + b'{"a": 1, "b": "same text"},' * 200 + b'{}]}'
    k = blob(r2, 'announcements', text, 'json')
    noise = bytes(range(256)) * 8
    k_noise = blob(r2, 'announcements', gzip.compress(noise), 'bin')    # already packed: left as it is
    r2.objects['raw_v2/nse/x/blobs/ab/' + 'a' * 64 + '.json'] = text        # name is not its hash: left alone
    st.compress(r2, do_delete=True)
    assert k not in r2.objects and gzip.decompress(r2.objects[k + '.gz']) == text
    assert raw_store.read_blob(lambda key: r2.objects.get(key), k) == text
    assert k_noise in r2.objects and 'raw_v2/nse/x/blobs/ab/' + 'a' * 64 + '.json' in r2.objects


def test_results_xbrl_trim_keeps_raw_of_unread_filing_after_it_was_compressed():
    r2 = R2()
    archive = pd.DataFrame({'xbrl_url': ['https://n/read.xml', 'https://n/failed.xml'],
                            'xbrl_status': ['ok', 'RuntimeError'],
                            'xbrl_json': [json.dumps({'facts': 'x' * 80}), '']})
    r2.objects['archive/nse_events/results/year=2026.parquet'] = parquet(archive)
    read = blob(r2, 'results_xbrl', b'<xbrl>read</xbrl>' * 100, 'xml')
    failed = blob(r2, 'results_xbrl', b'<xbrl>failed</xbrl>' * 100, 'xml')
    for name, url, key in (('a', 'https://n/read.xml', read), ('b', 'https://n/failed.xml', failed)):
        r2.objects[f'raw_v2/nse/results_xbrl/fetches/2026-11-01/{name}.json'] = json.dumps(
            {'url': url, 'blob_key': key, 'http_status': 200}).encode()
    st.compress(r2, do_delete=True)                       # the failed filing's blob is now failed + '.gz'
    doomed, kept = st.results_xbrl_doomed(r2)
    gone = {k for k, _ in doomed}
    assert gone == {read + '.gz', 'raw_v2/nse/results_xbrl/fetches/2026-11-01/a.json'}
    assert failed + '.gz' not in gone and kept == 2
