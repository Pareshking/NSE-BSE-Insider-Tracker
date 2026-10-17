"""Golden-set replay summary: how many of the 100 cards have a shown headline, shown points, metrics, results with
QoQ/YoY, and what is held, per category. Reads announcement_reader_dry_run.json from a replay run (read-only).
usage: python scripts/golden_compare.py announcement_reader_dry_run.json [baseline.json]"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path


def cell(v):
    return v if isinstance(v, (dict, list)) else (json.loads(v) if isinstance(v, str) and v[:1] in '[{' else v)


def stats(rows):
    out = collections.Counter()
    by_cat = collections.defaultdict(collections.Counter)
    for r in rows:
        if r.get('status') != 'read':
            out['not_read:' + str(r.get('status'))] += 1
            continue
        out['read'] += 1
        h = cell(r.get('headline'))
        pts = cell(r.get('points')) or []
        mets = cell(r.get('metrics')) or []
        flds = cell(r.get('fields')) or []
        shown_h = bool(isinstance(h, dict) and h.get('shown'))
        out['headline_shown'] += shown_h
        out['no_headline'] += not shown_h
        out['points_shown'] += sum(bool(p.get('shown')) for p in pts if isinstance(p, dict))
        out['points_held'] += sum(not p.get('shown') for p in pts if isinstance(p, dict))
        out['metrics_shown'] += sum(bool(m.get('shown')) for m in mets if isinstance(m, dict))
        out['metrics_held'] += sum(not m.get('shown') for m in mets if isinstance(m, dict))
        out['fields_held'] += sum(not f.get('shown') for f in flds if isinstance(f, dict) and f.get('reason') != 'entity labels not shown yet')
        out['with_qoq_or_yoy'] += any(isinstance(m, dict) and m.get('shown') and m.get('changes_from') for m in mets)
        c = by_cat[str(r.get('category'))]
        c['cards'] += 1
        c['headline'] += shown_h
    return out, by_cat


def main(argv):
    rows = json.loads(Path(argv[0]).read_text())
    out, by_cat = stats(rows)
    print('| measure | now |' + (' before |' if len(argv) > 1 else ''))
    base = stats(json.loads(Path(argv[1]).read_text()))[0] if len(argv) > 1 else None
    print('|---|---|' + ('---|' if base else ''))
    for k in sorted(out):
        print(f'| {k} | {out[k]} |' + (f' {base[k]} |' if base else ''))
    print('\n| category | cards | headline shown |\n|---|---|---|')
    for k, c in sorted(by_cat.items(), key=lambda kv: -kv[1]['cards']):
        print(f"| {k} | {c['cards']} | {c['headline']} |")


if __name__ == '__main__':
    main(sys.argv[1:])
