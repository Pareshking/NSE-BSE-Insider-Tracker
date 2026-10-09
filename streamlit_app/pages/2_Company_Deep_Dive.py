"""One company: price with insider filings, bulk/block deals and split/bonus events, plus an audit table."""
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import clean_data, r2_data, style  # noqa: E402
from insiders_clean import adjust, events as evm, product_views as pv, trade_table as tt  # noqa: E402

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

# --- campaign context: latest promoter campaign and whether large bulk/block buying coincided with it
asof_t = pd.to_datetime(trades['broadcast_date']).max()
camp = pv.active_campaigns(trades[trades['isin'] == isin], asof_t)
if len(camp):
    c = camp.iloc[0]
    al = pv.deal_alignment(deals, camp, asof_t)
    deal_txt = ("bulk/block net buying coincided: ₹{:.2f} Cr over {} deal day(s)".format(al.iloc[0]['deal_net'] / 1e7, int(al.iloc[0]['deal_days']))
                if len(al) and al.iloc[0]['deal_coincides'] else "no bulk/block net buying inside the campaign window")
    st.markdown(f"**Latest promoter campaign:** {c['span']} · {'**active**' if c['active'] else 'ended'} · {deal_txt}. "
                f"{pv.BADGE_ACCUMULATION}.")

num = lambda label, fmt: st.column_config.NumberColumn(label, format=fmt)       # noqa: E731
st.subheader("Filings and deals")
t1, t2 = st.tabs(["Insider filings", "Bulk & block deals"])
with t1:
    rows = tt.insider_rows(trades, isin)
    if rows.empty:
        st.info("No insider filings for this company in the product window (from 1 Jan 2026).")
    else:
        page, _ = style.paginate(rows.drop(columns=['Symbol', 'Company']), 'dd-ins', 50)
        st.dataframe(page, hide_index=True, use_container_width=True, column_config={
            'Date': st.column_config.DateColumn('Date', format='DD MMM YY', width='small'), 'Qty': num('Qty', '%d'),
            'Avg Price': num('Avg Price', '%.2f'), 'Value (₹ Cr)': num('Value (₹ Cr)', '%.2f'),
            '% of mcap (est.)': num('% of mcap (est.)', '%.3f'), 'Holding Δ %': num('Holding Δ %', '%.1f'),
            'File': st.column_config.LinkColumn('File', display_text='open')})
        style.download_csv(rows, f"{isin}_insider_filings.csv", key="dd_ins_csv")
        st.caption("`File` is the exchange's own XBRL disclosure where the filing carries one (NSE insider filings). The clean data has no "
                   "post-transaction shareholding percentage, so equity is the ESTIMATED value / market cap and Holding Δ is the change in the filer's own holding.")
with t2:
    drows = tt.deal_rows(deals, isin)
    if drows.empty:
        st.info("No bulk or block deals for this company in the product window.")
    else:
        page, _ = style.paginate(drows.drop(columns=['Symbol', 'Company']), 'dd-deal', 50)
        st.dataframe(page, hide_index=True, use_container_width=True, column_config={
            'Date': st.column_config.DateColumn('Date', format='DD MMM YY', width='small'), 'Qty': num('Qty', '%d'),
            'Avg Price': num('Avg Price', '%.2f'), 'Value (₹ Cr)': num('Value (₹ Cr)', '%.2f'), '% of mcap (est.)': num('% of mcap (est.)', '%.3f')})
        st.caption("Bulk and block deals have no per-record exchange link in the data; the deal id traces them to the raw archive.")
