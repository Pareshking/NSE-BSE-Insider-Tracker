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
    page_title="Insiders",
    page_icon="\U0001f4ca",
    layout="wide",
)
style.inject_base_css()
style.top_brand_bar(
    f"Session as of <span class=\"mono\">{datetime.now(timezone.utc).strftime('%d %b %Y · %H:%M UTC')}</span>"
)

# Top nav bar, not a sidebar -- this app is used on mobile, where a
# left-hand sidebar drawer costs a tap and half the screen width every
# time. position="top" needs a flat page list (a horizontal bar has nowhere
# to put section headers), so the TRANSACTIONS/ANALYTICS/DATA & TRUST
# grouping from the design mockup's sidebar doesn't carry over here.
pg = st.navigation(
    [
        st.Page("views/overview.py", title="Overview", icon="\U0001f3e0", default=True),
        st.Page("views/confluence_screener.py", title="Confluence Screener", icon="\U0001f9ed"),
        st.Page("views/entity_tracker.py", title="Entity Tracker", icon="\U0001f464"),
        st.Page("views/transactions.py", title="Evidence & Drill-down", icon="\U0001f50e"),
        st.Page("views/promoter_activity.py", title="Promoter Activity", icon="\U0001f4c8"),
        st.Page("views/bulk_block_concentration.py", title="Bulk & Block Concentration", icon="\U0001f4ca"),
        st.Page("views/data_quality.py", title="Data Quality", icon="✅"),
    ],
    position="top",
)

pg.run()

# After pg.run() so it sits at the foot of whichever page just rendered --
# every page, without each one having to remember to call it.
style.disclaimer_footer()
