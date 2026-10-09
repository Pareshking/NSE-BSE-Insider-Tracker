"""Adjustment factors implied by the exchanges' own prices (both NSE and BSE).

Each UDiFF row carries `prev_close`, the exchange's base price for the session, which the exchange resets on
an ex-date for splits, bonuses and similar. So the implied factor on session t is
    f_t = prev_close_t / close_(t-1)
(1.0 when nothing happened). This needs no corporate-action feed, so BSE-only securities are covered the same
way as NSE ones. An action feed (NSE `bc` files, NSE API, later BSE) classifies the events, it does not create them.

Adjusted price at t = close_t x product of f_s for every later session s. A feature at signal time T must only use
factors with s <= T: `adjust_as_of` does this, so a past signal never sees a later split.
A reset above 5% that matches a clean split/bonus/consolidation ratio is `split_bonus` and is the ONLY kind applied. Other large
resets (`other_large`: rights, demergers, relistings, series moves) and small ones (`minor`, mostly cash dividends) are counted, never applied.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

STRUCTURAL = 0.05      # |f - 1| above this = a large base-price reset (config)
MINOR = 0.001          # |f - 1| above this but below STRUCTURAL = minor
RATIO_TOL = 0.015      # a reset within 1.5% of a clean split/bonus ratio counts as one
KIND_ADJUSTED = ('split_bonus',)   # the only kind applied to prices (owner directive: splits and bonuses only)


def _clean_ratios() -> np.ndarray:
    """Factors a split, bonus or consolidation produces: 1/k (split into k), a/(a+b) (bonus b for a), k (consolidation)."""
    r = {1 / k for k in range(2, 21)} | {float(k) for k in range(2, 21)}
    r |= {a / (a + b) for a in range(1, 6) for b in range(1, 6)}
    return np.array(sorted(r))


_RATIOS = _clean_ratios()


def is_clean_ratio(f: np.ndarray) -> np.ndarray:
    f = np.asarray(f, dtype=float)
    d = np.abs(f[:, None] / _RATIOS[None, :] - 1)
    return np.nanmin(np.where(np.isnan(f)[:, None], np.inf, d), axis=1) <= RATIO_TOL


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
    big = (dev > STRUCTURAL).to_numpy()
    clean = is_clean_ratio(s['factor'].to_numpy())
    s['kind'] = np.select([big & clean, big, (dev > MINOR).to_numpy(), s['factor'].notna().to_numpy()],
                          ['split_bonus', 'other_large', 'minor', 'none'], 'unknown')
    return s[['exchange', 'isin', 'symbol', 'date', 'close', 'prev_close', 'last_close', 'factor', 'kind']]


def adjust_as_of(factors: pd.DataFrame, closes: pd.DataFrame, as_of, kinds=KIND_ADJUSTED) -> pd.DataFrame:
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
            'split_bonus': int((factors['kind'] == 'split_bonus').sum()),
            'other_large_not_adjusted': int((factors['kind'] == 'other_large').sum()), 'minor': int((factors['kind'] == 'minor').sum()),
            'unknown': int((factors['kind'] == 'unknown').sum())}


def inherit_nse(factors: pd.DataFrame) -> pd.DataFrame:
    """Dual-listed ISINs: BSE rows take the NSE factor and kind for the same date (owner directive: one verified
    adjustment per security). BSE-only ISINs keep their own factors; a BSE reset that is not a clean ratio stays unadjusted."""
    nse = factors[factors['exchange'] == 'NSE'][['isin', 'date', 'factor', 'kind']].rename(columns={'factor': 'n_factor', 'kind': 'n_kind'})
    dual = set(nse['isin'])
    out = factors.merge(nse, on=['isin', 'date'], how='left')
    take = (out['exchange'] == 'BSE') & out['isin'].isin(dual)
    out.loc[take, 'factor'] = out.loc[take, 'n_factor']
    out.loc[take, 'kind'] = out.loc[take, 'n_kind'].fillna('unknown')
    return out.drop(columns=['n_factor', 'n_kind'])
