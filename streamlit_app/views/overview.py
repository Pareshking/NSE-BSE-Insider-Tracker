import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import dedup, fields, r2_data, style

# Rights/preferential carry event dates from way earlier (or, for some
# corporate-action fields, later -- e.g. a record date) in a listing's
# lifecycle than the actual disclosure -- some run years off in either
# direction. Window "today's signals" to the same 90D the acquisition
# pipeline requests, both bounds, or a handful of stray rows swamp what's
# supposed to be a recent-activity view (confirmed 2026-09-02 against real
# data: unbounded above, the trend chart's x-axis ran three months past the
# run date).
WINDOW_DAYS = 90

# --- Concentration Alerts -------------------------------------------------
# Top-3-client share is trivially 100% for any security that only had one to
# three clients trade it in the window, which is most of them -- that alone
# flagged 493 "concentrated" securities on the 2026-08-31 run, every one at
# top3 100%. A concentration claim only says anything once there were enough
# participants for the trade to have been spread out and it wasn't, so
# require both a real field of clients and a size worth noticing.
CONCENTRATION_THRESHOLD = 0.6      # top-3 share of a security's traded value
CONCENTRATION_MIN_CLIENTS = 5      # below this, "top 3" is the whole population
CONCENTRATION_MIN_VALUE = 1e7      # Rs.1Cr -- ignore token volume

# --- Biggest Stake Changes ------------------------------------------------
# % change is relative to the person's OWN prior holding, so a small base
# turns an ordinary purchase into a four-digit headline (a real row: 1,000 ->
# 140,817 shares reads as +13,981.7%). Requiring a real starting position is
# the only thing that keeps this column meaningful, and the before/after
# counts are shown alongside so the reader can judge the number themselves.
MIN_BASE_HOLDING = 25_000

# --- Accumulation Signals -------------------------------------------------
# SEBI PIT disclosures carry a mode of acquisition/disposal, and most of the
# values in it are not open-market conviction: an ESOP allotment, a pledge or
# its invocation, an inter-se transfer between promoters, a gift or a
# corporate action all file the same way and carry the same rupee value.
# Summing them into "accumulation" and ranking by % of market cap is what
# produced rows like a -27.1%-of-market-cap "SELL". Rows whose mode is not
# stated are kept (dropping them would hide real market trades -- the field
# was empty on a third of the sampled NSE filings), so this excludes only
# what the source positively says was not a market transaction.
NON_MARKET_MODE_PATTERNS = (
    "ESOP", "ESOS", "ESPS", "PLEDGE", "INVOK", "REVOK", "ENCUMBR",
    "INTER-SE", "INTER SE", "OFF MARKET", "OFF-MARKET", "GIFT",
    "TRANSMISSION", "INHERIT", "BONUS", "SPLIT", "AMALGAM", "MERGER",
    "DEMERGER", "CONVERSION", "ALLOT", "RIGHTS", "BUYBACK", "OPEN OFFER",
)


