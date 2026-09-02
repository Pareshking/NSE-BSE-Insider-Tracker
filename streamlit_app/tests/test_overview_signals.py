"""Checks for Overview's rollups, built from rows the live app actually showed.

    python streamlit_app/tests/test_overview_signals.py

Every case here is something the deployed app got wrong on the 2026-08-31
run, reported from the phone screen:

  * one bulk/block deal rendered as up to four rows (Adani Green, 09 Jun,
    Rs.3246.50Cr, as Bulk BUY + Bulk SELL + Block BUY + Block SELL) because
    both counterparties disclose it and it can appear in both feeds;
  * "493 securities" flagged as concentrated, every one at top3 100%, because
    a security traded by three or fewer clients is trivially 100%;
  * "+13981.7%" as a headline stake change, off a 1,000-share base;
  * an ESOP/pledge-type filing summed into promoter "accumulation" and ranked
    by % of market cap.

These call overview_aggregates directly against an in-memory bucket, so they
assert on the numbers rather than on rendered HTML.
"""
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO / "streamlit_app"))

import pandas as pd  # noqa: E402

RUN_DATE = "2026-08-31"


def _insider_rows():
    """Promoter filings, including two that are not open-market trades."""
    return pd.DataFrame([
        # Genuine open-market accumulation.
        dict(canonical_transaction_date="2026-08-28", canonical_company="Cineline India Limited",
             canonical_symbol="CINELINE", canonical_person="Promoter A",
             canonical_person_category="Promoter Group", canonical_transaction_type="Acquisition",
             canonical_mode="Market Purchase", canonical_quantity=1_000_000.0,
             canonical_value=25.00e7, canonical_holding_before=5_000_000.0,
             canonical_holding_after=6_000_000.0, canonical_isin="INE001A01001", exchange="nse"),
        # ESOP allotment -- not conviction, must not reach Accumulation Signals.
        dict(canonical_transaction_date="2026-08-27", canonical_company="LEAP India Limited",
             canonical_symbol="LEAP", canonical_person="Promoter B",
             canonical_person_category="Promoter", canonical_transaction_type="Disposal",
             canonical_mode="ESOS", canonical_quantity=50_000_000.0,
             canonical_value=2000.00e7, canonical_holding_before=80_000_000.0,
             canonical_holding_after=30_000_000.0, canonical_isin="INE002B01002", exchange="nse"),
        # Pledge -- likewise excluded.
        dict(canonical_transaction_date="2026-08-26", canonical_company="Virgo Global Ltd",
             canonical_symbol="VIRGO", canonical_person="Promoter C",
             canonical_person_category="Promoter", canonical_transaction_type="Disposal",
             canonical_mode="Pledge", canonical_quantity=900_000.0,
             canonical_value=78.44e5, canonical_holding_before=4_000_000.0,
             canonical_holding_after=3_100_000.0, canonical_isin="INE003C01003", exchange="nse"),
        # Tiny base holding -- the +13981.7% shape.
        dict(canonical_transaction_date="2026-08-05", canonical_company="AAA TECHNOLOGIES LIMITED",
             canonical_symbol="AAATECH", canonical_person="ASHOK KUMAR CHORDIA",
             canonical_person_category="Designated Person", canonical_transaction_type="Acquisition",
             canonical_mode="Market Purchase", canonical_quantity=139_817.0,
             canonical_value=1.4e7, canonical_holding_before=1_000.0,
             canonical_holding_after=140_817.0, canonical_isin="INE004D01004", exchange="nse"),
        # Real base holding -- this one SHOULD survive into stake changes.
        dict(canonical_transaction_date="2026-08-20", canonical_company="Solid Base Ltd",
             canonical_symbol="SOLID", canonical_person="Director D",
             canonical_person_category="Director", canonical_transaction_type="Acquisition",
             canonical_mode="Market Purchase", canonical_quantity=50_000.0,
             canonical_value=2.0e7, canonical_holding_before=100_000.0,
             canonical_holding_after=150_000.0, canonical_isin="INE005E01005", exchange="nse"),
    ])


def _deal_rows(side_pairs=True):
    """One Adani Green deal, disclosed by both sides, in both feeds."""
    rows = []
    for side in (["BUY", "SELL"] if side_pairs else ["BUY"]):
        rows.append(dict(canonical_event_date="2026-06-09", canonical_company="Adani Green Energy Ltd",
                         canonical_symbol="ADANIGREEN", canonical_client=f"Client {side}",
                         canonical_side=side, canonical_quantity=1_000_000.0,
                         canonical_price=3246.50, canonical_isin="INE006F01006", exchange="nse"))
    # A security with a broad field of clients, genuinely concentrated.
    for i in range(6):
        rows.append(dict(canonical_event_date="2026-08-30", canonical_company="Broad Field Ltd",
                         canonical_symbol="BROAD", canonical_client=f"Fund {i}",
                         canonical_side="BUY", canonical_quantity=(900_000 if i < 3 else 40_000),
                         canonical_price=100.0, canonical_isin="INE007G01007", exchange="nse"))
    # A security with only two clients -- trivially "top3 100%", must NOT flag.
    for i in range(2):
        rows.append(dict(canonical_event_date="2026-08-29", canonical_company="Thin Trading Ltd",
                         canonical_symbol="THIN", canonical_client=f"Solo {i}",
                         canonical_side="BUY", canonical_quantity=500_000.0,
                         canonical_price=100.0, canonical_isin="INE008H01008", exchange="nse"))
    return pd.DataFrame(rows)


