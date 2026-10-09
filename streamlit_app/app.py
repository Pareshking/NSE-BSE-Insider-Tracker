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

HERE = Path(__file__).resolve().parent
# Anchor both import roots by absolute path so `lib` and `insiders_clean` resolve whatever the working directory is
# (Streamlit Cloud runs from the repo root; `streamlit run streamlit_app/app.py` and tests may not).
for root in (HERE, HERE.parent):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
from lib import style

st.set_page_config(
    page_title="Insiders",
    page_icon="\U0001f4ca",
    layout="wide",
)
style.inject_base_css()
style.top_brand_bar(
    f"Session as of <span class=\"mono\">{datetime.now(timezone.utc).strftime('%d %b %Y · %H:%M UTC')}</span>"
)

# Top nav bar, not a sidebar (mobile). Pages are grouped into three sections, which the top bar shows as menus.
pg = st.navigation(
    {
        "Daily": [
            st.Page("views/overview.py", title="Latest Filings", icon="\U0001f3e0", default=True),
            st.Page("pages/1_Promoter_Screener.py", title="Promoter Screener", icon="\U0001f4cc"),
            st.Page("pages/2_Company_Deep_Dive.py", title="Company Page", icon="\U0001f50d", url_path="deep-dive"),
            st.Page("pages/3_Risk_Flags.py", title="Promoter Selling", icon="⚠️"),
        ],
        "Explore": [
            st.Page("views/promoter_activity.py", title="Promoter Trades", icon="\U0001f4c8"),
            st.Page("views/bulk_block_concentration.py", title="Bulk & Block Deals", icon="\U0001f4ca"),
            st.Page("views/confluence_screener.py", title="Overlapping Activity", icon="\U0001f9ed"),
            st.Page("views/entity_tracker.py", title="Person & Fund Search", icon="\U0001f464"),
            st.Page("views/transactions.py", title="All Filings", icon="\U0001f50e"),
        ],
        "Research & Data": [
            st.Page("pages/6_Signal_Evidence.py", title="Research Findings", icon="\U0001f9ea"),
            st.Page("pages/4_Forward_Ledger.py", title="Tracked Signals", icon="\U0001f4d2"),
            st.Page("pages/5_Data_Health.py", title="Data Status", icon="\U0001fa7a"),
            st.Page("views/data_quality.py", title="Run Checks", icon="✅"),
        ],
    },
    position="top",
)

pg.run()

# After pg.run() so it sits at the foot of whichever page just rendered --
# every page, without each one having to remember to call it.
style.disclaimer_footer()
