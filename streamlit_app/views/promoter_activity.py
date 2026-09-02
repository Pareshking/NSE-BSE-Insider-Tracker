"""Promoter Activity -- net-position rollup, not a raw trade list.

The point: NSE/BSE already show every individual insider trade. What they
don't show is the STORY those trades add up to -- ten small daily buys by
one promoter are the same underlying signal as one large purchase, and this
page is where that rollup happens. Two grains, both real, neither hides the
other: per (person, company) for "who is doing this," and per company for
"what's happening here overall, across everyone." No minimum-size filter --
every row is shown, sorted by the size of the net position so the real
signals surface on their own.
"""
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import fields, r2_data, style

st.markdown("### Promoter Activity")
st.caption("Net position rollups -- not a raw trade list. See Evidence & Drill-down for individual transactions.")

client, dates = r2_data.page_gate()

top = st.columns([1, 1, 2])
with top[0]:
    selected_date = st.selectbox("Run date", dates, index=0)
with top[1]:
    exchange_choice = st.radio("Exchange", ["Both", "NSE", "BSE"], horizontal=True, label_visibility="collapsed")
exchanges = r2_data.EXCHANGES if exchange_choice == "Both" else [exchange_choice.lower()]

with r2_data.guard(f"the {selected_date} run"):
    df = r2_data.load_combined(client, "insider_trading", exchanges, selected_date)
if df.empty:
    st.caption(f"No insider-trading rows for {selected_date} on {exchange_choice}.")
    st.stop()

# fields.parse_dates, not a bare pd.to_datetime: BSE rows carry Indian
# DD/MM/YYYY, which pandas' default reading turns into either the wrong day
# or NaT -- and a NaT silently drops the row from every window below.
df["_date"] = fields.parse_dates(df["canonical_transaction_date"])
run_date = df["_date"].max()

ttype = fields.text_col(df, "canonical_transaction_type", upper=True)
df["_signed_qty"] = fields.num_col(df, "canonical_quantity")
df["_signed_val"] = fields.num_col(df, "canonical_value")
is_disposal = ttype.str.contains("DISPOS")
is_acq = ttype.str.contains("ACQUI")
df.loc[is_disposal, ["_signed_qty", "_signed_val"]] *= -1
unrecognized = (~is_disposal & ~is_acq).sum()

WINDOWS = {"7D": 7, "30D": 30, "90D": 90}
window_label = st.radio("Window", list(WINDOWS.keys()), index=1, horizontal=True)
window_days = WINDOWS[window_label]
cutoff = run_date - pd.Timedelta(days=window_days - 1)
win_df = df[(df["_date"] >= cutoff) & (df["_date"] <= run_date)]

if unrecognized:
    st.caption(f"⚠️ {unrecognized} row(s) had a transaction type that wasn't recognized as ACQUISITION or DISPOSAL and are excluded from the net calculation (shown but not summed).")

# Materiality (Phase 0.5): NSE-only market cap, keyed by symbol -- see
# scripts/nse_market_cap.py. A given rupee/share number means something
# completely different for a small-cap vs a large-cap company; this is the
# normalizer for that. No BSE-listed-only names covered here yet.
with r2_data.guard("the market cap reference data"):
    mcap_lookup = r2_data.market_cap_lookup(client, selected_date)
mcap_available = mcap_lookup is not None
if mcap_available:
    win_df = win_df.copy()
    win_df["_market_cap"] = win_df["canonical_symbol"].astype(str).str.upper().map(mcap_lookup)
else:
    win_df = win_df.copy()
    win_df["_market_cap"] = pd.NA
    st.caption("⚠️ Market cap reference data isn't available for this run date -- showing absolute ₹/shares only, no % of market cap.")

sort_basis = st.radio(
    "Sort by", ["% of market cap", "Absolute ₹ value"], horizontal=True,
    disabled=not mcap_available,
    help="% of market cap needs Phase 0.5 reference data for this run date." if not mcap_available else None,
)


def fmt_signed_inr(v: float) -> str:
    sign = "-" if v < 0 else ""
    return sign + style.fmt_inr(abs(v))


def direction_badge(net: float) -> str:
    if net > 0:
        return style.badge("NET BUY", "green", "green_bg", dot=False)
    if net < 0:
        return style.badge("NET SELL", "red", "red_bg", dot=False)
    return style.badge("FLAT", "text_2", "bg_sub", dot=False)


