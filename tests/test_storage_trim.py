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


def test_compress_covers_snapshots_and_readers_fall_back():
    """raw/ and reference/market_cap/ are kept gzipped (15 Nov 2026); clean_writer.get reads them by the plain key."""
    import clean_writer
    r2 = R2()
    body = json.dumps([{'symbol': f'S{i}', 'market_cap': i * 1000} for i in range(200)], indent=2).encode()
    r2.objects['reference/market_cap/2026-11-14/data.json'] = body
    r2.objects['raw/nse/insider_trading/2026-11-14/raw.json'] = body
    r2.objects['clean/current/x.json'] = body                          # not in the list: left alone
    st.compress(r2, do_delete=True)
    assert 'reference/market_cap/2026-11-14/data.json' not in r2.objects
    assert clean_writer.get(r2, 'reference/market_cap/2026-11-14/data.json') == body
    assert clean_writer.get(r2, 'raw/nse/insider_trading/2026-11-14/raw.json') == body
    assert 'clean/current/x.json' in r2.objects
    assert clean_writer.get(r2, 'reference/market_cap/2026-11-13/data.json') is None


def test_writer_stores_snapshot_gzipped_and_drops_plain_copy():
    import r2_writer
    r2 = R2()
    r2.objects['reference/market_cap/2026-11-14/data.json'] = b'old'
    key = r2_writer.put_gz(r2, 'reference/market_cap/2026-11-14/data.json', b'[1, 2]')
    assert key.endswith('.gz') and gzip.decompress(r2.objects[key]) == b'[1, 2]'
    assert 'reference/market_cap/2026-11-14/data.json' not in r2.objects


def test_price_zips_go_after_30_days_fetch_records_stay():
    from datetime import date
    r2 = R2()
    for day, body in (('2026-09-01', b'PK old zip'), ('2026-11-10', b'PK new zip')):
        key = f'raw_v2/exchange_files/nse_pr_zip/blobs/{sha256_hex(body)[:2]}/{sha256_hex(body)}.zip'
        r2.objects[key] = body
        r2.objects[f'raw_v2/exchange_files/nse_pr_zip/fetches/{day}/x.json'] = json.dumps(
            {'blob_key': key, 'covers': {'day': day}, 'url': f'https://n/PR{day}.zip', 'sha256': sha256_hex(body)}).encode()
    # 21 Nov 2026: a zip whose members are not in archive/nse_pr/ yet stays (nothing may exist only in raw)
    assert st.price_zips_doomed(r2, date(2026, 11, 15)) == ([], [])
    r2.objects['archive/nse_pr/mcap_csv/2026-09.parquet'] = parquet(pd.DataFrame({'date': [pd.Timestamp('2026-09-01')]}))
    doomed, gone = st.price_zips_doomed(r2, date(2026, 11, 15))
    assert [g['day'] for g in gone] == ['2026-09-01'] and len(doomed) == 1 and doomed[0][0].endswith('.zip')
