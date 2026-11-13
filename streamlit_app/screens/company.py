"""Company page (/company?symbol=XYZ), one dossier (redesign of 21 Oct 2026, docs/REVAMP_PLAN.md and
docs/DESIGN.md): the header line and the quote; for and against with their numbers (the Today builders in
insiders_clean/ideas.py run on this company's rows, 90 days); the risks, always shown; the price with each
insider decision and the money in and out; ownership by investor type, quarter by quarter, from the
shareholding XBRL; and one timeline of every filing, newest first, each row opening to its facts."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from data import store
from ui import kit, lwchart
from ui.kit import esc
from ui.table import facts

from insiders_clean import ideas, ownership, signals
from screens import buybacks
from screens.capital_raises import issue_rows, qip_rows, rights_rows
from screens.ctx import load, need_data, split_since, with_flags
from screens import moves, pages
from ui import ds

READ = {'leaning_positive': 'Ahead', 'drag': 'Behind', 'no_edge': 'No edge', 'few': 'Few cases', 'not_measured': 'Not measured'}
# Timeline kinds shown until switched off; the rest (ESOPs, gifts, transfers) on request.
QUIET = ('Other insider filing', 'Staff trade')
# The timeline opens on the decisions that moved money; the rest is one tap away (design V3, owner 23 Oct).
MONEY = ('Insider buy', 'Insider sell', 'Bulk deal', 'Block deal', 'SAST', 'Preferential issue', 'Rights issue', 'QIP', 'Buyback')
DEAL_MARK_MIN = 5e7   # Rs 5 crore: a bulk or block deal smaller than this is not drawn on the price line


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
    return None


def _link(url) -> list:
    return [('The filing', url)] if isinstance(url, str) and url.startswith('http') else []


def _day(v) -> pd.Timestamp:
    """A date on one basis: results carry an IST time with its zone, other filings a plain date."""
    d = pd.to_datetime(v, errors='coerce')
    if pd.notna(d) and d.tzinfo is not None:
        d = d.tz_convert('Asia/Kolkata').tz_localize(None)
    return d


def _signed(r):
    """% of market cap with the side's sign: a sale is negative (it showed as a green + on real data)."""
    v = kit._finite(r.get('pct_of_mcap'))
    return None if v is None else -abs(v) if r.get('side') == 'SELL' else abs(v)


def _row(date, what, who='', sub='', text='', value=None, pct=None, items=(), links=()) -> dict:
    return {'date': _day(date), 'what': what, 'who': who, 'sub': sub, 'text': text,
            'value': value, 'pct': pct, '_facts': list(items), '_links': list(links)}


