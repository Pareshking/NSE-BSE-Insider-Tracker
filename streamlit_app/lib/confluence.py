"""Cross-category "smart money confluence" logic -- joins insider trading,
bulk/block deals, and rights/preferential issues by ISIN to surface signals
no single category shows on its own (a promoter buying in the open market
the same window a company does a promoter-only preferential allotment, for
example). Grounded in the standard event-study literature on these exact
disclosure types (Seyhun 1998 on insider-trade materiality; Cohen/Malloy/
Pomorski 2012 on routine-vs-opportunistic insider trades; Chaturvedula et
al. 2015 on Indian bulk-deal asymmetry; Anshuman/Marisetty/Subrahmanyam
2011 and Hertzel/Smith 1993 on preferential allotments; Myers/Majluf 1984
and Eckbo/Masulis 1992 on rights-issue adverse selection) -- deliberately
NOT a price-based backtest (no price history in this project by choice),
so every signal here is a capital-structure/ownership-change signal, not a
return prediction.

No history-dependent classification (e.g. Cohen et al.'s routine vs.
opportunistic insider-trade split, which needs each person's multi-month
trading calendar) -- this project only carries a 90-day rolling window per
run, not enough accumulated history yet to tell "trades every quarter like
clockwork" from "sudden, unpredictable buy."
"""
from __future__ import annotations

import pandas as pd

MCAP_TIERS = [
    (1000e7, "Micro (< Rs.1,000Cr)"),
    (5000e7, "Small (Rs.1,000-5,000Cr)"),
    (float("inf"), "Mid/Large (> Rs.5,000Cr)"),
]


def mcap_tier(market_cap) -> str | None:
    if market_cap is None or pd.isna(market_cap):
        return None
    for ceiling, label in MCAP_TIERS:
        if market_cap < ceiling:
            return label
    return MCAP_TIERS[-1][1]


def _with_market_cap(df: pd.DataFrame, mcap_lookup: "pd.Series | None") -> pd.DataFrame:
    df = df.copy()
    if mcap_lookup is not None and not mcap_lookup.empty and "canonical_symbol" in df.columns:
        df["_market_cap"] = df["canonical_symbol"].astype(str).str.upper().map(mcap_lookup)
    else:
        df["_market_cap"] = pd.NA
    return df


def promoter_insider_flow(insider_df: pd.DataFrame, mcap_lookup) -> pd.DataFrame:
    """Net promoter open-market flow per ISIN: signed value (BUY positive,
    SELL negative) summed over the whole window -- staggered buying across
    many small trades is exactly what this catches, since it's a sum, not
    a single transaction."""
    if insider_df.empty or "canonical_isin" not in insider_df.columns:
        return pd.DataFrame(columns=["canonical_isin", "company", "symbol", "promoter_net_value", "promoter_trades", "market_cap"])
    df = insider_df.copy()
    df = df.dropna(subset=["canonical_isin"])
    person_cat = df.get("canonical_person_category", pd.Series(dtype=object)).astype(str).str.upper()
    df = df[person_cat.str.contains("PROMOTER")]
    if df.empty:
        return pd.DataFrame(columns=["canonical_isin", "company", "symbol", "promoter_net_value", "promoter_trades", "market_cap"])
    ttype = df.get("canonical_transaction_type", pd.Series(dtype=object)).astype(str).str.upper()
    signed = pd.to_numeric(df.get("canonical_value"), errors="coerce").fillna(0)
    signed = signed.where(~ttype.str.contains("DISPOS"), -signed)
    df["_signed_val"] = signed
    df = _with_market_cap(df, mcap_lookup)
    grouped = df.groupby("canonical_isin").agg(
        company=("canonical_company", "first"), symbol=("canonical_symbol", "first"),
        promoter_net_value=("_signed_val", "sum"), promoter_trades=("_signed_val", "size"),
        market_cap=("_market_cap", "first"),
    ).reset_index()
    return grouped


