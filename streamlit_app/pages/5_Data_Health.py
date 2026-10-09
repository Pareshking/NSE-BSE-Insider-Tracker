"""Pipeline freshness, raw capture counts, exclusion counts by reason, unmapped entities."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import clean_data, r2_data, style  # noqa: E402
from insiders_clean import product_views as pv  # noqa: E402

style.inject_base_css()
st.title("Data health")
client = clean_data.gate()
with r2_data.guard("data freshness"):
    trades, deals = clean_data.clean_table(client, 'insider_trades'), clean_data.clean_table(client, 'deals')
    px, ix = clean_data.prices(client), clean_data.index_close(client)
    led = clean_data.ledger(client)
    report = clean_data.cleaning_report(client)
    raw = clean_data.raw_capture_counts(client)

st.subheader("Freshness")
fresh = pv.freshness({'insider trades (disclosure date)': (trades, 'broadcast_date'), 'bulk/block deals': (deals, 'date'),
                      'NSE prices': (px, 'date'), 'Nifty indices': (ix, 'date'), 'forward ledger (entry)': (led, 'entry_date')})
st.dataframe(fresh, hide_index=True, use_container_width=True,
             column_config={'latest': st.column_config.DateColumn('latest')})
st.caption("The nightly job runs at 23:30 IST. An age above 3 days in a trading week means a stale pipeline.")

st.subheader("Raw capture (raw_v2, write-once)")
if raw.empty:
    st.info("No raw captures found.")
else:
    st.dataframe(raw, hide_index=True, use_container_width=True)
    st.caption(f"{int(raw['blobs'].sum()):,} distinct stored payloads and {int(raw['fetch_records'].sum()):,} fetch records. "
               "Every download is kept byte for byte; cleaning never edits it.")

st.subheader("Exclusions by reason (latest cleaning run)")
if not report:
    st.info("No cleaning report found.")
else:
    rows = [{'table': t, 'reason': r, 'rows removed': v.get('count', 0)} for t, tv in report.get('tables', {}).items()
            for r, v in tv.get('removed', {}).items()]
    inputs = [{'table': t, 'input rows': tv.get('input_rows'), 'output rows': tv.get('output_rows')} for t, tv in report.get('tables', {}).items()]
    st.dataframe(pd.DataFrame(inputs), hide_index=True, use_container_width=True)
    st.dataframe(pd.DataFrame(rows).sort_values(['table', 'rows removed'], ascending=[True, False]) if rows else pd.DataFrame(),
                 hide_index=True, use_container_width=True)
    st.caption(f"Report run date: {report.get('run_date')}.")

st.subheader("Unmapped entities")
unm = report.get('unmatched_securities', []) if report else []
c1, c2, c3 = st.columns(3)
c1.metric("Securities not matched to an ISIN", len(unm))
c2.metric("Insider rows without ISIN", int(trades['isin'].isna().sum()) if 'isin' in trades else 0)
c3.metric("Deal rows without ISIN", int(deals['isin'].isna().sum()) if 'isin' in deals else 0)
if unm:
    st.dataframe(pd.DataFrame(unm).head(200), hide_index=True, use_container_width=True)
st.markdown("**Known gaps:** BSE market cap, pledges, quarterly results dates and pre-2026 data are not in the product.")
