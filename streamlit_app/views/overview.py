import sys
import warnings
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import r2_data, style

client = r2_data.get_client()

if not r2_data.r2_configured():
    st.title("Overview")
    st.warning(
        "R2 credentials aren't configured for this app, so there's no data to show yet. "
        "Set `CLOUDFLARE_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, "
        "`R2_BUCKET_NAME` in `.streamlit/secrets.toml` (or as env vars) -- the same "
        "values already used by the GitHub Actions R2-storage workflow."
    )
    st.stop()

dates = r2_data.list_manifest_dates(client)
if not dates:
    st.title("Overview")
    st.info("No manifests found in the bucket yet -- the R2 write workflow hasn't run, or hasn't produced output for any date.")
    st.stop()

# --- header bar: title + exchange toggle + date selector + search + certification badges ---
h1, h2, h3, h5, h4 = st.columns([1.6, 1.4, 1.3, 2.2, 2.1])
with h1:
    st.markdown("### Overview")
with h2:
    exchange_choice = st.radio("Exchange", ["Both", "NSE", "BSE"], horizontal=True, label_visibility="collapsed")
with h3:
    selected_date = st.selectbox("Run date", dates, index=0, label_visibility="collapsed")
with h5:
    search_query = st.text_input(
        "Search", placeholder="Search company, person, symbol…",
        label_visibility="collapsed", key="overview_search",
    )

manifest = r2_data.load_manifest(client, selected_date)
entries = manifest.get("datasets", manifest if isinstance(manifest, list) else [])
if isinstance(entries, dict):
    entries = list(entries.values())

if manifest.get("backfilled"):
    st.info(
        f"This date's data was backfilled by the {style.fmt_date(manifest.get('backfilled_from_run_date'))} run "
        "-- the scheduled run for this day didn't produce a manifest (a failed run, most likely), so this is a "
        "catch-up write from a later day's already-fetched data, not a same-day capture.",
        icon="🔄",
    )

nse_ok = any(e.get("exchange") == "nse" and e.get("status") == "VERIFIED" for e in entries)
bse_ok = any(e.get("exchange") == "bse" and e.get("status") == "VERIFIED" for e in entries)
nse_all = all(e.get("status") == "VERIFIED" for e in entries if e.get("exchange") == "nse") and nse_ok
bse_all = all(e.get("status") == "VERIFIED" for e in entries if e.get("exchange") == "bse") and bse_ok
with h4:
    st.markdown(
        f'<div style="display:flex;gap:6px;justify-content:flex-end;padding-top:6px;">'
        f'{style.badge("BSE certified" if bse_all else "BSE partial", "green" if bse_all else "amber", "green_bg" if bse_all else "amber_bg")}'
        f'{style.badge("NSE certified" if nse_all else "NSE partial", "green" if nse_all else "amber", "green_bg" if nse_all else "amber_bg")}'
        f"</div>",
        unsafe_allow_html=True,
    )

exchanges = r2_data.EXCHANGES if exchange_choice == "Both" else [exchange_choice.lower()]
data = {(ex, cat): r2_data.load_canonical(client, ex, cat, selected_date) for ex in exchanges for cat in r2_data.CATEGORIES}
insider_df = pd.concat([data.get((ex, "insider_trading"), pd.DataFrame()) for ex in exchanges], ignore_index=True) if exchanges else pd.DataFrame()

# Rights/preferential carry event dates from way earlier (or, for some
# corporate-action fields, later -- e.g. a record date) in a listing's
# lifecycle than the actual disclosure -- some run years off in either
# direction. Window "today's signals" to the same 90D the acquisition
# pipeline requests, both bounds, or a handful of stray rows swamp what's
# supposed to be a recent-activity view (confirmed 2026-09-02 against real
# data: unbounded above, the trend chart's x-axis ran three months past the
# run date).
_signal_anchor = pd.to_datetime(selected_date, errors="coerce")
_signal_upper = _signal_anchor.date() if pd.notna(_signal_anchor) else None
_signal_cutoff = (_signal_anchor - pd.Timedelta(days=89)).date() if pd.notna(_signal_anchor) else None

