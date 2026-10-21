"""Track record: how stocks moved after each kind of filing was made public.

Measured nightly by insiders_clean/track.py (entry the close of the session
after the day made public, returns over 1 week to 6 months minus Nifty 500,
0.25 points of costs off every return). This page only reads the result."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from data import store
from ui import charts, kit
from ui.kit import esc

from insiders_clean import basket, evidence, track
from screens.ctx import load

MIN_CASES = 30  # below this a figure is shown, but marked "few cases"


def _cell(r, sized: bool) -> tuple[str, int]:
    """One horizon: median excess and the share of cases that beat the index; and the cases behind it."""
    if r is None or not r['cases']:
        return '<td class="na" title="No complete window yet">·</td>', 0
    m = r.get('median_excess_sm') if sized else r['median_excess']
    beat = r.get('beat_size_index') if sized else r['beat_index']
    n = int(r.get('cases_sm', r['cases']) if sized else r['cases'])   # the cases behind this median (audit W16)
    if m is None or pd.isna(m) or not n or beat is None or pd.isna(beat):
        return '<td class="na" title="No index return">—</td>', n
    tone = 'up' if m > 0 else 'down' if m < 0 else ''
    few = ' few' if n < MIN_CASES else ''
    return (f'<td class="{tone}{few}" title="{n} cases{", few" if few else ""}"><b>{kit.pct(m, 1, signed=True)}</b>'
            f'<i>{beat:.0f}%</i></td>'), n


def _names(df: pd.DataFrame, ctx) -> pd.DataFrame:
    """Company name and NSE symbol from the securities list (its name column is display_name), keeping any
    the artifact already carries."""
    sec = ctx.securities.drop_duplicates('isin').set_index('isin') if not ctx.securities.empty else pd.DataFrame()
    df = df.copy()
    for col, src in (('company', 'display_name'), ('nse_symbol', 'nse_symbol')):
        mapped = df['isin'].map(sec[src]) if src in sec else pd.Series(None, index=df.index, dtype=object)
        df[col] = mapped.combine_first(df[col]) if col in df else mapped
    if 'name' in sec:
        df['company'] = df['company'].fillna(df['isin'].map(sec['name']))
    return df


def render():
    ctx = load()
    kit.head('Evidence', 'How stocks did after each kind of filing was made public, against the index, after costs.')
    summ = store.artifact('artifacts/track_summary.parquet')
    if summ.empty:
        kit.note('Not measured yet.', 'The nightly precompute writes the track record after the first run with prices.')
        return
    ev = store.artifact('artifacts/track_events.parquet')
    first = pd.to_datetime(ev['day']).min() if not ev.empty else None
    last = pd.to_datetime(ev['entry_date']).max() if not ev.empty else None
    months = max(1, round((last - first).days / 30.4)) if first is not None and last is not None else 0
    kit.tiles([
        kit.Tile('Events measured', kit.count(len(ev)), f'{kit.day(first)} to {kit.day(last)}'),
        kit.Tile('History', f'{months} months', 'one market phase: an early read, not proof'),
        kit.Tile('Entry · costs', f'Next close · {track.COST_PCT:.2f} pts', 'first session after the day made public; round trip'),
    ])
    bench = st.segmented_control('Benchmark', ['Nifty 500', 'Size-matched index'], default='Nifty 500', key='tr_bench',
                                 label_visibility='collapsed') or 'Nifty 500'
    sized = bench != 'Nifty 500'
    if 'restricted' in ev:
        free = st.toggle('Tradable only', value=False, key='tr_free',
                         help='Leave out events where, on the day made public, the stock was trade for trade, on the SME board, '
                              f'or locked at its band on any of the last {track.LOCK_WINDOW} sessions (judged on that day, no hindsight)')
        if free:
            ev = ev[~ev['restricted'].astype(bool)]
            summ = track.summary(ev)
            kit.caption(f'{kit.count(len(ev))} events a reader could trade freely on the day; the scorecard below is re-measured on them.')
    index = 'size-matched index' if sized else 'Nifty 500'
    with kit.card('Scorecard', 'tr_score', f'median return minus the {index}, after costs · share of cases that beat it'):
        heads = (''.join(f'<th title="Median return over {h} minus the {index}, after costs; the share of cases that beat it">{h}</th>'
                         for h in track.HORIZONS)
                 + '<th title="Cases with a complete 3-month window">Cases</th>'
                 + '<th title="Median move from the last trade date to the day made public (sessions in between)">Before</th>'
                 + '<th title="The early read: 3 and 6 months against Nifty 500, 30+ cases">Read</th>')
        rows = []
        for sig, label in track.SIGNALS.items():
            g = summ[summ['signal'] == sig].set_index('horizon')
            if g.empty:
                continue
            got = [_cell(g.loc[h] if h in g.index else None, sized) for h in track.HORIZONS]
            cells = ''.join(c for c, _ in got)
            n3 = dict(zip(track.HORIZONS, (n for _, n in got))).get('3M', 0)
            cells += f'<td class="n">{kit.count(n3) if n3 else "·"}</td>'
            pre = g['median_pre_move'].iloc[0] if 'median_pre_move' in g else None
            lag = g['median_lag'].iloc[0] if 'median_lag' in g else None
            cells += (f'<td class="n" title="{lag:.0f} sessions">{kit.pct(pre, 1, signed=True)}</td>'
                      if pre is not None and pd.notna(pre) and lag is not None and pd.notna(lag) else '<td class="na">—</td>')
            v = evidence.verdict(summ, sig)
            cells += f'<td class="rd">{kit.tag(v["tag"].replace("Early read: ", ""), v["tone"])}</td>'
            rows.append(f'<tr><th>{esc(label)}</th>{cells}</tr>')
        st.html(f'<div class="ev-wrap"><table class="ev-t"><thead><tr><th>Signal</th>{heads}</tr></thead>'
                f'<tbody>{"".join(rows)}</tbody></table></div>')
        kit.caption(('Size-matched: Nifty 100 / Midcap 150 / Smallcap 250 / Microcap 250 by size · ' if sized else '')
                    + f'faded: under {MIN_CASES} cases · one event per company per signal per 21 sessions')

    _forward(ctx, sized)
    _basket(ctx)
    if ev.empty:
        return
    with kit.card('Every case', 'tr_cases', 'pick a signal; newest first'):
        pick = st.selectbox('Signal', list(track.SIGNALS), format_func=track.SIGNALS.get, key='tr_sig',
                            label_visibility='collapsed')
        rows = _names(ev[ev['signal'] == pick], ctx).sort_values('day', ascending=False)
        kit.table(rows, [
            kit.Col('company', 'Company', 'co'), kit.Col('day', 'Made public', 'date'),
            kit.Col('entry_price', 'Entry', 'price', phone=False), kit.Col('value', 'Value', 'money', phone=False),
            kit.Col('pre_move', 'Before public', 'spct', phone=False), kit.Col('lag_sessions', 'Lag', 'num', phone=False),
            *([kit.Col('restriction', 'Tradability', phone=False)] if 'restriction' in rows else []),
            *[kit.Col(f'excess_sm_{h}' if sized else f'excess_{h}', f'{h} vs {"size" if sized else "Nifty"}', 'spct',
                      phone=(h in ('1M', '3M'))) for h in track.HORIZONS],
        ], limit=200, download=f'track_{pick}')


def _forward(ctx, sized: bool):
    """The forward record: signals stamped the night they fired, never edited
    (insiders_clean/track.py). Drawn once it holds a row."""
    fw = store.artifact('artifacts/forward_outcomes.parquet')
    if fw.empty:
        return
    fw = _names(fw, ctx)
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


def _basket(ctx):
    """Model basket: a paper portfolio on fixed rules from the forward record
    (insiders_clean/basket.py). Drawn once it holds a position."""
    pos = store.artifact('artifacts/basket_positions.parquet')
    if pos.empty:
        return
    nav = store.artifact('artifacts/basket_nav.parquet')
    pos = _names(pos, ctx)
    pos['label'] = pos['signal'].map(track.SIGNALS).fillna(pos['signal'])
    closed = pos[pos['status'] == 'closed']
    with kit.card('Model basket', 'tr_basket', f'paper portfolio, rules fixed in advance (version {basket.BASKET_VERSION}): '
                  f'every forward-record signal with an "ahead" early read, no surveillance or tight-band flag, '
                  f'equal weight, held {basket.HOLD_SESSIONS} sessions, {track.COST_PCT:.2f} pts cost each'):
        if not nav.empty:
            b, i = float(nav['basket'].iloc[-1]), float(nav['index'].iloc[-1])
            kit.tiles([
                kit.Tile('Basket', kit.pct(b - 100, 1, signed=True), f'since {kit.day(nav["date"].iloc[0])}', 'up' if b > 100 else 'down'),
                kit.Tile('Nifty 500, same days', kit.pct(i - 100, 1, signed=True), 'price index'),
                kit.Tile('Open positions', kit.count(int((pos['status'] == 'open').sum())), f'{kit.count(len(closed))} closed'),
                kit.Tile('Closed in profit', f'{(closed["ret"] > 0).mean() * 100:.0f}%' if len(closed) else '—',
                         f'median {kit.pct(closed["ret"].median(), 1, signed=True)}' if len(closed) else 'none closed yet'),
            ])
            chart = charts.basket_vs_index(nav)
            if chart is not None:
                st.altair_chart(chart, width='stretch')
        kit.table(pos.sort_values(['status', 'entry_date'], ascending=[False, False]), [
            kit.Col('company', 'Company', 'co'), kit.Col('label', 'Signal', 'text', phone=False),
            kit.Col('entry_date', 'Entry', 'date'), kit.Col('entry_price', 'Entry price', 'price', phone=False),
            kit.Col('status', 'Status', 'text', phone=False), kit.Col('ret', 'Return after costs', 'spct'),
        ], limit=200, download='model_basket')
