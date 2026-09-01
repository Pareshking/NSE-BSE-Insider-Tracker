import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import r2_data, style

style.inject_base_css()

st.title("Overview")

client = r2_data.get_client()

if not r2_data.r2_configured():
    st.warning(
        "R2 credentials aren't configured for this app, so there's no data to show yet. "
        "Set `CLOUDFLARE_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, "
        "`R2_BUCKET_NAME` in `.streamlit/secrets.toml` (or as env vars) -- the same "
        "values already used by the GitHub Actions R2-storage workflow."
    )
    st.stop()

dates = r2_data.list_manifest_dates(client)
if not dates:
    st.info("No manifests found in the bucket yet -- the R2 write workflow hasn't run, or hasn't produced output for any date.")
    st.stop()

col_a, col_b = st.columns([1, 4])
with col_a:
    selected_date = st.selectbox("Run date", dates, index=0)

manifest = r2_data.load_manifest(client, selected_date)
entries = manifest.get("datasets", manifest if isinstance(manifest, list) else [])
if isinstance(entries, dict):
    entries = list(entries.values())

data = r2_data.load_all_canonical(client, selected_date)

# --- KPI strip: one card per category, badge per exchange showing whether
# that exchange's data made it into this run (VERIFIED + written), plus a
# "datasets verified this run" summary card. ---
kpi_cols = st.columns(len(r2_data.CATEGORIES) + 1)
status_by_key = {(e.get("exchange"), e.get("category")): e for e in entries}
written_count = sum(1 for e in entries if e.get("written"))
total_count = len(entries) or (len(r2_data.CATEGORIES) * len(r2_data.EXCHANGES))

for i, category in enumerate(r2_data.CATEGORIES):
    with kpi_cols[i]:
        df = pd.concat(
            [data.get((ex, category), pd.DataFrame()) for ex in r2_data.EXCHANGES],
            ignore_index=True,
        )
        badges = []
        for ex in r2_data.EXCHANGES:
            entry = status_by_key.get((ex, category), {})
            written = bool(entry.get("written"))
            badges.append(
                style.badge(ex.upper(), "green" if written else "amber", "green_bg" if written else "amber_bg")
            )
        st.markdown(
            style.kpi_card(
                r2_data.CATEGORY_LABELS[category].upper(),
                f"{len(df):,}",
                f'<div style="display:flex;gap:6px;margin-top:9px;">{"".join(badges)}</div>',
            ),
            unsafe_allow_html=True,
        )

with kpi_cols[-1]:
    st.markdown(
        f"""
        <div class="kpi-card" style="background:{style.COLORS['text']};color:#fff;">
        <div class="kpi-label" style="color:#94a3b8;">DATASETS VERIFIED</div>
        <div class="kpi-value" style="display:flex;align-items:baseline;gap:4px;">
            {written_count}<span style="font-size:15px;color:#94a3b8;">/{total_count}</span>
        </div>
        <div style="font-size:11px;color:#cbd5e1;margin-top:9px;">this run · not an average score</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.write("")
left, right = st.columns([2, 1])

with left:
    st.subheader("Latest activity — Insider Trading")
    insider_df = pd.concat(
        [data.get((ex, "insider_trading"), pd.DataFrame()) for ex in r2_data.EXCHANGES],
        ignore_index=True,
    )
    if insider_df.empty:
        st.caption("No insider-trading rows written for this run date.")
    else:
        show_cols = [
            c
            for c in [
                "canonical_transaction_date",
                "canonical_company",
                "canonical_person",
                "canonical_person_category",
                "canonical_transaction_type",
                "canonical_value",
                "exchange",
            ]
            if c in insider_df.columns
        ]
        recent = insider_df.sort_values("canonical_transaction_date", ascending=False).head(8)
        st.dataframe(recent[show_cols], hide_index=True, use_container_width=True)
    st.caption("Full drill-down (native fields, source ID, ISIN cross-match) is on the Transactions page.")

with right:
    st.markdown("**System status**")
    blocked = [e for e in entries if e.get("status") not in ("VERIFIED",) and e.get("exchange")]
    if blocked:
        for e in blocked:
            st.markdown(
                f"⚠️ {e.get('exchange', '?').upper()} {r2_data.CATEGORY_LABELS.get(e.get('category'), e.get('category'))}: "
                f"**{e.get('status')}** — {e.get('reason', 'no reason recorded')}"
            )
    else:
        st.success("No blocked or skipped datasets this run.")

    st.markdown("**Validation & Evidence**")
    rows_html = "".join(
        f'<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid {style.COLORS["border"]};font-size:12px;">'
        f'<span>{e.get("exchange","?").upper()} {r2_data.CATEGORY_LABELS.get(e.get("category"), e.get("category"))}</span>'
        f'{style.status_badge(e.get("status","MISSING"))}</div>'
        for e in entries
    )
    st.markdown(rows_html or "<em>No manifest entries.</em>", unsafe_allow_html=True)
    st.caption("Full audit on the Data Quality page.")
