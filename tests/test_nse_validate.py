"""The NSE certification gate for bulk/block: complete CSV fetches pass,
sparse or not-yet-published windows alone do not block, a failed chunk does."""
from __future__ import annotations

import json

import nse_validate


def report(chunks, w90_dates=3, w90_count=10):
    return {'target_date': nse_validate.TARGET, 'chunk_diagnostics': chunks,
            'windows': [{'name': '1d', 'count': 0, 'distinct_dates': []},
                        {'name': '7d', 'count': 1, 'distinct_dates': ['08-OCT-2026']},
                        {'name': '90d', 'count': w90_count, 'distinct_dates': [f'0{i}-OCT-2026' for i in range(w90_dates)]}]}


def certify(tmp_path, monkeypatch, rep):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'artifacts' / 'nse_bulk').mkdir(parents=True)
    (tmp_path / 'artifacts' / 'nse_bulk' / 'report.json').write_text(json.dumps(rep))
    monkeypatch.setattr(nse_validate, 'OUT', tmp_path / 'artifacts' / 'nse_validation')
    nse_validate.OUT.mkdir(parents=True, exist_ok=True)
    nse_validate.main()
    return json.loads((nse_validate.OUT / 'certification_report.json').read_text())['datasets']['bulk']


def test_empty_one_day_and_sparse_week_do_not_block_a_complete_csv_fetch(tmp_path, monkeypatch, capsys):
    ok = certify(tmp_path, monkeypatch, report([{'mode': 'csv', 'count': 5}, {'mode': 'csv', 'count': 0}]))
    assert ok['status'] == 'VERIFIED' and ok['non_csv_chunks'] == 0


def test_one_failed_chunk_blocks(tmp_path, monkeypatch, capsys):
    bad = certify(tmp_path, monkeypatch, report([{'mode': 'csv', 'count': 5}, {'mode': 'non_csv', 'count': 0}]))
    assert bad['status'] == 'BLOCKED' and bad['non_csv_chunks'] == 1


def test_empty_90_day_window_blocks(tmp_path, monkeypatch, capsys):
    assert certify(tmp_path, monkeypatch, report([{'mode': 'csv', 'count': 0}], w90_count=0, w90_dates=0))['status'] == 'BLOCKED'
