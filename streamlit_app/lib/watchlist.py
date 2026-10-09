"""Private watchlist: symbols or ISINs from `st.secrets["watchlist"]` (kept out of the public repo) plus an optional list
pasted for the current session. Nothing is written anywhere: the session list lives in `st.session_state` only and is gone when the
tab closes, so there is no personal data to leak. To keep a list between visits put it in the app's secrets:
    watchlist = ["RELIANCE", "INE002A01018"]"""
from __future__ import annotations

import re

import pandas as pd
import streamlit as st

SESSION_KEY, ONLY_KEY = "watchlist_session", "watchlist_only"


def parse(text) -> list[str]:
    """Split pasted text on commas, spaces and newlines; upper-case; drop empties and duplicates, keep order."""
    out: list[str] = []
    for tok in re.split(r"[\s,;]+", str(text or "")):
        tok = tok.strip().upper()
        if tok and tok not in out:
            out.append(tok)
    return out


def _from_secrets() -> list[str]:
    try:
        raw = st.secrets.get("watchlist", [])
    except Exception:  # noqa: BLE001 -- no secrets file at all is the normal local case
        return []
    return parse(" ".join(raw)) if isinstance(raw, (list, tuple)) else parse(raw)


def get() -> set[str]:
    return set(_from_secrets()) | set(st.session_state.get(SESSION_KEY, []))


def editor() -> None:
    """The paste box (session only) and a note on keeping a list in secrets."""
    pasted = st.text_area("Watchlist: symbols or ISINs (this session only, not saved)", value=" ".join(st.session_state.get(SESSION_KEY, [])),
                          key="watchlist_text", height=70, placeholder="RELIANCE, INE002A01018, ...",
                          help="Not saved anywhere. To keep a list between visits, add watchlist = [...] to the app's secrets (never to the repo).")
    st.session_state[SESSION_KEY] = parse(pasted)


def toggle(label: str = "My watchlist only") -> bool:
    only = st.checkbox(label, key=ONLY_KEY, help=f"{len(get())} symbols or ISINs tracked (secrets plus this session's paste box)")
    if only and not get():
        st.caption("Watchlist is empty: open Watchlist and paste symbols or ISINs.")
    return only


def controls(label: str = "My watchlist only") -> bool:
    """Popover editor plus toggle, in the current container."""
    with st.popover("Watchlist"):
        editor()
    return toggle(label)


def mask(df: pd.DataFrame, wl: set[str], isin_col: str | None, symbol_col: str | None) -> pd.Series:
    """True for rows whose ISIN or symbol is on the watchlist (case-insensitive); all False when neither column exists."""
    m = pd.Series(False, index=df.index)
    for col in (isin_col, symbol_col):
        if col and col in df.columns:
            m |= df[col].astype(str).str.strip().str.upper().isin(wl)
    return m


def limit(df: pd.DataFrame, wl: set[str], isin_col: str | None, symbol_col: str | None) -> pd.DataFrame:
    return df[mask(df, wl, isin_col, symbol_col)] if len(df) else df
