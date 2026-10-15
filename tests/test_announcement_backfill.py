"""Historical announcement AI backfill: bounded selection and source-linked persistent memory."""
from __future__ import annotations

import json
from datetime import date, datetime

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
    today = datetime.now(backfill.IST).date()
    current_month = today.strftime('%Y-%m')
    r2.objects.update({
        'archive/announcement_backfill/collection/2026-01.json': json.dumps(
            {'from': '2026-01-01', 'to': '2026-01-31', 'status': 'collection_verified'}).encode(),
        'archive/announcement_backfill/collection/2026-02.json': json.dumps(
            {'from': '2026-02-01', 'to': '2026-02-28', 'status': 'collection_verified'}).encode(),
        'archive/announcement_backfill/collection/2026-03.json': json.dumps(
            {'from': '2026-03-01', 'to': '2026-03-31', 'status': 'collection_commands_succeeded'}).encode(),
        f'archive/announcement_backfill/collection/{current_month}.json': json.dumps(
            {'from': f'{current_month}-01', 'to': today.isoformat(), 'status': 'collection_verified'}).encode(),
        'archive/announcement_backfill/collection/not-a-month.json': b'{}',
    })
    months = backfill.completed_collection_months(r2, date(2026, 1, 1), today)
    assert months == [m for m in ('2026-01', '2026-02') if m != current_month]


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



def test_historical_day_checkpoint_requires_verified_both_exchange_scope():
    r2 = FakeR2()
    day = date(2026, 1, 2)
    key = f'{backfill.COLLECTION_DAY_PREFIX}{day.isoformat()}.json'
    r2.objects[key] = json.dumps({
        'date': day.isoformat(), 'from': day.isoformat(), 'to': day.isoformat(),
        'status': 'collection_commands_succeeded',
    }).encode()
    assert not backfill.historical_day_collected(r2, day)

    # Legacy NSE-only markers must not skip collection: they lack BSE history.
    r2.objects[key] = json.dumps({
        'date': day.isoformat(), 'from': day.isoformat(), 'to': day.isoformat(),
        'status': 'collection_verified', 'scope': ['NSE'],
        'verification': {'bse_skipped': True},
    }).encode()
    assert not backfill.historical_day_collected(r2, day)

    r2.objects[key] = json.dumps({
        'date': day.isoformat(), 'from': day.isoformat(), 'to': day.isoformat(),
        'status': 'collection_verified', 'scope': ['NSE', 'BSE'],
        'verification': {'exchanges_verified': ['NSE', 'BSE'], 'reports_checked': True, 'bse_skipped': False},
    }).encode()
    assert backfill.historical_day_collected(r2, day)


def test_historical_collection_fetches_both_exchanges_and_writes_verified_daily_checkpoint(monkeypatch):
    r2 = FakeR2()
    day = date(2026, 1, 2)
    today = datetime.now(backfill.IST).date().isoformat()
    import clean_writer

    commands = []

    def fake_run(command, check, env):
        commands.append(command)
        assert check is True
        assert command[command.index('--from') + 1] == day.isoformat()
        assert command[command.index('--to') + 1] == day.isoformat()
        if 'collectors.nse_events.announcements' in command:
            clean_writer.put(r2, f'clean/reports/announcements/{today}.json', json.dumps({
                'window': [day.isoformat(), day.isoformat()],
                'calls': [
                    {'market': 'equities', 'from': day.isoformat(), 'to': day.isoformat(), 'rows': 3},
                    {'market': 'sme', 'from': day.isoformat(), 'to': day.isoformat(), 'rows': 1},
                ],
                'notes': [],
            }).encode(), 'application/json')
        elif 'collectors.bse.announcements' in command:
            clean_writer.put(r2, f'clean/reports/announcements_bse/{today}.json', json.dumps({
                'window': [day.isoformat(), day.isoformat()],
                'days': [{'day': day.isoformat(), 'bse_count': 2, 'unique': 2, 'pages': 1, 'short': False}],
                'notes': [], 'bse_calls': 1, 'via': 'requests',
            }).encode(), 'application/json')
        else:
            raise AssertionError(f'Unexpected historical collector command: {command}')
        return None

    monkeypatch.setattr(backfill.subprocess, 'run', fake_run)
    backfill.collect_historical_day(r2, day)

    assert len(commands) == 2
    assert 'collectors.nse_events.announcements' in commands[0]
    assert 'collectors.bse.announcements' in commands[1]
    assert backfill.historical_day_collected(r2, day)
    marker = json.loads(r2.objects[f'{backfill.COLLECTION_DAY_PREFIX}{day.isoformat()}.json'])
    assert marker['status'] == 'collection_verified'
    assert marker['scope'] == ['NSE', 'BSE']
    assert marker['verification']['bse_rows_reported'] == 2
    assert marker['verification']['bse_rows_fetched_unique'] == 2
    assert marker['verification']['bse_skipped'] is False


