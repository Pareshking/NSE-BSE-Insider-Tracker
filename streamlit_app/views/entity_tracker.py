"""Entity Tracker -- reverse-lookup by person/fund/client name across all
5 categories. Shows what an entity did (90-day aggregated flow, companies
touched, whether their entry coincided with a preferential allotment) --
not whether it worked out, since this project deliberately has no price
history to judge that against.
"""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import confluence, r2_data, style

st.markdown("### Entity Tracker")
st.caption("Search a promoter, insider, or institutional client name to see everything they did across insider trading and bulk/block deals this window.")

client = r2_data.get_client()
if not r2_data.r2_configured():
    st.warning("R2 credentials aren't configured -- see the Overview page for what's needed.")
    st.stop()

dates = r2_data.list_manifest_dates(client)
if not dates:
    st.info("No manifests found in the bucket yet.")
    st.stop()

top = st.columns([1, 1, 2])
with top[0]:
    selected_date = st.selectbox("Run date", dates, index=0)
with top[1]:
    exchange_choice = st.radio("Exchange", ["Both", "NSE", "BSE"], horizontal=True, label_visibility="collapsed")
exchanges = r2_data.EXCHANGES if exchange_choice == "Both" else [exchange_choice.lower()]

name_query = st.text_input("Entity name", placeholder="e.g. a promoter, HNI, or institution name…")
if not name_query:
    st.caption("Type a name to search -- nothing is listed until you do, this isn't a browse-everyone directory.")
    st.stop()

q = name_query.strip().lower()
cats = {c: pd.concat([r2_data.load_canonical(client, ex, c, selected_date) for ex in exchanges], ignore_index=True)
        for c in r2_data.CATEGORIES}
preferential_actions = confluence.corporate_action_flags(pd.DataFrame(), cats["preferential_issue"])
pref_isins_by_promoter = set(preferential_actions.loc[preferential_actions["preferential_allottee"] == "PROMOTER", "canonical_isin"]) if not preferential_actions.empty else set()

rows = []
insider_hits = cats["insider_trading"][cats["insider_trading"].get("canonical_person", pd.Series(dtype=object)).astype(str).str.lower().str.contains(q, na=False)] if not cats["insider_trading"].empty else pd.DataFrame()
for _, r in insider_hits.iterrows():
    ttype = str(r.get("canonical_transaction_type") or "").upper()
    val = pd.to_numeric(r.get("canonical_value"), errors="coerce") or 0
    signed = -val if "DISPOS" in ttype else val
    rows.append({
        "date": r.get("canonical_transaction_date"), "category": "insider_trading",
        "company": r.get("canonical_company"), "isin": r.get("canonical_isin"),
        "side": "SELL" if "DISPOS" in ttype else "BUY", "value": val, "signed_value": signed,
        "exchange": r.get("exchange"), "entity_role": r.get("canonical_person_category"),
    })
for cat in ("bulk_deals", "block_deals"):
    hits = cats[cat][cats[cat].get("canonical_client", pd.Series(dtype=object)).astype(str).str.lower().str.contains(q, na=False)] if not cats[cat].empty else pd.DataFrame()
    for _, r in hits.iterrows():
        side = str(r.get("canonical_side") or "").upper()
        val = (pd.to_numeric(r.get("canonical_quantity"), errors="coerce") or 0) * (pd.to_numeric(r.get("canonical_price"), errors="coerce") or 0)
        rows.append({
            "date": r.get("canonical_event_date"), "category": cat,
            "company": r.get("canonical_company"), "isin": r.get("canonical_isin"),
            "side": side, "value": val, "signed_value": -val if side == "SELL" else val,
            "exchange": r.get("exchange"), "entity_role": None,
        })

if not rows:
    st.info(f"No insider or bulk/block activity matching “{name_query}” this run.")
    st.stop()

entity_df = pd.DataFrame(rows)
net_value = entity_df["signed_value"].sum()
n_companies = entity_df["company"].nunique()
n_trades = len(entity_df)

k1, k2, k3 = st.columns(3)
with k1:
    st.markdown(style.kpi_card("NET VALUE", style.fmt_inr(net_value)), unsafe_allow_html=True)
with k2:
    st.markdown(style.kpi_card("COMPANIES TOUCHED", f"{n_companies:,}"), unsafe_allow_html=True)
with k3:
    st.markdown(style.kpi_card("TRANSACTIONS", f"{n_trades:,}"), unsafe_allow_html=True)

st.write("")
st.markdown('<div style="font-size:13px;font-weight:700;margin-bottom:8px;">By Company</div>', unsafe_allow_html=True)
by_company = entity_df.groupby(["company", "isin"]).agg(
    net_value=("signed_value", "sum"), trades=("signed_value", "size"),
).reset_index().sort_values("net_value", key=abs, ascending=False)

rows_html = []
for _, r in by_company.iterrows():
    coincided = r["isin"] in pref_isins_by_promoter
    badge = style.badge("+ PROMOTER PREFERENTIAL SAME WINDOW", "blue", "blue_bg", dot=False) if coincided else ""
    color = "green" if r["net_value"] >= 0 else "red"
    rows_html.append(
        f'<tr><td style="font-weight:500;">{r["company"] or "—"} {badge}</td>'
        f'<td class="mono" style="text-align:right;color:{style.COLORS[color]};font-weight:600;">{style.fmt_inr(r["net_value"])}</td>'
        f'<td class="mono" style="text-align:right;">{int(r["trades"])}</td></tr>'
    )
st.markdown(
    '<table class="evt-table"><tr><th>COMPANY</th><th style="text-align:right;">NET VALUE</th><th style="text-align:right;">TRADES</th></tr>'
    + "".join(rows_html) + "</table>",
    unsafe_allow_html=True,
)

st.write("")
st.markdown('<div style="font-size:13px;font-weight:700;margin-bottom:8px;">All Transactions</div>', unsafe_allow_html=True)
detail = entity_df.sort_values("date", ascending=False).copy()
detail["date"] = detail["date"].map(style.fmt_date)
detail["category"] = detail["category"].map(r2_data.CATEGORY_LABELS)
detail["value"] = detail["value"].map(style.fmt_inr)
detail["exchange"] = detail["exchange"].astype(str).str.upper()
st.dataframe(
    detail[["date", "category", "company", "side", "value", "exchange", "entity_role"]].rename(columns={
        "date": "Date", "category": "Category", "company": "Company", "side": "Side",
        "value": "Value", "exchange": "Exchange", "entity_role": "Role",
    }),
    hide_index=True, use_container_width=True,
)
st.caption("Shows what this entity did -- not whether it paid off. No price history in this project to judge forward returns against.")
