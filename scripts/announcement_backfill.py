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


def all_parquet(r2, prefix: str) -> pd.DataFrame:
    """Read every Parquet partition under a prefix, paginating R2 listing."""
    from clean_writer import read_parquet
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
    frames = [df for key in sorted(keys) if (df := read_parquet(r2, key)) is not None and not df.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


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
    rows = reads[reads.get('isin', pd.Series(index=reads.index, dtype=object)).fillna('').astype(str) == isin]
    events = []
    for row in rows.sort_values(['broadcast_date', 'broadcast_at'], na_position='last').to_dict('records'):
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


def run_backfill(start: date, end: date, batch_size: int, batch_minutes: float,
                 max_batches: int, dry_run: bool = False) -> int:
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
    if not lanes:
        state.update(status='blocked', last_error='No model lane has a usable key/model')
        save_state(r2, state)
        raise RuntimeError(state['last_error'])

    used = ar.used_today(r2, today.isoformat())
    for lane in lanes.values():
        lane.used_today = used

    # Source archives are immutable-by-event-id and are read independently from read history.
    nse = all_parquet(r2, 'archive/announcements/nse/')
    bse = all_parquet(r2, 'archive/announcements/bse/')
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
    reads = all_parquet(r2, ar.READS_PREFIX)
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
                reads = all_parquet(r2, ar.READS_PREFIX)
            state.update(status='complete', remaining=0, candidates=len(candidates),
                         read=int((reads.get('status', pd.Series(dtype=str)) == 'read').sum()),
                         failed=int((reads.get('status', pd.Series(dtype=str)) == 'failed').sum()),
                         last_batch_at=datetime.now(timezone.utc).isoformat())
            save_state(r2, state)
            print(f'Historical backfill complete: no eligible filings remain in {start}..{end}.')
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
            reads = all_parquet(r2, ar.READS_PREFIX)
            touched = set(to_read.get('isin', pd.Series(dtype=str)).dropna().astype(str))
            memories = persist_company_memories(r2, reads, touched)
            state['company_memories_written'] = int(state.get('company_memories_written', 0)) + memories
        counts_now = pd.Series([r.get('status') for r in rows]).value_counts().to_dict() if rows else {}
        state.update({
            'status': 'running',
            'completed_batches': int(state.get('completed_batches', 0)) + 1,
            'last_batch_at': datetime.now(timezone.utc).isoformat(),
            'last_batch_counts': counts_now,
            'last_batch_candidate_count': len(batch_ids),
            'read': int((reads.get('status', pd.Series(dtype=str)) == 'read').sum()) if not reads.empty else 0,
            'failed': int((reads.get('status', pd.Series(dtype=str)) == 'failed').sum()) if not reads.empty else 0,
            'remaining': max(0, len(to_read) - len(rows)),
            'setup_notes': setup[-10:],
        })
        save_state(r2, state)
        print(f'Backfill batch {state["completed_batches"]}: candidates={len(batch_ids)}, outcomes={counts_now}, '
              f'memory companies updated={state.get("company_memories_written", 0)}', flush=True)
        if dry_run:
            break
        # Refresh candidate and read archives for a safe, idempotent next pass.
        reads = all_parquet(r2, ar.READS_PREFIX)
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
    if not dry_run and not candidates.empty:
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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--from', dest='start', type=date.fromisoformat, default=START_DEFAULT)
    parser.add_argument('--to', dest='end', type=date.fromisoformat, default=datetime.now(IST).date())
    parser.add_argument('--batch-size', type=int, default=20)
    parser.add_argument('--batch-minutes', type=float, default=8)
    parser.add_argument('--max-batches', type=int, default=3)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    if args.end < args.start:
        parser.error('--to must be on or after --from')
    if args.batch_size < 1 or args.batch_minutes <= 0 or args.max_batches < 1:
        parser.error('batch-size, batch-minutes and max-batches must be positive')
    return run_backfill(args.start, args.end, args.batch_size, args.batch_minutes, args.max_batches, args.dry_run)


if __name__ == '__main__':
    sys.exit(main())
