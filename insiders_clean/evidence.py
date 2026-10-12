"""What the measured track record says about a signal, in one plain sentence.

Reads the summary written by insiders_clean/track.py (per signal and horizon:
cases, median excess over Nifty 500 after costs, share of cases that beat the
index). The verdict uses the 3-month and 6-month rows only and is a label on
what happened in our one year of data, never a forecast.

  few              fewer than MIN_CASES cases at 3 months: too few to judge
  leaning_positive median above the index at 3 months (and at 6 months when it
                   has enough cases) and more than half of the cases beat it
  drag             median below the index on the same terms and under half beat it
  no_edge          anything else
  not_measured     no row for the signal
"""
from __future__ import annotations

import pandas as pd

MIN_CASES = 30
CAVEAT = '. Under a year of history, so a hint, not proof; the reasons below matter more.'


def _row(summary: pd.DataFrame, signal: str, horizon: str):
    hit = summary[(summary['signal'] == signal) & (summary['horizon'] == horizon)]
    if hit.empty or not int(hit['cases'].iloc[0]):
        return None
    r = hit.iloc[0]
    return {'n': int(r['cases']), 'median': float(r['median_excess']), 'beat': float(r['beat_index'])}


def verdict(summary: pd.DataFrame | None, signal: str) -> dict:
    """{'kind', 'tone', 'tag', 'text'}; tone is the kit's tag tone (buy, sell, mute)."""
    if summary is None or summary.empty:
        return {'kind': 'not_measured', 'tone': 'mute', 'tag': 'Not measured', 'text': 'Not measured yet.'}
    r3, r6 = _row(summary, signal, '3M'), _row(summary, signal, '6M')
    if r3 is None:
        return {'kind': 'not_measured', 'tone': 'mute', 'tag': 'Not measured', 'text': 'Not measured yet.'}
    if r3['n'] < MIN_CASES:
        return {'kind': 'few', 'tone': 'mute', 'tag': 'Too few cases',
                'text': f'Only {r3["n"]} cases have a 3-month result ({r3["median"]:+.1f}% median against Nifty 500): too few to judge.'}
    six = r6 if r6 is not None and r6['n'] >= MIN_CASES else None
    up = r3['median'] > 0 and r3['beat'] >= 50 and (six is None or six['median'] > 0)
    down = r3['median'] < 0 and r3['beat'] < 50 and (six is None or six['median'] < 0)
    head = f'Median {r3["median"]:+.1f}% against Nifty 500 over 3 months ({r3["beat"]:.0f}% of {r3["n"]} cases beat it)'
    tail = f', {six["median"]:+.1f}% over 6 months ({six["n"]} cases)' if six else ''
    if up:
        return {'kind': 'leaning_positive', 'tone': 'buy', 'tag': 'Early read: ahead', 'text': head + tail + CAVEAT}
    if down:
        return {'kind': 'drag', 'tone': 'sell', 'tag': 'Early read: behind', 'text': head + tail + CAVEAT}
    return {'kind': 'no_edge', 'tone': 'mute', 'tag': 'Early read: no edge', 'text': head + tail + CAVEAT}
