"""Read-only: print the measured track record (artifacts/track_summary.parquet and
track_events.parquet in R2) as one table per signal, so the signals that lead the
site can be chosen from the data. Writes nothing."""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

from clean_writer import get  # noqa: E402
from r2_writer import r2_client  # noqa: E402

pd.set_option('display.width', 200)
pd.set_option('display.max_columns', 20)
pd.set_option('display.max_rows', 200)


def frame(client, key):
    body = get(client, key)
    return pd.read_parquet(io.BytesIO(body)) if body else None


def main():
    client = r2_client()
    summ = frame(client, 'artifacts/track_summary.parquet')
    ev = frame(client, 'artifacts/track_events.parquet')
    if summ is None or summ.empty:
        print('no track summary in R2')
        return
    print('summary columns:', list(summ.columns))
    if ev is not None and not ev.empty:
        print(f'events: {len(ev)}; days {pd.to_datetime(ev["day"]).min():%Y-%m-%d} to {pd.to_datetime(ev["day"]).max():%Y-%m-%d}')
        print('events per signal:', ev['signal'].value_counts().to_dict())
    for sig, g in summ.groupby('signal', sort=False):
        print(f'\n== {sig}: {g["label"].iloc[0]}')
        cols = [c for c in ('horizon', 'cases', 'median_excess', 'beat_index', 'median_return', 'mean_excess') if c in g.columns]
        print(g[cols].to_string(index=False))


if __name__ == '__main__':
    main()
