"""Model basket (docs/TODO.md item 10): a paper portfolio run on rules fixed in
advance, from the forward record only, so nothing in it was chosen with
hindsight.

Rules (BASKET_VERSION):
* A position opens for every forward-record row (insiders_clean/track.py)
  whose signal's evidence verdict, stamped on the row the night it fired, was
  `leaning_positive` (insiders_clean/evidence.py), and whose stock carried no
  surveillance, trade-for-trade, SME or tight-band flag that night (the
  research's "exclude ASM/GSM and 5%-band stocks"; circuit days count too).
* Entry the close of the first session after the day made public (the
  record's own entry), equal weight, held HOLD_SESSIONS sessions, then sold
  at that close. COST_PCT off each position, on its entry day.
* One position per company at a time: a new row for a company already held
  is skipped, not added to.
* The basket's value moves each session with the average return of the
  positions open that session; with none open it holds cash (0%).
Rows recorded before the verdict was stamped (no `evidence` column) never open
a position.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .track import COST_PCT

BASKET_VERSION = '2026-10-12'
HOLD_SESSIONS = 63
EXCLUDE_FLAGS = ('asm', 'gsm', 'esm', 'ibc', 't2t', 'sme', 'band', 'circuit')


def _flagged(flags) -> bool:
    s = '' if flags is None or (isinstance(flags, float) and np.isnan(flags)) else str(flags).lower()
    return any(f in s for f in EXCLUDE_FLAGS)


def positions(ledger: pd.DataFrame, close: pd.DataFrame) -> pd.DataFrame:
    """One row per position: isin, signal, entry and exit date and price, open or closed, return after costs."""
    cols = ['isin', 'signal', 'day', 'entry_date', 'entry_price', 'exit_date', 'exit_price', 'status', 'ret']
    if ledger.empty or 'evidence' not in ledger or close.empty:
        return pd.DataFrame(columns=cols)
    sessions = close.index
    pick = ledger[(ledger['evidence'] == 'leaning_positive')
                  & ~ledger.get('trade_flags', pd.Series('', index=ledger.index)).map(_flagged)].copy()
    pick['day'] = pd.to_datetime(pick['day'])
    pick = pick.sort_values(['day', 'recorded_at'])
    rows, held_until = [], {}
    for r in pick.itertuples():
        p = sessions.searchsorted(r.day, side='right')
        if p >= len(sessions) or r.isin not in close:
            continue
        if held_until.get(r.isin, -1) >= p:
            continue  # already held: one position per company
        e0 = close.at[sessions[p], r.isin]
        if not np.isfinite(e0) or e0 <= 0:
            continue
        q = p + HOLD_SESSIONS
        done = q < len(sessions)
        last = q if done else len(sessions) - 1
        e1 = close[r.isin].iloc[p:last + 1].ffill().iloc[-1]
        held_until[r.isin] = q
        rows.append({'isin': r.isin, 'signal': r.signal, 'day': r.day, 'entry_date': sessions[p], 'entry_price': e0,
                     'exit_date': sessions[q] if done else pd.NaT, 'exit_price': e1 if done else np.nan,
                     'status': 'closed' if done else 'open', 'ret': (e1 / e0 - 1) * 100 - COST_PCT})
    return pd.DataFrame(rows, columns=cols)


def nav(pos: pd.DataFrame, close: pd.DataFrame, index_close: pd.Series) -> pd.DataFrame:
    """Daily value of the basket and of the index, both 100 on the first entry day."""
    if pos.empty:
        return pd.DataFrame(columns=['date', 'basket', 'index', 'open_positions'])
    sessions = close.index
    start = sessions.searchsorted(pos['entry_date'].min())
    days = sessions[start:]
    daily = close.ffill().pct_change()
    rets, n_open = [], []
    for i, d in enumerate(days):
        live = pos[(pos['entry_date'] < d) & (pos['exit_date'].isna() | (pos['exit_date'] >= d))]
        entering = int((pos['entry_date'] == d).sum())
        r = daily.loc[d, live['isin']].fillna(0).mean() * 100 if len(live) else 0.0
        held = len(live) + entering
        rets.append(r - (COST_PCT * entering / held if held else 0.0))
        n_open.append(held)
    ix = index_close.reindex(days).ffill()
    return pd.DataFrame({'date': days, 'basket': 100 * np.cumprod(1 + np.array(rets) / 100),
                         'index': 100 * ix.to_numpy() / ix.iloc[0], 'open_positions': n_open})
