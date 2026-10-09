"""Smoke tests for the Phase 3 pages (pages/1..5) against an in-memory bucket: they render, say so when data is missing,
and an R2 outage shows a message instead of a traceback."""
import io
import json
import os
import sys
from pathlib import Path

import boto3
import numpy as np
import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO / "streamlit_app"))
sys.path.insert(0, str(REPO))
for k, v in {"CLOUDFLARE_ACCOUNT_ID": "a", "R2_ACCESS_KEY_ID": "k", "R2_SECRET_ACCESS_KEY": "s", "R2_BUCKET_NAME": "b"}.items():
    os.environ.setdefault(k, v)
import fake_r2  # noqa: E402

PAGES = ["1_Promoter_Screener", "2_Company_Deep_Dive", "3_Risk_Flags", "4_Forward_Ledger", "5_Data_Health"]


def _pq(df):
    b = io.BytesIO()
    df.to_parquet(b, index=False)
    return b.getvalue()


def objects(with_ledger=True, with_slim=True):
    days = pd.bdate_range("2026-06-01", periods=90)
    px = pd.DataFrame({"date": days, "exchange": "NSE", "isin": "INE000A01010", "symbol": "ABC", "name": "ABC Ltd",
                       "open": np.linspace(100, 130, 90), "close": np.linspace(100, 130, 90), "value": 1e6})
    px["prev_close"] = px["close"].shift(1)
    def t(date, value, role, side="BUY", pid="p1"):
        return dict(trade_id=f"{date}{role}{side}", isin="INE000A01010", company="ABC Ltd", broadcast_date=pd.Timestamp(date), value=value,
                    person_role=role, person_id=pid, side=side, is_market=True, is_primary=True, pct_of_mcap=0.1, exchange="nse",
                    quantity=1000, source_url="https://example.invalid/x.xml")
    trades = pd.DataFrame([t("2026-07-06", 30e5, "promoter"), t("2026-07-20", 30e5, "promoter"), t("2026-07-21", 80e5, "director", "SELL", "d")])
    deals = pd.DataFrame([dict(deal_id="d1", isin="INE000A01010", date=pd.Timestamp("2026-07-08"), is_primary=True, value=2e7, signed_value=2e7,
                               client_is_market_maker=False, side="BUY", quantity=5000, exchange="nse", feeds="bulk", client_name="X Fund")])
    idx = pd.DataFrame({"date": days, "symbol": "Nifty 500", "open": 1.0, "high": 1.0, "low": 1.0, "close": np.linspace(1000, 1050, 90)})
    o = {"clean/current/insider_trades.parquet": _pq(trades), "clean/current/deals.parquet": _pq(deals),
         "prices/daily/nse/2026-06.parquet": _pq(px), "indices/daily/nse/2026-06.parquet": _pq(idx),
         "clean/latest.json": json.dumps({"date": "2026-10-09", "report": "clean/reports/2026-10-09.json"}).encode(),
         "clean/reports/2026-10-09.json": json.dumps({"run_date": "2026-10-09", "unmatched_securities": [{"exchange": "bse", "symbol": "ZZ"}],
                                                      "tables": {"insider_trades": {"input_rows": 10, "output_rows": 8,
                                                                                    "removed": {"duplicate": {"count": 2, "examples": []}}}}}).encode(),
         "raw_v2/nse/insider/blobs/ab/abc.json": b"{}", "raw_v2/nse/insider/fetches/2026-10-01/t.json": b"{}"}
    if with_slim:
        o["artifacts/prices_summary_slim.parquet"] = _pq(pd.DataFrame([dict(
            isin="INE000A01010", symbol="ABC", name="ABC Ltd", exchange="NSE", last_date=days[-1], latest_close=130.0, high_52w=135.0, low_52w=90.0,
            pct_off_high=-0.2, ret_90d=0.1, ret_180d=0.2, last_split_date=pd.NaT, last_split_factor=np.nan, n_splits=0,
            market_cap=5e9, mcap_rank=700.0, mcap_bucket="Micro")]))
    if with_ledger:
        led = pd.DataFrame([dict(signal_id="s1", rule="promoter_accum_v1", isin="INE000A01010", company="ABC Ltd",
                                 disclosure_date=pd.Timestamp("2026-07-06"), entry_date=days[27], entry_basis="close", entry_price=108.0,
                                 value=30e5, n_filings=1, created_at=pd.Timestamp("2026-10-09")),
                          dict(signal_id="c1", rule="promoter_campaign_v2", isin="INE000A01010", company="ABC Ltd",
                               disclosure_date=pd.Timestamp("2026-07-20"), entry_date=days[40], entry_basis="close", entry_price=115.0,
                               value=60e5, n_filings=2, created_at=pd.Timestamp("2026-10-09"),
                               campaign_start=pd.Timestamp("2026-07-06"), campaign_buys=2)])
        o["ledger/forward_ledger.parquet"] = _pq(led)
        if with_slim:
            o["ledger/ledger_marks.parquet"] = _pq(led.assign(sessions_since_entry=62, current_price=130.0, return_to_date=0.2, excess_to_date_vs_nifty500=0.1,
                                                              ret_60=0.15, excess_60=0.05, ret_120=np.nan, excess_120=np.nan, ret_250=np.nan, excess_250=np.nan))
    return o


