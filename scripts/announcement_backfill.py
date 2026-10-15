"""Historical AI backfill for NSE/BSE announcements, with resumable R2 checkpoints.

Run after collecting announcement archives:
  python scripts/announcement_backfill.py --from 2026-01-01 --to 2026-10-14

The live reader remains independent. Completed filing reads live in the existing monthly archive;
verified company memory is a deterministic, source-linked projection of those reads.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import announcement_reader as ar  # noqa: E402
import announcement_sample as sample  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
START_DEFAULT = date(2026, 1, 1)
MEMORY_PREFIX = 'archive/company_memory/'
STATE_KEY = 'archive/announcement_backfill/state.json'
COLLECTION_PREFIX = 'archive/announcement_backfill/collection/'
COLLECTION_DAY_PREFIX = 'archive/announcement_backfill/collection-days/'
AI_DAY_PREFIX = 'archive/announcement_backfill/ai-days/'


def parquet_keys(r2, prefix: str) -> list[str]:
    """List Parquet partitions under a prefix, handling R2 pagination."""
    from r2_writer import BUCKET
    keys, token = [], None
    while True:
        args = {'Bucket': BUCKET, 'Prefix': prefix, 'MaxKeys': 1000}
        if token:
            args['ContinuationToken'] = token
        page = r2.list_objects_v2(**args)
        keys.extend(x['Key'] for x in page.get('Contents', [])
                    if x['Key'].endswith('.parquet') and not x['Key'].endswith('_state.parquet'))
        if not page.get('IsTruncated'):
            break
        token = page.get('NextContinuationToken')
        if not token:
            raise RuntimeError(f'R2 listing truncated without a continuation token: {prefix}')
    return sorted(keys)


def all_parquet(r2, prefix: str) -> pd.DataFrame:
    """Read every Parquet partition under a prefix, paginating R2 listing."""
    from clean_writer import read_parquet
    keys = parquet_keys(r2, prefix)
    frames = [df for key in keys if (df := read_parquet(r2, key)) is not None and not df.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

def month_parquet(r2, prefix: str, month: str) -> pd.DataFrame:
    """Read only one calendar-month partition, keeping continuous backfill bounded."""
    from clean_writer import read_parquet
    year, number = month.split('-', 1)
    frame = read_parquet(r2, f'{prefix}year={year}/month={number}.parquet')
    return frame if frame is not None else pd.DataFrame()


def completed_collection_months(r2, start: date, end: date) -> list[str]:
    """Months whose two-exchange collection jobs wrote an explicit completion marker."""
    from clean_writer import get
    from r2_writer import BUCKET
    months, token = [], None
    while True:
        args = {'Bucket': BUCKET, 'Prefix': COLLECTION_PREFIX}
        if token:
            args['ContinuationToken'] = token
        page = r2.list_objects_v2(**args)
        for item in page.get('Contents', []):
            key = item.get('Key', '')
            name = key[len(COLLECTION_PREFIX):]
            if not re.fullmatch(r'\d{4}-\d{2}\.json', name):
                continue
            month = name[:-5]
            first = date.fromisoformat(month + '-01')
            if not (start <= first <= end and first < datetime.now(IST).date().replace(day=1)):
                continue
            next_month = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
            required_start = max(first, start)
            required_end = min(next_month - timedelta(days=1), end)
            raw = get(r2, key)
            try:
                marker = json.loads(raw) if raw else {}
                # Only checkpoints written after two-exchange report validation may unlock AI work.
                if marker.get('status') != 'collection_verified':
                    continue
                collected_from = date.fromisoformat(marker.get('from', ''))
                collected_to = date.fromisoformat(marker.get('to', ''))
            except (TypeError, ValueError):
                continue
            if collected_from <= required_start and collected_to >= required_end:
                months.append(month)
        if not page.get('IsTruncated'):
            break
        token = page.get('NextContinuationToken')
        if not token:
            raise RuntimeError(f'R2 listing truncated without a continuation token: {COLLECTION_PREFIX}')
    return sorted(set(months))


def collect_historical_day(r2, day: date) -> None:
    """Collect exactly one historical date from both exchanges and certify both reports."""
    from clean_writer import get, put

    date_text = day.isoformat()
    env = os.environ.copy()
    subprocess.run([sys.executable, '-m', 'collectors.nse_events.announcements',
                    '--from', date_text, '--to', date_text], check=True, env=env)

    # A successful process exit is not proof of coverage: validate the exact
    # execution-date report and both NSE feeds before allowing BSE collection.
    report_date = datetime.now(IST).date().isoformat()
    raw = get(r2, f'clean/reports/announcements/{report_date}.json')
    if not raw:
        raise RuntimeError(f'Missing NSE collection report for historical date {date_text}')
    try:
        nse_report = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f'Invalid NSE collection report for historical date {date_text}') from exc
    if nse_report.get('window') != [date_text, date_text]:
        raise RuntimeError(f'Wrong NSE report window for {date_text}: {nse_report.get("window")}')
    if nse_report.get('notes'):
        raise RuntimeError(f'NSE collection report has unresolved notes for {date_text}: {nse_report["notes"]}')
    nse_calls = nse_report.get('calls', [])
    for market in ('equities', 'sme'):
        if not any(call.get('market') == market and call.get('from') == date_text
                   and call.get('to') == date_text for call in nse_calls):
            raise RuntimeError(f'NSE {market} feed did not certify {date_text}')

    subprocess.run([sys.executable, '-m', 'collectors.bse.announcements',
                    '--from', date_text, '--to', date_text], check=True, env=env)
    raw = get(r2, f'clean/reports/announcements_bse/{report_date}.json')
    if not raw:
        raise RuntimeError(f'Missing BSE collection report for historical date {date_text}')
    try:
        bse_report = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f'Invalid BSE collection report for historical date {date_text}') from exc
    if bse_report.get('window') != [date_text, date_text]:
        raise RuntimeError(f'Wrong BSE report window for {date_text}: {bse_report.get("window")}')
    if bse_report.get('notes'):
        raise RuntimeError(f'BSE collection report has unresolved notes for {date_text}: {bse_report["notes"]}')
    bse_days = bse_report.get('days', [])
    if len(bse_days) != 1 or bse_days[0].get('day') != date_text:
        raise RuntimeError(f'BSE feed did not certify exactly {date_text}: {bse_days}')
    bse_day = bse_days[0]
    if bse_day.get('bse_count') is None:
        raise RuntimeError(f'BSE count missing for historical date {date_text}')
    if bse_day.get('short') or int(bse_day.get('unique') or 0) != int(bse_day['bse_count']):
        raise RuntimeError(
            f'BSE page coverage incomplete for {date_text}: '
            f"reported={bse_day.get('bse_count')}, fetched_unique={bse_day.get('unique')}, "
            f"short={bse_day.get('short')}")

    marker = {
        'date': date_text,
        'from': date_text,
        'to': date_text,
        'completed_at': datetime.now(timezone.utc).isoformat(),
        'workflow_run_id': os.environ.get('GITHUB_RUN_ID'),
        'status': 'collection_verified',
        'scope': ['NSE', 'BSE'],
        'verification': {
            'nse_report_date': report_date,
            'nse_report_window': nse_report['window'],
            'nse_feed_calls': len(nse_calls),
            'bse_report_date': report_date,
            'bse_report_window': bse_report['window'],
            'bse_rows_reported': int(bse_day['bse_count']),
            'bse_rows_fetched_unique': int(bse_day.get('unique') or 0),
            'bse_pages': int(bse_day.get('pages') or 0),
            'exchanges_verified': ['NSE', 'BSE'],
            'bse_skipped': False,
            'reports_checked': True,
        },
    }
    put(r2, f'{COLLECTION_DAY_PREFIX}{date_text}.json',
        json.dumps(marker, separators=(',', ':')).encode(), 'application/json')
    print(f'Collected and verified NSE + BSE history for {date_text}.', flush=True)


def historical_day_collected(r2, day: date) -> bool:
    """Only a fully verified two-exchange date checkpoint can skip collection on a retry."""
    from clean_writer import get
    raw = get(r2, f'{COLLECTION_DAY_PREFIX}{day.isoformat()}.json')
    if not raw:
        return False
    try:
        marker = json.loads(raw)
    except (TypeError, ValueError):
        return False
    date_text = day.isoformat()
    return (
        marker.get('status') == 'collection_verified'
        and marker.get('date') == date_text
        and marker.get('from') == date_text
        and marker.get('to') == date_text
        and marker.get('scope') == ['NSE', 'BSE']
        and (marker.get('verification') or {}).get('exchanges_verified') == ['NSE', 'BSE']
        and (marker.get('verification') or {}).get('reports_checked') is True
        and (marker.get('verification') or {}).get('bse_skipped') is False
    )


def historical_day_ai_complete(r2, day: date) -> bool:
    """Only a terminal AI checkpoint tied to verified collection can advance the date cursor."""
    from clean_writer import get
    date_text = day.isoformat()
    if not historical_day_collected(r2, day):
        return False
    raw = get(r2, f'{AI_DAY_PREFIX}{date_text}.json')
    if not raw:
        return False
    try:
        checkpoint = json.loads(raw)
    except (TypeError, ValueError):
        return False
    return (
        checkpoint.get('status') == 'complete'
        and checkpoint.get('date') == date_text
        and checkpoint.get('from') == date_text
        and checkpoint.get('to') == date_text
        and checkpoint.get('remaining') == 0
        and checkpoint.get('scope') == ['NSE', 'BSE']
    )


def next_unfinished_history_day(r2, start: date, cutoff: date, state: dict) -> date | None:
    """Resume the cursor only when it was written for the current two-exchange scope."""
    pointer = start
    # Older state cursors were advanced while BSE was explicitly skipped. Do not
    # trust them until the scope migration rewinds and records the full scope.
    raw_pointer = state.get('next_history_date') if state.get('history_scope') == ['NSE', 'BSE'] else None
    if raw_pointer:
        try:
            proposed = date.fromisoformat(raw_pointer)
            if start <= proposed <= cutoff + timedelta(days=1):
                pointer = proposed
        except (TypeError, ValueError):
            pass
    while pointer <= cutoff and historical_day_ai_complete(r2, pointer):
        pointer += timedelta(days=1)
    return pointer if pointer <= cutoff else None


def mark_historical_day_ai_complete(r2, day: date, state: dict) -> None:
    """Persist the date-level AI completion before moving the resumable cursor."""
    from clean_writer import put
    date_text = day.isoformat()
    marker = {
        'date': date_text,
        'from': date_text,
        'to': date_text,
        'completed_at': datetime.now(timezone.utc).isoformat(),
        'workflow_run_id': os.environ.get('GITHUB_RUN_ID'),
        'status': 'complete',
        'remaining': 0,
        'scope': ['NSE', 'BSE'],
        'collection_checkpoint': f'{COLLECTION_DAY_PREFIX}{date_text}.json',
        'completed_batches': int(state.get('completed_batches', 0)),
        'last_batch_counts': state.get('last_batch_counts', {}),
        'company_memories_written': int(state.get('company_memories_written', 0)),
    }
    put(r2, f'{AI_DAY_PREFIX}{date_text}.json',
        json.dumps(marker, separators=(',', ':'), default=str).encode(), 'application/json')


def live_queue_pending(r2, today: date, setup: list[str]) -> bool:
    """Fail closed: historical work starts only when the normal live queue can be checked."""
    from collectors.nse_events.run_daily import security_master
    nse = ar.load_archive(r2, 'archive/announcements/nse/', today)
    bse = ar.load_archive(r2, 'archive/announcements/bse/', today)
    reads = ar.load_archive(r2, ar.READS_PREFIX, today)
    master = security_master(r2, today.isoformat(), setup)
    selected, _, counts = ar.choose(ar.candidates(nse, bse, master), reads, today)
    print(f'Live queue gate: eligible={counts.get("to_read", 0)}; historical work '
          f'{"deferred" if not selected.empty else "allowed"}.', flush=True)
    return not selected.empty



def missing_source_months(r2, start: date, end: date) -> list[str]:
    """A zero-row source archive must never be mistaken for a completed historical backfill."""
    required, cursor = [], start.replace(day=1)
    while cursor <= end:
        required.append(f'year={cursor.year}/month={cursor.month:02d}.parquet')
        cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
    missing = []
    for exchange in ('nse', 'bse'):
        keys = set(parquet_keys(r2, f'archive/announcements/{exchange}/'))
        for partition in required:
            if f'archive/announcements/{exchange}/{partition}' not in keys:
                missing.append(f'{exchange}:{partition[:-8]}')
    return missing


def json_cell(value):
    if isinstance(value, (dict, list)):
        return value
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def verified_event(row: dict) -> dict | None:
    """Only retain checked facts and quotes; every item stays tied to its filing."""
    if row.get('status') != 'read':
        return None
    headline = json_cell(row.get('headline'))
    if isinstance(headline, dict) and not headline.get('shown'):
        headline = None
    points = [p for p in (json_cell(row.get('points')) or [])
              if isinstance(p, dict) and p.get('shown')]
    fields = [f for f in (json_cell(row.get('fields')) or [])
              if isinstance(f, dict) and f.get('shown')]
    metrics = [m for m in (json_cell(row.get('metrics')) or [])
               if isinstance(m, dict) and m.get('shown')]
    if not headline and not points and not fields and not metrics:
        return None
    return {
        'date': str(row.get('broadcast_date') or ''),
        'event_id': str(row.get('event_id') or ''),
        'exchange': str(row.get('exchange') or ''),
        'company': str(row.get('company') or row.get('symbol') or ''),
        'symbol': str(row.get('symbol') or ''),
        'subject': str(row.get('subject') or ''),
        'category': str(row.get('category') or ''),
        'source_url': str(row.get('file_url') or ''),
        'read_at': str(row.get('read_at') or ''),
        'headline': headline,
        'points': points,
        'fields': fields,
        'metrics': metrics,
    }


def memory_for_company(reads: pd.DataFrame, isin: str) -> dict:
    if reads is None or reads.empty or 'isin' not in reads.columns:
        rows = pd.DataFrame()
    else:
        rows = reads[reads['isin'].fillna('').astype(str) == isin]
    events = []
    if not rows.empty:
        sort_cols = [c for c in ('broadcast_date', 'broadcast_at') if c in rows.columns]
        if sort_cols:
            rows = rows.sort_values(sort_cols, na_position='last')
        for row in rows.to_dict('records'):
            event = verified_event(row)
            if event:
                events.append(event)
    return {
        'schema_version': 1,
        'isin': isin,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'event_count': len(events),
        'events': events[-100:],
    }


def persist_company_memories(r2, reads: pd.DataFrame, isins: set[str]) -> int:
    """Write deterministic per-company memory from the complete read archive."""
    from clean_writer import put
    written = 0
    for isin in sorted(x for x in isins if x and x.lower() != 'nan'):
        if not re.fullmatch(r'[A-Za-z0-9._-]{2,32}', isin):
            continue
        body = memory_for_company(reads, isin)
        if not body['events']:
            continue
        put(r2, f'{MEMORY_PREFIX}{isin}.json',
            json.dumps(body, ensure_ascii=False, separators=(',', ':'), default=str).encode(),
            'application/json')
        written += 1
    return written


def upsert_company_memories(r2, rows: list[dict]) -> int:
    """Incrementally append newly verified reads to durable company memory; safe to retry by event_id."""
    from clean_writer import get, put
    updates = {}
    for row in rows or []:
        isin = str(row.get('isin') or '').strip()
        if not isin or isin.lower() == 'nan' or not re.fullmatch(r'[A-Za-z0-9._-]{2,32}', isin):
            continue
        event = verified_event(row)
        if event:
            updates.setdefault(isin, {})[event['event_id']] = event
    written = 0
    for isin, incoming in updates.items():
        raw = get(r2, f'{MEMORY_PREFIX}{isin}.json')
        try:
            previous = json.loads(raw) if raw else {}
        except (TypeError, ValueError):
            previous = {}
        events = {e.get('event_id'): e for e in previous.get('events', []) if e.get('event_id')}
        events.update(incoming)
        ordered = sorted(events.values(), key=lambda e: (e.get('date') or '', e.get('event_id') or ''))[-100:]
        body = {'schema_version': 1, 'isin': isin, 'generated_at': datetime.now(timezone.utc).isoformat(),
                'event_count': len(ordered), 'events': ordered}
        put(r2, f'{MEMORY_PREFIX}{isin}.json',
            json.dumps(body, ensure_ascii=False, separators=(',', ':'), default=str).encode(),
            'application/json')
        written += 1
    return written


def add_memory_context(r2, candidates: pd.DataFrame) -> pd.DataFrame:
    """Attach source-linked earlier company events to each new prompt."""
    from clean_writer import get
    if candidates is None or candidates.empty:
        return candidates
    out = candidates.copy()
    contexts = []
    cache = {}
    for row in out.to_dict('records'):
        isin = str(row.get('isin') or '').strip()
        memory = None
        if isin and isin.lower() != 'nan' and re.fullmatch(r'[A-Za-z0-9._-]{2,32}', isin):
            if isin not in cache:
                raw = get(r2, f'{MEMORY_PREFIX}{isin}.json')
                try:
                    cache[isin] = json.loads(raw) if raw else {}
                except (TypeError, ValueError):
                    cache[isin] = {}
            memory = cache[isin]
        current_date = str(row.get('broadcast_date') or '')
        events = [e for e in (memory or {}).get('events', [])
                  if e.get('date') and e.get('date') < current_date]
        # Keep a concise and auditable context; all facts carry their original event ID and URL.
        lines = []
        for e in events[-8:]:
            head = (e.get('headline') or {}).get('text') if isinstance(e.get('headline'), dict) else None
            summary = head or '; '.join(p.get('text', '') for p in e.get('points', [])[:2] if p.get('text'))
            if summary:
                lines.append(f"- {e.get('date')} [{e.get('event_id')}] {summary} (source: {e.get('source_url')})")
        contexts.append('\n'.join(lines))
    out['_company_memory'] = contexts
    return out


def save_state(r2, state: dict):
    from clean_writer import put
    state['updated_at'] = datetime.now(timezone.utc).isoformat()
    put(r2, STATE_KEY, json.dumps(state, indent=2, default=str).encode(), 'application/json')


def read_state(r2) -> dict:
    from clean_writer import get
    raw = get(r2, STATE_KEY)
    if not raw:
        return {'schema_version': 1, 'from': START_DEFAULT.isoformat(), 'status': 'not_started',
                'completed_batches': 0, 'read': 0, 'failed': 0}
    try:
        state = json.loads(raw)
        return state if isinstance(state, dict) else {}
    except (TypeError, ValueError):
        raise RuntimeError('Backfill checkpoint is not valid JSON; refusing to overwrite it')



# The integrated reader owns both current announcements and company-triggered historical work.
PIPELINE_STATE_KEY = 'archive/announcement_pipeline/state.json'


def read_pipeline_state(r2) -> dict:
    """Read the unified pipeline's independent, resumable collection/company queue."""
    from clean_writer import get
    raw = get(r2, PIPELINE_STATE_KEY)
    if not raw:
        return {'schema_version': 1, 'collection_next_date': START_DEFAULT.isoformat(),
                'target_isins': [], 'status': 'running'}
    try:
        state = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError('Unified announcement pipeline checkpoint is invalid JSON') from exc
    if not isinstance(state, dict):
        raise RuntimeError('Unified announcement pipeline checkpoint must be a JSON object')
    state.setdefault('collection_next_date', START_DEFAULT.isoformat())
    state.setdefault('target_isins', [])
    return state


