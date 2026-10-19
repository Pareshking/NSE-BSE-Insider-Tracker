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
        "attachment": "https://nsearchives.nseindia.com/corporate/xbrl/CIM_123_WebXMLFile_20261015_100000000.xml",
        "ixbrl": "https://nsearchives.nseindia.com/corporate/ixbrl/CIM_123_20261015_100000000_WEB.html",
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
    assert row["file_type"] == "xbrl"
    assert row["file_url"].endswith("_WebXMLFile_20261015_100000000.xml")
    assert row["xbrl_url"] == row["file_url"]
    assert bool(row["has_xbrl"]) is True
    assert row["broadcast_date"] == "2026-10-15"
    assert row["file_bytes"] == 3276


def test_dedicated_xbrl_feed_zip_of_documents_is_not_called_xbrl():
    # As NSE sent it on 15 Oct 2026: a 487 KB ZIP of the filing's documents beside the XML rows of ~5 KB.
    row = parse_xbrl([{"appId": "100514", "symbol": "BRACEPORT", "subject": "Resignation of Director/KMP/SMP",
                       "attachment": "https://nsearchives.nseindia.com/corporate/BRACEPORT_ROID_100514_KMP_Doc.zip",
                       "broadcastDateTime": "15-Oct-2026 14:12:58", "xbrlFileSize": "487.00 KB"}], "equities").iloc[0]
    assert row["file_type"] == "zip" and row["xbrl_url"] is None and bool(row["has_xbrl"]) is False


def test_nse_link_to_no_file_is_no_file():
    from collectors.nse_events.announcements import _file
    assert _file("https://nsearchives.nseindia.com/corporate/-") is None
    assert _file("-") is None
    assert _file("https://nsearchives.nseindia.com/corporate/GIRIRAJ_15102026160812_DPRegIntimation.pdf").endswith(".pdf")


def test_dedicated_xbrl_feed_ignores_rows_without_an_xml_attachment():
    parsed = parse_xbrl([{"appId": "APP-EMPTY", "symbol": "X", "ixbrl": "https://example.com/display.html"}])
    assert parsed.empty


def test_para_feed_prefers_xml_xbrl_field_over_pdf_and_ixbrl_display_links():
    parsed = parse_xbrl([{
        "appId": "APP-PARA",
        "symbol": "MARATHON",
        "subject": "Financial Results",
        "broadcastDateTime": "15-Oct-2026 10:00:00",
        "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/MARATHON_results.xml",
        "attachment": "https://nsearchives.nseindia.com/corporate/MARATHON_results.pdf",
        "ixbrl": "https://nsearchives.nseindia.com/corporate/ixbrl/MARATHON_results.html",
    }], "equities")
    assert len(parsed) == 1
    row = parsed.iloc[0]
    assert row["file_url"].endswith("MARATHON_results.xml")
    assert row["xbrl_url"] == row["file_url"]
    assert row["file_type"] == "xbrl"
    assert bool(row["has_xbrl"]) is True



def test_client_uses_dedicated_official_xbrl_announcements_endpoint(monkeypatch):
    requested = []
    monkeypatch.setattr(NSEClient, "warm_up", lambda self: setattr(self, "_warm", True))
    monkeypatch.setattr(NSEClient, "get", lambda self, url, **kwargs: requested.append((url, kwargs)) or {"data": [{"appId": "APP-1"}]})
    client = NSEClient()
    rows = client.xbrl_announcements(date(2026, 10, 15), date(2026, 10, 15), "equities")
    assert rows == [{"appId": "APP-1"}]
    assert requested == [(
        "https://www.nseindia.com/api/XBRL-announcements?index=equities&from_date=15-10-2026&to_date=15-10-2026&type=announcements",
        {"timeout": 10, "retries": 1},
    )]
    assert client.s.headers['Referer'] == "https://www.nseindia.com/"
    assert 'X-Requested-With' not in client.s.headers



def test_integrated_filing_client_supports_financials_and_governance_and_pagination():
    client = NSEClient()
    assert client.integrated_filing_url(date(2026, 10, 15), date(2026, 10, 16), 'financials').endswith(
        'type=Integrated%20Filing-%20Financials&page=1&size=100')
    assert client.integrated_filing_url(date(2026, 10, 15), date(2026, 10, 16), 'governance').endswith(
        'type=Integrated%20Filing-%20Governance&page=1&size=100')
    with pytest.raises(ValueError):
        client.integrated_filing_url(date(2026, 10, 15), date(2026, 10, 16), 'unknown')
    calls = []
    payloads = [
        {'data': [{'symbol': 'IOC'}], 'page': 1, 'size': 1, 'totalCount': 2},
        {'data': [{'symbol': 'IOC'}], 'page': 2, 'size': 1, 'totalCount': 2},
    ]
    client.get = lambda url, **kwargs: calls.append(url) or payloads.pop(0)
    assert len(client.integrated_filings(date(2026, 10, 15), date(2026, 10, 16), page_size=1)) == 2
    assert 'page=1&size=1' in calls[0] and 'page=2&size=1' in calls[1]


def test_integrated_filing_parser_keeps_only_exchange_supplied_xml_links():
    from collectors.nse_events.announcements import parse_integrated_xbrl
    rows = [
        {'symbol': 'IOC', 'companyName': 'Indian Oil Corporation Limited',
         'broadcastDateTime': '15-Oct-2026 18:43:11',
         'xbrl': 'https://nsearchives.nseindia.com/corporate/xbrl/IOC_results.xml'},
        {'symbol': 'IOC', 'companyName': 'Indian Oil Corporation Limited',
         'broadcastDateTime': '15-Oct-2026 18:43:11',
         'details': 'https://nsearchives.nseindia.com/corporate/IOC_results.pdf'},
        {'symbol': 'IOC', 'xbrl': 'https://nsearchives.nseindia.com/corporate/IOC_results.pdf'},
    ]
    parsed = parse_integrated_xbrl(rows, 'financials')
    assert len(parsed) == 1
    assert parsed.iloc[0]['symbol'] == 'IOC'
    assert parsed.iloc[0]['file_url'].endswith('IOC_results.xml')
    assert parsed.iloc[0]['subject'] == 'Integrated Filing - Financials'
    assert bool(parsed.iloc[0]['has_xbrl']) is True
