"""Event-study core for the pre-registered hypotheses (docs/RESEARCH.md).

Pure functions on frames, no I/O. Conventions (fixed before any outcome was looked at):
- Signal time is the disclosure's dissemination (`broadcast_ts`; day-level `broadcast_date` if no time).
- Entry: same-session close when the disclosure came before 14:00 IST; otherwise the next session's open.
  Conservative variant: the next session's close. Never the transaction date or the insider's own price.
- Outcome = close `h` sessions after the entry session, on a price series adjusted for structural capital actions
  (splits, bonuses; see adjust.py). Cash dividends are not adjusted, so these are price returns. Outcome windows may
  contain later splits: that is realised information about the outcome, not a feature at signal time.
- Benchmarks (all reported): the equal-weighted average of every traded security (market proxy built from our own
  price table; a broad index series is a later addition), and the equal-weighted average of securities in the same size
  bucket. Only complete windows count.
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


def benchmark_returns(close: pd.DataFrame, entry_pos: pd.Series, entry_basis: pd.Series, horizons=HORIZONS,
                      groups: pd.Series | None = None, event_groups: pd.Series | None = None) -> pd.DataFrame:
    """Equal-weighted peer return over the same window as each event (close-to-close from the entry session;
    for 'open' entries the benchmark starts at the previous close, a slight overstatement of the benchmark window, stated).
    `groups` maps ISIN -> bucket; when given with `event_groups`, peers are the same bucket."""
    daily = close.pct_change(fill_method=None)
    daily = daily.clip(-0.5, 0.5)
    cum_cache = {}
    res = pd.DataFrame(index=entry_pos.index, columns=[f'bm_{h}' for h in horizons], dtype=float)
    for key in ([None] if groups is None else sorted(set(event_groups.dropna()))):
        cols = close.columns if key is None else [c for c in close.columns if groups.get(c) == key]
        if len(cols) == 0:
            continue
        mkt = daily[cols].mean(axis=1, skipna=True).fillna(0.0)
        lg = np.log1p(mkt).cumsum().to_numpy()
        cum_cache[key] = lg
        rows = entry_pos.index if key is None else event_groups.index[event_groups == key]
        for i in rows:
            pos = entry_pos.at[i]
            if pd.isna(pos):
                continue
            pos = int(pos)
            start = pos - 1 if entry_basis.at[i] == 'open' else pos
            for h in horizons:
                end = pos + h
                if start >= 0 and end < len(lg):
                    res.at[i, f'bm_{h}'] = np.expm1(lg[end] - lg[start])
    return res


def abnormal(df: pd.DataFrame, bm: pd.DataFrame, horizons=HORIZONS) -> pd.DataFrame:
    out = df.copy()
    for h in horizons:
        out[f'ar_{h}'] = out[f'ret_{h}'] - bm[f'bm_{h}']
    return out


def summarise(df: pd.DataFrame, col: str, cluster: str = 'broadcast_date', seed: int = 7, boot: int = 2000) -> dict:
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
        out['ci95'] = [float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))]
    return out


def mde(sd: float, n: int) -> float:
    """Minimum detectable mean at 5% two-sided and 80% power."""
    return float((1.96 + 0.84) * sd / np.sqrt(n)) if n > 0 else float('nan')


def size_buckets(mcap: pd.DataFrame, prices: pd.DataFrame, asof: str = '2025-12-31') -> pd.Series:
    """ISIN -> micro/small/mid/large from NSE market cap on the last day on or before `asof` (before the product
    window, so no look-ahead). AMFI-style ranks: top 100 large, 101-250 mid, 251-500 small, the rest micro.
    Indicative only (owner: market cap is a rough size filter). ISINs with no NSE market cap are left out."""
    m = mcap[(mcap['category'] == 'Listed') & (mcap['date'] <= pd.Timestamp(asof))]
    if m.empty:
        return pd.Series(dtype=object)
    m = m[m['date'] == m['date'].max()]
    ids = prices.loc[prices['exchange'] == 'NSE', ['symbol', 'isin']].drop_duplicates('symbol')
    m = m.merge(ids, on='symbol', how='inner').dropna(subset=['market_cap'])
    m = m.sort_values('market_cap', ascending=False).drop_duplicates('isin')
    rank = np.arange(1, len(m) + 1)
    bucket = np.select([rank <= 100, rank <= 250, rank <= 500], ['large', 'mid', 'small'], 'micro')
    return pd.Series(bucket, index=m['isin'].to_numpy())
