"""Caution flags: heavy or rapid insider selling over 30 / 60 days. Pledge spikes are not collected yet."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import clean_data, r2_data, style  # noqa: E402
from insiders_clean import product_views as pv  # noqa: E402

style.inject_base_css()
st.title("Risk and caution flags")
st.info("Insider selling is a caution flag, not a trade signal. In the Jan-Jun 2026 development sample, stocks insiders sold "
        "lagged peers in early tests, but against Nifty 500 they did not underperform (docs/RESEARCH.md J.1); the evidence "
        "is mixed. Use these as a prompt to read the filings.")
client = clean_data.gate()
with r2_data.guard("insider trades"):
    trades = clean_data.clean_table(client, 'insider_trades')
asof = pd.to_datetime(trades['broadcast_date']).max()
c1, c2, c3 = st.columns(3)
days = c1.radio("Window", [30, 60], index=1, horizontal=True)
min_lakh = c2.select_slider("Heavy: value at least (Rs lakh)", [10, 25, 50, 100], value=25)
only_prom = c3.checkbox("Promoter / promoter group selling only")
f = pv.risk_flags(trades, asof, days, min_lakh * pv.LAKH)
if only_prom:
    f = f[f['promoter_selling']]
st.caption(f"Data to {asof:%d %b %Y}. Heavy = combined open-market sales at or above the bar; Rapid = sales on 3 or more separate disclosure days.")
if f.empty:
    st.info("No security is flagged under these settings.")
else:
    st.dataframe(f.assign(value_lakh=(f['value'] / pv.LAKH).round(1))[['company', 'isin', 'value_lakh', 'sell_days', 'people',
                                                                       'promoter_selling', 'heavy', 'rapid']],
                 hide_index=True, use_container_width=True)
st.warning("Pledge and encumbrance spikes: not available. Pledge disclosures are not in the pipeline yet (docs/TODO.md).")