def _months(start, end) -> int | None:
    """Whole months from the year-to-date start to the period end (6 for Apr-Sep), None when not filed."""
    a, b = pd.to_datetime(start, errors='coerce'), pd.to_datetime(end, errors='coerce')
    return None if pd.isna(a) or pd.isna(b) else (b.year - a.year) * 12 + b.month - a.month + 1


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
        # Designated persons, employees and relatives are not decision-makers (DESIGN_V3: they never count): their own
        # kind, one tap away, so 37 small staff sales of HCLTECH do not bury the promoters' own trades (12 Nov).
        decides = r.get('person_role') in signals.DECISION_ROLES
        what = (('Insider buy' if r['side'] == 'BUY' else 'Insider sell') if decides else 'Staff trade') if market else \
            'Pledge' if kind.startswith('pledge') else 'Other insider filing'
        verb = ('bought' if r['side'] == 'BUY' else 'sold') if market else str(r.get('mode_raw') or kind.replace('_', ' ') or 'filed').lower()
        n = kit.shares(r.get('quantity')) if kit._finite(r.get('quantity')) is not None else ''
        rows.append(_row(r.get('broadcast_date'), what, str(r.get('person_name') or ''), kit.role(r.get('person_role')),
                         f'{verb} {n} shares'.replace('  ', ' ') + (f' at {kit.price(r["price"])}' if market and kit._finite(r.get('price')) else ''),
                         r.get('value') if market else None, _signed(r) if market else None, _trade_facts(r), _link(r.get('source_url'))))
    for r in (d.to_dict('records') if not d.empty else []):
        buy = r['side'] == 'BUY'
        rows.append(_row(r.get('date'), f'{str(r.get("feeds") or "bulk").title()} deal', str(r.get('client_name') or ''),
                         'also filed as an insider trade' if r.get('also_filed') else '',
                         f'{"bought" if buy else "sold"} {kit.shares(r.get("quantity"))} shares at {kit.price(r.get("price"))}',
                         r.get('value'), _signed(r), [('Side', 'Buy' if buy else 'Sell')]))
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
    bb = buybacks.rows(own(store.table('buybacks')), ctx.prices, ctx.meetings)
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
        mine = res[res['isin'] == isin]
        if 'superseded' in mine:   # a revised filing shows once, as revised (insiders_clean/results.py)
            mine = mine[~mine['superseded'].astype('boolean').fillna(False)]
        for r in mine.to_dict('records'):
            # NSE's `consolidated` is text ("Consolidated" / "Non-Consolidated"): both read as true (audit 22 Oct).
            basis = 'consolidated' if str(r.get('consolidated') or '').strip().lower().startswith('consolidated') else 'standalone'
            months = _months(r.get('ytd_start'), r.get('period_end'))
            q = (f'quarter: revenue {kit.rupees(r.get("quarter_revenue"))} · profit {kit.rupees(r.get("quarter_profit"))}'
                 if kit._finite(r.get('quarter_revenue')) is not None else '')
            ytd = (f'{months} months: revenue {kit.rupees(r.get("ytd_revenue"))} · profit {kit.rupees(r.get("ytd_profit"))}'
                   if months and months > 3 and kit._finite(r.get('ytd_revenue')) is not None else '')
            more = [('Year to date', ytd)] if q and ytd else []
            if r.get('ytd_disagrees') == True:   # noqa: E712 -- insiders_clean/results.ytd_disagrees
                more.append(('Check the filing', "the quarter's revenue is above the year to date's: one of the two is wrong as filed"))
            rows.append(_row(r.get('broadcast_at'), 'Results', f'Quarter to {kit.day(r.get("period_end"))}', basis,
                             q or ytd, None, None, more))
    out = pd.DataFrame(rows)
    return out.dropna(subset=['date']).sort_values('date', ascending=False, kind='stable') if not out.empty else out


def _latest_trade(e: pd.DataFrame, prices: pd.DataFrame, now) -> dict | None:
    """The company's latest open-market decision by a promoter, director or KMP, with the price paid against today."""
    m = e[e['person_role'].isin(list(signals.PROMOTER_ROLES) + ['director', 'kmp'])] if not e.empty else e
    if m is None or m.empty:
        return None
    r = m.sort_values('seen').iloc[-1].to_dict()
    out = {'who': str(r.get('person_name') or 'An insider'), 'role': kit.role(r.get('person_role')), 'side': r.get('side'),
           'value': r.get('value'), 'seen': r.get('seen'), 'price': None, 'move': None}
    px = kit._finite(r.get('price'))
    if px and kit._finite(now):
        f = float(split_since(pd.DataFrame({'isin': [r.get('isin')], 'trade_date_to': [r.get('trade_date_to')]}), prices).iloc[0])
        if f == f:
            out['price'], out['move'] = px * f, (now / (px * f) - 1) * 100
    return out


def _ownership_html(table: pd.DataFrame, missing: list) -> str:
    # Only the quarters whose investor types add up; the others are counted, not drawn as empty columns.
    qs = [c for c in table.columns if c != 'change' and c not in missing]
    if not qs:
        return '<div class="empty">No quarter parsed yet.</div>'
    head = ''.join(f'<th>{c:%b %Y}</th>' for c in qs)
    body = ''
    for label, r in table.iterrows():
        cells = ''.join(f'<td>{"—" if pd.isna(r[q]) else f"{r[q]:.2f}"}</td>' for q in qs)
        ch = r['change']
        tone = '' if pd.isna(ch) or abs(ch) < 0.005 else 'up' if ch > 0 else 'down'
        cells += f'<td class="{tone}">{"—" if pd.isna(ch) else f"{ch:+.2f}"}</td>'
        body += f'<tr><th>{esc(label)}</th>{cells}</tr>'
    note = f'<p class="own-note">{kit.plural(len(missing), "earlier quarter")} not parsed yet</p>' if missing else ''
    return (f'<div class="own-wrap"><table class="own"><thead><tr><th>% of shares</th>{head}<th>Change</th></tr></thead>'
            f'<tbody>{body}</tbody></table></div>{note}')


