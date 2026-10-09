"""One company: price with insider filings, bulk/block deals and split/bonus events, plus an audit table."""
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import clean_data, r2_data, style  # noqa: E402
from insiders_clean import adjust, events as evm, product_views as pv  # noqa: E402

style.inject_base_css()
st.title("Company deep dive")
client = clean_data.gate()
with r2_data.guard("prices, trades and deals"):
    px, trades, deals = clean_data.prices(client), clean_data.clean_table(client, 'insider_trades'), clean_data.clean_table(client, 'deals')
if px.empty:
    st.warning("No price history is stored yet.")
    st.stop()
px['date'] = pd.to_datetime(px['date'])
cat = (px.dropna(subset=['isin']).sort_values('date').drop_duplicates('isin', keep='last')[['isin', 'symbol', 'name']]
       .assign(label=lambda d: d['symbol'].astype(str) + ' · ' + d['name'].astype(str) + ' · ' + d['isin']))
q = st.text_input("Search by symbol, name or ISIN", placeholder="e.g. RELIANCE or INE002A01018").strip().lower()
hits = cat[cat['label'].str.lower().str.contains(q, regex=False)] if q else cat.head(0)
if not q:
    st.info("Type a symbol, company name or ISIN to begin.")
    st.stop()
if hits.empty:
    st.warning("No company matches that search among stored NSE prices.")
    st.stop()
label = st.selectbox("Match", hits['label'].head(50))
isin = hits.set_index('label').at[label, 'isin']
p = px[px['isin'] == isin].sort_values('date')

fig = go.Figure(go.Scatter(x=p['date'], y=p['close'], mode='lines', name='Close (as printed, unadjusted)'))
styles = {'BUY': ('green', 'triangle-up', 'Insider market buy'), 'SELL': ('red', 'triangle-down', 'Insider market sell')}
for side, (color, symbol, name) in styles.items():
    e = evm.insider_events(trades[trades['isin'] == isin], side)
    m = e.merge(p[['date', 'close']], left_on='broadcast_date', right_on='date', how='left').dropna(subset=['close'])
    fig.add_trace(go.Scatter(x=m['broadcast_date'], y=m['close'], mode='markers', name=name,
                             marker=dict(color=color, size=10, symbol=symbol)))
prom = evm.insider_events(trades[trades['isin'] == isin], 'BUY', roles=evm.PROMOTER_ROLES).merge(
    p[['date', 'close']], left_on='broadcast_date', right_on='date', how='left').dropna(subset=['close'])
fig.add_trace(go.Scatter(x=prom['broadcast_date'], y=prom['close'], mode='markers', name='Promoter market buy',
                         marker=dict(color='darkgreen', size=14, symbol='star')))
d = evm.deal_events(deals[deals['isin'] == isin]).merge(p[['date', 'close']], left_on='broadcast_date', right_on='date', how='left').dropna(subset=['close'])
fig.add_trace(go.Scatter(x=d['broadcast_date'], y=d['close'], mode='markers', name='Bulk/block deal day',
                         marker=dict(color='orange', size=8, symbol='diamond')))
for _, r in (adjust.implied_factors(p)[lambda f: f['kind'] == 'split_bonus'] if 'prev_close' in p else p.iloc[0:0]).iterrows():
    fig.add_vline(x=r['date'], line_dash='dot', annotation_text=f"split/bonus ×{r['factor']:.3g}")
fig.update_layout(height=460, margin=dict(l=8, r=8, t=30, b=8), legend=dict(orientation='h', y=-0.15))
st.plotly_chart(fig, use_container_width=True)
st.caption("Prices are as printed: a split or bonus shows as a step at the dotted line. Markers sit on the disclosure date. "
           "Quarterly results dates are not collected yet, so none are shown.")

st.subheader("Audit trail")
audit = pv.audit_table(trades, deals, isin)
if audit.empty:
    st.info("No insider filings or deals for this company in the product window (from 1 Jan 2026).")
else:
    st.dataframe(audit, hide_index=True, use_container_width=True,
                 column_config={'link': st.column_config.LinkColumn('exchange file', display_text='open'),
                                'date': st.column_config.DateColumn('date'), 'value': st.column_config.NumberColumn('value (Rs)', format='%.0f')})
    st.caption("`exchange file` is the exchange's own XBRL disclosure where the filing carries one (NSE insider filings). "
               "Bulk/block deals and BSE filings have no per-record link in the data; the id column traces them to the raw archive.")
