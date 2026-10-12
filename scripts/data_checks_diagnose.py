"""Read-only diagnostic for the clean step's data checks (TODO 19).

Runs the clean step as scripts/clean_writer.py does, on what is already in R2 (archive, reference files,
price layer), and writes nothing to R2: the client is wrapped so any call other than a read raises. Prints
aggregate counts (the repo is public) and leaves a run artifact in artifacts/data_checks/:

  summary.json        counts per check and outcome, by kind and exchange; how far outside the day's range
                      market trades fall (to set day_range.PRICE_TOLERANCE from data, not by guess)
  insider_checks.csv  each clean insider row a check touched: filing number and link, security, numbers
                      and dates the checks read, outcome, flags (no person names)

Usage: TARGET_DATE=YYYY-MM-DD python scripts/data_checks_diagnose.py
"""
from __future__ import annotations

import io
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

import clean_writer
from r2_writer import SECURITY_MASTER_PATH, TARGET_DATE, r2_client

from insiders_clean.calendar import seed_state
from insiders_clean.pipeline import run

OUT = ROOT / 'artifacts' / 'data_checks'
CHECK_FLAGS = ('holding_change_differs_from_quantity', 'holding_moves_against_side', 'missing_quantity',
               'value_off_by_power_of_ten', 'quantity_value_swapped', 'price_far_outside_day_range',
               'disclosed_before_trade', 'disclosure_dated_in_future', 'dates_out_of_order', 'trade_date_in_future')
BANDS = [0, 0.005, 0.01, 0.02, 0.03, 0.05, 0.1, 0.2, 0.5, 1, 10, 1e12]


class ReadOnly:
    """An R2 client that can only read."""
    ALLOWED = frozenset({'get_object', 'list_objects_v2', 'head_object'})

    def __init__(self, client):
        self._client = client
        self.exceptions = client.exceptions

    def __getattr__(self, name):
        if name not in self.ALLOWED:
            raise PermissionError(f'read-only diagnostic: {name} refused')
        return getattr(self._client, name)


def counts(s: pd.Series) -> dict:
    return {str(k): int(v) for k, v in s.value_counts(dropna=False).items()}


def outside_distance(df: pd.DataFrame) -> pd.Series:
    """How far a price outside the range is from its nearest edge, as a share of that edge."""
    above = df['price'] / df['day_high'] - 1
    below = df['day_low'] / df['price'] - 1
    return above.where(df['price'] > df['day_high']).fillna(below.where(df['price'] < df['day_low'])).dropna()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    client = ReadOnly(r2_client())
    run_day = date.fromisoformat(TARGET_DATE)
    notes, canonical = [], {}
    for ex in ('nse', 'bse'):
        for cat in clean_writer.CATEGORIES:
            arch = clean_writer.read_archive(client, ex, cat)
            if arch is not None and not arch.empty:
                canonical[(ex, cat)] = arch
            print(f'archive {ex}/{cat}: {0 if arch is None else len(arch)} rows')
    mcap = clean_writer.last_good(client, 'reference/market_cap/{day}/data.json', run_day, include_today=True)
    cal = clean_writer.get(client, clean_writer.CALENDAR_KEY)
    vr_path = ROOT / SECURITY_MASTER_PATH
    vr = pd.read_csv(vr_path, dtype=str, keep_default_na=False) if vr_path.exists() else None
    lists = []
    for name in clean_writer.NSE_LISTS:  # the stored copies: the diagnostic fetches nothing from NSE
        body = clean_writer.last_good(client, f'reference/security_lists/{{day}}/{name}', run_day, include_today=True)
        if body:
            lists.append(pd.read_csv(io.BytesIO(body), dtype=str, keep_default_na=False))
        else:
            notes.append(f'{name}: no stored copy in the last {clean_writer.LOOKBACK_DAYS} days')
    ranges, price_info = clean_writer.load_price_ranges(client, run_day, notes)
    tables, report = run(canonical, TARGET_DATE, json.loads(cal) if cal else seed_state(), vr_master=vr,
                         nse_lists=lists, market_cap_rows=json.loads(mcap) if mcap else [], price_ranges=ranges)
    ins = tables['insider_trades']
    t = report['tables'].get('insider_trades', {})
    summary = {'run_date': TARGET_DATE, 'notes': notes + report['notes'], 'price_layer': price_info,
               'report': {k: t.get(k) for k in ('flagged', 'marked', 'data_checks')}}
    if len(ins):
        mk = ins['is_market'].astype(bool)
        noq = ~(ins['quantity'].astype(float) > 0)
        summary['clean_table'] = {
            'rows': len(ins), 'needs_review': int(ins['needs_review'].sum()),
            'price_check_market_by_exchange': {ex: counts(g['price_check']) for ex, g in ins[mk].groupby('exchange')},
            'holding_check_by_kind': {k: counts(g['holding_check']) for k, g in ins.groupby('kind')},
            'outside_distance_bands_market': counts(pd.cut(outside_distance(ins[mk]), BANDS).astype(str)),
            'outside_distance_bands_all': counts(pd.cut(outside_distance(ins), BANDS).astype(str)),
            'no_quantity_by_mode_and_type': counts((ins.loc[noq, 'mode_raw'].astype(str) + ' | '
                                                    + ins.loc[noq, 'transaction_type_raw'].astype(str)).str.slice(0, 80)),
        }
    (OUT / 'summary.json').write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps(summary, indent=2, default=str))
    if len(ins):
        hit = ins[ins['flags'].fillna('').str.contains('|'.join(CHECK_FLAGS)) | ins['marks'].fillna('').ne('')
                  | ins['kind'].eq('holding_only')
                  | (ins['is_market'].astype(bool) & ~ins['price_check'].isin(['inside', 'no_price_layer']))]
        keep = ['exchange', 'app_id', 'source_url', 'isin', 'symbol', 'person_role', 'kind', 'is_market', 'side',
                'mode_raw', 'transaction_type_raw', 'quantity', 'value', 'price', 'day_low', 'day_high', 'price_check',
                'holding_before', 'holding_after', 'holding_check', 'trade_date_from', 'trade_date_to',
                'intimation_date', 'broadcast_date', 'flags', 'marks']
        hit[keep].to_csv(OUT / 'insider_checks.csv', index=False)
        print(f'wrote {len(hit)} insider rows to {OUT}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