def sparkline(daily: pd.Series) -> go.Figure:
    cum = daily.cumsum()
    color = style.COLORS["green"] if cum.iloc[-1] >= 0 else style.COLORS["red"]
    fig = go.Figure(go.Scatter(x=list(range(len(cum))), y=cum.values, mode="lines", line=dict(color=color, width=2)))
    fig.update_layout(
        height=40, margin=dict(l=0, r=0, t=0, b=0),
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
    )
    return fig


def apply_sort(grouped: pd.DataFrame) -> pd.DataFrame:
    if sort_basis == "% of market cap" and mcap_available:
        key = grouped["pct_mcap"].abs().fillna(-1)
    else:
        key = grouped["net_val"].abs()
    return grouped.reindex(key.sort_values(ascending=False).index)


def pct_mcap_html(pct: float) -> str:
    if pd.isna(pct):
        return f'<span style="color:{style.COLORS["text_3"]};font-size:11px;">n/a</span>'
    return f'<span class="mono">{pct:+.2f}%</span> <span style="color:{style.COLORS["text_3"]};font-size:11px;">of mcap</span>'


grain = st.tabs(["By Person", "By Company"])

with grain[0]:
    grouped = (
        win_df.groupby(["canonical_company", "canonical_person"], dropna=False)
        .agg(net_qty=("_signed_qty", "sum"), net_val=("_signed_val", "sum"), trades=("_signed_qty", "size"),
             market_cap=("_market_cap", "first"))
        .reset_index()
    )
    grouped["pct_mcap"] = 100 * grouped["net_val"] / grouped["market_cap"]
    grouped = apply_sort(grouped)
    sort_desc = "sorted by size of net position relative to company market cap, largest first" if sort_basis == "% of market cap" and mcap_available else "sorted by size of net position, largest first"
    st.caption(f"{len(grouped)} promoter/company pairs, {window_label} window ending {style.fmt_date(run_date)} -- {sort_desc}.")
    for _, row in grouped.head(20).iterrows():
        c1, c2, c3, c4, c5 = st.columns([2.3, 1.1, 1.1, 1.3, 1.4])
        with c1:
            sub_color = style.COLORS["text_2"]
            st.markdown(f"**{row['canonical_company']}**  \n<span style='color:{sub_color};font-size:12px;'>{row['canonical_person']}</span>", unsafe_allow_html=True)
        with c2:
            st.markdown(f'<span class="mono">{row["net_qty"]:,.0f}</span> sh', unsafe_allow_html=True)
        with c3:
            st.markdown(f'<span class="mono">{fmt_signed_inr(row["net_val"])}</span>', unsafe_allow_html=True)
        with c4:
            st.markdown(pct_mcap_html(row["pct_mcap"]), unsafe_allow_html=True)
        with c5:
            st.markdown(direction_badge(row["net_val"]) + f' <span style="color:{style.COLORS["text_3"]};font-size:11px;">· {int(row["trades"])} trades</span>', unsafe_allow_html=True)
        person_rows = win_df[(win_df["canonical_company"] == row["canonical_company"]) & (win_df["canonical_person"] == row["canonical_person"])].sort_values("_date")
        if len(person_rows) > 1:
            daily = person_rows.groupby(person_rows["_date"].dt.date)["_signed_qty"].sum()
            st.plotly_chart(sparkline(daily), use_container_width=True, config={"displayModeBar": False}, key=f"spark-p-{row['canonical_company']}-{row['canonical_person']}")
        with st.expander(f"{int(row['trades'])} transaction(s) -- what actually happened"):
            detail_rows = "".join(
                f'<tr><td class="mono">{style.fmt_date(r["_date"])}</td>'
                f'<td style="color:{style.COLORS["green"] if str(r.get("canonical_transaction_type")).upper().find("ACQUI")>=0 else style.COLORS["red"]};font-weight:600;">{r.get("canonical_transaction_type") or "—"}</td>'
                f'<td class="mono" style="text-align:right;">{r.get("canonical_quantity") or 0:,.0f}</td>'
                f'<td class="mono" style="text-align:right;">{style.fmt_inr(r.get("canonical_value"))}</td>'
                f'<td style="text-align:right;">{style.exchange_badge(r.get("exchange") or "")}</td></tr>'
                for _, r in person_rows.iterrows()
            )
            st.markdown(
                '<div class="table-scroll"><table class="evt-table"><tr><th>DATE</th><th>TYPE</th><th style="text-align:right;">QTY</th>'
                '<th style="text-align:right;">VALUE</th><th style="text-align:right;">EXCH</th></tr>'
                + detail_rows + "</table></div>",
                unsafe_allow_html=True,
            )
        st.markdown(f'<hr style="margin:2px 0 10px 0;border:none;border-top:1px solid {style.COLORS["border"]};">', unsafe_allow_html=True)
    if len(grouped) > 20:
        st.caption(f"{len(grouped) - 20} more pairs not shown as charts -- full list below.")
        st.dataframe(
            grouped.iloc[20:].rename(columns={"canonical_company": "Company", "canonical_person": "Person", "net_qty": "Net Qty", "net_val": "Net Value", "pct_mcap": "% of Mcap", "trades": "Trades"}),
            hide_index=True, use_container_width=True,
        )

