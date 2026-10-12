"""Regressions from the 12 Oct page audit."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'streamlit_app'))

import pandas as pd
from ui import kit
from ui.table import _cell


def test_company_cell_ignores_nan_symbol():
    html, _, _ = _cell(kit.Col('company', 'Company', 'co'),
                       {'company': 'Acme Ltd', 'nse_symbol': float('nan'), 'symbol': 'ACME'}, {})
    assert 'nan' not in html.lower() and 'ACME' in html


def test_search_text_with_regex_characters_is_literal():
    s = pd.Series(['Tata (Power)', 'C++ Ltd'])
    assert s.str.contains('(', case=False, regex=False).tolist() == [True, False]
    assert s.str.contains('C++', case=False, regex=False).tolist() == [False, True]
