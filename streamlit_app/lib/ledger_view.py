"""Forward-ledger tables shared by the Forward Ledger and Signal Evidence pages (reads the precomputed marks only)."""
import pandas as pd
import streamlit as st

from lib import clean_data, r2_data
from insiders_clean import ledger as lg


def render(client) -> None:
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

    view_name = st.radio("Series", ["Single material transactions (promoter_accum_v1)", "Multi-quarter campaigns (promoter_campaign_v2)"], horizontal=True)
    is_v2 = "v2" in view_name
    sub = m[m['rule'] == (lg.RULE_V2 if is_v2 else lg.RULE)]
    if is_v2:
        st.caption(f"Campaign rule: promoter open-market buy days after 30 Jun 2026, at most {lg.CAMPAIGN_GAP_DAYS} days apart, count as one campaign. "
                   f"The signal is fixed on the first buy day (from the second on) where cumulative buying net of promoter open-market sales since "
                   f"the campaign started reaches Rs {lg.MIN_VALUE / 1e5:.0f} lakh. Later buys extend the campaign but never edit or re-enter the row. "
                   "Value is the net at that disclosure.")
    else:
        st.caption("Rule: one promoter / promoter-group open-market buy day with value of at least Rs 25 lakh, disclosed after 30 Jun 2026.")
    if sub.empty:
        st.info("No signals in this series yet. The series is filled by the 'Forward ledger update' workflow.")
        st.stop()
    st.metric("Signals in this series", len(sub))
    m = sub
    cols = ['company', 'isin', 'disclosure_date'] + (['campaign_start', 'campaign_buys'] if is_v2 else []) + [
            'value', 'entry_date', 'entry_basis', 'entry_price', 'current_price', 'return_to_date',
            'excess_to_date_vs_nifty500', 'sessions_since_entry'] + [c for h in lg.HORIZONS for c in (f'ret_{h}', f'excess_{h}')]
    pct = {c: st.column_config.NumberColumn(c, format='%.1f%%') for c in cols if c.startswith(('ret_', 'excess_', 'return_', 'excess_to'))}
    view = m[cols].copy()
    view['value'] = view['value'] / 1e7
    for c in pct:
        view[c] = view[c] * 100
    st.dataframe(view.sort_values('disclosure_date', ascending=False), hide_index=True, use_container_width=True,
                 column_config={**pct, 'value': st.column_config.NumberColumn('value (₹ Cr)', format='%.2f'),
                                'entry_price': st.column_config.NumberColumn('entry_price', format='%.2f'),
                                'current_price': st.column_config.NumberColumn('current_price', format='%.2f')})
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