@st.cache_data(ttl=300, max_entries=6, show_spinner=False)
def overview_aggregates(_client, date: str, exchanges: tuple[str, ...]) -> dict:
    """Every rollup this page draws, computed once per (run date, exchange
    choice).

    These are pure functions of the run's data, but Streamlit re-executes
    the whole script on every widget interaction -- so uncached, typing a
    single character into the search box re-parsed 90 days of dates and
    re-ran the per-security concentration groupby for all five categories.
    Search now filters the results below instead of recomputing them.
    """
    anchor = fields.parse_date(date)
    upper = anchor.date() if pd.notna(anchor) else None
    cutoff = (anchor - pd.Timedelta(days=WINDOW_DAYS - 1)).date() if pd.notna(anchor) else None

    by_category = {c: r2_data.load_combined(_client, c, exchanges, date) for c in r2_data.CATEGORIES}
    insider_df = by_category["insider_trading"]

    def in_window(dates_series):
        if cutoff is None:
            return dates_series.notna()
        return dates_series.notna() & (dates_series >= cutoff) & (dates_series <= upper)

    # --- promoter accumulation, ranked by % of market cap
    promoter_ranking = pd.DataFrame(columns=["net_val", "symbol", "market_cap", "pct_mcap"])
    non_market_excluded = 0
    if not insider_df.empty:
        person_cat = fields.text_col(insider_df, "canonical_person_category", upper=True)
        promoter_rows = insider_df[person_cat.str.contains("PROMOTER")].copy()
        # Drop what the filing itself says was not an open-market trade.
        if not promoter_rows.empty:
            mode = fields.text_col(promoter_rows, "canonical_mode", upper=True)
            is_non_market = mode.str.contains("|".join(NON_MARKET_MODE_PATTERNS), regex=True, na=False)
            non_market_excluded = int(is_non_market.sum())
            promoter_rows = promoter_rows[~is_non_market]
        if not promoter_rows.empty:
            ttype = fields.text_col(promoter_rows, "canonical_transaction_type", upper=True)
            signed_val = fields.num_col(promoter_rows, "canonical_value")
            promoter_rows["_signed_val"] = signed_val.where(~ttype.str.contains("DISPOS"), -signed_val)
            grouped = promoter_rows.groupby("canonical_company").agg(
                net_val=("_signed_val", "sum"), symbol=("canonical_symbol", "first"),
            )
            mcap_lookup = r2_data.market_cap_lookup(_client, date)
            if mcap_lookup is not None:
                grouped["market_cap"] = grouped["symbol"].astype(str).str.upper().map(mcap_lookup)
                grouped["pct_mcap"] = 100 * grouped["net_val"] / grouped["market_cap"]
            else:
                grouped["market_cap"] = pd.NA
                grouped["pct_mcap"] = pd.NA
            # Sort by |% of market cap| when known; unknown-market-cap rows sort
            # by raw value but always land after every ranked row, never
            # crowding out a smaller name just because its % couldn't be computed.
            has_pct = grouped["pct_mcap"].notna()
            promoter_ranking = pd.concat([
                grouped[has_pct].reindex(grouped[has_pct]["pct_mcap"].abs().sort_values(ascending=False).index),
                grouped[~has_pct].reindex(grouped[~has_pct]["net_val"].abs().sort_values(ascending=False).index),
            ])

    # --- one ranked feed across all 5 categories -- a big bulk deal or
    # preferential allotment is just as much "what happened today" as an
    # insider filing.
    combined_rows = []
    for category, df in by_category.items():
        if df.empty:
            continue
        df = df.copy()
        if category == "insider_trading":
            df["_value"] = fields.num_col(df, "canonical_value", fill=None)
            df["_date"] = df.get("canonical_transaction_date")
            ttype = fields.text_col(df, "canonical_transaction_type", upper=True)
            df["_side"] = ttype.map(lambda t: "BUY" if "ACQUI" in t else ("SELL" if "DISPOS" in t else None))
        elif category in ("bulk_deals", "block_deals"):
            df["_value"] = fields.num_col(df, "canonical_quantity", fill=None) * fields.num_col(df, "canonical_price", fill=None)
            df["_date"] = df.get("canonical_event_date")
            df["_side"] = fields.text_col(df, "canonical_side", upper=True).where(lambda s: s.isin(["BUY", "SELL"]))
        else:
            df["_value"] = fields.num_col(df, "canonical_amount_raised", fill=None)
            df["_date"] = df.get("canonical_event_date")
            df["_side"] = "ISSUANCE"  # capital raise, not a buy/sell trade -- never fabricate a side for these
        df["_category"] = category
        # Quantity/price identify the underlying trade for the dedup below;
        # they are meaningless for the issuance categories, which is fine --
        # those never take the bulk/block branch.
        df["_qty"] = fields.num_col(df, "canonical_quantity", fill=None)
        df["_price"] = fields.num_col(df, "canonical_price", fill=None)
        combined_rows.append(df[["_value", "_date", "_category", "_side", "_qty", "_price",
                                 "canonical_company", "exchange"]])
    combined = pd.concat(combined_rows, ignore_index=True) if combined_rows else pd.DataFrame(
        columns=["_value", "_date", "_category", "_side", "_qty", "_price", "canonical_company", "exchange"])
    combined = combined.dropna(subset=["_value"])
    if not combined.empty:
        combined["_parsed_date"] = fields.parse_dates(combined["_date"])
        combined = combined[in_window(combined["_parsed_date"].dt.date)]

    # One bulk/block trade is disclosed by BOTH counterparties, and the same
    # trade can surface in the bulk feed and the block feed, so a single deal
    # arrived here as up to four identical-value rows -- on the 2026-08-31 run
    # Adani Green filled four of the eight slots with one 09 Jun deal. Collapse
    # on what identifies the trade itself (company, day, quantity, price) and
    # keep one row, remembering that both sides were disclosed.
    if not combined.empty:
        deals = combined["_category"].isin(["bulk_deals", "block_deals"])
        sides = (
            combined[deals]
            .groupby(["canonical_company", "_parsed_date", "_qty", "_price"], dropna=False)["_side"]
            .transform(lambda s: "BUY & SELL" if s.nunique() > 1 else s.iloc[0])
        )
        combined.loc[deals, "_side"] = sides
        deduped = combined[deals].drop_duplicates(
            subset=["canonical_company", "_parsed_date", "_qty", "_price"], keep="first")
        combined = pd.concat([combined[~deals], deduped], ignore_index=True)

    # Most recent first. This is a "what just happened" feed; ranking it by
    # size instead meant one enormous deal from ten weeks ago outranked
    # everything that happened this week, and the same few mega-caps sat at
    # the top of the page every day regardless of the run date.
    top_transactions = combined.sort_values("_parsed_date", ascending=False, na_position="last") \
        if not combined.empty else combined

    # --- concentration: a few clients driving most of a security's volume.
    # Bulk and block are pooled per security here (unlike the dedicated page,
    # which keeps them apart because they are distinct deal types): the
    # question this asks is "who accumulated this stock", and a client who
    # worked through both windows is one story, not two. Pooling also stops
    # the same company being listed twice with nothing to tell the rows apart.
    deal_frames = [by_category[c] for c in ("bulk_deals", "block_deals")
                   if not by_category[c].empty and "canonical_client" in by_category[c].columns]
    alert_rows = []
    round_trips_dropped = 0
    if deal_frames:
        deals_df = pd.concat(deal_frames, ignore_index=True)
        # A client who buys and sells the same size in one day ends flat, so
        # counting that turnover as "driving the volume" of a security
        # overstates their grip on it -- they took no position at all.
        deals_df, round_trips_dropped = dedup.drop_intraday_round_trips(deals_df)
        deals_df["_value"] = fields.num_col(deals_df, "canonical_quantity") * fields.num_col(deals_df, "canonical_price")
        for company, sub in deals_df.groupby("canonical_company", dropna=False):
            by_client = sub.groupby("canonical_client")["_value"].sum().sort_values(ascending=False)
            total = float(by_client.sum())
            n_clients = int(by_client.size)
            if n_clients < CONCENTRATION_MIN_CLIENTS or total < CONCENTRATION_MIN_VALUE:
                continue
            share = by_client.head(3).sum() / total
            if share >= CONCENTRATION_THRESHOLD:
                alert_rows.append({
                    "company": company, "value": total, "share": float(share),
                    "clients": n_clients, "top_client": by_client.index[0],
                    "top_client_share": float(by_client.iloc[0] / total),
                })
    alert_rows.sort(key=lambda r: (r["share"], r["value"]), reverse=True)

    # --- biggest stake changes, by % of the holding, not rupees
    stake_changes = pd.DataFrame()
    if not insider_df.empty and "canonical_holding_before" in insider_df.columns:
        hdf = insider_df.copy()
        hdf["_before"] = fields.num_col(hdf, "canonical_holding_before", fill=None)
        hdf["_after"] = fields.num_col(hdf, "canonical_holding_after", fill=None)
        # A tiny base holding turns a small share move into a meaningless
        # four-digit percentage -- require a real starting position before
        # trusting the ratio.
        hdf = hdf[hdf["_before"] >= MIN_BASE_HOLDING]
        hdf["_pct_change"] = 100 * (hdf["_after"] - hdf["_before"]) / hdf["_before"]
        hdf = hdf.dropna(subset=["_pct_change"])
        stake_changes = hdf.reindex(hdf["_pct_change"].abs().sort_values(ascending=False).index)

    return {
        "promoter_ranking": promoter_ranking,
        "non_market_excluded": non_market_excluded,
        "top_transactions": top_transactions,
        "concentration_alerts": alert_rows,
        "round_trips_dropped": round_trips_dropped,
        "stake_changes": stake_changes,
        "has_insider_data": not insider_df.empty,
    }


