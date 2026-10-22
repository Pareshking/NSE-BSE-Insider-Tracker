"""A buyback's offer against the close before the board meeting that considered it (screens/buybacks.py)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from insiders_clean import ideas

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'streamlit_app'))
from screens import buybacks  # noqa: E402


def test_the_premium_at_announcement_is_against_the_close_before_the_board_meeting(monkeypatch):
    d = pd.to_datetime(['2026-08-27', '2026-08-28', '2026-08-31', '2026-09-01', '2026-10-21']).to_numpy()
    c = np.array([400.0, 410.0, 450.0, 460.0, 480.0])
    monkeypatch.setattr(buybacks.store, 'price_history', lambda: {'INE0BBCO0001': (d, c)})
    bb = pd.DataFrame({'symbol': ['BBCO'], 'isin': ['INE0BBCO0001'], 'route': ['tender'], 'offer_price': [600.0],
                       'offer_open': pd.to_datetime(['2026-10-10']), 'record_date': pd.to_datetime(['2026-10-01']),
                       'first_report': [pd.NaT], 'daily_reports': [None], 'shares_sought': [1e6], 'offer_value': [6e8]})
    prices = pd.DataFrame({'isin': ['INE0BBCO0001'], 'latest_close': [480.0]})
    meetings = pd.DataFrame({'symbol': ['BBCO', 'BBCO'], 'meeting_date': pd.to_datetime(['2026-08-31', '2026-03-01']),
                             'buyback': [True, True]})
    r = buybacks.rows(bb, prices, meetings).iloc[0]
    assert r['announced'] == pd.Timestamp('2026-08-31')
    assert abs(r['vs_announce'] - (600 / 410 - 1) * 100) < 1e-9        # the close of 28 Aug, the session before
    assert abs(r['vs_market'] - 25.0) < 1e-9
    s = ideas.buyback_events(buybacks.rows(bb, prices, meetings), pd.Timestamp('2026-10-19')).iloc[0]['sentence']
    assert s.startswith('Tender buyback at 25% above the price now (+46% against the close before the board meeting)')
    assert pd.isna(buybacks.rows(bb, prices).iloc[0]['vs_announce'])     # no meeting: blank, never guessed
