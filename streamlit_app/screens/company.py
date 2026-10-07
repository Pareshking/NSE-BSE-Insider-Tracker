"""Company page (/company?symbol=XYZ): everything about one company -- insider
trades, deals, SAST stakes, corporate actions, shareholding and pledge."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from ui import kit
from ui.kit import esc

from insiders_clean import signals
from screens.ctx import load, need_data


def _pick_symbol(ctx) -> str | None:
    sym = st.query_params.get('symbol')
    if sym:
        return sym.upper()
    names = ctx.eligible.dropna(subset=['nse_symbol']).drop_duplicates('nse_symbol')
    options = sorted(f'{c} · {s}' for c, s in zip(names['company'], names['nse_symbol']))
    choice = st.selectbox('Company', options, index=None, placeholder='Search a company', key='co_pick')
    if choice:
        st.query_params['symbol'] = choice.rsplit(' · ', 1)[1]
        st.rerun()
    return None


def render():
    ctx = load()
    if not need_data(ctx):
        return
    sym = _pick_symbol(ctx)
    if not sym:
        kit.head('Company', 'Pick a company, or open one from any table on the site.')
        return
    t = ctx.trades[ctx.trades['nse_symbol'].astype(str).str.upper() == sym].copy()
    sec = ctx.securities[ctx.securities['nse_symbol'].astype(str).str.upper() == sym] if not ctx.securities.empty else pd.DataFrame()
    rec = sec.iloc[0] if len(sec) else (t.iloc[0] if len(t) else None)
    name = (rec.get('display_name') if rec is not None and 'display_name' in rec else None) or \
           (t['company'].iloc[0] if len(t) else sym)
    kit.head(str(name), '')
    if rec is not None:
        parts = [f'<span class="mono">{esc(sym)}</span>']
        for k, label in (('bse_code', 'BSE'), ('isin', '')):
            if k in rec and pd.notna(rec.get(k)):
                parts.append(f'{label} <span class="mono">{esc(str(rec.get(k)))}</span>'.strip())
        for k in ('sector', 'industry'):
            if k in rec and pd.notna(rec.get(k)):
                parts.append(esc(str(rec.get(k))))
        if 'market_cap' in rec and pd.notna(rec.get('market_cap')):
            parts.append(f'Mkt cap {kit.rupees(rec.get("market_cap"))}')
        st.html(f'<div class="ident">{" · ".join(parts)}</div>')

    e = ctx.eligible[ctx.eligible['nse_symbol'].astype(str).str.upper() == sym]
    win = e[e['seen'] > ctx.ref - pd.Timedelta(days=365)]
    prom = win[win['person_role'].isin(signals.PROMOTER_ROLES)]
    off = win[win['person_role'].isin(['director', 'kmp'])]
    d = ctx.deals[ctx.deals['nse_symbol'].astype(str).str.upper() == sym] if not ctx.deals.empty else pd.DataFrame()
    if not d.empty:
        d = d[~d['client_is_market_maker'].astype('boolean').fillna(False) & d['is_primary'].astype('boolean').fillna(False)]
    sh = signals.latest_shareholding(ctx.shareholding)
    shr = sh[sh['symbol'].astype(str).str.upper() == sym] if not sh.empty else pd.DataFrame()
    pledge = shr['promoter_pledge_pct'].iloc[0] if len(shr) else None
    signed = prom['pct_of_mcap'] * prom['side'].map({'BUY': 1, 'SELL': -1})
    kit.tiles([
        kit.Tile('Promoter net, 12 months', kit.rupees(prom['signed_value'].sum(), signed=True),
                 f'{kit.pct(signed.sum(), 3, signed=True)} of market cap, open market only',
                 'up' if prom['signed_value'].sum() > 0 else 'down' if prom['signed_value'].sum() < 0 else ''),
        kit.Tile('Directors & KMP net', kit.rupees(off['signed_value'].sum(), signed=True), f'{off["person_id"].nunique()} people'),
        kit.Tile('Deals net, real buyers', kit.rupees(d['signed_value'].sum() if not d.empty else None, signed=True),
                 'bulk/block, market makers excluded'),
        kit.Tile('Promoter holding · pledge',
                 f'{kit.pct(shr["promoter_holding_pct"].iloc[0], 1) if len(shr) else "—"} · {kit.pct(pledge, 1) if pledge is not None else "—"}',
                 'pledge as % of promoter shares, latest quarter'),
    ])

    events = []
    for _, r in t.assign(seen=pd.to_datetime(t['broadcast_date'], errors='coerce')).sort_values('seen', ascending=False).head(60).iterrows():
        market = bool(r['is_market'])
        dot = ('buy' if r['side'] == 'BUY' else 'sell') if market else 'warn' if r.get('needs_review') else ''
        what = f'{r["mode_raw"] or r["kind"]!s}' if not market else ('bought' if r['side'] == 'BUY' else 'sold')
        events.append((r['seen'], dot, f'<b>{esc(str(r["person_name"]))}</b> ({esc(kit.role(r["person_role"]))}) '
                                       f'{esc(what)} {kit.rupees(r["value"])}' + ('' if market else ' · not an open-market trade')))
    if not d.empty:
        for _, r in d.sort_values('date', ascending=False).head(30).iterrows():
            verb = 'bought' if r['side'] == 'BUY' else 'sold'
            text = (f'<b>{esc(str(r["client_name"]))}</b> {verb} '
                    f'{kit.rupees(r["value"])} in a {esc(str(r["feeds"]))} deal')
            events.append((r['date'], 'buy' if r['side'] == 'BUY' else 'sell', text))
    for frame, date_col, text in ((ctx.actions, 'ex_date', lambda r: f'Corporate action: {esc(str(r["subject"]))}'),
                                  (ctx.sast, 'transaction_date', lambda r: f'SAST: <b>{esc(str(r["acquirer_name"]))}</b> '
                                   f'{esc(str(r["action_type"]).lower())}, stake now {kit.pct(r["post_stake_pct"])}'),
                                  (ctx.meetings, 'meeting_date', lambda r: f'Board meeting to consider {esc(str(r["purposes"]).replace("_", " "))}')):
        if frame is not None and not frame.empty:
            for _, r in frame[frame['symbol'].astype(str).str.upper() == sym].iterrows():
                events.append((pd.to_datetime(r[date_col], errors='coerce'), 'event', text(r)))
    events = sorted([x for x in events if pd.notna(x[0])], key=lambda x: x[0], reverse=True)
    with kit.card('Timeline', 'co_tl', 'every event, newest first'):
        if not events:
            kit.empty('No filings for this company in the data.')
        else:
            st.html('<div class="tl">' + ''.join(
                f'<div class="tl-row"><span class="tl-d">{pd.Timestamp(dt).strftime("%d %b %y")}</span>'
                f'<span class="tl-dot {dot}"></span><span class="tl-t">{txt}</span></div>' for dt, dot, txt in events[:80]) + '</div>')
    kit.caption('A price chart with each filing marked at its broadcast date arrives with the price join.')
