"""The model basket against the index (Altair, which ships with Streamlit). The company price chart is
ui/lwchart.py (TradingView Lightweight Charts, 22 Oct). The Company page's small charts are HTML, below."""
from __future__ import annotations

from typing import Callable

import altair as alt
import pandas as pd

from ui.kit import _finite, esc, rupees
from ui.theme import C

INK, INK3, LINE = C['ink'], C['ink-3'], C['line']   # ui/theme.py
BUY, SELL, PRICE = C['buy'], C['sell'], C['accent']


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


# ---- Company page, at a glance (owner, 19 Nov 2026: "not glance-worthy to take even a decision"). Small charts drawn as
# HTML and inline SVG, not Altair: they follow the column's width on a 390 px phone with no horizontal scroll, use the
# page's own font and take their colours from ui/theme.py through the stylesheet's tokens (ui/look.css, .cg-*). Each
# returns '' when there is nothing to draw, so the page says what is missing instead.

OWN_TOKEN = {'Promoter': 'own-promoter', 'Mutual funds': 'own-mf', 'Insurance': 'own-insurance', 'FPI': 'own-fpi',
             'Other DII': 'own-dii', 'Retail': 'own-retail', 'Others': 'own-others'}
OWN_NOTE = {'Other DII': 'banks, AIFs, pension and other domestic institutions', 'Retail': 'resident individuals, HNIs included',
            'Others': 'bodies corporate, foreign direct, government, NRIs, trusts'}
DARK = ('Promoter', 'Mutual funds', 'FPI')   # segments whose figure is written in white


def ownership_stack(mix: pd.DataFrame | None, order: list[str]) -> str:
    """One 100% bar per quarter (newest on top), a segment per ownership group with its share written inside when wide
    enough, and a legend with each group's latest share. `mix`: quarter, group, pct (company_glance.ownership_mix)."""
    if mix is None or mix.empty:
        return ''
    qs = sorted(mix['quarter'].unique(), reverse=True)
    last = mix[mix['quarter'] == qs[0]].set_index('group')['pct']
    legend = ''.join(f'<span class="cg-key" title="{esc(OWN_NOTE.get(g, g), quote=True)}"><i style="background:var(--{OWN_TOKEN[g]})"></i>'
                     f'{esc(g)} <b class="num">{last[g]:.1f}%</b></span>' for g in order if g in last.index)
    rows = []
    for q in qs:
        x = mix[mix['quarter'] == q].set_index('group')['pct']
        segs = ''.join(f'<i class="{"dk" if g in DARK else ""}" style="width:{max(x[g], 0):.3f}%;background:var(--{OWN_TOKEN[g]})" '
                       f'title="{esc(g, quote=True)} {x[g]:.2f}%">{f"{x[g]:.0f}" if x[g] >= 7 else ""}</i>'
                       for g in order if g in x.index)
        rows.append(f'<div class="cg-srow"><span class="cg-q">{pd.Timestamp(q):%b %y}</span><div class="cg-sbar">{segs}</div></div>')
    return f'<div class="cg-legend">{legend}</div><div class="cg-stack">{"".join(rows)}</div>'


def delta_bars(rows: list[tuple[str, float, str]], unit: str = 'pts', floor: float = 0.0,
               fmt: Callable[[float], str] | None = None) -> str:
    """Diverging bars: (label, value, note) per row, a rise to the right in green, a fall to the left in red, the value
    written at the end; a change under `floor` in size is grey (steady). `fmt` writes the value (default: +0.43 pts)."""
    rows = [(a, float(v), n) for a, v, n in rows if _finite(v) is not None]
    if not rows:
        return ''
    top = max(abs(v) for _, v, _ in rows) or 1.0
    out = []
    for label, v, note in rows:
        tone = 'flat' if abs(v) < floor or v == 0 else 'up' if v > 0 else 'down'
        side = 'left' if v >= 0 else 'right'
        text = fmt(v) if fmt else f'{v:+.2f}' + (f' {unit}' if unit else '')
        out.append(f'<div class="cg-drow"><span class="cg-dl">{esc(label)}' + (f'<em>{esc(note)}</em>' if note else '') + '</span>'
                   f'<span class="cg-dtrack"><i class="{tone}" style="{side}:50%;width:{abs(v) / top * 50:.2f}%"></i></span>'
                   f'<span class="cg-dv num {tone}">{esc(text)}</span></div>')
    return '<div class="cg-delta">' + ''.join(out) + '</div>'


def split_bar(buy, sell, fmt: Callable[[float], str] = rupees, what: tuple[str, str] = ('Bought', 'Sold')) -> str:
    """Bought against sold as one bar, green from the left and red to the right, each total and its share written above.
    '' when neither side has a value."""
    b, s = max(_finite(buy) or 0.0, 0.0), max(_finite(sell) or 0.0, 0.0)
    if b + s <= 0:
        return ''
    pb = b / (b + s) * 100
    return (f'<div class="cg-split"><div class="cg-splab"><span class="up">{esc(what[0])} <b class="num">{esc(fmt(b))}</b> · {pb:.0f}%</span>'
            f'<span class="down">{esc(what[1])} <b class="num">{esc(fmt(s))}</b> · {100 - pb:.0f}%</span></div>'
            f'<div class="cg-spbar"><i class="up" style="width:{pb:.2f}%"></i><i class="down" style="width:{100 - pb:.2f}%"></i></div></div>')


