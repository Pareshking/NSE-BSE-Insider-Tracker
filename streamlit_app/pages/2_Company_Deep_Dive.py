"""One company: price with insider filings, bulk/block deals and split/bonus events on a single timeline."""
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import clean_data, r2_data, style  # noqa: E402
from insiders_clean import adjust, events as evm  # noqa: E402

style.inject_base_css()
st.title("Company deep dive")
client, _ = r2_data.page_gate()
with r2_data.guard("prices, trades and deals"):
    px, trades, deals = clean_data.prices(client), clean_data.clean_table(client, 'insider_trades'), clean_data.clean_table(client, 'deals')
px['date'] = pd.to_datetime(px['date'])
names = (trades.dropna(subset=['isin', 'company']).drop_duplicates('isin').set_index('isin')['company'])
isins = sorted(set(px['isin'].dropna()) & set(names.index), key=lambda i: names[i])
isin = st.selectbox("Company", isins, format_func=lambda i: f"{names[i]} ({i})")
p = px[px['isin'] == isin].sort_values('date')
fig = go.Figure(go.Scatter(x=p['date'], y=p['close'], mode='lines', name='Close (as printed, unadjusted)'))
for side, color in (('BUY', 'green'), ('SELL', 'red')):
    e = evm.insider_events(trades[trades['isin'] == isin], side)
    m = e.merge(p[['date', 'close']], left_on='broadcast_date', right_on='date', how='left').dropna(subset=['close'])
    fig.add_trace(go.Scatter(x=m['broadcast_date'], y=m['close'], mode='markers', name=f'Insider market {side.lower()}',
                             marker=dict(color=color, size=9, symbol='triangle-up' if side == 'BUY' else 'triangle-down')))
d = evm.deal_events(deals[deals['isin'] == isin]).merge(p[['date', 'close']], left_on='broadcast_date', right_on='date', how='left').dropna(subset=['close'])
fig.add_trace(go.Scatter(x=d['broadcast_date'], y=d['close'], mode='markers', name='Bulk/block deal day',
                         marker=dict(color='orange', size=8, symbol='diamond')))
f = adjust.implied_factors(p)
for _, r in f[f['kind'] == 'split_bonus'].iterrows():
    fig.add_vline(x=r['date'], line_dash='dot', annotation_text=f"split/bonus x{r['factor']:.3g}")
st.plotly_chart(fig, use_container_width=True)
st.caption("Prices are as printed: a split/bonus appears as a step (dotted line). Quarterly results dates are not collected yet "
           "(listed in docs/TODO.md); nothing is inferred about them here.")
style.disclaimer_footer()
