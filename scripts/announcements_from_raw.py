"""Rebuild announcement archive rows from the exact exchange answers we saved (raw_v2), without asking the exchange again.

Raw is write-once and keeps NSE's and BSE's whole answers; the archive is built from them by the collectors' own
`parse`. Until 15 Oct the collectors dropped concall filings before archiving (the 08 Oct decision); the owner's 15 Oct
decision is to capture everything, so this reads every saved answer of `raw_v2/nse/announcements/` and
`raw_v2/bse/announcements/`, parses it exactly as the collector does, keeps the concall rows (CONCALL) and merges them
into archive/announcements/{nse,bse}/ by event_id. Rows already archived are not touched, so a re-run adds nothing.

    python scripts/announcements_from_raw.py --dry-run     # counts only, writes nothing
    python scripts/announcements_from_raw.py               # both exchanges
    python scripts/announcements_from_raw.py --source bse
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

from collectors.bse import announcements as bann  # noqa: E402
from collectors.nse_events import announcements as nann  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))


def saved_answers(r2, source: str):
    """(fetch record, parsed JSON body) for every successful saved answer of the announcement list, once per body."""
    from clean_writer import get, list_keys
    seen = set()
    for key in sorted(k for k in list_keys(r2, f'raw_v2/{source}/announcements/fetches/') if k.endswith('.json')):
        raw = get(r2, key)
        try:
            rec = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if rec.get('http_status') != 200 or int(rec.get('bytes') or 0) <= 2 or rec.get('blob_key') in seen:
            continue
        seen.add(rec['blob_key'])
        body = get(r2, rec['blob_key'])
        try:
            yield rec, json.loads(body)
        except (TypeError, ValueError):
            continue


def concall_rows(r2, source: str) -> tuple[pd.DataFrame, dict]:
    stats = {'answers': 0, 'rows': 0}
    frames = []
    for rec, data in saved_answers(r2, source):
        if source == 'nse':
            rows = data if isinstance(data, list) else []
            market = (rec.get('covers') or {}).get('index') or (re.search(r'index=(\w+)', rec.get('url') or '') or [None, 'equities'])[1]
            df = nann.parse(rows, market)
            keep = df[df['subject'].isin(nann.CONCALL)]
        else:
            rows = data.get('Table') if isinstance(data, dict) else None
            df = bann.parse(rows or [])
            keep = df[df['subcategory'].isin(bann.CONCALL)]
        stats['answers'] += 1
        stats['rows'] += len(df)
        if not keep.empty:
            frames.append(keep)
    new = pd.concat(frames, ignore_index=True).drop_duplicates('event_id', keep='last') if frames else pd.DataFrame()
    stats['concall_rows'] = len(new)
    return new, stats


def rebuild(r2, sources=('nse', 'bse'), dry_run=False, run_date: str | None = None) -> dict:
    run_date = run_date or datetime.now(IST).date().isoformat()
    report = {'run_date': run_date, 'dry_run': dry_run, 'sources': {}}
    for source in sources:
        new, stats = concall_rows(r2, source)
        stats['by_month'] = ({str(k): int(v) for k, v in new['broadcast_date'].astype(str).str[:7].value_counts().sort_index().items()}
                             if len(new) else {})
        if not dry_run and len(new):
            merge = nann.merge_into_archive if source == 'nse' else bann.merge_into_archive
            stats['added'], stats['partitions'] = merge(r2, new, run_date)
        report['sources'][source] = stats
    return report


def markdown(report: dict) -> str:
    out = ['## Concall filings rebuilt from the saved exchange answers' + (' (dry run, nothing written)' if report['dry_run'] else ''), '']
    for source, s in report['sources'].items():
        out.append(f'- **{source.upper()}**: {s["answers"]} saved answers read, {s["rows"]:,} rows parsed, '
                   f'{s["concall_rows"]} concall rows' + (f', {s.get("added", 0)} new to the archive' if not report['dry_run'] else ''))
        out.append(f'  - by month: {s["by_month"]}')
    return '\n'.join(out) + '\n'


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--source', choices=['nse', 'bse', 'both'], default='both')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args(argv)
    from r2_writer import r2_client
    report = rebuild(r2_client(), ('nse', 'bse') if args.source == 'both' else (args.source,), args.dry_run)
    text = markdown(report)
    print(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as f:
            f.write(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