def test_historical_collection_refuses_short_bse_page_coverage(monkeypatch):
    r2 = FakeR2()
    day = date(2026, 1, 2)
    today = datetime.now(backfill.IST).date().isoformat()
    import clean_writer

    def fake_run(command, check, env):
        if 'collectors.nse_events.announcements' in command:
            clean_writer.put(r2, f'clean/reports/announcements/{today}.json', json.dumps({
                'window': [day.isoformat(), day.isoformat()],
                'calls': [
                    {'market': 'equities', 'from': day.isoformat(), 'to': day.isoformat(), 'rows': 3},
                    {'market': 'sme', 'from': day.isoformat(), 'to': day.isoformat(), 'rows': 1},
                ],
                'notes': [],
            }).encode(), 'application/json')
        else:
            clean_writer.put(r2, f'clean/reports/announcements_bse/{today}.json', json.dumps({
                'window': [day.isoformat(), day.isoformat()],
                'days': [{'day': day.isoformat(), 'bse_count': 10, 'unique': 5, 'pages': 1, 'short': True}],
                'notes': [],
            }).encode(), 'application/json')

    monkeypatch.setattr(backfill.subprocess, 'run', fake_run)
    import pytest
    with pytest.raises(RuntimeError, match='BSE page coverage incomplete'):
        backfill.collect_historical_day(r2, day)
    assert f'{backfill.COLLECTION_DAY_PREFIX}{day.isoformat()}.json' not in r2.objects


def test_historical_collection_refuses_missing_sme_coverage(monkeypatch):
    r2 = FakeR2()
    day = date(2026, 1, 2)
    today = datetime.now(backfill.IST).date().isoformat()
    import clean_writer

    def fake_run(command, check, env):
        clean_writer.put(r2, f'clean/reports/announcements/{today}.json', json.dumps({
            'window': [day.isoformat(), day.isoformat()],
            'calls': [{'market': 'equities', 'from': day.isoformat(), 'to': day.isoformat(), 'rows': 3}],
            'notes': [],
        }).encode(), 'application/json')

    monkeypatch.setattr(backfill.subprocess, 'run', fake_run)
    import pytest
    with pytest.raises(RuntimeError, match='sme feed did not certify'):
        backfill.collect_historical_day(r2, day)
    assert f'{backfill.COLLECTION_DAY_PREFIX}{day.isoformat()}.json' not in r2.objects


def test_ai_day_checkpoint_requires_verified_collection_and_terminal_status():
    r2 = FakeR2()
    day = date(2026, 1, 2)
    day_text = day.isoformat()
    import clean_writer

    clean_writer.put(r2, f'{backfill.COLLECTION_DAY_PREFIX}{day_text}.json', json.dumps({
        'date': day_text, 'from': day_text, 'to': day_text,
        'status': 'collection_verified', 'scope': ['NSE'],
        'verification': {'bse_skipped': True},
    }).encode(), 'application/json')
    clean_writer.put(r2, f'{backfill.AI_DAY_PREFIX}{day_text}.json', json.dumps({
        'date': day_text, 'from': day_text, 'to': day_text,
        'status': 'running', 'remaining': 0, 'scope': ['NSE'],
    }).encode(), 'application/json')
    assert not backfill.historical_day_ai_complete(r2, day)

    clean_writer.put(r2, f'{backfill.COLLECTION_DAY_PREFIX}{day_text}.json', json.dumps({
        'date': day_text, 'from': day_text, 'to': day_text,
        'status': 'collection_verified', 'scope': ['NSE', 'BSE'],
        'verification': {'exchanges_verified': ['NSE', 'BSE'], 'reports_checked': True, 'bse_skipped': False},
    }).encode(), 'application/json')
    clean_writer.put(r2, f'{backfill.AI_DAY_PREFIX}{day_text}.json', json.dumps({
        'date': day_text, 'from': day_text, 'to': day_text,
        'status': 'complete', 'remaining': 0, 'scope': ['NSE', 'BSE'],
    }).encode(), 'application/json')
    assert backfill.historical_day_ai_complete(r2, day)


def test_next_unfinished_history_day_ignores_legacy_state_list_without_ai_checkpoint():
    r2 = FakeR2()
    start, cutoff = date(2026, 1, 1), date(2026, 1, 3)
    state = {'completed_history_dates': ['2026-01-01', '2026-01-02']}
    assert backfill.next_unfinished_history_day(r2, start, cutoff, state) == start


def test_next_unfinished_history_day_skips_only_verified_two_exchange_complete_days():
    r2 = FakeR2()
    import clean_writer
    for day in (date(2026, 1, 1), date(2026, 1, 2)):
        text_day = day.isoformat()
        clean_writer.put(r2, f'{backfill.COLLECTION_DAY_PREFIX}{text_day}.json', json.dumps({
            'date': text_day, 'from': text_day, 'to': text_day,
            'status': 'collection_verified', 'scope': ['NSE', 'BSE'],
            'verification': {'exchanges_verified': ['NSE', 'BSE'], 'reports_checked': True, 'bse_skipped': False},
        }).encode(), 'application/json')
        clean_writer.put(r2, f'{backfill.AI_DAY_PREFIX}{text_day}.json', json.dumps({
            'date': text_day, 'from': text_day, 'to': text_day,
            'status': 'complete', 'remaining': 0, 'scope': ['NSE', 'BSE'],
        }).encode(), 'application/json')
    assert backfill.next_unfinished_history_day(
        r2, date(2026, 1, 1), date(2026, 1, 3), {'next_history_date': '2026-01-01'}
    ) == date(2026, 1, 3)