def save_pipeline_state(r2, state: dict) -> None:
    from clean_writer import put
    state['updated_at'] = datetime.now(timezone.utc).isoformat()
    put(r2, PIPELINE_STATE_KEY, json.dumps(state, indent=2, default=str).encode(), 'application/json')


def advance_pipeline_history_collection(r2, today: date, state: dict, notes: list[str]) -> bool:
    """Collect one historical date per unified run; this is source collection, never market-wide AI reading.

    A date cursor advances only after the existing two-exchange verifier certifies NSE + BSE. Failures
    are checkpointed and surfaced but do not prevent current announcements from being read.
    """
    cutoff = today - timedelta(days=3)  # don't race the live collector's today/yesterday window
    try:
        pointer = date.fromisoformat(str(state.get('collection_next_date') or START_DEFAULT.isoformat()))
    except (TypeError, ValueError):
        pointer = START_DEFAULT
    if pointer < START_DEFAULT:
        pointer = START_DEFAULT
    while pointer <= cutoff and historical_day_collected(r2, pointer):
        pointer += timedelta(days=1)
    if pointer > cutoff:
        state.update(collection_next_date=pointer.isoformat(), collection_complete=True,
                     collection_cutoff=cutoff.isoformat(), collection_last_error=None)
        save_pipeline_state(r2, state)
        return True

    state.update(collection_complete=False, collection_next_date=pointer.isoformat(),
                 collection_cutoff=cutoff.isoformat(), collection_attempted_date=pointer.isoformat())
    save_pipeline_state(r2, state)
    try:
        collect_historical_day(r2, pointer)
        if not historical_day_collected(r2, pointer):
            raise RuntimeError('collector returned without a verified NSE+BSE checkpoint')
    except Exception as exc:  # noqa: BLE001 -- keep the current-day reader available
        message = f'historical source collection {pointer}: {type(exc).__name__}: {exc}'[:500]
        state['collection_last_error'] = message
        save_pipeline_state(r2, state)
        notes.append(message)
        return False

    next_day = pointer + timedelta(days=1)
    state.update(collection_next_date=next_day.isoformat(), collection_last_error=None,
                 collection_last_success=pointer.isoformat(), collection_complete=next_day > cutoff)
    save_pipeline_state(r2, state)
    print(f'Unified pipeline: verified historical source collection for {pointer}; next={next_day}.',
          flush=True)
    return bool(state['collection_complete'])


