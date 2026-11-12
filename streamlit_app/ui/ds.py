"""Design-system components (minimal theme, owner 12 Nov 2026: "build it and make sure to have minimalist theme", after
the Dribbble-style mock). Soft white cards on a grey page, big numbers in KPI cards, one-line rows (an initials badge,
the name and one grey line, the value and one chip on the right), no paragraphs. Colours and sizes: ui/theme.py only.

A page: head(), stats(), then section()s. A section opens a card; everything a page draws through this module after
it (stories, lists, record, club, calendar, empty, html) goes into that card until the next section() or head().
`inside()` gives the open card for widgets (pills, tables) that must sit in it.
"""
from __future__ import annotations

import re
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field

import streamlit as st

from ui.kit import esc

_t = threading.local()   # the card being filled, per script run (Streamlit runs each session's script on its own thread)


def _target():
    return getattr(_t, 'card', None) or st


def _reset():
    _t.card, _t.n = None, 0


@dataclass
class Story:
    """One decision as a row. `sub` is the one grey line (who did what, when); `chip` the one worked-out number
    (text, tone: 'up', 'dn', 'mut', 'wn'); `lede` the full sentence (on hover, and on the detail pages); `facts` the
    other numbers (detail pages); `note` said in amber when something needs a look."""
    company: str
    href: str = ''
    market: str = ''                 # trusted HTML: symbol · size · market cap · price
    lede: str = ''
    big: str = ''                    # the value, right
    facts: list = field(default_factory=list)
    note: str = ''
    tags: list = field(default_factory=list)     # (text, tone) tone in '', 'ok', 'warn', 'new'
    sub: str = ''
    chip: tuple = ()


def head(kicker: str, title_html: str, dek: list[str] | None = None) -> None:
    """The page's top: a small grey line, the headline (numbers in <b>), at most one grey line under it."""
    _reset()
    first = next((x for x in (dek or []) if x), '')
    st.html(f'<div class="head ds-head"><div class="ds-kicker">{kicker}</div><h1>{title_html}</h1>'
            + (f'<p class="ds-dek">{esc(first)}</p>' if first else '') + '</div>')


ICON = {'up': '↑', 'down': '↓', 'warn': '!', '': '•'}


def stats(cells: list[tuple]) -> None:
    """KPI cards: (label, value, note[, tone[, href]]). At most four in a row on a wide screen."""
    _t.card = None
    out = []
    for c in cells:
        k, v, s = c[0], c[1], c[2]
        tone = c[3] if len(c) > 3 else ''
        href = c[4] if len(c) > 4 else ''
        icon = f'<span class="ic {tone}">{ICON[tone]}</span>' if tone in ICON and tone else ''   # a neutral number has no icon
        inner = (f'<div class="l">{icon}{esc(k)}</div>'
                 f'<b>{esc(str(v))}</b><span class="s">{esc(s)}</span>')
        out.append('<a class="kpi" href="' + esc(href, quote=True) + '" target="_self">' + inner + '</a>' if href else f'<div class="kpi">{inner}</div>')
    st.html(f'<div class="ds-kpis n{min(len(cells), 4)}">' + ''.join(out) + '</div>')


def section(title: str, sub: str = '', href: str = '', link: str = '') -> None:
    """Open a card: the title on the left, one link on the right; `sub` is kept as the title's hover text."""
    _t.n = getattr(_t, 'n', 0) + 1
    slug = re.sub(r'[^a-z0-9]+', '_', title.lower()).strip('_')[:40]
    card = st.container(key=f'dscard_{_t.n}_{slug}')
    a = f'<a class="all" href="{esc(href, quote=True)}" target="_self">{esc(link or "See all")} →</a>' if href else ''
    card.html(f'<div class="ds-ch"><h2 title="{esc(sub, quote=True)}">{esc(title)}</h2>{a}</div>')
    _t.card = card


@contextmanager
def inside():
    """The open card, for widgets: `with ds.inside(): st.pills(...)`."""
    c = getattr(_t, 'card', None)
    if c is None:
        yield
    else:
        with c:
            yield


def html(body: str, **kw) -> None:
    _target().html(body, **kw)


def sub(title: str, note: str = '') -> str:
    return f'<div class="ds-sub">{esc(title)}' + (f'<span>{esc(note)}</span>' if note else '') + '</div>'


