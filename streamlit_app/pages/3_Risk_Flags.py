"""Caution flags: cumulative promoter net selling over 90 / 180 / 365 days. Pledge spikes are not collected yet."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import clean_data, r2_data, style  # noqa: E402
from insiders_clean import product_views as pv  # noqa: E402

style.inject_base_css()
style.head("Promoter selling", "Net promoter selling over 90, 180 and 365 days")
st.markdown(style.tag("Caution flag · not a trade signal", "Insider sells also beat Nifty 500 in our sample, so the evidence is mixed. Use this to prompt reading the filings. See Research Findings.", "sell"), unsafe_allow_html=True)
client = clean_data.gate()
with r2_data.guard("insider trades"):
    trades = clean_data.clean_table(client, 'insider_trades')
asof = pd.to_datetime(trades['broadcast_date']).max()
min_lakh = st.select_slider("Net selling at least (Rs lakh) in any window", [10, 25, 50, 100, 500], value=25)
f = pv.promoter_selling(trades, asof, min_value=min_lakh * pv.LAKH)
st.caption(f"Data to {asof:%d %b %Y} · open-market sales minus buys by promoters (negative = net buyer) · % of market cap is an estimate")
if f.empty:
    st.info("No security is flagged under these settings.")
else:
    v = f.copy()
    for w in pv.WINDOWS:
        v[f'sold_{w}d'] = (v[f'sold_{w}d'] / pv.LAKH).round(1)
        v[f'pct_{w}d'] = v[f'pct_{w}d'].round(3)
    st.dataframe(v.rename(columns={**{f'sold_{w}d': f'net sold {w}d (Rs lakh)' for w in pv.WINDOWS},
                                   **{f'pct_{w}d': f'% mcap {w}d (est.)' for w in pv.WINDOWS}}),
                 hide_index=True, use_container_width=True)
st.warning("Pledge and encumbrance spikes: not available. Pledge disclosures are not in the pipeline yet (docs/TODO.md).")
