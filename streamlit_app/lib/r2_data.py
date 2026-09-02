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

Failure handling: a genuinely absent object is not an error (the manifest
is the source of truth for *why* a dataset is missing), so those return an
empty result. Anything else -- expired keys, a 403, a network drop, a
corrupt Parquet body -- raises R2ReadError carrying a short message that is
safe to render. The underlying exception is logged server-side with its
traceback; it is never shown to the browser, because the traceback contains
the bucket name, the account-scoped endpoint URL and server filesystem
paths.
"""
from __future__ import annotations

import contextlib
import io
import json
import logging
import os

import boto3
import pandas as pd
import streamlit as st

log = logging.getLogger(__name__)

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

MISSING_CREDENTIALS_MESSAGE = (
    "R2 credentials aren't configured for this app, so there's no data to show yet. "
    "Set `CLOUDFLARE_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, "
    "`R2_BUCKET_NAME` in `.streamlit/secrets.toml` (or as env vars) -- the same "
    "values already used by the GitHub Actions R2-storage workflow."
)

# Cache sizes are memory bounds, not just speed knobs: Streamlit Community
# Cloud caps a container at ~1GB, and every distinct (date, exchange,
# category) argument tuple keeps its own DataFrame alive for the whole TTL.
# Without a ceiling, paging back through run dates in the date selector
# accumulates every Parquet frame it touches until the worker is OOM-killed.
# 30 canonical frames is three full run dates (2 exchanges x 5 categories).
_CANONICAL_CACHE_ENTRIES = 30
_MANIFEST_CACHE_ENTRIES = 30
_RAW_CACHE_ENTRIES = 6
_MARKET_CAP_CACHE_ENTRIES = 6


class R2ReadError(RuntimeError):
    """An R2 read failed for a reason other than 'the object isn't there'.

    The message is written to be shown to a user as-is: no bucket name, no
    endpoint URL, no traceback.
    """


def _describe(exc: Exception, what: str) -> str:
    """Short, leak-free description of a failed read, for the browser."""
    code = status = None
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        code = (response.get("Error") or {}).get("Code")
        status = (response.get("ResponseMetadata") or {}).get("HTTPStatusCode")
    if code == "AccessDenied" or status == 403:
        return f"access denied while {what} -- the R2 key is missing read permission, or has expired"
    if code:
        return f"R2 returned {code}{f' (HTTP {status})' if status else ''} while {what}"
    return f"couldn't reach R2 while {what} ({type(exc).__name__})"


def _is_missing_object(client, exc: Exception) -> bool:
    """True for 'no such key/bucket'. botocore surfaces this as a typed
    exception on the client, but some S3-compatible endpoints answer with a
    plain ClientError carrying the same code, so check both."""
    if isinstance(exc, (client.exceptions.NoSuchKey, client.exceptions.NoSuchBucket)):
        return True
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        code = (response.get("Error") or {}).get("Code")
        return code in {"NoSuchKey", "NoSuchBucket", "NotFound", "404"}
    return False


def _get_bytes(client, key: str) -> bytes | None:
    """Object body, or None when the object simply isn't there."""
    try:
        return client.get_object(Bucket=_bucket(), Key=key)["Body"].read()
    except Exception as exc:
        if _is_missing_object(client, exc):
            return None
        log.exception("R2 get_object failed for key %s", key)
        raise R2ReadError(_describe(exc, f"reading `{key}`")) from exc


@contextlib.contextmanager
def guard(what: str):
    """Wrap a page's data loading so an R2 failure renders as a message
    instead of a traceback. Stops the page -- a half-loaded analytics
    screen is worse than an explicit failure."""
    try:
        yield
    except R2ReadError as exc:
        st.error(f"Couldn't load {what}: {exc}.", icon="🚫")
        st.stop()


def page_gate(fallback_title: str | None = None):
    """The check every page opens with: credentials present, bucket
    reachable, at least one manifest. Returns (client, dates) or stops the
    page with an explanation. `fallback_title` is rendered only on the
    failure paths, for pages that draw their own header on the happy path."""
    def _title():
        if fallback_title:
            st.title(fallback_title)

    if not r2_configured():
        _title()
        st.warning(MISSING_CREDENTIALS_MESSAGE)
        st.stop()
    client = get_client()
    with guard("the list of run dates"):
        dates = list_manifest_dates(client)
    if not dates:
        _title()
        st.info(
            "No manifests found in the bucket yet -- the R2 write workflow hasn't run, "
            "or hasn't produced output for any date."
        )
        st.stop()
    return client, dates


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