def tag(text: str, tone: str = '') -> str:
    return f'<span class="ds-tag {tone}">{esc(text)}</span>'


def _initials(name: str) -> str:
    words = [w for w in re.split(r'[\s\-&().,]+', str(name or '')) if w and w[0].isalnum()]
    return (''.join(w[0] for w in words[:2]) or '·').upper()


def story_html(s: Story, detail: bool = True) -> str:
    # On a compact row only "New" and the warning: "Measured ahead" is what the Worth-a-look card already says (real
    # data, 12 Nov: tags beside the name pushed it off the row on a phone).
    shown = s.tags if detail else [(t, tone) for t, tone in s.tags if tone == 'new']
    tags = ''.join(tag(t, tone) for t, tone in shown) + (tag(s.note, 'warn') if s.note and not detail else '')
    name = ('' if not s.company else f'<a href="{esc(s.href, quote=True)}" target="_self">{esc(s.company)}</a>' if s.href
            else esc(s.company))
    line = s.sub or s.lede
    chip = f'<span class="chip {s.chip[1]}">{esc(s.chip[0])}</span>' if s.chip else ''
    more = ''
    if detail:
        facts = '<span class="sep">·</span>'.join(esc(x) for x in s.facts if x)
        more = ((f'<p class="ds-facts">{facts}</p>' if facts else '') + (f'<p class="ds-note">{esc(s.note)}</p>' if s.note else ''))
    av = f'<div class="av">{esc(_initials(s.company))}</div>' if s.company else ''   # on a company's own page: no badge
    return (f'<div class="ds-row" title="{esc(s.lede, quote=True)}">{av}<div class="who">'
            + (f'<div class="nm">{name}{tags}</div>' if name or tags else '')
            + f'<span class="ln">{esc(line)}</span>{more}</div><div class="val"><b>{esc(s.big)}</b>{chip}</div></div>')


def stories(items: list[Story], empty_text: str = '', detail: bool = True) -> None:
    if not items:
        if empty_text:
            empty(empty_text)
        return
    _target().html('<div class="ds-rows">' + ''.join(story_html(s, detail) for s in items) + '</div>')


def record(text_html: str) -> None:
    """A one-line footnote in the card (the measured record; what a kind means)."""
    if text_html:
        _target().html(f'<p class="ds-foot">{text_html}</p>')


def empty(text: str) -> None:
    _target().html(f'<p class="ds-empty">{esc(text)}</p>')


@dataclass
class Col:
    key: str
    label: str
    right: bool = False
    phone: bool = True


def list_html(rows: list[dict], cols: list[Col]) -> str:
    """A quiet table. Each cell value is trusted HTML built by the caller (escape names with esc)."""
    head_ = ''.join(f'<th class="{"r" if c.right else ""}{"" if c.phone else " opt"}">{esc(c.label)}</th>' for c in cols)
    body = ''.join('<tr>' + ''.join(f'<td class="{"r" if c.right else ""}{"" if c.phone else " opt"}">{r.get(c.key, "") or ""}</td>'
                                    for c in cols) + '</tr>' for r in rows)
    return f'<div class="ds-wrap"><table class="ds-list"><thead><tr>{head_}</tr></thead><tbody>{body}</tbody></table></div>'


def club(title: str, lines: list[str]) -> None:
    """What was left out as noise, counted and summed, as small grey lines at the foot of the card."""
    lines = [x for x in lines if x]
    if lines:
        _target().html(f'<div class="ds-club" title="{esc(title, quote=True)}">' + ''.join(f'<p>{x}</p>' for x in lines) + '</div>')


def calendar(days: list[tuple[str, list[str]]], limit: int | None = None) -> None:
    """[(day label 'Thu 12 Nov', [trusted HTML item, ...])] as rows with a date badge."""
    rows, n = [], 0
    for d, items in days:
        parts = d.split()
        badge = f'<div class="day"><b>{esc(parts[1] if len(parts) > 1 else d)}</b><span>{esc(parts[2] if len(parts) > 2 else "")}</span></div>'
        for x in items:
            if limit is not None and n >= limit:
                break
            rows.append(f'<div class="ds-ev">{badge}<div class="who">{x}</div></div>')
            n += 1
    if rows:
        _target().html('<div class="ds-rows">' + ''.join(rows) + '</div>')
