"""The company timeline: every event newest first, grouped by month.

Each event is a dict: date, kind (buy | sell | deal_buy | deal_sell | sast |
action | meeting | other), title (trusted HTML), amount (text), meta (a list
of trusted HTML snippets shown as one muted line) and an optional link.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from ui.kit import esc

NODES = {'buy': '▲', 'sell': '▼', 'deal_buy': '◆', 'deal_sell': '◆', 'sast': '◉', 'action': '●',
         'meeting': '⚑', 'other': '○'}
LABELS = {'buy': 'Open-market buy', 'sell': 'Open-market sale', 'deal_buy': 'Bulk/block buy',
          'deal_sell': 'Bulk/block sale', 'sast': 'Stake change (SAST)', 'action': 'Corporate action',
          'meeting': 'Board meeting', 'other': 'Other filing'}


def timeline(events: list[dict], limit: int = 80) -> None:
    events = sorted((e for e in events if pd.notna(e.get('date'))), key=lambda e: e['date'], reverse=True)[:limit]
    if not events:
        st.html('<div class="empty">No filings for this company in the data.</div>')
        return
    out, month = [], None
    for e in events:
        d = pd.Timestamp(e['date'])
        m = d.strftime('%B %Y')
        if m != month:
            month = m
            out.append(f'<div class="tlx-m">{esc(m)}</div>')
        k = e.get('kind', 'other')
        meta = ' · '.join(x for x in e.get('meta', []) if x)
        link = f' <a class="tlx-src" href="{esc(e["link"], quote=True)}" target="_blank">Filing ↗</a>' if e.get('link') else ''
        out.append(
            f'<div class="tlx-i {k}"><div class="tlx-d"><b>{d:%d}</b><span>{d:%a}</span></div>'
            f'<div class="tlx-n" title="{esc(LABELS.get(k, ""), quote=True)}">{NODES.get(k, "○")}</div>'
            f'<div class="tlx-c"><div class="tlx-t">{e["title"]}'
            + (f'<span class="tlx-amt">{esc(e["amount"])}</span>' if e.get('amount') else '') + '</div>'
            + (f'<div class="tlx-x">{meta}{link}</div>' if meta or link else '') + '</div></div>')
    st.html('<div class="tlx">' + ''.join(out) + '</div>')