def _month_range(start: date, end: date) -> list[str]:
    if end < start:
        return []
    month = start.replace(day=1)
    last = end.replace(day=1)
    out = []
    while month <= last:
        out.append(month.strftime('%Y-%m'))
        month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    return out



def filter_target_company_history(candidates: pd.DataFrame, target_isins: set[str],
                                  start: date, end: date) -> pd.DataFrame:
    """Restrict historical AI candidates to target ISINs and an inclusive date range."""
    if candidates is None or candidates.empty or 'isin' not in candidates or 'broadcast_date' not in candidates:
        return pd.DataFrame() if candidates is None else candidates.iloc[0:0].copy()
    target = {str(x).strip() for x in target_isins if x is not None and str(x).strip()}
    dates = pd.to_datetime(candidates['broadcast_date'], errors='coerce').dt.date
    return candidates[
        candidates['isin'].astype(str).isin(target) & (dates >= start) & (dates <= end)
    ].copy()


def run_targeted_company_backfill(r2, target_isins: set[str], today: date, master, lanes: dict,
                                  clients: dict, setup: list[str], *, batch_size: int = 8,
                                  batch_minutes: float = 2.0, dry_run: bool = False) -> dict:
    """Read only historical filings belonging to companies with current announcements or a saved target.

    Existing source archives are queried month-by-month. Historical reads remain idempotent through the
    canonical event_id read archive; company memory is updated only from verified read rows. The target
    queue is retained until source collection is complete, because later collection dates may reveal more
    history for the same company.
    """
    if dry_run or r2 is None:
        return {'companies': 0, 'historical_candidates': 0, 'read': 0, 'remaining': None}
    clean_isins = {str(x).strip() for x in target_isins
                   if x is not None and str(x).strip().lower() not in ('', 'nan', 'none')}
    if not clean_isins:
        return {'companies': 0, 'historical_candidates': 0, 'read': 0, 'remaining': 0}

    end = today - timedelta(days=1)
    start = START_DEFAULT
    if end < start:
        return {'companies': len(clean_isins), 'historical_candidates': 0, 'read': 0, 'remaining': 0}

    from r2_writer import r2_client
    # Use the caller's live R2 client and its already-configured lanes/quota ledger.
    candidates_parts, reads_parts = [], []
    for month in _month_range(start, end):
        nse = month_parquet(r2, 'archive/announcements/nse/', month)
        bse = month_parquet(r2, 'archive/announcements/bse/', month)
        if nse.empty and bse.empty:
            continue
        frame = ar.candidates(nse, bse, master)
        frame = filter_target_company_history(frame, clean_isins, start, end)
        if frame.empty:
            continue
        candidates_parts.append(frame)
        done_month = month_parquet(r2, ar.READS_PREFIX, month)
        if not done_month.empty and 'isin' in done_month:
            reads_parts.append(done_month[done_month['isin'].astype(str).isin(clean_isins)].copy())

    candidates = pd.concat(candidates_parts, ignore_index=True) if candidates_parts else pd.DataFrame()
    reads = pd.concat(reads_parts, ignore_index=True) if reads_parts else pd.DataFrame()
    if candidates.empty:
        return {'companies': len(clean_isins), 'historical_candidates': 0, 'read': 0, 'remaining': 0}

    # Only target ISINs can enter the model. Process oldest first so the memory timeline is causal.
    to_read, status_rows, counts = ar.choose(candidates, reads, today, date_from=start, date_to=end)
    to_read = to_read.sort_values(['broadcast_date', 'broadcast_at'], ascending=True) if not to_read.empty else to_read
    if not to_read.empty:
        to_read = add_memory_context(r2, to_read)
    saver = ar.Saver(r2, today.isoformat(), today)
    rows, run_notes = ar.run(to_read, lanes, reads, batch_minutes * 60,
                             max_filings=batch_size, on_row=saver.add)
    statuses = [ar.finish({**row, 'prompt_version': ar.PROMPT_VERSION,
                           'read_at': datetime.now(timezone.utc).isoformat()})
                for row in status_rows.to_dict('records')] if status_rows is not None else []
    saver.pending.extend(statuses)
    saver.flush(final=True)
    persisted = rows + statuses
    memories_written = upsert_company_memories(r2, persisted)
    # Recount from the just-updated source-of-truth frames; don't infer completion from attempted batch size.
    updated_reads = pd.concat([reads, pd.DataFrame(persisted)], ignore_index=True) if persisted else reads
    remaining_rows, _, _ = ar.choose(candidates, updated_reads, today, date_from=start, date_to=end)
    result = {'companies': len(clean_isins), 'historical_candidates': len(candidates),
              'selected': len(to_read), 'read': sum(1 for row in rows if row.get('status') == 'read'),
              'remaining': len(remaining_rows), 'memory_companies_updated': memories_written,
              'outcomes': pd.Series([r.get('status') for r in persisted]).value_counts().to_dict()
              if persisted else {}, 'counts': counts, 'notes': run_notes}
    print('Targeted historical company reads: ' + json.dumps(result, default=str), flush=True)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as f:
            f.write('### Targeted company history\n\n' +
                    '\n'.join(f'- **{k}:** {v}' for k, v in result.items()) + '\n')
    return result


