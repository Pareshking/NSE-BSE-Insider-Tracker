"""Company page (/company?symbol=XYZ), one dossier (redesign of 21 Oct 2026, docs/REVAMP_PLAN.md and
docs/DESIGN.md): the header line and the quote; for and against with their numbers (the Today builders in
insiders_clean/ideas.py run on this company's rows, 90 days); the risks, always shown; the price with each
insider decision and the money in and out; ownership by investor type, quarter by quarter, from the
shareholding XBRL; and one timeline of every filing, newest first, each row opening to its facts."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from data import store
from ui import charts, kit
from ui.kit import esc
from ui.table import facts, range_bar

from insiders_clean import ideas, ownership, signals
from screens import buybacks
from screens.capital_raises import issue_rows, qip_rows, rights_rows
from screens.ctx import load, need_data, with_flags

READ = {'leaning_positive': 'ahead', 'drag': 'behind', 'no_edge': 'no edge', 'few': 'few cases', 'not_measured': 'not measured'}
# Timeline kinds shown until switched off; the rest (ESOPs, gifts, transfers) on request.
QUIET = ('Other insider filing',)


def _headroom(ctx, e, shr, mine_sh):
    """Room to the 75% promoter ceiling (SCRR 19A) and creeping-acquisition room this financial year (SAST
    Reg 3(2): holders of 25% to under 75% may add 5% a year, gross, without an open offer), in one tile.
    The year's use is shares bought by promoters on the market over the company's total shares in the latest
    shareholding XBRL (audit D2); allotments and off-market moves are not in it."""
    if not len(shr) or pd.isna(shr['promoter_holding_pct'].iloc[0]):
        return None
    ph = float(shr['promoter_holding_pct'].iloc[0])
    fy = pd.Timestamp(year=ctx.ref.year if ctx.ref.month >= 4 else ctx.ref.year - 1, month=4, day=1)
    fy_buys = e[(e['seen'] >= fy) & (e['side'] == 'BUY') & e['person_role'].isin(signals.PROMOTER_ROLES)]
    mine = mine_sh if mine_sh is not None else pd.DataFrame()
    tot = pd.to_numeric(mine.sort_values('quarter_end')['total_shares'], errors='coerce').dropna() if 'total_shares' in mine else pd.Series(dtype=float)
    used = (pd.to_numeric(fy_buys['quantity'], errors='coerce').sum() / tot.iloc[-1] * 100 if len(tot) and tot.iloc[-1]
            else pd.to_numeric(fy_buys['pct_of_mcap'], errors='coerce').sum())
    creep = (f'{kit.pct(max(0.0, min(5.0 - used, 75 - ph)), 2)} creeping room left this FY · {kit.pct(used, 2)} bought since {kit.day(fy, with_year=False)}'
             if 25 <= ph < 75 else 'no creeping room: holding under 25%' if ph < 25 else f'{ph - 75:.2f} pts over: must sell down')
    return kit.Tile('Room to 75%', f'{75 - ph:.2f} pts' if ph < 75 else 'Over 75%', creep, '' if ph < 75 else 'down')


def _trade_facts(r) -> list:
    """One insider filing's facts, opened from its timeline row."""
    hb, ha = r.get('holding_before'), r.get('holding_after')
    flags = ', '.join(x.replace('_', ' ') for x in str(r.get('flags') or '').split(',') if x)
    frm, to = pd.to_datetime(r.get('trade_date_from'), errors='coerce'), pd.to_datetime(r.get('trade_date_to'), errors='coerce')
    when = lambda k: kit.day(r.get(k)) if pd.notna(pd.to_datetime(r.get(k), errors='coerce')) else ''  # noqa: E731
    return [
        ('Traded', (kit.day(to) if pd.isna(frm) or frm == to else f'{kit.day(frm)} to {kit.day(to)}') if pd.notna(to) else ''),
        ('Told the company', when('intimation_date')),
        ('Shares', kit.shares(r.get('quantity')) if kit._finite(r.get('quantity')) is not None else ''),
        ('Price', kit.price(r.get('price')) if kit._finite(r.get('price')) else ''),
        ('Held before', kit.shares(hb) if kit._finite(hb) is not None else ''),
        ('Held after', kit.shares(ha) if kit._finite(ha) is not None else ''),
        ('Own holding change', kit.pct(r.get('holding_change_pct'), 1, signed=True) if kit._finite(r.get('holding_change_pct')) is not None else ''),
        ('Mode as filed', str(r.get('mode_raw') or '')),
        ('After results', (f'{kit.sessions_text(r.get("sessions_since_window_open")).replace("same day", "first session")} after the window reopened'
                           if bool(r.get('window_open_buy')) and pd.notna(r.get('window_open_buy')) else '')),
        ('Filed late', 'yes' if r.get('insider_filed_late') is True or r.get('company_filed_late') is True else ''),
        ('Held back because', flags),
    ]


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


