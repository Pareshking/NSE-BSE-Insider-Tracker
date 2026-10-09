"""Shared visual tokens and small HTML helpers.

Colors are lifted directly from the published design mockup's CSS custom
properties (institutional research terminal theme, IBM Plex Sans/Mono) so
this app reads as the same product even though Streamlit can't reproduce
every element (slide-in drawer, custom dropdowns) natively.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from . import fields

COLORS = {
    "bg": "#FFFFFF",
    "bg_sub": "#F4F5F8",
    "border": "#E3E6EB",
    "text": "#0E1726",
    "text_2": "#3C4657",
    "text_3": "#5E6878",
    "blue": "#4F46E5",
    "blue_bg": "#EEF0FF",
    "green": "#067647",
    "green_bg": "#E8F5EE",
    "amber": "#B54708",
    "amber_bg": "#FEF6EA",
    "red": "#B42318",
    "red_bg": "#FDEDEB",
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
    # st.markdown(unsafe_allow_html=True), with `<style>` starting in column
    # 0 -- BOTH parts matter, and getting either wrong silently drops this
    # entire stylesheet:
    #
    #   * st.html() sanitizes what it is given and strips <style>/<link>
    #     outright. Verified 2026-09-02 against the real DOM: it rendered
    #     `<div data-testid="stHtml"></div>` -- empty -- so none of the rules
    #     below applied and the app ran with no styling at all (no card
    #     borders, no IBM Plex, and the Streamlit chrome this hides still
    #     showing). It was moved here to dodge the markdown bug below; it
    #     dodged it by discarding the CSS.
    #
    #   * The markdown bug was real, but it was an indentation bug. CommonMark
    #     passes a `<style>` block through verbatim, with NO inline parsing --
    #     so `a[aria-current="page"]` is safe -- but only when the tag opens
    #     with at most 3 spaces of indent. This string used to be indented 8,
    #     which makes it an indented CODE block instead, and that is what
    #     mangled it. Keep the CSS flush left; do not re-indent to match the
    #     surrounding function.
    #
    # The font is @import-ed rather than <link>-ed so the whole thing is one
    # verbatim block.
    st.markdown(
        f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Geist:wght@400..700&family=Geist+Mono:wght@400..700&display=swap');
html, body, [class*="css"] {{ font-family: 'Geist', -apple-system, 'Segoe UI', Roboto, sans-serif; }}
.mono {{ font-family: 'Geist Mono', ui-monospace, monospace; font-variant-numeric: tabular-nums; }}
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
.kpi-value {{ font-family: 'Geist Mono', monospace; font-size: 26px; font-weight: 600; margin-top: 8px; }}
.kv-row {{ display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid {COLORS['border']}; font-size: 12.5px; }}
.sec-title {{ font-size: 11px; font-weight: 700; color: {COLORS['text_3']}; letter-spacing: .05em; margin: 18px 0 4px 0; }}

/* ---- Streamlit chrome removal: this should read as a standalone
   product, not an obvious Streamlit demo.

   NEVER hide the header or the toolbar wholesale. Measured from the real
   DOM (2026-09-02, Chromium, this Streamlit build):

     - at >=1280px the page nav is [data-testid="stTopNavLink"];
     - at 412px there is NO stTopNavLink at all. The nav collapses into
       the sidebar (stSidebarNav), and the ONLY way to reach it is the
       [data-testid="stExpandSidebarButton"] chevron, which lives INSIDE
       header > stToolbar.

   So hiding stToolbar would cost a phone user every page but the one they
   landed on. Hide individual chrome children only, and leave the expand
   chevron alone. (An older comment here claimed the top nav renders inside
   the toolbar. It does not -- and that claim was recorded while this
   stylesheet was not reaching the page at all, so nothing it described had
   ever actually been observed applying.)

   Community Cloud's own owner strip (Share / star / edit / GitHub, in
   stToolbarActions) is deliberately NOT touched here. ---- */
/* The ⋮ main menu is deliberately left visible. This rule predates the
   st.html() bug and so had never actually applied; now that the stylesheet
   reaches the page it would take effect, and the owner asked for the
   toolbar to stay as it is. Re-enable by uncommenting.
[id="MainMenu"] {{ display: none; }}
*/
footer {{ visibility: hidden; }}
header[data-testid="stHeader"] {{ background: {COLORS['bg']}; border-bottom: 1px solid {COLORS['border']}; }}
[data-testid="stDecoration"] {{ display: none; }}
[data-testid="stStatusWidget"] {{ display: none; }}
.stAppDeployButton {{ display: none; }}
[data-testid="stAppDeployButton"] {{ display: none; }}
a[href*="streamlit.io"] {{ display: none !important; }}
/* The header overlays the top of the main container, so this padding is
   what keeps the brand strip out from under it -- it is not just cosmetic
   tightening. 1.2rem (the value here while the stylesheet was being
   silently dropped, so nobody saw it apply) clips "Insiders" and the
   session timestamp behind the 60px header. */
[data-testid="stMainBlockContainer"] {{ padding-top: 4.5rem; padding-left: 1.25rem; padding-right: 1.25rem; max-width: 100%; }}
@media (max-width: 640px) {{ [data-testid="stMainBlockContainer"] {{ padding-left: .5rem; padding-right: .5rem; }} }}
/* Dense, financial-grade type: tighter headings and vertical rhythm, tabular numerals in tables. */
h1 {{ font-size: 1.55rem !important; letter-spacing: -0.02em; margin-bottom: .25rem; }}
h2, h3 {{ letter-spacing: -0.02em; }}
[data-testid="stVerticalBlock"] {{ gap: .65rem; }}
[data-testid="stDataFrame"] {{ font-variant-numeric: tabular-nums; }}
.pill {{ display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: 11px; font-weight: 600; white-space: nowrap; }}
.pill-buy {{ background: {COLORS['green_bg']}; color: {COLORS['green']}; }}
.pill-sell {{ background: {COLORS['red_bg']}; color: {COLORS['red']}; }}
.pill-tag {{ background: {COLORS['bg_sub']}; color: {COLORS['text_2']}; border: 1px solid {COLORS['border']}; }}
.pill-prom {{ background: {COLORS['blue_bg']}; color: #4338CA; }}
.evt-table td.num, .evt-table th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
.evt-table.dense td {{ padding: 5px 8px; }}
.evt-table.dense th {{ padding: 6px 8px; }}

/* ---- Top nav bar (position="top"), not a sidebar -- this app is
   used on mobile, where a sidebar drawer costs a tap and half the
   screen width every time. Real testids (confirmed 2026-09-02):
   stTopNavLinkContainer wraps each stTopNavLink <a>. ---- */
[data-testid="stTopNavLink"] {{
    border-radius: 7px; padding: 6px 14px; font-size: 13px; font-weight: 500;
    color: {COLORS['text_2']};
}}
[data-testid="stTopNavLink"][aria-current="page"] {{
    background: {COLORS['blue_bg']}; color: #4338CA; font-weight: 600;
}}
.top-brand {{
    display: flex; align-items: baseline; justify-content: space-between;
    flex-wrap: wrap; gap: 6px; padding: 10px 2px 8px 2px;
    border-bottom: 1px solid {COLORS['border']}; margin-bottom: 4px;
}}
.top-brand-title {{ font-size: 15px; font-weight: 700; color: {COLORS['text']}; }}
.top-brand-session {{ font-size: 11px; color: {COLORS['text_3']}; }}

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
/* These tables carry 5-6 columns and are wider than a phone viewport, so
   they need somewhere to scroll. Styling the table itself does not work:
   with width:100% it stretches its parent instead of overflowing inside it,
   which pushed the rightmost column (the value) off-screen with no way to
   reach it. The wrapper is what bounds the width; min-width:0 stops it
   inheriting the table's content width through the flex/grid parents
   Streamlit puts around markdown blocks. */
.table-scroll {{ overflow-x: auto; max-width: 100%; min-width: 0; }}
.table-scroll .evt-table {{ min-width: max-content; }}
</style>
""",
        unsafe_allow_html=True,
    )


