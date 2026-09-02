"""Bulk & Block Concentration -- Phase 2 of ANALYTICS_PLAN.md.

Same principle as Promoter Activity: NSE/BSE already publish every
individual bulk/block deal. What's missing is the rollup that turns a list
of trades into a signal -- which securities have concentrated client
activity (a handful of clients moving most of the volume), which individual
deals are large relative to the company's own size, and who the repeat
clients are. Two grains, both real, decided the same way Promoter Activity's
were: "By Security" (who's active in this stock) and "By Client" (what is
this client doing across stocks) -- neither hides the other.

Bulk and Block are shown as separate tabs, not merged into one pool --
they are legally/structurally distinct deal types (bulk: >0.5% of a
company's shares in one trade; block: pre-negotiated large trades in a
separate window) and conflating them would misrepresent both.
"""
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import fields, r2_data, style

st.markdown("### Bulk & Block Concentration")
st.caption("Client concentration and largest transactions -- not a raw deal list. See Evidence & Drill-down for individual transactions.")

client, dates = r2_data.page_gate()

top = st.columns([1, 1, 2])
with top[0]:
    selected_date = st.selectbox("Run date", dates, index=0)
with top[1]:
    exchange_choice = st.radio("Exchange", ["Both", "NSE", "BSE"], horizontal=True, label_visibility="collapsed")
exchanges = r2_data.EXCHANGES if exchange_choice == "Both" else [exchange_choice.lower()]

deal_type = st.tabs(["Bulk Deals", "Block Deals"])
CATEGORY_BY_TAB = {"Bulk Deals": "bulk_deals", "Block Deals": "block_deals"}

with r2_data.guard("the market cap reference data"):
    mcap_lookup = r2_data.market_cap_lookup(client, selected_date)


def fmt_signed_inr(v: float) -> str:
    sign = "-" if v < 0 else ""
    return sign + style.fmt_inr(abs(v))


def pct_mcap_html(pct) -> str:
    if pct is None or pd.isna(pct):
        return f'<span style="color:{style.COLORS["text_3"]};font-size:11px;">n/a</span>'
    return f'<span class="mono">{pct:+.2f}%</span> <span style="color:{style.COLORS["text_3"]};font-size:11px;">of mcap</span>'


def concentration_badge(share: float) -> str:
    """Top-3-client share of a security's total traded value this window.
    Thresholds are a judgment call (no house convention existed for this
    project before Phase 2): >60% reads as concentrated in practice for
    bulk/block deals (a handful of institutional clients dominating one
    name), <30% as broad participation. No claim of statistical rigor --
    labeled 'concentrated'/'broad', not backed by a formal HHI cutoff."""
    if share >= 0.6:
        return style.badge("CONCENTRATED", "red", "red_bg", dot=False)
    if share >= 0.3:
        return style.badge("MODERATE", "amber", "amber_bg", dot=False)
    return style.badge("BROAD", "green", "green_bg", dot=False)


def sparkline(daily: pd.Series, color: str) -> go.Figure:
    fig = go.Figure(go.Scatter(x=list(range(len(daily))), y=daily.values, mode="lines", line=dict(color=color, width=2)))
    fig.update_layout(
        height=40, margin=dict(l=0, r=0, t=0, b=0),
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
    )
    return fig


