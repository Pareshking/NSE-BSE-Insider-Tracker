"""Other filings: stake changes of 5% or more, and holdings that changed hands
without a market trade. One page, two tabs; neither counts as buying or
selling anywhere else on the site."""
from __future__ import annotations

import streamlit as st
from ui import kit

from screens import sast, transfers


def render():
    kit.head('Other filings', 'Stake changes of 5% or more, and gifts, inter-se transfers, off-market deals, ESOPs and '
                              'pledges. None of these is counted as buying or selling.')
    stakes, moves = st.tabs(['Stake changes (5%+)', 'Gifts, off-market and pledges'])
    with stakes:
        sast.render(head=False)
    with moves:
        transfers.render(head=False)
