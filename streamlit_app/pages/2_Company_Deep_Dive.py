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
with r2_data.guard("trades, deals and the price summary"):
    trades, deals = clean_data.clean_table(client, 'insider_trades'), clean_data.clean_table(client, 'deals')
    summary = clean_data.price_summary(client)
if summary.empty:       # batch job not run yet: search the companies that have filings; prices still load per company
    cat = (trades.dropna(subset=['isin', 'company']).drop_duplicates('isin')[['isin', 'company']]
           .assign(symbol='', name=lambda d: d['company']))
else:
    cat = summary[['isin', 'symbol', 'name']]
cat = cat.assign(label=lambda d: d['symbol'].astype(str) + ' · ' + d['name'].astype(str) + ' · ' + d['isin'])
isin = st.session_state.get('deep_dive_isin')
q = st.text_input("Search by symbol, name or ISIN", placeholder="e.g. RELIANCE or INE002A01018").strip().lower()
if q:
    hits = cat[cat['label'].str.lower().str.contains(q, regex=False)]
    if hits.empty:
        st.warning("No company matches that search.")
        st.stop()
    label = st.selectbox("Match", hits['label'].head(50))
    isin = hits.set_index('label').at[label, 'isin']
    st.session_state['deep_dive_isin'] = isin
elif not isin:
    st.info("Type a symbol, company name or ISIN to begin, or open a company from the Promoter Screener.")
    st.stop()
else:
    st.caption("Showing " + str(cat.set_index('isin')['label'].get(isin, isin)))
with r2_data.guard("this company's prices"):
    p = clean_data.price_history(client, isin)
if p.empty:
    st.warning("No stored NSE prices for this company.")
    st.stop()
p = p.assign(date=pd.to_datetime(p['date'])).sort_values('date')
adjusted = st.toggle("Adjust for splits and bonuses", value=True)
f = adjust.implied_factors(p) if 'prev_close' in p else None      # from the prices as printed, before any adjustment
if adjusted:
    if f is not None:
        a = adjust.adjust_as_of(f, p[['exchange', 'isin', 'date', 'close']].dropna(), p['date'].max())
        p = p.merge(a[['exchange', 'isin', 'date', 'adj_close']], on=['exchange', 'isin', 'date'], how='left')
        p['close'] = p['adj_close'].fillna(p['close'])

fig = go.Figure(go.Scatter(x=p['date'], y=p['close'], mode='lines', name='Close (split/bonus adjusted)' if adjusted else 'Close (as printed)'))
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
for _, r in (f[f['kind'] == 'split_bonus'] if f is not None else p.iloc[0:0]).iterrows():
    fig.add_vline(x=r['date'], line_dash='dot', annotation_text=f"split/bonus ×{r['factor']:.3g}")
for _, c in pv.campaigns(trades[trades['isin'] == isin], trades['broadcast_date'].max(), min_value=float('-inf')).iterrows():
    fig.add_vrect(x0=c['start'], x1=c['end'] + pd.Timedelta(days=1), fillcolor='green', opacity=0.12, line_width=0,
                  annotation_text=f"campaign: {c['buy_days']} buy day(s)", annotation_position='top left')
fig.update_layout(height=460, margin=dict(l=8, r=8, t=30, b=8), legend=dict(orientation='h', y=-0.15))
st.plotly_chart(fig, use_container_width=True)
st.caption("Dotted lines mark detected split/bonus events (adjusted prices remove the step; switch the toggle off to see prices as printed). "
           "Green bands are promoter buying campaigns (buy days at most 90 days apart). Markers sit on the disclosure date. "
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
