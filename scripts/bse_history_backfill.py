"""BSE insider filings and bulk / block deals, history and recent days -> the
partitioned archive (archive/canonical/bse/{category}/), beside the nightly rows.

    python scripts/bse_history_backfill.py --dataset all --dry-run       # product window, fetch + count only
    python scripts/bse_history_backfill.py --dataset insider             # 08 Oct 2025 .. today, resumable
    python scripts/bse_history_backfill.py --dataset all --recent 10     # nightly: the last 10 days again

Why: the nightly BSE capture reads BSE's page defaults (scripts/bse_raw_capture_v2.py):
today's deals, and an insider list of that day's filings plus a fixed block of
older ones. Nothing before the first nightly run, and no day the nightly
missed, was ever collected. BSE's own history endpoints (collectors/bse/client.py)
fill the product window and, run nightly with --recent, every day since.

* insider: the insider CSV, 10 days a call, filtered on the date reported to
  BSE. Mapped to the nightly row's field names (collectors/bse/parsers.py)
  plus what only the CSV has: the to-date and the date the insider told the
  company. The CSV spells modes and dates differently from the nightly JSON,
  so a filing both captured gets two archive ids; the clean step links them
  (reason `bse_same_filing_two_feeds`, insiders_clean/insider.py).
* bulk / block: BulkDealData_ng, 10 / 31 days a call. Mapped to exactly the
  nightly row, so a deal both captured has one id: rows whose id is already
  in the archive are not written again (counted `already_in_archive`).

Rows go through r2_writer.rows_to_parquet_bytes (round trips flagged, never
dropped) and archive.merge_partitioned, with first_seen = last_seen = the run
date and `source` = bse_insider_csv / bse_deals_history (added after the id,
so it is not part of it). `last_merged` in _state.json is never moved.

Resumable: archive/_backfill/bse_{dataset}.json lists the chunks done; a
rerun skips them (--recent always refetches and marks nothing). Stops at once
on 401/403/429 or a body that is not data, keeping what it finished.
Report: clean/reports/backfill/{run_date}_bse_{dataset}.json.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

import clean_writer
import r2_writer

from collectors.bse import parsers
from collectors.bse.client import BSEClient, Blocked, Failed
from insiders_clean import archive
from insiders_clean.pipeline import PRODUCT_START

DATASETS = {
    'insider': {'category': 'insider_trading', 'days': 10, 'source': parsers.INSIDER_SOURCE},
    'bulk': {'category': 'bulk_deals', 'days': 10, 'source': parsers.DEALS_SOURCE},
    'block': {'category': 'block_deals', 'days': 31, 'source': parsers.DEALS_SOURCE},
}
ORDER = ('insider', 'bulk', 'block')
IST = timezone(timedelta(hours=5, minutes=30))


def today_ist() -> date:
    return datetime.now(IST).date()


def plan(start: date, end: date, days: int) -> list[tuple[date, date]]:
    out, cur = [], start
    while cur <= end:
        stop = min(cur + timedelta(days=days - 1), end)
        out.append((cur, stop))
        cur = stop + timedelta(days=1)
    return out


def chunk_key(a: date, b: date) -> str:
    return f'{a.isoformat()}..{b.isoformat()}'


def fetch_rows(bse: BSEClient, dataset: str, a: date, b: date) -> list[dict]:
    if dataset == 'insider':
        return parsers.insider_rows(bse.insider_csv(a, b))
    return parsers.deal_rows(bse.deals(dataset, a, b))


def canonical_frame(dataset: str, rows: list[dict]) -> pd.DataFrame | None:
    """The canonical frame the nightly writer would store, plus `source`."""
    if not rows:
        return None
    body, _ = r2_writer.rows_to_parquet_bytes('bse', DATASETS[dataset]['category'], rows)
    return pd.read_parquet(io.BytesIO(body)).assign(source=DATASETS[dataset]['source'])


def progress_key(dataset):
    return f'archive/_backfill/bse_{dataset}.json'


def report_key(run_date, dataset):
    return f'clean/reports/backfill/{run_date}_bse_{dataset}.json'


def _json(client, key):
    body = clean_writer.get(client, key)
    return json.loads(body) if body else None


def _put_json(client, key, obj):
    clean_writer.put(client, key, json.dumps(obj, indent=2, default=str).encode(), 'application/json')


class R2Sink:
    """Merges chunks into the BSE archive in R2; keeps the progress file."""

    def __init__(self, client, dataset, run_date, redo=False, recent=False):
        self.client, self.dataset, self.run_date = client, dataset, run_date
        self.redo, self.recent = redo, recent
        self.category = DATASETS[dataset]['category']
        self.prefix = clean_writer.archive_prefix('bse', self.category)
        self.progress = _json(client, progress_key(dataset)) or {'dataset': dataset, 'category': self.category,
                                                                 'chunks': {}}

    def done(self) -> dict:
        return {} if self.redo or self.recent else self.progress['chunks']

    def store(self, key, a, b, frame, info) -> dict:
        added, parts, known = 0, [], 0
        if frame is not None and not frame.empty:
            loaded = {}

            def load(part):
                if part not in loaded:
                    loaded[part] = clean_writer.read_parquet(self.client, f'{self.prefix}{part}.parquet')
                return loaded[part]
            # A row the archive already has (a deal the nightly stored) is
            # left as it is: same id, same content.
            have = set()
            for part in archive.partitions(frame, self.category).unique():
                f = load(part)
                if f is not None and archive.KEY in f:
                    have |= set(f[archive.KEY].astype(str))
            new = frame[~frame[archive.KEY].astype(str).isin(have)]
            known = len(frame) - len(new)
            touched, added = archive.merge_partitioned(load, new, self.run_date, self.category)
            for part, merged in touched.items():
                clean_writer.put_parquet(self.client, f'{self.prefix}{part}.parquet', merged)
            parts = sorted(touched)
        info = dict(info, rows_added=added, already_in_archive=known, partitions=parts, done_at=self.run_date)
        if not self.recent:
            self.progress['chunks'][key] = dict(info, **{'from': a.isoformat(), 'to': b.isoformat()})
            self.progress['updated'] = datetime.now(timezone.utc).isoformat()
            _put_json(self.client, progress_key(self.dataset), self.progress)
        self._update_state(added)
        return info

    def _update_state(self, added):
        """records and a backfill entry; last_merged is left as it is, and
        no state file is created where the nightly has not built one."""
        key = clean_writer.archive_state_key('bse', self.category)
        state = _json(self.client, key)
        if state is None:
            return
        state['records'] = int(state.get('records', 0)) + int(added)
        entry = state.setdefault('backfill', {}).setdefault(self.dataset, {})
        entry.update(chunks_done=len(self.progress['chunks']), updated=self.run_date,
                     rows_added=int(entry.get('rows_added', 0)) + int(added))
        _put_json(self.client, key, state)

    def report(self, rep):
        _put_json(self.client, report_key(self.run_date, self.dataset), rep)


class DrySink:
    def __init__(self, done=None):
        self._done = done or {}

    def done(self) -> dict:
        return self._done

    def store(self, key, a, b, frame, info) -> dict:
        return info

    def report(self, rep):
        pass


def run_dataset(dataset, start, end, bse: BSEClient, sink, run_date, log=print) -> dict:
    spec = DATASETS[dataset]
    chunks = plan(start, end, spec['days'])
    done = sink.done()
    rep = {'dataset': dataset, 'exchange': 'bse', 'category': spec['category'], 'run_date': run_date,
           'from': start.isoformat(), 'to': end.isoformat(), 'chunks_planned': len(chunks),
           'chunks_skipped_done': 0, 'chunks_done': 0, 'rows_fetched': 0, 'rows_added': 0,
           'already_in_archive': 0, 'round_trips_flagged': 0, 'empty_chunks': 0, 'stopped_at': None,
           'errors': [], 'chunks': {}}
    for a, b in chunks:
        key = chunk_key(a, b)
        if key in done:
            rep['chunks_skipped_done'] += 1
            continue
        try:
            rows = fetch_rows(bse, dataset, a, b)
            frame = canonical_frame(dataset, rows)
            info = {'rows_fetched': len(rows),
                    'round_trips_flagged': 0 if frame is None else int(frame['intraday_round_trip'].sum())}
            info = sink.store(key, a, b, frame, info)
        except (Blocked, ValueError) as e:  # ValueError: a CSV without the expected columns
            rep['stopped_at'] = {'chunk': key, 'reason': str(e)}
            log(f'  STOP {dataset} {key}: {e}')
            break
        except Failed as e:
            rep['errors'].append({'chunk': key, 'error': str(e)})
            log(f'  FAIL {dataset} {key}: {e}')
            continue
        rep['chunks'][key] = info
        rep['chunks_done'] += 1
        rep['empty_chunks'] += int(not info.get('rows_fetched'))
        for k in ('rows_fetched', 'rows_added', 'already_in_archive', 'round_trips_flagged'):
            rep[k] += int(info.get(k) or 0)
        log(f'  bse {dataset} {key}: fetched {info.get("rows_fetched", 0)}, added {info.get("rows_added", "-")}, '
            f'already in archive {info.get("already_in_archive", "-")}')
    sink.report(rep)
    return rep


def main(argv=None, client=None, bse=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--dataset', choices=ORDER + ('all',), required=True)
    ap.add_argument('--from', dest='start', type=date.fromisoformat, help=f'default {PRODUCT_START}')
    ap.add_argument('--to', dest='end', type=date.fromisoformat, help='default today (IST)')
    ap.add_argument('--recent', type=int, metavar='DAYS', help='the last DAYS days again (nightly); marks nothing done')
    ap.add_argument('--redo', action='store_true', help='refetch chunks already marked done (idempotent merge)')
    ap.add_argument('--dry-run', action='store_true', help='fetch and map; write nothing')
    args = ap.parse_args(argv)

    run_date = os.environ.get('TARGET_DATE') or datetime.now(timezone.utc).date().isoformat()
    end = args.end or today_ist()
    start = end - timedelta(days=args.recent - 1) if args.recent else (args.start or PRODUCT_START)
    has_r2 = all(os.environ.get(k) for k in ('CLOUDFLARE_ACCOUNT_ID', 'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY'))
    if client is None and (has_r2 or not args.dry_run):
        client = r2_writer.r2_client()
    if bse is None:
        raw = None
        if client is not None and not args.dry_run:
            from insiders_clean.raw_store import RawStore
            raw = RawStore(client, collector='bse_history_backfill')
        bse = BSEClient(raw=raw)

    reports, code = [], 0
    try:
        for ds in (ORDER if args.dataset == 'all' else (args.dataset,)):
            if start > end:
                print(f'{ds}: nothing to do ({start} > {end})')
                continue
            if args.dry_run:
                done = R2Sink(client, ds, run_date, redo=args.redo, recent=bool(args.recent)).done() if client else {}
                sink = DrySink(done)
            else:
                sink = R2Sink(client, ds, run_date, redo=args.redo, recent=bool(args.recent))
            print(f'bse {ds}: {start} .. {end}' + (' [recent]' if args.recent else '') + (' [dry run]' if args.dry_run else ''))
            rep = run_dataset(ds, start, end, bse, sink, run_date)
            rep['mode'] = 'dry_run' if args.dry_run else 'recent' if args.recent else 'r2'
            rep['via'] = bse.via
            reports.append(rep)
            print(f'bse {ds}: {rep["chunks_done"]} chunks done, {rep["chunks_skipped_done"]} already done, '
                  f'{rep["rows_fetched"]} rows fetched, {rep["rows_added"]} added, '
                  f'{rep["already_in_archive"]} already in the archive, {rep["empty_chunks"]} empty chunks, '
                  f'{len(rep["errors"])} errors ({bse.via})')
            if rep['errors']:
                code = max(code, 1)
            if rep['stopped_at']:
                print(f'bse {ds}: stopped at {rep["stopped_at"]["chunk"]}: {rep["stopped_at"]["reason"]}')
                code = 2
                break
    finally:
        bse.close()
    return reports, code


if __name__ == '__main__':
    sys.exit(main()[1])
