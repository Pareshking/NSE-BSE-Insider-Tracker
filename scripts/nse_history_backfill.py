"""Historical backfill: NSE's history endpoints -> the partitioned archive.

    python scripts/nse_history_backfill.py --dataset insider            # one year back .. 02 May 2026
    python scripts/nse_history_backfill.py --dataset bulk --dry-run     # fetch + map, print counts, write nothing
    python scripts/nse_history_backfill.py --dataset all --local-out out/   # home-connection fallback
    python scripts/nse_history_backfill.py --dataset all --upload-from out/ # ... merged into R2 later

What it fetches (insiders_clean/history.py has the field maps):
* insider: /api/corporates-pit, one calendar quarter per call. NSE moved to a
  new system on 03 May 2026, which the nightly scraper covers, so this
  dataset ends on 02 May 2026.
* bulk / block: /api/historicalOR/bulk-block-short-deals?csv=true, one
  calendar year per call (the JSON form is capped at 70 rows). NSE serves bulk
  back to Jan 2004 and block to Nov 2005, but by the owner's decision (08 Oct
  2026) every dataset starts one year before the run date by default (the site
  grows daily from there); --from goes further. Unless --to is given, a deals backfill ends
  the day before the earliest nightly record in that dataset's archive, so
  history and nightly data never overlap.

Each chunk is mapped to the nightly row shape, turned into canonical rows by
r2_writer's own rows_to_parquet_bytes (intraday round trips flagged, not dropped) and merged into
archive/canonical/nse/{category}/year=YYYY/quarter=Q.parquet with
first_seen = last_seen = the run date. `last_merged` in _state.json is never
moved: retention uses it to decide which dated nightly snapshots the archive
has absorbed, and a backfill absorbs none of them. If the dataset has no
_state.json yet, none is created (clean_writer's first run builds the
archive from the dated files on top of the backfilled partitions).

Resumable: archive/_backfill/nse_{dataset}.json lists the chunks done, with
row counts; a rerun skips them. On HTTP 401/403/429, or a body that is not
JSON / CSV, the run stops at once, keeps what it finished and reports where
it stopped. A chunk that still fails after 3 retries (network error, 5xx) is
reported and left for the next run.

Report: clean/reports/backfill/{run_date}_{dataset}.json.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import random
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

import clean_writer
import r2_writer

from insiders_clean import archive
from insiders_clean.dates import parse_dates
from insiders_clean.history import deal_rows, pit_row

HOME = 'https://www.nseindia.com/'
PIT_URL = 'https://www.nseindia.com/api/corporates-pit'
DEALS_URL = 'https://www.nseindia.com/api/historicalOR/bulk-block-short-deals'
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/126.0.0.0 Safari/537.36')
HEADERS = {
    'User-Agent': UA,
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Connection': 'keep-alive',
}
REFERER = {
    'insider': 'https://www.nseindia.com/companies-listing/corporate-filings-insider-trading',
    'bulk': 'https://www.nseindia.com/report-detail/display-bulk-and-block-deals',
    'block': 'https://www.nseindia.com/report-detail/display-bulk-and-block-deals',
}
PACE_SECONDS = (4.0, 6.0)
RETRIES = 3
STOP_STATUSES = (401, 403, 429)
DEFAULT_YEARS_BACK = 1  # owner, 08 Oct 2026: one year of history, then daily data


def today_ist() -> date:
    return datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
EARLIEST_SANE = date(1990, 1, 1)

DATASETS = {
    'insider': {'category': 'insider_trading', 'from': None, 'to': date(2026, 5, 2),
                'last': date(2026, 5, 2), 'chunk': 'quarter',
                'date_fields': ('acqfromDt', 'acqtoDt', 'intimDt', 'broadcastDt')},
    'bulk': {'category': 'bulk_deals', 'from': None, 'to': None, 'last': None,
             'chunk': 'year', 'option': 'bulk_deals', 'date_fields': ('BD_DT_DATE',)},
    'block': {'category': 'block_deals', 'from': None, 'to': None, 'last': None,
              'chunk': 'year', 'option': 'block_deals', 'date_fields': ('BD_DT_DATE',)},
}
ORDER = ('insider', 'bulk', 'block')


class Stopped(Exception):
    """NSE refused us (401/403/429) or sent something that is not data."""


class Failed(Exception):
    """A chunk still failed after the retries (network error or 5xx)."""


# --- chunk planning -----------------------------------------------------------

def plan_chunks(start: date, end: date, unit: str) -> list[tuple[date, date]]:
    """Calendar quarters or years covering [start, end], clipped to it."""
    out, cur = [], start
    while cur <= end:
        if unit == 'quarter':
            q_end_month = ((cur.month - 1) // 3 + 1) * 3
            nxt = date(cur.year + (q_end_month == 12), q_end_month % 12 + 1, 1)
        elif unit == 'year':
            nxt = date(cur.year + 1, 1, 1)
        else:
            raise ValueError(unit)
        stop = min(nxt - timedelta(days=1), end)
        out.append((cur, stop))
        cur = nxt
    return out


def chunk_key(a: date, b: date) -> str:
    return f'{a.isoformat()}..{b.isoformat()}'


def nse_date(d: date) -> str:
    return d.strftime('%d-%m-%Y')


# --- HTTP ---------------------------------------------------------------------

class NseHistory:
    """One browser-like session: warm-up on the home page, one User-Agent for
    the whole run, 4-6 s between calls."""

    def __init__(self, session=None, sleep=time.sleep, rng=None, pace=PACE_SECONDS, raw=None):
        self.raw = raw  # insiders_clean.raw_store.RawStore or None (dry run / local)
        self.session = session or requests.Session()
        self.session.headers.update(HEADERS)
        self.sleep, self.rng, self.pace = sleep, rng or random.Random(), pace
        self.calls = 0
        self.warmed = False

    def _wait(self):
        if self.calls:
            self.sleep(self.rng.uniform(*self.pace))

    def _get(self, url, params=None, referer=None, raw_tag=None):
        headers = {'Referer': referer} if referer else {}
        if params is not None:
            headers['Accept'] = '*/*'
        last = None
        for attempt in range(RETRIES + 1):
            self._wait()
            self.calls += 1
            try:
                resp = self.session.get(url, params=params, headers=headers, timeout=60)
            except requests.RequestException as e:
                last = f'{type(e).__name__}: {e}'
                continue
            if resp.status_code in STOP_STATUSES:
                raise Stopped(f'HTTP {resp.status_code} from {url}')
            if resp.status_code >= 500:
                last = f'HTTP {resp.status_code} from {url}'
                continue
            if resp.status_code != 200:
                raise Stopped(f'HTTP {resp.status_code} from {url}')
            if self.raw is not None and raw_tag:
                # exact bytes first, before any parsing or validation
                try:
                    self.raw.put('nse', raw_tag[0], resp.content, url=url, params=params,
                                 status=resp.status_code, content_type=resp.headers.get('Content-Type'),
                                 covers=raw_tag[1])
                except Exception as e:  # noqa: BLE001 - never continue without the raw copy
                    raise Failed(f'raw store write failed: {type(e).__name__}: {e}') from e
            return resp
        raise Failed(f'{last} (after {RETRIES} retries)')

    def warm_up(self):
        """One best-effort visit for cookies. NSE (Akamai) answers the home
        page with 403 to GitHub's runners while the data APIs still answer
        them (the nightly scraper uses the API with no warm-up), so a refused
        warm-up is not a reason to stop (first backfill run, 08 Oct 2026)."""
        if self.warmed:
            return
        self.warmed = True
        try:
            self.session.get(HOME, timeout=30)
            self.calls += 1
        except requests.RequestException:
            pass

    def insider(self, a: date, b: date) -> list[dict]:
        self.warm_up()
        resp = self._get(PIT_URL, {'index': 'equities', 'from_date': nse_date(a), 'to_date': nse_date(b)},
                         REFERER['insider'], raw_tag=('insider', {'from': a.isoformat(), 'to': b.isoformat()}))
        try:
            payload = json.loads(resp.content)
        except ValueError:
            raise Stopped(f'not JSON from {PIT_URL} ({resp.content[:60]!r})') from None
        rows = payload.get('data') if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise Stopped(f'JSON without a data list from {PIT_URL}')
        return rows

    def deals(self, option: str, a: date, b: date) -> bytes:
        self.warm_up()
        resp = self._get(DEALS_URL, {'optionType': option, 'from': nse_date(a), 'to': nse_date(b),
                                     'csv': 'true'}, REFERER['bulk'],
                         raw_tag=(option or 'deals', {'from': a.isoformat(), 'to': b.isoformat()}))
        if not is_deals_csv(resp.content):
            raise Stopped(f'not CSV from {DEALS_URL} ({resp.content[:60]!r})')
        return resp.content


def is_deals_csv(body: bytes) -> bool:
    head = body.decode('utf-8-sig', errors='replace').lstrip()[:200]
    return head.startswith(('"Date', 'Date')) and 'Symbol' in head


# --- mapping ------------------------------------------------------------------

def mapped_rows(dataset: str, payload) -> list[dict]:
    if dataset == 'insider':
        return [pit_row(h) for h in payload]
    return deal_rows(payload)


def impossible_dates(dataset: str, rows: list[dict], run_date: str) -> int:
    """Rows with a date before 1990 or after the run date in any date field.
    They are stored as they came; the cleaner flags future dates."""
    if not rows:
        return 0
    df = pd.DataFrame(rows)
    bad = pd.Series(False, index=df.index)
    today = date.fromisoformat(run_date)
    for f in DATASETS[dataset]['date_fields']:
        if f not in df:
            continue
        year = pd.to_numeric(df[f].astype('string').str.extract(r'(\d{4})', expand=False), errors='coerce')
        future = parse_dates(df[f]).map(lambda d: d is not None and d > today).astype(bool)
        bad |= future | (year > today.year).fillna(False) | (year < EARLIEST_SANE.year).fillna(False)
    return int(bad.sum())


def canonical_frame(dataset: str, rows: list[dict]) -> tuple[pd.DataFrame | None, int]:
    """(canonical frame as the nightly writer stores it, round-trip rows flagged).
    Flagged rows stay in the frame (`intraday_round_trip`); nothing is dropped."""
    category = DATASETS[dataset]['category']
    if not rows:
        return None, 0
    body, _ = r2_writer.rows_to_parquet_bytes('nse', category, rows)
    frame = pd.read_parquet(io.BytesIO(body))
    return frame, int(frame['intraday_round_trip'].sum())


# --- R2 ---------------------------------------------------------------------

def progress_key(dataset):
    return f'archive/_backfill/nse_{dataset}.json'


def report_key(run_date, dataset):
    return f'clean/reports/backfill/{run_date}_{dataset}.json'


def load_json(client, key):
    body = clean_writer.get(client, key)
    return json.loads(body) if body else None


def put_json(client, key, obj):
    clean_writer.put(client, key, json.dumps(obj, indent=2, default=str).encode(), 'application/json')


def earliest_nightly_date(client, category) -> date | None:
    """Earliest record date among nightly (non-history) rows of one dataset's
    archive, scanning partitions from the oldest."""
    prefix = clean_writer.archive_prefix('nse', category)
    keys = [k for k in clean_writer.list_keys(client, prefix)
            if k.endswith('.parquet') and archive.UNKNOWN not in k]

    def order(k):
        part = k[len(prefix):-len('.parquet')]
        y, q = part.split('/')
        return int(y.split('=')[1]), int(q.split('=')[1])

    for k in sorted(keys, key=order):
        frame = clean_writer.read_parquet(client, k)
        if frame is None or frame.empty:
            continue
        frame = frame[~archive.from_history(frame)]
        if frame.empty:
            continue
        days = parse_dates(frame[archive.DATE_COLUMNS[category][0]]).dropna()
        if len(days):
            return min(days)
    return None


class R2Sink:
    """Merges chunks into the archive in R2 and keeps the progress file."""

    def __init__(self, client, dataset, run_date, redo=False):
        self.client, self.dataset, self.run_date, self.redo = client, dataset, run_date, redo
        self.category = DATASETS[dataset]['category']
        self.prefix = clean_writer.archive_prefix('nse', self.category)
        self.progress = load_json(client, progress_key(dataset)) or {
            'dataset': dataset, 'category': self.category, 'chunks': {}}

    def done(self) -> dict:
        # --redo refetches chunks already stored (e.g. to recover rows an
        # earlier version dropped); the archive merge is idempotent, so rows
        # already there only get last_seen moved.
        return {} if self.redo else self.progress['chunks']

    def store(self, key, a, b, frame, info) -> dict:
        added, parts = 0, []
        if frame is not None and not frame.empty:
            def load(part):
                return clean_writer.read_parquet(self.client, f'{self.prefix}{part}.parquet')
            touched, added = archive.merge_partitioned(load, frame, self.run_date, self.category)
            for part, merged in touched.items():
                clean_writer.put_parquet(self.client, f'{self.prefix}{part}.parquet', merged)
            parts = sorted(touched)
        info = dict(info, rows_added=added, partitions=parts, done_at=self.run_date)
        self.progress['chunks'][key] = dict(info, **{'from': a.isoformat(), 'to': b.isoformat()})
        self._update_state(added)
        self.progress['updated'] = datetime.now(timezone.utc).isoformat()
        put_json(self.client, progress_key(self.dataset), self.progress)
        return info

    def _update_state(self, added):
        """records and a backfill entry; last_merged is left as it is. No
        state file is created where the nightly hasn't built one."""
        key = clean_writer.archive_state_key('nse', self.category)
        state = load_json(self.client, key)
        if state is None:
            return
        state['records'] = int(state.get('records', 0)) + int(added)
        chunks = self.progress['chunks']
        state.setdefault('backfill', {})[self.dataset] = {
            'chunks_done': len(chunks), 'rows': sum(c.get('rows_stored', 0) for c in chunks.values()),
            'rows_added': sum(c.get('rows_added', 0) for c in chunks.values()), 'updated': self.run_date}
        put_json(self.client, key, state)

    def report(self, rep):
        put_json(self.client, report_key(self.run_date, self.dataset), rep)


