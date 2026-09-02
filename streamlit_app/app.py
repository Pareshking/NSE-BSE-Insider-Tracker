"""Entry point. Run with: streamlit run streamlit_app/app.py

Needs R2 read credentials (same ones already used by scripts/r2_writer.py /
the GitHub Actions R2-storage workflow) either in .streamlit/secrets.toml or
as env vars: CLOUDFLARE_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY,
R2_BUCKET_NAME. Without them the app still runs and explains what's missing
-- it never fabricates numbers to fill the screen.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import style

st.set_page_config(
    page_title="NSE·BSE Corporate Event Tracker",
    page_icon="\U0001f4ca",
    layout="wide",
    initial_sidebar_state="expanded",
)
style.inject_base_css()
style.sidebar_brand()

pg = st.navigation(
    [
        st.Page("views/overview.py", title="Overview", icon="\U0001f3e0", default=True),
        st.Page("views/promoter_activity.py", title="Promoter Activity", icon="\U0001f4c8"),
        st.Page("views/bulk_block_concentration.py", title="Bulk & Block Concentration", icon="\U0001f4ca"),
        st.Page("views/transactions.py", title="Evidence & Drill-down", icon="\U0001f50e"),
        st.Page("views/data_quality.py", title="Data Quality", icon="✅"),
    ]
)

style.sidebar_footer(
    f"Session as of<br/><span class=\"mono\">{datetime.now(timezone.utc).strftime('%d %b %Y · %H:%M UTC')}</span>"
)

pg.run()
