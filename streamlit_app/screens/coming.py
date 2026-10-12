"""Datasets on the way: what each will answer, and how far it has got. A
section is built only when its data is in (docs/DATA_TO_PAGES.md)."""
from __future__ import annotations

import streamlit as st
from ui import kit

ITEMS = [
    ('SEBI ICDR minimum price on preferential issues', 'Needs daily volumes',
     'Higher of the 90-day and 10-day VWAP, to show whether promoters got shares below the floor. Preferential and rights issues themselves are on Capital raises.'),
    ('Rights take-up by promoters', 'Not in NSE\'s feed',
     'Whether promoters took up, renounced or let their entitlement lapse.'),
    ('Warrants and convertibles', 'Not collected yet',
     'Upfront money, exercise price against today\'s price, conversion deadline, and whether they were converted.'),
    ('QIPs', 'Not collected yet', 'Issue price, discount to market, and the institutions allotted.'),
    ('Management changes', 'Not collected yet', 'Director and KMP appointments and resignations, joined to their trades.'),
    ('Buyback price and route', 'Not collected yet', 'Offer price, tender or open-market route, and promoter participation.'),
]


def render():
    kit.head('Coming next', 'Datasets on the way. Each page is built once its data is collected and cleaned, '
                            'never filled with guesses.')
    with kit.card('Status', 'coming'):
        st.html(''.join(
            f'<div class="cm-r"><div><b>{kit.esc(name)}</b><p>{kit.esc(what)}</p></div>'
            f'<span class="tg {"tg-warn" if "Needs" in status else "tg-mute"}">{kit.esc(status)}</span></div>'
            for name, status, what in ITEMS))
