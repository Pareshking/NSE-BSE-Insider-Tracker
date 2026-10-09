"""Daily prices from the exchanges' UDiFF bhavcopy files (NSE and BSE share one layout).

Checked against real files on 09 Oct 2026: both exchanges serve the same 34-column CSV for 2025-01-15 and
2026-10-08. Prices here are as printed on the day: never adjusted.
"""
from __future__ import annotations

import io
import zipfile

import pandas as pd

COLUMNS = ['date', 'exchange', 'isin', 'symbol', 'series', 'name', 'instrument_id', 'open', 'high', 'low',
           'close', 'last', 'prev_close', 'settle', 'volume', 'value', 'trades']
_MAP = {'TradDt': 'date', 'Src': 'exchange', 'ISIN': 'isin', 'TckrSymb': 'symbol', 'SctySrs': 'series',
        'FinInstrmNm': 'name', 'FinInstrmId': 'instrument_id', 'OpnPric': 'open', 'HghPric': 'high',
        'LwPric': 'low', 'ClsPric': 'close', 'LastPric': 'last', 'PrvsClsgPric': 'prev_close',
        'SttlmPric': 'settle', 'TtlTradgVol': 'volume', 'TtlTrfVal': 'value', 'TtlNbOfTxsExctd': 'trades'}
_NUM = ['open', 'high', 'low', 'close', 'last', 'prev_close', 'settle', 'volume', 'value', 'trades']


def csv_bytes(body: bytes) -> bytes:
    """The CSV inside a zip, or the bytes themselves when already a CSV."""
    if body[:2] == b'PK':
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            names = [n for n in z.namelist() if n.lower().endswith('.csv')]
            if len(names) != 1:
                raise ValueError(f'expected one CSV in the zip, found {names}')
            return z.read(names[0])
    return body


def parse_udiff(body: bytes, exchange: str | None = None) -> pd.DataFrame:
    """Parse one day's file into `COLUMNS`. Raises ValueError if the layout is not UDiFF equity."""
    raw = pd.read_csv(io.BytesIO(csv_bytes(body)), dtype=str, keep_default_na=False)
    missing = [c for c in _MAP if c not in raw.columns]
    if missing:
        raise ValueError(f'not a UDiFF file, missing columns: {missing}')
    df = raw[list(_MAP)].rename(columns=_MAP)
    if exchange:
        df['exchange'] = exchange.upper()
    df['date'] = pd.to_datetime(df['date'], format='%Y-%m-%d', errors='coerce')
    for c in _NUM:
        df[c] = pd.to_numeric(df[c].str.replace(',', '', regex=False).replace('', pd.NA), errors='coerce')
    for c in ('isin', 'symbol', 'series', 'name', 'instrument_id'):
        df[c] = df[c].str.strip()
    return df[COLUMNS]


def validate_day(df: pd.DataFrame) -> dict:
    """Counts of rows that break basic sanity; the rows stay, the report says what was seen."""
    traded = df['volume'].fillna(0) > 0
    bad_range = traded & ((df['high'] < df['low']) | (df['close'] > df['high']) | (df['close'] < df['low']))
    return {'rows': int(len(df)), 'unreadable_date': int(df['date'].isna().sum()),
            'no_isin': int((df['isin'] == '').sum()), 'no_close': int(df['close'].isna().sum()),
            'nonpositive_close': int((df['close'] <= 0).sum()), 'range_inconsistent': int(bad_range.sum()),
            'duplicate_key': int(df.duplicated(['isin', 'symbol', 'series']).sum())}
