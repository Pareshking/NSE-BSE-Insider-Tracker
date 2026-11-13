"""The site's one theme (redesign of 12 Nov 2026, owner: "flat, minimal and subtle colours across the theme ...
use theme.py and bring everything there so in future one line change would work across the website").

Every colour, font, size, radius and spacing the site draws with is a token here. The stylesheets (ui/insiders.css,
ui/table.css, ui/ds.css) use only `var(--token)`; the charts (ui/lwchart.py, ui/charts.py) read `C` below. Change a
value here and every page follows. Nothing else in the code base sets a colour.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import streamlit as st

HERE = Path(__file__).resolve().parent

# ---- Colour: a warm-neutral page, near-black ink, one muted accent, muted green and red for buying and selling only,
# muted amber for "needs a look". Tints are the same hues at low strength, for backgrounds only.
COLORS = {
    'bg': '#F3F4F6',            # the page: a soft grey the cards sit on
    'surface': '#FFFFFF',       # a card
    'subtle': '#F1F2F6',        # a quiet fill: avatars, date badges, a neutral chip
    'hover': '#F8F9FB',         # a row under the pointer
    'line': '#EEF0F3',          # hairlines between rows inside a card
    'line-strong': '#E3E6EA',   # an input's edge, a table head's rule
    'rule': '#E3E6EA',
    'ink': '#111827',           # text
    'ink-2': '#4B5563',         # secondary text
    'ink-3': '#6B7280',         # labels, notes
    'ink-4': '#A3A9B3',         # a dash, an empty value
    'accent': '#4F5BD5',        # links, the selected control, the brand mark
    'accent-ink': '#3F49B8',
    'accent-tint': '#EEF0FC',
    'buy': '#15803D',     'buy-tint': '#E9F7EE',
    'sell': '#C2410C',    'sell-tint': '#FDEFE7',
    'warn': '#B45309',    'warn-tint': '#FEF5E6',  'warn-ink': '#92400E',
    'nse': '#5B4A8B',     'bse': '#2F6F7E',        # exchange marks
    'on-accent': '#FFFFFF',     # text on a filled accent chip
    'range-lo': '#F6DCD2', 'range-mid': '#E9EBEF', 'range-hi': '#CFEBDA',   # the 52-week bar, low to high
}

FONTS = {
    'ui': "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
    'mono': "'Geist Mono', ui-monospace, SFMono-Regular, Menlo, monospace",
}
FONT_LINK = ('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Geist+Mono:wght@400..600&display=swap')

# ---- Type scale (px): one per role. Headline is the page's news line; title a section's; the rest by use.
TYPE = {
    'fs-headline': '34px', 'fs-headline-phone': '26px',
    'fs-title': '17px', 'fs-card': '15px', 'fs-body': '14px', 'fs-small': '12.5px', 'fs-label': '11px',
    'fs-stat': '28px', 'fs-stat-phone': '22px',
    'fw-regular': '400', 'fw-medium': '500', 'fw-strong': '600', 'fw-stat': '600',
}

# ---- Space and shape: flat (no shadows), small radius, a 4 px grid.
SPACE = {
    'radius': '18px', 'radius-sm': '10px', 'radius-pill': '999px', 'shadow': 'none',
    'card-pad': '22px 24px', 'card-pad-phone': '18px',
    'gap-1': '4px', 'gap-2': '8px', 'gap-3': '12px', 'gap-4': '16px', 'gap-5': '24px', 'gap-6': '36px',
    'gutter': '40px', 'gutter-phone': '14px', 'row-h': '44px', 'page-max': '1280px',
}

# For Python drawing code (charts): the same values by name.
C = dict(COLORS)
C.update(FONTS)


def css_vars() -> str:
    tokens = {**COLORS, **{k: v for k, v in FONTS.items()}, **TYPE, **SPACE}
    return ':root{' + ''.join(f'--{k}:{v};' for k, v in tokens.items()) + '}'


def _css() -> str:
    # Keyed on the stylesheets' modification times: a changed .css reaches the running site without a restart (12 Nov).
    return _css_for(tuple((HERE / f).stat().st_mtime for f in CSS_FILES))


CSS_FILES = ('insiders.css', 'table.css', 'ds.css', 'dt.css')


@lru_cache(maxsize=2)
def _css_for(_mtimes: tuple) -> str:
    """The stylesheets without comments or blank lines. st.markdown passes a <style> block through untouched only while
    it has no blank line: at the first one Markdown ends the HTML block and prints the rest as text."""
    text = css_vars() + '\n' + '\n'.join((HERE / f).read_text(encoding='utf-8') for f in CSS_FILES)
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
    return '\n'.join(line.strip() for line in text.splitlines() if line.strip())


def inject() -> None:
    # st.markdown, not st.html: st.html sanitises away <style> and <link>.
    st.markdown('<link rel="preconnect" href="https://fonts.googleapis.com">'
                '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
                f'<link href="{FONT_LINK}" rel="stylesheet"><style>\n{_css()}\n</style>', unsafe_allow_html=True)


# ---- Streamlit's own widgets read .streamlit/config.toml, which cannot import this file. `streamlit_theme()` is
# that [theme] block from the tokens above; `python scripts/sync_theme.py` writes it into both config files, and
# tests/test_theme.py fails when they drift, so a token changed here reaches the widgets too.
def streamlit_theme() -> dict:
    return {
        'base': 'light', 'primaryColor': COLORS['accent'], 'backgroundColor': COLORS['bg'],
        'secondaryBackgroundColor': COLORS['surface'], 'textColor': COLORS['ink'], 'linkColor': COLORS['accent-ink'],
        'linkUnderline': False, 'borderColor': COLORS['line-strong'], 'showWidgetBorder': True, 'baseRadius': SPACE['radius-sm'],
        'greenColor': COLORS['buy'], 'redColor': COLORS['sell'], 'orangeColor': COLORS['warn'],
        'dataframeHeaderBackgroundColor': COLORS['subtle'],
        # Streamlit accepts one family per font URL (StreamlitInvalidThemeOptionError otherwise).
        'font': 'Inter:https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap, sans-serif',
        'codeFont': "'Geist Mono':https://fonts.googleapis.com/css2?family=Geist+Mono:wght@400..600&display=swap, monospace",
    }


def theme_toml() -> str:
    def val(v):
        return 'true' if v is True else 'false' if v is False else '"' + str(v).replace('"', '\\"') + '"'
    return ('[theme]\n# Written by scripts/sync_theme.py from streamlit_app/ui/theme.py: change the tokens there, not here.\n'
            + ''.join(f'{k} = {val(v)}\n' for k, v in streamlit_theme().items()))
