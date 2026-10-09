"""Data status: is the data in, what did cleaning remove or hold back."""
from __future__ import annotations

import streamlit as st
from data import store
from ui import kit

from screens.ctx import load


def render():
    ctx = load()
    rep = store.report()
    kit.head('Data status', 'What the last cleaning run took in, removed and held back, so every number on the '
                            'site can be traced.')
    if not rep:
        kit.note('No cleaning report yet.', 'The nightly run writes clean/reports/{date}.json.')
        return
    t = rep.get('tables', {})
    it, dl = t.get('insider_trades', {}), t.get('deals', {})
    kit.tiles([
        kit.Tile('Insider filings', f"{it.get('output_rows', 0):,}", f"{it.get('input_rows', 0):,} in, "
                 f"{sum(v['count'] for v in it.get('removed', {}).values()):,} removed"),
        kit.Tile('Deal rows', f"{dl.get('output_rows', 0):,}", f"{dl.get('input_rows', 0):,} in, "
                 f"{dl.get('market_maker_legs', 0):,} market-maker legs"),
        kit.Tile('Unmatched securities', f"{len(rep.get('unmatched_securities', [])):,}", 'kept, with their filed names'),
        kit.Tile('Calendar confirmed to', (rep.get('calendar') or {}).get('confirmed_through', '—'),
                 'trading sessions for deadlines'),
    ])
    c1, c2 = st.columns(2)
    with c1, kit.card('Removed', 'removed', 'copies of other rows'):
        for table, v in t.items():
            for reason, r in v.get('removed', {}).items():
                st.html(f'<div class="q-row"><b>{kit.esc(table)}</b> · {kit.esc(reason.replace("_", " "))}: '
                        f'<span class="num">{r["count"]:,}</span></div>')
    with c2, kit.card('Held back for a look', 'flagged', 'kept, but out of rankings'):
        for table, v in t.items():
            for flag, n in sorted(v.get('flagged', {}).items(), key=lambda x: -x[1]):
                st.html(f'<div class="q-row"><b>{kit.esc(table)}</b> · {kit.esc(flag.replace("_", " "))}: '
                        f'<span class="num">{n:,}</span></div>')
    if rep.get('notes'):
        with kit.card('Notes from the run', 'notes'):
            for n in rep['notes']:
                st.html(f'<div class="q-row">{kit.esc(n)}</div>')
    kit.caption(f"Run {rep.get('run_date', '—')}. Latest filing in the data: {kit.day(ctx.ref)}.")