def test_next_unfinished_history_day_reopens_legacy_nse_only_completion():
    r2 = FakeR2()
    import clean_writer
    for day in (date(2026, 1, 1), date(2026, 1, 2)):
        text_day = day.isoformat()
        clean_writer.put(r2, f'{backfill.COLLECTION_DAY_PREFIX}{text_day}.json', json.dumps({
            'date': text_day, 'from': text_day, 'to': text_day,
            'status': 'collection_verified', 'scope': ['NSE'],
            'verification': {'bse_skipped': True},
        }).encode(), 'application/json')
        clean_writer.put(r2, f'{backfill.AI_DAY_PREFIX}{text_day}.json', json.dumps({
            'date': text_day, 'from': text_day, 'to': text_day,
            'status': 'complete', 'remaining': 0, 'scope': ['NSE'],
        }).encode(), 'application/json')
    assert backfill.next_unfinished_history_day(
        r2, date(2026, 1, 1), date(2026, 1, 3), {'next_history_date': '2026-01-03'}
    ) == date(2026, 1, 1)


def test_targeted_history_filter_only_keeps_target_isins_and_inclusive_dates():
    frame = pd.DataFrame([
        _candidate('target-start', '2026-01-01', 'INE-TARGET'),
        _candidate('other-company', '2026-03-01', 'INE-OTHER'),
        _candidate('target-inside', '2026-05-12', 'INE-TARGET'),
        _candidate('target-end', '2026-10-14', 'INE-TARGET'),
        _candidate('target-before', '2025-12-31', 'INE-TARGET'),
        _candidate('target-after', '2026-10-15', 'INE-TARGET'),
    ])
    selected = backfill.filter_target_company_history(
        frame, {'INE-TARGET'}, date(2026, 1, 1), date(2026, 10, 14))
    assert set(selected['event_id']) == {'target-start', 'target-inside', 'target-end'}
    assert set(selected['isin']) == {'INE-TARGET'}


def test_unified_pipeline_collection_cursor_advances_one_verified_day_per_run(monkeypatch):
    r2 = FakeR2()
    import clean_writer

    monkeypatch.setattr(clean_writer, 'get', lambda client, key: client.objects.get(key))
    monkeypatch.setattr(clean_writer, 'put', lambda client, key, body, content_type=None:
                        client.objects.__setitem__(key, body if isinstance(body, bytes) else str(body).encode()))
    collected = set()
    monkeypatch.setattr(backfill, 'historical_day_collected',
                        lambda client, day: day.isoformat() in collected)

    def collect_one(client, day):
        collected.add(day.isoformat())

    monkeypatch.setattr(backfill, 'collect_historical_day', collect_one)
    today = date(2026, 1, 5)  # cutoff is Jan 2: only one historical date per call
    state = backfill.read_pipeline_state(r2)
    assert backfill.advance_pipeline_history_collection(r2, today, state, []) is False
    state = backfill.read_pipeline_state(r2)
    assert state['collection_next_date'] == '2026-01-02'
    assert collected == {'2026-01-01'}

    assert backfill.advance_pipeline_history_collection(r2, today, state, []) is True
    state = backfill.read_pipeline_state(r2)
    assert state['collection_next_date'] == '2026-01-03'
    assert state['collection_complete'] is True
    assert collected == {'2026-01-01', '2026-01-02'}


def test_unified_pipeline_collection_failure_keeps_cursor_for_retry(monkeypatch):
    r2 = FakeR2()
    import clean_writer

    monkeypatch.setattr(clean_writer, 'get', lambda client, key: client.objects.get(key))
    monkeypatch.setattr(clean_writer, 'put', lambda client, key, body, content_type=None:
                        client.objects.__setitem__(key, body if isinstance(body, bytes) else str(body).encode()))
    monkeypatch.setattr(backfill, 'historical_day_collected', lambda client, day: False)

    def fail_collection(client, day):
        raise RuntimeError('BSE report unavailable')

    monkeypatch.setattr(backfill, 'collect_historical_day', fail_collection)
    notes = []
    state = backfill.read_pipeline_state(r2)
    assert backfill.advance_pipeline_history_collection(r2, date(2026, 1, 5), state, notes) is False
    saved = backfill.read_pipeline_state(r2)
    assert saved['collection_next_date'] == '2026-01-01'
    assert saved['collection_last_error'].endswith('BSE report unavailable')
    assert notes and 'historical source collection 2026-01-01' in notes[0]