class LocalSink:
    """--local-out: each chunk's canonical frame as a file, plus a local
    progress file so a home run resumes too."""

    def __init__(self, out_dir, dataset, run_date):
        self.dir = Path(out_dir) / f'nse_{dataset}'
        self.dir.mkdir(parents=True, exist_ok=True)
        self.dataset, self.run_date = dataset, run_date
        p = self.dir / 'progress.json'
        self.progress = json.loads(p.read_text()) if p.exists() else {'dataset': dataset, 'chunks': {}}

    def done(self) -> dict:
        return self.progress['chunks']

    def store(self, key, a, b, frame, info) -> dict:
        if frame is not None and not frame.empty:
            frame.to_parquet(self.dir / f'{key}.parquet', index=False)
        info = dict(info, file=f'{key}.parquet' if frame is not None and not frame.empty else None,
                    done_at=self.run_date)
        self.progress['chunks'][key] = dict(info, **{'from': a.isoformat(), 'to': b.isoformat()})
        (self.dir / 'progress.json').write_text(json.dumps(self.progress, indent=2, default=str))
        return info

    def report(self, rep):
        (self.dir / f'report_{self.run_date}.json').write_text(json.dumps(rep, indent=2, default=str))


class DrySink:
    def __init__(self, done=None):
        self._done = done or {}

    def done(self) -> dict:
        return self._done

    def store(self, key, a, b, frame, info) -> dict:
        return info

    def report(self, rep):
        pass


