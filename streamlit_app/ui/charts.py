"""Small charts, in Altair (which ships with Streamlit), drawn with the theme's colours only (ui/theme.py). The company
price chart is ui/lwchart.py (TradingView Lightweight Charts, 22 Oct).

Bought vs sold at a glance (owner, 19 Nov 2026, on the People & funds page on a phone: "Not even pages have visualization to
understand bought or sold"). Each builder returns a chart (or, for the counts, a line of HTML) for good data and None (or '')
for nothing to draw, so a page draws a section only when its data is in. Sized for a 390 px phone: values written on the
marks, no legend, no axis where the labels already say it, no grid.
"""
from __future__ import annotations

from typing import Callable

import altair as alt
import pandas as pd

from ui.kit import _finite, company_href, esc, pct, rupees
from ui.theme import C

INK, INK2, INK3, INK4, LINE = C['ink'], C['ink-2'], C['ink-3'], C['ink-4'], C['line']   # ui/theme.py
BUY, SELL, PRICE = C['buy'], C['sell'], C['accent']
FONT = C['ui'].split(',')[0].strip("' ")
ROW = 36           # px per row of a bar chart: a line of text over a thin bar
LABEL_CHARS = 30   # a name cut to leave room for its value on a 390 px phone


def _finish(chart, height: int):
    """One look for every chart here: the site's font, no frame, transparent on the page."""
    return (chart.properties(height=height, width='container')
            .configure(font=FONT, background='transparent')
            .configure_view(strokeWidth=0)
            .configure_axis(labelColor=INK3, labelFontSize=12, domain=False, ticks=False, grid=False, title=None))


def _short(s, n: int = LABEL_CHARS) -> str:
    s = ' '.join(str(s).split())
    return s if len(s) <= n else s[:n - 1].rstrip() + '…'


def _unique(labels: list[str]) -> list[str]:
    """A label seen twice (two holders in one company) gets a counter, so each bar keeps its own row."""
    seen: dict[str, int] = {}
    out = []
    for x in labels:
        seen[x] = seen.get(x, 0) + 1
        out.append(x if seen[x] == 1 else f'{x} ({seen[x]})')
    return out


def pts(v) -> str:
    """A change in points of the company: +0.42 pts, -1.09 pts."""
    return f'{v:+.2f} pts'


def basket_vs_index(nav: pd.DataFrame) -> alt.Chart | None:
    """Model basket and Nifty 500, both 100 at the first entry (artifacts/basket_nav.parquet)."""
    if nav is None or nav.empty:
        return None
    long = nav.melt(id_vars='date', value_vars=['basket', 'index'], var_name='line', value_name='value')
    long['line'] = long['line'].map({'basket': 'Model basket', 'index': 'Nifty 500'})
    return alt.Chart(long).mark_line(strokeWidth=2).encode(
        x=alt.X('date:T', title=None, axis=alt.Axis(format='%d %b %y', grid=False, tickCount=6, labelColor=INK3)),
        y=alt.Y('value:Q', title=None, scale=alt.Scale(zero=False),
                axis=alt.Axis(format=',.0f', gridColor=LINE, labelColor=INK3, domain=False, tickCount=5)),
        color=alt.Color('line:N', scale=alt.Scale(domain=['Model basket', 'Nifty 500'], range=[PRICE, INK3]),
                        legend=alt.Legend(title=None, orient='top-left', labelColor=INK3)),
        tooltip=[alt.Tooltip('date:T', title='Date', format='%d %b %Y'), 'line:N', alt.Tooltip('value:Q', format=',.1f')],
    ).properties(height=220)


