import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import r2_data, style

style.inject_base_css()

st.title("Data Quality")
st.caption("First-class audit surface — never inferred from workflow success.")

client, dates = r2_data.page_gate()

selected_date = st.selectbox("Run date", dates, index=0)
with r2_data.guard(f"the {selected_date} run"):
    manifest = r2_data.load_manifest(client, selected_date)
    data = r2_data.load_all_canonical(client, selected_date)
entries = manifest.get("datasets", manifest if isinstance(manifest, list) else [])
if isinstance(entries, dict):
    entries = list(entries.values())

written = sum(1 for e in entries if e.get("written"))
total = len(entries) or (len(r2_data.CATEGORIES) * len(r2_data.EXCHANGES))
skipped = total - written

# The writer already counts this per dataset (write_dataset()'s
# 'cross_exchange_matches_flagged') -- use its number directly rather than
# re-deriving it, since it's the authoritative count from the same run.
match_count = sum(e.get("cross_exchange_matches_flagged", 0) or 0 for e in entries)

insider = pd.concat(
    [data.get((ex, "insider_trading"), pd.DataFrame()) for ex in r2_data.EXCHANGES],
    ignore_index=True,
)
isin_rate = None
if not insider.empty and "canonical_isin" in insider.columns:
    isin_rate = 100 * insider["canonical_isin"].notna().mean()

cols = st.columns(4)
with cols[0]:
    st.markdown(style.kpi_card("DATASETS WRITTEN TO R2", f"{written} / {total}"), unsafe_allow_html=True)
with cols[1]:
    st.markdown(
        style.kpi_card("SKIPPED (NOT SILENT)", f'<span style="color:{style.COLORS["amber"]};">{skipped}</span>'),
        unsafe_allow_html=True,
    )
with cols[2]:
    st.markdown(style.kpi_card("CROSS-EXCHANGE MATCHES FLAGGED", str(match_count)), unsafe_allow_html=True)
with cols[3]:
    val = f'<span style="color:{style.COLORS["green"]};">{isin_rate:.1f}%</span>' if isin_rate is not None else "—"
    st.markdown(style.kpi_card("ISIN RESOLUTION RATE (INSIDER)", val), unsafe_allow_html=True)

st.write("")
st.subheader("Certification matrix — this run")

if entries:
    rows_html = [
        '<div style="display:grid;grid-template-columns:.7fr 1.3fr 1.4fr .8fr .9fr 1.1fr;gap:10px;'
        f'padding:8px 4px;font-size:10px;font-weight:600;color:{style.COLORS["text_3"]};'
        f'border-bottom:1px solid {style.COLORS["border"]};">'
        "<div>EXCHANGE</div><div>CATEGORY</div><div>REASON / METHOD</div>"
        "<div style='text-align:right;'>RECORDS</div><div>STATUS</div><div>WRITTEN TO R2</div></div>"
    ]
    for e in sorted(entries, key=lambda x: (x.get("exchange", ""), x.get("category", ""))):
        rows_html.append(
            '<div style="display:grid;grid-template-columns:.7fr 1.3fr 1.4fr .8fr .9fr 1.1fr;gap:10px;'
            f'padding:10px 4px;font-size:12px;border-bottom:1px solid {style.COLORS["border"]};align-items:center;">'
            f'<div>{style.exchange_badge(e.get("exchange",""))}</div>'
            f'<div>{r2_data.CATEGORY_LABELS.get(e.get("category"), e.get("category"))}</div>'
            f'<div style="color:{style.COLORS["text_2"]};font-size:11px;">{e.get("reason","") or "—"}</div>'
            f'<div class="mono" style="text-align:right;">{e.get("row_count", 0):,}</div>'
            f'<div>{style.status_badge(e.get("status","MISSING"))}</div>'
            f'<div>{"✓" if e.get("written") else "skipped"}</div></div>'
        )
    st.markdown("".join(rows_html), unsafe_allow_html=True)
else:
    st.caption("Manifest for this date carries no dataset entries.")

