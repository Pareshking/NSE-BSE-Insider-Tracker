"""The parts every page is built from, so all pages read alike: a top bar,
a data strip, a page head, a row of tiles, cards, tags, and one way of
writing money, percentages and dates."""
from __future__ import annotations

import html
import math
from contextlib import contextmanager
from dataclasses import dataclass
from urllib.parse import quote

import pandas as pd
import streamlit as st

esc = html.escape


# ---- formatting ------------------------------------------------------------

def _finite(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def blank_text(values, pattern: str) -> pd.Series:
    """Numbers as text with a real blank where missing: st.dataframe writes
    "None" in an empty number cell whatever the format (a Styler's na_rep
    included). For sparse columns only; the column then sorts as text."""
    s = pd.to_numeric(pd.Series(values), errors='coerce')
    return s.map(lambda v: '' if pd.isna(v) else pattern.format(v))


def rupees(v, signed: bool = False) -> str:
    """Indian units: Rs. L under one crore, Rs. Cr above. Em dash when unknown."""
    f = _finite(v)
    if f is None:
        return '—'
    sign = ('+' if f > 0 else '−' if f < 0 else '') if signed else ('−' if f < 0 else '')
    a = abs(f)
    if a >= 1e7:
        return f'{sign}₹{a / 1e7:,.2f} Cr'
    return f'{sign}₹{a / 1e5:,.2f} L'


def pct(v, digits: int = 2, signed: bool = False) -> str:
    """A number that is already a percentage (0.42 -> '0.42%')."""
    f = _finite(v)
    if f is None:
        return '—'
    if f != 0 and abs(f) < 0.5 * 10 ** -digits:
        return f'{"−" if f < 0 else "+" if signed else ""}<{10 ** -digits:.{digits}f}%'
    return f'{f:+.{digits}f}%' if signed else f'{f:.{digits}f}%'


def day(v) -> str:
    try:
        return pd.Timestamp(v).strftime('%d %b %Y')
    except (TypeError, ValueError):
        return '—'


def count(v) -> str:
    f = _finite(v)
    return '—' if f is None else f'{f:,.0f}'


ROLE_LABELS = {'promoter': 'promoter', 'promoter_group': 'promoter group', 'director': 'director', 'kmp': 'KMP',
               'designated_person': 'designated person', 'immediate_relative': 'relative', 'employee': 'employee',
               'other': 'other', 'missing': 'role not stated'}


def role(r) -> str:
    return ROLE_LABELS.get(str(r), str(r).replace('_', ' '))


# ---- links -------------------------------------------------------------------

def company_href(symbol) -> str:
    return f'/company?symbol={quote(str(symbol))}' if symbol else '#'


def entity_href(entity_id) -> str:
    return f'/entity?id={quote(str(entity_id))}' if entity_id else '#'


# ---- tags --------------------------------------------------------------------

def tag(text: str, tone: str = 'mute') -> str:
    return f'<span class="tg tg-{tone}">{esc(text)}</span>'


def side_tag(side) -> str:
    return tag('BUY', 'buy') if side == 'BUY' else tag('SELL', 'sell') if side == 'SELL' else ''


def exchange_tags(listed_on) -> str:
    return ' '.join(f'<span class="ex ex-{e}">{e.upper()}</span>'
                    for e in str(listed_on or '').split(',') if e in ('nse', 'bse'))


# ---- page structure ------------------------------------------------------------

def head(title: str, sub: str) -> None:
    st.html(f'<div class="head"><h1>{esc(title)}</h1><p>{esc(sub)}</p></div>')


@dataclass(frozen=True)
class Tile:
    label: str
    value: str
    note: str = ''
    tone: str = ''   # '', 'up', 'down'


def tiles(items: list[Tile]) -> None:
    cells = ''.join(
        f'<div class="tile"><span class="k">{esc(t.label)}</span>'
        f'<span class="v num {t.tone}">{esc(t.value)}</span>'
        + (f'<span class="s">{esc(t.note)}</span>' if t.note else '') + '</div>' for t in items)
    st.html(f'<section class="tiles">{cells}</section>')


@contextmanager
def card(title: str, key: str, aside: str = ''):
    with st.container(key=f'card_{key}'):
        st.html(f'<div class="card-h"><h2>{esc(title)}</h2>'
                + (f'<span>{esc(aside)}</span>' if aside else '') + '</div>')
        yield


def note(lead: str, text: str = '') -> None:
    st.html(f'<div class="note" role="note"><b>{esc(lead)}</b>' + (f' {esc(text)}' if text else '') + '</div>')


def caption(text: str) -> None:
    st.html(f'<p class="cap">{esc(text)}</p>')


def empty(text: str) -> None:
    st.html(f'<div class="empty">{esc(text)}</div>')


def topbar(pages: list, active, pill_text: str, pill_warn: bool = False) -> None:
    """Brand (link home), page links, data pill; a menu replaces the links
    on narrow screens."""
    with st.container(key='topbar', horizontal=True, vertical_alignment='center', gap='small'):
        with st.container(key='brand', width='content'):
            st.page_link(pages[0], label='Insiders')
        with st.container(key='links', horizontal=True, vertical_alignment='center', width='stretch'):
            for i, p in enumerate(pages):
                with st.container(key=f'{"on" if p is active else "off"}_link_{i}', width='content'):
                    st.page_link(p)
        st.html(f'<span class="pill{" warn" if pill_warn else ""}"><i></i>{esc(pill_text)}</span>', width='content')
        with st.container(key='menu', width='content'), st.popover('☰', type='tertiary', help='Pages'):
            for i, p in enumerate(pages):
                with st.container(key=f'{"on" if p is active else "off"}_menu_{i}'):
                    st.page_link(p)


def strip(parts: list[str]) -> None:
    """The data line under the bar: each part is trusted HTML built by the caller."""
    st.html('<div class="strip">' + ''.join(f'<span>{p}</span>' for p in parts) + '</div>')




# Tables live in ui/table.py; re-exported so pages keep one import.
from ui.table import Col, range_bar, spark, table  # noqa: E402,F401
