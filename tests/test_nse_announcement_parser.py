"""Regression tests for parsing NSE attachment metadata."""
import pandas as pd
import pytest

from collectors.nse_events.announcements import parse


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
