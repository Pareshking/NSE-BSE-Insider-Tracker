"""Pipeline freshness and what the data covers. Exclusion counts are in the clean-layer reports (docs/CLEAN_LAYER.md)."""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import clean_data, r2_data, style  # noqa: E402
from insiders_clean import product_views as pv  # noqa: E402

style.inject_base_css()
st.title("Data health")
client, dates = r2_data.page_gate()
with r2_data.guard("data freshness"):
    trades, deals = clean_data.clean_table(client, 'insider_trades'), clean_data.clean_table(client, 'deals')
    px, ix = clean_data.prices(client), clean_data.index_close(client)
fresh = pv.freshness({'insider trades (disclosure date)': (trades, 'broadcast_date'), 'bulk/block deals': (deals, 'date'),
                      'NSE prices': (px, 'date'), 'Nifty indices': (ix, 'date')})
st.dataframe(fresh, hide_index=True, use_container_width=True)
st.caption(f"Latest nightly manifest: {dates[0]}. The nightly run is at 23:30 IST; ages above 3 days on a trading week mean a stale pipeline.")
st.markdown("""
- **Raw archive:** every downloaded file is stored byte for byte, write-once, under `raw_v2/` in R2 (docs/DATA_DICTIONARY.md).
- **Exclusions:** each cleaning rule counts what it removes; the counts are in `docs/CLEAN_LAYER.md` reports, not hidden.
- **Known gaps:** BSE market cap, pledges, quarterly results dates, and pre-2026 data are not in the product.
""")
style.disclaimer_footer()
