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
- Size-matched excess as well: large caps against Nifty 100, mid caps Nifty
  Midcap 150, small caps Nifty Smallcap 250, micro caps (and unbucketed) Nifty
  Microcap 250. The size bucket is today's (NSE market-cap rank), not the one
  on the event day: labelled as such.
- Before the filing was public: the stock's move from the last trade date to
  the day made public, and the lag in sessions (insider signals only).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import signals

HORIZONS = {'1W': 5, '1M': 21, '3M': 63, '6M': 126}
COST_PCT = 0.25
SPACING_SESSIONS = 21
MIN_VALUE = 25e5  # Rs 25 lakh: below this a trade is not counted as a decision
SIZE_INDEX = {'Large': 'Nifty 100', 'Mid': 'Nifty Midcap 150', 'Small': 'Nifty Smallcap 250', 'Micro': 'Nifty Microcap 250'}

SIGNALS = {
    'promoter_buy': 'Promoter open-market buy (₹25 L+)',
    'promoter_buy_near_high': 'Promoter buy within 5% of the 52-week high',
    'promoter_buy_far_below_high': 'Promoter buy 30%+ below the 52-week high',
    'spotlight': 'One person buys 0.15%+ of market cap in 30 days',
    'cluster': '2+ decision-makers buying within 30 days',
    'officer_buy': 'Director or KMP open-market buy (₹25 L+)',
    'promoter_sell': 'Promoter open-market sale (₹25 L+)',
    'officer_sell': 'Director or KMP open-market sale (₹25 L+)',
    'window_open_buy': 'Promoter or officer buy in the first 5 sessions after results (₹25 L+)',
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
    if 'window_open_buy' in big:  # the results date is known before the trade, so no look-ahead (insiders_clean/trading_window.py)
        out.append(big[(prom | off) & (big['side'] == 'BUY') & big['window_open_buy'].astype('boolean').fillna(False)]
                   .assign(signal='window_open_buy'))
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
    ev = pd.concat([x[['isin', 'day', 'signal', 'value', 'trade_date_to']] for x in out if not x.empty]
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


def forward_returns(ev: pd.DataFrame, close: pd.DataFrame, index_close: pd.Series,
                    size_index: dict | None = None, bucket: dict | None = None) -> pd.DataFrame:
    """Per event: entry date and price, then for each horizon the stock's
    return, the index's return and the excess, net of costs (percent).
    With `size_index` (index name -> closes) and `bucket` (ISIN -> size
    bucket), also the excess over the size-matched index."""
    if ev.empty:
        return ev
    sessions = close.index
    idx = index_close.reindex(sessions).ffill()
    sized = {k: v.reindex(sessions).ffill() for k, v in (size_index or {}).items()}
    out = ev.copy()
    out['size_bucket'] = out['isin'].map(bucket or {})
    ff = close.ffill()
    if 'trade_date_to' in out:
        td = pd.to_datetime(out['trade_date_to'], errors='coerce')
        p_trade = [ff[i].asof(t) if i in ff and pd.notna(t) and t >= sessions[0] else np.nan for i, t in zip(out['isin'], td)]
        p_public = [ff[i].asof(d) if i in ff else np.nan for i, d in zip(out['isin'], out['day'])]
        out['pre_move'] = (np.array(p_public, dtype=float) / np.array(p_trade, dtype=float) - 1) * 100
        out['lag_sessions'] = [float(sessions.searchsorted(d, side='right') - sessions.searchsorted(t, side='right'))
                               if pd.notna(t) else np.nan for d, t in zip(out['day'], td)]
    pos = sessions.searchsorted(out['day'].to_numpy(), side='right')  # first session after the day made public
    out['entry_date'] = [sessions[p] if p < len(sessions) else pd.NaT for p in pos]
    entry = [close.at[sessions[p], i] if p < len(sessions) and i in close else np.nan for p, i in zip(pos, out['isin'])]
    out['entry_price'] = entry
    for name, n in HORIZONS.items():
        stock, bench, size_b = [], [], []
        for p, i, e0, b in zip(pos, out['isin'], entry, out['size_bucket']):
            q = p + n
            if q >= len(sessions) or i not in close or not np.isfinite(e0) or e0 <= 0:
                stock.append(np.nan)
                bench.append(np.nan)
                size_b.append(np.nan)
                continue
            e1 = close.at[sessions[q], i]
            stock.append((e1 / e0 - 1) * 100 if np.isfinite(e1) else np.nan)
            bench.append((idx.iloc[q] / idx.iloc[p] - 1) * 100)
            s_ix = sized.get(SIZE_INDEX.get(b, SIZE_INDEX['Micro']))
            size_b.append((s_ix.iloc[q] / s_ix.iloc[p] - 1) * 100 if s_ix is not None else np.nan)
        out[f'ret_{name}'] = np.array(stock) - COST_PCT
        out[f'excess_{name}'] = out[f'ret_{name}'] - np.array(bench)
        out[f'excess_sm_{name}'] = out[f'ret_{name}'] - np.array(size_b)
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
                         'median_return': g[f'ret_{name}'].dropna().median() if n else np.nan,
                         'median_excess_sm': g[f'excess_sm_{name}'].dropna().median() if f'excess_sm_{name}' in g and n else np.nan,
                         'beat_size_index': (g[f'excess_sm_{name}'].dropna() > 0).mean() * 100
                         if f'excess_sm_{name}' in g and g[f'excess_sm_{name}'].notna().any() else np.nan,
                         'median_pre_move': g['pre_move'].dropna().median() if 'pre_move' in g and g['pre_move'].notna().any() else np.nan,
                         'median_lag': g['lag_sessions'].dropna().median() if 'lag_sessions' in g and g['lag_sessions'].notna().any() else np.nan})
    return pd.DataFrame(rows)


