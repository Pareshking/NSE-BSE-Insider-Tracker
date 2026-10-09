"""Track record: what happened after each kind of signal. Filled by the
signal lab; until then the page says exactly what will be measured."""
from __future__ import annotations

import streamlit as st
from ui import kit

from insiders_clean import signals


def render():
    kit.head('Track record', 'How stocks moved after each kind of signal, measured from the moment the filing '
                             'became public, after costs, with the number of cases next to every figure.')
    kit.note('Not measured yet.', 'This page fills in once the history backfill (NSE filings since Nov 2015) and '
                                  'the price join are done. No figure is shown before it is measured.')
    with kit.card('What will be measured', 'tr_plan'):
        st.html(
            '<div class="q-row"><b>Entry</b> the next session\'s close after the filing was broadcast, so only what you could have acted on counts.</div>'
            '<div class="q-row"><b>Returns</b> 1 week, 1, 3 and 6 months, minus the Nifty 500 over the same days.</div>'
            '<div class="q-row"><b>Costs</b> about 0.25% per round trip (STT both sides, stamp duty, DP charge) taken off every result.</div>'
            f'<div class="q-row"><b>Signals compared</b> spotlight ({signals.SPOTLIGHT_PCT_30D}%+ of market cap in 30 days) vs smaller buys; '
            f'float absorbers ({signals.FLOAT_ABSORBER_PCT_90D}%+ in 90 days); clusters vs single buyers; buys near the 52-week high vs after falls; '
            'promoter selling; preferential allotments at a premium vs a discount; high pledge.</div>'
            '<div class="q-row"><b>Sample size</b> shown next to every figure; a result from fewer than 30 cases is marked as such.</div>')
