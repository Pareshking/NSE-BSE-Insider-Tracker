"""Smart Money Confluence Screener -- joins insider trading, bulk/block
deals, and rights/preferential issues by ISIN to rank companies by Float
Absorption Ratio (FAR): combined promoter + institutional net flow as a
% of market cap. See lib/confluence.py for the literature this is built on
and exactly why each signal is classified the way it is.

Deliberately not a price/return backtest -- every number here is a
capital-structure or ownership-change fact (who bought, who sold, how much
of the company), not a price prediction.
"""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import confluence, dedup, fields, r2_data, style

st.markdown("### Confluence Screener")
st.caption("Companies where promoters, institutions, and capital-raise events overlap -- ranked by Float Absorption Ratio (FAR), the % of market cap changing hands to informed entities.")

@st.cache_data(ttl=300, max_entries=6, show_spinner="Joining categories by ISIN…")
def confluence_table(_client, date: str, exchanges: tuple[str, ...]):
    """The per-ISIN confluence table and the internal transfers pulled out
    of it, for one (run date, exchange choice).

    Cached because it is by far the heaviest thing this app does -- the
    internal-transfer pass compares every bulk/block buy against every sell
    on the same ISIN and date -- and none of it depends on the filters
    below. Uncached, every keystroke in the search box re-ran the whole
    join.
    """
    cats = {c: r2_data.load_combined(_client, c, exchanges, date) for c in r2_data.CATEGORIES}
    mcap_lookup = r2_data.market_cap_lookup(_client, date)

    promoter_flow = confluence.promoter_insider_flow(cats["insider_trading"], mcap_lookup)
    inst_flow, transfers = confluence.institutional_flow(cats["bulk_deals"], cats["block_deals"], mcap_lookup)
    actions = confluence.corporate_action_flags(cats["rights_issue"], cats["preferential_issue"])

    merged = pd.merge(promoter_flow, inst_flow, on="canonical_isin", how="outer", suffixes=("_p", "_i"))
    merged["company"] = merged["company_p"].combine_first(merged.get("company_i"))
    merged["symbol"] = merged["symbol_p"].combine_first(merged.get("symbol_i"))
    merged["market_cap"] = merged["market_cap_p"].combine_first(merged.get("market_cap_i"))
    merged = merged.drop(columns=[c for c in ("company_p", "company_i", "symbol_p", "symbol_i", "market_cap_p", "market_cap_i") if c in merged.columns])
    merged = merged.merge(actions, on="canonical_isin", how="left")
    for col, default in [("promoter_net_value", 0), ("institutional_net_value", 0), ("has_rights_issue", False), ("has_preferential", False)]:
        merged[col] = merged[col].fillna(default)

    merged["combined_flow"] = merged["promoter_net_value"] + merged["institutional_net_value"]
    merged["far_pct"] = 100 * merged["combined_flow"] / merged["market_cap"]
    merged["tier"] = merged["market_cap"].map(confluence.mcap_tier)
    if merged.empty:
        # .apply(axis=1) over no rows returns an empty Series, which pandas
        # refuses to unpack into two columns ("Columns must be same length
        # as key"). Reached whenever nothing joins -- e.g. a run where no
        # category resolved an ISIN.
        merged["category"] = pd.Series(dtype=object)
        merged["category_color"] = pd.Series(dtype=object)
    else:
        merged[["category", "category_color"]] = merged.apply(lambda r: pd.Series(confluence.classify(r)), axis=1)
    return merged, transfers


client, dates = r2_data.page_gate()

top = st.columns([1, 1, 2])
with top[0]:
    selected_date = st.selectbox("Run date", dates, index=0)
with top[1]:
    exchange_choice = st.radio("Exchange", ["Both", "NSE", "BSE"], horizontal=True, label_visibility="collapsed")
exchanges = tuple(r2_data.EXCHANGES) if exchange_choice == "Both" else (exchange_choice.lower(),)

with r2_data.guard(f"the {selected_date} run"):
    merged, transfers = confluence_table(client, selected_date, exchanges)
    # Loaded separately (not returned from the cache above) so the
    # constituent-transaction dialog reads the same already-cached frames
    # instead of keeping a second copy of them alive in the cache.
    cats = {c: r2_data.load_combined(client, c, exchanges, selected_date) for c in r2_data.CATEGORIES}

if merged.empty:
    st.info("No insider/bulk/block/rights/preferential data for this run date.")
    st.stop()

filter_cols = st.columns([1.3, 1.3, 1.6, 1.4])
with filter_cols[0]:
    tier_pick = st.multiselect("Market cap tier", [t for _, t in confluence.MCAP_TIERS])
with filter_cols[1]:
    category_pick = st.multiselect("Category", sorted(merged["category"].dropna().unique(), key=str))
with filter_cols[2]:
    company_search = st.text_input("Search company / symbol", placeholder="Search…")
with filter_cols[3]:
    sort_basis = st.radio("Sort by", ["FAR %", "Combined Value"], horizontal=True,
                           help="FAR % needs market cap; falls back to value when it's not available for a name.")

