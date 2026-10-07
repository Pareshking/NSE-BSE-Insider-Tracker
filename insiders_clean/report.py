"""The cleaning report: what each rule removed, flagged or couldn't place.

Written next to the clean tables as clean/{date}/cleaning_report.json and
shown on the Data page, so a reader can see what was taken out and why.
"""
from __future__ import annotations

from collections import Counter

EXAMPLES_PER_REASON = 25


class Report:
    def __init__(self, run_date: str):
        self.data = {'run_date': run_date, 'tables': {}, 'unmatched_securities': [],
                     'unrecognised_values': {}, 'notes': []}

    def table(self, name: str) -> dict:
        return self.data['tables'].setdefault(name, {
            'input_rows': 0, 'output_rows': 0, 'removed': {}, 'flagged': {}, 'by_exchange': {}})

    def removed(self, table: str, reason: str, ids):
        ids = [str(i) for i in ids]
        if not ids:
            return
        entry = self.table(table)['removed'].setdefault(reason, {'count': 0, 'examples': []})
        entry['count'] += len(ids)
        room = EXAMPLES_PER_REASON - len(entry['examples'])
        entry['examples'] += ids[:max(room, 0)]

    def flagged(self, table: str, flag_lists):
        counts = Counter(f for flags in flag_lists for f in flags)
        t = self.table(table)['flagged']
        for flag, n in counts.items():
            t[flag] = t.get(flag, 0) + n

    def unrecognised(self, field: str, values):
        counts = Counter(v for v in values if v)
        if counts:
            bucket = self.data['unrecognised_values'].setdefault(field, {})
            for v, n in counts.items():
                bucket[v] = bucket.get(v, 0) + n

    def unmatched(self, rows):
        seen = {(r['exchange'], r['symbol']) for r in self.data['unmatched_securities']}
        for r in rows:
            key = (r['exchange'], r['symbol'])
            if key not in seen:
                seen.add(key)
                self.data['unmatched_securities'].append(r)

    def note(self, text: str):
        self.data['notes'].append(text)
