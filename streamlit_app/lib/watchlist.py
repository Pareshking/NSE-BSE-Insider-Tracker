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


def controls(label: str = "Show my watchlist only") -> bool:
    """Draw the paste box and the toggle; return True when the page should be limited to the watchlist."""
    with st.expander("My watchlist", expanded=False):
        pasted = st.text_area("Symbols or ISINs (this session only, not saved)", value=" ".join(st.session_state.get(SESSION_KEY, [])),
                              key="watchlist_text", height=70, placeholder="RELIANCE, INE002A01018, ...")
        st.session_state[SESSION_KEY] = parse(pasted)
        n_secret = len(_from_secrets())
        st.caption(f"{n_secret} from the app's private secrets, {len(st.session_state[SESSION_KEY])} pasted. "
                   "To keep a list between visits, add `watchlist = [...]` to the app's secrets (never to the repo).")
    only = st.checkbox(label, key=ONLY_KEY)
    if only and not get():
        st.info("Your watchlist is empty. Paste symbols or ISINs above, or add them to the app's secrets.")
    return only


def mask(df: pd.DataFrame, wl: set[str], isin_col: str | None, symbol_col: str | None) -> pd.Series:
    """True for rows whose ISIN or symbol is on the watchlist (case-insensitive); all False when neither column exists."""
    m = pd.Series(False, index=df.index)
    for col in (isin_col, symbol_col):
        if col and col in df.columns:
            m |= df[col].astype(str).str.strip().str.upper().isin(wl)
    return m


def limit(df: pd.DataFrame, wl: set[str], isin_col: str | None, symbol_col: str | None) -> pd.DataFrame:
    return df[mask(df, wl, isin_col, symbol_col)] if len(df) else df