def institutional_flow(bulk_df: pd.DataFrame, block_df: pd.DataFrame, mcap_lookup):
    """Net non-promoter bulk/block flow per ISIN, with same-day matching-size
    buy+sell on one ISIN pulled out as 'internal transfers' (portfolio
    rebalancing between two institutions, not a real change in who holds the
    float -- Keim & Madhavan 1996) rather than counted as real net flow.
    Returns (flow_df, transfers_df)."""
    combined = pd.concat([d for d in (bulk_df, block_df) if not d.empty], ignore_index=True) if any(not d.empty for d in (bulk_df, block_df)) else pd.DataFrame()
    if combined.empty or "canonical_isin" not in combined.columns:
        empty = pd.DataFrame(columns=["canonical_isin", "company", "symbol", "institutional_net_value", "institutional_trades", "market_cap"])
        return empty, pd.DataFrame()

    df = combined.dropna(subset=["canonical_isin"]).copy()
    df["_qty"] = pd.to_numeric(df.get("canonical_quantity"), errors="coerce").fillna(0)
    df["_price"] = pd.to_numeric(df.get("canonical_price"), errors="coerce").fillna(0)
    df["_value"] = df["_qty"] * df["_price"]
    side = df.get("canonical_side", pd.Series(dtype=object)).astype(str).str.upper()
    df["_signed_val"] = df["_value"].where(side != "SELL", -df["_value"])

    # Internal transfer: same ISIN, same date, a BUY and a SELL within 1% of
    # the same quantity -- pull both legs out before summing net flow.
    transfer_rows = []
    exclude_idx = set()
    date_col = "canonical_event_date"
    if date_col in df.columns:
        for (isin, event_date), sub in df.groupby(["canonical_isin", date_col]):
            buys = sub[side.loc[sub.index] == "BUY"]
            sells = sub[side.loc[sub.index] == "SELL"]
            for bi, brow in buys.iterrows():
                for si, srow in sells.iterrows():
                    if si in exclude_idx or bi in exclude_idx:
                        continue
                    if brow["_qty"] > 0 and abs(brow["_qty"] - srow["_qty"]) / brow["_qty"] <= 0.01:
                        exclude_idx.add(bi)
                        exclude_idx.add(si)
                        transfer_rows.append({
                            "canonical_isin": isin, "company": brow.get("canonical_company"),
                            "event_date": event_date, "quantity": brow["_qty"],
                            "value": brow["_value"], "buyer": brow.get("canonical_client"),
                            "seller": srow.get("canonical_client"),
                        })
                        break

    net_df = df[~df.index.isin(exclude_idx)]
    net_df = _with_market_cap(net_df, mcap_lookup)
    grouped = net_df.groupby("canonical_isin").agg(
        company=("canonical_company", "first"), symbol=("canonical_symbol", "first"),
        institutional_net_value=("_signed_val", "sum"), institutional_trades=("_signed_val", "size"),
        market_cap=("_market_cap", "first"),
    ).reset_index()
    return grouped, pd.DataFrame(transfer_rows)


def corporate_action_flags(rights_df: pd.DataFrame, preferential_df: pd.DataFrame) -> pd.DataFrame:
    """Per-ISIN: has_rights_issue, has_preferential, and the preferential
    allottee mix (PROMOTER / NON_PROMOTER / MIXED) -- the allottee category
    is what separates Anshuman et al.'s "owner-manager mitigation" signal
    from Hertzel & Smith's "outside certification" signal."""
    frames = []
    if not rights_df.empty and "canonical_isin" in rights_df.columns:
        r = rights_df.dropna(subset=["canonical_isin"])[["canonical_isin"]].drop_duplicates()
        r["has_rights_issue"] = True
        frames.append(r.set_index("canonical_isin"))
    if not preferential_df.empty and "canonical_isin" in preferential_df.columns:
        p = preferential_df.dropna(subset=["canonical_isin"]).copy()
        allottee_mix = p.groupby("canonical_isin")["canonical_allottee_category"].apply(
            lambda s: "PROMOTER" if (s == "PROMOTER").any() else ("MIXED" if (s == "MIXED").any() else "NON_PROMOTER")
        )
        pf = pd.DataFrame({"has_preferential": True, "preferential_allottee": allottee_mix})
        frames.append(pf)
    if not frames:
        return pd.DataFrame(columns=["canonical_isin", "has_rights_issue", "has_preferential", "preferential_allottee"])
    out = pd.concat(frames, axis=1).reset_index().rename(columns={"index": "canonical_isin"})
    # concat(axis=1) only creates has_rights_issue/has_preferential when the
    # corresponding input frame was non-empty -- .get(col, False) on a
    # DataFrame returns the literal False, not a column of False, when the
    # column is simply absent, so .fillna would crash on it.
    if "has_rights_issue" not in out.columns:
        out["has_rights_issue"] = False
    if "has_preferential" not in out.columns:
        out["has_preferential"] = False
    out["has_rights_issue"] = out["has_rights_issue"].fillna(False)
    out["has_preferential"] = out["has_preferential"].fillna(False)
    return out


def classify(row) -> tuple[str, str]:
    """One of the confluence archetypes from the literature, given a row
    with promoter_net_value, institutional_net_value, has_rights_issue,
    has_preferential, preferential_allottee. Returns (label, color_key)."""
    promoter_net = row.get("promoter_net_value") or 0
    inst_net = row.get("institutional_net_value") or 0
    has_pref = bool(row.get("has_preferential"))
    has_rights = bool(row.get("has_rights_issue"))
    allottee = row.get("preferential_allottee")

    if has_pref and allottee == "PROMOTER" and promoter_net > 0:
        return "Insider Alpha", "green"
    if has_pref and allottee in ("NON_PROMOTER", "MIXED") and inst_net > 0:
        return "Certification", "green"
    if has_rights and promoter_net < 0:
        return "Adverse Exit", "red"
    if has_rights and promoter_net >= 0:
        return "Capital Defense", "amber"
    if promoter_net > 0 and inst_net > 0:
        return "Accumulation", "green"
    if promoter_net < 0 and inst_net < 0:
        return "Distribution", "red"
    return "No Confluence", "text_2"
