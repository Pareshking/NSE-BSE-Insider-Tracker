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
import streamlit as st
from lib import r2_data

TABLES = ('insider_trades', 'deals', 'securities', 'sast', 'actions', 'meetings', 'shareholding')


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


@st.cache_data(ttl=600, show_spinner=False, max_entries=len(TABLES))
def table(name: str) -> pd.DataFrame:
    body = _read(f'clean/current/{name}.parquet')
    return pd.read_parquet(io.BytesIO(body)) if body else pd.DataFrame()


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
