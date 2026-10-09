"""Forward-test ledger: promoter accumulation signals first disclosed after 30 Jun 2026, followed as they mature."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import clean_data, r2_data, style  # noqa: E402
from insiders_clean import ledger as lg  # noqa: E402

style.inject_base_css()
st.title("Forward ledger")
st.info("A monitor, not a test: signals are fixed when disclosed (rule `promoter_accum_v1`: promoter / promoter-group "
        "open-market buy, day value at least Rs 25 lakh, disclosed after 30 Jun 2026) and never edited. Returns are before "
        "costs and shown as absolute and excess vs Nifty 500. Showing these outcomes means the hold-out is no longer unseen "
        "for these events (docs/DECISIONS.md).")
client = clean_data.gate()
with r2_data.guard("the ledger"):
    led = clean_data.ledger(client)
    m = clean_data.ledger_marks(client)
if led.empty:
    st.warning("The ledger has not been written yet. Run the 'Forward ledger update' workflow to append the current signals.")
    st.stop()
if m.empty or len(m) < len(led):
    st.warning("Ledger marks are missing or older than the ledger (run the 'Precompute slim assets' workflow). Showing entry facts only.")
    m = led.assign(**{c: float('nan') for c in ['current_price', 'return_to_date', 'excess_to_date_vs_nifty500', 'sessions_since_entry']
                      + [f'{k}_{h}' for h in lg.HORIZONS for k in ('ret', 'excess')]})

st.metric("Signals in the ledger", len(m))
cols = ['company', 'isin', 'disclosure_date', 'entry_date', 'entry_basis', 'entry_price', 'current_price', 'return_to_date',
        'excess_to_date_vs_nifty500', 'sessions_since_entry'] + [c for h in lg.HORIZONS for c in (f'ret_{h}', f'excess_{h}')]
pct = {c: st.column_config.NumberColumn(c, format='%.1f%%') for c in cols if c.startswith(('ret_', 'excess_', 'return_', 'excess_to'))}
view = m[cols].copy()
for c in pct:
    view[c] = view[c] * 100
st.dataframe(view.sort_values('disclosure_date', ascending=False), hide_index=True, use_container_width=True, column_config=pct)
st.subheader("Matured so far")
rows = []
for h in lg.HORIZONS:
    a, x = m[f'ret_{h}'].dropna(), m[f'excess_{h}'].dropna()
    rows.append({'horizon (sessions)': h, 'matured': len(a), 'mean return %': round(100 * a.mean(), 1) if len(a) else None,
                 'median return %': round(100 * a.median(), 1) if len(a) else None,
                 'mean excess vs Nifty 500 %': round(100 * x.mean(), 1) if len(x) else None,
                 'beat Nifty 500 %': round(100 * (x > 0).mean(), 0) if len(x) else None,
                 'note': 'PRELIMINARY — SAMPLE MATURING' if len(a) < 30 else ''})
st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
st.caption("250-session outcomes cannot mature before mid-2027. Excess return is not evidence of insider information "
           "(micro-cap segment effect; docs/RESEARCH.md J.3).")