# --- slim category-count strip: full per-category detail lives on Evidence
# & Drill-down (already tabbed by category); this is just "where's the
# volume", not a second copy of that page. ---
status_by_key = {(e.get("exchange"), e.get("category")): e for e in entries}
strip_html = []
for category in r2_data.CATEGORIES:
    df = pd.concat([data.get((ex, category), pd.DataFrame()) for ex in exchanges], ignore_index=True) if exchanges else pd.DataFrame()
    any_written = any(status_by_key.get((ex, category), {}).get("written") for ex in r2_data.EXCHANGES)
    fg, bg = ("text", "bg_sub") if any_written else ("amber", "amber_bg")
    strip_html.append(
        f'<span class="badge" style="background:{style.COLORS[bg]};color:{style.COLORS[fg]};font-weight:600;">'
        f'{r2_data.CATEGORY_LABELS[category]} <span class="mono" style="font-weight:700;">{len(df):,}</span></span>'
    )
st.markdown(f'<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:4px;">{"".join(strip_html)}</div>', unsafe_allow_html=True)
st.caption("Full category-by-category browsing (filters, search, evidence drill-down) is on the Evidence & Drill-down page.")

st.write("")
st.markdown('<div style="font-size:14px;font-weight:700;margin-bottom:2px;">Today\'s Signals</div>', unsafe_allow_html=True)
st.caption("Cross-category highlights, not raw counts -- who's buying/selling with conviction, what's big, where volume is concentrated.")

sig1, sig2, sig3 = st.columns([1, 1.3, 1])

with sig1:
    st.markdown('<div style="font-size:12px;font-weight:700;margin-bottom:10px;">Net Promoter Buyers / Sellers</div>', unsafe_allow_html=True)
    if insider_df.empty:
        st.caption("No insider-trading data.")
    else:
        pdf = insider_df.copy()
        person_cat = pdf.get("canonical_person_category", pd.Series(dtype=object)).astype(str).str.upper()
        ttype = pdf.get("canonical_transaction_type", pd.Series(dtype=object)).astype(str).str.upper()
        promoter_rows = pdf[person_cat.str.contains("PROMOTER")].copy()
        signed_val = pd.to_numeric(promoter_rows.get("canonical_value"), errors="coerce").fillna(0)
        signed_val = signed_val.where(~ttype.loc[promoter_rows.index].str.contains("DISPOS"), -signed_val)
        promoter_rows["_signed_val"] = signed_val
        net = promoter_rows.groupby("canonical_company")["_signed_val"].sum()
        buyers, sellers = net[net > 0].sort_values(ascending=False).head(3), net[net < 0].sort_values().head(3)
        if buyers.empty and sellers.empty:
            st.caption("No promoter acquisitions/disposals this run.")
        for company, val in buyers.items():
            st.markdown(
                f'<div style="display:flex;justify-content:space-between;font-size:12px;padding:5px 0;border-bottom:1px solid {style.COLORS["border"]};">'
                f'<span>{style.badge("BUY", "green", "green_bg", dot=False)} {company}</span>'
                f'<span class="mono">{style.fmt_inr(val)}</span></div>',
                unsafe_allow_html=True,
            )
        for company, val in sellers.items():
            st.markdown(
                f'<div style="display:flex;justify-content:space-between;font-size:12px;padding:5px 0;border-bottom:1px solid {style.COLORS["border"]};">'
                f'<span>{style.badge("SELL", "red", "red_bg", dot=False)} {company}</span>'
                f'<span class="mono">-{style.fmt_inr(abs(val))}</span></div>',
                unsafe_allow_html=True,
            )
    st.caption("Full net-position rollup is on Promoter Activity.")

