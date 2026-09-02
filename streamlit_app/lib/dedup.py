"""Collapsing rows that describe the same real-world event.

The canonical data is right to hold all of these rows -- each is a real,
separately-filed disclosure -- but showing them all as separate lines makes
one deal look like four, which is what the deployed app did on Ather Energy
(28 Aug 2026, Rs.1758.24Cr, appearing as Bulk SELL + Bulk BUY + Block SELL +
Block BUY) and on Adani Green in Overview's feed.

Three distinct causes, deliberately handled separately:

1. **Two counterparties.** A bulk/block deal is disclosed by the buyer AND
   the seller, so one trade arrives as two rows with opposite sides.

2. **Two feeds.** The same trade can be published in both the bulk-deals and
   the block-deals dataset, doubling it again.

3. **Two exchanges.** NSE and BSE can both carry the same underlying event.
   `scripts/r2_writer.py` already detects these and writes
   `cross_exchange_possible_match_id`, deliberately as a *flag* -- the
   project's rule is that it never merges NSE and BSE into one combined
   truth. Collapsing here is a display decision only: the underlying rows are
   untouched, and the surviving row is labelled with both exchanges so the
   reader can see that a merge happened and that it was only a *possible*
   match.
"""
from __future__ import annotations

import pandas as pd

from . import fields

# Company + day + quantity + price identifies the trade itself, independently
# of who filed it and which feed carried it. Value alone is not enough (two
# unrelated trades can share a round value); quantity AND price matching to
# the paisa on the same name and day is the trade.
DEAL_KEY = ["canonical_company", "_dedup_date", "_dedup_qty", "_dedup_price"]


def _deal_key_frame(df: pd.DataFrame, date_col: str) -> pd.DataFrame:
    out = df.copy()
    out["_dedup_date"] = fields.parse_dates(out[date_col]) if date_col in out.columns else pd.NaT
    out["_dedup_qty"] = fields.num_col(out, "canonical_quantity", fill=None)
    out["_dedup_price"] = fields.num_col(out, "canonical_price", fill=None)
    return out


def collapse_deal_sides(df: pd.DataFrame, *, date_col: str = "canonical_event_date") -> pd.DataFrame:
    """Collapse causes 1 and 2 for a bulk/block frame.

    Adds `_sides` ("BUY", "SELL" or "BUY & SELL"), `_feeds` (the category
    labels the trade appeared in) and `_parties` (every disclosing client),
    so the collapsed row still says what was folded into it. Returns the
    frame unchanged in shape when there is nothing to collapse.
    """
    if df.empty:
        return df
    keyed = _deal_key_frame(df, date_col)
    grouped = keyed.groupby(DEAL_KEY, dropna=False)

    sides = fields.text_col(keyed, "canonical_side", upper=True)
    keyed["_side_tmp"] = sides
    keyed["_sides"] = grouped["_side_tmp"].transform(
        lambda s: " & ".join(sorted({v for v in s if v})) or None)
    if "category" in keyed.columns:
        keyed["_feeds"] = grouped["category"].transform(lambda s: ", ".join(sorted(set(s.dropna()))))
    keyed["_parties"] = grouped["canonical_client"].transform(
        lambda s: ", ".join(sorted({str(v) for v in s.dropna() if str(v).strip()}))) \
        if "canonical_client" in keyed.columns else None

    collapsed = keyed.drop_duplicates(subset=DEAL_KEY, keep="first")
    return collapsed.drop(columns=["_side_tmp"], errors="ignore")


