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
               shareholding=store.table('shareholding'), ref=signals.as_of(trades), latest=store.latest())


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
