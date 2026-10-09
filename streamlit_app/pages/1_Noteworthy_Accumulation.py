"""What is new and noteworthy: material promoter accumulation (>= Rs 25 lakh, repeat buying) and net bulk/block buying."""
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
client, _ = r2_data.page_gate()
with r2_data.guard("insider trades and deals"):
    trades, deals = clean_data.clean_table(client, 'insider_trades'), clean_data.clean_table(client, 'deals')
asof = pd.to_datetime(trades['broadcast_date']).max()
days = st.select_slider("Look-back (calendar days)", [30, 60, 90, 180], value=90)
st.caption(f"As of the latest disclosure in the data: {asof:%d %b %Y}. Promoter / promoter-group open-market buys, "
           "day combined; token trades under Rs 25 lakh removed. `cluster` = repeat buying within 30 days.")
acc = pv.promoter_accumulation(trades, asof, days)
st.subheader(f"Promoter accumulation ({len(acc)})")
st.dataframe(acc, hide_index=True, use_container_width=True)
st.subheader("Net bulk / block buying (market makers excluded)")
st.dataframe(pv.block_bulk_accumulation(deals, asof, days), hide_index=True, use_container_width=True)
style.disclaimer_footer()
