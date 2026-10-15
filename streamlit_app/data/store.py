"""Reads the clean tables. In production from R2 (clean/current/*.parquet,
written nightly by scripts/clean_writer.py and the NSE events collector);
for local work from a folder named by INSIDERS_LOCAL_DATA that has the same
layout (clean/current/..., clean/latest.json)."""
from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import streamlit as st
from lib import r2_data

TABLES = ('insider_trades', 'deals', 'securities', 'sast', 'actions', 'meetings', 'shareholding', 'preferential', 'rights', 'tradability',
          'buybacks', 'bse_sast', 'bse_actions')
TABLES += ('preferential_allottees', 'preferential_lockins', 'qip', 'qip_allottees')   # insiders_clean/issues.py
TABLES += ('promoter_group',)   # members of each promoter group, from the shareholding XBRL
TABLES += ('announcement_reads',)   # filings read by scripts/announcement_reader.py, values checked


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
    return r2_data._get_bytes(r2_data.get_client(), key)


def configured() -> bool:
    return _local() is not None or r2_data.r2_configured()


# Kept in R2 for the clean layer and audits; no page reads them, and as Python strings they were a large
# share of the site's memory (meetings' raw_json alone 22 MB of 35): scripts/site_memory_report.py.
UNUSED = ('raw_json', 'xbrl_json', 'xbrl_url', 'xbrl_sha256')
ONLY = {'promoter_group': ('symbol', 'quarter_end', 'member_name', 'sub_category', 'shares', 'pct_of_company',
                           'pledged_shares')}   # the company page's card; the whole table was 76 MB in memory

FRESH = ('announcement_reads',)   # rewritten through the day as filings are read: kept for 3 minutes, not 10


def table(name: str) -> pd.DataFrame:
    return _fresh_table(name) if name in FRESH else _table(name)


def _parquet(name: str) -> pd.DataFrame:
    body = _read(f'clean/current/{name}.parquet')
    if not body:
        return pd.DataFrame()
    names = [c for c in pq.read_schema(io.BytesIO(body)).names if not c.startswith('__index_level_')]
    keep = [c for c in names if c not in UNUSED and (name not in ONLY or c in ONLY[name])]
    return pd.read_parquet(io.BytesIO(body), columns=keep)


@st.cache_data(ttl=600, show_spinner=False, max_entries=len(TABLES))
def _table(name: str) -> pd.DataFrame:
    return _parquet(name)


@st.cache_data(ttl=180, show_spinner=False, max_entries=len(FRESH))
def _fresh_table(name: str) -> pd.DataFrame:
    return _parquet(name)


@st.cache_data(ttl=600, show_spinner=False)
def prices() -> pd.DataFrame:
    """One row per ISIN: latest close, 52-week high/low (split and bonus
    adjusted), rewritten after each nightly run by scripts/precompute_slim.py."""
    body = _read('artifacts/prices_summary_slim.parquet')
    return pd.read_parquet(io.BytesIO(body)) if body else pd.DataFrame()


@st.cache_data(ttl=1800, show_spinner=False)
def price_history() -> dict:
    """ISIN -> (dates, closes) for the stocks in our filings, last ~400 days,
    split and bonus adjusted (artifacts/price_history.parquet)."""
    body = _read('artifacts/price_history.parquet')
    if not body:
        return {}
    h = pd.read_parquet(io.BytesIO(body))
    h['isin'] = h['isin'].astype('category')   # one string per stock, not per row: was 41 MB of the 49
    h['date'] = pd.to_datetime(h['date'])
    return {i: (g['date'].to_numpy(), g['close'].to_numpy(dtype='float64'))
            for i, g in h.groupby('isin', sort=False, observed=True)}


@st.cache_data(ttl=1800, show_spinner=False)
def artifact(key: str) -> pd.DataFrame:
    """A parquet the precompute job writes under artifacts/ (empty if absent)."""
    body = _read(key)
    return pd.read_parquet(io.BytesIO(body)) if body else pd.DataFrame()


@st.cache_data(ttl=1800, show_spinner=False)
def market_strip() -> list:
    body = _read('artifacts/market_strip.json')
    return json.loads(body) if body else []


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
