"""Re-read the saved exchange answers (raw_v2/, write-once, never changed here) into the archive: what the collectors
used to leave only in raw (owner, 21 Nov 2026: every line of every raw file must reach the database).

    python scripts/raw_reparse.py --targets all --dry-run      # counts only, writes nothing
    python scripts/raw_reparse.py --targets bse_actions,bse_meetings,bse_sast

No exchange is asked and no model called. The clean tables do not change: an archived row keeps every value and its
first_seen / last_seen, and a row added is one the clean tables leave out (kept = false, with its drop_reason), or a
line in a table of its own that no clean table reads (insiders_clean/archive.backfill). A kept row found in raw but
not in the archive is counted (`kept_not_archived`), never added: that would change a clean table.

Targets:

* rows the collectors dropped, added with kept = false (archive/{bse,nse}_events/{stream}/year=YYYY.parquet):
  bse_actions, bse_meetings, bse_sast, nse_actions, nse_meetings. Board meetings are grouped per fetch day (the
  answers of one night together, as the collector unites them); BSE SAST over every distinct raw row, the archived
  row of a disclosure first, so a repeat that differs outside the id is added as a repeat (parsers.SAST_REPEAT);
* lossless copies filled on rows already archived (where the archive has none): nse_tenders (bids_json),
  nse_announcements and bse_announcements (raw_json; `--add-missing` also adds a filing found only in raw),
  bse_bulk_deals and bse_block_deals (raw_json, archive/canonical/bse/{bulk,block}_deals/);
* their own tables, the lines added where missing: udiff_nse and udiff_bse (prices/udiff_extra/{nse,bse}/), nse_pr
  (archive/nse_pr/{kind}/; PR zips older than 30 days were deleted by scripts/storage_trim.py price_zips, counted
  here as `blob_missing`: fetch them again with Price backfill, `extras_only`), index_close (the five columns
  indices/daily/nse/ gained, filled where empty).

A blob whose bytes do not match its fetch record's SHA-256 is skipped and counted. The report goes to stdout, the
job summary and clean/reports/raw_reparse/{date}.json (not in a dry run).
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

from insiders_clean import archive, raw_store  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
WORKERS = 16


# --- reading raw_v2 -------------------------------------------------------------------------------------------------

def records(r2, source: str, dataset: str) -> list[dict]:
    """Fetch records of successful answers, oldest first, one per blob (its latest fetch)."""
    from clean_writer import get, list_keys
    keys = sorted(k for k in list_keys(r2, f'{raw_store.PREFIX}/{source}/{dataset}/fetches/') if k.endswith('.json'))

    def one(k):
        try:
            return json.loads(get(r2, k))
        except (TypeError, ValueError):
            return None
    with ThreadPoolExecutor(WORKERS) as pool:
        recs = [r for r in pool.map(one, keys) if isinstance(r, dict)]
    ok = [r for r in recs if int(r.get('http_status') or 0) == 200 and not r.get('content_check') and r.get('blob_key')]
    latest = {}
    for r in sorted(ok, key=lambda r: r.get('fetched_at_utc') or ''):
        latest[r['blob_key']] = r
    return sorted(latest.values(), key=lambda r: r.get('fetched_at_utc') or '')


def bodies(r2, recs: list[dict], stats: dict):
    """(record, bytes as sent) for each record whose blob is there and matches its SHA-256; the rest counted."""
    from clean_writer import get_blob

    def one(rec):
        return rec, get_blob(r2, rec['blob_key'])
    with ThreadPoolExecutor(WORKERS) as pool:
        for rec, body in pool.map(one, recs):
            if body is None:
                stats['blob_missing'] = stats.get('blob_missing', 0) + 1
                continue
            if raw_store.sha256_hex(body) != rec.get('sha256'):
                stats['sha256_differs'] = stats.get('sha256_differs', 0) + 1
                continue
            stats['blobs_read'] = stats.get('blobs_read', 0) + 1
            yield rec, body


def json_rows(body: bytes) -> list[dict]:
    """The row list of a JSON answer: a list, or the dict's `data` / `Table`."""
    data = json.loads(body.decode('utf-8', errors='replace'))
    if isinstance(data, dict):
        data = next((data[k] for k in ('data', 'Table') if isinstance(data.get(k), list)), [])
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []


def by_day(pairs) -> dict:
    """{fetch day: [(record, bytes)]}: the answers of one night together."""
    out: dict = {}
    for rec, body in pairs:
        out.setdefault((rec.get('fetched_at_utc') or '')[:10], []).append((rec, body))
    return dict(sorted(out.items()))


# --- writing the archive ---------------------------------------------------------------------------------------------

def parquet_keys(r2, prefix: str) -> list[str]:
    from clean_writer import list_keys
    return sorted(k for k in list_keys(r2, prefix) if k.endswith('.parquet'))


def read(r2, key: str, columns=None) -> pd.DataFrame | None:
    from clean_writer import get
    body = get(r2, key)
    return pd.read_parquet(io.BytesIO(body), columns=columns) if body is not None else None


def apply(r2, prefix: str, new: pd.DataFrame, key: str, partition, run_date: str, dry: bool, stats: dict,
          fill: tuple = (), add: bool = True, add_kept: bool = False) -> None:
    """Fill `fill` on archived rows and add the rows not archived (archive.backfill), one partition at a time.
    `partition(rows) -> Series` names each new row's partition file (relative to `prefix`, without .parquet)."""
    from clean_writer import put_parquet
    if new is None or new.empty:
        return
    new = new.drop_duplicates(key, keep='last')
    where: dict = {}
    for k in parquet_keys(r2, prefix):
        part = read(r2, k, columns=[key])
        if part is not None:
            where.update(dict.fromkeys(part[key].astype(str), k))
    ids = new[key].astype(str)
    known = ids.isin(where)
    stats['raw_rows'] = stats.get('raw_rows', 0) + len(new)
    stats['already_archived'] = stats.get('already_archived', 0) + int(known.sum())
    targets: dict = {}
    if fill:
        for k, rows in new[known].groupby(ids[known].map(where)):
            targets.setdefault(k, []).append(rows)
    fresh = new[~known]
    if add and len(fresh):
        for part, rows in fresh.groupby(partition(fresh)):
            targets.setdefault(f'{prefix}{part}.parquet', []).append(rows)
    elif len(fresh):
        stats['not_in_archive'] = stats.get('not_in_archive', 0) + len(fresh)
    for k, frames in sorted(targets.items()):
        rows = pd.concat(frames, ignore_index=True)
        merged, c = archive.backfill(read(r2, k), rows, run_date, key=key, fill=fill, add_kept=add_kept)
        for n, v in c.items():
            stats[n] = stats.get(n, 0) + v
        if (c['added'] or c['filled']) and not dry:
            put_parquet(r2, k, merged)
            stats.setdefault('written', []).append(k)


def merge_lines(r2, key: str, new: pd.DataFrame, id_cols: list, dry: bool, stats: dict) -> None:
    """A table of its own (UDiFF columns, PR zip members): lines not there are added; lines there are left as they
    are."""
    from clean_writer import put_parquet
    old = read(r2, key)
    both = pd.concat([old, new], ignore_index=True) if old is not None else new
    both = both.drop_duplicates(id_cols, keep='first').sort_values(id_cols).reset_index(drop=True)
    added = len(both) - (0 if old is None else len(old))
    stats['lines_added'] = stats.get('lines_added', 0) + added
    if added and not dry:
        for c in both.columns:
            if both[c].dtype == object:
                both[c] = both[c].astype('string')
        put_parquet(r2, key, both)
        stats.setdefault('written', []).append(key)


# --- targets ---------------------------------------------------------------------------------------------------------

def _bse_events():
    from collectors.bse import events, parsers
    return events, parsers


def _nse_events():
    from collectors.nse_events import parsers, run_daily
    return run_daily, parsers


def _concat(frames):
    frames = [f for f in frames if f is not None and len(f)]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def bse_actions(r2, run_date, dry, stats):
    events, parsers = _bse_events()
    new = _concat(parsers.parse_actions(json_rows(b), keep_all=True)[0]
                  for _, b in bodies(r2, records(r2, 'bse', 'corporate_actions'), stats))
    apply(r2, events.prefix('actions'), new, 'event_id', lambda d: events.year_of(d['ex_date']), run_date, dry, stats)


