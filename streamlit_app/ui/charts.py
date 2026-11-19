"""The model basket against the index (Altair, which ships with Streamlit). The company price chart is
ui/lwchart.py (TradingView Lightweight Charts, 22 Oct)."""
from __future__ import annotations

import altair as alt
import pandas as pd

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
                axis=alt.Axis(labelColor=INK, labelLimit=200, ticks=False, domain=False)),
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
