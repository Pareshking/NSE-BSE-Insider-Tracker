import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import fields, r2_data, style

style.inject_base_css()

st.title("Evidence & Drill-down")
st.caption("Every individual transaction, with source fields and cross-match evidence. For rollups and signals, see Overview and Promoter Activity.")

client, dates = r2_data.page_gate()

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

# Columns formatted as compact currency (style.fmt_inr) rather than shown as
# raw numbers -- keeps this table visually consistent with every other page's
# currency display instead of reading as an unstyled dump of canonical_* rows.
CURRENCY_COLUMNS = {"canonical_value", "canonical_price", "canonical_amount_raised"}
QUANTITY_COLUMNS = {"canonical_quantity"}


def pretty_label(col: str) -> str:
    return col.replace("canonical_", "").replace("_", " ").title()

for tab, cat in zip(category, r2_data.CATEGORIES):
    with tab:
        with r2_data.guard(f"the {selected_date} run"):
            df = r2_data.load_combined(client, cat, exchanges, selected_date)
        if df.empty:
            st.caption(f"No {r2_data.CATEGORY_LABELS[cat]} rows for {selected_date} on {exchange_choice}.")
            continue

        filter_cols = st.columns(len(FILTERABLE.get(cat, [])) + 1)
        mask = pd.Series(True, index=df.index)
        for i, fcol in enumerate(FILTERABLE.get(cat, [])):
            if fcol not in df.columns:
                continue
            # key=str: a canonical column can carry mixed types across
            # NSE and BSE, and plain sorted() then raises "'<' not supported
            # between instances of 'int' and 'str'".
            options = sorted((v for v in df[fcol].dropna().unique() if v != ""), key=str)
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

        # Newest first. This table had no ordering at all, so it rendered in
        # whatever order the source happened to return -- the Rights Issues
        # tab opened on 14 Jul, 11 May, 30 Jun, 13 Jun, which reads as
        # unsorted noise. Sorting on the PARSED date matters as much as
        # sorting at all: the raw column mixes NSE ISO with BSE day-first, so
        # a plain string sort interleaves the two exchanges into an order
        # that is not chronological either.
        date_field = ("canonical_transaction_date" if "canonical_transaction_date" in filtered.columns
                      else "canonical_event_date")
        if date_field in filtered.columns:
            filtered = filtered.assign(_sort_date=fields.parse_dates(filtered[date_field])) \
                               .sort_values("_sort_date", ascending=False, na_position="last") \
                               .drop(columns=["_sort_date"])

        count_col, export_col = st.columns([3, 1])
        with count_col:
            st.caption(f"{len(filtered):,} of {len(df):,} rows")
        with export_col:
            # Every column, not just the displayed ones: the native source
            # fields are the point of this page, and an export that dropped
            # them would be less evidence than the screen it came from.
            style.download_csv(
                filtered, f"{cat}_{selected_date}_{exchange_choice.lower()}.csv",
                label="Export rows", key=f"dl-{cat}",
            )

        show_cols = [c for c in DISPLAY_COLUMNS[cat] if c in filtered.columns]
        display_df = filtered[show_cols].copy()
        date_col = "canonical_transaction_date" if "canonical_transaction_date" in display_df.columns else "canonical_event_date"
        if date_col in display_df.columns:
            display_df[date_col] = style.fmt_date_col(display_df[date_col])
        for col in CURRENCY_COLUMNS & set(display_df.columns):
            display_df[col] = display_df[col].map(style.fmt_inr)
        for col in QUANTITY_COLUMNS & set(display_df.columns):
            display_df[col] = display_df[col].map(style.fmt_qty)
        if "exchange" in display_df.columns:
            display_df["exchange"] = display_df["exchange"].astype(str).str.upper()

        event = st.dataframe(
            display_df,
            hide_index=True,
            use_container_width=True,
            on_select="rerun",
            selection_mode="single-row",
            key=f"table-{cat}",
            column_config={
                col: st.column_config.Column(label=pretty_label(col)) for col in display_df.columns
            },
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
                        label = pretty_label(col)
                        if col.endswith("_date"):
                            value = style.fmt_date(row[col])
                        elif col in CURRENCY_COLUMNS:
                            value = style.fmt_inr(row[col])
                        elif col in QUANTITY_COLUMNS:
                            value = style.fmt_qty(row[col])
                        else:
                            value = row[col]
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
