"""Adjustment factors implied by the exchanges' own prices (both NSE and BSE).

Each UDiFF row carries `prev_close`, the exchange's base price for the session, which the exchange resets on
an ex-date for splits, bonuses and similar. So the implied factor on session t is
    f_t = prev_close_t / close_(t-1)
(1.0 when nothing happened). This needs no corporate-action feed, so BSE-only securities are covered the same
way as NSE ones. An action feed (NSE `bc` files, NSE API, later BSE) classifies the events, it does not create them.

Adjusted price at t = close_t x product of f_s for every later session s. A feature at signal time T must only use
factors with s <= T: `adjust_as_of` does this, so a past signal never sees a later split.
A reset that matches a filed bonus or split (NSE's and BSE's corporate actions, `expected_factors`) or, where none is
filed, a reset above 5% that matches a clean split/bonus/consolidation ratio is `split_bonus` and is the ONLY kind
applied (`kind_basis` says which). Other large resets (`other_large`: rights, demergers, relistings, series moves,
special dividends) and small ones (`minor`, mostly cash dividends) are counted, never applied.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

STRUCTURAL = 0.05      # |f - 1| above this = a large base-price reset (config)
MINOR = 0.001          # |f - 1| above this but below STRUCTURAL = minor
RATIO_TOL = 0.015      # a reset within 1.5% of a clean split/bonus ratio counts as one
KIND_ADJUSTED = ('split_bonus',)   # the only kind applied to prices (owner directive: splits and bonuses only)


# Bonus n:h (n new shares for every h held) moves the price by h/(h+n). Boards use small n and h, and h of 6 or 10
# beside 1-5 (1:6, 1:10, 3:10, 7:10, 11:10 are on NSE's lists; audit W7). h of 7, 8 or 9 is left out of the guess:
# with them almost any reset lands within the tolerance of some ratio (0.73 is 8/11 within 0.4%). A filed action
# (`expected_factors`) covers every ratio, whatever h.
BONUS_HELD = (1, 2, 3, 4, 5, 6, 10)


def _clean_ratios() -> np.ndarray:
    """Factors a split, bonus or consolidation produces: 1/k (split into k), k (consolidation), a/(a+b) (bonus b
    for a held, a and b up to 5), and h/(h+n) for a bonus n:h with h in BONUS_HELD and n up to h + 1."""
    r = {1 / k for k in range(2, 21)} | {float(k) for k in range(2, 21)}
    r |= {a / (a + b) for a in range(1, 6) for b in range(1, 6)}
    r |= {h / (h + n) for h in BONUS_HELD for n in range(1, h + 2)}
    return np.array(sorted(r))


_RATIOS = _clean_ratios()


def is_clean_ratio(f: np.ndarray) -> np.ndarray:
    f = np.asarray(f, dtype=float)
    d = np.abs(f[:, None] / _RATIOS[None, :] - 1)
    return np.nanmin(np.where(np.isnan(f)[:, None], np.inf, d), axis=1) <= RATIO_TOL


def _ratio_factor(ratio) -> float:
    """'n:h' (n new for h held, NSE's and BSE's wording 'Bonus 1:3') -> h / (h + n)."""
    try:
        n, h = (float(x) for x in str(ratio).split(':'))
    except (TypeError, ValueError):
        return np.nan
    return h / (h + n) if n > 0 and h > 0 else np.nan


def expected_factors(actions: pd.DataFrame | None) -> pd.DataFrame:
    """Filed corporate actions (clean `actions` / `bse_actions`: isin, purpose, ex_date, ratio, face_value_from,
    face_value_to) -> one row per ISIN and ex-date: `expected` = the product of the factors of its bonuses
    (h/(h+n)) and splits (to/from face value), NaN when the date has no bonus or split, and `split_bonus` (bool).
    A date with only a dividend, rights or buyback is kept: it says the reset that day is not a bonus or split."""
    cols = ['isin', 'ex_date', 'expected', 'split_bonus']
    if actions is None or actions.empty or not {'isin', 'purpose', 'ex_date'} <= set(actions.columns):
        return pd.DataFrame(columns=cols)
    a = actions.copy()
    a['ex_date'] = pd.to_datetime(a['ex_date'], errors='coerce').dt.normalize()
    a = a.dropna(subset=['isin', 'ex_date'])
    a = a[a['isin'].astype(str).str.strip() != '']
    purpose = a['purpose'].astype(str).str.lower()
    ratio = a['ratio'] if 'ratio' in a else pd.Series(None, index=a.index)
    fv_from = pd.to_numeric(a['face_value_from'], errors='coerce') if 'face_value_from' in a else np.nan
    fv_to = pd.to_numeric(a['face_value_to'], errors='coerce') if 'face_value_to' in a else np.nan
    a['_f'] = np.where(purpose.eq('bonus'), ratio.map(_ratio_factor),
                       np.where(purpose.eq('split'), fv_to / fv_from, np.nan))
    a['_sb'] = purpose.isin(['bonus', 'split'])
    # One filing seen twice (NSE and BSE, or two captures) counts once per purpose.
    a = a.drop_duplicates(['isin', 'ex_date', 'purpose', '_f'])
    g = a.groupby(['isin', 'ex_date'])
    out = pd.DataFrame({'expected': g['_f'].apply(lambda s: s.prod() if s.notna().any() else np.nan),
                        'split_bonus': g['_sb'].any()}).reset_index()
    out.loc[~out['split_bonus'], 'expected'] = np.nan
    return out[cols]


def session_frame(prices: pd.DataFrame) -> pd.DataFrame:
    """One row per exchange, ISIN and date: the most traded series that day."""
    p = prices.dropna(subset=['date', 'close']).copy()
    p = p[p['isin'] != '']
    p['value'] = p['value'].fillna(0)
    p = p.sort_values(['exchange', 'isin', 'date', 'value'], ascending=[True, True, True, False])
    return p.drop_duplicates(['exchange', 'isin', 'date']).reset_index(drop=True)


def _action_on_session(s: pd.DataFrame, exp: pd.DataFrame) -> pd.DataFrame:
    """Per session row: the filed action whose ex-date falls after the previous print and on or before this one
    (an illiquid stock may not trade on the ex-date itself). Columns `expected`, `split_bonus`, `has_action`."""
    out = pd.DataFrame({'expected': np.nan, 'split_bonus': False, 'has_action': False}, index=s.index)
    if exp.empty:
        return out
    left = s[['isin', 'date', 'last_date']].assign(_i=np.arange(len(s)))
    left = left[left['isin'].isin(set(exp['isin']))]
    m = left.merge(exp, on='isin', how='inner')
    m = m[(m['ex_date'] <= m['date']) & (m['last_date'].isna() | (m['ex_date'] > m['last_date']))]
    if m.empty:
        return out
    m = m.sort_values(['_i', 'split_bonus'], ascending=[True, False]).drop_duplicates('_i')
    rows = s.index[m['_i'].to_numpy()]
    out.loc[rows, 'expected'] = m['expected'].to_numpy()
    out.loc[rows, 'split_bonus'] = m['split_bonus'].to_numpy().astype(bool)
    out.loc[rows, 'has_action'] = True
    return out


def implied_factors(prices: pd.DataFrame, max_gap_days: int = 10, actions: pd.DataFrame | None = None) -> pd.DataFrame:
    """Per exchange, ISIN and session: `factor` (None when the previous print is missing or too old), `kind` and
    `kind_basis`. With `actions` (the filed corporate actions, `expected_factors`), a session whose reset falls on a
    filed bonus or split is `split_bonus` when the factor is within RATIO_TOL of the filed ratio (basis `action`,
    even under the 5% line: a 1:20 bonus moves the price 4.8%), and not adjusted when it differs
    (`action_mismatch`); a large reset on a date with only a dividend, rights or buyback filed is never taken for
    a bonus (`action_not_split_bonus`: a 20% special dividend is 0.8, the factor of a 1:4 bonus). Where no action
    is filed (BSE-only names, dates before the action history), the clean-ratio guess decides (`ratio`)."""
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
    s['kind_basis'] = np.where(big & clean, 'ratio', '')
    act = _action_on_session(s, expected_factors(actions))
    has, sb = act['has_action'].to_numpy(dtype=bool), act['split_bonus'].to_numpy(dtype=bool)
    with np.errstate(invalid='ignore', divide='ignore'):
        near = np.abs(s['factor'].to_numpy(dtype=float) / act['expected'].to_numpy(dtype=float) - 1) <= RATIO_TOL
    moved = (dev > MINOR).to_numpy()
    filed = has & sb & near & moved
    s.loc[filed, 'kind'], s.loc[filed, 'kind_basis'] = 'split_bonus', 'action'
    mismatch = has & sb & ~near & big
    s.loc[mismatch, 'kind'], s.loc[mismatch, 'kind_basis'] = 'other_large', 'action_mismatch'
    other = has & ~sb & big
    s.loc[other, 'kind'], s.loc[other, 'kind_basis'] = 'other_large', 'action_not_split_bonus'
    return s[['exchange', 'isin', 'symbol', 'date', 'close', 'prev_close', 'last_close', 'factor', 'kind',
              'kind_basis']]


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
            'unknown': int((factors['kind'] == 'unknown').sum()),
            'by_basis': ({str(k): int(v) for k, v in factors.loc[factors['kind_basis'] != '', 'kind_basis']
                          .value_counts().items()} if 'kind_basis' in factors else {})}


def inherit_nse(factors: pd.DataFrame) -> pd.DataFrame:
    """Dual-listed ISINs: BSE rows take the NSE factor and kind for the same date (owner directive: one verified
    adjustment per security). BSE-only ISINs keep their own factors; a BSE reset that is not a clean ratio stays unadjusted."""
    cols = ['factor', 'kind'] + (['kind_basis'] if 'kind_basis' in factors else [])
    ren = {c: f'n_{c}' for c in cols}
    nse = factors[factors['exchange'] == 'NSE'][['isin', 'date'] + cols].rename(columns=ren)
    dual = set(nse['isin'])
    out = factors.merge(nse, on=['isin', 'date'], how='left')
    take = (out['exchange'] == 'BSE') & out['isin'].isin(dual)
    out.loc[take, 'factor'] = out.loc[take, 'n_factor']
    out.loc[take, 'kind'] = out.loc[take, 'n_kind'].fillna('unknown')
    if 'kind_basis' in factors:
        out.loc[take, 'kind_basis'] = out.loc[take, 'n_kind_basis'].fillna('')
    return out.drop(columns=list(ren.values()))
