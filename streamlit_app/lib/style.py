"""Shared visual tokens and small HTML helpers.

Colors are lifted directly from the published design mockup's CSS custom
properties (institutional research terminal theme, IBM Plex Sans/Mono) so
this app reads as the same product even though Streamlit can't reproduce
every element (slide-in drawer, custom dropdowns) natively.
"""
from __future__ import annotations

import streamlit as st

COLORS = {
    "bg": "#ffffff",
    "bg_sub": "#f8fafc",
    "border": "#e2e8f0",
    "text": "#0f172a",
    "text_2": "#64748b",
    "text_3": "#94a3b8",
    "blue": "#2563eb",
    "blue_bg": "#eff6ff",
    "green": "#059669",
    "green_bg": "#ecfdf5",
    "amber": "#b45309",
    "amber_bg": "#fffbeb",
    "red": "#dc2626",
    "red_bg": "#fef2f2",
    "nse": "#6d28d9",
    "nse_bg": "#f5f3ff",
    "bse": "#0e7490",
    "bse_bg": "#ecfeff",
}

STATUS_COLORS = {
    "VERIFIED": ("green", "green_bg"),
    "RATE-LIMITED": ("amber", "amber_bg"),
    "BLOCKED": ("amber", "amber_bg"),
    "MISSING": ("text_2", "bg_sub"),
    "EMPTY": ("text_2", "bg_sub"),
}

EXCHANGE_COLORS = {"nse": ("nse", "nse_bg"), "bse": ("bse", "bse_bg")}


def inject_base_css():
    st.markdown(
        f"""
        <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap">
        <style>
        html, body, [class*="css"] {{ font-family: 'IBM Plex Sans', sans-serif; }}
        .mono {{ font-family: 'IBM Plex Mono', ui-monospace, monospace; font-variant-numeric: tabular-nums; }}
        .badge {{
            display: inline-flex; align-items: center; gap: 5px;
            padding: 3px 9px; border-radius: 5px; font-size: 11px; font-weight: 600;
            white-space: nowrap;
        }}
        .badge-dot {{ width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }}
        .kpi-card {{
            background: {COLORS['bg']}; border: 1px solid {COLORS['border']};
            border-radius: 10px; padding: 16px;
        }}
        .kpi-label {{ font-size: 10.5px; font-weight: 600; color: {COLORS['text_3']}; letter-spacing: .04em; }}
        .kpi-value {{ font-family: 'IBM Plex Mono', monospace; font-size: 26px; font-weight: 600; margin-top: 8px; }}
        .kv-row {{ display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid {COLORS['border']}; font-size: 12.5px; }}
        .sec-title {{ font-size: 11px; font-weight: 700; color: {COLORS['text_3']}; letter-spacing: .05em; margin: 18px 0 4px 0; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def badge(text: str, fg_key: str, bg_key: str, dot: bool = True) -> str:
    dot_html = f'<span class="badge-dot" style="background:{COLORS[fg_key]};"></span>' if dot else ""
    return (
        f'<span class="badge" style="background:{COLORS[bg_key]};color:{COLORS[fg_key]};">'
        f"{dot_html}{text}</span>"
    )


def status_badge(status: str) -> str:
    fg, bg = STATUS_COLORS.get(status, ("text_2", "bg_sub"))
    return badge(status, fg, bg)


def exchange_badge(exchange: str) -> str:
    fg, bg = EXCHANGE_COLORS.get(exchange, ("text_2", "bg_sub"))
    return badge(exchange.upper(), fg, bg, dot=False)


def kpi_card(label: str, value: str, sub_html: str = "") -> str:
    return (
        f'<div class="kpi-card"><div class="kpi-label">{label}</div>'
        f'<div class="kpi-value">{value}</div>{sub_html}</div>'
    )
