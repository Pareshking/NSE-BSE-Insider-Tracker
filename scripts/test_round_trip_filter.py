"""Checks r2_writer's intraday round-trip filter against real-shaped rows.

    python scripts/test_round_trip_filter.py

No network and no credentials: this only exercises the pure filtering
function, using native NSE and BSE bulk-deal field names.

The rows are modelled on Atal Realtech (05-09 Jun 2026), where one LLP
trading against itself accounted for most of the tape and buried the real
one-way deals in the same name.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import r2_writer  # noqa: E402


def nse(date, client, side, qty, price=116.0, symbol="ATALREAL"):
    return {"BD_DT_DATE": date, "BD_SYMBOL": symbol, "BD_SCRIP_NAME": "Atal Realtech Limited",
            "BD_CLIENT_NAME": client, "BD_BUY_SELL": side, "BD_QTY_TRD": qty, "BD_TP_WATP": price}


def bse(date, client, side, qty, price=116.0, code="544214"):
    return {"event_date": date, "security_code": code, "company": "Atal Realtech Limited",
            "person": client, "side": side, "quantity": qty, "price": price}


CASES = []


def case(name, exchange, category, rows, expect_kept, expect_dropped):
    CASES.append((name, exchange, category, rows, expect_kept, expect_dropped))


# The reported pattern: same client, same day, same size, both ways.
case("same-client round trip drops both legs", "nse", "bulk_deals", [
    nse("05-JUN-2026", "ALTIZEN VENTURES LLP", "S", 500000, 116.60),
    nse("05-JUN-2026", "ALTIZEN VENTURES LLP", "B", 500000, 116.20),
], expect_kept=0, expect_dropped=2)

# A genuine one-way deal in the same name on the same day must survive.
case("one-way deal survives alongside a round trip", "nse", "bulk_deals", [
    nse("05-JUN-2026", "ALTIZEN VENTURES LLP", "S", 500000, 116.60),
    nse("05-JUN-2026", "ALTIZEN VENTURES LLP", "B", 500000, 116.20),
    nse("05-JUN-2026", "GARG ATUL", "S", 200000, 119.00),
], expect_kept=1, expect_dropped=2)

# Net accumulation is NOT a round trip: 24,000 sold against 310,000 bought.
case("uneven buy/sell is accumulation, not a round trip", "nse", "bulk_deals", [
    nse("08-JUN-2026", "ALTIZEN VENTURES LLP", "S", 24000, 116.46),
    nse("08-JUN-2026", "ALTIZEN VENTURES LLP", "B", 310000, 116.13),
], expect_kept=2, expect_dropped=0)

# Two DIFFERENT parties on one trade is the Ather Energy case -- one real
# change of ownership. Knowing who bought is the point, so both are kept.
case("two counterparties on one trade are kept", "nse", "bulk_deals", [
    nse("28-AUG-2026", "GOVERNMENT OF SINGAPORE", "S", 1000000, 1758.24, symbol="ATHERENERG"),
    nse("28-AUG-2026", "HERO MOTOCORP LIMITED", "B", 1000000, 1758.24, symbol="ATHERENERG"),
], expect_kept=2, expect_dropped=0)

# Same client, same size, but different days -- a position held overnight.
case("across two days is not a round trip", "nse", "bulk_deals", [
    nse("05-JUN-2026", "ALTIZEN VENTURES LLP", "B", 500000, 116.20),
    nse("06-JUN-2026", "ALTIZEN VENTURES LLP", "S", 500000, 117.10),
], expect_kept=2, expect_dropped=0)

# BSE native field names, same rule.
case("BSE rows use the same rule", "bse", "block_deals", [
    bse("05/06/2026", "ALTIZEN VENTURES LLP", "S", 500000, 116.60),
    bse("05/06/2026", "ALTIZEN VENTURES LLP", "B", 500000, 116.20),
], expect_kept=0, expect_dropped=2)

# Quantities matching to rounding still count (tolerance), but a real
# difference does not.
case("near-equal quantities count as a round trip", "nse", "bulk_deals", [
    nse("05-JUN-2026", "FUND X", "B", 100000, 50.0),
    nse("05-JUN-2026", "FUND X", "S", 99500, 50.4),
], expect_kept=0, expect_dropped=2)

# Insider filings are out of scope -- they carry a person and a mode, not a
# client and a side.
case("insider category untouched", "nse", "insider_trading", [
    {"date": "2026-06-05", "acqName": "X", "buyQuantity": 100, "symbol": "ATALREAL"},
], expect_kept=1, expect_dropped=0)

# The rule fires on evidence only: an unreadable client or date keeps the row.
case("missing client keeps the rows", "nse", "bulk_deals", [
    nse("05-JUN-2026", "", "S", 500000, 116.60),
    nse("05-JUN-2026", "", "B", 500000, 116.20),
], expect_kept=2, expect_dropped=0)

case("unparseable date keeps the rows", "nse", "bulk_deals", [
    nse("not-a-date", "ALTIZEN VENTURES LLP", "S", 500000, 116.60),
    nse("not-a-date", "ALTIZEN VENTURES LLP", "B", 500000, 116.20),
], expect_kept=2, expect_dropped=0)


def main() -> int:
    failures = 0
    for name, exchange, category, rows, expect_kept, expect_dropped in CASES:
        kept, dropped = r2_writer.drop_intraday_round_trips(exchange, category, rows)
        ok = len(kept) == expect_kept and dropped == expect_dropped
        failures += not ok
        detail = "" if ok else f"  -- kept {len(kept)} (want {expect_kept}), dropped {dropped} (want {expect_dropped})"
        print(f"{'ok  ' if ok else 'FAIL'} {name}{detail}")
    print(f"\n{failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
