"""Forward-test ledger (docs/RESEARCH.md section F): an append-only record of promoter accumulation signals first
disclosed after the development period, followed as they mature.

Rule version `promoter_accum_v1`: a promoter / promoter-group open-market buy event (the day's filings combined)
with combined value >= Rs 25 lakh and disclosure date after 2026-06-30. Entry follows the research convention
(same close if disclosed before 14:00 IST, otherwise the next open). Only entry facts are stored; current price and
returns are computed from the price table when shown, so a later split or bonus is picked up and nothing is edited.

Owner-directed monitoring: showing outcomes of post-June events means the hold-out is no longer unseen for these
events (docs/DECISIONS.md). The ledger is a monitor, not the final test.
"""
from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd

from . import evaluate as ev, events as evm

RULE = 'promoter_accum_v1'
MIN_VALUE = 25e5
HORIZONS = (60, 120, 250)
COLUMNS = ['signal_id', 'rule', 'isin', 'company', 'disclosure_date', 'entry_date', 'entry_basis', 'entry_price',
           'value', 'n_filings', 'created_at']


def signal_id(isin: str, date) -> str:
    return hashlib.sha1(f'{RULE}|{isin}|{pd.Timestamp(date):%Y-%m-%d}'.encode()).hexdigest()[:16]


def new_signals(trades: pd.DataFrame) -> pd.DataFrame:
    e = evm.insider_events(trades, 'BUY', roles=evm.PROMOTER_ROLES)
    e = e[(pd.to_datetime(e['broadcast_date']) > evm.DEV_END) & (e['value'] >= MIN_VALUE)].copy()
    e['signal_id'] = [signal_id(i, d) for i, d in zip(e['isin'], e['broadcast_date'])]
    return e


def entries_for(sig: pd.DataFrame, close: pd.DataFrame, open_: pd.DataFrame, names: pd.Series, now) -> pd.DataFrame:
    """Entry date, basis and reference price (as printed on the entry day) for signals whose entry session exists."""
    ep = ev.entry_points(sig, close.index)
    rows = []
    for (_, r), pos, basis in zip(sig.iterrows(), ep['pos'], ep['basis']):
        if pd.isna(pos) or int(pos) >= len(close.index) or r['isin'] not in close.columns:
            continue
        pos = int(pos)
        price = open_.at[close.index[pos], r['isin']] if basis == 'open' else close.at[close.index[pos], r['isin']]
        if not np.isfinite(price) or price <= 0:
            continue
        rows.append({'signal_id': r['signal_id'], 'rule': RULE, 'isin': r['isin'], 'company': names.get(r['isin'], r['isin']),
                     'disclosure_date': pd.Timestamp(r['broadcast_date']), 'entry_date': close.index[pos], 'entry_basis': basis,
                     'entry_price': float(price), 'value': float(r['value']), 'n_filings': int(r['n_filings']),
                     'created_at': pd.Timestamp(now)})
    return pd.DataFrame(rows, columns=COLUMNS)


def append_only(existing: pd.DataFrame | None, new: pd.DataFrame) -> pd.DataFrame:
    """Existing rows are kept exactly; only signals not already present are added. Raises if a new row would
    contradict an existing signal (same id, different entry facts) - that would be an edit."""
    if existing is None or existing.empty:
        return new.reset_index(drop=True)
    clash = new.merge(existing, on='signal_id', suffixes=('', '_old'))
    for c in ('isin', 'entry_date', 'entry_price'):
        bad = clash[clash[c] != clash[c + '_old']]
        if len(bad):
            raise ValueError(f'ledger rows would change: {c} differs for {len(bad)} signals')
    add = new[~new['signal_id'].isin(existing['signal_id'])]
    return pd.concat([existing, add], ignore_index=True)


def mark(ledger: pd.DataFrame, close: pd.DataFrame, open_: pd.DataFrame, nifty: pd.Series) -> pd.DataFrame:
    """Latest price and, per horizon (60/120/250 sessions after the entry session), absolute and Nifty 500 excess
    return once matured. Before maturity the horizon columns are NaN and `to_date_*` shows the return so far.
    `close` and `open_` must be split/bonus adjusted panels."""
    sessions = close.index
    ix = nifty.reindex(sessions).ffill().to_numpy(dtype=float)
    out = ledger.copy()
    last_pos = len(sessions) - 1
    cols = {c: i for i, c in enumerate(close.columns)}
    cv = close.to_numpy()
    open_ = open_.reindex(index=sessions, columns=close.columns)
    cur, aret, xret, age = [], [], [], []
    hz = {h: ([], []) for h in HORIZONS}
    for _, r in out.iterrows():
        j = cols.get(r['isin'])
        pos = sessions.searchsorted(pd.Timestamp(r['entry_date']))
        basis = r['entry_basis']
        ok = j is not None and pos < len(sessions)
        base_px = None
        if ok:
            base_px = open_.at[sessions[pos], r['isin']] if basis == 'open' else cv[pos, j]
            base_px = base_px if np.isfinite(base_px) and base_px > 0 else None
        start = pos if basis == 'close' else pos - 1
        age.append(last_pos - pos)
        last_px = cv[last_pos, j] if ok else np.nan
        cur.append(last_px)
        aret.append(last_px / base_px - 1 if ok and base_px else np.nan)
        xret.append((last_px / base_px - 1) - (ix[last_pos] / ix[start] - 1) if ok and base_px and start >= 0 and np.isfinite(ix[start]) else np.nan)
        for h in HORIZONS:
            end = pos + h
            if ok and base_px and end <= last_pos and np.isfinite(cv[end, j]):
                hz[h][0].append(cv[end, j] / base_px - 1)
                hz[h][1].append((cv[end, j] / base_px - 1) - (ix[end] / ix[start] - 1) if start >= 0 else np.nan)
            else:
                hz[h][0].append(np.nan); hz[h][1].append(np.nan)
    out['sessions_since_entry'] = age
    out['current_price'] = cur
    out['return_to_date'] = aret
    out['excess_to_date_vs_nifty500'] = xret
    for h in HORIZONS:
        out[f'ret_{h}'], out[f'excess_{h}'] = hz[h]
    return out