def render():
    """One company, redesign of 12 Nov 2026: the news, the numbers, then every money decision of the last 12 months as
    5W-2H stories (insiders, deals, raises, pledges, big holders), the checks before acting, the price with every
    decision on it, who owns the company, and every filing with the noise counted, not listed."""
    ctx = load()
    if not need_data(ctx):
        return
    sym = _pick_symbol(ctx)
    if not sym:
        from screens import companies_list
        companies_list.render_list()
        return
    t = ctx.trades[ctx.trades['nse_symbol'].astype(str).str.upper() == sym].copy()
    sec = ctx.securities[ctx.securities['nse_symbol'].astype(str).str.upper() == sym] if not ctx.securities.empty else pd.DataFrame()
    rec = sec.iloc[0] if len(sec) else (t.iloc[0] if len(t) else None)
    if rec is None:
        ds.head('Company', esc(sym), [f'No company with the symbol {sym} in our data. Open one from any page, or check the spelling.'])
        return
    name = (rec.get('display_name') if 'display_name' in rec else None) or (t['company'].iloc[0] if len(t) else sym)
    isin = rec.get('isin') if pd.notna(rec.get('isin')) else (t['isin'].dropna().iloc[0] if len(t) and t['isin'].notna().any() else None)
    pr = ctx.prices[ctx.prices['isin'] == isin].iloc[0] if isin and not ctx.prices.empty and (ctx.prices['isin'] == isin).any() else None
    hist = store.price_history().get(isin) if isin else None
    now = pr['latest_close'] if pr is not None and pd.notna(pr.get('latest_close')) else None
    mcap = pr.get('market_cap') if pr is not None and pd.notna(pr.get('market_cap')) else rec.get('market_cap')
    key = str(ctx.ref)
    summary = store.artifact('artifacts/track_summary.parquet')

    e = ctx.eligible[ctx.eligible['nse_symbol'].astype(str).str.upper() == sym]
    win = e[e['seen'] > ctx.ref - pd.Timedelta(days=365)]
    prom = win[win['person_role'].isin(signals.PROMOTER_ROLES)]
    off = win[win['person_role'].isin(['director', 'kmp'])]
    d = ctx.deals[ctx.deals['nse_symbol'].astype(str).str.upper() == sym] if not ctx.deals.empty else pd.DataFrame()
    if not d.empty:
        d = d[~d['client_is_market_maker'].astype('boolean').fillna(False) & d['is_primary'].astype('boolean').fillna(False)]
        d = d[d['date'] > ctx.deals['date'].max() - pd.Timedelta(days=365)]
        d = d.assign(also_filed=signals.deals_also_filed(d, ctx.trades))
    shd = ctx.shareholding
    mine_sh = shd[(shd['symbol'].astype(str).str.upper() == sym) | ((shd['isin'] == isin) if isin and 'isin' in shd else False)] \
        if not shd.empty else pd.DataFrame()
    shr = signals.latest_shareholding(mine_sh).head(1)
    pledge = shr['promoter_pledge_pct'].iloc[0] if len(shr) else None
    headroom = _headroom(ctx, e, shr, mine_sh)
    enc = pd.to_numeric(mine_sh.sort_values('quarter_end')['promoter_encumbered_pct'], errors='coerce').iloc[-1] \
        if len(mine_sh) and 'promoter_encumbered_pct' in mine_sh else None

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

    # ---- Raises, pledges and big holders as stories; insiders, deals and stakes are dense tables below (R8) ----
    ev = moves.events(ctx, key, 365)
    ev = ev[ev['isin'] == isin] if isin and not ev.empty else ev.iloc[0:0]
    other = moves.event_stories(ctx, ev, pages.RAISE_KINDS | pages.RISK_KINDS | pages.RELEASE_KINDS | pages.STAKE_KINDS | pages.HOLDER_KINDS, summary)
    import copy
    other = [copy.copy(x) for x in other]   # the cached stories stay whole
    for x in other:   # on its own page the company's name and market line would repeat on every story
        x.company, x.market = '', ''

    # ---- Masthead: codes, the name, the news ----
    q = sym.replace('&', '%26')
    ident = [f'<span class="mono">{esc(sym)}</span>']
    for k, label in (('bse_code', 'BSE '), ('isin', '')):
        if k in rec and pd.notna(rec.get(k)):
            ident.append(f'{label}<span class="mono">{esc(str(rec.get(k)))}</span>')
    ident += [esc(str(rec.get(k))) for k in ('sector', 'industry') if k in rec and pd.notna(rec.get(k))]
    ident.append(f'<a href="https://www.nseindia.com/get-quotes/equity?symbol={q}" target="_blank" rel="noopener">NSE ↗</a>')
    latest = _latest_trade(e, ctx.prices, now)
    lines = []
    if latest:
        lines.append(f'Latest: {latest["who"]} ({latest["role"]}) {"bought" if latest["side"] == "BUY" else "sold"} {kit.rupees(latest["value"])} '
                     f'on the market, made public {kit.day(latest["seen"])}.')   # the move since is in the table, against the average paid (13 Nov)
    pnet = prom['signed_value'].sum() if not prom.empty else 0.0
    signed_mcap = (prom['pct_of_mcap'] * prom['side'].map({'BUY': 1, 'SELL': -1})).sum() if not prom.empty else 0.0
    lines.append('Over 12 months promoters ' + (f'put in net {kit.rupees(pnet)} ({kit.pct(signed_mcap, 2, signed=True)} of the company) on the market.' if pnet > 0
                 else f'took out net {kit.rupees(-pnet)} ({kit.pct(signed_mcap, 2, signed=True)} of the company) on the market.' if pnet < 0
                 else 'did not trade on the market.'))
    ds.head(' · '.join(ident), esc(str(name)), lines)

    snap = store.snapshot()
    hit = snap[snap['symbol'].astype(str).str.upper() == sym] if not snap.empty and 'symbol' in snap else pd.DataFrame()
    srow = hit.iloc[0].to_dict() if len(hit) else {}

    def own(label, val, chg, quarter):
        if val is None or pd.isna(val):
            return (label, '—', 'no shareholding filing')
        note = (f'{chg:+.2f} pts' if chg is not None and pd.notna(chg) else '') + (f' · {pd.Timestamp(quarter):%b %Y}' if quarter is not None and pd.notna(quarter) else '')
        return (label, f'{val:.2f}%', note, 'up' if chg is not None and pd.notna(chg) and chg > 0 else 'down' if chg is not None and pd.notna(chg) and chg < 0 else '')
    day_note = ''
    if hist and len(hist[1]) >= 2:
        c0, c1 = float(hist[1][-2]), float(hist[1][-1])
        day_note = f'{(c1 / c0 - 1) * 100:+.2f}% on {kit.day(hist[0][-1], with_year=False)}'
    ph = shr['promoter_holding_pct'].iloc[0] if len(shr) else None
    ds.stats([('Price', kit.price(now) if now else '—', day_note),
              ('52-week', kit.pct(pr['pct_off_high'] * 100, 1, signed=True) if pr is not None and pd.notna(pr.get('pct_off_high')) else '—', 'from the high'),
              ('Market cap', kit.rupees(mcap) if kit._finite(mcap) else '—', str(pr['mcap_bucket']) if pr is not None and isinstance(pr.get('mcap_bucket'), str) else ''),
              own('Promoters', srow.get('promoter', ph), srow.get('promoter_change_pts'), srow.get('promoter_quarter', shr['quarter_end'].iloc[0] if len(shr) else None)),
              ('Pledged', kit.pct(pledge, 1) if pledge is not None and pd.notna(pledge) else '—', 'of promoter shares',
               'down' if pledge is not None and pd.notna(pledge) and pledge > signals.HIGH_PLEDGE_PCT else ''),
              own('Mutual funds', srow.get('mf'), srow.get('mf_change_pts'), srow.get('mf_quarter')),
              own('Foreign investors', srow.get('fpi'), srow.get('fpi_change_pts'), srow.get('fpi_quarter'))])

    # ---- Checks before acting: every standing risk, one line each ----
    sold = prom[prom['side'] == 'SELL']
    cheap = ideas.issue_events(raises.get('Preferential issue'), ctx.ref, mine_sh, days=365, allottees=store.table('preferential_allottees'))
    tp = t[t['is_primary'].astype('boolean').fillna(False)] if not t.empty else t
    late = (tp[(pd.to_datetime(tp['broadcast_date'], errors='coerce') > ctx.ref - pd.Timedelta(days=365))
               & ((tp.get('insider_filed_late') == True) | (tp.get('company_filed_late') == True))]  # noqa: E712
            if not tp.empty else tp)
    fl = with_flags(pd.DataFrame({'isin': [isin]})) if isin else pd.DataFrame()
    flags = fl['trade_flags'].iloc[0] if 'trade_flags' in fl else None
    notes = (fl['trade_flag_notes'].iloc[0] if 'trade_flag_notes' in fl else None) or flags
    checks = {
        'Pledge': (f'{kit.pct(pledge, 1)} of promoter shares pledged' + (f'; {kit.pct(enc, 1)} encumbered in all' if enc is not None and pd.notna(enc)
                   and pd.notna(pledge) and enc > pledge + 0.05 else '')) if pledge is not None and pd.notna(pledge) else 'no shareholding filing in the data',
        'Promoter sales': (f'{kit.rupees(sold["value"].sum())} on the market in 12 months, '
                           f'{kit.pct(pd.to_numeric(sold["pct_of_mcap"], errors="coerce").sum(), 2)} of market cap') if not sold.empty else 'none on the market in 12 months',
        'Cheap issues': '; '.join(cheap.loc[cheap['list'] == 'warn', 'sentence']) if not cheap.empty and (cheap['list'] == 'warn').any() else 'none in 12 months',
        'Late filings': kit.plural(len(late), 'insider filing') + ' made late in 12 months' if len(late) else 'none in 12 months',
        'Tradability': (' · '.join(notes) if notes else 'no NSE surveillance or trade-for-trade flag') if isinstance(flags, list) else "not known (not in NSE's list)",
        'Room to 75%': f'{headroom.value} · {headroom.note}' if headroom else '',
    }
    amber = {k for k, bad in (('Pledge', pledge is not None and pd.notna(pledge) and pledge > signals.HIGH_PLEDGE_PCT), ('Promoter sales', not sold.empty),
                              ('Cheap issues', not cheap.empty and (cheap['list'] == 'warn').any()), ('Late filings', len(late) > 0),
                              ('Tradability', isinstance(flags, list) and bool(flags))) if bad}
    ds.section('Checks before acting', 'Amber needs a look')
    ds.html('<dl class="ds-w ds-checks">' + ''.join(f'<dt>{esc(k)}</dt><dd class="{"warn" if k in amber else ""}">{esc(v)}</dd>'
                                                   for k, v in checks.items() if v) + '</dl>')

    # ---- Money decisions, 12 months: the dense tables of the topic pages (redesign 13 Nov 2026, R8) ----
    from screens import proto
    with ds.inside():
        proto.company_tables(ctx, isin, sym)
    if other:
        ds.section('Raises, pledges and big holders', '12 months')
        ds.stories(other)

    # ---- The price with every decision, and the money by who ----
    ds.section('Price and every decision', '▲ bought ▼ sold: insiders on the day made public, funds from ₹5 Cr in deals · hover for who')
    with ds.inside():
        left, right = st.columns([3, 2], gap='large')
    with left:
        marks = e.assign(role=e['person_role'].map(kit.role))
        if not d.empty:
            big = d[~d['also_filed'] & pd.to_numeric(d['value'], errors='coerce').ge(DEAL_MARK_MIN)]
            marks = pd.concat([marks, big.assign(seen=big['date'], person_name=big['client_name'], role='bulk or block deal')[
                ['seen', 'side', 'value', 'person_name', 'role']]], ignore_index=True)
        chart = lwchart.price_chart(*hist, marks, key=sym) if hist else None
        if chart is None:
            ds.empty('No price history for this stock in our NSE/BSE price files yet.')
        else:
            st.html(chart, unsafe_allow_javascript=True)
    with right:
        others_ = win[~win['person_role'].isin(list(signals.PROMOTER_ROLES) + ['director', 'kmp'])]
        rest = d[~d['also_filed']] if not d.empty else d
        flows = [('Promoters', prom['signed_value'].sum(), f'{kit.pct(signed_mcap, 2, signed=True)} of the company'),
                 ('Directors and KMP', off['signed_value'].sum(), kit.plural(off['person_id'].nunique(), 'person', 'people')),
                 ('Staff and relatives', others_['signed_value'].sum(), 'not decision-makers'),
                 ('Others in deals', rest['signed_value'].sum() if not rest.empty else 0.0, 'bulk/block, market makers out')]
        scale = max([abs(v) for _, v, _ in flows] + [1.0])
        st.html('<div class="ds-sub">Net money, 12 months<span>open market, each rupee once</span></div><div class="fl">' + ''.join(
            f'<div class="fl-row"><span class="fl-l">{esc(label)}<em>{esc(note)}</em></span><span class="fl-track">'
            f'<i class="{"pos" if v >= 0 else "neg"}" style="width:{abs(v) / scale * 50:.1f}%"></i></span>'
            f'<span class="fl-v num">{kit.rupees(v, signed=True)}</span></div>' for label, v, note in flows) + '</div>')

    # ---- Who owns it ----
    table, missing = ownership.by_quarter(mine_sh)
    ds.section('Who owns it?', "By investor type, % of shares, from each quarter's shareholding filing")
    if table.empty:
        ds.empty('No shareholding pattern loaded for this company yet.')
    elif table.drop(columns='change').isna().all().all():
        ds.empty('Not parsed yet: the investor types of these filings are still being read.')
    else:
        ds.html(_ownership_html(table, missing))
    pg = store.table('promoter_group')
    if not pg.empty and 'symbol' in pg:
        pg = pg[pg['symbol'].astype(str).str.upper() == sym]
        if not pg.empty:
            last = pg['quarter_end'].max()
            pg = pg[pg['quarter_end'] == last].sort_values('shares', ascending=False)
            rows = [{'m': esc(str(r.get('member_name') or '')), 'c': esc(str(r.get('sub_category') or '')),
                     'p': kit.pct(r.get('pct_of_company'), 2) if kit._finite(r.get('pct_of_company')) is not None else '—',
                     'pl': kit.shares(r.get('pledged_shares')) if kit._finite(r.get('pledged_shares')) else '—'} for r in pg.head(15).to_dict('records')]
            ds.html(ds.sub(f'Promoter group at {kit.day(last)}', f'{kit.plural(len(pg), "member")}, largest first'
                           + (f'; {len(pg) - 15} smaller not listed' if len(pg) > 15 else ''))
                    + ds.list_html(rows, [ds.Col('m', 'Member'), ds.Col('c', 'Category', phone=False), ds.Col('p', '% of company', True),
                                          ds.Col('pl', 'Pledged shares', True, phone=False)]))

    # ---- Every filing, the noise one tap away ----
    tl = _timeline(ctx, sym, t, d, raises)
    ds.section('Every filing', 'Newest first; a row opens to its facts and the filing. Staff trades, ESOPs, gifts and transfers are off until picked')
    kinds = list(dict.fromkeys(tl['what'])) if not tl.empty else []
    kinds = [k for k in kinds if k in MONEY] + [k for k in kinds if k not in MONEY]
    counts = tl['what'].value_counts().to_dict() if not tl.empty else {}
    with ds.inside():
        pick = st.pills('Show', kinds, selection_mode='multi', default=[k for k in kinds if k not in QUIET], key=f'co_tl_{sym}',
                        format_func=lambda k: f'{k} · {counts.get(k, 0)}', label_visibility='collapsed') if kinds else []
    shown = tl[tl['what'].isin(pick)] if not tl.empty else tl
    with ds.inside():
        kit.table(shown, [
            kit.Col('date', 'Date', 'date'), kit.Col('what', 'Filing'), kit.Col('who', 'Who', sub='sub'),
            kit.Col('text', 'What'), kit.Col('value', 'Value', 'money'), kit.Col('pct', '% of mcap', 'spct')],
            limit=200, height=2800, key=f'co_tlt_{sym}', empty_text='No filings for this company in our data.',
            detail=lambda r: facts(r['_facts'], r['_links']))
