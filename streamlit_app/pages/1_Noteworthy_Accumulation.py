"""What is new and noteworthy: promoter net accumulation over 90 / 180 / 365 days, multi-quarter campaigns, net bulk/block buying."""
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
first = pd.to_datetime(trades['broadcast_date']).min()

c1, c2, c3 = st.columns(3)
min_lakh = c1.select_slider("Minimum net value in any window (Rs lakh)", [10, 25, 50, 100, 500], value=25)
min_pct = c2.select_slider("or net share of market cap (%)", [0.02, 0.05, 0.1, 0.25, 1.0], value=0.05)
only_sustained = c3.checkbox("Sustained only (net buying in all three windows)")
st.caption(f"Data {first:%d %b %Y} to {asof:%d %b %Y}: the 365-day window covers only the data we hold. Promoter / promoter-group "
           "open-market flow, buys minus sells; director, KMP, designated-person and employee filings are left out. "
           "Share of market cap is ESTIMATED (value / market cap on the disclosure day), a proxy for share of equity.")

acc = pv.promoter_absorption(trades, asof, min_value=min_lakh * pv.LAKH, min_pct=min_pct)
if only_sustained:
    acc = acc[acc['sustained']]
st.subheader(f"Promoter net accumulation ({len(acc)})")
if acc.empty:
    st.info("Nothing clears these filters.")
else:
    view = acc.copy()
    for w in pv.WINDOWS:
        view[f'net_{w}d'] = (view[f'net_{w}d'] / pv.LAKH).round(1)
        view[f'pct_{w}d'] = view[f'pct_{w}d'].round(3)
    st.dataframe(view.drop(columns=['badge']).rename(columns={**{f'net_{w}d': f'net {w}d (Rs lakh)' for w in pv.WINDOWS},
                                                              **{f'pct_{w}d': f'% mcap {w}d (est.)' for w in pv.WINDOWS}}),
                 hide_index=True, use_container_width=True,
                 column_config={'last_buy': st.column_config.DateColumn('last buy')})
    st.caption(pv.BADGE_ACCUMULATION)
    style.download_csv(view, "promoter_net_accumulation.csv", key="acc_csv")

st.subheader("Multi-quarter campaigns")
st.caption(f"Buy days at most {pv.CAMPAIGN_GAP_DAYS} days apart form one campaign. Sales inside the campaign span are netted off.")
camp = pv.campaigns(trades, asof, min_value=min_lakh * pv.LAKH)
if camp.empty:
    st.info("No campaign clears the bar.")
else:
    st.dataframe(camp.assign(bought=(camp['bought'] / pv.LAKH).round(1), sold=(camp['sold'] / pv.LAKH).round(1),
                             net=(camp['net'] / pv.LAKH).round(1), pct_of_mcap=camp['pct_of_mcap'].round(3))
                 .rename(columns={'bought': 'bought (Rs lakh)', 'sold': 'sold (Rs lakh)', 'net': 'net (Rs lakh)', 'pct_of_mcap': '% mcap (est.)'}),
                 hide_index=True, use_container_width=True)

st.subheader("Net bulk / block buying")
win = st.radio("Window (days)", list(pv.WINDOWS), horizontal=True)
st.caption("Net buyers after same-day netting across clients; market makers excluded. Bulk and block deals are combined; "
           "no time of day is available. Context only: no proven edge.")
bb = pv.block_bulk_accumulation(deals, asof, win)
names = trades.dropna(subset=['isin', 'company']).drop_duplicates('isin').set_index('isin')['company']
if bb.empty:
    st.info("No net-buy deals clear the bar in the window.")
else:
    st.dataframe(bb.assign(company=bb['isin'].map(names), net_value_cr=(bb['net_value'] / 1e7).round(2))[['company', 'isin', 'net_value_cr', 'days']],
                 hide_index=True, use_container_width=True)