with grain[1]:
    grouped_c = (
        win_df.groupby("canonical_company", dropna=False)
        .agg(net_qty=("_signed_qty", "sum"), net_val=("_signed_val", "sum"), trades=("_signed_qty", "size"),
             promoters=("canonical_person", "nunique"), market_cap=("_market_cap", "first"))
        .reset_index()
    )
    grouped_c["pct_mcap"] = 100 * grouped_c["net_val"] / grouped_c["market_cap"]
    grouped_c = apply_sort(grouped_c)
    sort_desc = "sorted by size of net position relative to company market cap, largest first" if sort_basis == "% of market cap" and mcap_available else "sorted by size of net position, largest first"
    st.caption(f"{len(grouped_c)} companies, {window_label} window -- all promoters/insiders combined per company, {sort_desc}.")
    for _, row in grouped_c.head(20).iterrows():
        c1, c2, c3, c4, c5 = st.columns([2.3, 1.1, 1.1, 1.3, 1.4])
        with c1:
            sub_color = style.COLORS["text_2"]
            st.markdown(f"**{row['canonical_company']}**  \n<span style='color:{sub_color};font-size:12px;'>{int(row['promoters'])} distinct promoter(s)/insider(s)</span>", unsafe_allow_html=True)
        with c2:
            st.markdown(f'<span class="mono">{row["net_qty"]:,.0f}</span> sh', unsafe_allow_html=True)
        with c3:
            st.markdown(f'<span class="mono">{fmt_signed_inr(row["net_val"])}</span>', unsafe_allow_html=True)
        with c4:
            st.markdown(pct_mcap_html(row["pct_mcap"]), unsafe_allow_html=True)
        with c5:
            st.markdown(direction_badge(row["net_val"]) + f' <span style="color:{style.COLORS["text_3"]};font-size:11px;">· {int(row["trades"])} trades</span>', unsafe_allow_html=True)
        company_rows = win_df[win_df["canonical_company"] == row["canonical_company"]].sort_values("_date")
        if len(company_rows) > 1:
            daily = company_rows.groupby(company_rows["_date"].dt.date)["_signed_qty"].sum()
            st.plotly_chart(sparkline(daily), use_container_width=True, config={"displayModeBar": False}, key=f"spark-c-{row['canonical_company']}")
        with st.expander(f"{int(row['trades'])} transaction(s) -- what actually happened"):
            detail_rows = "".join(
                f'<tr><td class="mono">{style.fmt_date(r["_date"])}</td>'
                f'<td style="font-weight:500;">{r.get("canonical_person") or "—"}</td>'
                f'<td style="color:{style.COLORS["green"] if str(r.get("canonical_transaction_type")).upper().find("ACQUI")>=0 else style.COLORS["red"]};font-weight:600;">{r.get("canonical_transaction_type") or "—"}</td>'
                f'<td class="mono" style="text-align:right;">{r.get("canonical_quantity") or 0:,.0f}</td>'
                f'<td class="mono" style="text-align:right;">{style.fmt_inr(r.get("canonical_value"))}</td>'
                f'<td style="text-align:right;">{style.exchange_badge(r.get("exchange") or "")}</td></tr>'
                for _, r in company_rows.iterrows()
            )
            st.markdown(
                '<div class="table-scroll"><table class="evt-table"><tr><th>DATE</th><th>PERSON</th><th>TYPE</th><th style="text-align:right;">QTY</th>'
                '<th style="text-align:right;">VALUE</th><th style="text-align:right;">EXCH</th></tr>'
                + detail_rows + "</table></div>",
                unsafe_allow_html=True,
            )
        st.markdown(f'<hr style="margin:2px 0 10px 0;border:none;border-top:1px solid {style.COLORS["border"]};">', unsafe_allow_html=True)
    if len(grouped_c) > 20:
        st.caption(f"{len(grouped_c) - 20} more companies not shown as charts -- full list below.")
        st.dataframe(
            grouped_c.iloc[20:].rename(columns={"canonical_company": "Company", "net_qty": "Net Qty", "net_val": "Net Value", "pct_mcap": "% of Mcap", "trades": "Trades", "promoters": "Promoters"}),
            hide_index=True, use_container_width=True,
        )
