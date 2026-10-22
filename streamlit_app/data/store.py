"""Reads the clean tables. In production from R2 (clean/current/*.parquet,
written nightly by scripts/clean_writer.py and the NSE events collector);
for local work from a folder named by INSIDERS_LOCAL_DATA that has the same
layout (clean/current/..., clean/latest.json)."""
from __future__ import annotations

import io
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import streamlit as st
from lib import r2_data

# Arrow's bundled allocator (jemalloc on Linux, mimalloc on Windows) keeps the memory a parquet was decoded
# into after the frame is built; the system allocator hands it back. Reading four of the site's tables
# left the process at 283 MB with the bundled one and 128 MB with this (22 Oct). Nothing read changes.
pa.set_memory_pool(pa.system_memory_pool())

TABLES = ('insider_trades', 'deals', 'securities', 'sast', 'actions', 'meetings', 'shareholding', 'preferential', 'rights', 'tradability',
          'buybacks', 'bse_sast', 'bse_actions')
TABLES += ('preferential_allottees', 'preferential_lockins', 'qip', 'qip_allottees')   # insiders_clean/issues.py
TABLES += ('promoter_group',)   # members of each promoter group, from the shareholding XBRL
TABLES += ('results',)   # NSE results from the XBRL (insiders_clean/results.py): the last full year behind a card's size
TABLES += ('universe',)   # companies of Rs 100 Cr and up (insiders_clean/universe.py): every other table is cut to it
TABLES += ('announcement_reads', 'announcement_reads_history')   # filings read by scripts/announcement_reader.py, values checked; the history is reads older than 60 days


def _local() -> Path | None:
    """INSIDERS_LOCAL_DATA, or `streamlit run app.py -- --local-data PATH`."""
    p = os.environ.get('INSIDERS_LOCAL_DATA')
    if not p and '--local-data' in sys.argv[:-1]:
        p = sys.argv[sys.argv.index('--local-data') + 1]
    return Path(p) if p else None


def _read(key: str) -> bytes | None:
    local = _local()
    if local is not None:
        f = local / key
        return f.read_bytes() if f.exists() else None
    if not r2_data.r2_configured():
        return None
    with _LOCK:
        hit = _FETCHED.pop(key, None)
        if hit is not None and hit[1] > 1:
            _FETCHED[key] = [hit[0], hit[1] - 1, hit[2]]
    if hit is not None and time.monotonic() - hit[2] <= FETCHED_TTL:
        return hit[0]
    return r2_data._get_bytes(r2_data.get_client(), key)


# The objects a first visit reads, fetched from R2 side by side instead of one after another: each GET
# is about 0.4 s from the site, and a cold Today read 17 of them in turn (6.6 of its 15 s, 22 Oct). The
# bytes wait here until a reader parses them (once; twice for securities, which the model basket also
# reads whole), then are dropped; leftovers go at the next prefetch or after FETCHED_TTL.
PREFETCH = tuple(f'clean/current/{t}.parquet' for t in (
    'universe', 'insider_trades', 'deals', 'securities', 'sast', 'bse_sast', 'actions', 'bse_actions', 'meetings',
    'shareholding', 'preferential', 'rights', 'results', 'buybacks', 'tradability', 'qip', 'promoter_group',
    'preferential_lockins', 'preferential_allottees', 'qip_allottees')) + tuple(f'artifacts/{a}' for a in (
        'prices_summary_slim.parquet', 'price_history.parquet', 'market_strip.json', 'track_summary.parquet',
        'track_events.parquet', 'forward_outcomes.parquet', 'basket_positions.parquet', 'basket_nav.parquet')) + (
    'clean/latest.json',)
READS = {'clean/current/securities.parquet': 2}
FETCHED_TTL = 300
_FETCHED: dict[str, list] = {}   # key -> [bytes, reads left, fetched at]
_LOCK = threading.Lock()


