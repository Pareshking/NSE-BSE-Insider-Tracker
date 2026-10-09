import pandas as pd
import pytest

pytest.importorskip("streamlit")
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "streamlit_app"))
from lib import watchlist  # noqa: E402


def test_parse_normalises_and_dedupes():
    assert watchlist.parse(" reliance, INE002A01018\nreliance ;tcs ") == ["RELIANCE", "INE002A01018", "TCS"]
    assert watchlist.parse(None) == [] and watchlist.parse("  ,, ") == []


def test_limit_matches_isin_or_symbol_case_insensitive():
    df = pd.DataFrame({"isin": ["INE1", "INE2", "INE3"], "symbol": ["aa", "BB", None]})
    wl = {"AA", "INE3"}
    assert list(watchlist.limit(df, wl, "isin", "symbol")["isin"]) == ["INE1", "INE3"]
    assert watchlist.limit(df, set(), "isin", "symbol").empty
    assert watchlist.limit(df, wl, "nope", None).empty            # no usable column -> nothing matches