def diverging_bar(df: pd.DataFrame | None, label: str, value: str, fmt: Callable[[float], str] = pts,
                  tag: str | None = None, limit: int = 15) -> alt.Chart | None:
    """Added (green, right of zero) against cut (red, left of zero), one bar per row, largest added at the top and
    largest cut at the bottom; each row's name and value on a line over its bar. `fmt` writes the value (points by default; pass
    lambda v: rupees(v, signed=True) for rupees); `tag` names a column whose text follows the value ("new", "exited").
    Rows with no value or a zero change are left out (nothing to draw); the `limit` largest either way are kept."""
    if df is None or df.empty or label not in df or value not in df:
        return None
    d = pd.DataFrame({'_l': df[label].astype(str), '_v': pd.to_numeric(df[value], errors='coerce'),
                      '_g': df[tag].fillna('').astype(str) if tag and tag in df else ''})
    d = d[d['_v'].notna() & d['_v'].ne(0)]
    if d.empty:
        return None
    d = d.loc[d['_v'].abs().sort_values(ascending=False, kind='stable').index[:limit]]
    d = d.sort_values('_v', ascending=False, kind='stable').reset_index(drop=True)
    d['_l'] = _unique([_short(x) for x in d['_l']])
    d['_t'] = [fmt(v) + (f' {g}' if g else '') for v, g in zip(d['_v'], d['_g'])]
    d['_tone'] = d['_v'].map(lambda v: 'up' if v > 0 else 'down')
    lo, hi = min(d['_v'].min(), 0.0), max(d['_v'].max(), 0.0)
    span = (hi - lo) or 1.0
    dom = [lo - 0.01 * span, hi + 0.01 * span]
    # Each row: the name on the left and the value on the right, on one line, the bar under them from the zero line. The
    # bars have the full width and no text sits beside them, so nothing collides on a 390 px phone.
    x = alt.X('_v:Q', scale=alt.Scale(domain=dom, nice=False), axis=None)
    y = alt.Y('_l:N', sort=list(d['_l']), axis=None, scale=alt.Scale(paddingInner=0, paddingOuter=0))
    tone = alt.Color('_tone:N', scale=alt.Scale(domain=['up', 'down'], range=[BUY, SELL]), legend=None)
    tip = [alt.Tooltip('_l:N', title='Name'), alt.Tooltip('_t:N', title='Change')]
    base = alt.Chart(d).encode(y=y)
    bars = base.mark_bar(height=8, yOffset=8, cornerRadius=2).encode(x=x, x2=alt.datum(0), color=tone, tooltip=tip)
    zero = base.mark_tick(color=INK4, thickness=1, size=14, yOffset=8).encode(x=alt.datum(0))
    name = base.mark_text(align='left', baseline='middle', dy=-7, x=0, fontSize=12.5, color=INK).encode(text='_l:N', tooltip=tip)
    val = base.mark_text(align='right', baseline='middle', dy=-7, x='width', fontSize=12.5, fontWeight=600).encode(
        text='_t:N', color=tone)
    return _finish(alt.layer(bars, zero, name, val), ROW * len(d))


def buy_sell_split(buy, sell, fmt: Callable[[float], str] = rupees) -> alt.Chart | None:
    """One horizontal bar: bought (green, from the left) and sold (red, to the right), each total written over its end
    with its share of the two. None when neither side has a value."""
    b, s = max(_finite(buy) or 0.0, 0.0), max(_finite(sell) or 0.0, 0.0)
    total = b + s
    if total <= 0:
        return None
    seg = pd.DataFrame({'side': ['Bought', 'Sold'], 'a': [0.0, b], 'b': [b, total], 'v': [b, s]})
    seg = seg[seg['v'] > 0]
    lab = pd.DataFrame({'x': [0.0, total], 'align': ['left', 'right'], 'tone': ['up', 'down'],
                        't': [f'Bought {fmt(b)} · {b / total * 100:.0f}%', f'Sold {fmt(s)} · {s / total * 100:.0f}%']})
    xs = alt.Scale(domain=[0, total], nice=False)
    color = alt.Color('side:N', scale=alt.Scale(domain=['Bought', 'Sold'], range=[BUY, SELL]), legend=None)
    bar = alt.Chart(seg).mark_bar(height=14, cornerRadius=2).encode(
        x=alt.X('a:Q', scale=xs, axis=None), x2='b:Q', y=alt.value(34), color=color,
        tooltip=[alt.Tooltip('side:N', title='Side'), alt.Tooltip('v:Q', title='₹', format=',.0f')])
    tone = alt.Color('tone:N', scale=alt.Scale(domain=['up', 'down'], range=[BUY, SELL]), legend=None)
    left = alt.Chart(lab.iloc[[0]]).mark_text(align='left', baseline='bottom', fontSize=13, fontWeight=600).encode(
        x=alt.X('x:Q', scale=xs, axis=None), y=alt.value(22), text='t:N', color=tone)
    right = alt.Chart(lab.iloc[[1]]).mark_text(align='right', baseline='bottom', fontSize=13, fontWeight=600).encode(
        x=alt.X('x:Q', scale=xs, axis=None), y=alt.value(22), text='t:N', color=tone)
    return _finish(alt.layer(bar, left, right), 44)


