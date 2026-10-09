"""The company price chart: a year of closes with every open-market insider
trade marked on the day it was made public (Altair, which ships with
Streamlit; no extra dependency)."""
from __future__ import annotations

import altair as alt
import pandas as pd

INK, INK3, LINE = '#0E1726', '#5E6878', '#E3E6EB'
BUY, SELL, PRICE = '#067647', '#B42318', '#4F46E5'


def price_with_trades(dates, closes, trades: pd.DataFrame, days: int = 365) -> alt.LayerChart | None:
    """`trades`: rows with seen (date made public), side, value, person_name,
    role. Each trade sits on the close of its broadcast day (or the next
    session), sized by value."""
    px = pd.DataFrame({'date': pd.to_datetime(dates), 'close': closes})
    px = px[px['date'] >= px['date'].max() - pd.Timedelta(days=days)]
    if len(px) < 5:
        return None
    lo, hi = float(px['close'].min()), float(px['close'].max())
    pad = (hi - lo) * 0.08 or hi * 0.05
    scale = alt.Scale(domain=[lo - pad, hi + pad], nice=False, zero=False)
    base = alt.Chart(px).encode(x=alt.X('date:T', title=None, axis=alt.Axis(format='%b %y', grid=False, tickCount=8,
                                                                           labelColor=INK3, domainColor=LINE)))
    area = base.mark_area(color=PRICE, opacity=0.07).encode(y=alt.Y('close:Q', scale=scale), y2=alt.datum(lo - pad))
    line = base.mark_line(color=PRICE, strokeWidth=1.6).encode(
        y=alt.Y('close:Q', title=None, scale=scale,
                axis=alt.Axis(format=',.0f', gridColor='#F0F2F5', labelColor=INK3, domain=False, tickCount=5)),
        tooltip=[alt.Tooltip('date:T', title='Date', format='%d %b %Y'), alt.Tooltip('close:Q', title='Close ₹', format=',.2f')])
    layers = [area, line]
    if trades is not None and not trades.empty:
        t = trades.dropna(subset=['seen']).copy()
        t['seen'] = pd.to_datetime(t['seen']).dt.normalize()
        t = t[(t['seen'] >= px['date'].min()) & (t['seen'] <= px['date'].max())].sort_values('seen')
        if not t.empty:
            t = pd.merge_asof(t, px.rename(columns={'date': 'seen'}).sort_values('seen'), on='seen', direction='forward')
            t['value_cr'] = pd.to_numeric(t['value'], errors='coerce') / 1e7
            t['what'] = t['side'].map({'BUY': 'Bought', 'SELL': 'Sold'})
            dots = alt.Chart(t.dropna(subset=['close'])).mark_point(filled=True, opacity=0.9, stroke='white', strokeWidth=1).encode(
                x='seen:T', y=alt.Y('close:Q', scale=scale),
                shape=alt.Shape('what:N', scale=alt.Scale(domain=['Bought', 'Sold'], range=['triangle-up', 'triangle-down']),
                                legend=alt.Legend(title=None, orient='top-left', labelColor=INK3)),
                color=alt.Color('what:N', scale=alt.Scale(domain=['Bought', 'Sold'], range=[BUY, SELL]), legend=None),
                size=alt.Size('value_cr:Q', scale=alt.Scale(range=[50, 420]), legend=None),
                tooltip=[alt.Tooltip('seen:T', title='Made public', format='%d %b %Y'),
                         alt.Tooltip('person_name:N', title='Who'), alt.Tooltip('role:N', title='Role'),
                         alt.Tooltip('what:N', title='Trade'), alt.Tooltip('value_cr:Q', title='₹ Cr', format=',.2f'),
                         alt.Tooltip('close:Q', title='Close that day ₹', format=',.2f')])
            layers.append(dots)
    return (alt.layer(*layers).properties(height=300)
            .configure(font='Geist').configure_view(strokeWidth=0)
            .configure_axis(labelFontSize=11))
