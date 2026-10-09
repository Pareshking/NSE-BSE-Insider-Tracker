"""Loads the site's stylesheet (ui/insiders.css) once per run, before
anything is drawn."""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import streamlit as st

HERE = Path(__file__).resolve().parent
FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link href="https://fonts.googleapis.com/css2?family=Geist:wght@400..700'
         '&family=Geist+Mono:wght@400..700&family=Schibsted+Grotesk:wght@600..800&display=swap" rel="stylesheet">')


@lru_cache(maxsize=1)
def _css() -> str:
    """The stylesheet without comments or blank lines. st.markdown passes a
    <style> block through untouched only while it has no blank line: at the
    first one Markdown ends the HTML block and prints the rest as text
    (seen in a real browser; the headless test runner doesn't render CSS)."""
    text = (HERE / 'insiders.css').read_text(encoding='utf-8')
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
    return '\n'.join(line.strip() for line in text.splitlines() if line.strip())


def inject() -> None:
    # st.markdown, not st.html: st.html sanitises away <style> and <link>.
    st.markdown(f'{FONTS}<style>\n{_css()}\n</style>', unsafe_allow_html=True)
