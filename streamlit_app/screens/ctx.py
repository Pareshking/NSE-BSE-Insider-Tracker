"""Everything a page needs: the clean tables, the eligible insider trades and
the 'as of' date (the latest filing in the data, never the wall clock). Built
once per 10 minutes and shared by every visitor and page run, not copied per
run (copies per run put the site over its memory limit): pages copy a frame
before changing it."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import streamlit as st
from data import store

from insiders_clean import signals
from insiders_clean.bse_events import with_bse


@dataclass
class Ctx:
    trades: pd.DataFrame        # all clean insider filings
    eligible: pd.DataFrame      # open-market, primary, not held back
    deals: pd.DataFrame
    securities: pd.DataFrame
    sast: pd.DataFrame          # NSE's, plus BSE rows NSE has not got (listed_on 'bse')
    actions: pd.DataFrame
    meetings: pd.DataFrame
    shareholding: pd.DataFrame
    preferential: pd.DataFrame  # NSE preferential issue records, both stages, linked where certain
    rights: pd.DataFrame
    prices: pd.DataFrame        # per ISIN: latest_close, high_52w, pct_off_high, last_date
    ref: pd.Timestamp | None
    latest: dict
    marks: dict | None = None   # ISIN -> [(day made public, side)], for the sparklines
    results: pd.DataFrame | None = None   # NSE results (columns the cards use), for the size against the last full year


def _display_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Columns only the pages use: value in crores, exchange in capitals."""
    if df.empty:
        return df
    df = df.copy()
    if 'value' in df:
        df['value_cr'] = pd.to_numeric(df['value'], errors='coerce') / 1e7
    if 'listed_on' in df:
        df['listed_on'] = df['listed_on'].astype(str).str.upper()
    return df


def load() -> Ctx:
    return _shared()


@st.cache_resource(ttl=600, show_spinner=False, max_entries=1)
def _shared() -> Ctx:
    trades = _display_columns(store.table('insider_trades'))
    elig = signals.eligible(trades) if not trades.empty else trades
    deals = _display_columns(store.table('deals'))
    if not deals.empty:
        deals['date'] = pd.to_datetime(deals['date'], errors='coerce')
    return Ctx(trades=trades, eligible=elig, deals=deals, securities=store.table('securities'),
               sast=with_bse(store.table('sast'), store.table('bse_sast')),
               actions=with_bse(store.table('actions'), store.table('bse_actions')), meetings=store.table('meetings'),
               shareholding=store.table('shareholding'), preferential=store.table('preferential'),
               rights=store.table('rights'), prices=store.prices(), ref=signals.as_of(trades), latest=store.latest(),
               marks=_marks(elig), results=store.table('results'))


def need_data(ctx: Ctx) -> bool:
    """Draws the explanation and returns False when there's nothing to show."""
    if ctx.trades.empty:
        from ui import kit
        kit.note('No clean data yet.',
                 'The nightly cleaning step writes clean/current/ in R2; this page fills in after its first run.'
                 if store.configured() else
                 'R2 credentials are not configured for this app (see .streamlit/secrets.toml.example).')
        return False
    return True


PRICE_COLS = ['latest_close', 'low_52w', 'high_52w', 'pct_off_high', 'mcap_bucket']


def with_prices(df: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """Adds the latest close and 52-week range by ISIN (blank where the stock
    has no price in our NSE/BSE files)."""
    if df.empty or prices.empty or 'isin' not in df:
        return df.assign(**{c: None for c in PRICE_COLS})
    p = prices.drop_duplicates('isin').set_index('isin')
    return df.assign(**{c: df['isin'].map(p[c]) if c in p else None for c in PRICE_COLS})


def pre_public_move(df: pd.DataFrame) -> pd.Series:
    """Per filing, the stock's move (%) from the last trade date to the day it
    was made public, on split-adjusted closes (artifacts/price_history.parquet,
    the last ~400 days): what the market had already done before a reader
    could know. Blank where either close is missing."""
    hist = store.price_history()
    out = pd.Series(np.nan, index=df.index)
    if df.empty or not hist:
        return out
    to = pd.to_datetime(df['trade_date_to'], errors='coerce').to_numpy()
    seen = pd.to_datetime(df['broadcast_date'], errors='coerce').dt.normalize().to_numpy()
    for k, (i, a, b) in enumerate(zip(df['isin'], to, seen)):
        h = hist.get(i)
        if h is None or pd.isna(a) or pd.isna(b) or b < a:
            continue
        d, c = h
        ia, ib = np.searchsorted(d, a, side='right') - 1, np.searchsorted(d, b, side='right') - 1
        if ia >= 0 and ib >= 0 and c[ia] > 0:
            out.iloc[k] = (c[ib] / c[ia] - 1) * 100
    return out


def split_since(df: pd.DataFrame, prices: pd.DataFrame, date_col='trade_date_to') -> pd.Series:
    """Per row, the split/bonus factor that puts a price of `date_col`'s day
    (a trade, an allotment, a buyback offer) on the basis of today's adjusted
    close (price x factor; shares / factor): 1 when none came after that day,
    the factor when one did, blank when more than one may have (the summary
    keeps only the last) or the date is unreadable. `date_col` may be a list:
    the first readable date per row is used."""
    one = pd.Series(1.0, index=df.index)
    if df.empty or prices.empty or 'last_split_date' not in prices or 'isin' not in df:
        return one
    p = prices.drop_duplicates('isin').set_index('isin')
    when = pd.Series(pd.NaT, index=df.index)
    for c in [date_col] if isinstance(date_col, str) else date_col:
        if c in df:
            when = when.fillna(pd.to_datetime(df[c], errors='coerce'))
    split = pd.to_datetime(df['isin'].map(p['last_split_date']), errors='coerce')
    n = pd.to_numeric(df['isin'].map(p['n_splits']), errors='coerce').fillna(0)
    f = pd.to_numeric(df['isin'].map(p['last_split_factor']), errors='coerce')
    after = split.notna() & (when.isna() | (when < split))
    return one.where(~after, f).where(~(after & (when.isna() | (n > 1))))


def with_flags(df: pd.DataFrame) -> pd.DataFrame:
    """Adds today's tradability flags by ISIN (NSE surveillance stage, trade for trade, SME, tight band,
    circuit-locked days), drawn as amber badges under the company name. Flags, never a filter."""
    return signals.with_tradability(df, store.table('tradability'))


def _marks(eligible: pd.DataFrame) -> dict:
    """ISIN -> [(day made public, side)] for open-market insider trades."""
    if eligible.empty:
        return {}
    e = eligible.dropna(subset=['isin', 'seen'])
    return {i: list(zip(g['seen'], g['side'])) for i, g in e.groupby('isin', sort=False)}


def with_sparks(df: pd.DataFrame, ctx: Ctx) -> pd.DataFrame:
    """Adds `_spark` (the year's price line, insider trades marked) and
    `_chg_1y` by ISIN."""
    from ui import kit
    if df.empty or 'isin' not in df:
        return df
    hist, marks = store.price_history(), ctx.marks if ctx.marks is not None else _marks(ctx.eligible)
    drawn = [kit.spark(*hist[i], marks.get(i, ())) if isinstance(i, str) and i in hist else (None, None)
             for i in df['isin']]
    return df.assign(_spark=[s for s, _ in drawn], _chg_1y=[c for _, c in drawn])