def _empty(cols):
    return pd.DataFrame(columns=cols)


def build_module():
    """Import views/overview.py's aggregate with R2 access stubbed out."""
    import fake_r2  # noqa: F401  (ensures the tests dir is importable)
    import streamlit as st
    from lib import r2_data

    frames = {
        "insider_trading": _insider_rows(),
        "bulk_deals": _deal_rows(),
        "block_deals": _deal_rows(),
        "rights_issue": _empty(["canonical_event_date", "canonical_company", "canonical_isin", "exchange"]),
        "preferential_issue": _empty(["canonical_event_date", "canonical_company", "canonical_isin", "exchange"]),
    }
    r2_data.load_combined = lambda _c, category, exchanges, date: frames[category].copy()
    r2_data.market_cap_lookup = lambda _c, date: pd.Series(
        {"CINELINE": 301e7, "LEAP": 7380e7, "VIRGO": 318e7, "AAATECH": 200e7, "SOLID": 500e7})
    r2_data.page_gate = lambda *a, **kw: (None, [RUN_DATE])

    spec = importlib.util.spec_from_file_location(
        "overview_under_test", REPO / "streamlit_app" / "views" / "overview.py")
    mod = importlib.util.module_from_spec(spec)
    # Run only the module-level defs, not the Streamlit page body: executing
    # the page needs a script context. Pull the function out by exec'ing the
    # file up to the page_gate call.
    source = (REPO / "streamlit_app" / "views" / "overview.py").read_text()
    head = source.split("client, dates = r2_data.page_gate")[0]
    st.cache_data = lambda **kw: (lambda fn: fn)   # bypass caching in-process
    exec(compile(head, "overview.py", "exec"), mod.__dict__)
    return mod


def main() -> int:
    mod = build_module()
    agg = mod.overview_aggregates(None, RUN_DATE, ("nse",))
    failures = []

    def check(name, cond, detail=""):
        print(f"{'ok  ' if cond else 'FAIL'} {name}{'' if cond else '  -- ' + detail}")
        if not cond:
            failures.append(name)

    # 1. Non-market modes excluded from promoter accumulation.
    ranked = agg["promoter_ranking"]
    companies = set(ranked.index)
    check("ESOP filing kept out of Accumulation Signals",
          "LEAP India Limited" not in companies, f"got {companies}")
    check("pledge filing kept out of Accumulation Signals",
          "Virgo Global Ltd" not in companies, f"got {companies}")
    check("genuine market purchase retained",
          "Cineline India Limited" in companies, f"got {companies}")
    check("excluded count reported", agg["non_market_excluded"] == 2,
          f"got {agg['non_market_excluded']}")

    # 2. Transactions feed: date-ordered and deduplicated.
    top = agg["top_transactions"]
    adani = top[top["canonical_company"] == "Adani Green Energy Ltd"]
    check("one Adani Green deal renders as one row", len(adani) == 1, f"got {len(adani)} rows")
    check("both disclosed sides noted on the collapsed row",
          (adani["_side"] == "BUY & SELL").all() if len(adani) else False,
          f"got {list(adani['_side'])}")
    dates = top["_parsed_date"].tolist()
    check("feed is most-recent-first", dates == sorted(dates, reverse=True),
          f"got {[str(d)[:10] for d in dates]}")

    # 3. Concentration: thin books must not flag, broad ones must.
    alert_companies = {a["company"] for a in agg["concentration_alerts"]}
    check("2-client security not flagged as concentrated",
          "Thin Trading Ltd" not in alert_companies, f"got {alert_companies}")
    check("genuinely concentrated security still flagged",
          "Broad Field Ltd" in alert_companies, f"got {alert_companies}")
    check("no duplicate company across bulk/block",
          len(alert_companies) == len(agg["concentration_alerts"]),
          f"{len(agg['concentration_alerts'])} rows, {len(alert_companies)} names")

    # 4. Stake changes: absurd percentages gone, real ones kept.
    stake = agg["stake_changes"]
    people = set(stake.get("canonical_person", pd.Series(dtype=object)))
    check("1,000-share base no longer yields a headline %",
          "ASHOK KUMAR CHORDIA" not in people, f"got {people}")
    check("real position change retained", "Director D" in people, f"got {people}")
    if not stake.empty:
        check("no percentage above 1000% survives",
              stake["_pct_change"].abs().max() < 1000,
              f"max {stake['_pct_change'].abs().max():.1f}%")

    print(f"\n{len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
