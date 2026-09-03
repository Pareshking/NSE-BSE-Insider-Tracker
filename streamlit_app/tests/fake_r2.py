"""In-memory fake of the R2/S3 surface streamlit_app/lib/r2_data.py uses.

Objects are shaped exactly like the ones scripts/r2_writer.py writes: same
keys, same canonical_* column names, and -- deliberately -- the same mixed
date conventions the two exchanges really publish, since reading those
wrongly was a live bug.
"""
import io, json
import pandas as pd


class NoSuchKey(Exception):
    pass


class NoSuchBucket(Exception):
    pass


class _Exceptions:
    NoSuchKey = NoSuchKey
    NoSuchBucket = NoSuchBucket


class FakeS3:
    def __init__(self, objects, fail=None):
        self.objects = objects           # {key: bytes}
        self.fail = fail                 # exception to raise on every call
        self.exceptions = _Exceptions()

    def _maybe_fail(self):
        if self.fail:
            raise self.fail

    def get_object(self, Bucket, Key):
        self._maybe_fail()
        if Key not in self.objects:
            raise NoSuchKey(f"missing {Key}")
        return {"Body": io.BytesIO(self.objects[Key])}

    def get_paginator(self, name):
        outer = self

        class _P:
            def paginate(self, Bucket, Prefix=""):
                outer._maybe_fail()
                contents = [{"Key": k} for k in outer.objects if k.startswith(Prefix)]
                return [{"Contents": contents}]
        return _P()


def build_objects(dates, *, insider_cols=None, drop_cols=(), with_mcap=True, cast_by_exchange=None):
    """Synthetic bucket shaped exactly like scripts/r2_writer.py's layout."""
    objects = {}
    for date in dates:
        entries = []
        for ex in ("nse", "bse"):
            for cat in ("insider_trading", "bulk_deals", "block_deals", "rights_issue", "preferential_issue"):
                df = _frame(ex, cat, date, drop_cols, (cast_by_exchange or {}).get(ex))
                entries.append({
                    "exchange": ex, "category": cat, "status": "VERIFIED",
                    "written": True, "row_count": len(df), "reason": "live fetch",
                    "cross_exchange_matches_flagged": 1 if cat == "insider_trading" else 0,
                })
                objects[f"canonical/{ex}/{cat}/{date}/data.parquet"] = _parquet(df)
                objects[f"raw/{ex}/{cat}/{date}/raw.json"] = json.dumps(
                    df.to_dict("records"), default=str).encode()
        objects[f"manifests/{date}.json"] = json.dumps({"datasets": entries}).encode()
        if with_mcap:
            objects[f"reference/market_cap/{date}/data.json"] = json.dumps(
                [{"symbol": "ACME", "market_cap": 4.5e9}, {"symbol": "BETA", "market_cap": 9.0e10}]).encode()
    return objects


def _parquet(df):
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    return buf.getvalue()


def _frame(exchange, category, date, drop_cols=(), cast=None):
    """One category's rows for one exchange.

    Dates are written in the convention that exchange really uses: NSE ISO
    (2026-09-01), BSE Indian day-first (01/09/2026). Both have to land on
    the same day once parsed -- a single blanket dayfirst setting reads one
    of them months off.
    """
    base_date = pd.Timestamp(date)
    date_format = "%Y-%m-%d" if exchange == "nse" else "%d/%m/%Y"
    # Deliberately NOT in date order. The exchanges do not return sorted
    # rows, and a fixture that happens to be sorted lets an unsorted page
    # pass -- which is how Evidence & Drill-down shipped rendering Rights
    # Issues as 14 Jul, 11 May, 30 Jun, 13 Jun.
    days = [(base_date - pd.Timedelta(days=d)).strftime(date_format) for d in (10, 1, 40, 3)]
    if category == "insider_trading":
        df = pd.DataFrame({
            "canonical_transaction_date": days,
            "canonical_company": ["Acme Ltd", "Acme Ltd", "Beta Corp", "Beta Corp"],
            "canonical_symbol": ["ACME", "ACME", "BETA", "BETA"],
            "canonical_person": ["R Sharma", "R Sharma", "K Iyer", "K Iyer"],
            "canonical_person_category": ["PROMOTER", "PROMOTER", "DESIGNATED PERSON", "PROMOTER"],
            "canonical_transaction_type": ["ACQUISITION", "DISPOSAL", "ACQUISITION", "ACQUISITION"],
            "canonical_quantity": [1000.0, 400.0, 25000.0, 900.0],
            "canonical_value": [250000.0, 100000.0, 7_500_000.0, None],
            "canonical_holding_before": [50000.0, 51000.0, 900.0, 200000.0],
            "canonical_holding_after": [51000.0, 50600.0, 25900.0, 200900.0],
            "canonical_isin": ["INE001A01001", "INE001A01001", "INE002B01002", "INE002B01002"],
            "exchange": exchange,
            "cross_exchange_possible_match_id": [None, None, "m-1", None],
            "cross_exchange_match_basis": [None, None, "isin+date+qty", None],
            "cross_exchange_match_confidence": [None, None, "HIGH", None],
            "native_scrip": ["ACME", "ACME", "BETA", "BETA"],
        })
    elif category in ("bulk_deals", "block_deals"):
        df = pd.DataFrame({
            "canonical_event_date": days,
            "canonical_company": ["Acme Ltd", "Acme Ltd", "Acme Ltd", "Beta Corp"],
            "canonical_symbol": ["ACME", "ACME", "ACME", "BETA"],
            "canonical_client": ["Alpha Fund", "Alpha Fund", "Gamma AMC", "Alpha Fund"],
            "canonical_side": ["BUY", "SELL", "BUY", "SELL"],
            "canonical_quantity": [10000.0, 10000.0, 5000.0, None],
            "canonical_price": [120.0, 120.5, 118.0, 90.0],
            "canonical_isin": ["INE001A01001"] * 3 + ["INE002B01002"],
            "exchange": exchange,
        })
    else:
        df = pd.DataFrame({
            "canonical_event_date": days,
            "canonical_company": ["Acme Ltd", "Beta Corp", "Acme Ltd", "Beta Corp"],
            "canonical_company_unreliable": [False, False, True, False],
            "canonical_symbol": ["ACME", "BETA", "ACME", "BETA"],
            "canonical_stage": ["ANNOUNCED", "COMPLETED", "ANNOUNCED", "COMPLETED"],
            "canonical_amount_raised": [1.2e8, 4.0e7, None, 8.0e7],
            "canonical_isin": ["INE001A01001", "INE002B01002"] * 2,
            "exchange": exchange,
        })
        if category == "preferential_issue":
            df["canonical_allottee_category"] = ["PROMOTER", "NON_PROMOTER", "PROMOTER", "MIXED"]
    for col in drop_cols:
        if col in df.columns:
            df = df.drop(columns=[col])
    # One exchange writing a column as text while the other writes numbers is
    # how mixed-dtype columns actually arise: each Parquet file is internally
    # uniform, and the mixture only appears once load_combined concatenates
    # them. That concat is what crashed Evidence & Drill-down and Promoter
    # Activity ("Unknown format code 'f' for object of type 'str'").
    for col, fn in (cast or {}).items():
        if col in df.columns:
            df[col] = df[col].map(lambda v, _f=fn: v if v is None else _f(v))
    return df