def collapse_cross_exchange(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse cause 3: rows the writer flagged as the same event on the
    other exchange.

    Only rows carrying a flag are touched; everything else passes through.
    Adds `_exchanges` naming every exchange the event was seen on, so a
    collapsed row is visibly a cross-exchange one rather than silently
    reduced to whichever side happened to sort first.
    """
    if df.empty or "cross_exchange_possible_match_id" not in df.columns:
        if not df.empty and "exchange" in df.columns:
            df = df.copy()
            df["_exchanges"] = df["exchange"].astype(str).str.upper()
        return df

    out = df.copy()
    own = fields.text_col(out, "canonical_event_id")
    other = fields.text_col(out, "cross_exchange_possible_match_id")
    # An unordered pair key, so the NSE row and its BSE counterpart hash to
    # the same bucket. Rows with no flag keep their own id and stand alone.
    out["_pair_key"] = [
        "|".join(sorted([a, b])) if b else (a or f"row-{i}")
        for i, (a, b) in enumerate(zip(own, other))
    ]
    if "exchange" in out.columns:
        out["_exchanges"] = out.groupby("_pair_key")["exchange"].transform(
            lambda s: " + ".join(sorted({str(v).upper() for v in s.dropna()})))
    collapsed = out.drop_duplicates(subset=["_pair_key"], keep="first")
    return collapsed.drop(columns=["_pair_key"], errors="ignore")


# NOTE ON WHERE THIS RUNS. As of 2026-09-02 the pipeline drops these rows at
# ingestion -- scripts/r2_writer.py::drop_intraday_round_trips, same rule and
# same tolerance -- so for any run written after that date this pass finds
# nothing. It stays because the bucket still holds earlier runs that were
# written before the rule existed, and picking an older date in the run
# selector reads that data. Keep the two in sync; if they ever disagree, the
# writer's version is the one that decides what exists.
#
# A client who buys and sells the same stock on the same day in the same
# size has finished the day flat: no ownership changed hands, so it is not
# accumulation, distribution or concentration -- it is day trading that
# happened to cross the 0.5% bulk-deal disclosure threshold. It shows up as a
# BUY and a SELL at slightly different values (a real pair: ALTIZEN VENTURES
# LLP in Atal Realtech, 05 Jun 2026, SELL Rs.5.83Cr against BUY Rs.5.81Cr --
# the difference is the day's spread, not a position).
#
# Note this is NOT the four-row duplicate above: there the two sides are two
# DIFFERENT parties at one price, and it is one real trade. Here it is ONE
# party on both sides at two prices, and it is two real trades that cancel.
# The tolerance catches quantities that match to rounding rather than
# exactly; set it to 0.0 to require an exact share-for-share match.
ROUND_TRIP_QTY_TOLERANCE = 0.01


def intraday_round_trips(df: pd.DataFrame, *, date_col: str = "canonical_event_date") -> pd.Series:
    """Boolean mask, aligned to `df.index`, of rows belonging to a same-day
    same-client round trip in one security.

    True for BOTH legs -- the buy and the sell are equally uninformative
    about who owns the company at the end of the day.
    """
    empty = pd.Series(False, index=df.index)
    needed = {"canonical_client", "canonical_side"}
    if df.empty or not needed.issubset(df.columns):
        return empty

    keyed = df.copy()
    keyed["_rt_date"] = fields.parse_dates(keyed[date_col]) if date_col in keyed.columns else pd.NaT
    keyed["_rt_qty"] = fields.num_col(keyed, "canonical_quantity")
    keyed["_rt_side"] = fields.text_col(keyed, "canonical_side", upper=True)
    security = "canonical_isin" if "canonical_isin" in keyed.columns else "canonical_company"

    mask = empty.copy()
    for _, group in keyed.groupby(["canonical_client", security, "_rt_date"], dropna=False):
        buys = group[group["_rt_side"] == "BUY"]["_rt_qty"].sum()
        sells = group[group["_rt_side"] == "SELL"]["_rt_qty"].sum()
        if buys <= 0 or sells <= 0:
            continue
        if abs(buys - sells) / max(buys, sells) <= ROUND_TRIP_QTY_TOLERANCE:
            mask.loc[group.index] = True
    return mask


def drop_intraday_round_trips(df: pd.DataFrame, *, date_col: str = "canonical_event_date"):
    """`(kept_rows, number_dropped)`. The count is returned rather than
    swallowed so a page can say what it removed instead of quietly showing
    fewer rows than the source has."""
    if df.empty:
        return df, 0
    mask = intraday_round_trips(df, date_col=date_col)
    return df[~mask], int(mask.sum())


def collapse_all(df: pd.DataFrame, *, date_col: str = "canonical_event_date") -> pd.DataFrame:
    """Both counterparty/feed collapsing and cross-exchange collapsing, in
    the order that matters: fold the two sides of a trade together first,
    then fold the exchanges, so a four-row deal ends as one row rather than
    two."""
    return collapse_cross_exchange(collapse_deal_sides(df, date_col=date_col))