def bse_meetings(r2, run_date, dry, stats):
    events, parsers = _bse_events()
    frames = []
    for _, pairs in by_day(bodies(r2, records(r2, 'bse', 'board_meetings'), stats)).items():
        seen: dict = {}
        for _, b in pairs:   # the night's answers united, as meetings_window does
            data = json.loads(b.decode('utf-8', errors='replace'))
            for t in ('Table', 'Table1'):
                for r in (data.get(t) or []) if isinstance(data, dict) else []:
                    seen[(t, json.dumps(r, sort_keys=True, default=str))] = r
        payload = {t: [r for (tt, _), r in seen.items() if tt == t] for t in ('Table', 'Table1')}
        frames.append(parsers.parse_board_meetings(payload, keep_all=True)[0])
    apply(r2, events.prefix('meetings'), _concat(frames), 'event_id', lambda d: events.year_of(d['meeting_date']),
          run_date, dry, stats)


def bse_sast(r2, run_date, dry, stats):
    """Every distinct raw row, the archived row of each disclosure first: parse_sast keeps the first of an event_id,
    so what the archive holds stays the disclosure, and the other rows of it are repeats."""
    events, parsers = _bse_events()
    raws: dict = {}
    for _, b in bodies(r2, records(r2, 'bse', 'sast'), stats):
        for r in json_rows(b):
            raws.setdefault(parsers._raw(r), r)
    stored = set()
    for k in parquet_keys(r2, events.prefix('sast')):
        part = read(r2, k, columns=['raw_json'])
        if part is not None:
            stored |= set(part['raw_json'].dropna().astype(str))
    ordered = [r for j, r in raws.items() if j in stored] + [r for j, r in raws.items() if j not in stored]
    new, _ = parsers.parse_sast(ordered, keep_all=True)
    apply(r2, events.prefix('sast'), new, 'event_id', lambda d: events.year_of(d['trade_date_to']), run_date, dry, stats)


def nse_actions(r2, run_date, dry, stats):
    run_daily, parsers = _nse_events()
    new = _concat(parsers.parse_corporate_actions(json_rows(b), keep_all=True)[0]
                  for _, b in bodies(r2, records(r2, 'nse', 'actions'), stats))
    apply(r2, run_daily.prefix('actions'), new, 'event_id', lambda d: run_daily.year_of(d['ex_date']), run_date, dry,
          stats)


def nse_meetings(r2, run_date, dry, stats):
    run_daily, parsers = _nse_events()
    frames = []
    for _, pairs in by_day(bodies(r2, records(r2, 'nse', 'meetings'), stats)).items():
        seen: dict = {}
        for _, b in pairs:
            for r in json_rows(b):
                seen.setdefault(json.dumps(r, sort_keys=True, default=str), r)
        frames.append(parsers.parse_board_meetings(list(seen.values()), keep_all=True)[0])
    new = _concat(frames)
    apply(r2, run_daily.prefix('meetings'), new, 'event_id', lambda d: run_daily.year_of(d['meeting_date']), run_date,
          dry, stats)


def nse_tenders(r2, run_date, dry, stats):
    run_daily, parsers = _nse_events()
    new = _concat(parsers.parse_tender_offers(json_rows(b)) for _, b in bodies(r2, records(r2, 'nse', 'tenders'), stats))
    if len(new):
        new = new[new['bids_json'].notna()][['event_id', 'bids_json']]
    apply(r2, run_daily.prefix('tenders'), new, 'event_id', None, run_date, dry, stats, fill=('bids_json',), add=False)


def _market(rec) -> str:
    m = re.search(r'index=(\w+)', rec.get('url') or '')
    return (rec.get('covers') or {}).get('index') or (m.group(1) if m else 'equities')


