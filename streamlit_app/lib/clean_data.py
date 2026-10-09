"""Read-only access to the derived tables the research uses (clean/, prices/, indices/). Cached; never writes."""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # repo root, for insiders_clean

from lib import r2_data  # noqa: E402


def _read(client, key: str) -> pd.DataFrame:
    try:
        body = client.get_object(Bucket=r2_data._bucket(), Key=key)['Body'].read()
    except Exception as exc:  # noqa: BLE001
        raise r2_data.R2ReadError(r2_data._describe(exc, key)) from exc
    return pd.read_parquet(io.BytesIO(body))


@st.cache_data(ttl=900, max_entries=4, show_spinner=False)
def clean_table(_client, name: str) -> pd.DataFrame:
    """`name` is 'insider_trades' or 'deals'."""
    return _read(_client, f'clean/current/{name}.parquet')


@st.cache_data(ttl=900, max_entries=1, show_spinner=False)
def prices(_client, exchange: str = 'nse') -> pd.DataFrame:
    """All stored months of daily prices for one exchange (as printed, unadjusted)."""
    keys = [o['Key'] for p in _client.get_paginator('list_objects_v2').paginate(Bucket=r2_data._bucket(), Prefix=f'prices/daily/{exchange}/')
            for o in p.get('Contents', [])]
    return pd.concat([_read(_client, k) for k in sorted(keys)], ignore_index=True) if keys else pd.DataFrame()


@st.cache_data(ttl=900, max_entries=1, show_spinner=False)
def index_close(_client) -> pd.DataFrame:
    keys = [o['Key'] for p in _client.get_paginator('list_objects_v2').paginate(Bucket=r2_data._bucket(), Prefix='indices/daily/nse/')
            for o in p.get('Contents', [])]
    return pd.concat([_read(_client, k) for k in sorted(keys)], ignore_index=True) if keys else pd.DataFrame()