filtered = merged[merged["category"] != "No Confluence"].copy()
if tier_pick:
    filtered = filtered[filtered["tier"].isin(tier_pick)]
if category_pick:
    filtered = filtered[filtered["category"].isin(category_pick)]
if company_search:
    q = company_search.strip().lower()
    filtered = filtered[filtered["company"].astype(str).str.lower().str.contains(q, na=False) |
                         filtered["symbol"].astype(str).str.lower().str.contains(q, na=False)]

if sort_basis == "Combined Value":
    ranked = filtered.reindex(filtered["combined_flow"].abs().sort_values(ascending=False).index)
else:
    has_far = filtered["far_pct"].notna()
    ranked = pd.concat([
        filtered[has_far].reindex(filtered[has_far]["far_pct"].abs().sort_values(ascending=False).index),
        filtered[~has_far].reindex(filtered[~has_far]["combined_flow"].abs().sort_values(ascending=False).index),
    ])

caption_col, export_col = st.columns([3, 1])
with caption_col:
    st.caption(f"{len(ranked):,} companies with a confluence signal this run (of {len(merged):,} with any promoter/institutional/corporate-action activity).")
with export_col:
    style.download_csv(
        ranked.drop(columns=["category_color"], errors="ignore"),
        f"confluence_{selected_date}_{exchange_choice.lower()}.csv", label="Export screen",
    )

for _, row in ranked.head(40).iterrows():
    far_html = f'{row["far_pct"]:+.2f}%<span style="font-size:10px;color:{style.COLORS["text_3"]};"> FAR</span>' if pd.notna(row["far_pct"]) else '<span style="color:' + style.COLORS["text_3"] + ';font-size:11px;">mcap n/a</span>'
    flags = []
    if row["has_preferential"]:
        flags.append(style.badge(f'PREF ({row.get("preferential_allottee") or "?"})', "blue", "blue_bg", dot=False))
    if row["has_rights_issue"]:
        flags.append(style.badge("RIGHTS", "amber", "amber_bg", dot=False))
    c1, c2, c3, c4 = st.columns([2.3, 1.2, 1.6, 1.3])
    with c1:
        tier_text = row["tier"] if pd.notna(row["tier"]) else "tier n/a"
        st.markdown(f'**{row["company"] or "—"}**  \n<span style="color:{style.COLORS["text_2"]};font-size:11px;">{tier_text}</span>', unsafe_allow_html=True)
    with c2:
        st.markdown(f'<span class="mono" style="font-size:14px;font-weight:600;">{far_html}</span>', unsafe_allow_html=True)
    with c3:
        st.markdown(style.badge(row["category"], row["category_color"], f'{row["category_color"]}_bg' if row["category_color"] != "text_2" else "bg_sub", dot=False) + " " + " ".join(flags), unsafe_allow_html=True)
    with c4:
        if st.button("Details →", key=f"detail-{row['canonical_isin']}", use_container_width=True):
            st.session_state["confluence_detail_isin"] = row["canonical_isin"]
    # FAR is a combined number -- show which side is actually driving it,
    # since "Insider Alpha" and "Certification" are fundamentally about
    # WHO is buying, not just how much in total.
    promoter_val = fields.as_float(row.get("promoter_net_value"))
    inst_val = fields.as_float(row.get("institutional_net_value"))
    breakdown_bits = []
    if promoter_val:
        color = "green" if promoter_val > 0 else "red"
        breakdown_bits.append(f'<span style="color:{style.COLORS[color]};">Promoter {style.fmt_inr(promoter_val)}</span>')
    if inst_val:
        color = "green" if inst_val > 0 else "red"
        breakdown_bits.append(f'<span style="color:{style.COLORS[color]};">Institutional {style.fmt_inr(inst_val)}</span>')
    if breakdown_bits:
        st.markdown(f'<div style="font-size:11px;color:{style.COLORS["text_3"]};margin-top:2px;">{" · ".join(breakdown_bits)}</div>', unsafe_allow_html=True)
    st.markdown(f'<hr style="margin:4px 0 10px 0;border:none;border-top:1px solid {style.COLORS["border"]};">', unsafe_allow_html=True)

