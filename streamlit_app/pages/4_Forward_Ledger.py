"""Forward-test ledger: promoter accumulation signals first disclosed after 30 Jun 2026, followed as they mature."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import clean_data, ledger_view, style  # noqa: E402

style.inject_base_css()
style.head("Tracked signals", "Forward ledger: promoter signals followed from the day they were filed")
st.info("A monitor, not a test: signals are fixed when disclosed (two series, below: single material filings and multi-quarter "
        "campaigns, both promoter / promoter-group open-market buying disclosed after 30 Jun 2026) and never edited. Returns are before "
        "costs and shown as absolute and excess vs Nifty 500. Showing these outcomes means the hold-out is no longer unseen "
        "for these events (docs/DECISIONS.md).")
client = clean_data.gate()
ledger_view.render(client)
