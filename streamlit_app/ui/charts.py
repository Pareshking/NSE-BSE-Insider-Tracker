"""The model basket against the index (Altair, which ships with Streamlit). The company price chart is
ui/lwchart.py (TradingView Lightweight Charts, 22 Oct)."""
from __future__ import annotations

import altair as alt
import pandas as pd

INK, INK3, LINE = '#0E1726', '#5E6878', '#E3E6EB'
BUY, SELL, PRICE = '#067647', '#B42318', '#4F46E5'


def basket_vs_index(nav: pd.DataFrame) -> alt.Chart | None:
    """Model basket and Nifty 500, both 100 at the first entry (artifacts/basket_nav.parquet)."""
    if nav is None or nav.empty:
        return None
    long = nav.melt(id_vars='date', value_vars=['basket', 'index'], var_name='line', value_name='value')
    long['line'] = long['line'].map({'basket': 'Model basket', 'index': 'Nifty 500'})
    return alt.Chart(long).mark_line(strokeWidth=2).encode(
        x=alt.X('date:T', title=None, axis=alt.Axis(format='%d %b %y', grid=False, tickCount=6, labelColor=INK3)),
        y=alt.Y('value:Q', title=None, scale=alt.Scale(zero=False),
                axis=alt.Axis(format=',.0f', gridColor='#F0F2F5', labelColor=INK3, domain=False, tickCount=5)),
        color=alt.Color('line:N', scale=alt.Scale(domain=['Model basket', 'Nifty 500'], range=[PRICE, INK3]),
                        legend=alt.Legend(title=None, orient='top-left', labelColor=INK3)),
        tooltip=[alt.Tooltip('date:T', title='Date', format='%d %b %Y'), 'line:N', alt.Tooltip('value:Q', format=',.1f')],
    ).properties(height=220)
