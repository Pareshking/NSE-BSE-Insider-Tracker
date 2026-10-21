"""NSE's daily market-cap file (`mcap{DDMMYYYY}.csv` inside the PR zip).

VERIFIED (09 Oct 2026): present for 2025-01-15 and 2026-10-08 with the same columns: trade date, symbol,
series, name, category, face value, issue size (shares in issue that day), close, market cap = issue size x close.
That makes shares outstanding point in time for NSE-listed names; no static snapshot is needed.
The file name's case differs between years (`MCAP15012025.csv`, `mcap08102026.csv`).
"""
from __future__ import annotations

import io
import zipfile

import numpy as np
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


# --- Market cap at the trade date (clean step, read only) -------------------------------------------------------

DAILY_KEY = 'marketcap/daily/nse/{month}.parquet'
READ_COLUMNS = ['date', 'symbol', 'series', 'market_cap']
# Equity series, in the order a symbol's row is chosen when it prints in more than one on a day.
EQUITY_SERIES = ('EQ', 'BE', 'BZ', 'SM', 'ST', 'SZ')
# A trade takes the market cap of its own session, or of the last session before it within this many calendar
# days (a weekend, a holiday, a long Diwali break). Further back than that, or after the last day the layer holds
# (it is extended by the Price backfill workflow), there is no dated figure and the latest market cap is used.
MAX_STALE_DAYS = 10
BASES = ('trade_date', 'previous_session', 'latest', 'none')


def daily_frame(df: pd.DataFrame | None) -> pd.DataFrame:
    """Parsed mcap rows -> one row per symbol and date (an equity series first), market cap > 0."""
    cols = ['symbol', 'date', 'market_cap']
    if df is None or df.empty:
        return pd.DataFrame(columns=cols)
    d = df[[c for c in READ_COLUMNS if c in df.columns]].copy()
    d['symbol'] = d['symbol'].astype('string').str.strip().str.upper()
    d['date'] = pd.to_datetime(d['date'], errors='coerce').dt.normalize()
    d['market_cap'] = pd.to_numeric(d['market_cap'], errors='coerce')
    d = d[d['symbol'].fillna('').ne('') & d['date'].notna() & (d['market_cap'] > 0)]
    series = d['series'].astype('string').str.strip().str.upper() if 'series' in d else pd.Series('', index=d.index)
    rank = {s: i for i, s in enumerate(EQUITY_SERIES)}
    d['_rank'] = [rank.get(s, len(rank)) if isinstance(s, str) else len(rank) for s in series]
    d = d.sort_values(['symbol', 'date', '_rank']).drop_duplicates(['symbol', 'date'])
    d['symbol'] = d['symbol'].astype(object)
    return d[cols].reset_index(drop=True)


def load_daily(get, months) -> tuple[pd.DataFrame | None, dict]:
    """Read `marketcap/daily/nse/{month}.parquet` through `get(key) -> bytes | None`. A missing month is listed, an
    unreadable one is listed with its error; neither stops the clean step (those rows fall back to the latest cap)."""
    frames, found, missing, unreadable = [], [], [], {}
    for m in months:
        key = DAILY_KEY.format(month=m)
        try:
            body = get(key)
            if body is None:
                missing.append(key)
                continue
            frames.append(daily_frame(pd.read_parquet(io.BytesIO(body), columns=READ_COLUMNS)))
            found.append(key)
        except Exception as e:  # noqa: BLE001 -- one bad month must not stop the clean step
            unreadable[key] = f'{type(e).__name__}: {e}'
    info = {'months_read': len(found), 'months_missing': missing, 'months_unreadable': unreadable}
    frames = [f for f in frames if len(f)]
    if not frames:
        return None, info
    daily = daily_frame(pd.concat(frames, ignore_index=True))
    info.update(sessions=int(daily['date'].nunique()), first=str(daily['date'].min().date()),
                last=str(daily['date'].max().date()))
    return daily, info


def at_trade_date(symbols: pd.Series, days: pd.Series, daily: pd.DataFrame | None, latest: pd.Series,
                  fallback_symbols: pd.Series | None = None) -> pd.DataFrame:
    """Per row: `market_cap_at_trade` = NSE's market cap of that symbol on `days` (as of: the session itself, else
    the last one before it within MAX_STALE_DAYS), `market_cap_date` (the session used) and `market_cap_basis`
    (BASES). `fallback_symbols` is tried where `symbols` finds no dated figure (a symbol renamed since the trade).
    With no dated figure the row takes `latest` (basis 'latest'), or nothing ('none')."""
    idx = symbols.index
    out = pd.DataFrame({'market_cap_at_trade': np.nan, 'market_cap_date': pd.NaT}, index=idx)
    day = pd.to_datetime(days, errors='coerce').dt.normalize()
    if daily is not None and not daily.empty:
        right = daily.rename(columns={'date': '_mdate'})[['symbol', '_mdate', 'market_cap']].sort_values('_mdate')
        for syms in (symbols, fallback_symbols):
            if syms is None:
                continue
            todo = out['market_cap_at_trade'].isna().to_numpy()
            s = syms.astype('string').str.strip().str.upper()
            left = pd.DataFrame({'symbol': s.to_numpy(), '_day': day.to_numpy(), '_i': np.arange(len(idx))})[todo]
            left = left.dropna(subset=['symbol', '_day'])
            if left.empty:
                continue
            left['symbol'] = left['symbol'].astype(object)
            hit = pd.merge_asof(left.sort_values('_day'), right, left_on='_day', right_on='_mdate', by='symbol',
                                direction='backward', tolerance=pd.Timedelta(days=MAX_STALE_DAYS))
            hit = hit.dropna(subset=['market_cap'])
            rows = idx[hit['_i'].to_numpy()]
            out.loc[rows, 'market_cap_at_trade'] = hit['market_cap'].to_numpy()
            out.loc[rows, 'market_cap_date'] = hit['_mdate'].to_numpy()
    dated = out['market_cap_at_trade'].notna().to_numpy()
    same_day = (out['market_cap_date'] == day).to_numpy()
    lat = pd.to_numeric(latest, errors='coerce')
    lat = lat.where(lat > 0)
    use_latest = ~dated & lat.notna().to_numpy()
    out.loc[use_latest, 'market_cap_at_trade'] = lat[use_latest]
    out['market_cap_basis'] = np.select([dated & same_day, dated, use_latest],
                                        ['trade_date', 'previous_session', 'latest'], 'none')
    return out
