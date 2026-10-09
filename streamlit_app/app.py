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
        "Executive Conviction": [
            st.Page("views/overview.py", title="Overview", icon="\U0001f3e0", default=True),
            st.Page("pages/1_Promoter_Screener.py", title="Promoter Screener", icon="\U0001f4cc"),
            st.Page("pages/2_Company_Deep_Dive.py", title="Company Deep Dive", icon="\U0001f50d"),
            st.Page("pages/4_Forward_Ledger.py", title="Forward Ledger", icon="\U0001f4d2"),
            st.Page("pages/3_Risk_Flags.py", title="Risk & Caution Flags", icon="⚠️"),
        ],
        "Exploration & Screeners": [
            st.Page("views/confluence_screener.py", title="Confluence Screener", icon="\U0001f9ed"),
            st.Page("views/entity_tracker.py", title="Entity Tracker", icon="\U0001f464"),
            st.Page("views/bulk_block_concentration.py", title="Bulk & Block Concentration", icon="\U0001f4ca"),
            st.Page("views/promoter_activity.py", title="Promoter Activity", icon="\U0001f4c8"),
            st.Page("views/transactions.py", title="Evidence & Drill-down", icon="\U0001f50e"),
        ],
        "Operations & Audit": [
            st.Page("pages/5_Data_Health.py", title="Data Health & Lineage", icon="\U0001fa7a"),
            st.Page("views/data_quality.py", title="Data Quality", icon="✅"),
        ],
    },
    position="top",
)

pg.run()

# After pg.run() so it sits at the foot of whichever page just rendered --
# every page, without each one having to remember to call it.
style.disclaimer_footer()