# --- the run ------------------------------------------------------------------

def resolve_range(dataset, start, end, client) -> tuple[date, date, str | None]:
    """(from, to, note). Deals without --to end the day before the earliest
    nightly record in the archive."""
    spec = DATASETS[dataset]
    note = None
    start = start or spec['from'] or (today_ist() - timedelta(days=365 * DEFAULT_YEARS_BACK))
    if end is None:
        if spec['to'] is not None:
            end = spec['to']
        else:
            if client is None:
                raise SystemExit(f'{dataset}: --to is required (no R2 access to read the archive)')
            first = earliest_nightly_date(client, spec['category'])
            if first is None:
                raise SystemExit(f'{dataset}: no archive in R2 yet; give --to explicitly')
            end = first - timedelta(days=1)
            note = f'--to defaulted to {end} (earliest archived record {first})'
    if spec['last'] and end > spec['last']:
        note = f'--to {end} clipped to {spec["last"]} (NSE changed systems on {spec["last"] + timedelta(days=1)})'
        end = spec['last']
    return start, end, note


def run_dataset(dataset, start, end, http: NseHistory | None, sink, run_date, payloads=None, log=print):
    """Fetch (or, with `payloads`, read local chunk frames), map and store
    every chunk not done yet. Returns the report dict."""
    spec = DATASETS[dataset]
    if payloads is not None:  # the local run's own chunks, inside [start, end]
        chunks = [tuple(date.fromisoformat(x) for x in k.split('..')) for k in sorted(payloads)]
        chunks = [(a, b) for a, b in chunks if a >= start and b <= end]
    else:
        chunks = plan_chunks(start, end, spec['chunk'])
    done = sink.done()
    rep = {'dataset': dataset, 'category': spec['category'], 'run_date': run_date,
           'from': start.isoformat(), 'to': end.isoformat(), 'chunks_planned': len(chunks),
           'chunks_skipped_done': 0, 'chunks_done': 0, 'rows_fetched': 0, 'rows_stored': 0,
           'rows_added': 0, 'round_trips_dropped': 0, 'impossible_dates': 0,
           'stopped_at': None, 'errors': [], 'chunks': {}}
    for a, b in chunks:
        key = chunk_key(a, b)
        if key in done:
            rep['chunks_skipped_done'] += 1
            continue
        try:
            if payloads is not None:
                frame, info = payloads[key]
            else:
                raw = http.insider(a, b) if dataset == 'insider' else http.deals(spec['option'], a, b)
                rows = mapped_rows(dataset, raw)
                frame, dropped = canonical_frame(dataset, rows)
                info = {'rows_fetched': len(rows), 'rows_stored': 0 if frame is None else len(frame),
                        'round_trips_dropped': dropped,
                        'impossible_dates': impossible_dates(dataset, rows, run_date)}
            info = sink.store(key, a, b, frame, info)
        except Stopped as e:
            rep['stopped_at'] = {'chunk': key, 'reason': str(e)}
            log(f'  STOP {dataset} {key}: {e}')
            break
        except Failed as e:
            rep['errors'].append({'chunk': key, 'error': str(e)})
            log(f'  FAIL {dataset} {key}: {e}')
            continue
        rep['chunks'][key] = info
        rep['chunks_done'] += 1
        for k in ('rows_fetched', 'rows_stored', 'rows_added', 'round_trips_dropped', 'impossible_dates'):
            rep[k] += int(info.get(k) or 0)
        log(f'  {dataset} {key}: fetched {info.get("rows_fetched", 0)}, stored {info.get("rows_stored", 0)}, '
            f'added {info.get("rows_added", "-")}, impossible dates {info.get("impossible_dates", 0)}')
    sink.report(rep)
    return rep


