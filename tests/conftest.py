"""Shared fixtures for the cleaning-layer tests.

Real filings: tests/fixtures/nse_pit_real.json holds NSE PIT filings fetched
on 07 Oct 2026 from NSE's public filing list and each filing's XBRL, through
scripts/nse_insider.py's own parser (fetch_filing_list + fetch_and_parse).
They are turned into canonical rows by scripts/r2_writer.py's own
rows_to_parquet_bytes, so the tests see exactly what the nightly run stores
in R2.
"""
from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / 'fixtures'
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
os.environ.setdefault('SECURITY_MASTER_PATH', str(ROOT / 'reference_data' / 'security_master_20260901.csv'))

import r2_writer

from insiders_clean.calendar import seed_state
from insiders_clean.report import Report
from insiders_clean.securities import (
    SecurityMaster,
    bse_list_frame,
    nse_list_frame,
)

RUN_DATE = '2026-10-07'

# BSE list rows in the shape of the nightly market-cap reference file
# (reference/market_cap/{date}/data.json). Clean Max's code, ISIN and name
# are as in the security master; market caps here are test values.
BSE_ROWS = [
    {'symbol': '544717', 'isin': 'INE647U01026', 'company_name': 'Clean Max Enviro Energy Solutions Ltd',
     'market_cap': 9.0e10, 'source': 'bse_list_securities', 'group': 'A'},
    {'symbol': '544865', 'isin': 'INE00GO01025', 'company_name': 'LEAP India Ltd',
     'market_cap': 6.27e10, 'source': 'bse_list_securities', 'group': 'B'},
]


def canonical(exchange: str, category: str, rows: list[dict]) -> pd.DataFrame:
    """Rows -> the canonical Parquet frame r2_writer would write."""
    body, _ = r2_writer.rows_to_parquet_bytes(exchange, category, rows)
    return pd.read_parquet(io.BytesIO(body)).assign(exchange=exchange, category=category)


@pytest.fixture(scope='session')
def real_nse_rows():
    rows = json.loads((FIXTURES / 'nse_pit_real.json').read_text(encoding='utf-8'))
    return [{k: v for k, v in r.items() if k != '_filing'} for r in rows]


@pytest.fixture(scope='session')
def master():
    vr = pd.read_csv(ROOT / 'reference_data' / 'security_master_20260901.csv', dtype=str,
                     keep_default_na=False)
    nse = nse_list_frame(pd.read_csv(FIXTURES / 'nse_equity_sample.csv', dtype=str),
                         pd.read_csv(FIXTURES / 'nse_sme_sample.csv', dtype=str))
    return SecurityMaster(vr_master=vr, nse_list=nse, bse_list=bse_list_frame(BSE_ROWS),
                          market_cap_rows=BSE_ROWS + [
                              {'symbol': 'ZEEL', 'market_cap': 6.9e10, 'source': 'pr_zip'},
                              {'symbol': 'KESORAMIND', 'market_cap': 8.0e9, 'source': 'pr_zip'}])


@pytest.fixture()
def report():
    return Report(RUN_DATE)


@pytest.fixture(scope='session')
def calendar():
    from insiders_clean.calendar import Calendar
    return Calendar.from_state(seed_state())
