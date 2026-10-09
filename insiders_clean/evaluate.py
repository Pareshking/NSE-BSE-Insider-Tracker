"""Event-study core for the pre-registered hypotheses (docs/RESEARCH.md).

Pure functions on frames, no I/O. Conventions (fixed before any outcome was looked at):
- Signal time is the disclosure's dissemination (`broadcast_ts`; day-level `broadcast_date` if no time).
- Entry: same-session close when the disclosure came before 14:00 IST; otherwise the next session's open.
  Conservative variant: the next session's close. Never the transaction date or the insider's own price.
- Outcome = close `h` sessions after the entry session, on a price series adjusted for structural capital actions
  (splits, bonuses; see adjust.py). Cash dividends are not adjusted, so these are price returns. Outcome windows may
  contain later splits: that is realised information about the outcome, not a feature at signal time.
- Benchmark (owner directive 9 Oct 2026): one broad index, Nifty 500 closing values from NSE's index archive, next to the
  absolute return. The earlier equal-weighted and size-matched benchmarks were removed (micro-cap skew). Only complete
  windows count.
- Inference clusters by signal date: events disclosed the same day are not independent.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

HORIZONS = (5, 20, 60, 120, 250)
CUTOFF_HOUR = 14      # before this hour (IST) the same session's close is still a realistic entry


def price_panel(prices: pd.DataFrame, field: str) -> pd.DataFrame:
    """date x ISIN panel of `field`, NSE preferred, BSE filling the gaps."""
    p = prices.dropna(subset=['isin', field])
    p = p[p['isin'] != '']
    p = p.assign(_rank=(p['exchange'] != 'NSE').astype(int)).sort_values(['isin', 'date', '_rank', 'value'],
                                                                         ascending=[True, True, True, False])
    p = p.drop_duplicates(['isin', 'date'])
    return p.pivot(index='date', columns='isin', values=field).sort_index()


def entry_points(events: pd.DataFrame, sessions: pd.DatetimeIndex) -> pd.DataFrame:
    """Per event: entry session index and whether entry is that session's close ('close') or the next open ('open')."""
    ts = pd.to_datetime(events['broadcast_ts'], errors='coerce') if 'broadcast_ts' in events else pd.Series(pd.NaT, index=events.index)
    day = pd.to_datetime(events['broadcast_date'], errors='coerce').dt.normalize()
    day = day.fillna(ts.dt.normalize())
    has_time = ts.notna() & (ts.dt.hour > 0)
    early = has_time & (ts.dt.hour < CUTOFF_HOUR)
    pos_same = sessions.searchsorted(day.to_numpy(dtype='datetime64[ns]'), side='left')   # first session >= day
    is_session = (pos_same < len(sessions)) & (sessions[np.minimum(pos_same, len(sessions) - 1)] == day.to_numpy(dtype='datetime64[ns]'))
    pos_next = sessions.searchsorted(day.to_numpy(dtype='datetime64[ns]'), side='right')  # first session > day
    use_same = early.to_numpy() & is_session
    out = pd.DataFrame({'pos': np.where(use_same, pos_same, pos_next).astype(float),
                        'basis': np.where(use_same, 'close', 'open')}, index=events.index)
    out.loc[day.isna(), ['pos', 'basis']] = [np.nan, None]
    return out


def forward_returns(events: pd.DataFrame, close: pd.DataFrame, open_: pd.DataFrame, horizons=HORIZONS,
                    conservative: bool = False) -> pd.DataFrame:
    """Event rows with `ret_{h}` (simple return from entry to the close h sessions later); NaN if the window is incomplete."""
    sessions = close.index
    ep = entry_points(events, sessions)
    out = events.copy()
    for h in horizons:
        out[f'ret_{h}'] = np.nan
    out['entry_pos'] = ep['pos']
    out['entry_basis'] = ep['basis']
    cols = {c: i for i, c in enumerate(close.columns)}
    cv, ov = close.to_numpy(), open_.reindex(index=close.index, columns=close.columns).to_numpy()
    for idx, isin, pos, basis in zip(out.index, out['isin'], ep['pos'], ep['basis']):
        j = cols.get(isin)
        if j is None or pd.isna(pos):
            continue
        pos = int(pos)
        if pos >= len(sessions):
            continue
        if conservative and basis == 'open':
            entry = cv[pos, j]
        else:
            entry = ov[pos, j] if basis == 'open' else cv[pos, j]
        if not np.isfinite(entry) or entry <= 0:
            continue
        for h in horizons:
            end = pos + h
            if end < len(sessions) and np.isfinite(cv[end, j]):
                out.at[idx, f'ret_{h}'] = cv[end, j] / entry - 1
    return out


def index_returns(index_close: pd.Series, sessions: pd.DatetimeIndex, entry_pos: pd.Series, entry_basis: pd.Series,
                  horizons=HORIZONS) -> pd.DataFrame:
    """Return of a broad index (Nifty 500 closing values) over the same window as each event: from the entry session's
    close ('close' entries) or the previous session's close ('open' entries, a slight overstatement of the window,
    stated) to the close `h` sessions after the entry session. NaN if the index is missing on either date."""
    ix = index_close.reindex(sessions).to_numpy(dtype=float)
    res = pd.DataFrame(index=entry_pos.index, columns=[f'bm_{h}' for h in horizons], dtype=float)
    for i in entry_pos.index:
        pos = entry_pos.at[i]
        if pd.isna(pos):
            continue
        pos = int(pos)
        start = pos - 1 if entry_basis.at[i] == 'open' else pos
        for h in horizons:
            end = pos + h
            if start >= 0 and end < len(ix) and np.isfinite(ix[start]) and np.isfinite(ix[end]) and ix[start] > 0:
                res.at[i, f'bm_{h}'] = ix[end] / ix[start] - 1
    return res


def excess(df: pd.DataFrame, bm: pd.DataFrame, horizons=HORIZONS) -> pd.DataFrame:
    """Adds `ex_{h}` = stock return minus index return (simple difference of the two holding-period returns)."""
    out = df.copy()
    for h in horizons:
        out[f'ex_{h}'] = out[f'ret_{h}'] - bm[f'bm_{h}']
        out[f'idx_{h}'] = bm[f'bm_{h}']
    return out


def summarise(df: pd.DataFrame, col: str, cluster: str = 'broadcast_date', seed: int = 7, boot: int = 2000,
              level: float = 95.0) -> dict:
    """N, mean, median, hit rate, and a date-clustered bootstrap 95% interval of the mean."""
    d = df.dropna(subset=[col])
    n = len(d)
    if n == 0:
        return {'n': 0}
    out = {'n': int(n), 'clusters': int(d[cluster].nunique()), 'mean': float(d[col].mean()), 'median': float(d[col].median()),
           'hit_rate': float((d[col] > 0).mean()), 'sd': float(d[col].std(ddof=1)) if n > 1 else float('nan')}
    g = d.groupby(cluster)[col].agg(['sum', 'count'])
    if len(g) > 1:
        rng = np.random.default_rng(seed)
        s, c = g['sum'].to_numpy(), g['count'].to_numpy()
        idx = rng.integers(0, len(g), size=(boot, len(g)))
        means = s[idx].sum(axis=1) / c[idx].sum(axis=1)
        tail = (100 - level) / 2
        out['ci95' if level == 95.0 else f'ci{level:g}'] = [float(np.percentile(means, tail)), float(np.percentile(means, 100 - tail))]
    return out


def mde(sd: float, n: int) -> float:
    """Minimum detectable mean at 5% two-sided and 80% power."""
    return float((1.96 + 0.84) * sd / np.sqrt(n)) if n > 0 else float('nan')
