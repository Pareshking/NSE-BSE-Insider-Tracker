"""Historical announcement AI backfill: bounded selection and source-linked persistent memory."""
from __future__ import annotations

import json
from datetime import date

import pandas as pd

import announcement_backfill as backfill
import announcement_reader as ar
from test_archive_and_writer import FakeR2


def _candidate(eid, day, isin='INE000A01001', status=None):
    return {
        'event_id': eid, 'exchange': 'NSE', 'market': 'equities', 'isin': isin,
        'symbol': 'ACME', 'company': 'Acme Ltd', 'subject': 'Outcome of Board Meeting',
        'detail': 'Board approved a project', 'group': 'to_sort',
        'file_url': f'https://example.test/{eid}.pdf', 'file_type': 'pdf',
        'broadcast_at': f'{day}T10:00:00+05:30', 'broadcast_date': day,
        'market_cap': 50_000_000_000, 'status': status, 'tries': 0,
    }


def test_continuous_worker_uses_only_checkpointed_completed_months():
    r2 = FakeR2()
    r2.objects.update({
        'archive/announcement_backfill/collection/2026-01.json': json.dumps({'from': '2026-01-01', 'to': '2026-01-31'}).encode(),
        'archive/announcement_backfill/collection/2026-02.json': json.dumps({'from': '2026-02-01', 'to': '2026-02-28'}).encode(),
        'archive/announcement_backfill/collection/2026-10.json': json.dumps({'from': '2026-10-01', 'to': '2026-10-14'}).encode(),
        'archive/announcement_backfill/collection/not-a-month.json': b'{}',
    })
    months = backfill.completed_collection_months(r2, date(2026, 1, 1), date(2026, 10, 14))
    assert months == ['2026-01', '2026-02']


def test_choose_accepts_explicit_inclusive_history_range_and_excludes_outside_dates():
    candidates = pd.DataFrame([
        _candidate('old', '2025-12-31'),
        _candidate('start', '2026-01-01', 'INE000A01002'),
        _candidate('inside', '2026-05-12', 'INE000A01003'),
        _candidate('end', '2026-10-14', 'INE000A01004'),
        _candidate('future', '2026-10-15', 'INE000A01005'),
    ])
    selected, _, counts = ar.choose(candidates, None, date(2026, 10, 14),
                                    date_from=date(2026, 1, 1), date_to=date(2026, 10, 14))
    assert set(selected['event_id']) == {'start', 'inside', 'end'}
    assert counts['candidates'] == 3


def test_verified_event_only_persists_checked_claims_with_filing_provenance():
    row = _candidate('nse:1', '2026-02-01')
    row.update({
        'status': 'read', 'category': 'acquisition', 'read_at': '2026-02-01T12:00:00Z',
        'headline': json.dumps({'text': 'Acme buys 51% of Beta', 'quote': 'acquires 51%', 'shown': True}),
        'points': json.dumps([
            {'text': '51% stake acquired', 'quote': 'acquires 51%', 'shown': True},
            {'text': 'Unsupported claim', 'quote': 'not found', 'shown': False},
        ]),
        'fields': json.dumps([{'name': 'stake', 'value': '51%', 'quote': 'acquires 51%', 'shown': True}]),
        'metrics': json.dumps([{'label': 'stake', 'value': '51', 'quote': 'acquires 51%', 'shown': True}]),
    })
    event = backfill.verified_event(row)
    assert event['event_id'] == 'nse:1'
    assert event['source_url'] == row['file_url']
    assert len(event['points']) == 1 and event['points'][0]['shown']
    assert event['fields'][0]['quote'] == 'acquires 51%'
    assert backfill.verified_event({**row, 'status': 'failed'}) is None


def test_upsert_company_memory_is_idempotent_and_keeps_source_linked_events():
    r2 = FakeR2()
    row = _candidate('nse:1', '2026-02-01')
    row.update({
        'status': 'read', 'category': 'rights', 'read_at': '2026-02-01T12:00:00Z',
        'headline': json.dumps({'text': 'Acme sets rights issue', 'quote': 'rights issue', 'shown': True}),
        'points': json.dumps([]), 'fields': json.dumps([]), 'metrics': json.dumps([]),
    })
    assert backfill.upsert_company_memories(r2, [row]) == 1
    assert backfill.upsert_company_memories(r2, [row]) == 1
    stored = json.loads(r2.objects['archive/company_memory/INE000A01001.json'])
    assert stored['event_count'] == 1
    assert stored['events'][0]['event_id'] == 'nse:1'
    assert stored['events'][0]['source_url'] == row['file_url']


def test_memory_context_only_includes_earlier_events_and_prompt_carries_provenance(monkeypatch):
    r2 = FakeR2()
    import clean_writer
    clean_writer.put(r2, 'archive/company_memory/INE000A01001.json', json.dumps({
        'schema_version': 1, 'isin': 'INE000A01001', 'events': [
            {'date': '2026-01-05', 'event_id': 'nse:past', 'headline': {'text': 'Acme approved a plant'},
             'points': [], 'source_url': 'https://example.test/past.pdf'},
            {'date': '2026-03-05', 'event_id': 'nse:future', 'headline': {'text': 'Future event'},
             'points': [], 'source_url': 'https://example.test/future.pdf'},
        ]}).encode(), 'application/json')
    frame = ar.with_company_memory(r2, pd.DataFrame([_candidate('nse:new', '2026-02-01')]))
    assert 'nse:past' in frame.iloc[0]['_company_memory']
    assert 'nse:future' not in frame.iloc[0]['_company_memory']
    prompt = ar.card_prompt(frame.iloc[0].to_dict(), 'The board approved a project.')
    assert 'Earlier verified company history' in prompt
    assert 'https://example.test/past.pdf' in prompt