def matches_company(df: pd.DataFrame, query: str) -> pd.DataFrame:
    if not query or df.empty:
        return df
    return df[df["canonical_company"].astype(str).str.lower().str.contains(query.strip().lower(), na=False)]


client, dates = r2_data.page_gate("Overview")

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
        "Search", placeholder="Search company or symbol…",
        label_visibility="collapsed", key="overview_search",
        help="Searching by person or fund name? Use Entity Tracker instead -- it looks up a name across every category, not just this page's company filter.",
    )

with r2_data.guard(f"the {selected_date} run"):
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

exchanges = tuple(r2_data.EXCHANGES) if exchange_choice == "Both" else (exchange_choice.lower(),)
with r2_data.guard(f"the {selected_date} run"):
    agg = overview_aggregates(client, selected_date, exchanges)
# The category pulse strip that used to sit here (five row counts with a
# this-week-vs-usual delta) is gone: on mobile its five cards stacked into a
# full screen of scrolling that had to be got past before reaching anything
# actionable, and a raw row count per category is closer to a pipeline
# statistic than a signal. Data Quality already carries the per-run counts.

title_col, link_col = st.columns([3, 1.3])
with title_col:
    st.markdown('<div style="font-size:14px;font-weight:700;margin-bottom:8px;">Today\'s Signals</div>', unsafe_allow_html=True)