def top_brand_bar(session_text: str):
    """Brand strip above the top nav bar -- replaces the old sidebar's brand
    block + footer now that navigation runs across the top, not down the
    side (this app is used on mobile, where a sidebar drawer costs a tap
    and half the screen width every time)."""
    dots = "".join(
        f'<span style="display:inline-block;width:9px;height:9px;border-radius:50%;background:{COLORS[c]};margin-right:4px;"></span>'
        for c in ("red", "amber", "green")
    )
    st.markdown(
        '<div class="top-brand">'
        f'<div>{dots}<span class="top-brand-title" style="margin-left:4px;">Insiders</span></div>'
        f'<div class="top-brand-session">{session_text}</div>'
        "</div>",
        unsafe_allow_html=True,
    )


def download_csv(df: "pd.DataFrame", filename: str, *, label: str = "Download CSV", key: str | None = None):
    """Export exactly the rows currently on screen, with the canonical_*
    values as stored -- raw numbers and source date strings, not this app's
    ₹8.40L / '01 Sep 2026' display formatting. Someone re-checking a figure
    against the exchange's own filing needs what was published, not what we
    rendered."""
    if df is None or df.empty:
        return
    st.download_button(
        label=f"{label} ({len(df):,} rows)",
        data=df.to_csv(index=False).encode("utf-8"),
        file_name=filename,
        mime="text/csv",
        key=key,
    )


DISCLAIMER = (
    "Public NSE/BSE disclosures, republished for research. Not investment advice, "
    "not a recommendation, and no relationship with either exchange or SEBI. Figures are "
    "as filed by the issuer and can be revised or withdrawn at source -- verify against the "
    "exchange's own filing before acting on anything here."
)


def disclaimer_footer():
    """Rendered on every page. A tool that ranks insider and promoter
    activity invites being read as a buy/sell signal; saying plainly that it
    isn't belongs on the screen, not only in the README."""
    st.markdown(
        f'<div style="margin-top:28px;padding-top:10px;border-top:1px solid {COLORS["border"]};'
        f'font-size:10.5px;color:{COLORS["text_3"]};line-height:1.5;">{DISCLAIMER}</div>',
        unsafe_allow_html=True,
    )


