"""Datasets on the way: what each will answer, and how far it has got. A
section is built only when its data is in (docs/DATA_TO_PAGES.md)."""
from __future__ import annotations

import streamlit as st
from ui import kit

ITEMS = [
    ('Preferential allotments and private placements', 'Collected, not cleaned yet',
     'Who got shares, at what price against the market price and the SEBI ICDR floor, how much, dilution, lock-in expiry.'),
    ('Rights issues', 'Collected, not cleaned yet',
     'Ratio and price, record date, and whether promoters took up, renounced or let their entitlement lapse.'),
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
            f'<span class="tg {"tg-warn" if "not cleaned" in status else "tg-mute"}">{kit.esc(status)}</span></div>'
            for name, status, what in ITEMS))