# --- Forward record (docs/TODO.md item 26) ----------------------------------
# The backtest above is re-measured every night on the whole history, so a
# rule change rewrites the past. The forward record does not: each run appends
# the events that fired since the last run to a new write-once file in R2
# (`ledger/forward/<run time>.parquet`), stamped with the run time and the rule
# version, and never edits a row. Outcomes are derived from those rows later,
# by the same forward_returns as the backtest.

RULES_VERSION = '2026-10-12.3'  # bump when a signal rule, threshold, spacing or cost changes
# .2: window_open_buy added. .3: clusters count a company's promoter group once (shareholding pattern).
LEDGER_PREFIX = 'ledger/forward/'
FIRE_WINDOW = 5  # sessions: an event made public this recently counts as firing now (covers missed runs)
LEDGER_COLS = ['signal', 'isin', 'day', 'value', 'recorded_at', 'rules_version', 'last_session', 'close_at_record']


def new_ledger_rows(ev: pd.DataFrame, ledger: pd.DataFrame, close: pd.DataFrame, run_at: pd.Timestamp) -> pd.DataFrame:
    """Events made public in the last FIRE_WINDOW sessions and not yet in the
    ledger (keyed on signal, ISIN and day made public). `close_at_record` is
    the latest close known at this run (adjusted as of this run)."""
    if ev.empty or close.empty:
        return pd.DataFrame(columns=LEDGER_COLS)
    sessions = close.index
    since = sessions[max(0, len(sessions) - FIRE_WINDOW)]
    fresh = ev[pd.to_datetime(ev['day']) >= since].copy()
    if not ledger.empty and len(fresh):
        seen = set(zip(ledger['signal'], ledger['isin'], pd.to_datetime(ledger['day'])))
        fresh = fresh[[k not in seen for k in zip(fresh['signal'], fresh['isin'], pd.to_datetime(fresh['day']))]]
    last = close.ffill().iloc[-1]
    fresh['recorded_at'] = run_at
    fresh['rules_version'] = RULES_VERSION
    fresh['last_session'] = sessions[-1]
    fresh['close_at_record'] = [float(last[i]) if i in last.index and pd.notna(last[i]) else np.nan for i in fresh['isin']]
    if 'value' not in fresh:
        fresh['value'] = np.nan
    return fresh[LEDGER_COLS].reset_index(drop=True)


# --- Tradability on the event day ------------------------------------------
# The research says leave out stocks a reader could not trade freely. Judged
# from the bhavcopy as it stood on the day made public, so no look-ahead:
# trade-for-trade or SME series that day, and locked days in the 20 sessions
# up to it (one price all day with a move of LOCK_MIN_MOVE% or more: NSE's
# narrowest band is 2%, so such a day is a band lock). Today's surveillance
# lists are not used here: their history starts on 12 Oct 2026.
T2T_SERIES, SME_SERIES = ('BE', 'BZ', 'ST'), ('SM', 'ST', 'SZ')
LOCK_WINDOW, LOCK_MIN_MOVE = 20, 1.9


def restrictions(ev: pd.DataFrame, px: pd.DataFrame | None) -> pd.DataFrame:
    """Adds `restriction` (plain words, '' when none) and `restricted` per
    event from NSE price rows (date, isin, series, open, high, low, close,
    prev_close, volume)."""
    out = ev.copy()
    out['restriction'] = ''
    if out.empty or px is None or px.empty:
        out['restricted'] = False
        return out
    p = px[['date', 'isin', 'series', 'open', 'high', 'low', 'close', 'prev_close', 'volume']].dropna(subset=['isin', 'date']).copy()
    p['date'] = pd.to_datetime(p['date'])
    move = (p['close'] / p['prev_close'].where(p['prev_close'] > 0) - 1).abs() * 100
    p['locked'] = ((p['open'] == p['high']) & (p['high'] == p['low']) & (p['low'] == p['close'])
                   & (p['volume'] > 0) & (move >= LOCK_MIN_MOVE)).fillna(False)
    by = {i: g.sort_values('date') for i, g in p.groupby('isin', sort=False)}
    why = []
    for i, day in zip(out['isin'], pd.to_datetime(out['day'])):
        g = by.get(i)
        upto = g[g['date'] <= day] if g is not None else None
        if upto is None or upto.empty:
            why.append('')
            continue
        series, w = str(upto['series'].iloc[-1]), []
        if series in T2T_SERIES:
            w.append('trade for trade')
        if series in SME_SERIES:
            w.append('SME')
        n = int(upto['locked'].tail(LOCK_WINDOW).sum())
        if n:
            w.append(f'{n} locked day{"s" if n > 1 else ""} in {LOCK_WINDOW}')
        why.append(', '.join(w))
    out['restriction'] = why
    out['restricted'] = out['restriction'] != ''
    return out
