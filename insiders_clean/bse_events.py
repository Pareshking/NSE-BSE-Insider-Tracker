"""BSE SAST and corporate actions -> clean tables beside NSE's. No I/O.

A company listed on both exchanges files one SAST disclosure to each and has
one corporate action shown by both, so a BSE row that NSE's table also holds
is linked to it and marked `on_nse` (NSE is primary, as for insider filings);
the pages show NSE's row and the BSE rows NSE has not got (BSE-only companies,
and days before NSE's events collection began on 07 Oct 2026).

Links (each counted in the run report):
* SAST: same ISIN, same last trade date, same direction, and shares acquired
  (or sold) within 1% or 1 share. Names are not compared: filers type the
  acquirer differently on each exchange.
* Actions: same ISIN, purpose and ex-date.
"""
from __future__ import annotations

import pandas as pd

from .securities import SecurityMaster


def _day(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors='coerce').dt.normalize()


def add_identity(df: pd.DataFrame, master: SecurityMaster) -> pd.DataFrame:
    """ISIN from the BSE code; `symbol` becomes the NSE symbol when the
    company has one (pages and the Company page are keyed by it), else the
    BSE code."""
    df = df.copy()
    df['isin'] = [master.resolve('bse', c)[0] if isinstance(c, str) and c else None for c in df['bse_code']]
    recs = {i: master.record(i) for i in df['isin'].dropna().unique()}
    df['nse_symbol'] = df['isin'].map(lambda i: (recs.get(i) or {}).get('nse_symbol'))
    df['symbol'] = df['nse_symbol'].where(df['nse_symbol'].notna(), df['bse_code'])
    df['company_display'] = [(recs.get(i) or {}).get('display_name') or c for i, c in zip(df['isin'], df['company'])]
    df['unmatched_security'] = df['isin'].isna()
    return df


def _sast_keys(df: pd.DataFrame) -> pd.DataFrame:
    acq = df['action_type'].astype(str).str.lower().str.startswith('acq')
    shares = pd.to_numeric(df['shares_acquired'], errors='coerce').where(acq, pd.to_numeric(df['shares_sold'], errors='coerce'))
    return pd.DataFrame({'isin': df['isin'], 'day': _day(df['trade_date_to']), 'dir': acq.map({True: 'acq', False: 'sale'}),
                         'shares': shares, 'event_id': df['event_id']}, index=df.index)


def link_to_nse(bse: pd.DataFrame, nse: pd.DataFrame | None, stream: str) -> pd.DataFrame:
    """Adds `on_nse`, `nse_event_id` and `listed_on` ('bse' or 'bse,nse')."""
    bse = bse.copy()
    bse['on_nse'] = False
    bse['nse_event_id'] = None
    if nse is not None and not nse.empty and 'isin' in nse and not bse.empty:
        if stream == 'sast':
            b, n = _sast_keys(bse).reset_index(), _sast_keys(nse)
            m = b.merge(n.dropna(subset=['isin', 'day']), on=['isin', 'day', 'dir'], suffixes=('', '_nse'))
            close = (m['shares'] - m['shares_nse']).abs() <= (m['shares_nse'].abs() * 0.01).clip(lower=1)
            m = m[close]
        else:
            b = pd.DataFrame({'isin': bse['isin'], 'purpose': bse['purpose'], 'day': _day(bse['ex_date']),
                              'event_id': bse['event_id']}, index=bse.index).reset_index()
            n = pd.DataFrame({'isin': nse['isin'], 'purpose': nse['purpose'], 'day': _day(nse['ex_date']),
                              'event_id': nse['event_id']}).dropna(subset=['isin', 'day'])
            m = b.merge(n, on=['isin', 'purpose', 'day'], suffixes=('', '_nse'))
        first = m.drop_duplicates('index').set_index('index')['event_id_nse']
        bse.loc[first.index, 'on_nse'] = True
        bse.loc[first.index, 'nse_event_id'] = first
    bse['listed_on'] = bse['on_nse'].map({True: 'bse,nse', False: 'bse'})
    return bse


def clean(arch: pd.DataFrame | None, master: SecurityMaster, nse: pd.DataFrame | None, stream: str):
    """(clean BSE table, counts for the run report)."""
    if arch is None or arch.empty:
        return pd.DataFrame(), {'rows': 0}
    df = link_to_nse(add_identity(arch, master), nse, stream)
    counts = {'rows': len(df), 'on_nse': int(df['on_nse'].sum()), 'bse_only': int((~df['on_nse']).sum()),
              'unmatched_securities': int(df['unmatched_security'].sum()),
              'nse_rows_compared': 0 if nse is None else len(nse)}
    return df, counts


def with_bse(nse: pd.DataFrame, bse: pd.DataFrame) -> pd.DataFrame:
    """NSE's table plus the BSE rows NSE has not got, for the pages: a
    filing or action on both exchanges shows once (NSE's row)."""
    nse = nse.assign(listed_on='nse') if not nse.empty and 'listed_on' not in nse else nse
    if bse is None or bse.empty or 'on_nse' not in bse:
        return nse
    extra = bse[~bse['on_nse'].astype('boolean').fillna(False)]
    if nse.empty:
        return extra.reset_index(drop=True)
    return pd.concat([nse, extra], ignore_index=True)
