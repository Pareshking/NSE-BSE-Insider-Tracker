"""The short lists behind the Actions page: who is buying, who is selling,
which promoters have pledged a lot. Each reuses the signal rules in
insiders_clean/signals.py and returns at most `limit` rows, strongest first."""
from __future__ import annotations

import pandas as pd

from . import signals

DAYS = 30
MIN_SELL_VALUE = 25e5   # Rs 25 lakh, the same floor the track record uses


def buying(t: pd.DataFrame, ref: pd.Timestamp, roles: tuple[str, ...], limit: int = 8) -> pd.DataFrame:
    """Open-market buyers (token buys left out) in the last 30 days, by % of market cap bought."""
    if t is None or t.empty or ref is None:
        return pd.DataFrame()
    w = signals.person_windows(t, ref)
    w = w[w['person_role'].isin(roles) & (w['value_30d'] > 0)]
    return w.sort_values('pct_30d', ascending=False).head(limit).reset_index(drop=True)


def selling(t: pd.DataFrame, ref: pd.Timestamp, roles: tuple[str, ...], days: int = DAYS, limit: int = 8) -> pd.DataFrame:
    """Open-market sellers in the last `days` days (sales of Rs 25 lakh or more), by % of market cap sold."""
    if t is None or t.empty or ref is None:
        return pd.DataFrame()
    s = t[(t['side'] == 'SELL') & t['person_role'].isin(roles) & (t['seen'] <= ref)
          & (t['seen'] > ref - pd.Timedelta(days=days))].dropna(subset=['isin'])
    if s.empty:
        return pd.DataFrame()
    out = s.groupby(['isin', 'person_id'], as_index=False).agg(
        person_name=('person_name', 'last'), person_role=('person_role', 'last'), company=('company', 'last'),
        nse_symbol=('nse_symbol', 'last'), value=('value', 'sum'), pct_of_mcap=('pct_of_mcap', 'sum'),
        trades=('value', 'size'), last_seen=('seen', 'max'))
    out = out[out['value'] >= MIN_SELL_VALUE]
    return out.sort_values('pct_of_mcap', ascending=False).head(limit).reset_index(drop=True)


def pledged(shareholding: pd.DataFrame | None, securities: pd.DataFrame | None,
            threshold: float = signals.HIGH_PLEDGE_PCT, limit: int = 8) -> pd.DataFrame:
    """Promoters who have pledged more than `threshold` % of their shares, from each company's
    latest filing. A quarter whose pledge file is not parsed yet (carried forward) is left out."""
    s = signals.latest_shareholding(shareholding)
    if s.empty:
        return pd.DataFrame()
    stale = (s['shareholding_stale'].astype('boolean').fillna(False) if 'shareholding_stale' in s
             else pd.Series(False, index=s.index))
    s = s[(s['promoter_pledge_pct'] > threshold) & ~stale]
    if s.empty:
        return pd.DataFrame()
    if securities is not None and not securities.empty:
        meta = securities.drop_duplicates('isin').set_index('isin')
        for col in ('company', 'nse_symbol'):
            if col in meta:
                s[col] = s['isin'].map(meta[col])
    if 'nse_symbol' not in s or s['nse_symbol'].isna().all():
        s['nse_symbol'] = s['symbol']
    if 'company' not in s or s['company'].isna().all():
        s['company'] = s['symbol']
    return s.sort_values('promoter_pledge_pct', ascending=False).head(limit).reset_index(drop=True)
