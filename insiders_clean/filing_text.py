"""The extracted text of every announcement file, kept so a filing is downloaded and turned into text once.

We keep no PDFs (to-do 2.7). The exchange serves a link for as long as it chooses (BSE moves old files to AttachHis),
and turning a 2 MB PDF into text takes a download and a `pdftotext` run, so the text is kept instead: one compressed
Parquet file per exchange and broadcast day,

    archive/filing_text/{nse|bse}/year=YYYY/month=MM/day=DD.parquet

one row per filing (`event_id` of the announcement archive): the text exactly as the reader would receive it
(`announcement_sample.text_of`: PDF text with `pdftotext -layout`, a ZIP's PDFs under file headers, XBRL facts where
the attachment is XBRL) but not cut at the model's length limit, the SHA-256 of the downloaded file, the extractor
version, pages and characters, and the outcome:

    ok       text extracted
    no_text  the file has no text layer (scanned?) or is empty
    failed   the download or the extraction raised; `tries` counts attempts, a missing file (HTTP 404/410) is final

Cleaning for a model (logos, addresses, padding, boilerplate: to-do 4.14) is NOT done here. The raw text is kept so
the cleaning can change and be re-run without another download.
"""
from __future__ import annotations

import io
import re
from datetime import date

import pandas as pd

PREFIX = 'archive/filing_text/'
EXTRACTOR = 'pdftotext-layout+xbrl-facts v1'
MAX_TRIES = 3
DONE = ('ok', 'no_text')
COLUMNS = ['event_id', 'exchange', 'broadcast_date', 'file_url', 'status', 'tries', 'reason', 'file_bytes',
           'file_sha256', 'extractor', 'extracted_at', 'pages', 'chars', 'notes', 'text']


def key(exchange: str, day: date | str) -> str:
    d = date.fromisoformat(str(day)[:10])
    return f'{PREFIX}{exchange}/year={d.year}/month={d.month:02d}/day={d.day:02d}.parquet'


def load_day(r2, exchange: str, day) -> pd.DataFrame:
    from clean_writer import read_parquet
    df = read_parquet(r2, key(exchange, day))
    return df.reindex(columns=COLUMNS) if df is not None else pd.DataFrame(columns=COLUMNS)


def pending(archive_rows: pd.DataFrame, cached: pd.DataFrame) -> pd.DataFrame:
    """The archive rows with a file and no finished record: never tried, or failed fewer than MAX_TRIES times."""
    if archive_rows is None or archive_rows.empty:
        return archive_rows
    done = set(cached.loc[cached['status'].isin(DONE), 'event_id']) if len(cached) else set()
    tries = dict(zip(cached['event_id'], cached['tries'].fillna(0).astype(int))) if len(cached) else {}
    keep = [e not in done and tries.get(e, 0) < MAX_TRIES for e in archive_rows['event_id']]
    return archive_rows[keep]


def merge(old: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    """One row per event_id; a newer attempt replaces the older one."""
    if old is None or old.empty:
        return new.reindex(columns=COLUMNS).reset_index(drop=True)
    both = pd.concat([old.reindex(columns=COLUMNS), new.reindex(columns=COLUMNS)], ignore_index=True)
    return both.drop_duplicates('event_id', keep='last').sort_values('event_id').reset_index(drop=True)


def save_day(r2, exchange: str, day, df: pd.DataFrame) -> None:
    from clean_writer import put
    buf = io.BytesIO()
    df.reindex(columns=COLUMNS).to_parquet(buf, index=False, compression='zstd')
    put(r2, key(exchange, day), buf.getvalue(), 'application/octet-stream')


def permanent(error: str) -> bool:
    """A missing document will not come back: do not retry it."""
    return bool(re.search(r'HTTP\s*(?:404|410)\b', str(error), re.IGNORECASE))
