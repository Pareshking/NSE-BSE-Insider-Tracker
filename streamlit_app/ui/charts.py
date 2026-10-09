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
    area = base.mark_area(color=PRICE, opacity=0.10).encode(y=alt.Y('close:Q', scale=scale), y2=alt.datum(lo - pad))
    line = base.mark_line(color=PRICE, strokeWidth=2).encode(
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
            dots = alt.Chart(t.dropna(subset=['close'])).mark_point(filled=True, opacity=0.9, stroke='white', strokeWidth=2).encode(
                x='seen:T', y=alt.Y('close:Q', scale=scale),
                shape=alt.Shape('what:N', scale=alt.Scale(domain=['Bought', 'Sold'], range=['triangle-up', 'triangle-down']),
                                legend=alt.Legend(title=None, orient='top-left', labelColor=INK3)),
                color=alt.Color('what:N', scale=alt.Scale(domain=['Bought', 'Sold'], range=[BUY, SELL]), legend=None),
                size=alt.Size('value_cr:Q', scale=alt.Scale(range=[110, 520]), legend=None),
                tooltip=[alt.Tooltip('seen:T', title='Made public', format='%d %b %Y'),
                         alt.Tooltip('person_name:N', title='Who'), alt.Tooltip('role:N', title='Role'),
                         alt.Tooltip('what:N', title='Trade'), alt.Tooltip('value_cr:Q', title='₹ Cr', format=',.2f'),
                         alt.Tooltip('close:Q', title='Close that day ₹', format=',.2f')])
            layers.append(dots)
    return (alt.layer(*layers).properties(height=300)
            .configure(font='Geist').configure_view(strokeWidth=0)
            .configure_axis(labelFontSize=11))


def monthly_flow(df: pd.DataFrame, date_col: str, title: str, months: int = 12) -> alt.Chart | None:
    """Buys up, sales down, per month, in Rs crore: one panel, one axis.
    `df` has date_col, side (BUY/SELL) and value in rupees."""
    if df is None or df.empty:
        return None
    x = df[[date_col, 'side', 'value']].copy()
    x['month'] = pd.to_datetime(x[date_col], errors='coerce').dt.to_period('M').dt.to_timestamp()
    x = x.dropna(subset=['month'])
    x = x[x['month'] >= x['month'].max() - pd.DateOffset(months=months - 1)]
    x['cr'] = pd.to_numeric(x['value'], errors='coerce') / 1e7 * x['side'].map({'BUY': 1, 'SELL': -1})
    m = x.groupby(['month', 'side'], as_index=False)['cr'].sum()
    m['what'] = m['side'].map({'BUY': 'Bought', 'SELL': 'Sold'})
    net = m.groupby('month', as_index=False)['cr'].sum()
    bars = alt.Chart(m).mark_bar(cornerRadiusEnd=3, size=14).encode(
        x=alt.X('month:T', title=None, axis=alt.Axis(format='%b', labelColor=INK3, domainColor=LINE, ticks=False, grid=False)),
        y=alt.Y('cr:Q', title=None, axis=alt.Axis(format=',.0f', labelColor=INK3, gridColor='#F0F2F5', domain=False)),
        color=alt.Color('what:N', scale=alt.Scale(domain=['Bought', 'Sold'], range=[BUY, SELL]),
                        legend=alt.Legend(title=None, orient='top', direction='horizontal', labelColor=INK3)),
        tooltip=[alt.Tooltip('month:T', title='Month', format='%b %Y'), alt.Tooltip('what:N', title=''),
                 alt.Tooltip('cr:Q', title='₹ Cr', format=',.1f')])
    dots = alt.Chart(net).mark_point(filled=True, color=INK, size=36, stroke='white', strokeWidth=2).encode(
        x='month:T', y='cr:Q', tooltip=[alt.Tooltip('month:T', title='Month', format='%b %Y'),
                                        alt.Tooltip('cr:Q', title='Net ₹ Cr', format=',.1f')])
    zero = alt.Chart(pd.DataFrame({'y': [0]})).mark_rule(color='#C9CFD8', strokeWidth=1).encode(y='y:Q')
    return (alt.layer(bars, zero, dots).properties(height=230, title=alt.TitleParams(title, anchor='start', fontSize=13,
                                                                                    fontWeight=600, color=INK))
            .configure(font='Geist').configure_view(strokeWidth=0))