def holding_trend(df: pd.DataFrame | None, label: str = 'company', when: str = 'quarter_end', value: str = 'pct_of_company',
                  columns: int = 2, limit: int = 8) -> alt.Chart | None:
    """% of the company held at each quarter we have, one small panel per company (`label`), each point written with its
    value; the line green when the holding rose from the first quarter shown to the last, red when it fell. A quarter
    with no point is one where the holder was not named (under 1%) or the company's list is not in. One company: one
    panel, 320 px. None when there is nothing to draw."""
    if df is None or df.empty or not {label, when, value} <= set(df.columns):
        return None
    d = pd.DataFrame({'_l': df[label].astype(str), '_d': pd.to_datetime(df[when], errors='coerce'),
                      '_v': pd.to_numeric(df[value], errors='coerce')}).dropna()
    if d.empty:
        return None
    d = d.groupby(['_l', '_d'], as_index=False)['_v'].sum().sort_values(['_l', '_d'])
    order = d.sort_values('_d').groupby('_l')['_v'].last().sort_values(ascending=False).index[:limit]
    d = d[d['_l'].isin(order)].copy()
    first, last = d.groupby('_l')['_v'].transform('first'), d.groupby('_l')['_v'].transform('last')
    d['_tone'] = ['up' if b > a else 'down' if b < a else 'flat' for a, b in zip(first, last)]
    d['_q'] = d['_d'].dt.strftime('%b %y')
    d['_t'] = [pct(v, 2) for v in d['_v']]
    d['_s'] = [_short(x, 30) for x in d['_l']]
    quarters = list(dict.fromkeys(d.sort_values('_d')['_q']))
    names = list(dict.fromkeys(_short(x, 30) for x in order))
    color = alt.Color('_tone:N', scale=alt.Scale(domain=['up', 'down', 'flat'], range=[BUY, SELL, INK3]), legend=None)
    x = alt.X('_q:O', sort=quarters, axis=alt.Axis(labelAngle=0, labelColor=INK3, labelPadding=4))
    y = alt.Y('_v:Q', scale=alt.Scale(zero=False, padding=16), axis=None)
    base = alt.Chart().encode(x=x, y=y)
    layer = alt.layer(base.mark_line(strokeWidth=2).encode(color=color),
                      base.mark_point(filled=True, size=40).encode(color=color,
                                                                     tooltip=[alt.Tooltip('_s:N', title='Company'),
                                                                              alt.Tooltip('_q:N', title='Quarter'),
                                                                              alt.Tooltip('_t:N', title='Held')]),
                      base.mark_text(dy=-11, fontSize=11.5, color=INK).encode(text='_t:N'), data=d)
    if len(names) == 1:
        return (_finish(layer.properties(title=alt.TitleParams(names[0], anchor='start', fontSize=12.5, color=INK, fontWeight=600)), 110)
                .properties(width=320))   # a fixed width: the page draws trends at their own size (width='content')
    w = 150
    chart = (layer.properties(width=w, height=86)
             .facet(facet=alt.Facet('_s:N', sort=names, title=None,
                                    header=alt.Header(labelColor=INK, labelFontSize=12.5, labelFontWeight=600,
                                                      labelAnchor='start', labelLimit=w, labelPadding=2)),
                    columns=columns, spacing={'row': 14, 'column': 18})
             .resolve_scale(y='independent'))
    return (chart.configure(font=FONT, background='transparent').configure_view(strokeWidth=0)
            .configure_axis(labelColor=INK3, labelFontSize=11.5, domain=False, ticks=False, grid=False, title=None))


