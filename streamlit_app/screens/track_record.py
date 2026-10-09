"""Track record: how stocks moved after each kind of filing was made public.

Measured nightly by insiders_clean/track.py (entry the close of the session
after the day made public, returns over 1 week to 6 months minus Nifty 500,
0.25 points of costs off every return). This page only reads the result."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from data import store
from ui import kit
from ui.kit import esc

from insiders_clean import track
from screens.ctx import load

MIN_CASES = 30  # below this a figure is shown, but marked "few cases"


def _cell(r) -> str:
    """One horizon: median excess, beat-the-index share and cases."""
    if r is None or not r['cases']:
        return '<td class="sc-na">not yet<br><span>no complete window</span></td>'
    m, beat, n = r['median_excess'], r['beat_index'], int(r['cases'])
    tone = 'up' if m > 0 else 'down' if m < 0 else ''
    few = n < MIN_CASES
    return (f'<td class="sc {tone}{" few" if few else ""}"><b>{kit.pct(m, 1, signed=True)}</b>'
            f'<span>{beat:.0f}% beat · {kit.plural(n, "case")}{" · few" if few else ""}</span></td>')


def render():
    ctx = load()
    kit.head('Track record', 'What stocks did after each kind of filing was made public: median return over Nifty '
                             '500, after costs, with the number of cases.')
    summ = store.artifact('artifacts/track_summary.parquet')
    if summ.empty:
        kit.note('Not measured yet.', 'The nightly precompute writes the track record after the first run with prices.')
        return
    ev = store.artifact('artifacts/track_events.parquet')
    first = pd.to_datetime(ev['day']).min() if not ev.empty else None
    last = pd.to_datetime(ev['entry_date']).max() if not ev.empty else None
    kit.tiles([
        kit.Tile('Events measured', kit.count(len(ev)), f'{kit.day(first)} to {kit.day(last)}'),
        kit.Tile('Entry', 'Next close', 'close of the first session after the day made public'),
        kit.Tile('Benchmark', 'Nifty 500', 'same sessions, price index'),
        kit.Tile('Costs', f'{track.COST_PCT:.2f} pts', 'off every return, round trip'),
    ])
    with kit.card('Scorecard', 'tr_score', 'median excess return over Nifty 500 · share of cases that beat it'):
        heads = ''.join(f'<th>{h}</th>' for h in track.HORIZONS)
        rows = []
        for sig, label in track.SIGNALS.items():
            g = summ[summ['signal'] == sig].set_index('horizon')
            if g.empty:
                continue
            cells = ''.join(_cell(g.loc[h] if h in g.index else None) for h in track.HORIZONS)
            rows.append(f'<tr><th class="sc-l">{esc(label)}</th>{cells}</tr>')
        st.html(f'<div class="sc-wrap"><table class="sc-t"><thead><tr><th></th>{heads}</tr></thead>'
                f'<tbody>{"".join(rows)}</tbody></table></div>')
        kit.caption(f'Medians, not means: a few big winners would flatter a mean. "Few" marks fewer than {MIN_CASES} '
                    'cases. One year of history is one market regime, and windows overlap, so read these as '
                    'evidence building up, not as proof. Each company counts once per signal per 21 sessions.')

    if ev.empty:
        return
    with kit.card('Every case', 'tr_cases', 'pick a signal; newest first'):
        pick = st.selectbox('Signal', list(track.SIGNALS), format_func=track.SIGNALS.get, key='tr_sig',
                            label_visibility='collapsed')
        rows = ev[ev['signal'] == pick].copy()
        meta = ctx.securities.drop_duplicates('isin').set_index('isin') if not ctx.securities.empty else pd.DataFrame()
        for col in ('company', 'nse_symbol'):
            rows[col] = rows['isin'].map(meta[col]) if col in meta else None
        rows = rows.sort_values('day', ascending=False)
        kit.table(rows, [
            kit.Col('company', 'Company', 'co'), kit.Col('day', 'Made public', 'date'),
            kit.Col('entry_price', 'Entry', 'price', phone=False), kit.Col('value', 'Value', 'money', phone=False),
            *[kit.Col(f'excess_{h}', f'{h} vs Nifty', 'spct', phone=(h in ('1M', '3M'))) for h in track.HORIZONS],
        ], limit=200, download=f'track_{pick}')
