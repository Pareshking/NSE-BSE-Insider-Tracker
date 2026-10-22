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


def test_tables_are_drawn_in_the_page_with_plain_links_and_rows_that_open():
    """Tables moved out of iframes on 21 Oct: they share the page's styles, links are plain links,
    and a row with facts behind it carries a hidden detail row that sorts with it."""
    import pandas as pd
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_string("""
import sys; sys.path.insert(0, 'streamlit_app')
import pandas as pd
from ui import table
rows = pd.DataFrame({'company': ['Alpha Ltd', 'Beta Ltd'], 'nse_symbol': ['ALPHA', 'BETA'], 'value': [2e7, 5e6]})
table.table(rows, [table.Col('company', 'Company', 'co'), table.Col('value', 'Value', 'money')],
            detail=lambda r: table.facts([('Value', str(r['value']))], [('Filing', 'https://example.com/f.xml')]))
""")
    at.run()
    assert not at.exception
    html = ' '.join(e.proto.body for e in at.get('html'))
    assert 'iframe' not in html and 'target="_top"' not in html
    assert 'company?symbol=ALPHA" target="_self"' in html
    assert html.count('<template>') == 2 and 'data-l=' in html and 'has-dt' in html and 'groups.sort' in html

def test_flags_given_as_one_string_are_badges_not_letters():
    """The forward record's flags arrive as "ESM I, T2T, 5% band" and were drawn letter by letter (21 Oct)."""
    out = kit.flag_tags('ESM I, T2T, 5% band', 'Enhanced surveillance, stage I')
    assert out.count('class="tg tg-warn"') == 3 and '>ESM I<' in out and '>5% band<' in out
    assert out.count('Enhanced surveillance, stage I') == 3
    assert kit.flag_tags(['SME'], ['SME board']).count('tg-warn') == 1 and kit.flag_tags(None) == ''