detail_isin = st.session_state.get("confluence_detail_isin")
if detail_isin:
    row = merged[merged["canonical_isin"] == detail_isin].iloc[0]

    @st.dialog(f"{row['company'] or detail_isin}")
    def show_confluence_detail(isin=detail_isin, row=row):
        st.markdown(
            style.badge(row["category"], row["category_color"], f'{row["category_color"]}_bg' if row["category_color"] != "text_2" else "bg_sub", dot=False)
            + f' <span class="mono" style="margin-left:8px;">{isin}</span>',
            unsafe_allow_html=True,
        )
        st.markdown('<div class="sec-title">CONSTITUENT TRANSACTIONS</div>', unsafe_allow_html=True)
        any_rows = False
        insider_hits = cats["insider_trading"][cats["insider_trading"].get("canonical_isin") == isin] if not cats["insider_trading"].empty else pd.DataFrame()
        for _, r in insider_hits.iterrows():
            any_rows = True
            ttype = str(r.get("canonical_transaction_type") or "")
            color = "green" if "ACQUI" in ttype.upper() else "red"
            st.markdown(
                f'<div class="kv-row"><span>{style.fmt_date(r.get("canonical_transaction_date"))} · Insider · '
                f'<span style="color:{style.COLORS[color]};">{ttype.title()}</span> · {r.get("canonical_person") or "—"} '
                f'({r.get("canonical_person_category") or "—"})</span><span class="mono">{style.fmt_inr(r.get("canonical_value"))}</span></div>',
                unsafe_allow_html=True,
            )
        # Bulk and block are pooled before rendering, not looped separately:
        # one trade is disclosed by both counterparties AND can appear in both
        # feeds, so looping per category showed a single deal four times
        # (Ather Energy, 28 Aug 2026, Rs.1758.24Cr). Same-day same-client
        # round trips are dropped outright -- they net to no ownership change
        # and were burying the real deals (Atal Realtech's page was almost
        # entirely one LLP trading against itself).
        deal_frames = []
        for cat in ("bulk_deals", "block_deals"):
            if cats[cat].empty:
                continue
            hits = cats[cat][cats[cat].get("canonical_isin") == isin].copy()
            if hits.empty:
                continue
            hits["category"] = r2_data.CATEGORY_LABELS[cat]
            deal_frames.append(hits)
        round_trips_dropped = 0
        if deal_frames:
            deals = pd.concat(deal_frames, ignore_index=True)
            deals, round_trips_dropped = dedup.drop_intraday_round_trips(deals)
            deals = dedup.collapse_all(deals)
            deals = deals.sort_values("_dedup_date", ascending=False, na_position="last")
            for _, r in deals.iterrows():
                any_rows = True
                sides = r.get("_sides") or "—"
                color = "green" if sides == "BUY" else ("red" if sides == "SELL" else "text_2")
                value = fields.as_float(r.get("canonical_quantity")) * fields.as_float(r.get("canonical_price"))
                parties = r.get("_parties") or r.get("canonical_client") or "—"
                # Only worth saying when the row actually folded two exchanges
                # together; "NSE" alone is noise on every other line.
                exchanges = str(r.get("_exchanges") or "")
                cross_note = f" · {exchanges}" if "+" in exchanges else ""
                st.markdown(
                    f'<div class="kv-row"><span>{style.fmt_date(r.get("canonical_event_date"))} · '
                    f'{r.get("_feeds") or "—"} · '
                    f'<span style="color:{style.COLORS[color]};">{sides}</span> · {parties}{cross_note}</span>'
                    f'<span class="mono">{style.fmt_inr(value)}</span></div>',
                    unsafe_allow_html=True,
                )
        if round_trips_dropped:
            st.caption(
                f"{round_trips_dropped} same-day round-trip leg(s) hidden — one client buying and "
                "selling the same quantity on the same day, which changes no one's holding."
            )
        for cat in ("rights_issue", "preferential_issue"):
            hits = cats[cat][cats[cat].get("canonical_isin") == isin] if not cats[cat].empty else pd.DataFrame()
            for _, r in hits.iterrows():
                any_rows = True
                st.markdown(
                    f'<div class="kv-row"><span>{style.fmt_date(r.get("canonical_event_date"))} · {r2_data.CATEGORY_LABELS[cat]}'
                    f'{" · " + r.get("canonical_allottee_category") if pd.notna(r.get("canonical_allottee_category")) else ""}</span>'
                    f'<span class="mono">{style.fmt_inr(r.get("canonical_amount_raised"))}</span></div>',
                    unsafe_allow_html=True,
                )
        if not any_rows:
            st.caption("No constituent rows found (unexpected -- the summary row above was built from this ISIN's data).")
        if st.button("Close"):
            del st.session_state["confluence_detail_isin"]
            st.rerun()

    show_confluence_detail()

if not transfers.empty:
    st.write("")
    st.markdown('<div style="font-size:13px;font-weight:700;margin-bottom:8px;">Internal Transfers (excluded from FAR)</div>', unsafe_allow_html=True)
    st.caption("Same-day, matching-size bulk/block buy+sell on one ISIN -- portfolio rebalancing between two institutions, not a real change in who holds the float.")
    rows_html = "".join(
        f'<tr><td class="mono">{style.fmt_date(r["event_date"])}</td><td style="font-weight:500;">{r["company"] or "—"}</td>'
        f'<td style="color:{style.COLORS["text_2"]};">{r["buyer"] or "—"} ← {r["seller"] or "—"}</td>'
        f'<td class="mono" style="text-align:right;">{style.fmt_inr(r["value"])}</td></tr>'
        for _, r in transfers.iterrows()
    )
    st.markdown(
        '<div class="table-scroll"><table class="evt-table"><tr><th>DATE</th><th>COMPANY</th><th>BUYER ← SELLER</th><th style="text-align:right;">VALUE</th></tr>'
        + rows_html + "</table></div>",
        unsafe_allow_html=True,
    )
