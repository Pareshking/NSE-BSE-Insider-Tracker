"""Shared visual tokens and small HTML helpers.

Colors are lifted directly from the published design mockup's CSS custom
properties (institutional research terminal theme, IBM Plex Sans/Mono) so
this app reads as the same product even though Streamlit can't reproduce
every element (slide-in drawer, custom dropdowns) natively.
"""
from __future__ import annotations

import pandas as pd
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
    # st.html(), not st.markdown() -- this is raw CSS with plenty of
    # patterns (bare letter glued to a bracket attribute selector, e.g.
    # `a[aria-current="page"]`) that Streamlit's markdown-then-HTML pipeline
    # misparses as Markdown link syntax, silently truncating the string and
    # leaking the rest as visible page text. st.html() renders raw HTML/CSS
    # with no markdown pass at all, which sidesteps the whole bug class.
    st.html(
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

        /* ---- Streamlit chrome removal: this should read as a standalone
           product, not an obvious Streamlit demo. ---- */
        [id="MainMenu"] {{ visibility: hidden; }}
        footer {{ visibility: hidden; }}
        header[data-testid="stHeader"] {{ background: transparent; height: 0; }}
        [data-testid="stToolbar"] {{ display: none; }}
        [data-testid="stDecoration"] {{ display: none; }}
        [data-testid="stStatusWidget"] {{ display: none; }}
        .stAppDeployButton {{ display: none; }}
        [data-testid="stAppDeployButton"] {{ display: none; }}
        a[href*="streamlit.io"] {{ display: none !important; }}
        [data-testid="stAppViewContainer"] > .main {{ padding-top: 0.5rem; }}
        [data-testid="stMainBlockContainer"] {{ padding-top: 1.2rem; }}

        /* ---- Sidebar: brand block + reskinned native nav ---- */
        [data-testid="stSidebar"] {{ background: {COLORS['bg']}; border-right: 1px solid {COLORS['border']}; }}
        [data-testid="stSidebarNav"] {{ padding-top: 4px; }}
        [data-testid="stSidebarNav"] a {{
            border-radius: 7px; margin: 1px 0; font-size: 13px; font-weight: 500;
            color: {COLORS['text_2']};
        }}
        [data-testid="stSidebarNav"] a[aria-current="page"] {{
            background: {COLORS['blue_bg']}; color: #1d4ed8; font-weight: 600;
        }}
        .brand-block {{ padding: 4px 4px 14px 4px; border-bottom: 1px solid {COLORS['border']}; margin-bottom: 6px; }}
        .brand-title {{ font-size: 15px; font-weight: 700; color: {COLORS['text']}; line-height: 1.3; }}
        .brand-sub {{ font-size: 11px; color: {COLORS['text_3']}; margin-top: 4px; }}
        .sidebar-footer {{ font-size: 11px; color: {COLORS['text_3']}; margin-top: 18px; }}

        /* ---- Segmented control (exchange toggle) built from st.radio.
           Real DOM (verified 2026-09-01): label[data-testid="stRadioOption"]
           > span (visually-hidden input) + div > div > (div[circle], div[stMarkdownContainer]).
           The circle indicator is the first-child div two levels inside the
           label's direct div child -- targeting the wrong depth here once
           hid the whole label (text included), leaving an empty box. ---- */
        div[role="radiogroup"] {{
            background: {COLORS['bg_sub']}; border: 1px solid {COLORS['border']};
            border-radius: 8px; padding: 3px; display: inline-flex; gap: 2px;
        }}
        [data-testid="stRadioOption"] {{
            border-radius: 6px; padding: 3px 12px; margin: 0 !important; font-size: 12px !important;
        }}
        [data-testid="stRadioOption"] > div > div > div:first-child {{ display: none; }}
        [data-testid="stRadioOption"][data-selected="true"] {{ background: {COLORS['blue']}; }}
        [data-testid="stRadioOption"][data-selected="true"] p {{ color: #fff !important; font-weight: 600; }}

        /* ---- Small custom HTML table (Latest Activity) ---- */
        .evt-table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
        .evt-table th {{
            text-align: left; font-size: 10px; font-weight: 600; color: {COLORS['text_3']};
            letter-spacing: .03em; padding: 8px 10px; border-bottom: 1px solid {COLORS['border']};
        }}
        .evt-table td {{ padding: 9px 10px; border-bottom: 1px solid {COLORS['border']}; vertical-align: middle; }}
        .evt-table tr:last-child td {{ border-bottom: none; }}
        </style>
        """
    )


def sidebar_brand():
    st.sidebar.markdown(
        '<div class="brand-block">'
        '<div class="brand-title">NSE·BSE Corporate<br/>Event Tracker</div>'
        '<div class="brand-sub">Insider · Deals · Issues</div>'
        "</div>",
        unsafe_allow_html=True,
    )


def sidebar_footer(text: str):
    st.sidebar.markdown(f'<div class="sidebar-footer">{text}</div>', unsafe_allow_html=True)


def fmt_inr(value) -> str:
    """₹8.40L / ₹1.14Cr style compact currency, matching the mockup."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "—"
    if abs(v) >= 1e7:
        return f"₹{v/1e7:.2f}Cr"
    if abs(v) >= 1e5:
        return f"₹{v/1e5:.2f}L"
    if abs(v) >= 1e3:
        return f"₹{v/1e3:.1f}K"
    return f"₹{v:,.0f}"


def fmt_date(value) -> str:
    """Clean 'DD Mon YYYY' date, no time component -- NSE/BSE source dates
    arrive in inconsistent formats (plain date strings, full ISO timestamps,
    parquet round-trips that pick up a spurious 00:00:00) and Streamlit's
    default rendering shows whatever it gets verbatim. Falls back to the
    original string, never blanks a value it can't parse -- this project
    doesn't hide data it can't explain, just don't show it worse than raw."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return str(value)
    return parsed.strftime("%d %b %Y")


def fmt_date_col(series: "pd.Series") -> "pd.Series":
    """Same formatting as fmt_date, applied to a whole column for st.dataframe."""
    return series.map(fmt_date)


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
