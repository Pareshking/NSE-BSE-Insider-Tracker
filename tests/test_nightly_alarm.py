"""scripts/nightly_alarm.py: the nightly run goes red when data was not written (18 Nov 2026)."""
from __future__ import annotations

import json

import nightly_alarm as a


def test_skipped_datasets_and_failed_notes_are_problems():
    manifest = {'datasets': [
        {'exchange': 'nse', 'category': 'insider_trading', 'written': True},
        {'exchange': 'nse', 'category': 'bulk_deals', 'written': False,
         'reason': "validator status is 'BLOCKED', not VERIFIED"}],
        'reference_data': [{'dataset': 'market_cap', 'written': True}]}
    log = ('  shareholding: {"added": 7}\n'
           "  note: promoter_group: failed (ArrowTypeError: ('cannot be converted', 'column quarter_end'))\n")
    found = a.problems(manifest, log)
    assert found[0] == "nse/bulk_deals not written: validator status is 'BLOCKED', not VERIFIED"
    assert found[1].startswith('BSE events: promoter_group: failed (ArrowTypeError')
    assert len(found) == 2


def test_a_good_night_passes_and_a_missing_manifest_fails(tmp_path):
    good = {'datasets': [{'exchange': 'nse', 'category': 'bulk_deals', 'written': True}], 'reference_data': []}
    m = tmp_path / 'm.json'
    m.write_text(json.dumps(good))
    assert a.main([str(m), str(tmp_path / 'none.log')]) == 0
    assert a.main([str(tmp_path / 'missing.json'), str(tmp_path / 'none.log')]) == 1
