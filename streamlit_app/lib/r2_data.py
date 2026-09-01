"""R2 data-access layer for the Streamlit frontend.

Reads the exact objects scripts/r2_writer.py writes -- same bucket, same
layout (manifests/{date}.json, canonical/{exchange}/{category}/{date}/data.parquet,
raw/{exchange}/{category}/{date}/raw.json) and the same canonical_* field
names it computes. This module never writes to R2, only reads.

Credentials: st.secrets first (Streamlit Cloud), falling back to the same
env var names r2_writer.py and the GitHub Actions workflow already use
(CLOUDFLARE_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY,
R2_BUCKET_NAME) -- so the same secret values already sitting in the repo's
GitHub Actions secrets can be pasted into .streamlit/secrets.toml or the
shell with no renaming.
"""
from __future__ import annotations

import io
import json
import os

import boto3
import pandas as pd
import streamlit as st

CATEGORIES = [
    "insider_trading",
    "bulk_deals",
    "block_deals",
    "rights_issue",
    "preferential_issue",
]
EXCHANGES = ["nse", "bse"]

CATEGORY_LABELS = {
    "insider_trading": "Insider Trading",
    "bulk_deals": "Bulk Deals",
    "block_deals": "Block Deals",
    "rights_issue": "Rights Issues",
    "preferential_issue": "Preferential Issues",
}


def _cfg(name: str) -> str | None:
    # st.secrets raises StreamlitSecretNotFoundError on membership/lookup
    # when no secrets.toml exists anywhere at all (not just "key missing") --
    # env-var-only setups (e.g. this repo's GitHub Actions secrets) must
    # still work, so treat "no secrets file" the same as "key not in it".
    try:
        if name in st.secrets:
            return st.secrets[name]
    except st.errors.StreamlitSecretNotFoundError:
        pass
    return os.environ.get(name)


def r2_configured() -> bool:
    return all(
        _cfg(k)
        for k in (
            "CLOUDFLARE_ACCOUNT_ID",
            "R2_ACCESS_KEY_ID",
            "R2_SECRET_ACCESS_KEY",
            "R2_BUCKET_NAME",
        )
    )


@st.cache_resource(show_spinner=False)
def get_client():
    if not r2_configured():
        return None
    return boto3.client(
        "s3",
        endpoint_url=f"https://{_cfg('CLOUDFLARE_ACCOUNT_ID')}.r2.cloudflarestorage.com",
        aws_access_key_id=_cfg("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=_cfg("R2_SECRET_ACCESS_KEY"),
        region_name="auto",
    )


def _bucket() -> str:
    return _cfg("R2_BUCKET_NAME")


@st.cache_data(ttl=300, show_spinner=False)
def list_manifest_dates(_client) -> list[str]:
    """Dates (YYYY-MM-DD) that have a manifests/{date}.json object, newest first."""
    if _client is None:
        return []
    dates = []
    paginator = _client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=_bucket(), Prefix="manifests/"):
        for obj in page.get("Contents", []):
            name = obj["Key"].rsplit("/", 1)[-1]
            if name.endswith(".json"):
                dates.append(name[: -len(".json")])
    return sorted(set(dates), reverse=True)


@st.cache_data(ttl=300, show_spinner=False)
def load_manifest(_client, date: str) -> dict:
    """The full manifests/{date}.json -- per-(exchange,category) run outcome,
    including entries for datasets that were correctly skipped (BLOCKED/MISSING),
    never silently omitted."""
    if _client is None:
        return {}
    try:
        obj = _client.get_object(Bucket=_bucket(), Key=f"manifests/{date}.json")
        return json.loads(obj["Body"].read())
    except _client.exceptions.NoSuchKey:
        return {}


@st.cache_data(ttl=300, show_spinner=False)
def load_canonical(_client, exchange: str, category: str, date: str) -> pd.DataFrame:
    """canonical/{exchange}/{category}/{date}/data.parquet as a DataFrame.
    Empty DataFrame (not an error) if the dataset wasn't written this run --
    the manifest is the source of truth for *why*, this just returns what
    actually exists."""
    if _client is None:
        return pd.DataFrame()
    key = f"canonical/{exchange}/{category}/{date}/data.parquet"
    try:
        obj = _client.get_object(Bucket=_bucket(), Key=key)
        return pd.read_parquet(io.BytesIO(obj["Body"].read()))
    except _client.exceptions.NoSuchKey:
        return pd.DataFrame()


@st.cache_data(ttl=300, show_spinner=False)
def load_raw(_client, exchange: str, category: str, date: str) -> list[dict]:
    """raw/{exchange}/{category}/{date}/raw.json -- native fields, unmodified,
    for evidence drill-down alongside the canonical_* columns."""
    if _client is None:
        return []
    key = f"raw/{exchange}/{category}/{date}/raw.json"
    try:
        obj = _client.get_object(Bucket=_bucket(), Key=key)
        return json.loads(obj["Body"].read())
    except _client.exceptions.NoSuchKey:
        return []


def load_all_canonical(_client, date: str) -> dict[tuple[str, str], pd.DataFrame]:
    """{(exchange, category): DataFrame} for every combination that has data
    on this date. Skips (returns no key) whatever load_canonical returns empty
    for -- callers should check the manifest for *why*, not assume a bug."""
    out = {}
    for exchange in EXCHANGES:
        for category in CATEGORIES:
            df = load_canonical(_client, exchange, category, date)
            if not df.empty:
                out[(exchange, category)] = df
    return out
