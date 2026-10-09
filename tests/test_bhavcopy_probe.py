"""The probe's file inspection (no network)."""
from __future__ import annotations

import io
import zipfile
from datetime import date

import bhavcopy_probe as bp


def test_zip_of_csv_is_described_with_columns_rows_and_series_counts():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('BhavCopy.csv', 'TradDt,SctySrs,ISIN,ClsPric\n2025-01-15,EQ,INE1,10\n2025-01-15,BE,INE2,11\n2025-01-15,EQ,INE3,12\n')
    info = bp.inspect(buf.getvalue())
    assert info['csv_header'] == ['TradDt', 'SctySrs', 'ISIN', 'ClsPric'] and info['csv_rows'] == 3
    assert info['counts_SctySrs'] == {'EQ': 2, 'BE': 1} and len(info['sample_rows']) == 2


def test_html_block_page_is_recognised_not_parsed_as_data():
    assert 'html' in bp.inspect(b'<!DOCTYPE html><html>Access Denied</html>')['looks_like']


def test_candidate_urls_for_a_day():
    urls = dict(bp.candidates(date(2025, 1, 15)))
    assert urls['nse_udiff_cm'].endswith('BhavCopy_NSE_CM_0_0_0_20250115_F_0000.csv.zip')
    assert urls['nse_old_cm_bhav'].endswith('/2025/JAN/cm15JAN2025bhav.csv.zip')
    assert urls['bse_udiff_cm'].endswith('BhavCopy_BSE_CM_0_0_0_20250115_F_0000.CSV')
