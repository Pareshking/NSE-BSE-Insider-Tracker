"""Data status: is the data in, what did cleaning remove or hold back."""
from __future__ import annotations

import streamlit as st
from data import store
from ui import kit

from screens.ctx import load

TABLES = {'insider_trades': 'Insider filings', 'deals': 'Bulk and block deals', 'securities': 'Securities'}
REASONS = {
    'repeat_filing': 'Same trade filed again', 'corrected_refiling': 'Replaced by a corrected filing',
    'superseded_by_revision': 'Replaced by a revision NSE marked', 'before_product_start': 'Traded before 08 Oct 2025',
    'no_readable_transaction_date': 'No readable trade date', 'intraday_round_trip': 'Intraday round trip (bought and sold same day)',
    'same_deal_in_older_json_form': 'Same deal in the old feed format', 'same_trade_in_both_feeds': 'Same trade in bulk and block feeds',
    'unrecognised_mode': 'Mode of acquisition not stated', 'unmatched_security': 'Company not found in NSE/BSE lists',
    'holding_change_differs_from_quantity': "Holding change doesn't match shares traded",
    'missing_or_zero_value': 'Market trade with no value', 'mode_contradicts_side': 'Mode says buy, type says sell',
    'holding_jump_on_market_trade': 'Holding jumped 20x+ on a market trade', 'value_over_25pct_of_mcap': 'Value over 25% of market cap',
    'dates_out_of_order': 'Dates out of order', 'trade_date_in_future': 'Trade date in the future',
}


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
        kit.Tile('Calendar confirmed to', kit.day((rep.get('calendar') or {}).get('confirmed_through')),
                 'trading sessions for deadlines'),
    ])
    c1, c2 = st.columns(2)
    with c1, kit.card('Removed', 'removed', 'copies or out of the window, counted'):
        for table, v in t.items():
            items = [(REASONS.get(r, r.replace('_', ' ').capitalize()), x['count'], '') for r, x in v.get('removed', {}).items()]
            if items:
                st.html(f'<div class="bl-h">{kit.esc(TABLES.get(table, table))}</div>' + kit.bar_list(items))
    with c2, kit.card('Held back for a look', 'flagged', 'kept, but out of rankings and totals'):
        for table, v in t.items():
            items = [(REASONS.get(f, f.replace('_', ' ').capitalize()), n, 'warn') for f, n in v.get('flagged', {}).items()]
            if items:
                st.html(f'<div class="bl-h">{kit.esc(TABLES.get(table, table))}</div>' + kit.bar_list(items))
    if rep.get('notes'):
        with kit.card('Notes from the run', 'notes'):
            for n in rep['notes']:
                st.html(f'<div class="q-row">{kit.esc(n)}</div>')
    kit.caption(f"Cleaning run of {kit.day(rep.get('run_date'))} · latest filing in the data {kit.day(ctx.ref)}.")