def _link(url) -> list:
    return [('The filing', url)] if isinstance(url, str) and url.startswith('http') else []


def _day(v) -> pd.Timestamp:
    """A date on one basis: results carry an IST time with its zone, other filings a plain date."""
    d = pd.to_datetime(v, errors='coerce')
    if pd.notna(d) and d.tzinfo is not None:
        d = d.tz_convert('Asia/Kolkata').tz_localize(None)
    return d


def _row(date, what, who='', sub='', text='', value=None, pct=None, items=(), links=()) -> dict:
    return {'date': _day(date), 'what': what, 'who': who, 'sub': sub, 'text': text,
            'value': value, 'pct': pct, '_facts': list(items), '_links': list(links)}


def _timeline(ctx, sym, t, d, raises) -> pd.DataFrame:
    """Every filing of the company, one row each, newest first: insider filings (one per trade, not per
    exchange copy), bulk and block deals, SAST disclosures, issues, buybacks, corporate actions, board
    meetings and results."""
    own = lambda f: f[f['symbol'].astype(str).str.upper() == sym] if f is not None and not f.empty and 'symbol' in f else pd.DataFrame()  # noqa: E731
    rows = []
    tp = t[t['is_primary'].astype('boolean').fillna(False)] if not t.empty else t
    for r in tp.to_dict('records'):
        kind = str(r.get('kind') or '')
        market = bool(r.get('is_market'))
        what = ('Insider buy' if r['side'] == 'BUY' else 'Insider sell') if market else \
            'Pledge' if kind.startswith('pledge') else 'Other insider filing'
        verb = ('bought' if r['side'] == 'BUY' else 'sold') if market else str(r.get('mode_raw') or kind.replace('_', ' ') or 'filed').lower()
        n = kit.shares(r.get('quantity')) if kit._finite(r.get('quantity')) is not None else ''
        rows.append(_row(r.get('broadcast_date'), what, str(r.get('person_name') or ''), kit.role(r.get('person_role')),
                         f'{verb} {n} shares'.replace('  ', ' ') + (f' at {kit.price(r["price"])}' if market and kit._finite(r.get('price')) else ''),
                         r.get('value') if market else None, r.get('pct_of_mcap') if market else None, _trade_facts(r), _link(r.get('source_url'))))
    for r in (d.to_dict('records') if not d.empty else []):
        buy = r['side'] == 'BUY'
        rows.append(_row(r.get('date'), f'{str(r.get("feeds") or "bulk").title()} deal', str(r.get('client_name') or ''),
                         'also filed as an insider trade' if r.get('also_filed') else '',
                         f'{"bought" if buy else "sold"} {kit.shares(r.get("quantity"))} shares at {kit.price(r.get("price"))}',
                         r.get('value'), r.get('pct_of_mcap'), [('Side', 'Buy' if buy else 'Sell')]))
    for r in own(ctx.sast).to_dict('records'):
        name = str(r.get('acquirer_name') or '')
        lender = bool(ideas.SECURITY_HOLDER.search(name))
        net = r.get('percent_equity_traded')
        rows.append(_row(r.get('broadcast_date') if pd.notna(pd.to_datetime(r.get('broadcast_date'), errors='coerce')) else r.get('transaction_date'),
                         'SAST', name, "lender's trustee or agent: shares held as security" if lender else ('promoter' if r.get('is_promoter') else ''),
                         f'{str(r.get("action_type") or "").lower()} · now holds {kit.pct(r.get("post_stake_pct"))}', None, net,
                         [('Bought', kit.pct(r.get('pct_acquired'))), ('Sold', kit.pct(r.get('pct_sold'))),
                          ('Mode as filed', str(r.get('mode') or '')), ('Traded to', kit.day(r.get('transaction_date')) if pd.notna(pd.to_datetime(r.get('transaction_date'), errors='coerce')) else '')],
                         _link(r.get('attachment'))))
    for label, x in raises.items():
        for r in x.to_dict('records'):
            vs = kit._finite(r.get('vs_market'))
            rows.append(_row(r.get('posted_on'), label, str(r.get('status') or ''), str(r.get('allottee_label') or r.get('allottee_category') or '').title(),
                             (f'at {kit.price(r.get("offer_price"))}' if kit._finite(r.get('offer_price')) else 'price not filed')
                             + (f', {kit.pct(vs, 1, signed=True)} vs the price now' if vs is not None else ''),
                             r.get('amount'), None,
                             [('Shares', kit.shares(r.get('shares_allotted')) if kit._finite(r.get('shares_allotted')) is not None else ''),
                              ('Instruments', str(r.get('instruments') or '')),
                              ('Trading approval', kit.day(r.get('trading_approval_date')) if pd.notna(pd.to_datetime(r.get('trading_approval_date'), errors='coerce')) else '')],
                             _link(r.get('xbrl_url'))))
    bb = buybacks.rows(own(store.table('buybacks')), ctx.prices)
    for r in (bb.to_dict('records') if not bb.empty else []):
        vs = kit._finite(r.get('vs_market'))
        rows.append(_row(r.get('when'), 'Buyback', str(r.get('how') or 'route not on NSE'), '',
                         (f'at {kit.price(r.get("offer_price"))}' if kit._finite(r.get('offer_price')) else '')
                         + (f', {kit.pct(vs, 1, signed=True)} vs the price now' if vs is not None else ''),
                         r.get('offer_value'), None,
                         [('Record date', kit.day(r.get('record_date')) if pd.notna(r.get('record_date')) else ''),
                          ('Offer', f'{kit.day(r["offer_open"])} to {kit.day(r["offer_close"])}' if pd.notna(r.get('offer_open')) else '')]))
    for r in own(ctx.actions).to_dict('records'):
        if r.get('purpose') == 'buyback' and not bb.empty:
            continue   # shown above, with its price and route
        rows.append(_row(r.get('ex_date'), 'Corporate action', str(r.get('subject') or r.get('purpose') or ''), '', '', None, None,
                         [('Record date', kit.day(r.get('record_date')) if pd.notna(pd.to_datetime(r.get('record_date'), errors='coerce')) else '')]))
    for r in own(ctx.meetings).to_dict('records'):
        rows.append(_row(r.get('meeting_date'), 'Board meeting', str(r.get('purposes') or '').replace('_', ' ').replace(',', ', ')))
    res = ctx.results
    isin = t['isin'].dropna().iloc[0] if not t.empty and t['isin'].notna().any() else None
    if res is not None and not res.empty and isin:
        for r in res[res['isin'] == isin].to_dict('records'):
            rows.append(_row(r.get('broadcast_at'), 'Results', f'Year to {kit.day(r.get("period_end"))}',
                             'consolidated' if r.get('consolidated') else 'standalone',
                             f'revenue {kit.rupees(r.get("ytd_revenue"))} · profit {kit.rupees(r.get("ytd_profit"))}'
                             if kit._finite(r.get('ytd_revenue')) is not None else ''))
    out = pd.DataFrame(rows)
    return out.dropna(subset=['date']).sort_values('date', ascending=False, kind='stable') if not out.empty else out


