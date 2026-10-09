"""Append new forward-ledger signals to R2 (`ledger/forward_ledger.parquet`). Append-only: existing rows are kept
byte-for-value; the job refuses to change any. Aggregate output only (public repo)."""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from insiders_clean import ledger as lg  # noqa: E402
from price_coverage import load_prefix  # noqa: E402

KEY = 'ledger/forward_ledger.parquet'


def main() -> int:
    import r2_writer
    client, bucket = r2_writer.r2_client(), r2_writer.BUCKET
    rd = lambda k: pd.read_parquet(io.BytesIO(client.get_object(Bucket=bucket, Key=k)['Body'].read()))  # noqa: E731
    trades = rd('clean/current/insider_trades.parquet')
    px = load_prefix(client, bucket, 'prices/daily/')
    px['date'] = pd.to_datetime(px['date'])
    from insiders_clean import evaluate as ev
    raw_close, raw_open = ev.price_panel(px, 'close'), ev.price_panel(px, 'open')
    names = trades.dropna(subset=['isin', 'company']).drop_duplicates('isin').set_index('isin')['company']
    now = pd.Timestamp.now(tz='UTC').tz_localize(None)
    v1 = lg.entries_for(lg.new_signals(trades), raw_close, raw_open, names, now)
    v2 = lg.entries_for(lg.new_campaign_signals(trades), raw_close, raw_open, names, now, rule=lg.RULE_V2)
    print(f'ledger: v1 candidates {len(v1)}, v2 candidate campaigns {len(v2)}')
    new = pd.concat([v1, v2], ignore_index=True)
    try:
        existing = rd(KEY)
    except Exception as e:  # noqa: BLE001
        if 'NoSuchKey' not in str(e) and '404' not in str(e):
            raise
        existing = None
    merged = lg.append_only(existing, new)
    added = len(merged) - (0 if existing is None else len(existing))
    if added:
        buf = io.BytesIO()
        merged.to_parquet(buf, index=False)
        client.put_object(Bucket=bucket, Key=KEY, Body=buf.getvalue())
    print(f'ledger: existing {0 if existing is None else len(existing)}, candidate signals {len(new)}, added {added}, total {len(merged)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
