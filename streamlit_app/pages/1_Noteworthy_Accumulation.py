"""What is new and noteworthy: material promoter accumulation and net bulk/block buying."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import clean_data, r2_data, style  # noqa: E402
from insiders_clean import product_views as pv  # noqa: E402

style.inject_base_css()
st.title("Noteworthy accumulation")
st.info(pv.NO_EDGE_NOTE)
client = clean_data.gate()
with r2_data.guard("insider trades and deals"):
    trades, deals = clean_data.clean_table(client, 'insider_trades'), clean_data.clean_table(client, 'deals')
asof = pd.to_datetime(trades['broadcast_date']).max()

c1, c2, c3, c4 = st.columns(4)
days = c1.select_slider("Look-back (days)", [30, 60, 90, 180], value=90)
min_lakh = c2.select_slider("Minimum value (Rs lakh)", [10, 25, 50, 100], value=25)
min_pct = c3.select_slider("or share of market cap (%)", [0.02, 0.05, 0.1, 0.25], value=0.05)
only_cluster = c4.checkbox("Repeat buying only (30-day cluster)")
st.caption(f"Data to {asof:%d %b %Y}. Promoter / promoter-group open-market buys only; director, KMP, designated-person and "
           "employee filings are left out. A security shows when its combined value or its share of market cap clears the bar.")

acc = pv.promoter_accumulation(trades, asof, days, min_lakh * pv.LAKH, min_pct)
if only_cluster:
    acc = acc[acc['cluster']]
st.subheader(f"Promoter accumulation ({len(acc)})")
if acc.empty:
    st.info("Nothing clears these filters in the window.")
else:
    view = acc.assign(value_lakh=(acc['value'] / pv.LAKH).round(1), pct_of_mcap=acc['pct_of_mcap'].round(3))
    st.dataframe(view[['company', 'isin', 'value_lakh', 'pct_of_mcap', 'buy_days', 'first', 'last', 'cluster', 'badge']],
                 hide_index=True, use_container_width=True,
                 column_config={'first': st.column_config.DateColumn('first'), 'last': st.column_config.DateColumn('last')})
    style.download_csv(view, "promoter_accumulation.csv", key="acc_csv")

st.subheader("Net bulk / block buying")
st.caption("Net buyers after same-day netting across clients; market makers excluded. Bulk and block deals are combined; "
           "no time of day is available. Context only: no proven edge.")
bb = pv.block_bulk_accumulation(deals, asof, days)
names = trades.dropna(subset=['isin', 'company']).drop_duplicates('isin').set_index('isin')['company']
if bb.empty:
    st.info("No net-buy deals clear the bar in the window.")
else:
    st.dataframe(bb.assign(company=bb['isin'].map(names), net_value_cr=(bb['net_value'] / 1e7).round(2))[['company', 'isin', 'net_value_cr', 'days']],
                 hide_index=True, use_container_width=True)
