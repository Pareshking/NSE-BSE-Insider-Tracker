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


def _cell(r, sized: bool) -> str:
    """One horizon: median excess, beat-the-index share and cases."""
    if r is None or not r['cases']:
        return '<td class="sc-na">not yet<br><span>no complete window</span></td>'
    m = r.get('median_excess_sm') if sized else r['median_excess']
    beat = r.get('beat_size_index') if sized else r['beat_index']
    n = int(r['cases'])
    if m is None or pd.isna(m):
        return '<td class="sc-na">—<br><span>no index</span></td>'
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
        kit.Tile('Benchmark', 'Nifty 500', 'or the size-matched index, same sessions'),
        kit.Tile('Costs', f'{track.COST_PCT:.2f} pts', 'off every return, round trip'),
    ])
    if first is not None and last is not None:
        months = max(1, round((last - first).days / 30.4))
        kit.note('Early read.', f'Our measured history is about {months} months ({kit.day(first)} to {kit.day(last)}), one market '
                                'phase. Treat every row as a hint that gets firmer as history grows, not as proof of an edge.')
    bench = st.segmented_control('Benchmark', ['Nifty 500', 'Size-matched index'], default='Nifty 500', key='tr_bench',
                                 label_visibility='collapsed') or 'Nifty 500'
    sized = bench != 'Nifty 500'
    with kit.card('Scorecard', 'tr_score', f'median excess return over {"the size-matched index" if sized else "Nifty 500"}'
                  ' · share of cases that beat it'):
        heads = ''.join(f'<th>{h}</th>' for h in track.HORIZONS) + '<th>Before public</th>'
        rows = []
        for sig, label in track.SIGNALS.items():
            g = summ[summ['signal'] == sig].set_index('horizon')
            if g.empty:
                continue
            cells = ''.join(_cell(g.loc[h] if h in g.index else None, sized) for h in track.HORIZONS)
            pre = g['median_pre_move'].iloc[0] if 'median_pre_move' in g else None
            lag = g['median_lag'].iloc[0] if 'median_lag' in g else None
            cells += (f'<td class="sc-pre"><b>{kit.pct(pre, 1, signed=True)}</b><span>median move · {lag:.0f} sessions</span></td>'
                      if pre is not None and pd.notna(pre) and lag is not None and pd.notna(lag) else '<td class="sc-na">—</td>')
            rows.append(f'<tr><th class="sc-l">{esc(label)}</th>{cells}</tr>')
        st.html(f'<div class="sc-wrap"><table class="sc-t"><thead><tr><th></th>{heads}</tr></thead>'
                f'<tbody>{"".join(rows)}</tbody></table></div>')
        kit.caption(('Size-matched: large caps against Nifty 100, mid caps Midcap 150, small caps Smallcap 250, micro caps '
                     "Microcap 250, by today's size bucket. " if sized else '')
                    + "Before public: the stock's move from the last trade date to the day the filing was made public, and "
                    'how many sessions that took. ' + f'Medians, not means: a few big winners would flatter a mean. "Few" marks fewer than {MIN_CASES} '
                    'cases. One year of history is one market regime, and windows overlap, so read these as '
                    'evidence building up, not as proof. Each company counts once per signal per 21 sessions.')

    _forward(ctx, sized)
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
            kit.Col('pre_move', 'Before public', 'spct', phone=False), kit.Col('lag_sessions', 'Lag', 'num', phone=False),
            *[kit.Col(f'excess_sm_{h}' if sized else f'excess_{h}', f'{h} vs {"size" if sized else "Nifty"}', 'spct',
                      phone=(h in ('1M', '3M'))) for h in track.HORIZONS],
        ], limit=200, download=f'track_{pick}')


def _forward(ctx, sized: bool):
    """The forward record: signals stamped the night they fired, never edited
    (insiders_clean/track.py). Drawn once it holds a row."""
    fw = store.artifact('artifacts/forward_outcomes.parquet')
    if fw.empty:
        return
    fw = fw.copy()
    meta = ctx.securities.drop_duplicates('isin').set_index('isin') if not ctx.securities.empty else pd.DataFrame()
    for col in ('company', 'nse_symbol'):
        fw[col] = fw['isin'].map(meta[col]) if col in meta else None
    fw['label'] = fw['signal'].map(track.SIGNALS).fillna(fw['signal'])
    started = pd.to_datetime(fw['recorded_at']).min()
    done = {h: fw[f'excess_sm_{h}' if sized else f'excess_{h}'].dropna() for h in track.HORIZONS}
    sub = ' · '.join(f'{h} {kit.pct(x.median(), 1, signed=True)} ({kit.plural(len(x), "case")})' for h, x in done.items() if len(x))
    with kit.card('Forward record', 'tr_fwd', f'recorded the night each signal fired since {kit.day(started)}, never edited · '
                  + (f'median excess {sub}' if sub else 'no complete window yet')):
        kit.table(fw.sort_values(['day', 'recorded_at'], ascending=False), [
            kit.Col('company', 'Company', 'co'), kit.Col('label', 'Signal', 'text'),
            kit.Col('day', 'Made public', 'date'), kit.Col('recorded_at', 'Recorded', 'date', phone=False),
            kit.Col('close_at_record', 'Close then', 'price', phone=False), kit.Col('entry_price', 'Entry', 'price', phone=False),
            *[kit.Col(f'excess_sm_{h}' if sized else f'excess_{h}', f'{h} vs {"size" if sized else "Nifty"}', 'spct',
                      phone=(h == '1M')) for h in track.HORIZONS],
        ], limit=200, download='forward_record')
