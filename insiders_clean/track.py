"""Track record: what a stock did after each kind of filing was made public.

Built nightly by scripts/precompute_slim.py from the clean tables and the
price layer; the site's Track record page only reads the result.

Rules (docs/SIGNALS.md, "Track record"):
- Clock starts on the day the filing was made public (`broadcast_date`).
  The time of day is not in every filing, so entry is that day's close only
  when it is a session AND the filing is NSE's (published during market hours
  is not guaranteed either way) -- to stay cautious, entry is always the close
  of the first session AFTER the broadcast day.
- Returns from the entry close over 5, 21, 63 and 126 sessions; only complete
  windows count. Excess = stock return minus Nifty 500 over the same sessions.
- One event per company per signal per 21 sessions, so a run of tranches is
  one decision, not twenty.
- Costs: 0.25 percentage points off every return (round trip at a
  zero-brokerage broker: STT, exchange charges, stamp duty, slippage).
- Prices adjusted for splits and bonuses only.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import signals

HORIZONS = {'1W': 5, '1M': 21, '3M': 63, '6M': 126}
COST_PCT = 0.25
SPACING_SESSIONS = 21
MIN_VALUE = 25e5  # Rs 25 lakh: below this a trade is not counted as a decision

SIGNALS = {
    'promoter_buy': 'Promoter open-market buy (₹25 L+)',
    'promoter_buy_near_high': 'Promoter buy within 5% of the 52-week high',
    'promoter_buy_far_below_high': 'Promoter buy 30%+ below the 52-week high',
    'spotlight': 'One person buys 0.15%+ of market cap in 30 days',
    'cluster': '2+ insiders buying within 30 days',
    'officer_buy': 'Director or KMP open-market buy (₹25 L+)',
    'promoter_sell': 'Promoter open-market sale (₹25 L+)',
    'officer_sell': 'Director or KMP open-market sale (₹25 L+)',
    'fund_deal_buy': 'Bulk/block net buy by a real fund (small caps)',
}


def _space(ev: pd.DataFrame, sessions: pd.DatetimeIndex) -> pd.DataFrame:
    """Keep the first event per company, then the next one at least
    SPACING_SESSIONS sessions later."""
    if ev.empty:
        return ev
    ev = ev.sort_values(['isin', 'day']).copy()
    ev['_i'] = sessions.searchsorted(ev['day'].to_numpy())
    keep, last = [], {}
    for idx, isin, i in zip(ev.index, ev['isin'], ev['_i']):
        if isin not in last or i - last[isin] >= SPACING_SESSIONS:
            keep.append(idx)
            last[isin] = i
    return ev.loc[keep].drop(columns='_i')


def events(trades: pd.DataFrame, deals: pd.DataFrame | None, close: pd.DataFrame) -> pd.DataFrame:
    """One row per (signal, company, day made public): isin, day, signal, value."""
    t = signals.eligible(trades)
    t = t.dropna(subset=['isin', 'seen'])
    t['day'] = t['seen'].dt.normalize()
    big = t[(t['value'] >= MIN_VALUE) & ~t['is_token']]
    prom, off = big['person_role'].isin(signals.PROMOTER_ROLES), big['person_role'].isin(['director', 'kmp'])
    out = [big[prom & (big['side'] == 'BUY')].assign(signal='promoter_buy'),
           big[off & (big['side'] == 'BUY')].assign(signal='officer_buy'),
           big[prom & (big['side'] == 'SELL')].assign(signal='promoter_sell'),
           big[off & (big['side'] == 'SELL')].assign(signal='officer_sell')]
    # price context at the day made public: distance from the 52-week high
    pb = out[0]
    if not pb.empty:
        ff = close.ffill()
        hi = close.rolling(250, min_periods=120).max()
        px = [ff[i].asof(d) if i in ff else np.nan for i, d in zip(pb['isin'], pb['day'])]
        h = [hi[i].asof(d) if i in hi else np.nan for i, d in zip(pb['isin'], pb['day'])]
        off_high = pd.Series(px, index=pb.index) / pd.Series(h, index=pb.index) - 1
        out.append(pb[off_high >= -0.05].assign(signal='promoter_buy_near_high'))
        out.append(pb[off_high <= -0.30].assign(signal='promoter_buy_far_below_high'))
    # spotlight and cluster: the first day each was crossed, replayed day by day
    days = sorted(t['day'].unique())
    seen_spot, seen_clus, rows = set(), set(), []
    for d in days:
        end = pd.Timestamp(d) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        today = t[t['day'] == d]
        if today.empty or not (today['side'] == 'BUY').any():
            continue
        sp = signals.spotlight(t[t['seen'] <= end], end)
        for isin in set(sp['isin']) & set(today.loc[today['side'] == 'BUY', 'isin']):
            if (isin, d) not in seen_spot:
                seen_spot.add((isin, d))
                rows.append({'isin': isin, 'day': pd.Timestamp(d), 'signal': 'spotlight'})
        cl = signals.clusters(t[t['seen'] <= end], end)
        if not cl.empty:
            for isin in set(cl.loc[pd.to_datetime(cl['last_seen']).dt.normalize() == d, 'isin']):
                if (isin, d) not in seen_clus:
                    seen_clus.add((isin, d))
                    rows.append({'isin': isin, 'day': pd.Timestamp(d), 'signal': 'cluster'})
    ev = pd.concat([x[['isin', 'day', 'signal', 'value']] for x in out if not x.empty]
                   + ([pd.DataFrame(rows)] if rows else []), ignore_index=True)
    if deals is not None and not deals.empty:
        d = deals.copy()
        d['date'] = pd.to_datetime(d['date'], errors='coerce')
        mm = d['client_is_market_maker'].astype('boolean').fillna(False)
        d = d[~mm & d['is_primary'].astype('boolean').fillna(False)
              & (pd.to_numeric(d['market_cap'], errors='coerce') < signals.SMALL_CAP_MAX_MCAP)]
        net = pd.to_numeric(d['signed_value'], errors='coerce').groupby([d['isin'], d['date']]).sum()
        nb = net[net >= MIN_VALUE].reset_index().rename(columns={'date': 'day', 'signed_value': 'value'})
        ev = pd.concat([ev, nb.assign(signal='fund_deal_buy')], ignore_index=True)
    sessions = close.index
    return pd.concat([_space(g, sessions) for _, g in ev.groupby('signal')], ignore_index=True) if len(ev) else ev


def forward_returns(ev: pd.DataFrame, close: pd.DataFrame, index_close: pd.Series) -> pd.DataFrame:
    """Per event: entry date and price, then for each horizon the stock's
    return, the index's return and the excess, net of costs (percent)."""
    if ev.empty:
        return ev
    sessions = close.index
    idx = index_close.reindex(sessions).ffill()
    out = ev.copy()
    pos = sessions.searchsorted(out['day'].to_numpy(), side='right')  # first session after the day made public
    out['entry_date'] = [sessions[p] if p < len(sessions) else pd.NaT for p in pos]
    entry = [close.at[sessions[p], i] if p < len(sessions) and i in close else np.nan for p, i in zip(pos, out['isin'])]
    out['entry_price'] = entry
    for name, n in HORIZONS.items():
        stock, bench = [], []
        for p, i, e0 in zip(pos, out['isin'], entry):
            q = p + n
            if q >= len(sessions) or i not in close or not np.isfinite(e0) or e0 <= 0:
                stock.append(np.nan)
                bench.append(np.nan)
                continue
            e1 = close.at[sessions[q], i]
            stock.append((e1 / e0 - 1) * 100 if np.isfinite(e1) else np.nan)
            bench.append((idx.iloc[q] / idx.iloc[p] - 1) * 100)
        out[f'ret_{name}'] = np.array(stock) - COST_PCT
        out[f'excess_{name}'] = out[f'ret_{name}'] - np.array(bench)
    return out


def summary(fr: pd.DataFrame) -> pd.DataFrame:
    """Per signal and horizon: cases, median and mean excess, share that beat
    the index, and a rough 90% interval for the mean (overlapping windows and
    same-day clustering make the true interval wider; shown as a guide)."""
    rows = []
    for sig, g in fr.groupby('signal'):
        for name in HORIZONS:
            x = g[f'excess_{name}'].dropna()
            n = len(x)
            se = x.std(ddof=1) / np.sqrt(n) if n > 1 else np.nan
            rows.append({'signal': sig, 'label': SIGNALS.get(sig, sig), 'horizon': name, 'cases': n,
                         'median_excess': x.median() if n else np.nan, 'mean_excess': x.mean() if n else np.nan,
                         'beat_index': (x > 0).mean() * 100 if n else np.nan,
                         'ci_low': x.mean() - 1.645 * se if n > 1 else np.nan,
                         'ci_high': x.mean() + 1.645 * se if n > 1 else np.nan,
                         'median_return': g[f'ret_{name}'].dropna().median() if n else np.nan})
    return pd.DataFrame(rows)