def count_strip(added=None, cut=None, new=None, exited=None) -> str:
    """A compact line of counts: ▲ added, ▼ cut, new (crossed 1%), exited (dropped below 1%). HTML for st.html; '' when
    no count is known. A count of zero is shown: it is a fact."""
    cells = [(added, '▲', 'added', 'up'), (cut, '▼', 'cut', 'down'), (new, '+', 'new, crossed 1%', 'up'),
             (exited, '−', 'exited, under 1%', 'down')]
    cells = [(int(n), m, w, t) for n, m, w, t in cells if _finite(n) is not None]
    if not cells:
        return ''
    return '<div class="cstrip">' + ''.join(
        f'<span class="cs {t if n else "zero"}"><b>{m} {n:,}</b> {esc(w)}</span>' for n, m, w, t in cells) + '</div>'


def change_rows(rows: pd.DataFrame | None, company: str = 'company', symbol: str = 'symbol', now: str = 'pct_of_company',
                change: str = 'pct_change', status: str = 'change', sub: str = '', limit: int = 100) -> str:
    """A dense list instead of tall cards on a phone: one line per company (name linked to its page, symbol under it), the
    % of the company held now (`sub`: a muted note after the symbol), and the change in points with a coloured ▲ / ▼; "new" when it crossed 1%, "exited" when it
    left the list. HTML for st.html; '' when there are no rows."""
    if rows is None or rows.empty:
        return ''
    out = []
    for r in rows.head(limit).to_dict('records'):
        sym = str(r.get(symbol) or '')
        note = r.get(sub) if sub else None
        note = f' · {esc(str(note))}' if isinstance(note, str) and note else ''
        name = str(r.get(company) or sym)
        st_ = r.get(status)
        held = _finite(r.get(now))
        chg = _finite(r.get(change))
        if st_ == 'new':
            c = f'<span class="up">+ new</span><em>crossed 1%</em>'
        elif st_ == 'exited':
            c = '<span class="down">− exited</span><em>under 1%</em>'
        elif chg is not None and chg != 0:
            c = f'<span class="{"up" if chg > 0 else "down"}">{"▲" if chg > 0 else "▼"} {abs(chg):.2f}</span><em>pts</em>'
        elif st_ in ('same', 'added', 'cut'):
            c = '<span class="na">unchanged</span>'
        else:
            c = '<span class="na">—</span><em>one quarter</em>'
        out.append(f'<div class="cr"><div class="cr-n"><a href="{esc(company_href(sym), quote=True)}" target="_self">{esc(name)}</a>'
                   f'<span class="cr-s"><span class="sym">{esc(sym)}</span>{note}</span></div>'
                   f'<div class="cr-p num">{pct(held, 2) if held is not None and st_ != "exited" else "—"}</div>'
                   f'<div class="cr-c num">{c}</div></div>')
    more = len(rows) - min(len(rows), limit)
    head = '<div class="cr cr-h"><div>Company</div><div>% held</div><div>Change, pts</div></div>'
    return '<div class="crows">' + head + ''.join(out) + '</div>' + (f'<p class="tbl-cap">Top {limit:,} of {len(rows):,}</p>' if more else '')
