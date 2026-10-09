"""Forward-test ledger: append-only record of accumulation clusters as they mature (60 / 120 / 250 sessions vs Nifty 500)."""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import r2_data, style  # noqa: E402

style.inject_base_css()
st.title("Forward ledger")
st.info("Not started: the ledger store (`ledger/` in R2, append-only, written by a dedicated job) does not exist yet. "
        "Nothing is shown rather than anything simulated.")
st.markdown("""
Planned rules (docs/RESEARCH.md section F):
- one row per signal: timestamp, rule version, input snapshot reference, reference entry price;
- rows are never edited; a rule change starts a new series;
- outcomes are filled at 60, 120 and 250 sessions: absolute return and excess vs Nifty 500, before costs;
- 250-session outcomes cannot mature before 2027.
""")
client, _ = r2_data.page_gate()
try:
    keys = client.list_objects_v2(Bucket=r2_data._bucket(), Prefix='ledger/', MaxKeys=1).get('KeyCount', 0)
except Exception:  # noqa: BLE001
    keys = 0
st.metric("Ledger objects in R2", keys)
style.disclaimer_footer()
