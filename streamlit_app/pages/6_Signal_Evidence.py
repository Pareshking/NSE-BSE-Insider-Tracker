"""What our own data shows about insider and promoter disclosures, how sure we are, and the forward-test ledger."""
import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import clean_data, ledger_view, style  # noqa: E402

COST_PP = 0.30      # round-trip friction in percentage points: STT, exchange/turnover charges and slippage (assumption)
style.inject_base_css()
style.head("Research findings", "What our own data shows, how sure we are, and the forward-test ledger")
st.error("**Verdict: insufficient evidence of an edge.** Promoter open-market buys beat Nifty 500 in the Jan-Jun 2026 development sample, "
         "but insider SELLS beat it too (+4.4% at 60 sessions), and about 85% of events are micro caps. The excess mostly reflects how "
         "that segment performed in one half-year, not insider information. Nothing here is a validated signal (docs/RESEARCH.md J.3).")
data = json.loads((Path(__file__).resolve().parents[1] / "data" / "research_summary.json").read_text())
rows = []
for r in data["rows"]:
    rows.append({"Cut": r["cut"], "What": r["label"],
                 "N (60s)": r["n60"], "Date clusters": r["clusters60"],
                 "60s excess, gross %": r["ex60"][0], "60s excess, net %": round(r["ex60"][0] - COST_PP, 2),
                 "60s median net %": round(r["ex60"][1] - COST_PP, 2), "60s 95% CI (gross)": f'{r["ci60"][0]:+.1f}..{r["ci60"][1]:+.1f}',
                 "Beat Nifty 500 %": r["hit60"],
                 "N (120s)": r["n120"], "120s excess, net % [PRELIMINARY]": round(r["ex120"][0] - COST_PP, 2),
                 "120s 95% CI (gross)": f'{r["ci120"][0]:+.1f}..{r["ci120"][1]:+.1f}'})
tbl = pd.DataFrame(rows)
st.subheader("Excess return vs Nifty 500 (development sample, 1 Jan to 30 Jun 2026)")
num = lambda label, fmt="%.1f": st.column_config.NumberColumn(label, format=fmt)       # noqa: E731
st.dataframe(tbl, hide_index=True, use_container_width=True, column_config={
    "N (60s)": num("N (60s)", "%d"), "N (120s)": num("N (120s)", "%d"), "Date clusters": num("Date clusters", "%d"),
    "60s excess, gross %": num("60s excess, gross %"), "60s excess, net %": num("60s excess, net %"), "60s median net %": num("60s median net %"),
    "Beat Nifty 500 %": num("Beat Nifty 500 %", "%d"), "120s excess, net % [PRELIMINARY]": num("120s excess, net % [PRELIMINARY]")})
st.caption(f"Source: {data['source']}. Net = mean (or median) excess minus a flat {COST_PP:.2f} percentage points round trip (ESTIMATED assumption "
           "for STT, exchange charges and slippage; real impact in illiquid micro caps is likely higher, so net is an upper bound). The confidence "
           "interval is the gross date-clustered bootstrap interval of the mean. 120-session figures: **PRELIMINARY — SAMPLE MATURING IN 2026** "
           "(January-April disclosures only, heavily overlapping windows). Nifty 500 itself returned +1.9% (60s) and +3.8% (120s) on average.")
st.subheader("How to read this")
st.markdown("""
- **Not an edge (ESTIMATED).** A positive excess with a confidence interval above zero is not proof of insider information when sells show the same and most events are micro caps.
- **Earlier benchmarks** (equal-weighted and size-matched) gave about zero or negative abnormal returns for the same buys (docs/RESEARCH.md sections H and I).
- **Not tested yet:** size- and liquidity-matched excess, buys minus sells, delisted names (survivorship), regime effects (one half-year). Non-market acquisitions are deferred to the Phase 5 backlog.
- **Costs:** only the flat assumption above is applied; no liquidity-dependent impact.
- **Hold-out:** events after 30 Jun 2026 are not scored here; the ledger below follows them as a monitor, not a registered test.
""")
st.subheader("Forward-test ledger")
client = clean_data.gate()
ledger_view.render(client)
