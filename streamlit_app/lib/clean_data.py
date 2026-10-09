"""Read-only access to the derived tables the research uses (clean/, prices/, indices/). Cached; never writes."""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # repo root, for insiders_clean

from lib import r2_data  # noqa: E402


def _list_keys(client, prefix: str) -> list[str]:
    try:
        return sorted(o['Key'] for p in client.get_paginator('list_objects_v2').paginate(Bucket=r2_data._bucket(), Prefix=prefix)
                      for o in p.get('Contents', []))
    except Exception as exc:  # noqa: BLE001
        raise r2_data.R2ReadError(r2_data._describe(exc, prefix)) from exc


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
    keys = _list_keys(_client, f'prices/daily/{exchange}/')
    return pd.concat([_read(_client, k) for k in keys], ignore_index=True) if keys else pd.DataFrame()


@st.cache_data(ttl=900, max_entries=1, show_spinner=False)
def index_close(_client) -> pd.DataFrame:
    keys = _list_keys(_client, 'indices/daily/nse/')
    return pd.concat([_read(_client, k) for k in keys], ignore_index=True) if keys else pd.DataFrame()


def gate():
    """Credentials present -> an R2 client; otherwise explain and stop. These pages read derived tables directly and
    do not need the legacy nightly manifests."""
    if not r2_data.r2_configured():
        st.warning(r2_data.MISSING_CREDENTIALS_MESSAGE)
        st.stop()
    return r2_data.get_client()


@st.cache_data(ttl=900, max_entries=1, show_spinner=False)
def ledger(_client) -> pd.DataFrame:
    """The forward ledger, or an empty frame if the job has not written it yet."""
    if 'ledger/forward_ledger.parquet' not in _list_keys(_client, 'ledger/'):
        return pd.DataFrame()
    return _read(_client, 'ledger/forward_ledger.parquet')


@st.cache_data(ttl=900, max_entries=1, show_spinner=False)
def cleaning_report(_client) -> dict:
    """Latest cleaning report (what each rule removed and why), or {} if absent."""
    import json
    try:
        latest = json.loads(_client.get_object(Bucket=r2_data._bucket(), Key='clean/latest.json')['Body'].read())
        return json.loads(_client.get_object(Bucket=r2_data._bucket(), Key=latest['report'])['Body'].read())
    except Exception:  # noqa: BLE001
        return {}


@st.cache_data(ttl=3600, max_entries=1, show_spinner=False)
def raw_capture_counts(_client) -> pd.DataFrame:
    """Stored raw files per source/dataset under raw_v2/: blobs (distinct payloads) and fetch records."""
    counts: dict[tuple[str, str], list[int]] = {}
    for key in _list_keys(_client, 'raw_v2/'):
        parts = key.split('/')
        if len(parts) < 4:
            continue
        c = counts.setdefault((parts[1], parts[2]), [0, 0])
        c[0 if parts[3] == 'blobs' else 1] += 1
    return pd.DataFrame([{'source': s, 'dataset': d, 'blobs': b, 'fetch_records': f} for (s, d), (b, f) in sorted(counts.items())])
