"""Today as questions and answers (streamlit_app/screens/proto.py today_headline)."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'streamlit_app'))


def test_headline_names_the_block_that_is_most_of_the_selling():
    from screens.proto import today_headline
    d = pd.DataFrame([
        {'side': 'BUY', 'isin': 'A', 'company': 'Control Print', 'value': 14.5e7, 'pct_of_company': 1.49},
        {'side': 'BUY', 'isin': 'H', 'company': 'Havells', 'value': 125.6e7, 'pct_of_company': 0.17},
        {'side': 'SELL', 'isin': 'F', 'company': 'Happy Forgings', 'value': 597.65e7, 'pct_of_company': 3.44},
        {'side': 'SELL', 'isin': 'G', 'company': 'Gallantt', 'value': 182.6e7, 'pct_of_company': 1.24}])
    head, sub = today_headline(d, {})
    assert 'three quarters of the selling is Happy Forgings' in head
    assert 'Control Print, 1.49% of the company' in sub and 'The largest in rupees: Havells' in sub


def test_headline_with_nothing_past_the_bar():
    from screens.proto import today_headline
    assert today_headline(pd.DataFrame(), {})[0].startswith('No promoter or director decision')
