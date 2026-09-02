import sys
import warnings
from pathlib import Path

import pandas as pd
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

# One shared per-category daily-count series, windowed to the same 90D the
# acquisition pipeline requests -- computed once, reused by the pulse strip's
# this-week-vs-usual delta below instead of redoing this date-parsing pass
# per widget.
_DATE_FIELD = {
    "insider_trading": "canonical_transaction_date",
    "bulk_deals": "canonical_event_date", "block_deals": "canonical_event_date",
    "rights_issue": "canonical_event_date", "preferential_issue": "canonical_event_date",
}
_window_dates = (
    pd.date_range(_signal_cutoff, _signal_upper, freq="D").date if _signal_cutoff is not None else []
)
daily_by_cat = {}
for category in r2_data.CATEGORIES:
    df = pd.concat([data.get((ex, category), pd.DataFrame()) for ex in exchanges], ignore_index=True) if exchanges else pd.DataFrame()
    date_field = _DATE_FIELD[category]
    if df.empty or date_field not in df.columns:
        daily_by_cat[category] = pd.Series(0, index=_window_dates)
        continue
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        cat_dates = pd.to_datetime(df[date_field], errors="coerce", dayfirst=True).dt.date
    cat_dates = cat_dates.dropna()
    if _signal_cutoff is not None:
        cat_dates = cat_dates[(cat_dates >= _signal_cutoff) & (cat_dates <= _signal_upper)]
    daily = cat_dates.value_counts()
    daily_by_cat[category] = daily.reindex(_window_dates, fill_value=0).sort_index() if len(_window_dates) else daily

# --- Category Pulse Strip: count + this-week-vs-usual delta, per category --
# a signal ("is this heating up right now"), not a trend chart -- shape over
# time doesn't tell an investor what to do with it.
pulse_cols = st.columns(len(r2_data.CATEGORIES))
for i, category in enumerate(r2_data.CATEGORIES):
    daily = daily_by_cat[category]
    total = int(daily.sum())
    last7 = int(daily.tail(7).sum())
    prior_avg7 = daily.iloc[:-7].mean() * 7 if len(daily) > 7 else None
    if prior_avg7 and prior_avg7 > 0:
        delta_pct = 100 * (last7 - prior_avg7) / prior_avg7
        delta_html = (
            f'<span style="color:{style.COLORS["green"] if delta_pct >= 0 else style.COLORS["red"]};font-weight:600;">'
            f'{"▲" if delta_pct >= 0 else "▼"} {abs(delta_pct):.0f}%</span> <span style="color:{style.COLORS["text_3"]};">vs usual week</span>'
        )
    else:
        delta_html = f'<span style="color:{style.COLORS["text_3"]};">{last7} in last 7d</span>'
    with pulse_cols[i]:
        st.markdown(
            f'<div class="kpi-card" style="padding:12px 14px;">'
            f'<div class="kpi-label">{r2_data.CATEGORY_LABELS[category].upper()}</div>'
            f'<div class="kpi-value" style="font-size:22px;margin-top:4px;">{total:,}</div>'
            f'<div style="font-size:10.5px;margin-top:4px;">{delta_html}</div>'
            f"</div>",
            unsafe_allow_html=True,
        )
st.caption("Count and this week vs. the window's usual pace, last 90 days -- full category-by-category browsing is on Evidence & Drill-down.")

st.write("")
st.markdown('<div style="font-size:14px;font-weight:700;margin-bottom:2px;">Today\'s Signals</div>', unsafe_allow_html=True)
st.caption("Cross-category highlights, not raw counts -- who's buying/selling with conviction, what's big, where volume is concentrated.")

sig1, sig2, sig3 = st.columns([1, 1.3, 1])