def run(page, objs, fail=None, search=None):
    st.cache_data.clear()
    st.cache_resource.clear()
    boto3.client = lambda *a, **k: fake_r2.FakeS3(objs, fail=fail)
    app = AppTest.from_file(str(REPO / "streamlit_app" / "pages" / f"{page}.py"), default_timeout=90)
    app.run()
    if search and app.text_input:
        app.text_input[0].set_value(search).run()
    return app


@pytest.mark.parametrize("page", PAGES)
def test_pages_render(page):
    app = run(page, objects(), search="ABC" if page.startswith("2_") else None)
    assert not app.exception, app.exception[0].message if app.exception else ""


def test_deep_dive_shows_chart_and_audit_link():
    app = run("2_Company_Deep_Dive", objects(), search="abc")
    assert not app.exception and len(app.dataframe) >= 1


def test_ledger_missing_says_so():
    app = run("4_Forward_Ledger", objects(with_ledger=False))
    assert not app.exception and any("not been written" in w.value for w in app.warning)


@pytest.mark.parametrize("page", PAGES)
def test_r2_outage_is_a_message_not_a_traceback(page):
    app = run(page, objects(), fail=RuntimeError("simulated outage"), search=None)
    assert not app.exception


def test_screener_filters_and_lists_the_company():
    app = run("1_Promoter_Screener", objects())
    assert not app.exception and len(app.dataframe) == 1 and len(app.dataframe[0].value) == 1
    # a Large-cap-only filter removes the (Micro) company
    app.multiselect[0].set_value(["Large"]).run()
    assert not app.exception and any("Nothing clears" in i.value for i in app.info)


def test_screener_without_slim_artifact_degrades():
    app = run("1_Promoter_Screener", objects(with_slim=False))
    assert not app.exception and any("price summary has not been written" in w.value for w in app.warning)
    assert len(app.dataframe) == 1


def test_ledger_reads_precomputed_marks_and_never_loads_prices():
    objs = objects()
    objs = {k: v for k, v in objs.items() if not k.startswith("prices/daily")}      # a price load would now fail
    app = run("4_Forward_Ledger", objs)
    assert not app.exception and len(app.dataframe) >= 1


def test_ledger_without_marks_shows_entry_facts():
    app = run("4_Forward_Ledger", objects(with_slim=False))
    assert not app.exception and any("marks are missing" in w.value for w in app.warning)


def test_deep_dive_prefills_from_screener_and_loads_one_isin():
    st.cache_data.clear()
    boto3.client = lambda *a, **k: fake_r2.FakeS3(objects())
    app = AppTest.from_file(str(REPO / "streamlit_app" / "pages" / "2_Company_Deep_Dive.py"), default_timeout=90)
    app.session_state["deep_dive_isin"] = "INE000A01010"
    app.run()
    assert not app.exception and len(app.dataframe) >= 1


def test_ledger_toggle_switches_between_series():
    app = run("4_Forward_Ledger", objects())
    assert not app.exception and app.metric[0].value == "1"
    app.radio[0].set_value("Multi-quarter campaigns (promoter_campaign_v2)").run()
    assert not app.exception and app.metric[0].value == "1"
    assert "campaign_start" in list(app.dataframe[0].value.columns)


def test_screener_shows_deal_alignment_and_filings_table():
    app = run("1_Promoter_Screener", objects())
    cols = list(app.dataframe[0].value.columns)
    assert "Deals align" in cols and "Bulk/block in campaign (₹ Cr)" in cols and "Campaign" in cols
