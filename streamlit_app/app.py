"""Entry point. Run with: streamlit run streamlit_app/app.py

Needs R2 read credentials (same ones already used by scripts/r2_writer.py /
the GitHub Actions R2-storage workflow) either in .streamlit/secrets.toml or
as env vars: CLOUDFLARE_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY,
R2_BUCKET_NAME. Without them the app still runs and explains what's missing
-- it never fabricates numbers to fill the screen.
"""
import streamlit as st

st.set_page_config(
    page_title="NSE·BSE Corporate Event Tracker",
    page_icon="\U0001f4ca",
    layout="wide",
)

pg = st.navigation(
    [
        st.Page("views/overview.py", title="Overview", icon="\U0001f3e0", default=True),
        st.Page("views/transactions.py", title="Transactions", icon="\U0001f4c8"),
        st.Page("views/data_quality.py", title="Data Quality", icon="✅"),
    ]
)
pg.run()