with sig1:
    st.markdown('<div style="font-size:12px;font-weight:700;margin-bottom:10px;">Accumulation Signals — Promoters</div>', unsafe_allow_html=True)
    # Ranked by % of market cap, not raw rupees: a promoter quietly building
    # a Rs.25Cr position over several staggered buys in a Rs.100Cr company is
    # a far stronger conviction signal than a Rs.1Cr filing at HDFC Bank --
    # summing the whole window's transactions per company already captures
    # staggered buying, raw-rupee ranking just buries the small-cap signal
    # under mega-cap noise. Falls back to raw value only when market cap
    # isn't available for a name (NSE-only reference data, see Promoter
    # Activity's own caveat).
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
        grouped = promoter_rows.groupby("canonical_company").agg(
            net_val=("_signed_val", "sum"), symbol=("canonical_symbol", "first"),
        )
        mcap_df = r2_data.load_market_cap(client, selected_date)
        if not mcap_df.empty:
            mcap_lookup = mcap_df.drop_duplicates("symbol").set_index("symbol")["market_cap"]
            grouped["market_cap"] = grouped["symbol"].astype(str).str.upper().map(mcap_lookup)
            grouped["pct_mcap"] = 100 * grouped["net_val"] / grouped["market_cap"]
        else:
            grouped["pct_mcap"] = pd.NA
        # Sort by |% of market cap| when known; unknown-market-cap rows sort
        # by raw value but always land after every ranked row, never
        # crowding out a smaller name just because its % couldn't be computed.
        has_pct = grouped["pct_mcap"].notna()
        ranked = pd.concat([
            grouped[has_pct].reindex(grouped[has_pct]["pct_mcap"].abs().sort_values(ascending=False).index),
            grouped[~has_pct].reindex(grouped[~has_pct]["net_val"].abs().sort_values(ascending=False).index),
        ])
        buyers = ranked[ranked["net_val"] > 0].head(4)
        sellers = ranked[ranked["net_val"] < 0].head(2)
        if buyers.empty and sellers.empty:
            st.caption("No promoter acquisitions/disposals this run.")
        for company, row in pd.concat([buyers, sellers]).iterrows():
            is_buy = row["net_val"] > 0
            pct_html = (
                f'<span class="mono" style="font-size:11px;">{row["pct_mcap"]:+.1f}% mcap</span>'
                if pd.notna(row["pct_mcap"]) else
                f'<span style="font-size:10px;color:{style.COLORS["text_3"]};">mcap n/a</span>'
            )
            st.markdown(
                f'<div style="display:flex;justify-content:space-between;align-items:baseline;font-size:12px;padding:5px 0;border-bottom:1px solid {style.COLORS["border"]};">'
                f'<span>{style.badge("BUY" if is_buy else "SELL", "green" if is_buy else "red", "green_bg" if is_buy else "red_bg", dot=False)} {company}</span>'
                f'<span style="text-align:right;">{pct_html}<br/><span class="mono">{style.fmt_inr(abs(row["net_val"]))}</span></span></div>',
                unsafe_allow_html=True,
            )
    st.caption("Full window summed per company (catches staggered buying), ranked by % of market cap where known. Full rollup on Promoter Activity.")

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
            ttype = df.get("canonical_transaction_type", pd.Series(dtype=object)).astype(str).str.upper()
            df["_side"] = ttype.map(lambda t: "BUY" if "ACQUI" in t else ("SELL" if "DISPOS" in t else None))
        elif category in ("bulk_deals", "block_deals"):
            df["_value"] = pd.to_numeric(df.get("canonical_quantity"), errors="coerce") * pd.to_numeric(df.get("canonical_price"), errors="coerce")
            df["_date"] = df.get("canonical_event_date")
            df["_side"] = df.get("canonical_side", pd.Series(dtype=object)).astype(str).str.upper().where(lambda s: s.isin(["BUY", "SELL"]))
        else:
            df["_value"] = pd.to_numeric(df.get("canonical_amount_raised"), errors="coerce")
            df["_date"] = df.get("canonical_event_date")
            df["_side"] = "ISSUANCE"  # capital raise, not a buy/sell trade -- never fabricate a side for these
        df["_category"] = category
        combined_rows.append(df[["_value", "_date", "_category", "_side", "canonical_company", "exchange"]])
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
            side = r.get("_side")
            if side == "BUY":
                side_badge = style.badge("BUY", "green", "green_bg", dot=False)
            elif side == "SELL":
                side_badge = style.badge("SELL", "red", "red_bg", dot=False)
            elif side == "ISSUANCE":
                side_badge = style.badge("ISSUANCE", "text_2", "bg_sub", dot=False)
            else:
                side_badge = "—"
            rows_html.append(
                f'<tr><td class="mono">{style.fmt_date(r["_date"])}</td>'
                f'<td style="font-weight:500;">{r.get("canonical_company") or "—"}</td>'
                f'<td>{style.badge(r2_data.CATEGORY_LABELS.get(r["_category"], r["_category"]), "text_2", "bg_sub", dot=False)}</td>'
                f'<td>{side_badge}</td>'
                f'<td class="mono" style="text-align:right;">{style.fmt_inr(r["_value"])}</td>'
                f'<td style="text-align:right;">{style.exchange_badge(ex)}</td></tr>'
            )
        st.markdown(
            '<table class="evt-table"><tr><th>DATE</th><th>COMPANY</th><th>CATEGORY</th><th>SIDE</th>'
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
st.markdown('<div style="font-size:13px;font-weight:700;margin-bottom:2px;">Biggest Stake Changes — Insider Trading</div>', unsafe_allow_html=True)
st.caption("Ranked by % change in the insider's own holding, not ₹ value -- a modest rupee amount can be a huge conviction move for a small stake, and a huge rupee amount can be trivial for a large one.")
if insider_df.empty or "canonical_holding_before" not in insider_df.columns:
    st.caption("No holding-before/after data this run.")
else:
    hdf = insider_df.copy()
    hdf["_before"] = pd.to_numeric(hdf.get("canonical_holding_before"), errors="coerce")
    hdf["_after"] = pd.to_numeric(hdf.get("canonical_holding_after"), errors="coerce")
    # A tiny base holding turns a small share move into a meaningless
    # four-digit percentage -- require a real starting position before
    # trusting the ratio.
    hdf = hdf[hdf["_before"] >= 1000]
    hdf["_pct_change"] = 100 * (hdf["_after"] - hdf["_before"]) / hdf["_before"]
    hdf = hdf.dropna(subset=["_pct_change"])
    if search_query and not hdf.empty:
        q = search_query.strip().lower()
        hdf = hdf[hdf["canonical_company"].astype(str).str.lower().str.contains(q, na=False)]
    if hdf.empty:
        st.caption(f"No stake changes match “{search_query}”." if search_query else "No stake changes with a reliable base holding this run.")
    else:
        top_changes = hdf.reindex(hdf["_pct_change"].abs().sort_values(ascending=False).index).head(8)
        rows_html = []
        for _, r in top_changes.iterrows():
            pct = r["_pct_change"]
            color = "green" if pct >= 0 else "red"
            rows_html.append(
                f'<tr><td class="mono">{style.fmt_date(r.get("canonical_transaction_date"))}</td>'
                f'<td style="font-weight:500;">{r.get("canonical_company") or "—"}</td>'
                f'<td style="color:{style.COLORS["text_2"]};">{r.get("canonical_person") or "—"}</td>'
                f'<td class="mono" style="text-align:right;color:{style.COLORS[color]};font-weight:600;">{pct:+.1f}%</td>'
                f'<td style="text-align:right;">{style.exchange_badge(str(r.get("exchange") or ""))}</td></tr>'
            )
        st.markdown(
            '<table class="evt-table"><tr><th>DATE</th><th>COMPANY</th><th>PERSON</th>'
            '<th style="text-align:right;">HOLDING Δ</th><th style="text-align:right;">EXCH</th></tr>'
            + "".join(rows_html) + "</table>",
            unsafe_allow_html=True,
        )
    st.caption("Requires a starting holding of at least 1,000 shares, to keep the ratio meaningful. Full drill-down on Evidence & Drill-down.")
