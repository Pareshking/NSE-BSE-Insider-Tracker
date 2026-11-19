"""Small charts, drawn with the theme's colours only (ui/theme.py). The company price chart is ui/lwchart.py (TradingView
Lightweight Charts, 22 Oct); the model basket against the index and the Funds page's sector bars and heatmap are Altair
(which ships with Streamlit); the Company page's at-a-glance charts are HTML (ownership_stack, delta_bars,
split_bar, spark, columns), so they follow a 390 px phone's width with no horizontal scroll.

Bought or sold at a glance (owner, 19 Nov 2026, on the People & funds page on a phone: "Not even pages have visualization to
understand bought or sold"): diverging_bar and buy_sell_split take a page's table and draw it with delta_bars and split_bar;
holding_trend, count_strip and change_rows add the quarter trend, the counts and a dense change list. Each returns a chart
or HTML for good data and None or '' for nothing to draw, so a section waits for its data.
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
LABEL_CHARS = 26   # a name cut to leave room for its value on a 390 px phone


def _finish(chart, height: int):
    """One look for every chart here: the site's font, no frame, transparent on the page."""
    return (chart.properties(height=height, width='container')
            .configure(font=FONT, background='transparent')
            .configure_view(strokeWidth=0)
            .configure_axis(labelColor=INK3, labelFontSize=12, domain=False, ticks=False, grid=False, title=None))


def _short(s, n: int = LABEL_CHARS) -> str:
    s = ' '.join(str(s).split())
    return s if len(s) <= n else s[:n - 1].rstrip() + '…'


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
                  tag: str | None = None, limit: int = 15) -> str:
    """A page's table as delta_bars: added (green, right of zero) against cut (red, left of zero), largest added at the
    top and largest cut at the bottom, each value written at the end. `fmt` writes the value (points by default; pass
    lambda v: rupees(v, signed=True) for rupees); `tag` names a column whose text goes under the name ("new: crossed 1%",
    "MF"). Rows with no value or a zero change are left out (nothing to draw); the `limit` largest either way are kept.
    HTML for st.html; '' when there is nothing to draw."""
    if df is None or df.empty or label not in df or value not in df:
        return ''
    d = pd.DataFrame({'_l': df[label].astype(str), '_v': pd.to_numeric(df[value], errors='coerce'),
                      '_g': df[tag].fillna('').astype(str) if tag and tag in df else ''})
    d = d[d['_v'].notna() & d['_v'].ne(0)]
    if d.empty:
        return ''
    d = d.loc[d['_v'].abs().sort_values(ascending=False, kind='stable').index[:limit]]
    d = d.sort_values('_v', ascending=False, kind='stable')
    html = delta_bars([(_short(lab), v, g) for lab, v, g in zip(d['_l'], d['_v'], d['_g'])], fmt=fmt)
    # 'wide': on a phone the name and value share a line and the bar runs the full width under them (ui/look.css)
    return html.replace('<div class="cg-delta">', '<div class="cg-delta wide">', 1)


def buy_sell_split(buy, sell, fmt: Callable[[float], str] = rupees) -> str:
    """Bought against sold as one bar with both totals and shares (split_bar). '' when neither side has a value."""
    return split_bar(buy, sell, fmt=fmt)


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
            c = f'<span class="{"up" if chg > 0 else "down"}">{"▲" if chg > 0 else "▼"} {abs(chg):.2f}</span><em class="u">pts</em>'
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


def spark(values: list, w: int = 120, h: int = 34, tone: str = 'flat', signed: bool = False) -> str:
    """A small run of `values` (oldest first) as HTML columns, the last one strong: plain HTML, so it draws in st.html
    (whose sanitiser drops SVG) as well as in st.markdown. Plain: columns from the bottom, scaled from the lowest value
    to the highest (the lowest still shows), the last in `tone` ('up', 'down', 'flat'). `signed`: columns above and
    below a zero line, green for a positive value and red for a negative one (a flow). A missing value keeps its slot
    empty. '' with no value. Colours are in ui/look.css; only positions are written here."""
    vals = [_finite(x) for x in values]
    real = [x for x in vals if x is not None]
    if not real:
        return ''
    n = len(vals)
    wd = 100 / n
    if signed:
        lo, hi = min(real + [0.0]), max(real + [0.0])
        zero = hi / ((hi - lo) or 1.0) * 100   # % from the top
    else:
        lo, hi = min(real), max(real)
    span = (hi - lo) or 1.0
    cols = []
    for i, v in enumerate(vals):
        if v is None:
            continue
        if signed:
            ht = max(abs(v) / span * 100, 3.0)
            top = max(zero - ht if v >= 0 else zero, 0.0)
            cls = 'p' if v >= 0 else 'n'
        else:
            ht = 100.0 if hi == lo else 15 + (v - lo) / span * 85
            top = 100 - ht
            cls = 'q'
        cols.append(f'<i class="{cls}{" last" if i == n - 1 else ""}" style="left:{i * wd + wd * 0.15:.2f}%;width:{wd * 0.7:.2f}%;'
                    f'top:{top:.2f}%;height:{ht:.2f}%"></i>')
    axis = f'<i class="z" style="top:{zero:.2f}%"></i>' if signed else ''
    return (f'<span class="cg-spark {tone}{" signed" if signed else ""}" style="--w:{w}px;--h:{h}px" aria-hidden="true">'
            f'{axis}{"".join(cols)}</span>')


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
