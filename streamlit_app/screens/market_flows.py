"""Market flows in one line: what FPIs, DIIs and mutual funds did on the latest day each source has.

Reads `market_flows` (scripts/market_flows.py; columns in docs/DATA_DICTIONARY.md). Each source has its own
latest day (NSE's provisional figures are out the same evening, NSDL's custodian figures the next day, SEBI's
mutual fund figures about two weeks later), so each part of the line names its own date. Not placed on a page yet."""
from __future__ import annotations

import pandas as pd
from ui import kit

NSE_SEGMENTS = ('cash_nse_bse_msei', 'cash_nse')   # all three exchanges first; NSE alone if that is all there is
WHO = {'fpi': 'FPIs', 'dii': 'DIIs', 'mf': 'mutual funds'}


def _day(d) -> str:
    return f'{pd.Timestamp(d).day} {pd.Timestamp(d):%b}'


def _did(category: str, net) -> str:
    net = float(net)
    if net == 0:
        return f'{WHO[category]} were flat'
    return f'{WHO[category]} {"bought" if net > 0 else "sold"} {kit.rupees(abs(net) * 1e7)}'


def _latest(df: pd.DataFrame, source: str, segments) -> pd.DataFrame:
    """Rows of the first of `segments` the source has, on that segment's latest day."""
    rows = df[df['source'] == source]
    for seg in segments:
        part = rows[rows['segment'] == seg]
        if not part.empty:
            return part[part['date'] == part['date'].max()]
    return rows.iloc[0:0]


def flows_line(df: pd.DataFrame) -> str:
    """'FPIs bought ₹5,867 Cr, DIIs sold ₹3,160 Cr on 18 Nov (exchanges, provisional); NSDL: FPIs bought ₹11,266
    Cr of equity, reported 18 Nov; mutual funds sold ₹2,222 Cr of equity on 4 Nov (SEBI)'. Net figures; a source
    with no rows is left out; '' when there is nothing."""
    if df is None or df.empty or not {'date', 'source', 'segment', 'category', 'net_cr'} <= set(df.columns):
        return ''
    df = df.assign(date=pd.to_datetime(df['date']))
    parts = []
    nse = _latest(df, 'nse', NSE_SEGMENTS)
    if not nse.empty:
        by = nse.set_index('category')['net_cr']
        who = ', '.join(_did(c, by[c]) for c in ('fpi', 'dii') if c in by)
        where = 'exchanges' if nse['segment'].iloc[0] == 'cash_nse_bse_msei' else 'NSE'
        tag = ', provisional' if 'provisional' in nse and nse['provisional'].astype(bool).any() else ''
        parts.append(f'{who} on {_day(nse["date"].iloc[0])} ({where}{tag})')
    nsdl = _latest(df, 'nsdl', ('equity',))
    if not nsdl.empty:
        parts.append(f'NSDL: {_did("fpi", nsdl["net_cr"].iloc[0])} of equity, reported {_day(nsdl["date"].iloc[0])}')
    sebi = _latest(df, 'sebi', ('equity',))
    if not sebi.empty:
        parts.append(f'{_did("mf", sebi["net_cr"].iloc[0])} of equity on {_day(sebi["date"].iloc[0])} (SEBI)')
    line = '; '.join(parts)
    return line[:1].upper() + line[1:]
