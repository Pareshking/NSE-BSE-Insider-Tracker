import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import r2_data, style

client = r2_data.get_client()

if not r2_data.r2_configured():
    st.title("Overview")
    st.warning(
        "R2 credentials aren't configured for this app, so there's no data to show yet. "
        "Set `CLOUDFLARE_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, "
        "`R2_BUCKET_NAME` in `.streamlit/secrets.toml` (or as env vars) -- the same "
        "values already used by the GitHub Actions R2-storage workflow."
    )
    st.stop()

dates = r2_data.list_manifest_dates(client)
if not dates:
    st.title("Overview")
    st.info("No manifests found in the bucket yet -- the R2 write workflow hasn't run, or hasn't produced output for any date.")
    st.stop()

# --- header bar: title + exchange toggle + date selector + certification badges ---
h1, h2, h3, h4 = st.columns([2, 1.4, 1.3, 2.3])
with h1:
    st.markdown("### Overview")
with h2:
    exchange_choice = st.radio("Exchange", ["Both", "NSE", "BSE"], horizontal=True, label_visibility="collapsed")
with h3:
    selected_date = st.selectbox("Run date", dates, index=0, label_visibility="collapsed")

manifest = r2_data.load_manifest(client, selected_date)
entries = manifest.get("datasets", manifest if isinstance(manifest, list) else [])
if isinstance(entries, dict):
    entries = list(entries.values())

nse_ok = any(e.get("exchange") == "nse" and e.get("status") == "VERIFIED" for e in entries)
bse_ok = any(e.get("exchange") == "bse" and e.get("status") == "VERIFIED" for e in entries)
nse_all = all(e.get("status") == "VERIFIED" for e in entries if e.get("exchange") == "nse") and nse_ok
bse_all = all(e.get("status") == "VERIFIED" for e in entries if e.get("exchange") == "bse") and bse_ok
with h4:
    st.markdown(
        f'<div style="display:flex;gap:6px;justify-content:flex-end;padding-top:6px;">'
        f'{style.badge("BSE certified" if bse_all else "BSE partial", "green" if bse_all else "amber", "green_bg" if bse_all else "amber_bg")}'
        f'{style.badge("NSE certified" if nse_all else "NSE partial", "green" if nse_all else "amber", "green_bg" if nse_all else "amber_bg")}'
        f"</div>",
        unsafe_allow_html=True,
    )

exchanges = r2_data.EXCHANGES if exchange_choice == "Both" else [exchange_choice.lower()]
data = {(ex, cat): r2_data.load_canonical(client, ex, cat, selected_date) for ex in exchanges for cat in r2_data.CATEGORIES}

# --- KPI strip ---
status_by_key = {(e.get("exchange"), e.get("category")): e for e in entries}
written_count = sum(1 for e in entries if e.get("written"))
total_count = len(entries) or (len(r2_data.CATEGORIES) * len(r2_data.EXCHANGES))

kpi_cols = st.columns(len(r2_data.CATEGORIES) + 1)
for i, category in enumerate(r2_data.CATEGORIES):
    with kpi_cols[i]:
        df = pd.concat([data.get((ex, category), pd.DataFrame()) for ex in exchanges], ignore_index=True) if exchanges else pd.DataFrame()
        badges = []
        for ex in r2_data.EXCHANGES:
            entry = status_by_key.get((ex, category), {})
            written = bool(entry.get("written"))
            badges.append(style.badge(ex.upper(), "green" if written else "amber", "green_bg" if written else "amber_bg"))
        st.markdown(
            style.kpi_card(
                r2_data.CATEGORY_LABELS[category].upper(),
                f"{len(df):,}",
                f'<div style="display:flex;gap:6px;margin-top:9px;">{"".join(badges)}</div>',
            ),
            unsafe_allow_html=True,
        )

