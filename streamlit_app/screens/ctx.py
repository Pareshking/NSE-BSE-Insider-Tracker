"""Everything a page needs, loaded once per run: the clean tables, the
eligible insider trades and the 'as of' date (the latest filing in the data,
never the wall clock)."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import streamlit as st
from data import store

from insiders_clean import signals


@dataclass
class Ctx:
    trades: pd.DataFrame        # all clean insider filings
    eligible: pd.DataFrame      # open-market, primary, not held back
    deals: pd.DataFrame
    securities: pd.DataFrame
    sast: pd.DataFrame
    actions: pd.DataFrame
    meetings: pd.DataFrame
    shareholding: pd.DataFrame
    prices: pd.DataFrame        # per ISIN: latest_close, high_52w, pct_off_high, last_date
    ref: pd.Timestamp | None
    latest: dict


@st.cache_data(ttl=600, show_spinner=False)
def _eligible(trades: pd.DataFrame) -> pd.DataFrame:
    return signals.eligible(trades) if not trades.empty else trades


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
    trades = _display_columns(store.table('insider_trades'))
    elig = _eligible(trades)
    deals = _display_columns(store.table('deals'))
    if not deals.empty:
        deals['date'] = pd.to_datetime(deals['date'], errors='coerce')
    return Ctx(trades=trades, eligible=elig, deals=deals, securities=store.table('securities'),
               sast=store.table('sast'), actions=store.table('actions'), meetings=store.table('meetings'),
               shareholding=store.table('shareholding'), prices=store.prices(), ref=signals.as_of(trades), latest=store.latest())


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
    if df.empty:
        return df
    if prices.empty or 'isin' not in df:
        return df.assign(**{c: None for c in PRICE_COLS})
    p = prices.drop_duplicates('isin').set_index('isin')
    return df.assign(**{c: df['isin'].map(p[c]) if c in p else None for c in PRICE_COLS})


@st.cache_data(ttl=600, show_spinner=False)
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
    hist, marks = store.price_history(), _marks(ctx.eligible)
    drawn = [kit.spark(*hist[i], marks.get(i, ())) if isinstance(i, str) and i in hist else (None, None)
             for i in df['isin']]
    return df.assign(_spark=[s for s, _ in drawn], _chg_1y=[c for _, c in drawn])
