from datetime import date
"""Regression tests for parsing NSE attachment metadata."""
import pandas as pd
import pytest

from collectors.nse_events.announcements import parse, parse_xbrl
from collectors.nse_events.client import NSEClient


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (True, True),
        (False, False),
        ("true", True),
        ("TRUE", True),
        ("false", False),
        ("False", False),
        ("1", True),
        ("0", False),
        (1, True),
        (0, False),
        ("yes", True),
        ("no", False),
        (None, None),
        ("", None),
        ("unknown", None),
    ],
)
def test_has_xbrl_parses_boolean_values_without_truthy_string_bug(raw, expected):
    row = {
        "seq_id": "123",
        "an_dt": "15-Oct-2026 10:00:00",
        "hasXbrl": raw,
        "attchmntFile": "https://nsearchives.nseindia.com/corporate/sample.pdf",
    }
    parsed = parse([row])
    actual = parsed.iloc[0]["has_xbrl"]
    if expected is None:
        assert pd.isna(actual)  # pandas nullable boolean may be NA
    else:
        assert bool(actual) is expected


def test_has_xbrl_unknown_values_remain_unknown():
    parsed = parse([{"seq_id": "124", "hasXbrl": {"unexpected": "shape"}}])
    assert pd.isna(parsed.iloc[0]["has_xbrl"])



def test_dedicated_xbrl_feed_rows_are_normalized_as_stable_xml_companions():
    raw = [{
        "appId": "APP-123",
        "symbol": "MARATHON",
        "companyName": "Marathon Nextgen Realty Limited",
        "subject": "Outcome of Board Meeting",
        "eventType": "Outcome of Board Meeting",
        "broadcastDateTime": "15-Oct-2026 10:00:00",
        "disseminationDateTime": "15-Oct-2026 10:00:03",
        "attachment": "https://nsearchives.nseindia.com/corporate/xbrl/MARATHON_123.xml",
        "ixbrl": "https://nsearchives.nseindia.com/corporate/xbrl/MARATHON_123.html",
        "xbrlFileSize": "3.2 KB",
    }]
    first = parse_xbrl(raw, "equities")
    second = parse_xbrl(raw, "equities")
    assert len(first) == 1
    row = first.iloc[0]
    assert row["event_id"].startswith("nse:xbrl:equities:APP-123:")
    assert row["event_id"] == second.iloc[0]["event_id"]
    assert row["symbol"] == "MARATHON"
    assert row["subject"] == "Outcome of Board Meeting"
    assert row["file_type"] == "xml"
    assert row["file_url"].endswith("MARATHON_123.xml")
    assert row["xbrl_url"] == row["file_url"]
    assert bool(row["has_xbrl"]) is True
    assert row["broadcast_date"] == "2026-10-15"
    assert row["file_bytes"] == 3276


def test_dedicated_xbrl_feed_ignores_rows_without_an_xml_attachment():
    parsed = parse_xbrl([{"appId": "APP-EMPTY", "symbol": "X", "ixbrl": "https://example.com/display.html"}])
    assert parsed.empty



def test_client_uses_dedicated_official_xbrl_announcements_endpoint(monkeypatch):
    requested = []
    monkeypatch.setattr(NSEClient, "get", lambda self, url: requested.append(url) or {"data": [{"appId": "APP-1"}]})
    client = NSEClient()
    rows = client.xbrl_announcements(date(2026, 10, 15), date(2026, 10, 15), "equities")
    assert rows == [{"appId": "APP-1"}]
    assert requested == [
        "https://www.nseindia.com/api/XBRL-announcements?index=equities&from_date=15-10-2026&to_date=15-10-2026&type=announcements"
    ]