with sig2:
    st.markdown('<div style="font-size:12px;font-weight:700;margin-bottom:10px;">Biggest Transactions — All Categories</div>', unsafe_allow_html=True)
    # A single ranked feed across all 5 categories -- not just insider
    # trading -- since a big bulk deal or preferential allotment is just as
    # much "what happened today" as an insider filing.
    combined_rows = []
    for category in r2_data.CATEGORIES:
        df = pd.concat([data.get((ex, category), pd.DataFrame()) for ex in exchanges], ignore_index=True) if exchanges else pd.DataFrame()
        if df.empty:
            continue
        df = df.copy()
        if category == "insider_trading":
            df["_value"] = pd.to_numeric(df.get("canonical_value"), errors="coerce")
            df["_date"] = df.get("canonical_transaction_date")
        elif category in ("bulk_deals", "block_deals"):
            df["_value"] = pd.to_numeric(df.get("canonical_quantity"), errors="coerce") * pd.to_numeric(df.get("canonical_price"), errors="coerce")
            df["_date"] = df.get("canonical_event_date")
        else:
            df["_value"] = pd.to_numeric(df.get("canonical_amount_raised"), errors="coerce")
            df["_date"] = df.get("canonical_event_date")
        df["_category"] = category
        combined_rows.append(df[["_value", "_date", "_category", "canonical_company", "exchange"]])
    combined = pd.concat(combined_rows, ignore_index=True) if combined_rows else pd.DataFrame()
    combined = combined.dropna(subset=["_value"])
    if _signal_cutoff is not None and not combined.empty:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            parsed_dates = pd.to_datetime(combined["_date"], errors="coerce", dayfirst=True).dt.date
        combined = combined[(parsed_dates >= _signal_cutoff) & (parsed_dates <= _signal_upper)]
    if search_query and not combined.empty:
        q = search_query.strip().lower()
        combined = combined[combined["canonical_company"].astype(str).str.lower().str.contains(q, na=False)]
    if combined.empty:
        st.caption(f"No transactions match “{search_query}”." if search_query else "No transactions this run.")
    else:
        top_txns = combined.sort_values("_value", ascending=False).head(8)
        rows_html = []
        for _, r in top_txns.iterrows():
            ex = str(r.get("exchange") or "")
            rows_html.append(
                f'<tr><td class="mono">{style.fmt_date(r["_date"])}</td>'
                f'<td style="font-weight:500;">{r.get("canonical_company") or "—"}</td>'
                f'<td>{style.badge(r2_data.CATEGORY_LABELS.get(r["_category"], r["_category"]), "text_2", "bg_sub", dot=False)}</td>'
                f'<td class="mono" style="text-align:right;">{style.fmt_inr(r["_value"])}</td>'
                f'<td style="text-align:right;">{style.exchange_badge(ex)}</td></tr>'
            )
        st.markdown(
            '<table class="evt-table"><tr><th>DATE</th><th>COMPANY</th><th>CATEGORY</th>'
            '<th style="text-align:right;">VALUE</th><th style="text-align:right;">EXCH</th></tr>'
            + "".join(rows_html) + "</table>",
            unsafe_allow_html=True,
        )
        if search_query:
            st.caption(f"{len(combined):,} transactions match “{search_query}”, top {len(top_txns)} shown by value.")
    st.caption("Ranked by value across insider trading, bulk/block deals, and rights/preferential issues, last 90 days. Full drill-down on Evidence & Drill-down.")

