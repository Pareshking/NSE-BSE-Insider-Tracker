"""NSE daily index closing file (`ind_close_all_DDMMYYYY.csv`): one row per index per session.

`symbol` holds the index name so the generic backfill code can key on it. Only the broad-market baseline
(Nifty 500) is used by the research; other indices are kept because they cost nothing."""
from __future__ import annotations

import io

import pandas as pd

# The last five since 21 Nov 2026 (owner: every raw field reaches a table): NSE's own day change in points and %, and
# the index's P/E, P/B and dividend yield, as printed. Months written before then lack them until re-parsed from
# raw_v2 (scripts/raw_reparse.py index_close).
COLUMNS = ['date', 'symbol', 'open', 'high', 'low', 'close', 'volume', 'turnover_cr',
           'points_change', 'change_pct', 'pe', 'pb', 'div_yield']
_MAP = {'index name': 'symbol', 'index date': 'date', 'open index value': 'open', 'high index value': 'high',
        'low index value': 'low', 'closing index value': 'close', 'volume': 'volume', 'turnover (rs. cr.)': 'turnover_cr',
        'points change': 'points_change', 'change(%)': 'change_pct', 'p/e': 'pe', 'p/b': 'pb', 'div yield': 'div_yield'}
BASELINE = 'Nifty 500'


def parse_index(body: bytes) -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(body), dtype=str)
    df.columns = [c.strip().lower() for c in df.columns]
    if 'index name' not in df.columns or 'closing index value' not in df.columns:
        raise ValueError('not an NSE index closing file')
    df = df.rename(columns=_MAP)
    df = df[[c for c in COLUMNS if c in df.columns]]
    df['symbol'] = df['symbol'].str.strip()
    df['date'] = pd.to_datetime(df['date'], format='%d-%m-%Y', errors='coerce')
    for c in COLUMNS[2:]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce')
    return df.dropna(subset=['date', 'close']).reset_index(drop=True)


def validate(df: pd.DataFrame) -> dict:
    b = df[df['symbol'] == BASELINE]
    return {'rows': int(len(df)), 'listed': int(len(df)), 'missing_baseline': int(len(b) == 0),
            'nonpositive_close': int((df['close'] <= 0).sum())}