with kpi_cols[-1]:
    st.markdown(
        f"""
        <div class="kpi-card" style="background:{style.COLORS['text']};color:#fff;">
        <div class="kpi-label" style="color:#94a3b8;">DATASETS VERIFIED</div>
        <div class="kpi-value" style="display:flex;align-items:baseline;gap:4px;">
            {written_count}<span style="font-size:15px;color:#94a3b8;">/{total_count}</span>
        </div>
        <div style="font-size:11px;color:#cbd5e1;margin-top:9px;">this run · not an average score</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.write("")
left, right = st.columns([2, 1])

with left:
    st.markdown('<div style="font-size:13px;font-weight:700;margin-bottom:10px;">Latest activity — Insider Trading</div>', unsafe_allow_html=True)
    insider_df = pd.concat([data.get((ex, "insider_trading"), pd.DataFrame()) for ex in exchanges], ignore_index=True) if exchanges else pd.DataFrame()
    if insider_df.empty:
        st.caption("No insider-trading rows written for this run date.")
    else:
        recent = insider_df.sort_values("canonical_transaction_date", ascending=False).head(8)
        rows_html = []
        for _, r in recent.iterrows():
            date_ = str(r.get("canonical_transaction_date") or "—")
            company = str(r.get("canonical_company") or "—")
            person = str(r.get("canonical_person") or "—")
            cat = str(r.get("canonical_person_category") or "—")
            ttype = str(r.get("canonical_transaction_type") or "—")
            value = style.fmt_inr(r.get("canonical_value"))
            ex = str(r.get("exchange") or "")
            type_color = "green" if "ACQUI" in ttype.upper() else ("red" if "DISPOS" in ttype.upper() else "text_2")
            rows_html.append(
                f'<tr><td class="mono">{date_}</td>'
                f'<td style="font-weight:500;">{company}</td>'
                f'<td style="color:{style.COLORS["text_2"]};">{person}</td>'
                f'<td>{style.badge(cat, "nse" if ex=="nse" else "bse", "nse_bg" if ex=="nse" else "bse_bg", dot=False)}</td>'
                f'<td style="color:{style.COLORS[type_color]};font-weight:500;">{ttype.title()}</td>'
                f'<td class="mono" style="text-align:right;">{value}</td>'
                f'<td style="text-align:right;">{style.exchange_badge(ex)}</td></tr>'
            )
        st.markdown(
            '<table class="evt-table"><tr><th>DATE</th><th>COMPANY</th><th>PERSON</th><th>CATEGORY</th>'
            f'<th>TYPE</th><th style="text-align:right;">VALUE</th><th style="text-align:right;">EXCH</th></tr>'
            + "".join(rows_html) + "</table>",
            unsafe_allow_html=True,
        )
    st.caption("Full drill-down (native fields, source ID, ISIN cross-match) is on the Evidence & Drill-down page. Net-position rollups are on Promoter Activity.")

with right:
    st.markdown("**Date coverage**")
    if not insider_df.empty and "canonical_transaction_date" in insider_df.columns:
        n_dates = insider_df["canonical_transaction_date"].nunique()
        coverage_pct = min(100, round(100 * n_dates / 90))
        freshness = manifest.get("generated_at", "—")
        st.markdown(
            f'<div class="kv-row"><span style="color:{style.COLORS["text_2"]};">Requested</span><span class="mono">90D</span></div>'
            f'<div class="kv-row"><span style="color:{style.COLORS["text_2"]};">Actual (Insider)</span><span class="mono">{n_dates} dates</span></div>'
            f'<div style="height:6px;background:{style.COLORS["bg_sub"]};border-radius:3px;overflow:hidden;margin:8px 0;"><div style="width:{coverage_pct}%;height:100%;background:{style.COLORS["green"]};"></div></div>'
            f'<div class="kv-row" style="border-bottom:none;"><span style="color:{style.COLORS["text_2"]};">Freshness</span><span class="mono" style="color:{style.COLORS["green"]};">{freshness}</span></div>',
            unsafe_allow_html=True,
        )
    else:
        st.caption("No data to compute coverage from.")

    st.markdown("**System status**")
    blocked = [e for e in entries if e.get("status") not in ("VERIFIED",) and e.get("exchange")]
    if blocked:
        for e in blocked:
            st.markdown(
                f"⚠️ {e.get('exchange', '?').upper()} {r2_data.CATEGORY_LABELS.get(e.get('category'), e.get('category'))}: "
                f"**{e.get('status')}** — {e.get('reason', 'no reason recorded')}"
            )
    else:
        st.success("No blocked or skipped datasets this run.")

    st.markdown("**Validation & evidence**")
    rows_html = "".join(
        f'<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid {style.COLORS["border"]};font-size:12px;">'
        f'<span>{e.get("exchange","?").upper()} {r2_data.CATEGORY_LABELS.get(e.get("category"), e.get("category"))}</span>'
        f'{style.status_badge(e.get("status","MISSING"))}</div>'
        for e in entries
    )
    st.markdown(rows_html or "<em>No manifest entries.</em>", unsafe_allow_html=True)
    st.caption("Full audit on the Data Quality page.")