with sig3:
    st.markdown('<div style="font-size:12px;font-weight:700;margin-bottom:10px;">Concentration Alerts</div>', unsafe_allow_html=True)
    alert_rows = []
    for category in ("bulk_deals", "block_deals"):
        df = pd.concat([data.get((ex, category), pd.DataFrame()) for ex in exchanges], ignore_index=True) if exchanges else pd.DataFrame()
        if df.empty:
            continue
        df = df.copy()
        df["_value"] = pd.to_numeric(df.get("canonical_quantity"), errors="coerce").fillna(0) * pd.to_numeric(df.get("canonical_price"), errors="coerce").fillna(0)
        for (company, symbol), sub in df.groupby(["canonical_company", "canonical_symbol"], dropna=False):
            by_client = sub.groupby("canonical_client")["_value"].sum().sort_values(ascending=False)
            total = by_client.sum()
            share = (by_client.head(3).sum() / total) if total else 0.0
            if share >= 0.6 and total > 0:
                alert_rows.append({"company": company, "category": category, "value": total, "share": share})
    if not alert_rows:
        st.caption("No securities with >60% top-3-client concentration this run.")
    else:
        alert_rows.sort(key=lambda r: r["value"], reverse=True)
        st.markdown(f'<div style="font-size:22px;font-weight:700;margin-bottom:6px;">{len(alert_rows)}</div>', unsafe_allow_html=True)
        st.caption(f"{'security' if len(alert_rows) == 1 else 'securities'} with a handful of clients driving most of the volume.")
        for r in alert_rows[:4]:
            st.markdown(
                f'<div style="display:flex;justify-content:space-between;font-size:12px;padding:5px 0;border-bottom:1px solid {style.COLORS["border"]};">'
                f'<span>{style.badge("CONCENTRATED", "red", "red_bg", dot=False)} {r["company"]}</span>'
                f'<span class="mono">top3 {r["share"]*100:.0f}%</span></div>',
                unsafe_allow_html=True,
            )
    st.caption("Top-3-client share of a security's traded value, this run. Full view on Bulk & Block Concentration.")

st.write("")
st.markdown('<div style="font-size:13px;font-weight:700;margin-bottom:10px;">Activity Trend — All Categories</div>', unsafe_allow_html=True)
# One line per category, not just insider trading -- daily row counts using
# each category's own date field (transaction_date for insider trading,
# event_date for the other four).
_DATE_FIELD = {
    "insider_trading": "canonical_transaction_date",
    "bulk_deals": "canonical_event_date", "block_deals": "canonical_event_date",
    "rights_issue": "canonical_event_date", "preferential_issue": "canonical_event_date",
}
_TREND_COLORS = {
    "insider_trading": style.COLORS["blue"], "bulk_deals": style.COLORS["nse"],
    "block_deals": style.COLORS["bse"], "rights_issue": style.COLORS["green"],
    "preferential_issue": style.COLORS["amber"],
}
daily_by_cat = {}
for category in r2_data.CATEGORIES:
    df = pd.concat([data.get((ex, category), pd.DataFrame()) for ex in exchanges], ignore_index=True) if exchanges else pd.DataFrame()
    date_field = _DATE_FIELD[category]
    if df.empty or date_field not in df.columns:
        continue
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        dates = pd.to_datetime(df[date_field], errors="coerce", dayfirst=True).dt.date
    dates = dates.dropna()
    if _signal_cutoff is not None:
        dates = dates[(dates >= _signal_cutoff) & (dates <= _signal_upper)]
    daily = dates.value_counts()
    if not daily.empty:
        daily_by_cat[category] = daily

if not daily_by_cat:
    st.caption("No data to chart.")
else:
    visible_labels = st.pills(
        "Categories", [r2_data.CATEGORY_LABELS[c] for c in daily_by_cat],
        selection_mode="multi", default=[r2_data.CATEGORY_LABELS[c] for c in daily_by_cat],
        label_visibility="collapsed", key="trend_category_toggle",
    )
    shown = {c for c in daily_by_cat if r2_data.CATEGORY_LABELS[c] in (visible_labels or [])}
    all_dates = sorted(set().union(*(d.index for d in daily_by_cat.values())))
    fig = go.Figure()
    for category, daily in daily_by_cat.items():
        if category not in shown:
            continue
        fig.add_trace(go.Scatter(
            x=all_dates, y=[int(daily.get(d, 0)) for d in all_dates],
            mode="lines", name=r2_data.CATEGORY_LABELS[category],
            line=dict(color=_TREND_COLORS[category], width=2.5),
        ))
    if not shown:
        st.caption("No categories selected -- toggle one on above to chart it.")
    else:
        fig.update_layout(
            height=240, margin=dict(l=0, r=0, t=4, b=0),
            xaxis=dict(showgrid=False), yaxis=dict(showgrid=True, gridcolor=style.COLORS["border"], zeroline=False),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, font=dict(size=11)),
            font=dict(family="IBM Plex Sans, sans-serif", size=11, color=style.COLORS["text_2"]),
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
st.caption("Daily row count per category, last 90 days. Click a pill to toggle its line.")
