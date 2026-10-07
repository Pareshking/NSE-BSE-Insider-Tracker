"""Archive merge, and the nightly writer + weekly retention run end to end
against an in-memory R2 (no network: NSE list fetches are stubbed)."""
from __future__ import annotations

import io
import json

import pandas as pd
import pytest
from conftest import BSE_ROWS, FIXTURES, canonical

from insiders_clean import archive


class NoSuchKey(Exception):
    pass


class FakeR2:
    class exceptions:
        NoSuchKey = NoSuchKey

    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.deleted: list[str] = []

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise NoSuchKey(Key)
        return {'Body': io.BytesIO(self.objects[Key])}

    def put_object(self, Bucket, Key, Body, ContentType=None):
        self.objects[Key] = Body

    def list_objects_v2(self, Bucket, Prefix, ContinuationToken=None):
        return {'Contents': [{'Key': k, 'Size': len(v)} for k, v in sorted(self.objects.items())
                             if k.startswith(Prefix)], 'IsTruncated': False}

    def delete_objects(self, Bucket, Delete):
        for o in Delete['Objects']:
            self.objects.pop(o['Key'], None)
            self.deleted.append(o['Key'])


def parquet(df):
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    return buf.getvalue()


# --- archive.merge -----------------------------------------------------------

def test_merge_keeps_each_record_once_with_first_and_last_seen(real_nse_rows):
    day1 = canonical('nse', 'insider_trading', real_nse_rows[:10])
    day2 = canonical('nse', 'insider_trading', real_nse_rows[5:15])  # 5 overlap, 5 new
    arch, n1 = archive.merge(None, day1, '2026-10-05')
    arch, n2 = archive.merge(arch, day2, '2026-10-06')
    assert (n1, n2) == (10, 5) and len(arch) == 15
    ids = canonical('nse', 'insider_trading', real_nse_rows[5:6])['canonical_event_id'].iloc[0]
    row = arch[arch['canonical_event_id'] == ids].iloc[0]
    assert (row['first_seen'], row['last_seen']) == ('2026-10-05', '2026-10-06')
    gone = archive.possibly_withdrawn(arch, '2026-10-06')
    assert gone.sum() == 5  # seen on day 1 only, still inside the window


def test_merge_survives_type_drift(real_nse_rows):
    a = canonical('nse', 'insider_trading', real_nse_rows[:3])
    b = a.copy()
    b['appId'] = b['appId'].astype(int)  # same field, int one day, text the next
    b['canonical_event_id'] = b['canonical_event_id'] + 'x'
    arch, _ = archive.merge(None, a, '2026-10-05')
    arch, _ = archive.merge(arch, b, '2026-10-06')
    parquet(arch)  # must still write


# --- writer + retention against the fake bucket -------------------------------

@pytest.fixture()
def bucket(monkeypatch, real_nse_rows):
    import clean_writer
    import r2_retention
    r2 = FakeR2()
    days = ['2026-09-20', '2026-09-21', '2026-10-06']
    for i, day in enumerate(days):
        rows = real_nse_rows[: 60 + 30 * i]
        r2.objects[f'canonical/nse/insider_trading/{day}/data.parquet'] = parquet(
            canonical('nse', 'insider_trading', rows).drop(columns=['exchange', 'category']))
        r2.objects[f'raw/nse/insider_trading/{day}/raw.json'] = json.dumps(rows).encode()
    r2.objects['reference/market_cap/2026-10-06/data.json'] = json.dumps(BSE_ROWS).encode()

    class Resp:
        status_code = 200

        def __init__(self, path):
            self.content = path.read_bytes()

    sample = {'EQUITY_L': FIXTURES / 'nse_equity_sample.csv', 'SME_EQUITY_L': FIXTURES / 'nse_sme_sample.csv'}
    monkeypatch.setattr(clean_writer.requests, 'get',
                        lambda url, **kw: Resp(next(p for k, p in sample.items() if url.endswith(f'/{k}.csv'))))
    for mod in (clean_writer, r2_retention):
        monkeypatch.setattr(mod, 'r2_client', lambda: r2)
    monkeypatch.setattr(clean_writer, 'TARGET_DATE', '2026-10-07')
    monkeypatch.setattr(r2_retention, 'TARGET_DATE', '2026-10-07')
    return r2, clean_writer, r2_retention


def archive_frame(r2, prefix='archive/canonical/nse/insider_trading/'):
    keys = sorted(k for k in r2.objects if k.startswith(prefix) and k.endswith('.parquet'))
    return keys, pd.concat([pd.read_parquet(io.BytesIO(r2.objects[k])) for k in keys], ignore_index=True)