def unified_company_history_stage(r2, current_isins: set[str], today: date, master, lanes: dict,
                                  clients: dict, setup: list[str], *, batch_size: int = 8,
                                  batch_minutes: float = 2.0, dry_run: bool = False) -> dict:
    """Queue today's announcing companies, advance source collection, then AI-read only queued companies."""
    if dry_run or r2 is None:
        return {'companies': 0, 'historical_candidates': 0, 'read': 0, 'remaining': None}
    state = read_pipeline_state(r2)
    queue = {str(x).strip() for x in state.get('target_isins', [])
             if x is not None and str(x).strip().lower() not in ('', 'nan', 'none')}
    queue.update(str(x).strip() for x in current_isins
                 if x is not None and str(x).strip().lower() not in ('', 'nan', 'none'))
    state['target_isins'] = sorted(queue)
    state['last_current_companies'] = sorted(current_isins)
    state['last_current_date'] = today.isoformat()
    save_pipeline_state(r2, state)

    # Keep the historical source archive progressing inside this same workflow; no separate night worker.
    complete = advance_pipeline_history_collection(r2, today, state, setup)
    state = read_pipeline_state(r2)
    result = run_targeted_company_backfill(r2, queue, today, master, lanes, clients, setup,
                                           batch_size=batch_size, batch_minutes=batch_minutes, dry_run=False)

    # Retire a company only after all historical source dates are collected and its eligible queue is empty.
    if complete and result.get('remaining') == 0:
        state['target_isins'] = []
        state['completed_target_companies_at'] = datetime.now(timezone.utc).isoformat()
    else:
        state['target_isins'] = sorted(queue)
    state['last_targeted_history'] = result
    save_pipeline_state(r2, state)
    return result


