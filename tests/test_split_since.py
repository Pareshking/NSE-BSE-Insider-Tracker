"""Price paid restated for splits and bonuses after the trade (streamlit_app/screens/ctx.py)."""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'streamlit_app'))
from screens.ctx import split_since  # noqa: E402


def test_split_since():
    prices = pd.DataFrame({'isin': ['A', 'B', 'C'], 'last_split_date': pd.to_datetime(['2026-06-01', '2026-06-01', None]),
                           'last_split_factor': [0.5, 0.2, None], 'n_splits': [1, 2, 0]})
    trades = pd.DataFrame({'isin': ['A', 'A', 'B', 'B', 'C', 'D', 'A'],
                           'trade_date_to': pd.to_datetime(['2026-05-01', '2026-06-01', '2026-07-01', '2026-05-01',
                                                            '2026-05-01', '2026-05-01', None])})
    f = split_since(trades, prices)
    assert f.iloc[0] == 0.5        # bought before the one split: paid x 0.5
    assert f.iloc[1] == 1.0        # bought on the ex-date: already on the new basis
    assert f.iloc[2] == 1.0        # after the last of two splits
    assert pd.isna(f.iloc[3])      # before the last of two: the earlier factor is unknown
    assert f.iloc[4] == 1.0 and f.iloc[5] == 1.0   # no split, or no price row
    assert pd.isna(f.iloc[6])      # no trade date, and the stock has split


def test_pre_public_move(monkeypatch):
    import numpy as np
    from screens import ctx
    d = pd.to_datetime(['2026-06-01', '2026-06-02', '2026-06-03', '2026-06-04']).to_numpy()
    monkeypatch.setattr(ctx.store, 'price_history', lambda: {'A': (d, np.array([100.0, 104.0, 110.0, 99.0]))})
    t = pd.DataFrame({'isin': ['A', 'A', 'B'], 'trade_date_to': pd.to_datetime(['2026-06-01', '2026-06-04', '2026-06-01']),
                      'broadcast_date': pd.to_datetime(['2026-06-03 18:00', '2026-06-02 10:00', '2026-06-03 10:00'])})
    m = ctx.pre_public_move(t)
    assert abs(m.iloc[0] - 10.0) < 1e-9 and pd.isna(m.iloc[1]) and pd.isna(m.iloc[2])