with link_col:
    st.page_link("views/confluence_screener.py", label="Cross-category confluence signals →", icon="🧭")

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
    if not agg["has_insider_data"]:
        st.caption("No insider-trading data.")
    else:
        ranked = agg["promoter_ranking"]
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
    _excluded = agg["non_market_excluded"]
    st.caption(
        "Open-market promoter trades only, ranked by % of market cap."
        + (f" {_excluded} non-market filing(s) (ESOP, pledge, inter-se, gift) excluded."
           if _excluded else "")
        + " Full rollup on Promoter Activity."
    )

with sig2:
    st.markdown('<div style="font-size:12px;font-weight:700;margin-bottom:10px;">Biggest Transactions — All Categories</div>', unsafe_allow_html=True)
    # A single ranked feed across all 5 categories -- not just insider
    # trading -- since a big bulk deal or preferential allotment is just as
    # much "what happened today" as an insider filing.
    combined = matches_company(agg["top_transactions"], search_query)
    if combined.empty:
        st.caption(f"No transactions match “{search_query}”." if search_query else "No transactions this run.")
    else:
        top_txns = combined.head(8)
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
            '<div class="table-scroll"><table class="evt-table"><tr><th>DATE</th><th>COMPANY</th><th>CATEGORY</th><th>SIDE</th>'
            '<th style="text-align:right;">VALUE</th><th style="text-align:right;">EXCH</th></tr>'
            + "".join(rows_html) + "</table></div>",
            unsafe_allow_html=True,
        )
        if search_query:
            st.caption(f"{len(combined):,} transactions match “{search_query}”, {len(top_txns)} most recent shown.")
    st.caption(
        "Most recent first, last 90 days. Both sides of a bulk/block deal are one row. "
        "Full drill-down on Evidence & Drill-down."
    )