for tab, tab_name in zip(deal_type, CATEGORY_BY_TAB):
    category = CATEGORY_BY_TAB[tab_name]
    with tab:
        with r2_data.guard(f"the {selected_date} run"):
            df = r2_data.load_combined(client, category, exchanges, selected_date)
        if df.empty:
            st.caption(f"No {tab_name.lower()} for {selected_date} on {exchange_choice}.")
            continue

        # fields.parse_dates, not a bare pd.to_datetime: BSE bulk/block rows
        # carry Indian DD/MM/YYYY, which pandas' default reading turns into
        # NaT -- silently dropping every BSE row from the windows below.
        df["_date"] = fields.parse_dates(df["canonical_event_date"])
        run_date = df["_date"].max()
        df["_qty"] = fields.num_col(df, "canonical_quantity")
        df["_price"] = fields.num_col(df, "canonical_price")
        df["_value"] = df["_qty"] * df["_price"]
        if mcap_lookup is not None:
            df["_market_cap"] = df["canonical_symbol"].astype(str).str.upper().map(mcap_lookup)
        else:
            df["_market_cap"] = pd.NA

        window_label = st.radio("Window", ["7D", "30D", "90D"], index=1, horizontal=True, key=f"win-{category}")
        window_days = {"7D": 7, "30D": 30, "90D": 90}[window_label]
        cutoff = run_date - pd.Timedelta(days=window_days - 1)
        win_df = df[(df["_date"] >= cutoff) & (df["_date"] <= run_date)]

        # Both concentration grains are defined by who the counterparty was,
        # so without canonical_client there is nothing honest to compute:
        # folding every row into one unnamed client would report 100%
        # concentration on every security. Say the field is missing and
        # offer the one view that doesn't depend on it.
        has_client = "canonical_client" in win_df.columns
        grain_options = ["By Security", "By Client", "Largest Transactions"] if has_client else ["Largest Transactions"]
        grain = st.radio("View", grain_options, horizontal=True, key=f"grain-{category}")
        if not has_client:
            st.caption(
                f"⚠️ This run's {tab_name.lower()} carry no client field, so the concentration views "
                "(By Security, By Client) can't be computed -- showing individual transactions only."
            )

        if grain == "Largest Transactions":
            largest = win_df.sort_values("_value", ascending=False).head(30)
            st.caption(f"Top 30 individual {tab_name.lower()} by value, {window_label} window ending {style.fmt_date(run_date)}.")
            rows_html = []
            for _, r in largest.iterrows():
                pct = 100 * r["_value"] / r["_market_cap"] if pd.notna(r["_market_cap"]) and r["_market_cap"] else None
                side_color = "green" if str(r.get("canonical_side")).upper() == "BUY" else ("red" if str(r.get("canonical_side")).upper() == "SELL" else "text_2")
                rows_html.append(
                    f'<tr><td class="mono">{style.fmt_date(r["_date"])}</td>'
                    f'<td style="font-weight:500;">{r.get("canonical_company") or "—"}</td>'
                    f'<td style="color:{style.COLORS["text_2"]};">{r.get("canonical_client") or "—"}</td>'
                    f'<td style="color:{style.COLORS[side_color]};font-weight:500;">{r.get("canonical_side") or "—"}</td>'
                    f'<td class="mono" style="text-align:right;">{r["_qty"]:,.0f}</td>'
                    f'<td class="mono" style="text-align:right;">{style.fmt_inr(r["_value"])}</td>'
                    f'<td style="text-align:right;">{pct_mcap_html(pct)}</td>'
                    f'<td style="text-align:right;">{style.exchange_badge(r.get("exchange") or "")}</td></tr>'
                )
            st.markdown(
                '<table class="evt-table"><tr><th>DATE</th><th>COMPANY</th><th>CLIENT</th><th>SIDE</th>'
                '<th style="text-align:right;">QTY</th><th style="text-align:right;">VALUE</th>'
                '<th style="text-align:right;">% MCAP</th><th style="text-align:right;">EXCH</th></tr>'
                + "".join(rows_html) + "</table>",
                unsafe_allow_html=True,
            )
            continue

        if grain == "By Security":
            grouped = (
                win_df.groupby(["canonical_company", "canonical_symbol"], dropna=False)
                .agg(total_value=("_value", "sum"), total_qty=("_qty", "sum"), trades=("_value", "size"),
                     distinct_clients=("canonical_client", "nunique"), market_cap=("_market_cap", "first"))
                .reset_index()
            )
            # Concentration: top-3 clients' share of this security's total value in the window.
            def top3_share(sub):
                by_client = sub.groupby("canonical_client")["_value"].sum().sort_values(ascending=False)
                total = by_client.sum()
                return (by_client.head(3).sum() / total) if total else 0.0
            grouped["top3_share"] = grouped.apply(
                lambda row: top3_share(win_df[win_df["canonical_symbol"] == row["canonical_symbol"]]), axis=1
            )
            grouped["pct_mcap"] = 100 * grouped["total_value"] / grouped["market_cap"]
            grouped = grouped.sort_values("total_value", ascending=False)
            st.caption(f"{len(grouped)} securities, {window_label} window -- sorted by total traded value, largest first.")
            for _, row in grouped.head(20).iterrows():
                c1, c2, c3, c4, c5 = st.columns([2.3, 1.2, 1.2, 1.3, 1.4])
                with c1:
                    st.markdown(f"**{row['canonical_company']}**  \n<span style='color:{style.COLORS['text_2']};font-size:12px;'>{int(row['distinct_clients'])} distinct client(s) · {int(row['trades'])} trades</span>", unsafe_allow_html=True)
                with c2:
                    st.markdown(f'<span class="mono">{row["total_qty"]:,.0f}</span> sh', unsafe_allow_html=True)
                with c3:
                    st.markdown(f'<span class="mono">{style.fmt_inr(row["total_value"])}</span>', unsafe_allow_html=True)
                with c4:
                    st.markdown(pct_mcap_html(row["pct_mcap"]), unsafe_allow_html=True)
                with c5:
                    st.markdown(concentration_badge(row["top3_share"]) + f' <span style="color:{style.COLORS["text_3"]};font-size:11px;">· top3 {row["top3_share"]*100:.0f}%</span>', unsafe_allow_html=True)
                sec_rows = win_df[win_df["canonical_symbol"] == row["canonical_symbol"]].sort_values("_date")
                if len(sec_rows) > 1:
                    daily = sec_rows.groupby(sec_rows["_date"].dt.date)["_value"].sum()
                    st.plotly_chart(sparkline(daily, style.COLORS["blue"]), use_container_width=True, config={"displayModeBar": False}, key=f"spark-sec-{category}-{row['canonical_symbol']}")
                with st.expander(f"{int(row['trades'])} trade(s) -- who, when, how much"):
                    detail_rows = "".join(
                        f'<tr><td class="mono">{style.fmt_date(r["_date"])}</td>'
                        f'<td style="font-weight:500;">{r.get("canonical_client") or "—"}</td>'
                        f'<td style="color:{style.COLORS["green"] if str(r.get("canonical_side")).upper() == "BUY" else style.COLORS["red"]};font-weight:600;">{r.get("canonical_side") or "—"}</td>'
                        f'<td class="mono" style="text-align:right;">{r["_qty"]:,.0f}</td>'
                        f'<td class="mono" style="text-align:right;">{style.fmt_inr(r["_value"])}</td>'
                        f'<td style="text-align:right;">{style.exchange_badge(r.get("exchange") or "")}</td></tr>'
                        for _, r in sec_rows.iterrows()
                    )
                    st.markdown(
                        '<table class="evt-table"><tr><th>DATE</th><th>CLIENT</th><th>SIDE</th>'
                        '<th style="text-align:right;">QTY</th><th style="text-align:right;">VALUE</th><th style="text-align:right;">EXCH</th></tr>'
                        + detail_rows + "</table>",
                        unsafe_allow_html=True,
                    )
                st.markdown(f'<hr style="margin:2px 0 10px 0;border:none;border-top:1px solid {style.COLORS["border"]};">', unsafe_allow_html=True)
            if len(grouped) > 20:
                st.caption(f"{len(grouped) - 20} more securities -- full list below.")
                st.dataframe(
                    grouped.iloc[20:][["canonical_company", "canonical_symbol", "total_qty", "total_value", "pct_mcap", "trades", "distinct_clients", "top3_share"]]
                    .rename(columns={"canonical_company": "Company", "canonical_symbol": "Symbol", "total_qty": "Total Qty",
                                      "total_value": "Total Value", "pct_mcap": "% of Mcap", "trades": "Trades",
                                      "distinct_clients": "Clients", "top3_share": "Top-3 Share"}),
                    hide_index=True, use_container_width=True,
                )

        else:  # By Client
            grouped_c = (
                win_df.groupby("canonical_client", dropna=False)
                .agg(total_value=("_value", "sum"), total_qty=("_qty", "sum"), trades=("_value", "size"),
                     distinct_securities=("canonical_symbol", "nunique"))
                .reset_index()
            )
            grouped_c = grouped_c.sort_values("total_value", ascending=False)
            st.caption(f"{len(grouped_c)} clients, {window_label} window -- sorted by total traded value, largest first.")
            for _, row in grouped_c.head(20).iterrows():
                c1, c2, c3, c4 = st.columns([2.5, 1.2, 1.4, 1.5])
                with c1:
                    st.markdown(f"**{row['canonical_client'] or '—'}**  \n<span style='color:{style.COLORS['text_2']};font-size:12px;'>{int(row['distinct_securities'])} distinct security/ies</span>", unsafe_allow_html=True)
                with c2:
                    st.markdown(f'<span class="mono">{row["total_qty"]:,.0f}</span> sh', unsafe_allow_html=True)
                with c3:
                    st.markdown(f'<span class="mono">{style.fmt_inr(row["total_value"])}</span>', unsafe_allow_html=True)
                with c4:
                    st.markdown(f'<span style="color:{style.COLORS["text_3"]};font-size:11px;">{int(row["trades"])} trades</span>', unsafe_allow_html=True)
                client_rows = win_df[win_df["canonical_client"] == row["canonical_client"]].sort_values("_date")
                if len(client_rows) > 1:
                    daily = client_rows.groupby(client_rows["_date"].dt.date)["_value"].sum()
                    st.plotly_chart(sparkline(daily, style.COLORS["blue"]), use_container_width=True, config={"displayModeBar": False}, key=f"spark-cl-{category}-{row['canonical_client']}")
                with st.expander(f"{int(row['trades'])} trade(s) -- which securities, when, how much"):
                    detail_rows = "".join(
                        f'<tr><td class="mono">{style.fmt_date(r["_date"])}</td>'
                        f'<td style="font-weight:500;">{r.get("canonical_company") or "—"}</td>'
                        f'<td style="color:{style.COLORS["green"] if str(r.get("canonical_side")).upper() == "BUY" else style.COLORS["red"]};font-weight:600;">{r.get("canonical_side") or "—"}</td>'
                        f'<td class="mono" style="text-align:right;">{r["_qty"]:,.0f}</td>'
                        f'<td class="mono" style="text-align:right;">{style.fmt_inr(r["_value"])}</td>'
                        f'<td style="text-align:right;">{style.exchange_badge(r.get("exchange") or "")}</td></tr>'
                        for _, r in client_rows.iterrows()
                    )
                    st.markdown(
                        '<table class="evt-table"><tr><th>DATE</th><th>SECURITY</th><th>SIDE</th>'
                        '<th style="text-align:right;">QTY</th><th style="text-align:right;">VALUE</th><th style="text-align:right;">EXCH</th></tr>'
                        + detail_rows + "</table>",
                        unsafe_allow_html=True,
                    )
                st.markdown(f'<hr style="margin:2px 0 10px 0;border:none;border-top:1px solid {style.COLORS["border"]};">', unsafe_allow_html=True)
            if len(grouped_c) > 20:
                st.caption(f"{len(grouped_c) - 20} more clients -- full list below.")
                st.dataframe(
                    grouped_c.iloc[20:].rename(columns={"canonical_client": "Client", "total_qty": "Total Qty",
                                                          "total_value": "Total Value", "trades": "Trades",
                                                          "distinct_securities": "Securities"}),
                    hide_index=True, use_container_width=True,
                )