@st.cache_data(ttl=300, max_entries=1, show_spinner=False)
def list_manifest_dates(_client) -> list[str]:
    """Dates (YYYY-MM-DD) that have a manifests/{date}.json object, newest first."""
    if _client is None:
        return []
    dates = []
    try:
        paginator = _client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=_bucket(), Prefix="manifests/"):
            for obj in page.get("Contents", []):
                name = obj["Key"].rsplit("/", 1)[-1]
                if name.endswith(".json"):
                    dates.append(name[: -len(".json")])
    except Exception as exc:
        if _is_missing_object(_client, exc):
            return []
        log.exception("R2 list_objects_v2 failed for prefix manifests/")
        raise R2ReadError(_describe(exc, "listing run dates")) from exc
    return sorted(set(dates), reverse=True)


@st.cache_data(ttl=300, max_entries=_MANIFEST_CACHE_ENTRIES, show_spinner=False)
def load_manifest(_client, date: str) -> dict:
    """The full manifests/{date}.json -- per-(exchange,category) run outcome,
    including entries for datasets that were correctly skipped (BLOCKED/MISSING),
    never silently omitted."""
    if _client is None:
        return {}
    body = _get_bytes(_client, f"manifests/{date}.json")
    if body is None:
        return {}
    try:
        return json.loads(body)
    except ValueError as exc:
        log.exception("Manifest for %s is not valid JSON", date)
        raise R2ReadError(f"the manifest for {date} isn't readable JSON") from exc


@st.cache_data(ttl=300, max_entries=_CANONICAL_CACHE_ENTRIES, show_spinner=False)
def load_canonical(_client, exchange: str, category: str, date: str) -> pd.DataFrame:
    """canonical/{exchange}/{category}/{date}/data.parquet as a DataFrame.
    Empty DataFrame (not an error) if the dataset wasn't written this run --
    the manifest is the source of truth for *why*, this just returns what
    actually exists."""
    if _client is None:
        return pd.DataFrame()
    key = f"canonical/{exchange}/{category}/{date}/data.parquet"
    body = _get_bytes(_client, key)
    if body is None:
        return pd.DataFrame()
    try:
        return pd.read_parquet(io.BytesIO(body))
    except Exception as exc:
        log.exception("Parquet at %s could not be read", key)
        raise R2ReadError(
            f"the {CATEGORY_LABELS.get(category, category)} file for {exchange.upper()} "
            f"on {date} isn't readable Parquet"
        ) from exc


@st.cache_data(ttl=300, max_entries=_RAW_CACHE_ENTRIES, show_spinner=False)
def load_raw(_client, exchange: str, category: str, date: str) -> list[dict]:
    """raw/{exchange}/{category}/{date}/raw.json -- native fields, unmodified,
    for evidence drill-down alongside the canonical_* columns."""
    if _client is None:
        return []
    key = f"raw/{exchange}/{category}/{date}/raw.json"
    body = _get_bytes(_client, key)
    if body is None:
        return []
    try:
        return json.loads(body)
    except ValueError as exc:
        log.exception("Raw JSON at %s could not be parsed", key)
        raise R2ReadError(f"the raw {CATEGORY_LABELS.get(category, category)} file for {date} isn't readable JSON") from exc


@st.cache_data(ttl=300, max_entries=_MARKET_CAP_CACHE_ENTRIES, show_spinner=False)
def load_market_cap(_client, date: str) -> pd.DataFrame:
    """reference/market_cap/{date}/data.json -- NSE symbol -> market cap
    reference data (see scripts/nse_market_cap.py). NSE-only and only for
    symbols with activity that day; not a transaction dataset, so it isn't
    part of the certification manifest['datasets'] list. Empty DataFrame
    (not an error) if this run didn't produce one."""
    if _client is None:
        return pd.DataFrame()
    body = _get_bytes(_client, f"reference/market_cap/{date}/data.json")
    if body is None:
        return pd.DataFrame()
    try:
        rows = json.loads(body)
    except ValueError as exc:
        log.exception("Market cap reference for %s could not be parsed", date)
        raise R2ReadError(f"the market cap reference for {date} isn't readable JSON") from exc
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def market_cap_lookup(_client, date: str) -> "pd.Series | None":
    """symbol (upper-cased) -> market cap, or None when this run has no
    reference data. Every caller was building this the same way."""
    mcap_df = load_market_cap(_client, date)
    if mcap_df.empty or "symbol" not in mcap_df.columns:
        return None
    lookup = mcap_df.drop_duplicates("symbol").set_index("symbol")["market_cap"]
    lookup.index = lookup.index.astype(str).str.upper()
    return lookup


def load_combined(_client, category: str, exchanges, date: str) -> pd.DataFrame:
    """One category's rows across the chosen exchanges, concatenated.
    Empty DataFrame when none of them wrote this dataset."""
    frames = [load_canonical(_client, ex, category, date) for ex in exchanges]
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


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