def fmt_inr(value) -> str:
    """₹8.40L / ₹1.14Cr style compact currency, matching the mockup."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "—"
    # NaN survives float() and used to render as the literal "₹nan". An
    # amount the source didn't publish is unknown, not zero, so it gets the
    # same em dash as any other absent value.
    if pd.isna(v):
        return "—"
    if abs(v) >= 1e7:
        return f"₹{v/1e7:.2f}Cr"
    if abs(v) >= 1e5:
        return f"₹{v/1e5:.2f}L"
    if abs(v) >= 1e3:
        return f"₹{v/1e3:.1f}K"
    return f"₹{v:,.0f}"


def fmt_qty(value) -> str:
    """Share counts, formatted the same way everywhere and safe on any dtype.

    NSE and BSE mix numeric and stringy representations of the same quantity
    ('51000.0' as often as 51000.0) -- scripts/r2_writer.py's _num() coerces
    what it recognises, but anything it doesn't reaches the frontend as text.
    An f-string number format on that text raises "Unknown format code 'f'
    for object of type 'str'" and takes the whole page down, which is what
    Evidence & Drill-down and Promoter Activity were doing.
    """
    number = fields.as_float(value, default=float("nan"))
    if pd.isna(number):
        return "—"
    return f"{number:,.0f}"


def fmt_date(value) -> str:
    """Clean 'DD Mon YYYY' date, no time component -- NSE/BSE source dates
    arrive in inconsistent formats (plain date strings, full ISO timestamps,
    parquet round-trips that pick up a spurious 00:00:00) and Streamlit's
    default rendering shows whatever it gets verbatim. Falls back to the
    original string, never blanks a value it can't parse -- this project
    doesn't hide data it can't explain, just don't show it worse than raw.

    Parsing lives in lib.fields.parse_dates, which picks the convention per
    value. This used to pass a blanket dayfirst=True on the grounds that it
    was "a harmless no-op on unambiguous ISO strings" -- it isn't: pandas
    reads ISO '2026-09-01' as 9 January 2026 under dayfirst, so every NSE
    date whose day-of-month was <= 12 rendered with day and month swapped.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    parsed = fields.parse_date(value)
    if pd.isna(parsed):
        return str(value)
    return parsed.strftime("%d %b %Y")


def fmt_date_col(series: "pd.Series") -> "pd.Series":
    """Same formatting as fmt_date, applied to a whole column for st.dataframe."""
    parsed = fields.parse_dates(series)
    return parsed.dt.strftime("%d %b %Y").fillna(
        series.map(lambda v: "—" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v))
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


def exchange_badge(exchange) -> str:
    # str() first: this is called with whatever the exchange column held, and
    # a non-string there ("'int' object has no attribute 'upper'") took down
    # Promoter Activity and Bulk & Block Concentration.
    name = str(exchange or "").strip()
    fg, bg = EXCHANGE_COLORS.get(name.lower(), ("text_2", "bg_sub"))
    return badge(name.upper() or "—", fg, bg, dot=False)


def kpi_card(label: str, value: str, sub_html: str = "") -> str:
    return (
        f'<div class="kpi-card"><div class="kpi-label">{label}</div>'
        f'<div class="kpi-value">{value}</div>{sub_html}</div>'
    )


def pill(text: str, kind: str = "tag") -> str:
    """Soft pill: kind is buy (green), sell (muted rose), prom (indigo, promoter) or tag (neutral)."""
    return f'<span class="pill pill-{kind}">{text}</span>'


def side_pill(side, market: bool | None = None) -> str:
    s = str(side).upper()
    if s == "BUY":
        return pill("Market Buy" if market else "Buy", "buy")
    if s == "SELL":
        return pill("Market Sell" if market else "Sell", "sell")
    return pill(s if s not in ("NONE", "NAN", "") else "-", "tag")


def category_pill(label: str) -> str:
    return pill(label, "prom" if "romoter" in str(label) else "tag")


def fmt_cr(value) -> str:
    """Rupees as crore with 2 decimals (Screener.in trade-hub style); '-' when missing."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "-"
    return "-" if v != v else f"{v / 1e7:,.2f}"


def paginate(df: "pd.DataFrame", key: str, page_size: int = 50) -> tuple["pd.DataFrame", int]:
    """Slice `df` for the current page and draw a compact pager. Returns (page rows, row offset of the page)."""
    n = len(df)
    pages = max(1, -(-n // page_size))
    if pages == 1:
        return df, 0
    c1, c2 = st.columns([1, 5])
    page = c1.number_input("Page", min_value=1, max_value=pages, value=1, step=1, key=f"{key}-page", label_visibility="collapsed")
    c2.caption(f"Page {page} of {pages} · rows {(page - 1) * page_size + 1:,}-{min(page * page_size, n):,} of {n:,}")
    start = (int(page) - 1) * page_size
    return df.iloc[start:start + page_size], start
