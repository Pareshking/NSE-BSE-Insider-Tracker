import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import r2_data, style

style.inject_base_css()

st.title("Evidence & Drill-down")
st.caption("Every individual transaction, with source fields and cross-match evidence. For rollups and signals, see Overview and Promoter Activity.")

client = r2_data.get_client()
if not r2_data.r2_configured():
    st.warning("R2 credentials aren't configured -- see the Overview page for what's needed.")
    st.stop()

dates = r2_data.list_manifest_dates(client)
if not dates:
    st.info("No manifests found in the bucket yet.")
    st.stop()

top = st.columns([1, 1, 3])
with top[0]:
    selected_date = st.selectbox("Run date", dates, index=0)
with top[1]:
    exchange_choice = st.radio("Exchange", ["Both", "NSE", "BSE"], horizontal=True)

category = st.tabs([r2_data.CATEGORY_LABELS[c] for c in r2_data.CATEGORIES])

exchanges = r2_data.EXCHANGES if exchange_choice == "Both" else [exchange_choice.lower()]

# Per-category display column sets, drawn straight from canonicalize()'s
# output fields in scripts/r2_writer.py -- kept aligned by hand since that's
# the single source of truth for what these fields mean.
DISPLAY_COLUMNS = {
    "insider_trading": [
        "canonical_transaction_date", "canonical_company", "canonical_symbol",
        "canonical_person", "canonical_person_category", "canonical_transaction_type",
        "canonical_quantity", "canonical_value", "canonical_isin", "exchange",
    ],
    "bulk_deals": [
        "canonical_event_date", "canonical_company", "canonical_symbol",
        "canonical_client", "canonical_side", "canonical_quantity", "canonical_price",
        "canonical_isin", "exchange",
    ],
    "block_deals": [
        "canonical_event_date", "canonical_company", "canonical_symbol",
        "canonical_client", "canonical_side", "canonical_quantity", "canonical_price",
        "canonical_isin", "exchange",
    ],
    "rights_issue": [
        "canonical_event_date", "canonical_company", "canonical_company_unreliable",
        "canonical_symbol", "canonical_stage", "canonical_amount_raised",
        "canonical_isin", "exchange",
    ],
    "preferential_issue": [
        "canonical_event_date", "canonical_company", "canonical_company_unreliable",
        "canonical_symbol", "canonical_stage", "canonical_allottee_category",
        "canonical_amount_raised", "canonical_isin", "exchange",
    ],
}

FILTERABLE = {
    "insider_trading": ["canonical_person_category", "canonical_transaction_type"],
    "bulk_deals": ["canonical_side"],
    "block_deals": ["canonical_side"],
    "rights_issue": ["canonical_stage"],
    "preferential_issue": ["canonical_stage", "canonical_allottee_category"],
}

for tab, cat in zip(category, r2_data.CATEGORIES):
    with tab:
        dfs = [r2_data.load_canonical(client, ex, cat, selected_date) for ex in exchanges]
        dfs = [d for d in dfs if not d.empty]
        if not dfs:
            st.caption(f"No {r2_data.CATEGORY_LABELS[cat]} rows for {selected_date} on {exchange_choice}.")
            continue
        df = pd.concat(dfs, ignore_index=True)

        filter_cols = st.columns(len(FILTERABLE.get(cat, [])) + 1)
        mask = pd.Series(True, index=df.index)
        for i, fcol in enumerate(FILTERABLE.get(cat, [])):
            if fcol not in df.columns:
                continue
            options = sorted(v for v in df[fcol].dropna().unique() if v)
            with filter_cols[i]:
                picked = st.multiselect(fcol.replace("canonical_", "").replace("_", " ").title(), options, key=f"{cat}-{fcol}")
            if picked:
                mask &= df[fcol].isin(picked)
        with filter_cols[-1]:
            search = st.text_input("Search company / person / ISIN", key=f"{cat}-search")
        if search:
            search_l = search.lower()
            text_cols = [c for c in df.columns if df[c].dtype == object]
            row_mask = df[text_cols].apply(
                lambda col: col.astype(str).str.lower().str.contains(search_l, na=False)
            ).any(axis=1)
            mask &= row_mask

        filtered = df[mask]
        st.caption(f"{len(filtered):,} of {len(df):,} rows")

        show_cols = [c for c in DISPLAY_COLUMNS[cat] if c in filtered.columns]
        display_df = filtered[show_cols + ["canonical_event_id"]] if "canonical_event_id" in filtered.columns else filtered[show_cols]
        display_df = display_df.drop(columns=["canonical_event_id"], errors="ignore")
        date_col = "canonical_transaction_date" if "canonical_transaction_date" in display_df.columns else "canonical_event_date"
        if date_col in display_df.columns:
            display_df = display_df.copy()
            display_df[date_col] = style.fmt_date_col(display_df[date_col])

        event = st.dataframe(
            display_df,
            hide_index=True,
            use_container_width=True,
            on_select="rerun",
            selection_mode="single-row",
            key=f"table-{cat}",
        )

        selected_rows = event.selection.rows if event and event.selection else []
        if selected_rows:
            row = filtered.iloc[selected_rows[0]]

            has_match = pd.notna(row.get("cross_exchange_possible_match_id"))

            @st.dialog("Evidence")
            def show_evidence(row=row, cat=cat, has_match=has_match):
                st.markdown(
                    f'{style.exchange_badge(row.get("exchange",""))} '
                    f'{style.badge("Cross-exchange match", "blue", "blue_bg", dot=False) if has_match else style.badge("No match this run", "text_3", "bg_sub", dot=False)}',
                    unsafe_allow_html=True,
                )
                st.markdown('<div class="sec-title">CANONICAL FIELDS</div>', unsafe_allow_html=True)
                for col in DISPLAY_COLUMNS[cat]:
                    if col in row.index and pd.notna(row[col]):
                        label = col.replace("canonical_", "").replace("_", " ").title()
                        value = style.fmt_date(row[col]) if col.endswith("_date") else row[col]
                        st.markdown(
                            f'<div class="kv-row"><span style="color:{style.COLORS["text_2"]};">{label}</span><span class="mono">{value}</span></div>',
                            unsafe_allow_html=True,
                        )
                if has_match:
                    st.markdown('<div class="sec-title">CROSS-EXCHANGE MATCH</div>', unsafe_allow_html=True)
                    st.markdown(
                        f'<div class="kv-row"><span style="color:{style.COLORS["text_2"]};">Basis</span>'
                        f'<span class="mono">{row.get("cross_exchange_match_basis")}</span></div>'
                        f'<div class="kv-row"><span style="color:{style.COLORS["text_2"]};">Confidence</span>'
                        f'<span class="mono">{row.get("cross_exchange_match_confidence")}</span></div>',
                        unsafe_allow_html=True,
                    )
                st.markdown('<div class="sec-title">NATIVE FIELDS</div>', unsafe_allow_html=True)
                native_cols = [
                    c for c in row.index
                    if not c.startswith("canonical_") and not c.startswith("cross_exchange_")
                    and c not in ("exchange", "category")
                ]
                st.json({c: row[c] for c in native_cols if pd.notna(row[c])}, expanded=False)

            show_evidence()

        st.caption("Row selection opens the evidence view — native fields, cross-exchange match basis, all preserved alongside the aligned canonical_* columns.")