def _signal_list(rows: pd.DataFrame, tone: str, empty_text: str) -> str:
    if rows.empty:
        return f'<p class="co-none">{esc(empty_text)}</p>'
    out = []
    for r in rows.to_dict('records'):
        pct = r.get('pct_of_company')
        num = f'{pct:.2f}%' if pd.notna(pct) and pct else ''
        chips = ''.join(f'<span class="chip {tone}">{esc(k)}<i>{esc(READ.get(r["reads"].get(k, ""), ""))}</i></span>' for k in r['kinds'])
        out.append(f'<li><div><p>{esc(r["sentence"])}</p><div class="idea-chips">{chips}</div></div>'
                   f'<b class="num">{esc(num)}</b></li>')
    return f'<ul class="co-sig">{"".join(out)}</ul>'


def _ownership_html(table: pd.DataFrame, missing: list) -> str:
    qs = [c for c in table.columns if c != 'change']
    head = ''.join(f'<th>{c:%b %Y}' + ('<em>not parsed yet</em>' if c in missing else '') + '</th>' for c in qs)
    body = ''
    for label, r in table.iterrows():
        cells = ''.join(f'<td>{"—" if pd.isna(r[q]) else f"{r[q]:.2f}"}</td>' for q in qs)
        ch = r['change']
        tone = '' if pd.isna(ch) or abs(ch) < 0.005 else 'up' if ch > 0 else 'down'
        cells += f'<td class="{tone}">{"—" if pd.isna(ch) else f"{ch:+.2f}"}</td>'
        body += f'<tr><th>{esc(label)}</th>{cells}</tr>'
    return f'<div class="own-wrap"><table class="own"><thead><tr><th>% of shares</th>{head}<th>Change</th></tr></thead><tbody>{body}</tbody></table></div>'


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
    if rec is None:
        kit.head('Company', '')
        kit.empty(f'No company with the symbol {sym} in our data. Open one from any table, or check the spelling.')
        return
    name = (rec.get('display_name') if 'display_name' in rec else None) or (t['company'].iloc[0] if len(t) else sym)
    isin = rec.get('isin') if pd.notna(rec.get('isin')) else (t['isin'].dropna().iloc[0] if len(t) and t['isin'].notna().any() else None)
    pr = ctx.prices[ctx.prices['isin'] == isin].iloc[0] if isin and not ctx.prices.empty and (ctx.prices['isin'] == isin).any() else None
    hist = store.price_history().get(isin) if isin else None

    # Header: the name; one line of codes, sector and links; one line of the quote.
    kit.head(str(name), '')
    q = sym.replace('&', '%26')
    ident = [f'<span class="mono">{esc(sym)}</span>']
    for k, label in (('bse_code', 'BSE '), ('isin', '')):
        if k in rec and pd.notna(rec.get(k)):
            ident.append(f'{label}<span class="mono">{esc(str(rec.get(k)))}</span>')
    ident += [esc(str(rec.get(k))) for k in ('sector', 'industry') if k in rec and pd.notna(rec.get(k))]
    ident.append(f'<a href="https://www.nseindia.com/get-quotes/equity?symbol={q}" target="_blank" rel="noopener">NSE</a>')
    st.html(f'<div class="ident">{" · ".join(ident)}</div>')
    if pr is not None and pd.notna(pr.get('latest_close')):
        day = ''
        if hist and len(hist[1]) >= 2:
            c0, c1 = float(hist[1][-2]), float(hist[1][-1])
            tone = 'up' if c1 > c0 else 'down' if c1 < c0 else ''
            day = f'<span class="{tone}">{c1 - c0:+,.2f} ({(c1 / c0 - 1) * 100:+.2f}%)</span> on {kit.day(hist[0][-1])}'
        mcap = pr.get('market_cap') if pd.notna(pr.get('market_cap')) else rec.get('market_cap')
        st.html('<div class="quote">'
                f'<b class="num">{kit.price(pr["latest_close"])}</b>{day}'
                f'<span class="q-k">52W</span>{range_bar(pr.get("latest_close"), pr.get("low_52w"), pr.get("high_52w"))}'
                + (f'<span class="q-k">Mkt cap</span><b class="num">{kit.rupees(mcap)}</b>' if kit._finite(mcap) else '')
                + (f'<span class="q-k">Size</span>{esc(str(pr["mcap_bucket"]))}' if isinstance(pr.get('mcap_bucket'), str) else '')
                + '</div>')

    e = ctx.eligible[ctx.eligible['nse_symbol'].astype(str).str.upper() == sym]
    win = e[e['seen'] > ctx.ref - pd.Timedelta(days=365)]
    prom = win[win['person_role'].isin(signals.PROMOTER_ROLES)]
    off = win[win['person_role'].isin(['director', 'kmp'])]
    d = ctx.deals[ctx.deals['nse_symbol'].astype(str).str.upper() == sym] if not ctx.deals.empty else pd.DataFrame()
    if not d.empty:
        d = d[~d['client_is_market_maker'].astype('boolean').fillna(False) & d['is_primary'].astype('boolean').fillna(False)]
        d = d[d['date'] > ctx.deals['date'].max() - pd.Timedelta(days=365)]  # same 12 months as the insider flow
        d = d.assign(also_filed=signals.deals_also_filed(d, ctx.trades))
    shd = ctx.shareholding
    mine_sh = shd[(shd['symbol'].astype(str).str.upper() == sym) | ((shd['isin'] == isin) if isin and 'isin' in shd else False)] \
        if not shd.empty else pd.DataFrame()
    sh = signals.latest_shareholding(mine_sh)
    shr = sh.head(1)
    pledge = shr['promoter_pledge_pct'].iloc[0] if len(shr) else None
    headroom = _headroom(ctx, e, shr, mine_sh)
    enc = pd.to_numeric(mine_sh.sort_values('quarter_end')['promoter_encumbered_pct'], errors='coerce').iloc[-1] \
        if len(mine_sh) and 'promoter_encumbered_pct' in mine_sh else None
    kit.tiles([
        kit.Tile('Promoters hold', kit.pct(shr['promoter_holding_pct'].iloc[0], 1) if len(shr) and pd.notna(shr['promoter_holding_pct'].iloc[0]) else '—',
                 f'quarter to {kit.day(shr["quarter_end"].iloc[0])}' if len(shr) else 'no shareholding pattern yet'),
        kit.Tile('Pledged', kit.pct(pledge, 1) if pledge is not None and pd.notna(pledge) else '—',
                 'of promoter shares' + (f' · {kit.pct(enc, 1)} encumbered in all' if enc is not None and pd.notna(enc) and pledge is not None
                                         and pd.notna(pledge) and enc > pledge + 0.05 else ''),
                 'down' if pledge is not None and pd.notna(pledge) and pledge > signals.HIGH_PLEDGE_PCT else ''),
        *([headroom] if headroom else []),
    ])

    # Issues of this company, for the For / Against and the timeline.
    raises = {}
    for label, recs, build in (('Preferential issue', ctx.preferential, issue_rows), ('Rights issue', ctx.rights, rights_rows)):
        if recs is not None and not recs.empty and 'symbol' in recs:
            mine = recs[recs['symbol'].astype(str).str.upper() == sym]
            if not mine.empty:
                raises[label] = build(mine, ctx.prices)
    qips = store.table('qip')
    if not qips.empty and 'symbol' in qips:
        mine = qips[qips['symbol'].astype(str).str.upper() == sym]
        if not mine.empty:
            raises['QIP'] = qip_rows(mine, ctx.prices).assign(offer_price=lambda r: r.get('issue_price'))

    # For and against: the Today builders on this company's rows, 90 days.
    summary = store.artifact('artifacts/track_summary.parquet')
    own = lambda f: f[f['isin'] == isin] if isin and f is not None and not f.empty and 'isin' in f else None  # noqa: E731
    bb = buybacks.rows(own(store.table('buybacks')), ctx.prices)
    pros, cons = ideas.company_view([
        ideas.insider_events(e, ctx.ref, mine_sh, summary), ideas.pledge_events(t, ctx.ref, mine_sh),
        ideas.stake_events(own(ctx.sast), ctx.ref), ideas.fund_events(own(ctx.deals), t, ctx.ref),
        ideas.issue_events(raises.get('Preferential issue'), ctx.ref, mine_sh), ideas.buyback_events(bb, ctx.ref, mine_sh)], summary)

    # Risks: standing facts and the last 12 months, always shown.
    risks = []
    if pledge is not None and pd.notna(pledge) and pledge > 0:
        risks.append(f'Promoters have pledged {kit.pct(pledge, 1)} of their shares')
    if enc is not None and pd.notna(enc) and enc > (pledge if pledge is not None and pd.notna(pledge) else 0) + 0.05:
        risks.append(f'{kit.pct(enc, 1)} of promoter shares encumbered (pledge, non-disposal undertakings and others)')
    sold = prom[prom['side'] == 'SELL']
    if not sold.empty:
        risks.append(f'Promoters sold {kit.rupees(sold["value"].sum())} on the market in 12 months '
                     f'({kit.pct(pd.to_numeric(sold["pct_of_mcap"], errors="coerce").sum(), 2)} of market cap)')
    cheap = ideas.issue_events(raises.get('Preferential issue'), ctx.ref, mine_sh, days=365)
    for s_ in cheap.loc[cheap['list'] == 'warn', 'sentence'] if not cheap.empty else []:
        risks.append(s_)
    tp = t[t['is_primary'].astype('boolean').fillna(False)] if not t.empty else t
    if not tp.empty:
        late = tp[(pd.to_datetime(tp['broadcast_date'], errors='coerce') > ctx.ref - pd.Timedelta(days=365))
                  & ((tp.get('insider_filed_late') == True) | (tp.get('company_filed_late') == True))]  # noqa: E712
        if len(late):
            risks.append(f'{kit.plural(len(late), "insider filing")} made late in 12 months')
    fl = with_flags(pd.DataFrame({'isin': [isin]})) if isin else pd.DataFrame()
    flag_html = kit.flag_tags(fl['trade_flags'].iloc[0], fl['trade_flag_notes'].iloc[0]) if 'trade_flags' in fl and fl['trade_flags'].iloc[0] else ''
    if flag_html:
        risks.append(' · '.join(fl['trade_flag_notes'].iloc[0]))

    c1, c2, c3 = st.columns(3, gap='medium')
    with c1, kit.card('For', 'co_for', '90 days · largest share first'):
        st.html(_signal_list(pros, 'acc', 'No insider buying, big investor, fund or promoter issue past the bar in 90 days.'))
    with c2, kit.card('Against', 'co_against', '90 days · largest share first'):
        st.html(_signal_list(cons, 'sell', 'No promoter selling, pledging, cheap issue or big exit past the bar in 90 days.'))
    with c3, kit.card('Risks', 'co_risks', 'always shown'):
        st.html((f'<div class="flags">{flag_html}</div>' if flag_html else '')
                + (f'<ul class="co-risk">{"".join(f"<li>{esc(x)}</li>" for x in risks)}</ul>' if risks else '<p class="co-none">None found.</p>'))

    left, right = st.columns([3, 2], gap='medium')
    with left, kit.card('Price and insider trades', 'co_px', '12 months · ▲ bought ▼ sold, on the day made public'):
        chart = charts.price_with_trades(*hist, e.assign(role=e['person_role'].map(kit.role))) if hist else None
        if chart is None:
            kit.empty('No price history for this stock in our NSE/BSE price files yet.')
        else:
            st.altair_chart(chart, width='stretch')
    # Net open-market money by who, 12 months, each rupee once: a bulk/block deal that is an insider's own
    # filed trade counts under the insider, not again under deals (audit D3, D6).
    other = win[~win['person_role'].isin(list(signals.PROMOTER_ROLES) + ['director', 'kmp'])]
    rest = d[~d['also_filed']] if not d.empty else d
    signed = prom['pct_of_mcap'] * prom['side'].map({'BUY': 1, 'SELL': -1})
    flows = [('Promoters', prom['signed_value'].sum(), f'{kit.pct(signed.sum(), 2, signed=True)} of mcap'),
             ('Directors & KMP', off['signed_value'].sum(), kit.plural(off['person_id'].nunique(), 'person', 'people')),
             ('Other insiders', other['signed_value'].sum(), ''),
             ('Other deal buyers & sellers', rest['signed_value'].sum() if not rest.empty else 0.0, 'bulk/block, market makers out')]
    scale = max([abs(v) for _, v, _ in flows] + [1.0])
    bars = ''.join(
        f'<div class="fl-row"><span class="fl-l">{esc(label)}<em>{esc(note)}</em></span><span class="fl-track">'
        f'<i class="{"pos" if v >= 0 else "neg"}" style="width:{abs(v) / scale * 50:.1f}%"></i></span>'
        f'<span class="fl-v num">{kit.rupees(v, signed=True)}</span></div>' for label, v, note in flows)
    with right, kit.card('Money in and out', 'co_flow', '12 months, open market, each rupee once'):
        st.html(f'<div class="fl">{bars}</div>')

    table, missing = ownership.by_quarter(mine_sh)
    with kit.card('Ownership', 'co_own', 'by investor type, % of shares, from each quarter\'s shareholding XBRL'):
        if table.empty:
            kit.empty('No shareholding pattern loaded for this company yet.')
        elif table.drop(columns='change').isna().all().all():
            kit.empty('Not parsed yet: the investor types of these filings are still being read.')
        else:
            st.html(_ownership_html(table, missing))
        pg = store.table('promoter_group')
        if not pg.empty and 'symbol' in pg:
            pg = pg[pg['symbol'].astype(str).str.upper() == sym]
            if not pg.empty:
                last = pg['quarter_end'].max()
                pg = pg[pg['quarter_end'] == last].sort_values('shares', ascending=False)
                with st.expander(f'Promoter group · {kit.plural(len(pg), "member")} at {kit.day(last)}'):
                    kit.table(pg, [
                        kit.Col('member_name', 'Member'), kit.Col('sub_category', 'Category', phone=False),
                        kit.Col('shares', 'Shares', 'shares', phone=False), kit.Col('pct_of_company', '% of company', 'pct'),
                        kit.Col('pledged_shares', 'Pledged', 'shares', phone=False)], limit=60, key=f'co_pg_{sym}')

    tl = _timeline(ctx, sym, t, d, raises)
    with kit.card('Timeline', 'co_tl', 'every filing, newest first · a row opens to its facts'):
        kinds = list(dict.fromkeys(tl['what'])) if not tl.empty else []
        counts = tl['what'].value_counts().to_dict() if not tl.empty else {}
        pick = st.pills('Show', kinds, selection_mode='multi', default=[k for k in kinds if k not in QUIET], key=f'co_tl_{sym}',
                        format_func=lambda k: f'{k} · {counts.get(k, 0)}', label_visibility='collapsed') if kinds else []
        shown = tl[tl['what'].isin(pick)] if not tl.empty else tl
        kit.table(shown, [
            kit.Col('date', 'Date', 'date'), kit.Col('what', 'Filing'), kit.Col('who', 'Who', sub='sub'),
            kit.Col('text', 'What', phone=False), kit.Col('value', 'Value', 'money'), kit.Col('pct', '% of mcap', 'spct', phone=False)],
            limit=200, download=f'{sym}_timeline', key=f'co_tlt_{sym}', empty_text='No filings for this company in our data.',
            detail=lambda r: facts(r['_facts'], r['_links']))
