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
    'bg': '#FAFAF8',            # the page
    'surface': '#FFFFFF',       # a raised surface (menus, popovers, the table's sticky column)
    'subtle': '#F3F3F0',        # a quiet background: hover, note boxes, the table head
    'hover': '#F6F6F3',         # a row under the pointer
    'line': '#E6E6E1',          # hairlines between rows
    'line-strong': '#D6D6CF',   # rules under heads, between sections
    'rule': '#2B2E33',          # the dark rule above a section title
    'ink': '#1E2125',           # text
    'ink-2': '#4B5058',         # secondary text
    'ink-3': '#777C84',         # labels, notes
    'ink-4': '#A9ADB3',         # a dash, an empty value
    'accent': '#3E5C7E',        # links, the selected control: a muted steel blue
    'accent-ink': '#2F4A68',
    'accent-tint': '#EDF1F5',
    'buy': '#2F7A57',     'buy-tint': '#EAF3EE',
    'sell': '#AE4B3E',    'sell-tint': '#F7ECEA',
    'warn': '#9A6B16',    'warn-tint': '#F8F1E2',  'warn-ink': '#6B4A10',
    'nse': '#5B4A8B',     'bse': '#2F6F7E',        # exchange marks
    'on-accent': '#FFFFFF',     # text on a filled accent chip
    'range-lo': '#EFD9D4', 'range-mid': '#E7E7E2', 'range-hi': '#D3E7DB',   # the 52-week bar, low to high
}

FONTS = {
    'ui': "'Geist', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
    'mono': "'Geist Mono', ui-monospace, SFMono-Regular, Menlo, monospace",
}
FONT_LINK = ('https://fonts.googleapis.com/css2?family=Geist:wght@300..700&family=Geist+Mono:wght@400..600&display=swap')

# ---- Type scale (px): one per role. Headline is the page's news line; title a section's; the rest by use.
TYPE = {
    'fs-headline': '34px', 'fs-headline-phone': '24px',
    'fs-title': '20px', 'fs-card': '15px', 'fs-body': '14px', 'fs-small': '12.5px', 'fs-label': '11px',
    'fs-stat': '24px', 'fs-stat-phone': '20px',
    'fw-regular': '400', 'fw-medium': '500', 'fw-strong': '600', 'fw-stat': '400',
}

# ---- Space and shape: flat (no shadows), small radius, a 4 px grid.
SPACE = {
    'radius': '6px', 'radius-sm': '4px', 'shadow': 'none',
    'gap-1': '4px', 'gap-2': '8px', 'gap-3': '12px', 'gap-4': '16px', 'gap-5': '24px', 'gap-6': '36px',
    'gutter': '24px', 'gutter-phone': '14px', 'row-h': '44px', 'page-max': '1320px',
}

# For Python drawing code (charts): the same values by name.
C = dict(COLORS)
C.update(FONTS)


def css_vars() -> str:
    tokens = {**COLORS, **{k: v for k, v in FONTS.items()}, **TYPE, **SPACE}
    return ':root{' + ''.join(f'--{k}:{v};' for k, v in tokens.items()) + '}'


@lru_cache(maxsize=1)
def _css() -> str:
    """The stylesheets without comments or blank lines. st.markdown passes a <style> block through untouched only while
    it has no blank line: at the first one Markdown ends the HTML block and prints the rest as text."""
    text = css_vars() + '\n' + '\n'.join((HERE / f).read_text(encoding='utf-8') for f in ('insiders.css', 'table.css', 'ds.css'))
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
        'secondaryBackgroundColor': COLORS['subtle'], 'textColor': COLORS['ink'], 'linkColor': COLORS['accent-ink'],
        'linkUnderline': False, 'borderColor': COLORS['line-strong'], 'showWidgetBorder': True, 'baseRadius': SPACE['radius'],
        'greenColor': COLORS['buy'], 'redColor': COLORS['sell'], 'orangeColor': COLORS['warn'],
        'dataframeHeaderBackgroundColor': COLORS['subtle'],
        # Streamlit accepts one family per font URL (StreamlitInvalidThemeOptionError otherwise).
        'font': 'Geist:https://fonts.googleapis.com/css2?family=Geist:wght@300..700&display=swap, sans-serif',
        'codeFont': "'Geist Mono':https://fonts.googleapis.com/css2?family=Geist+Mono:wght@400..600&display=swap, monospace",
    }


def theme_toml() -> str:
    def val(v):
        return 'true' if v is True else 'false' if v is False else '"' + str(v).replace('"', '\\"') + '"'
    return ('[theme]\n# Written by scripts/sync_theme.py from streamlit_app/ui/theme.py: change the tokens there, not here.\n'
            + ''.join(f'{k} = {val(v)}\n' for k, v in streamlit_theme().items()))
