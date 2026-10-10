"""A collector report written for another day must never certify (9 Oct 2026:
a crashed insider fetch left the 31 Aug files in place and they were stored as
VERIFIED under 2026-10-09)."""
import importlib
import json
import sys
from pathlib import Path

SCRIPTS = str(Path(__file__).resolve().parents[1] / 'scripts')


def _report(target):
    row = {'date': '2026-10-01', 'symbol': 'ABC', 'acqName': 'X', 'personCategory': 'Promoters',
           'buyQuantity': '1', 'sellquantity': '0', 'buyValue': '1', 'sellValue': '0', 'transactionType': 'Acquisition'}
    w = lambda name: {'name': name, 'count': 1, 'distinct_dates': ['2026-10-01']}
    return {'target_date': target, 'windows': [w('1d'), w('7d'), w('90d')], 'rows': [row]}


def _run(tmp_path, monkeypatch, report_target):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('TARGET_DATE', '2026-10-09')
    monkeypatch.setenv('LOOKBACK_DAYS', '7')
    ins = tmp_path / 'artifacts' / 'nse_insider'
    ins.mkdir(parents=True)
    rep = _report(report_target)
    (ins / 'report.json').write_text(json.dumps(rep))
    (ins / '90d.json').write_text(json.dumps({'rows': rep['rows']}))
    monkeypatch.syspath_prepend(SCRIPTS)
    sys.modules.pop('nse_validate', None)
    mod = importlib.import_module('nse_validate')
    mod.main()
    return json.loads((tmp_path / 'artifacts' / 'nse_validation' / 'certification_report.json').read_text())


def test_report_from_another_day_is_blocked(tmp_path, monkeypatch):
    out = _run(tmp_path, monkeypatch, '2026-08-31')
    assert out['datasets']['insider']['status'] == 'BLOCKED'
    assert out['datasets']['insider']['stale_or_missing_report'] == '2026-08-31'
    assert out['promoter_semantics'] == 'BLOCKED'  # not read from the old file either


def test_report_for_the_run_day_is_verified(tmp_path, monkeypatch):
    out = _run(tmp_path, monkeypatch, '2026-10-09')
    assert out['datasets']['insider']['status'] == 'VERIFIED'
    assert 'stale_or_missing_report' not in out['datasets']['insider']
