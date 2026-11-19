"""Average daily traded value (insiders_clean/slim.py) and a decision against it (screens/proto.day_multiple)."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from insiders_clean import slim


def test_average_daily_value_sums_exchanges_and_takes_the_last_20_sessions():
    days = pd.bdate_range('2026-10-01', periods=25)
    rows = [{'isin': 'INEA', 'date': d, 'exchange': ex, 'value': v} for i, d in enumerate(days)
            for ex, v in (('NSE', 100.0 if i >= 5 else 9999.0), ('BSE', 20.0))]
    rows += [{'isin': 'INEB', 'date': days[0], 'exchange': 'NSE', 'value': 50.0}]
    a = slim.average_daily_value(pd.DataFrame(rows)).set_index('isin')
    assert a.loc['INEA', 'adv_20d'] == 120.0 and a.loc['INEA', 'adv_sessions'] == 20
    assert a.loc['INEB', 'adv_sessions'] == 1


def test_day_multiple():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'streamlit_app'))
    from screens.proto import day_multiple
    assert day_multiple(30e7, 10e7) == 3.0
    assert day_multiple(30e7, None) is None and day_multiple(30e7, 0) is None
