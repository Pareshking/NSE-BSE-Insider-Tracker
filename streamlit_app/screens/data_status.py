"""Data status: is the data in, what did cleaning remove or hold back."""
from __future__ import annotations

import streamlit as st
from data import store
from ui import kit

from screens.ctx import load

TABLES = {'insider_trades': 'Insider filings', 'deals': 'Bulk and block deals', 'securities': 'Securities'}
REASONS = {
    'repeat_filing': 'Same trade filed again', 'bse_same_filing_two_feeds': 'Same BSE filing in both BSE feeds', 'corrected_refiling': 'Replaced by a corrected filing',
    'superseded_by_revision': 'Replaced by a revision NSE marked', 'before_product_start': 'Traded before 08 Oct 2025',
    'no_readable_transaction_date': 'No readable trade date', 'intraday_round_trip': 'Intraday round trip (bought and sold same day)',
    'intraday_round_trip_across_exchanges': 'Intraday round trip across exchanges or feeds (bought and sold same day)',
    'same_deal_in_older_json_form': 'Same deal in the old feed format', 'same_trade_in_both_feeds': 'Same trade in bulk and block feeds',
    'unrecognised_mode': 'Mode of acquisition not stated', 'unmatched_security': 'Company not found in NSE/BSE lists',
    'holding_change_differs_from_quantity': "Holding change doesn't match shares traded",
    'missing_or_zero_value': 'Market trade with no value', 'mode_contradicts_side': 'Mode says buy, type says sell',
    'holding_jump_on_market_trade': 'Holding jumped 20x+ on a market trade', 'value_over_25pct_of_mcap': 'Value over 25% of market cap',
    'dates_out_of_order': 'Dates out of order', 'trade_date_in_future': 'Trade date in the future',
    'holding_moves_against_side': 'Holding moves against the side (a buy that lowers it)',
    'missing_quantity': 'Market trade with no shares filed', 'disclosed_before_trade': 'Disclosed before the trade ended',
    'disclosure_dated_in_future': 'Disclosure dated in the future', 'value_off_by_power_of_ten': 'Value off by a power of ten (lakh, crore)',
    'quantity_value_swapped': 'Shares and value swapped', 'price_far_outside_day_range': "Price far outside the day's range",
    'price_outside_day_range': "Price a little outside the day's range",
}
PRICE_NOT_CHECKED = {'no_price': 'no shares or value', 'no_isin': 'no security', 'no_dates': 'no trade date',
                     'span_too_long': 'span over a month', 'before_price_layer': 'before our prices',
                     'after_price_layer': 'after our last price day', 'no_print': 'no trade printed'}


def _sum(d: dict, *keys) -> int:
    return sum(int(d.get(k, 0)) for k in keys)


def _checks(it: dict, layer: dict) -> None:
    """The four checks from the 09 Oct brief, as counted by the cleaning run
    (insiders_clean/insider.py; what each holds back: docs/CLEAN_LAYER.md)."""
    dc = it.get('data_checks')
    if not dc:
        return
    c, fl = kit.count, it.get('flagged', {})
    rows = []
    h = dc['holding']['market']
    rows.append(f"<b>Holding change = shares traded.</b> {c(h.get('match', 0))} of "
                f"{c(sum(h.values()) - h.get('not_applicable', 0))} market trades match; "
                f"{c(_sum(h, 'differs', 'against_side_and_differs'))} differ in size and "
                f"{c(_sum(h, 'against_side', 'against_side_and_differs'))} move against the side, held back; "
                f"{c(h.get('not_filed', 0))} could not be checked (a holding or the quantity not filed).")
    p = dc['price']
    if p.get('price_layer'):
        m = p['market']
        skipped = ', '.join(f'{c(m[k])} {v}' for k, v in PRICE_NOT_CHECKED.items() if m.get(k))
        span = f" (sessions {kit.day(layer.get('first'))} to {kit.day(layer.get('last'))})" if layer.get('last') else ''
        rows.append(f"<b>Implied price inside the day's range</b>{kit.esc(span)}. {c(m.get('inside', 0))} market trades "
                    f"inside; held back: {c(m.get('power_of_ten', 0))} off by a power of ten, {c(m.get('swapped', 0))} "
                    f"with shares and value swapped, {c(_sum(m, 'far_below', 'far_above'))} more than "
                    f"{p['far_outside']:.0%} outside; marked only: {c(_sum(m, 'below', 'above'))} a little outside"
                    + (f'; not checked: {kit.esc(skipped)}.' if skipped else '.'))
    else:
        rows.append("<b>Implied price inside the day's range:</b> not run, no price layer loaded.")
    rows.append(f"<b>Disclosure dates.</b> {c(fl.get('disclosed_before_trade', 0))} disclosed before the trade ended, "
                f"{c(fl.get('disclosure_dated_in_future', 0))} disclosures and {c(fl.get('trade_date_in_future', 0))} "
                f"trades dated in the future, {c(fl.get('dates_out_of_order', 0))} other dates out of order; all held back.")
    ho = dc['holding_only']
    filed = ', '.join(f'{c(n)} as {k.replace("_", " ")}' for k, n in ho.get('filed_as', {}).items())
    rows.append(f"<b>Holding-only disclosures</b> (no shares traded, e.g. on appointment): {c(ho.get('count', 0))}, "
                "not counted as trades" + (f' (filed {kit.esc(filed)}).' if filed else '.'))
    # One row per check: its name, then what the run found (each row's first bold part is the check).
    cells = []
    for r in rows:
        name, _, rest = r.partition('</b>')
        cells.append(f'<tr><th>{name.replace("<b>", "").rstrip(".:")}</th><td>{rest.lstrip(" .:")}</td></tr>')
    with kit.card('Data checks', 'checks', 'insider filings, counted before the product window'):
        st.html(f'<table class="dq-t"><tbody>{"".join(cells)}</tbody></table>')


def render():
    ctx = load()
    rep = store.report()
    kit.head('Data quality', 'What the last cleaning run took in, removed and held back, so every number on the '
                            'site can be traced.')
    # TradingView Lightweight Charts (Apache-2.0) draws the price and trend charts with its logo off; its NOTICE
    # asks for this credit on a page of the site.
    st.html('<p class="cap">Charts: <a href="https://www.tradingview.com/" target="_blank" rel="noopener">TradingView '
            'Lightweight Charts</a>, Copyright © TradingView, Inc.</p>')
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
    u = rep.get('universe')
    if u:
        kit.note('Study universe.', f"{u['in_universe']:,} of {u['isins']:,} companies have a market cap of ₹{u['min_market_cap'] / 1e7:,.0f} Cr "
                                    f"or more and are shown; {u['under_cutoff']:,} smaller and {u['no_market_cap']:,} with no market cap are "
                                    'collected and kept, but left out of every page (insiders_clean/universe.py). The track record '
                                    "judges each event on that day's market cap.")
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
    _checks(it, rep.get('price_layer') or {})
    if rep.get('notes'):
        with kit.card('Notes from the run', 'notes'):
            for n in rep['notes']:
                st.html(f'<div class="q-row">{kit.esc(n)}</div>')
    kit.caption(f"Cleaning run of {kit.day(rep.get('run_date'))} · latest filing in the data {kit.day(ctx.ref)}.")