st.caption(
    'Every row reflects the validator status recorded at write time — a dataset marked '
    '"skipped" is never silently written as an empty "successful" result.'
)

# The one place rows are deliberately removed before writing, so it is
# disclosed here rather than left to be inferred from a row count that
# doesn't match the validator's.
round_trips = sum(e.get("intraday_round_trip_rows_dropped", 0) or 0 for e in entries)
if round_trips:
    st.caption(
        f"↳ {round_trips:,} intraday round-trip row(s) were dropped before writing this run — "
        "one client buying and selling the same quantity of the same security on the same day, "
        "which leaves no one's holding changed. Both legs are removed at ingestion "
        "(`scripts/r2_writer.py`), so nothing downstream counts them. The validator certified "
        f"{round_trips:,} rows more than the counts above; this is that difference."
    )

st.write("")
left, right = st.columns(2)
with left:
    st.markdown("**Known limitations (shown, not hidden)**")
    st.markdown(
        "- Cross-exchange same-event matching is **flag-only** — never merges NSE and BSE rows into one combined truth\n"
        "- NSE endpoints Akamai-rate-limit under rapid re-testing — a `RATE-LIMITED`/`BLOCKED` status here reflects that, not a code failure\n"
        "- ISIN resolution depends on the security-master snapshot's coverage — a genuinely absent ISIN is reported as such, not guessed\n"
        "- Confluence Screener classifications (Insider Alpha, Certification, etc.) are a **same-90-day-window heuristic**, not a statistical test — "
        "they flag *what* overlapped, not a probability the overlap is meaningful, and carry no price history to confirm it\n"
        "- Confluence Screener's Float Absorption Ratio needs market cap for a name — where it's missing, that company sorts by raw value instead, "
        "never silently dropped\n"
        "- Source dates arrive in three conventions (NSE ISO `2026-08-28`, NSE IST-midnight-as-UTC `…T18:30:00Z`, BSE `31/08/2026`); "
        "`lib/fields.parse_dates` picks per value, and anything it can't place is shown as filed rather than guessed at\n"
        "- A canonical field an exchange didn't publish narrows what a page can compute, and the page says so — it is never backfilled with a "
        "placeholder that would read as data\n"
        "- **Intraday round trips are dropped at ingestion**, not merely hidden: one client buying and selling the same quantity of the same "
        "security on the same day ends flat, so both legs are removed before anything is written and no calculation anywhere sees them. "
        "The count is reported above. This is the only case where rows are discarded rather than recorded — the upstream capture in "
        "`artifacts/` still holds them if the rule ever needs re-checking"
    )
    st.markdown("**Scope of this app**")
    st.markdown(
        "- Republishes public NSE/BSE disclosures for research. **Not investment advice**, not a recommendation, and not affiliated with "
        "either exchange or SEBI\n"
        "- Every figure is as filed by the issuer. Issuers revise and withdraw filings, so verify against the exchange's own filing before "
        "acting on anything here\n"
        "- No price history anywhere in this project, by design — nothing here says whether any of this activity paid off"
    )
with right:
    st.markdown("**Reference data**")
    sm_path = Path(__file__).resolve().parents[2] / "reference_data"
    sm_files = sorted(sm_path.glob("security_master_*.csv")) if sm_path.exists() else []
    if sm_files:
        sm_df = pd.read_csv(sm_files[-1], dtype=str, keep_default_na=False)
        dup_isin = sm_df["isin"].duplicated().sum() if "isin" in sm_df.columns else "—"
        st.markdown(
            f'<div class="kv-row"><span>Security master snapshot</span><span class="mono">{sm_files[-1].stem.replace("security_master_", "")} · {len(sm_df):,} securities</span></div>'
            f'<div class="kv-row"><span>Duplicate ISINs</span><span class="mono" style="color:{style.COLORS["green"]};">{dup_isin}</span></div>',
            unsafe_allow_html=True,
        )
    else:
        st.caption("No security_master_*.csv found in reference_data/.")