def run_backfill(start: date, end: date, batch_size: int, batch_minutes: float,
                 max_batches: int, dry_run: bool = False, month_only: bool = False,
                 nse_only: bool = False) -> int:
    from r2_writer import r2_client
    today = datetime.now(IST).date()
    r2 = r2_client()
    state = read_state(r2)
    state.update({'schema_version': 1, 'from': start.isoformat(), 'to': end.isoformat(),
                  'status': 'running', 'last_error': None})
    save_state(r2, state)

    setup = []
    lane_spec = ar.lanes_of(ar.LANES_FILE.read_text(encoding='utf-8'))
    entries = [e for lane in lane_spec.values() for e in lane]
    clients, client_notes = ar.clients_for(entries)
    setup.extend(client_notes)
    lanes = {name: ar.Lane(name, [e for e in ar.usable(models) if e.split(':', 1)[0] in clients], clients)
             for name, models in lane_spec.items()}
    lanes = {name: lane for name, lane in lanes.items() if lane.entries}
    ar.configure_rate_limit_circuit_breaker(lanes, r2, today.isoformat())
    if not lanes:
        state.update(status='blocked', last_error='No model lane has a usable key/model')
        save_state(r2, state)
        raise RuntimeError(state['last_error'])

    used = ar.used_today(r2, today.isoformat())
    for lane in lanes.values():
        lane.used_today = used

    # Require every month in the requested range from both exchanges; never call an empty archive "complete".
    missing = [] if month_only else missing_source_months(r2, start, end)
    if missing:
        state.update(status='blocked', missing_source_months=missing,
                     last_error='Historical source collection incomplete; run phase=collect/both first')
        save_state(r2, state)
        raise RuntimeError(state['last_error'] + ': ' + ', '.join(missing))
    # Source archives are immutable-by-event-id and are read independently from read history.
    one_month = start.strftime('%Y-%m') == end.strftime('%Y-%m')
    nse = month_parquet(r2, 'archive/announcements/nse/', start.strftime('%Y-%m')) if month_only and one_month else all_parquet(r2, 'archive/announcements/nse/')
    bse = pd.DataFrame() if nse_only else (month_parquet(r2, 'archive/announcements/bse/', start.strftime('%Y-%m')) if month_only and one_month else all_parquet(r2, 'archive/announcements/bse/'))
    master = None
    try:
        from collectors.nse_events.run_daily import security_master
        master = security_master(r2, today.isoformat(), setup)
    except Exception as exc:  # noqa: BLE001
        setup.append(f'security master unavailable: {type(exc).__name__}: {exc}')
    candidates = ar.candidates(nse, bse, master)
    if not candidates.empty:
        dates = pd.to_datetime(candidates['broadcast_date'], errors='coerce').dt.date
        candidates = candidates[(dates >= start) & (dates <= end)].copy()
    reads = month_parquet(r2, ar.READS_PREFIX, start.strftime('%Y-%m')) if month_only and one_month else all_parquet(r2, ar.READS_PREFIX)
    if not reads.empty:
        read_dates = pd.to_datetime(reads['broadcast_date'], errors='coerce').dt.date
        reads = reads[read_dates >= start].copy()

    total_new = 0
    for batch in range(max_batches):
        to_read, status_rows, counts = ar.choose(candidates, reads, today, date_from=start, date_to=end)
        if to_read.empty:
            if not dry_run and status_rows is not None and not status_rows.empty:
                skipped = [ar.finish({**row, 'prompt_version': ar.PROMPT_VERSION,
                                      'read_at': datetime.now(timezone.utc).isoformat()})
                           for row in status_rows.to_dict('records')]
                ar.write(r2, skipped, today.isoformat(), today)
                reads = month_parquet(r2, ar.READS_PREFIX, start.strftime('%Y-%m')) if month_only and one_month else all_parquet(r2, ar.READS_PREFIX)
            state.update(status='complete', remaining=0, candidates=len(candidates),
                         read=int((reads.get('status', pd.Series(dtype=str)) == 'read').sum()),
                         failed=int((reads.get('status', pd.Series(dtype=str)) == 'failed').sum()),
                         last_batch_at=datetime.now(timezone.utc).isoformat())
            save_state(r2, state)
            print(f'Historical backfill complete: no eligible filings remain in {start}..{end}.')
            break
        # Historical work must yield to the live queue between batches, not merely
        # once at workflow startup. Fail closed if the live queue cannot be checked.
        if month_only and not dry_run and live_queue_pending(r2, today, setup):
            state.update(status='paused', remaining=len(to_read),
                         pause_reason='live_queue_pending',
                         last_batch_at=datetime.now(timezone.utc).isoformat())
            save_state(r2, state)
            print(f'Historical batch deferred: {len(to_read)} historical filings remain; live queue has priority.',
                  flush=True)
            break
        # Oldest first; after every batch, update persistent memory before continuing.
        to_read = to_read.sort_values(['broadcast_date', 'broadcast_at'], ascending=True)
        to_read = add_memory_context(r2, to_read)
        batch_ids = set(to_read['event_id'].astype(str))
        saver = None if dry_run else ar.Saver(r2, today.isoformat(), today)
        rows, notes = ar.run(to_read, lanes, reads, batch_minutes * 60,
                             max_filings=batch_size, on_row=saver.add if saver else None)
        statuses = [ar.finish({**row, 'prompt_version': ar.PROMPT_VERSION,
                               'read_at': datetime.now(timezone.utc).isoformat()})
                    for row in status_rows.to_dict('records')]
        if saver:
            saver.pending.extend(statuses)
            saver.flush(final=True)
        else:
            rows.extend(statuses)
        total_new += len(rows)
        if not dry_run:
            reads = month_parquet(r2, ar.READS_PREFIX, start.strftime('%Y-%m')) if month_only and one_month else all_parquet(r2, ar.READS_PREFIX)
            touched = set(to_read.get('isin', pd.Series(dtype=str)).dropna().astype(str))
            if month_only:
                memories = upsert_company_memories(r2, rows)
            else:
                memories = persist_company_memories(r2, reads, touched)
            state['company_memories_written'] = int(state.get('company_memories_written', 0)) + memories
        counts_now = pd.Series([r.get('status') for r in rows]).value_counts().to_dict() if rows else {}
        # Recount the eligible queue from the persisted read archive. Do not infer
        # completion from batch return counts: retries, status rows, and partial
        # batches can make that estimate inaccurate.
        if not dry_run:
            remaining_rows, _, _ = ar.choose(candidates, reads, today, date_from=start, date_to=end)
            remaining_now = len(remaining_rows)
        else:
            remaining_now = max(0, len(to_read) - len(rows))
        if month_only and not dry_run:
            # Count historical calls in the same daily quota ledger used by the live reader.
            ar.append_usage(r2, today.isoformat(), {
                'at': datetime.now(timezone.utc).isoformat(),
                'source': 'historical_backfill',
                'counts': counts,
                'outcomes': counts_now,
                'added': saver.added if saver else 0,
                'usage': ar.usage(clients, lanes),
                'notes': setup,
            })
        state.update({
            'status': 'running',
            'completed_batches': int(state.get('completed_batches', 0)) + 1,
            'last_batch_at': datetime.now(timezone.utc).isoformat(),
            'last_batch_counts': counts_now,
            'last_batch_candidate_count': len(batch_ids),
            'read': int((reads.get('status', pd.Series(dtype=str)) == 'read').sum()) if not reads.empty else 0,
            'failed': int((reads.get('status', pd.Series(dtype=str)) == 'failed').sum()) if not reads.empty else 0,
            'remaining': remaining_now,
            'setup_notes': setup[-10:],
        })
        save_state(r2, state)
        print(f'Backfill batch {state["completed_batches"]}: candidates={len(batch_ids)}, outcomes={counts_now}, '
              f'memory companies updated={state.get("company_memories_written", 0)}', flush=True)
        if dry_run:
            break
        # Refresh candidate and read archives for a safe, idempotent next pass.
        reads = month_parquet(r2, ar.READS_PREFIX, start.strftime('%Y-%m')) if month_only and one_month else all_parquet(r2, ar.READS_PREFIX)
        if not reads.empty:
            dates = pd.to_datetime(reads['broadcast_date'], errors='coerce').dt.date
            reads = reads[dates >= start].copy()
        if 'event_id' in candidates:
            # Failed rows under MAX_TRIES are retried; completed and exhausted rows are filtered by choose().
            pass
    else:
        state['status'] = 'paused' if state.get('remaining', 0) else 'complete'
        save_state(r2, state)
    # Rebuild the memories of all companies seen in this backfill, not just the final batch.
    if not dry_run and not candidates.empty and not month_only:
        reads = all_parquet(r2, ar.READS_PREFIX)
        isins = set(candidates.get('isin', pd.Series(dtype=str)).dropna().astype(str))
        state['company_memories_written_final'] = persist_company_memories(r2, reads, isins)
        state['status'] = 'paused' if state.get('remaining', 0) else state.get('status', 'complete')
        save_state(r2, state)
    report = {
        'from': start.isoformat(), 'to': end.isoformat(), 'source_filings': len(candidates),
        'reads_archive_rows': len(reads), 'batches_this_run': min(max_batches, int(state.get('completed_batches', 0))),
        'status': state.get('status'), 'remaining': state.get('remaining'),
        'company_memories_written': state.get('company_memories_written_final', 0),
        'checkpoint': STATE_KEY, 'notes': setup,
    }
    summary = '### Historical announcement AI backfill\n\n' + '\n'.join(f'- **{k}:** {v}' for k, v in report.items())
    print(summary)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as f:
            f.write(summary + '\n')
    return 0


