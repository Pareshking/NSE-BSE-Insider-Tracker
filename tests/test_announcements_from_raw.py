"""Concall rows come back into the archive from the saved exchange answers, once, without another request."""
from __future__ import annotations

import io
import json
from datetime import date

import announcements_from_raw as fr
import pandas as pd
import test_announcements as nse_t
import test_bse_announcements as bse_t
from test_archive_and_writer import FakeR2

from collectors.bse import announcements as bann
from collectors.nse_events import announcements as nann
from insiders_clean.raw_store import RawStore


def _archive(r2, prefix):
    keys = [k for k in r2.objects if k.startswith(prefix)]
    return pd.concat([pd.read_parquet(io.BytesIO(r2.objects[k])) for k in keys]) if keys else pd.DataFrame()


def _old_collector_archive(r2):
    """What the collectors archived before 15 Oct: every row but the concall ones."""
    nse = [r for r in nse_t.ROWS]
    bse = [r for r in bse_t.ROWS if r['SUBCATNAME'] not in bann.CONCALL]
    nann.merge_into_archive(r2, nann.parse(nse), '2026-10-14')
    bann.merge_into_archive(r2, bann.parse(bse), '2026-10-14')


def _save_answers(r2):
    raw = RawStore(r2, bucket='b', collector='test')
    concall = dict(nse_t.ROWS[0], seq_id='9001', desc=nann.CONCALL[0])
    raw.put('nse', 'announcements', json.dumps(nse_t.ROWS + [concall]).encode(), url='https://www.nseindia.com/api/x?index=equities',
            covers={'index': 'equities'}, content_type='application/json')
    raw.put('nse', 'announcements', b'[]', url='https://www.nseindia.com/api/x?index=sme', covers={'index': 'sme'},
            content_type='application/json')
    raw.put('bse', 'announcements', json.dumps({'Table': bse_t.ROWS, 'Table1': [{'ROWCNT': len(bse_t.ROWS)}]}).encode(),
            url='https://api.bseindia.com/x', content_type='application/json')
    raw.put('bse', 'announcements', b'<html>blocked</html>', url='https://api.bseindia.com/x', status=403,
            content_type='text/html')


def test_rebuild_adds_only_the_missing_concall_rows_and_a_rerun_adds_none():
    r2 = FakeR2()
    _old_collector_archive(r2)
    before_nse, before_bse = len(_archive(r2, nann.PREFIX)), len(_archive(r2, bann.PREFIX))
    _save_answers(r2)
    bse_concall = sum(r['SUBCATNAME'] in bann.CONCALL for r in bse_t.ROWS)
    assert bse_concall
    dry = fr.rebuild(r2, dry_run=True, run_date='2026-10-15')
    assert dry['sources']['nse']['concall_rows'] == 1 and dry['sources']['bse']['concall_rows'] == bse_concall
    assert len(_archive(r2, nann.PREFIX)) == before_nse and len(_archive(r2, bann.PREFIX)) == before_bse   # nothing written
    report = fr.rebuild(r2, run_date='2026-10-15')
    assert report['sources']['nse']['added'] == 1 and report['sources']['bse']['added'] == bse_concall
    nse, bse = _archive(r2, nann.PREFIX), _archive(r2, bann.PREFIX)
    assert len(nse) == before_nse + 1 and '9001' in set(nse['seq_id'])
    assert len(bse) == before_bse + bse_concall and set(bse['subcategory']) >= set(bann.CONCALL)
    again = fr.rebuild(r2, run_date='2026-10-16')
    assert again['sources']['nse']['added'] == 0 and again['sources']['bse']['added'] == 0
    assert 'concall rows' in fr.markdown(report)


def test_a_failed_or_unreadable_saved_answer_is_ignored():
    r2 = FakeR2()
    raw = RawStore(r2, bucket='b', collector='test')
    raw.put('bse', 'announcements', b'not json', url='https://api.bseindia.com/x', content_type='text/plain')
    raw.put('bse', 'announcements', b'{"Table": null}', url='https://api.bseindia.com/x', content_type='application/json')
    report = fr.rebuild(r2, sources=('bse',), run_date='2026-10-15')
    assert report['sources']['bse']['concall_rows'] == 0 and not any(k.startswith(bann.PREFIX) for k in r2.objects)
