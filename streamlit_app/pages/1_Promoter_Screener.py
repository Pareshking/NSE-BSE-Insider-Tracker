"""Promoter accumulation screener: net promoter open-market flow over 90 / 180 / 365 days, campaigns, price context."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import clean_data, r2_data, style  # noqa: E402
from insiders_clean import product_views as pv, trade_table as tt  # noqa: E402

CR = 1e7
style.inject_base_css()
st.title("Promoter accumulation screener")
st.info(pv.NO_EDGE_NOTE)
client = clean_data.gate()
with r2_data.guard("insider trades and price summary"):
    trades, deals = clean_data.clean_table(client, 'insider_trades'), clean_data.clean_table(client, 'deals')
    summary = clean_data.price_summary(client)
asof = pd.to_datetime(trades['broadcast_date']).max()
first = pd.to_datetime(trades['broadcast_date']).min()
have_prices = not summary.empty

with st.expander("Filters", expanded=True):
    c1, c2, c3 = st.columns(3)
    horizon = c1.radio("Horizon", ['90D', '180D', '365D', 'Sustained'], index=1, horizontal=True,
                       help="Sustained = net buying in all three windows; the value and % bars then apply to the 365-day figures.")
    net_label = c2.selectbox("Minimum net value", ["25 lakh", "50 lakh", "1 crore", "5 crore"], index=0)
    pct_label = c3.selectbox("Minimum equity absorbed (est.)", ["Any", "0.1%", "0.25%", "0.5%", "1%", "2%"], index=0)
    c4, c5, c6 = st.columns(3)
    buckets = c4.multiselect("Market cap category", list(pv.BUCKET_ORDER), default=list(pv.BUCKET_ORDER),
                             help="ESTIMATED: rank of NSE market cap on the latest stored day (Large top 100, Mid 101-250, Small 251-500, Micro the rest).",
                             disabled=not have_prices)
    dd_label = c5.selectbox("Price context", ["Any", "More than 15% below 52-week high", "More than 30% below 52-week high"],
                            disabled=not have_prices)
    active_only = c6.checkbox("Active campaign only", help=f"Repeat purchases with gaps of at most {pv.CAMPAIGN_GAP_DAYS} days, last buy within that gap of the latest data.")
    pure = st.checkbox("Exclude any stock with promoter selling in the selected window")
if not have_prices:
    st.warning("The price summary has not been written yet (run the 'Precompute slim assets' workflow), so market-cap and price-context filters are off.")

net_min = {"25 lakh": 25 * pv.LAKH, "50 lakh": 50 * pv.LAKH, "1 crore": CR, "5 crore": 5 * CR}[net_label]
pct_min = 0.0 if pct_label == "Any" else float(pct_label.rstrip('%'))
dd_min = {"Any": 0.0}.get(dd_label, 0.15 if "15%" in dd_label else 0.30)

acc = pv.promoter_absorption(trades, asof, min_value=1, min_pct=0)
camps = pv.active_campaigns(trades, asof)
res = pv.screen(acc, summary if have_prices else None, camps, horizon, net_min, pct_min, buckets or pv.BUCKET_ORDER, active_only, dd_min, pure)
if len(res):
    res = res.merge(pv.deal_alignment(deals, camps, asof), on='isin', how='left')
else:
    res = res.assign(deal_net=pd.Series(dtype=float), deal_days=pd.Series(dtype=float), deal_coincides=pd.Series(dtype=bool))

st.caption(f"Data {first:%d %b %Y} to {asof:%d %b %Y}: the 365-day window covers only the data we hold. Promoter / promoter-group "
           "open-market flow, buys minus sells; director, KMP, designated-person and employee filings are left out. "
           "Equity absorbed is ESTIMATED (net value / market cap on the disclosure day), a proxy for share of equity.")
st.subheader(f"Results ({len(res)})")
if res.empty:
    st.info("Nothing clears these filters.")
    st.stop()
grid = pd.DataFrame({
    'Symbol': res['symbol'].fillna(res['company']), 'Company': res['company'], 'Cap': res['mcap_bucket'].fillna('n/a'),
    **{f'{w}D net (₹ Cr)': (res[f'net_{w}d'] / CR) for w in pv.HORIZONS.values()},
    '% absorbed (est.)': res['pct'], 'Campaign': res['span'].fillna('-'), 'Active': res['active'],
    'Bulk/block in campaign (₹ Cr)': res['deal_net'] / CR, 'Deals align': res['deal_coincides'].fillna(False).map({True: 'Net buying', False: '-'}),
    '% off 52W high': res['pct_off_high'] * 100}).sort_values(f'{pv.HORIZONS.get(horizon, 365)}D net (₹ Cr)', ascending=False)
res = res.loc[grid.index].reset_index(drop=True)
grid = grid.reset_index(drop=True)
num = lambda label, fmt: st.column_config.NumberColumn(label, format=fmt)       # noqa: E731 -- right-aligned numerics
cfg = {**{f'{w}D net (₹ Cr)': num(f'{w}D net (₹ Cr)', '%.2f') for w in pv.HORIZONS.values()}, '% absorbed (est.)': num('% absorbed (est.)', '%.3f'),
       'Bulk/block in campaign (₹ Cr)': num('Bulk/block (₹ Cr)', '%.2f'), '% off 52W high': num('% off 52W high', '%.1f'),
       'Symbol': st.column_config.TextColumn(width='small'), 'Cap': st.column_config.TextColumn(width='small'),
       'Campaign': st.column_config.TextColumn(width='medium'), 'Active': st.column_config.CheckboxColumn(width='small')}
page, off = style.paginate(grid, 'screener', 50)
event = st.dataframe(page, hide_index=True, use_container_width=True, on_select="rerun", selection_mode="single-row",
                     key="screener_grid", column_config=cfg)
st.caption(f"{pv.BADGE_ACCUMULATION}. Sorted by the selected horizon, largest first. 'Deals align' = bulk/block net buying (market makers "
           "excluded) inside the campaign window; deals carry no reliable FII/DII label. Select a row for its filings.")
sel = event.selection.rows if event and event.selection else []
if sel:
    row = res.iloc[off + sel[0]]
    if st.button(f"Open {row['symbol'] or row['company']} in Company Deep Dive", type="primary"):
        st.session_state['deep_dive_isin'] = row['isin']
        st.switch_page("pages/2_Company_Deep_Dive.py")
    st.subheader(f"Filings: {row['company']}")
    rows = tt.insider_rows(trades, row['isin'])
    st.dataframe(rows.drop(columns=['Symbol', 'Company']), hide_index=True, use_container_width=True, column_config={
        'Date': st.column_config.DateColumn('Date', format='DD MMM YY', width='small'),
        'Qty': num('Qty', '%d'), 'Avg Price': num('Avg Price', '%.2f'), 'Value (₹ Cr)': num('Value (₹ Cr)', '%.2f'),
        '% of mcap (est.)': num('% of mcap (est.)', '%.3f'), 'Holding Δ %': num('Holding Δ %', '%.1f'),
        'File': st.column_config.LinkColumn('File', display_text='open')})
style.download_csv(grid, "promoter_screener.csv", key="screener_csv")
