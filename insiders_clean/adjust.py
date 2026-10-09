"""Adjustment factors implied by the exchanges' own prices (both NSE and BSE).

Each UDiFF row carries `prev_close`, the exchange's base price for the session, which the exchange resets on
an ex-date for splits, bonuses and similar. So the implied factor on session t is
    f_t = prev_close_t / close_(t-1)
(1.0 when nothing happened). This needs no corporate-action feed, so BSE-only securities are covered the same
way as NSE ones. An action feed (NSE `bc` files, NSE API, later BSE) classifies the events, it does not create them.

Adjusted price at t = close_t x product of f_s for every later session s. A feature at signal time T must only use
factors with s <= T: `adjust_as_of` does this, so a past signal never sees a later split.
Threshold for a "structural" event (split, bonus, consolidation, demerger-like) is a config value; small moves are
kept separately as `minor` (cash dividends, rounding), never silently merged.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

STRUCTURAL = 0.05      # |f - 1| above this = structural event (config, to be tuned on data)
MINOR = 0.001          # |f - 1| above this but below STRUCTURAL = minor


def session_frame(prices: pd.DataFrame) -> pd.DataFrame:
    """One row per exchange, ISIN and date: the most traded series that day."""
    p = prices.dropna(subset=['date', 'close']).copy()
    p = p[p['isin'] != '']
    p['value'] = p['value'].fillna(0)
    p = p.sort_values(['exchange', 'isin', 'date', 'value'], ascending=[True, True, True, False])
    return p.drop_duplicates(['exchange', 'isin', 'date']).reset_index(drop=True)


def implied_factors(prices: pd.DataFrame, max_gap_days: int = 10) -> pd.DataFrame:
    """Per exchange, ISIN and session: `factor` (None when the previous print is missing or too old), `kind`."""
    s = session_frame(prices).sort_values(['exchange', 'isin', 'date'])
    g = s.groupby(['exchange', 'isin'], sort=False)
    s['last_close'] = g['close'].shift(1)
    s['last_date'] = g['date'].shift(1)
    gap = (s['date'] - s['last_date']).dt.days
    usable = s['last_close'].notna() & s['prev_close'].notna() & (s['last_close'] > 0) & (gap <= max_gap_days)
    s['factor'] = np.where(usable, s['prev_close'] / s['last_close'], np.nan)
    dev = (s['factor'] - 1).abs()
    s['kind'] = np.select([dev > STRUCTURAL, dev > MINOR, s['factor'].notna()], ['structural', 'minor', 'none'], 'unknown')
    return s[['exchange', 'isin', 'symbol', 'date', 'close', 'prev_close', 'last_close', 'factor', 'kind']]


def adjust_as_of(factors: pd.DataFrame, closes: pd.DataFrame, as_of, kinds=('structural',)) -> pd.DataFrame:
    """Adjust `closes` (exchange, isin, date, close) using only factors dated <= as_of."""
    f = factors[(factors['date'] <= pd.Timestamp(as_of)) & factors['kind'].isin(kinds)]
    f = f[['exchange', 'isin', 'date', 'factor']]
    out = closes[closes['date'] <= pd.Timestamp(as_of)].copy().sort_values(['exchange', 'isin', 'date'])
    out['adj_close'] = out['close']
    for (ex, isin), grp in f.groupby(['exchange', 'isin']):
        mask = (out['exchange'] == ex) & (out['isin'] == isin)
        d = out.loc[mask, 'date']
        mult = pd.Series(1.0, index=d.index)
        for fd, fv in zip(grp['date'], grp['factor']):
            mult[d < fd] *= fv
        out.loc[mask, 'adj_close'] = out.loc[mask, 'close'] * mult
    return out


def coverage(factors: pd.DataFrame) -> dict:
    return {'sessions': int(len(factors)), 'with_factor': int(factors['factor'].notna().sum()),
            'structural': int((factors['kind'] == 'structural').sum()), 'minor': int((factors['kind'] == 'minor').sum()),
            'unknown': int((factors['kind'] == 'unknown').sum())}