def announcements(source: str, add_missing: bool):
    def run(r2, run_date, dry, stats):
        if source == 'nse':
            from collectors.nse_events import announcements as ann
            parse = lambda rec, b: ann.parse(json_rows(b), _market(rec))  # noqa: E731
        else:
            from collectors.bse import announcements as ann
            parse = lambda rec, b: ann.parse(json_rows(b))  # noqa: E731
        new = _concat(parse(rec, b) for rec, b in bodies(r2, records(r2, source, 'announcements'), stats))
        if not add_missing and len(new):
            new = new[['event_id', ann.RAW_COLUMN]]
        apply(r2, ann.PREFIX, new, 'event_id', lambda d: d['broadcast_date'].map(ann.partition), run_date, dry, stats,
              fill=(ann.RAW_COLUMN,), add=add_missing, add_kept=add_missing)
    return run


def bse_deals(category: str):
    def run(r2, run_date, dry, stats):
        import r2_writer

        from collectors.bse import parsers
        rows = [r for _, b in bodies(r2, records(r2, 'bse', f'{category}_history'), stats)
                for r in parsers.deal_rows(json_rows(b))]
        new = pd.DataFrame({'canonical_event_id': [r2_writer.canonical_event_id('bse', category, r) for r in rows],
                            'raw_json': [r['raw_json'] for r in rows]})
        apply(r2, f'archive/canonical/bse/{category}/', new, 'canonical_event_id', None, run_date, dry, stats,
              fill=('raw_json',), add=False)
    return run


def udiff(exchange: str):
    def run(r2, run_date, dry, stats):
        from insiders_clean import prices
        def read(b):
            # BSE answers a day with no file with its home page and status 200 (scripts/price_backfill.py); such a
            # blob, or any that is not a UDiFF file, is counted and skipped, not allowed to stop the target.
            try:
                return prices.udiff_extra(b, exchange.upper())
            except Exception as exc:  # noqa: BLE001
                stats['blobs_unreadable'] = stats.get('blobs_unreadable', 0) + 1
                stats.setdefault('unreadable_reasons', {})
                k = type(exc).__name__
                stats['unreadable_reasons'][k] = stats['unreadable_reasons'].get(k, 0) + 1
                return None
        frames = _concat(f for f in (read(b) for _, b in bodies(r2, records(r2, 'exchange_files',
                                                                              f'{exchange}_udiff_cm'), stats))
                         if f is not None)
        if not len(frames):
            return
        tmpl = prices.UDIFF_EXTRA_KEY.replace('{exchange}', exchange)
        for month, rows in frames.groupby(pd.to_datetime(frames['date'], errors='coerce').dt.strftime('%Y-%m')):
            merge_lines(r2, tmpl.replace('{month}', month), rows, prices.UDIFF_EXTRA_ID, dry, stats)
    return run


def nse_pr(r2, run_date, dry, stats):
    from insiders_clean import market_cap
    found: dict = {}
    for rec, b in bodies(r2, records(r2, 'exchange_files', 'nse_pr_zip'), stats):
        day = (rec.get('covers') or {}).get('day')
        if not day:
            stats['no_day_in_record'] = stats.get('no_day_in_record', 0) + 1
            continue
        for kind, rows in market_cap.pr_members(b, day).items():
            found.setdefault(market_cap.PR_MEMBERS_KEY.format(kind=kind, month=str(day)[:7]), []).append(rows)
    for key, frames in sorted(found.items()):
        merge_lines(r2, key, pd.concat(frames, ignore_index=True), market_cap.PR_MEMBERS_ID, dry, stats)


def index_close(r2, run_date, dry, stats):
    """The columns indices/daily/nse/ gained on 21 Nov 2026, filled where a month's row has none (by date, index)."""
    from clean_writer import put_parquet

    from insiders_clean import index_close as ic
    new = _concat(ic.parse_index(b) for _, b in bodies(r2, records(r2, 'exchange_files', 'nse_index_close'), stats))
    if not len(new):
        return
    added_cols = [c for c in ic.COLUMNS if c not in ('date', 'symbol', 'open', 'high', 'low', 'close', 'volume',
                                                       'turnover_cr')]
    new = new.assign(_k=new['date'].dt.strftime('%Y-%m-%d') + '|' + new['symbol']).drop_duplicates('_k', keep='last')
    for month, rows in new.groupby(new['date'].dt.strftime('%Y-%m')):
        key = f'indices/daily/nse/{month}.parquet'
        old = read(r2, key)
        if old is None:
            stats['month_not_in_layer'] = stats.get('month_not_in_layer', 0) + 1
            continue
        k = pd.to_datetime(old['date']).dt.strftime('%Y-%m-%d') + '|' + old['symbol'].astype(str)
        src = rows.set_index('_k')
        filled = 0
        for c in added_cols:
            if c not in old.columns:
                old[c] = float('nan')
            hole = old[c].isna()
            got = k[hole].map(src[c])
            old.loc[got.dropna().index, c] = got.dropna()
            filled += int(got.notna().sum())
        stats['filled'] = stats.get('filled', 0) + filled
        if filled and not dry:
            put_parquet(r2, key, old)
            stats.setdefault('written', []).append(key)