def run_continuous(start: date, end: date, batch_size: int, batch_minutes: float,
                    max_batches: int) -> int:
    """Live-first daily loop: collect one date, read only that date, then advance."""
    from r2_writer import r2_client

    r2 = r2_client()
    today = datetime.now(IST).date()
    setup = []
    if live_queue_pending(r2, today, setup):
        print('Historical AI deferred: eligible live filings remain.', flush=True)
        return 0

    # The live collector owns today/yesterday and the nightly collector owns the
    # last three days. Never compete with that live window.
    cutoff = min(end, today - timedelta(days=3))
    if cutoff < start:
        print(f'Historical worker waiting: no historical dates in {start}..{cutoff}.', flush=True)
        return 0

    state = read_state(r2)
    # The earlier backfill deliberately skipped BSE. On the first two-exchange
    # run, rewind to the requested start and revalidate old dates; NSE reads are
    # already deduplicated, while BSE-only filings now become eligible.
    expected_scope = ['NSE', 'BSE']
    if state.get('history_scope') != expected_scope:
        state['history_scope'] = expected_scope
        state['next_history_date'] = start.isoformat()
        state['scope_migration_at'] = datetime.now(timezone.utc).isoformat()
        save_state(r2, state)

    day = next_unfinished_history_day(r2, start, cutoff, state)
    if day is None:
        next_day = cutoff + timedelta(days=1)
        state.update(status='complete', remaining=0, next_history_date=next_day.isoformat())
        save_state(r2, state)
        print(f'Historical worker: every date through {cutoff} is complete.', flush=True)
        return 0

    day_text = day.isoformat()
    if not historical_day_collected(r2, day):
        print(f'Historical worker selected {day_text}: collecting this date only.', flush=True)
        collect_historical_day(r2, day)
    else:
        print(f'Historical worker selected {day_text}: verified collection checkpoint exists.', flush=True)

    before_batches = int(state.get('completed_batches', 0))
    run_backfill(day, day, batch_size, batch_minutes, max_batches=max_batches,
                 dry_run=False, month_only=True, nse_only=False)
    state = read_state(r2)
    after_batches = int(state.get('completed_batches', 0))

    # A multi-batch run may finish the date in the same workflow. Only advance
    # after the per-day AI completion conditions are explicitly satisfied.
    if state.get('status') == 'complete' and state.get('remaining') == 0:
        mark_historical_day_ai_complete(r2, day, state)
    elif after_batches > before_batches or state.get('pause_reason') == 'live_queue_pending':
        # Preserve the active date and durable cursor; the next workflow resumes it.
        state['active_history_date'] = day_text
        state['next_history_date'] = day_text
        state['status'] = 'paused'
        save_state(r2, state)
        print(f'Historical worker paused on {day_text} after {after_batches - before_batches} batch(es); '
              'next cycle resumes this date.', flush=True)
        return 0
    else:
        # No eligible work was processed and completion was not certified.
        state['active_history_date'] = day_text
        state['next_history_date'] = day_text
        state['status'] = 'running'
        save_state(r2, state)
        print(f'Historical worker did not certify completion for {day_text}; will retry this date.', flush=True)
        return 0

    completed_days = set(state.get('completed_history_dates', []))
    completed_days.add(day_text)
    state.update(
        status='running',
        remaining=None,
        completed_history_dates=sorted(completed_days),
        last_completed_history_date=day_text,
        active_history_date=None,
        next_history_date=(day + timedelta(days=1)).isoformat(),
    )
    save_state(r2, state)
    print(f'Historical date {day_text} is complete; the next cycle will start the next date.', flush=True)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--from', dest='start', type=date.fromisoformat, default=START_DEFAULT)
    parser.add_argument('--to', dest='end', type=date.fromisoformat, default=datetime.now(IST).date())
    parser.add_argument('--batch-size', type=int, default=20)
    parser.add_argument('--batch-minutes', type=float, default=8)
    parser.add_argument('--max-batches', type=int, default=3)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--continuous', action='store_true', help='live-first: process one batch from completed months only')
    args = parser.parse_args(argv)
    if args.end < args.start:
        parser.error('--to must be on or after --from')
    if args.batch_size < 1 or args.batch_minutes <= 0 or args.max_batches < 1:
        parser.error('batch-size, batch-minutes and max-batches must be positive')
    if args.continuous:
        if args.dry_run:
            parser.error('--continuous cannot be combined with --dry-run')
        return run_continuous(args.start, args.end, args.batch_size, args.batch_minutes, args.max_batches)
    return run_backfill(args.start, args.end, args.batch_size, args.batch_minutes, args.max_batches, args.dry_run)


if __name__ == '__main__':
    sys.exit(main())