def local_payloads(in_dir, dataset) -> dict:
    """--upload-from: {chunk key: (frame, info)} from a --local-out run."""
    d = Path(in_dir) / f'nse_{dataset}'
    p = d / 'progress.json'
    if not p.exists():
        return {}
    progress = json.loads(p.read_text())
    out = {}
    for key, c in progress['chunks'].items():
        frame = pd.read_parquet(d / c['file']) if c.get('file') else None
        info = {k: c.get(k) for k in ('rows_fetched', 'rows_stored', 'round_trips_dropped', 'impossible_dates')}
        out[key] = (frame, info)
    return out


def _range_of_local(payloads) -> tuple[date, date]:
    keys = sorted(payloads)
    return date.fromisoformat(keys[0].split('..')[0]), date.fromisoformat(keys[-1].split('..')[1])


def main(argv=None, client=None, http=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--dataset', choices=('insider', 'bulk', 'block', 'all'), required=True)
    ap.add_argument('--from', dest='start', type=date.fromisoformat)
    ap.add_argument('--to', dest='end', type=date.fromisoformat)
    ap.add_argument('--redo', action='store_true', help='refetch chunks already marked done (idempotent merge)')
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true', help='fetch and map; write nothing')
    mode.add_argument('--local-out', metavar='DIR', help='write chunk files locally instead of R2')
    mode.add_argument('--upload-from', metavar='DIR', help='merge a --local-out run into R2')
    args = ap.parse_args(argv)

    run_date = os.environ.get('TARGET_DATE') or datetime.now(timezone.utc).date().isoformat()
    has_r2 = all(os.environ.get(k) for k in ('CLOUDFLARE_ACCOUNT_ID', 'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY'))
    if client is None and (has_r2 or not (args.dry_run or args.local_out)):
        client = r2_writer.r2_client()
    datasets = ORDER if args.dataset == 'all' else (args.dataset,)
    if http is None and not args.upload_from:
        raw = None
        if client is not None and not (args.dry_run or args.local_out):
            from insiders_clean.raw_store import RawStore
            raw = RawStore(client, collector='nse_history_backfill')
        http = NseHistory(raw=raw)

    reports, code = [], 0
    for ds in datasets:
        payloads = None
        if args.upload_from:
            payloads = local_payloads(args.upload_from, ds)
            if not payloads:
                print(f'{ds}: nothing in {args.upload_from}')
                continue
            lo, hi = _range_of_local(payloads)
            start, end, note = args.start or lo, args.end or hi, None
        else:
            start, end, note = resolve_range(ds, args.start, args.end, client)
        if start > end:
            print(f'{ds}: nothing to do ({start} > {end})')
            continue
        if args.dry_run:
            done = R2Sink(client, ds, run_date, redo=args.redo).done() if client is not None else {}
            sink = DrySink(done)
        elif args.local_out:
            sink = LocalSink(args.local_out, ds, run_date)
        else:
            sink = R2Sink(client, ds, run_date, redo=args.redo)
        print(f'{ds}: {start} .. {end}' + (f' ({note})' if note else '')
              + (' [dry run]' if args.dry_run else ''))
        rep = run_dataset(ds, start, end, http, sink, run_date, payloads=payloads)
        rep['mode'] = 'dry_run' if args.dry_run else 'local_out' if args.local_out else (
            'upload_from' if args.upload_from else 'r2')
        if note:
            rep['note'] = note
        reports.append(rep)
        print(f'{ds}: {rep["chunks_done"]} chunks done, {rep["chunks_skipped_done"]} already done, '
              f'{rep["rows_fetched"]} rows fetched, {rep["rows_added"]} added, '
              f'{rep["impossible_dates"]} with impossible dates, {len(rep["errors"])} errors')
        if rep['errors']:
            code = max(code, 1)
        if rep['stopped_at']:
            print(f'{ds}: stopped at {rep["stopped_at"]["chunk"]}: {rep["stopped_at"]["reason"]}')
            code = 2
            break
    return reports, code


if __name__ == '__main__':
    sys.exit(main()[1])