with sig3:
    st.markdown('<div style="font-size:12px;font-weight:700;margin-bottom:10px;">Concentration Alerts</div>', unsafe_allow_html=True)
    alert_rows = matches_company(pd.DataFrame(agg["concentration_alerts"]), search_query)
    alert_rows = alert_rows.to_dict("records") if not alert_rows.empty else []
    if not alert_rows:
        st.caption(
            f"No security had {CONCENTRATION_MIN_CLIENTS}+ clients trading it with the top 3 "
            f"taking {CONCENTRATION_THRESHOLD:.0%}+ of the value this run."
        )
    else:
        # The bare count used to lead here, and it was the least useful thing
        # on the page -- "493 securities" told an investor nothing and every
        # row read top3 100%. Lead with the names instead, and say who the
        # dominant client actually is, which is the part worth acting on.
        for r in alert_rows[:4]:
            st.markdown(
                f'<div style="font-size:12px;padding:6px 0;border-bottom:1px solid {style.COLORS["border"]};">'
                f'<div style="display:flex;justify-content:space-between;align-items:baseline;gap:8px;">'
                f'<span style="font-weight:500;">{r["company"] or "—"}</span>'
                f'<span class="mono" style="white-space:nowrap;">top3 {r["share"]*100:.0f}%</span></div>'
                f'<div style="color:{style.COLORS["text_3"]};font-size:10.5px;margin-top:2px;">'
                f'{r["clients"]} clients · {style.fmt_inr(r["value"])} traded · largest '
                f'<span style="color:{style.COLORS["text_2"]};">{r["top_client"] or "—"}</span> '
                f'at {r["top_client_share"]*100:.0f}%</div></div>',
                unsafe_allow_html=True,
            )
        if len(alert_rows) > 4:
            st.caption(f"{len(alert_rows) - 4} more on Bulk & Block Concentration.")
    _rt = agg["round_trips_dropped"]
    st.caption(
        f"Securities where {CONCENTRATION_MIN_CLIENTS}+ clients traded and the top 3 still took "
        f"{CONCENTRATION_THRESHOLD:.0%}+ of the value."
        + (f" {_rt} same-day round-trip leg(s) excluded — a client who ends the day flat took no position."
           if _rt else "")
        + " Full view on Bulk & Block Concentration."
    )

st.write("")
st.markdown('<div style="font-size:13px;font-weight:700;margin-bottom:8px;">Biggest Stake Changes — Insider Trading</div>', unsafe_allow_html=True)
if agg["stake_changes"].empty and not search_query:
    st.caption("No holding-before/after data this run.")
else:
    hdf = matches_company(agg["stake_changes"], search_query)
    if hdf.empty:
        st.caption(f"No stake changes match “{search_query}”." if search_query else "No stake changes with a reliable base holding this run.")
    else:
        top_changes = hdf.head(8)
        rows_html = []
        for _, r in top_changes.iterrows():
            pct = r["_pct_change"]
            color = "green" if pct >= 0 else "red"
            rows_html.append(
                f'<tr><td class="mono">{style.fmt_date(r.get("canonical_transaction_date"))}</td>'
                f'<td style="font-weight:500;">{r.get("canonical_company") or "—"}</td>'
                f'<td style="color:{style.COLORS["text_2"]};">{r.get("canonical_person") or "—"}</td>'
                # The share counts sit next to the percentage on purpose: the
                # % is against this person's own prior holding, so it is only
                # interpretable once you can see what that holding was.
                f'<td class="mono" style="text-align:right;color:{style.COLORS["text_2"]};">'
                f'{r["_before"]:,.0f} → {r["_after"]:,.0f}</td>'
                f'<td class="mono" style="text-align:right;color:{style.COLORS[color]};font-weight:600;">{pct:+.1f}%</td>'
                f'<td style="text-align:right;">{style.exchange_badge(str(r.get("exchange") or ""))}</td></tr>'
            )
        st.markdown(
            '<div class="table-scroll"><table class="evt-table"><tr><th>DATE</th><th>COMPANY</th><th>PERSON</th>'
            '<th style="text-align:right;">SHARES</th>'
            '<th style="text-align:right;">HOLDING Δ</th><th style="text-align:right;">EXCH</th></tr>'
            + "".join(rows_html) + "</table></div>",
            unsafe_allow_html=True,
        )
    st.caption(
        f"Change in the individual's own holding, not in the company. Only positions of "
        f"{MIN_BASE_HOLDING:,}+ shares before the trade, since a smaller base turns an "
        f"ordinary purchase into a four-digit percentage."
    )