def test_first_run_builds_archive_and_clean_tables(bucket, real_nse_rows):
    r2, writer, _ = bucket
    writer.main()
    keys, arch = archive_frame(r2)
    assert len(arch) == 120  # union of the three dated windows, each record once
    assert all('/year=2026/quarter=' in k for k in keys) and len(keys) >= 2
    assert arch['canonical_event_id'].is_unique
    state = json.loads(r2.objects['archive/canonical/nse/insider_trading/_state.json'])
    assert state['last_merged'] == '2026-10-06' and state['records'] == 120
    latest = json.loads(r2.objects['clean/latest.json'])
    assert latest['date'] == '2026-10-07'
    trades = pd.read_parquet(io.BytesIO(r2.objects['clean/current/insider_trades.parquet']))
    assert 0 < len(trades) <= 120
    report = json.loads(r2.objects[latest['report']])
    assert report['archive']['nse/insider_trading']['records'] == 120
    assert any('archive built from 3 dated files' in n for n in report['notes'])
    assert 'reference/security_lists/2026-10-07/nse_equity.csv' in r2.objects


def test_next_night_rewrites_only_the_quarters_it_touches(bucket, real_nse_rows):
    r2, writer, _ = bucket
    writer.main()
    q3 = r2.objects['archive/canonical/nse/insider_trading/year=2026/quarter=3.parquet']
    tonight = real_nse_rows[:4] + [dict(real_nse_rows[0], acqName='New Person', appId='9999')]
    r2.objects['canonical/nse/insider_trading/2026-10-07/data.parquet'] = parquet(
        canonical('nse', 'insider_trading', tonight).drop(columns=['exchange', 'category']))
    writer.main()
    state = json.loads(r2.objects['archive/canonical/nse/insider_trading/_state.json'])
    assert state['partitions_written_today'] == ['year=2026/quarter=4']
    assert state['last_merged'] == '2026-10-07' and state['records'] == 121
    assert r2.objects['archive/canonical/nse/insider_trading/year=2026/quarter=3.parquet'] is q3  # not rewritten


def test_partitions_follow_the_records_own_date(real_nse_rows):
    df = canonical('nse', 'insider_trading', real_nse_rows)
    parts = archive.partitions(df, 'insider_trading')
    first = df['canonical_broadcast_date'].iloc[0]  # '01-Oct-2026 16:42:04'
    assert first.startswith('01-Oct-2026') and parts.iloc[0] == 'year=2026/quarter=4'
    assert archive.partition_of(None) == 'year=unknown'


def test_retention_dry_run_deletes_nothing_then_deletes_only_absorbed_old(bucket, monkeypatch):
    r2, writer, retention = bucket
    writer.main()
    before = set(r2.objects)
    retention.main()
    assert set(r2.objects) == before  # dry run
    monkeypatch.setattr(retention, 'DELETE', True)
    retention.main()
    assert sorted(r2.deleted) == ['canonical/nse/insider_trading/2026-09-20/data.parquet',
                                  'canonical/nse/insider_trading/2026-09-21/data.parquet',
                                  'raw/nse/insider_trading/2026-09-20/raw.json',
                                  'raw/nse/insider_trading/2026-09-21/raw.json']
    assert 'archive/canonical/nse/insider_trading/_state.json' in r2.objects
    assert 'canonical/nse/insider_trading/2026-10-06/data.parquet' in r2.objects  # inside 14 days


def test_retention_never_touches_a_dataset_without_archive(bucket, monkeypatch):
    r2, _, retention = bucket
    monkeypatch.setattr(retention, 'DELETE', True)
    retention.main()  # writer never ran: no archive
    assert r2.deleted == []


def test_clean_runs_on_rows_round_tripped_through_the_archive(real_nse_rows):
    """07 Oct 2026, first R2 run: rows read back from the archive carry <NA>
    for missing text (here canonical_isin and a blank mode), and the cleaner
    crashed on `not <NA>`. Two merges, the second mixing object and string
    columns, then a full pipeline run."""
    import pandas as pd

    from insiders_clean.calendar import seed_state
    from insiders_clean.pipeline import run

    rows = [dict(r) for r in real_nse_rows[:40]]
    rows[0]['modeOfAcquisition'] = ''
    rows[1]['acqName'] = ''
    day1 = canonical('nse', 'insider_trading', rows[:20])
    day1['canonical_isin'] = None
    arch, _ = archive.merge(None, day1, '2026-10-05')
    arch, _ = archive.merge(arch, canonical('nse', 'insider_trading', rows[15:]), '2026-10-06')
    assert pd.api.types.is_string_dtype(arch['canonical_isin']) and arch['canonical_isin'].isna().any()
    arch = pd.concat([arch, arch.head(1).astype(object)], ignore_index=True)  # object + string mix
    tables, _ = run({('nse', 'insider_trading'): arch}, '2026-10-07', seed_state())
    t = tables['insider_trades']
    assert not t['person_id'].astype(str).str.contains('<na>|na$', regex=True).any()
    assert '<NA>' not in set(t['mode_raw'].dropna())
    assert (t['kind'] == 'missing').any()
