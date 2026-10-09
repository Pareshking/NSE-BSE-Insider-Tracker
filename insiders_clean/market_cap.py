"""NSE's daily market-cap file (`mcap{DDMMYYYY}.csv` inside the PR zip).

VERIFIED (09 Oct 2026): present for 2025-01-15 and 2026-10-08 with the same columns: trade date, symbol,
series, name, category, face value, issue size (shares in issue that day), close, market cap = issue size x close.
That makes shares outstanding point in time for NSE-listed names; no static snapshot is needed.
The file name's case differs between years (`MCAP15012025.csv`, `mcap08102026.csv`).
"""
from __future__ import annotations

import io
import zipfile

import pandas as pd

COLUMNS = ['date', 'symbol', 'series', 'name', 'category', 'face_value', 'issue_size', 'close', 'market_cap']
_MAP = {'trade date': 'date', 'symbol': 'symbol', 'series': 'series', 'security name': 'name', 'category': 'category',
        'face value(rs.)': 'face_value', 'issue size': 'issue_size', 'close price/paid up value(rs.)': 'close',
        'market cap(rs.)': 'market_cap'}


def mcap_member(z: zipfile.ZipFile) -> str:
    names = [n for n in z.namelist() if n.lower().startswith('mcap') and n.lower().endswith('.csv')]
    if len(names) != 1:
        raise ValueError(f'expected one mcap file in the PR zip, found {names}')
    return names[0]


def parse_mcap(body: bytes) -> pd.DataFrame:
    """Parse a PR zip or a bare mcap CSV. Raises ValueError if the layout is not the known one."""
    if body[:2] == b'PK':
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            body = z.read(mcap_member(z))
    raw = pd.read_csv(io.BytesIO(body), dtype=str, keep_default_na=False)
    raw.columns = [c.strip().lower() for c in raw.columns]
    missing = [c for c in _MAP if c not in raw.columns]
    if missing:
        raise ValueError(f'not an NSE mcap file, missing columns: {missing}')
    df = raw[list(_MAP)].rename(columns=_MAP)
    for c in ('symbol', 'series', 'name', 'category'):
        df[c] = df[c].str.strip()
    df['date'] = pd.to_datetime(df['date'].str.strip(), format='%d %b %Y', errors='coerce')
    for c in ('face_value', 'issue_size', 'close', 'market_cap'):
        df[c] = pd.to_numeric(df[c].str.strip().str.replace(',', '', regex=False).replace('', pd.NA), errors='coerce')
    return df[df['symbol'] != ''][COLUMNS].reset_index(drop=True)


def validate(df: pd.DataFrame) -> dict:
    """Market cap should equal issue size x close; count rows that do not (the rows stay)."""
    ok = (df['issue_size'] * df['close'] - df['market_cap']).abs() <= 0.01 * df['market_cap'].abs() + 1
    return {'rows': int(len(df)), 'unreadable_date': int(df['date'].isna().sum()),
            'no_issue_size': int(df['issue_size'].isna().sum()), 'mcap_not_size_x_close': int((~ok & df['market_cap'].notna()).sum()),
            'listed': int((df['category'] == 'Listed').sum())}
