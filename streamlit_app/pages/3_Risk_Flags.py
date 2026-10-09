"""Caution flags: heavy insider selling. Pledge spikes are not collected yet and are said so."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import clean_data, r2_data, style  # noqa: E402
from insiders_clean import product_views as pv  # noqa: E402

style.inject_base_css()
st.title("Risk and caution flags")
st.info("Heavy insider selling is a caution flag, not a trade signal. In the development sample insider sells did not "
        "underperform Nifty 500 (docs/RESEARCH.md J.1); earlier peer-relative tests pointed the other way. Treat as "
        "a prompt to read the filing.")
client, _ = r2_data.page_gate()
with r2_data.guard("insider trades"):
    trades = clean_data.clean_table(client, 'insider_trades')
asof = pd.to_datetime(trades['broadcast_date']).max()
days = st.select_slider("Look-back (calendar days)", [30, 60, 90], value=60)
st.dataframe(pv.heavy_selling(trades, asof, days), hide_index=True, use_container_width=True)
st.warning("Pledge and encumbrance spikes: not available. Pledge disclosures are not in the pipeline yet (docs/TODO.md).")
style.disclaimer_footer()