TARGETS = {
    'bse_actions': bse_actions, 'bse_meetings': bse_meetings, 'bse_sast': bse_sast,
    'nse_actions': nse_actions, 'nse_meetings': nse_meetings, 'nse_tenders': nse_tenders,
    'nse_announcements': None, 'bse_announcements': None,
    'bse_bulk_deals': bse_deals('bulk_deals'), 'bse_block_deals': bse_deals('block_deals'),
    'udiff_nse': udiff('nse'), 'udiff_bse': udiff('bse'), 'nse_pr': nse_pr, 'index_close': index_close,
}


def run(r2, targets, dry: bool = False, run_date: str | None = None, add_missing: bool = False) -> dict:
    run_date = run_date or datetime.now(IST).date().isoformat()
    report = {'run_date': run_date, 'dry_run': dry, 'targets': {}}
    for name in targets:
        fn = TARGETS[name] or announcements(name.split('_')[0], add_missing)
        stats: dict = {}
        try:
            fn(r2, run_date, dry, stats)
        except Exception as exc:  # noqa: BLE001 -- one target failing is reported; the others go on
            stats['failed'] = f'{type(exc).__name__}: {exc}'[:300]
        report['targets'][name] = stats
        print(f'{name}: {json.dumps({k: v for k, v in stats.items() if k != "written"}, default=str)}', flush=True)
    return report


def markdown(report: dict) -> str:
    out = ['## Raw re-read into the archive' + (' (dry run, nothing written)' if report['dry_run'] else ''), '',
           '| target | blobs read | raw rows | already archived | added | filled | lines added | kept rows not archived '
           '| other |', '|---|---:|---:|---:|---:|---:|---:|---:|---|']
    main = ('blobs_read', 'raw_rows', 'already_archived', 'added', 'filled', 'lines_added', 'kept_not_archived')
    for name, s in report['targets'].items():
        other = '; '.join(f'{k} {v}' for k, v in s.items() if k not in main and k != 'written')
        out.append(f'| {name} | ' + ' | '.join(f'{s.get(k, 0):,}' for k in main) + f' | {other} |')
    return '\n'.join(out) + '\n'


def parse_targets(text: str) -> list[str]:
    names = [t.strip() for t in text.split(',') if t.strip()]
    if names == ['all']:
        return list(TARGETS)
    unknown = [n for n in names if n not in TARGETS]
    if unknown or not names:
        raise argparse.ArgumentTypeError(f'unknown target {unknown or text}; use all or ' + ', '.join(TARGETS))
    return names


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--targets', type=parse_targets, default=list(TARGETS))
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--add-missing', action='store_true', help='announcements: also add a filing found only in raw')
    ap.add_argument('--within', type=parse_targets, default=None,
                    help='only the asked targets among these (one workflow job per concurrency group)')
    args = ap.parse_args(argv)
    targets = [t for t in args.targets if args.within is None or t in args.within]
    if not targets:
        print('no target of this group asked')
        return 0
    from clean_writer import put
    from r2_writer import r2_client
    r2 = r2_client()
    report = run(r2, targets, args.dry_run, add_missing=args.add_missing)
    text = markdown(report)
    print(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as f:
            f.write(text)
    if not args.dry_run:
        put(r2, f"clean/reports/raw_reparse/{report['run_date']}.json",
            json.dumps(report, indent=2, default=str).encode(), 'application/json')
    return 1 if any('failed' in s for s in report['targets'].values()) else 0


if __name__ == '__main__':
    sys.exit(main())