def prefetch(keys=PREFETCH, workers: int = 30) -> int:
    """Fetch `keys` from R2 in parallel into the read-once buffer `_read` takes them from. A key that fails
    is left out (its reader fetches it again and reports the error as before). Returns how many arrived.
    Nothing to do for a local folder."""
    if _local() is not None or not r2_data.r2_configured():
        return 0
    client = r2_data.get_client()

    def get(key):
        try:
            return key, r2_data._get_bytes(client, key)
        except Exception:  # noqa: BLE001 -- the reader fetches it again and shows the error
            return key, None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        got = [(k, b) for k, b in pool.map(get, keys) if b is not None]
    now = time.monotonic()
    with _LOCK:
        _FETCHED.clear()
        _FETCHED.update({k: [b, READS.get(k, 1), now] for k, b in got})
    return len(got)


def configured() -> bool:
    return _local() is not None or r2_data.r2_configured()


# Kept in R2 for the clean layer and audits; no page reads them, and as Python strings they were a large
# share of the site's memory (meetings' raw_json alone 22 MB of 35): scripts/site_memory_report.py.
UNUSED = ('raw_json', 'xbrl_json', 'xbrl_url', 'xbrl_sha256')
# ...except the filing's XBRL link on the issue tables (a few thousand rows): the Filings page links each issue to it.
LINKS = {('preferential', 'xbrl_url'), ('rights', 'xbrl_url'), ('qip', 'xbrl_url')}
ONLY = {'results': ('isin', 'period_end', 'consolidated', 'ytd_revenue', 'ytd_total_income', 'ytd_profit', 'broadcast_at'),
        'promoter_group': ('isin', 'symbol', 'quarter_end', 'member_name', 'sub_category', 'shares', 'pct_of_company',
                           'pledged_shares')}   # the company page's card; the whole table was 76 MB in memory

# Rows pages never read: the company page shows each company's promoter group at its latest quarter only
# (screens/company.py), so older quarters are not kept. A company whose quarters are all blank keeps its
# rows, so the page reads exactly what it read before.
LATEST = {'promoter_group': ('symbol', 'quarter_end')}

FRESH = ('announcement_reads',)   # rewritten through the day as filings are read: kept for 3 minutes, not 10


def table(name: str) -> pd.DataFrame:
    return _fresh_table(name) if name in FRESH else _table(name)


@st.cache_resource(ttl=600, show_spinner=False)
def universe_isins() -> frozenset | None:
    """ISINs of companies of Rs 100 Cr and up (clean/current/universe.parquet,
    written by the clean step from insiders_clean/universe.py); None until it exists."""
    u = _parquet('universe', cut=False)
    return frozenset(u.loc[u['in_universe'].astype(bool), 'isin'].dropna()) if not u.empty and 'in_universe' in u else None


@st.cache_data(ttl=600, show_spinner=False)
def names() -> pd.DataFrame:
    """ISIN, display name and NSE symbol of every security, not cut to the universe: only for the model
    basket, a fixed-rule paper portfolio whose rows must add up to its return even when a holding has
    since fallen under Rs 100 Cr."""
    df = _parquet('securities', cut=False)
    cols = [c for c in ('isin', 'display_name', 'name', 'nse_symbol') if c in df]
    return df[cols].drop_duplicates('isin') if 'isin' in df else pd.DataFrame()


def _parquet(name: str, cut: bool = True) -> pd.DataFrame:
    """A clean table with the columns pages use, cut to the study universe: a
    company under Rs 100 Cr (or a row with no ISIN) never reaches a page, nor
    the site's memory. Tables without an ISIN column are left whole."""
    body = _read(f'clean/current/{name}.parquet')
    if not body:
        return pd.DataFrame()
    names = [c for c in pq.read_schema(io.BytesIO(body)).names if not c.startswith('__index_level_')]
    keep = [c for c in names if (c not in UNUSED or (name, c) in LINKS) and (name not in ONLY or c in ONLY[name])]
    df = pd.read_parquet(io.BytesIO(body), columns=keep)
    uni = universe_isins() if cut and name != 'universe' and 'isin' in df else None
    df = df[df['isin'].isin(uni)].reset_index(drop=True) if uni is not None else df
    return _latest_only(df, *LATEST[name]) if name in LATEST else df


