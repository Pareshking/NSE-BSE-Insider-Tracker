"""Design-system components (redesign of 12 Nov 2026). Each returns HTML for st.html, or draws it, in the classes of
ui/ds.css; colours and sizes come from ui/theme.py. A page is: head(), stats(), then section()s of stories(), lists()
and club() (what was left out as noise, counted), so every page reads the same way.

A story answers 5W-2H with the arithmetic done: who, what, when (traded, made public, how many days between), where
(market and exchange), how (mode), how much (rupees, % of the company, % of the person's own holding), price (paid,
now, the move), why it matters (the measured record or the rule it passed), and what to watch (pledge, 52-week,
surveillance flags, a late filing)."""
from __future__ import annotations

from dataclasses import dataclass, field

import streamlit as st

from ui.kit import esc

W_LABELS = {'who': 'Who', 'what': 'What', 'when': 'When', 'where': 'Where', 'how': 'How', 'much': 'How much',
            'price': 'Price', 'why': 'Why it matters', 'watch': 'Watch'}


@dataclass
class Story:
    company: str
    href: str = ''
    market: str = ''                 # trusted HTML: symbol · size · market cap · price
    lede: str = ''                   # one sentence, the news
    big: str = ''                    # the headline number (₹ value), right
    big_sub: str = ''                # under it (% of the company)
    w: dict = field(default_factory=dict)        # key in W_LABELS -> text
    warn: set = field(default_factory=set)       # keys drawn amber
    tags: list = field(default_factory=list)     # (text, tone) tone in '', 'ok', 'warn', 'new'


def head(kicker: str, title_html: str, dek: list[str] | None = None) -> None:
    """The masthead. `title_html` is trusted HTML (numbers in <b>); the kicker may hold trusted HTML too."""
    st.html(f'<div class="head ds-head"><div class="ds-kicker">{kicker}</div><h1>{title_html}</h1>'
            + ''.join(f'<p class="ds-dek">{esc(x)}</p>' for x in (dek or []) if x) + '</div>')


def stats(cells: list[tuple]) -> None:
    """(label, value, note[, tone[, href]]) per cell."""
    out = []
    for c in cells:
        k, v, s = c[0], c[1], c[2]
        tone = c[3] if len(c) > 3 else ''
        href = c[4] if len(c) > 4 else ''
        inner = f'<span class="k">{esc(k)}</span><b class="{tone}">{esc(str(v))}</b><span class="s">{esc(s)}</span>'
        link = '<a href="' + esc(href, quote=True) + '" target="_self">' + inner + '</a>' if href else inner
        out.append(f'<div>{link}</div>')
    st.html('<div class="ds-stats">' + ''.join(out) + '</div>')


def section(title: str, sub: str = '', href: str = '', link: str = '') -> None:
    a = f'<a class="all" href="{esc(href, quote=True)}" target="_self">{esc(link or "See all")} →</a>' if href else ''
    st.html(f'<div class="ds-sec"><h2>{esc(title)}</h2>{a}' + (f'<p>{esc(sub)}</p>' if sub else '') + '</div>')


def sub(title: str, note: str = '') -> str:
    return f'<div class="ds-sub">{esc(title)}' + (f'<span>{esc(note)}</span>' if note else '') + '</div>'


def tag(text: str, tone: str = '') -> str:
    return f'<span class="ds-tag {tone}">{esc(text)}</span>'


def story_html(s: Story) -> str:
    tags = ''.join(tag(t, tone) for t, tone in s.tags)
    rows = ''.join(f'<dt>{esc(W_LABELS[k])}</dt><dd class="{"warn" if k in s.warn else ""}">{esc(v)}</dd>'
                   for k, v in ((k, s.w.get(k)) for k in W_LABELS) if v)
    name = (f'<a class="co" href="{esc(s.href, quote=True)}" target="_self">{esc(s.company)}</a>' if s.href else f'<b>{esc(s.company)}</b>')
    big = (f'<div class="ds-big"><b>{esc(s.big)}</b><span>{esc(s.big_sub)}</span></div>' if s.big or s.big_sub else '')
    return (f'<article class="ds-story"><div class="ds-story-h"><div>{name} {tags}<div class="mk">{s.market}</div></div>{big}</div>'
            + (f'<p class="ds-lede">{esc(s.lede)}</p>' if s.lede else '') + f'<dl class="ds-w">{rows}</dl></article>')


def stories(items: list[Story], empty: str = '') -> None:
    if not items:
        if empty:
            st.html(f'<p class="ds-empty">{esc(empty)}</p>')
        return
    st.html('<div class="ds-stories">' + ''.join(story_html(s) for s in items) + '</div>')


def record(html: str) -> None:
    """The measured record once, above the stories it is about (trusted HTML)."""
    if html:
        st.html(f'<div class="ds-rec">{html}</div>')


def empty(text: str) -> None:
    st.html(f'<p class="ds-empty">{esc(text)}</p>')


@dataclass
class Col:
    key: str
    label: str
    right: bool = False
    phone: bool = True


def list_html(rows: list[dict], cols: list[Col]) -> str:
    """A dense list. Each cell value is trusted HTML built by the caller (escape names with esc)."""
    head = ''.join(f'<th class="{"r" if c.right else ""}{"" if c.phone else " opt"}">{esc(c.label)}</th>' for c in cols)
    body = ''.join('<tr>' + ''.join(f'<td class="{"r" if c.right else ""}{"" if c.phone else " opt"}">{r.get(c.key, "") or ""}</td>'
                                    for c in cols) + '</tr>' for r in rows)
    return f'<div class="ds-wrap"><table class="ds-list"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def club(title: str, lines: list[str]) -> None:
    """What was left out as noise, each line trusted HTML with its count and sum (owner, 12 Nov: club what is not worth
    showing, e.g. staff selling 0.001% of a company)."""
    lines = [x for x in lines if x]
    if lines:
        st.html(f'<div class="ds-club"><h4>{esc(title)}</h4><ul>' + ''.join(f'<li>{x}</li>' for x in lines) + '</ul></div>')


def calendar(days: list[tuple[str, list[str]]]) -> None:
    """[(day label, [trusted HTML item, ...])]."""
    if days:
        cols = []
        for d, items in days:
            lis = ''.join('<li>' + x + '</li>' for x in items)
            cols.append(f'<div><h4>{esc(d)}</h4><ul>{lis}</ul></div>')
        st.html('<div class="ds-cal">' + ''.join(cols) + '</div>')