def spark(values: list, w: int = 120, h: int = 34, tone: str = 'flat') -> str:
    """A small line of `values` (oldest first) with a dot on the last value."""
    v = [float(x) for x in values if _finite(x) is not None]
    if not v:
        return ''
    lo, hi = min(v), max(v)
    span = (hi - lo) or 1.0
    n = len(v)
    xs = [w / 2] if n == 1 else [3 + i * (w - 6) / (n - 1) for i in range(n)]
    ys = [h / 2 if hi == lo else h - 4 - (x - lo) / span * (h - 8) for x in v]
    line = ' '.join(f'{x:.1f},{y:.1f}' for x, y in zip(xs, ys))
    return (f'<svg class="cg-spark {tone}" viewBox="0 0 {w} {h}" width="{w}" height="{h}" aria-hidden="true">'
            + (f'<polyline points="{line}" fill="none" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"/>' if n > 1 else '')
            + f'<circle cx="{xs[-1]:.1f}" cy="{ys[-1]:.1f}" r="2.6"/></svg>')


def columns(items: list[dict], fmt: Callable[[float], str] = rupees) -> str:
    """Vertical bars, one per item {'label', 'value', 'top' (the figure over the bar, default fmt(value)), 'sub' (a line
    under the label, e.g. year on year), 'sub_tone', 'tone'}, scaled to the largest; a loss hangs under the zero line in
    red. '' when no item has a value."""
    items = [i for i in items if _finite(i.get('value')) is not None]
    if not items:
        return ''
    hi = max(max(float(i['value']) for i in items), 0.0)
    lo = min(min(float(i['value']) for i in items), 0.0)
    span = (hi - lo) or 1.0
    zero = hi / span * 100   # % from the top where zero sits
    out = []
    for i in items:
        v = float(i['value'])
        h = abs(v) / span * 100
        top = zero - h if v >= 0 else zero
        tone = i.get('tone') or ('down' if v < 0 else '')
        sub = (f'<span class="cg-cs {i.get("sub_tone", "")}">{esc(i["sub"])}</span>' if i.get('sub')
               else '<span class="cg-cs">&nbsp;</span>')
        out.append(f'<div class="cg-col" title="{esc(i["label"], quote=True)}: {esc(fmt(v), quote=True)}">'
                   f'<span class="cg-cv num">{esc(i.get("top") or fmt(v))}</span>'
                   f'<div class="cg-cplot"><i class="{tone}" style="top:{top:.2f}%;height:{max(h, 0.8):.2f}%"></i>'
                   f'<b style="top:{zero:.2f}%"></b></div><span class="cg-cl">{esc(i["label"])}</span>{sub}</div>')
    return f'<div class="cg-cols" style="--n:{len(items)}">' + ''.join(out) + '</div>'


def diverging_bars(df: pd.DataFrame, label: str = 'label', value: str = 'net_cr', unit: str = '₹ Cr',
                   limit: int = 24) -> alt.Chart | None:
    """Horizontal bars either side of zero, buying (green) right and selling (red) left, most bought on top: the Funds
    page's net rupees by sector. At most `limit` rows, the largest either way."""
    if df is None or df.empty:
        return None
    d = df.assign(_abs=df[value].abs()).sort_values('_abs', ascending=False).head(limit).sort_values(value, ascending=False)
    d = d.assign(side=d[value].ge(0).map({True: 'Bought', False: 'Sold'})).drop(columns='_abs')
    tips = [alt.Tooltip(f'{label}:N', title='Group'), alt.Tooltip(f'{value}:Q', title=f'Net, {unit}', format=',.1f')]
    if 'stocks' in d:
        tips.append(alt.Tooltip('stocks:Q', title='Stocks'))
    bars = alt.Chart(d).mark_bar(cornerRadius=2).encode(
        y=alt.Y(f'{label}:N', sort=d[label].tolist(), title=None,
                axis=alt.Axis(labelColor=INK, labelLimit=200, ticks=False, domain=False, labelOverlap=False)),
        x=alt.X(f'{value}:Q', title=unit, axis=alt.Axis(format=',.0f', gridColor=LINE, labelColor=INK3, titleColor=INK3,
                                                         domain=False, tickCount=5)),
        color=alt.Color('side:N', scale=alt.Scale(domain=['Bought', 'Sold'], range=[BUY, SELL]), legend=None),
        tooltip=tips)
    zero = alt.Chart(pd.DataFrame({'x': [0]})).mark_rule(color=INK3, strokeWidth=1).encode(x='x:Q')
    return (bars + zero).properties(height=max(120, 24 * len(d))).configure_view(stroke=None)


def heatmap(df: pd.DataFrame, x: str = 'month_label', y: str = 'house', value: str = 'flow_pct', cap: float = 5.0,
            x_order: list | None = None) -> alt.Chart | None:
    """A grid of one value per row and column, selling red through a neutral grey to buying green, clipped at ±`cap`
    (the tooltip keeps the true value): the Funds page's house × month net buying as a % of the house's equity."""
    if df is None or df.empty:
        return None
    d = df.dropna(subset=[value])
    if d.empty:
        return None
    rows = d[y].nunique()
    return alt.Chart(d).mark_rect(cornerRadius=2).encode(
        x=alt.X(f'{x}:O', title=None, sort=x_order, axis=alt.Axis(labelColor=INK3, labelAngle=0, ticks=False, domain=False)),
        y=alt.Y(f'{y}:N', title=None, sort='ascending', axis=alt.Axis(labelColor=INK, labelLimit=220, ticks=False, domain=False)),
        color=alt.Color(f'{value}:Q', scale=alt.Scale(domain=[-cap, 0, cap], range=[SELL, C['range-mid'], BUY], clamp=True),
                        legend=alt.Legend(title='% of equity', orient='top', labelColor=INK3, titleColor=INK3)),
        tooltip=[alt.Tooltip(f'{y}:N', title='House'), alt.Tooltip(f'{x}:O', title='Month'),
                 alt.Tooltip(f'{value}:Q', title='Net bought, % of equity', format='+.2f')],
    ).properties(height=max(120, 20 * rows)).configure_view(stroke=None)