def _latest_only(df: pd.DataFrame, by: str, when: str) -> pd.DataFrame:
    """The rows at each `by`'s latest `when` (`by` compared as the page compares it: as text, in capitals)."""
    if df.empty or by not in df or when not in df:
        return df
    try:
        last = df[when].groupby(df[by].astype(str).str.upper()).transform('max')
    except TypeError:   # dates that do not order (text mixed with blanks): kept whole, as before
        return df
    return df[df[when].eq(last) | last.isna()]


# Shared, not copied: st.cache_data keeps a pickled copy of each table and unpickles a fresh one on every
# call (the whole 156k-row promoter_group on each Company page, 22 Oct). Callers never change a table in
# place (screens/ctx.py: pages copy a frame before changing it; tests/test_ui_pages.py checks it).
@st.cache_resource(ttl=600, show_spinner=False, max_entries=len(TABLES))
def _table(name: str) -> pd.DataFrame:
    return _parquet(name)


@st.cache_data(ttl=180, show_spinner=False, max_entries=len(FRESH))
def _fresh_table(name: str) -> pd.DataFrame:
    return _parquet(name)


@st.cache_resource(ttl=600, show_spinner=False)
def prices() -> pd.DataFrame:
    """One row per ISIN: latest close, 52-week high/low (split and bonus
    adjusted), rewritten after each nightly run by scripts/precompute_slim.py."""
    body = _read('artifacts/prices_summary_slim.parquet')
    return pd.read_parquet(io.BytesIO(body)) if body else pd.DataFrame()


@st.cache_resource(ttl=1800, show_spinner=False)
def price_history() -> dict:
    """ISIN -> (dates, closes) for the stocks in our filings, last ~400 days,
    split and bonus adjusted (artifacts/price_history.parquet). Shared by every
    page run, not unpickled per call; the arrays are read-only."""
    body = _read('artifacts/price_history.parquet')
    if not body:
        return {}
    h = pd.read_parquet(io.BytesIO(body))
    h['isin'] = h['isin'].astype('category')   # one string per stock, not per row: was 41 MB of the 49
    h['date'] = pd.to_datetime(h['date'])
    out = {}
    for i, g in h.groupby('isin', sort=False, observed=True):
        d, c = g['date'].to_numpy(), g['close'].to_numpy(dtype='float64')
        d.setflags(write=False)
        c.setflags(write=False)
        out[i] = (d, c)
    return out


@st.cache_data(ttl=1800, show_spinner=False)
def artifact(key: str) -> pd.DataFrame:
    """A parquet the precompute job writes under artifacts/ (empty if absent)."""
    body = _read(key)
    return pd.read_parquet(io.BytesIO(body)) if body else pd.DataFrame()


@st.cache_data(ttl=1800, show_spinner=False)
def market_strip() -> list:
    body = _read('artifacts/market_strip.json')
    return json.loads(body) if body else []


@st.cache_data(ttl=600, show_spinner=False, max_entries=500)
def said(isin: str) -> dict:
    """What management said on the company's latest earnings calls (archive/management_said/{ISIN}.json, written by the reader from
    the call transcripts, each fact with its exact quote); {} when none has been read."""
    if not isin or not str(isin).replace('_', '').isalnum():
        return {}
    body = _read(f'archive/management_said/{isin}.json')
    try:
        return json.loads(body) if body else {}
    except ValueError:
        return {}


@st.cache_data(ttl=600, show_spinner=False)
def latest() -> dict:
    body = _read('clean/latest.json')
    return json.loads(body) if body else {}


@st.cache_data(ttl=600, show_spinner=False)
def report() -> dict:
    info = latest()
    key = info.get('report')
    body = _read(key) if key and key != 'local' else _read('clean/report_local.json')
    return json.loads(body) if body else {}
