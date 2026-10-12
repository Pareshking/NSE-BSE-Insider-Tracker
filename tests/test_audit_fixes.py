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


def test_table_links_navigate_through_the_parent_page():
    """Streamlit's st.iframe is sandboxed without top-level navigation, so a bare target=_top link is
    blocked (checked in Chromium on 12 Oct). The frame script must hand the click to the parent page."""
    from ui import table
    assert "closest('a[target=\"_top\"]')" in table.SORT_JS and 'window.parent.document' in table.SORT_JS
