"""One theme (owner, 12 Nov 2026: "use theme.py and bring everything there so in future one line change would work
across the website"): every colour lives in streamlit_app/ui/theme.py; the stylesheets use var(--token) only; the
Streamlit config's [theme] block is written from it (scripts/sync_theme.py)."""
from __future__ import annotations

import re
import sys

from conftest import ROOT

sys.path.insert(0, str(ROOT / 'streamlit_app'))
sys.path.insert(0, str(ROOT / 'scripts'))

HEX = re.compile(r'#[0-9A-Fa-f]{6}\b|#[0-9A-Fa-f]{3}\b')


def test_no_colour_outside_theme_py():
    ui = ROOT / 'streamlit_app'
    hits = []
    for f in list(ui.rglob('*.py')) + list(ui.rglob('*.css')):
        if f.name == 'theme.py' or '__pycache__' in f.parts:
            continue
        text = re.sub(r'/\*.*?\*/', '', f.read_text(encoding='utf-8'), flags=re.DOTALL)
        hits += [f'{f.relative_to(ROOT)}: {m}' for m in HEX.findall(text)]
    assert not hits, hits


def test_every_css_variable_is_a_theme_token():
    from ui import theme
    tokens = set(theme.COLORS) | set(theme.FONTS) | set(theme.TYPE) | set(theme.SPACE)
    used = set()
    for f in ('insiders.css', 'table.css', 'ds.css'):
        used |= set(re.findall(r'var\(--([a-z0-9-]+)', (ROOT / 'streamlit_app' / 'ui' / f).read_text(encoding='utf-8')))
    assert used <= tokens, sorted(used - tokens)


def test_streamlit_config_follows_theme_py():
    import sync_theme
    for f in sync_theme.CONFIGS:
        text = f.read_text(encoding='utf-8')
        assert sync_theme.synced(text) == text, f'{f}: run python scripts/sync_theme.py'


def test_one_token_changes_the_stylesheet(monkeypatch):
    from ui import theme
    monkeypatch.setitem(theme.COLORS, 'accent', '#123456')
    assert '--accent:#123456;' in theme.css_vars()


def test_streamlit_font_urls_name_one_family():
    from ui import theme
    for k in ('font', 'codeFont'):
        assert theme.streamlit_theme()[k].count('family=') == 1, k
