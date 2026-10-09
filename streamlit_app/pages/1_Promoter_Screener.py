"""Promoter accumulation screener: the table first, filters in a popover, filing history under the selected row."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import clean_data, r2_data, style, watchlist  # noqa: E402
from insiders_clean import product_views as pv, trade_table as tt  # noqa: E402

CR = 1e7
num = lambda label, fmt, help=None: st.column_config.NumberColumn(label, format=fmt, help=help)       # noqa: E731
style.inject_base_css()
client = clean_data.gate()
with r2_data.guard("insider trades and price summary"):
    trades, deals = clean_data.clean_table(client, 'insider_trades'), clean_data.clean_table(client, 'deals')
    summary = clean_data.price_summary(client)
asof = pd.to_datetime(trades['broadcast_date']).max()
have_prices = not summary.empty

style.head("Promoter screener", f"Net promoter open-market buying · data to {asof:%d %b %Y}")
st.markdown(style.tag("Contextual accumulation · no proven edge",
                      "Promoter buying showed no standalone edge in our tests. Equity absorbed is an estimate (net value / market cap). See Signal Evidence.", "tag"),
            unsafe_allow_html=True)

with st.container(key="tb_scr"):
    t1, t3, t2, t4 = st.columns([1, 1.7, 2.6, 1.3])
with t1:
    with st.popover("Filters", use_container_width=True):
        net_label = st.selectbox("Min net value", ["25 lakh", "50 lakh", "1 crore", "5 crore"], help="Applies to the selected horizon (365D for Sustained).")
        pct_label = st.selectbox("Min % of equity absorbed", ["Any", "0.1%", "0.25%", "0.5%", "1%", "2%"],
                                 help="Estimate: net value / market cap on the disclosure day.")
        buckets = st.multiselect("Market cap", list(pv.BUCKET_ORDER), default=list(pv.BUCKET_ORDER), disabled=not have_prices,
                                 help="Rank of NSE market cap: Large top 100, Mid 101-250, Small 251-500, Micro the rest.")
        dd_label = st.selectbox("Price context", ["Any", "> 15% below 52W high", "> 30% below 52W high"], disabled=not have_prices)
        active_only = st.checkbox("Active campaign only", help=f"Repeat purchases at most {pv.CAMPAIGN_GAP_DAYS} days apart, last buy within that gap of the latest data.")
        pure = st.checkbox("No promoter selling in window")
        watchlist.editor()
        if not have_prices:
            st.caption("Price summary not written yet: market-cap and price filters are off.")
with t2:
    horizon = st.radio("Horizon", ['90D', '180D', '365D', 'Sustained'], index=1, horizontal=True, label_visibility="collapsed",
                       help="Sustained = net buying in all three windows; value and % bars then apply to the 365-day figures.")
with t3:
    sort_label = st.selectbox("Sort", ["Newest buy", "% absorbed", "Net value"], label_visibility="collapsed",
                              help="Newest first by default: a bigger purchase is not a better signal (large buys did worse against size peers).")
with t4:
    wl_only = watchlist.toggle()

net_min = {"25 lakh": 25 * pv.LAKH, "50 lakh": 50 * pv.LAKH, "1 crore": CR, "5 crore": 5 * CR}[net_label]
pct_min = 0.0 if pct_label == "Any" else float(pct_label.rstrip('%'))
dd_min = 0.0 if dd_label == "Any" else (0.15 if "15%" in dd_label else 0.30)
acc = pv.promoter_absorption(trades, asof, min_value=1, min_pct=0)
camps = pv.active_campaigns(trades, asof)
res = pv.screen(acc, summary if have_prices else None, camps, horizon, net_min, pct_min, buckets or pv.BUCKET_ORDER, active_only, dd_min, pure,
                sort={'Newest buy': 'last_buy', '% absorbed': 'pct', 'Net value': 'net'}[sort_label])
if wl_only:
    res = watchlist.limit(res, watchlist.get(), 'isin', 'symbol').reset_index(drop=True)
if len(res):
    res = res.merge(pv.deal_alignment(deals, camps, asof), on='isin', how='left')
else:
    res = res.assign(deal_net=pd.Series(dtype=float), deal_days=pd.Series(dtype=float), deal_coincides=pd.Series(dtype=bool))

top = res.sort_values('pct', ascending=False).iloc[0] if len(res) else None
style.readings([
    ("Active campaigns", f"{int(res['active'].sum()) if len(res) else 0}", "≤ 90-day gaps"),
    ("Net buying 180D", f"₹ {res['net_180d'].clip(lower=0).sum() / CR:,.1f} Cr" if len(res) else "–", "filtered securities"),
    ("Top absorbed", str(top['symbol'] or top['company'])[:18] if top is not None else "–", f"{top['pct']:.2f}% of equity (est.)" if top is not None else ""),
    ("Matching", f"{len(res):,}", f"{horizon} horizon"),
])
if res.empty:
    st.info("Nothing clears these filters.")
    st.stop()

grid = pd.DataFrame({
    'Symbol': res['symbol'].fillna(res['company']), 'Company': res['company'], 'M-Cap': res['mcap_bucket'].fillna('n/a'),
    'Last buy': res['last_buy'],
    '90D net (₹ Cr)': res['net_90d'] / CR, '180D net (₹ Cr)': res['net_180d'] / CR, '365D net (₹ Cr)': res['net_365d'] / CR,
    '% equity absorbed': res['pct'], 'Active campaign': res['active'].map({True: '● Active', False: '–'}),
    'Deals': res['deal_coincides'].eq(True).map({True: 'Net buying', False: '–'}),
    '52W drawdown %': res['pct_off_high'] * 100,
    'Action': ["/deep-dive?isin=" + i for i in res['isin']]})
page, off = style.paginate(grid, 'screener', 50)
event = st.dataframe(page, hide_index=True, use_container_width=True, on_select="rerun", selection_mode="single-row", key="screener_grid",
                     height=min(640, 38 + 35 * len(page)), column_config={
    'Symbol': st.column_config.TextColumn(width='small'), 'Company': st.column_config.TextColumn(width='medium'),
    'M-Cap': st.column_config.TextColumn(width='small', help="ESTIMATED rank bucket from NSE market cap"),
    'Last buy': st.column_config.DateColumn('Last buy', format='DD MMM YY', width='small'),
    '90D net (₹ Cr)': num('90D net (₹ Cr)', '%.2f'), '180D net (₹ Cr)': num('180D net (₹ Cr)', '%.2f'), '365D net (₹ Cr)': num('365D net (₹ Cr)', '%.2f'),
    '% equity absorbed': num('% absorbed', '%.2f', "ESTIMATED: net value / market cap on the disclosure day, for the selected horizon"),
    'Active campaign': st.column_config.TextColumn('Campaign', width='small', help="Repeat promoter buying with gaps of at most 90 days"),
    'Deals': st.column_config.TextColumn(width='small', help="Bulk/block net buying (market makers excluded) inside the campaign window; deals carry no FII/DII label"),
    '52W drawdown %': num('52W drawdown %', '%.1f'),
    'Action': st.column_config.LinkColumn('Action', display_text='Deep dive', width='small')})
sel = event.selection.rows if event and event.selection else []
if sel:
    row = res.iloc[off + sel[0]]
    c1, c2 = st.columns([4, 1])
    c1.markdown(f"**{row['company']}** · {row['span'] if isinstance(row['span'], str) else 'single filing'}")
    if c2.button("Open deep dive", type="primary", use_container_width=True):
        st.session_state['deep_dive_isin'] = row['isin']
        st.switch_page("pages/2_Company_Deep_Dive.py")
    rows = tt.insider_rows(trades, row['isin']).drop(columns=['Symbol', 'Company'])
    st.dataframe(rows.head(12), hide_index=True, use_container_width=True, column_config={
        'Date': st.column_config.DateColumn('Date', format='DD MMM YY', width='small'),
        'Qty': num('Qty', '%d'), 'Avg Price': num('Avg Price', '%.2f'), 'Value (₹ Cr)': num('Value (₹ Cr)', '%.2f'),
        '% of mcap (est.)': num('% of mcap', '%.3f'), 'Holding Δ %': num('Holding Δ %', '%.1f'),
        'File': st.column_config.LinkColumn('File', display_text='open')})
else:
    st.caption("Select a row to see its filings.")
style.download_csv(grid.drop(columns=['Action']), "promoter_screener.csv", key="screener_csv")
