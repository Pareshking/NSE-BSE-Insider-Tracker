"""Company page (/company?symbol=XYZ), a decision page (redesign of 19 Nov 2026; owner: "Completely useless design and
not glance-worthy to take even a decision, doesn't even inspire confidence"). It answers in ten seconds: is smart money
accumulating or leaving this stock, and is anything wrong with it?

Top to bottom: the verdict in one sentence and the chips behind it (insiders 90 days, mutual funds at the month end,
foreign and domestic institutions this quarter, deals, red flags; each with its evidence status); the price with every
insider decision, deal, SAST crossing and results day on it, beside the checks as a scorecard; who owns it and who is
moving, beside which fund houses hold it; whether the business is growing, beside the money in and out; then every
decision in detail (insiders and deals each with a bought-against-sold bar, stake changes, raises), the promoter group,
holders over 1% and every filing. The numbers come from screens/company_glance.py (tested in tests/test_company_page.py)."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from data import store
from ui import dates, kit, lwchart
from ui.kit import esc
from ui.table import facts

from insiders_clean import evidence, ideas, ownership, participants, public_holders, signals
from insiders_clean.results import basis_label
from screens import buybacks
from screens import company_glance as cg
from ui import charts as cg_charts
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


BLOCK_MIN_LEGS = 3   # one day, one price, this many named clients or more: one block, shown as one row


def deal_blocks(d: pd.DataFrame) -> tuple[list[dict], pd.DataFrame]:
    """Deals that are one block (one day, one price, BLOCK_MIN_LEGS named clients or more) as one row each: who sold,
    who bought, the buyers by type, every buyer with value. Owner 19 Nov 2026, IIFL Finance on 18 Nov: FIH Mauritius's
    sale showed as one card and its ~50 buyers as 50 small cards among the rest, so the buy side read as unknown.
    Returns (block rows, the deals not in a block)."""
    if d is None or d.empty or not {'date', 'price', 'side'} <= set(d.columns):
        return [], d
    x = d.assign(_day=pd.to_datetime(d['date'], errors='coerce').dt.normalize(),
                 _px=pd.to_numeric(d['price'], errors='coerce').round(1),
                 _v=pd.to_numeric(d.get('value'), errors='coerce'),
                 _q=pd.to_numeric(d.get('quantity'), errors='coerce'))
    out, used = [], []
    for (day, px), g in x.dropna(subset=['_day', '_px']).groupby(['_day', '_px'], sort=False):
        if len(g) < BLOCK_MIN_LEGS:
            continue
        used.extend(g.index)
        sell, buy = g[g['side'] == 'SELL'].sort_values('_v', ascending=False), g[g['side'] == 'BUY'].sort_values('_v', ascending=False)
        lead = sell if len(sell) and sell['_v'].sum() >= buy['_v'].sum() else buy   # the side the block is about
        def top(f, n=3):
            return ', '.join(f'{c} {kit.rupees(v)}' for c, v in zip(f['client_name'].astype(str).head(n), f['_v'].head(n)))
        if len(sell) and len(buy):
            who = f'{", ".join(sell["client_name"].astype(str).head(2))}' + (f' +{len(sell) - 2}' if len(sell) > 2 else '') \
                  + f' to {len(buy)} buyer{"s" * (len(buy) > 1)}'
        elif len(sell):
            who = f'{len(sell)} sellers'
        else:
            who = f'{len(buy)} buyers'
        verb = 'sold' if lead is sell else 'bought'
        text = f'{verb} {kit.shares(lead["_q"].sum())} shares at {kit.price(px)}' + (f' · bought by {top(buy)}' + (f' +{len(buy) - 3} more' if len(buy) > 3 else '')
                                                                                     if lead is sell and len(buy) else '')
        facts_ = []
        if len(sell) and len(buy):
            named = buy['_q'].sum() / sell['_q'].sum() if sell['_q'].sum() else None
            facts_.append(('Buyers named', f'{len(buy)} buyers for {kit.shares(buy["_q"].sum())} of the {kit.shares(sell["_q"].sum())} shares sold'
                           + (f' ({named:.0%})' if named is not None else '')))
        for side_name, f in (('Buyers', buy), ('Sellers', sell)):
            if f.empty:
                continue
            kinds = f.assign(_t=f['client_name'].map(lambda n: participants.TYPES.get(participants.classify(n)[0], 'Unknown')))
            by = kinds.groupby('_t').agg(v=('_v', 'sum'), n=('_v', 'size')).sort_values('v', ascending=False)
            facts_.append((f'{side_name} by type', ' · '.join(f'{t} {kit.rupees(r.v)} ({int(r.n)})' for t, r in by.iterrows())))
            facts_ += [(f'{"Bought" if side_name == "Buyers" else "Sold"}: {c}', f'{kit.rupees(v)} · {kit.shares(q)} shares')
                       for c, v, q in zip(f['client_name'].astype(str), f['_v'], f['_q'])]
        first = lead.iloc[0].to_dict()
        feed = str(first.get('feeds') or 'block').split(',')[0].strip().title() or 'Block'
        out.append(_row(day, f'{feed} deal', who, f'{len(g)} clients at one price', text,
                        lead['_v'].sum(), sum(v for v in (_signed(r) for r in lead.to_dict('records')) if v is not None) or None, facts_))
    return out, d.drop(index=used)


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
    blocks, d = deal_blocks(d)
    rows.extend(blocks)
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
            top = basis_label(r.get('revenue_basis'))
            top = 'revenue' if top == 'Revenue' else top.lower()   # a bank's total income, an insurer's premium (20 Nov)
            q = (f'quarter: {top} {kit.rupees(r.get("quarter_revenue"))} · profit {kit.rupees(r.get("quarter_profit"))}'
                 if kit._finite(r.get('quarter_revenue')) is not None else '')
            ytd = (f'{months} months: {top} {kit.rupees(r.get("ytd_revenue"))} · profit {kit.rupees(r.get("ytd_profit"))}'
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


def holder_change(r: dict) -> str:
    """One holder's change since the company's previous quarter, in words and points (public_holders.changes)."""
    c = r.get('change')
    if c == 'new':
        return 'New: crossed 1%'
    if c == 'exited':
        return f'Left the list (was {kit.pct(r.get("prev_pct"), 2)}): under 1% or sold out'
    if c in ('added', 'cut'):
        pts = kit._finite(r.get('pct_change'))
        return (f'{"Added" if c == "added" else "Cut"} {kit.shares(abs(kit._finite(r.get("shares_change")) or 0))} shares'
                + (f', {pts:+.2f} pts' if pts is not None else ''))
    if c == 'same':
        return 'Unchanged'
    return '—'


def holder_rows(ch: pd.DataFrame) -> list[dict]:
    """Rows of "Who holds over 1%?": name (linked to the holder's page), type, % now, the change. Exited holders last."""
    return [{'h': f'<a href="{kit.entity_href(r.get("holder_key"))}" target="_self">{esc(str(r.get("holder_name") or ""))}</a>',
             't': esc(public_holders.TYPE_LABELS.get(r.get('type'), str(r.get('type') or ''))),
             'p': kit.pct(r.get('pct_of_company'), 2) if r.get('change') != 'exited' else '—',
             'c': esc(holder_change(r))} for r in ch.to_dict('records')]


def _public_holders(ph: pd.DataFrame, sym: str, isin, mine_sh: pd.DataFrame | None) -> None:
    """Who holds over 1%? The public shareholders the latest filing names, and the change since the quarter before."""
    if ph is None or ph.empty or 'symbol' not in ph:
        return
    mine = ph[(ph['symbol'].astype(str).str.upper() == sym) | ((ph['isin'] == isin) if isin else False)]
    ds.section('Who holds over 1%?', 'Public shareholders the shareholding pattern names (over 1% of the company), '
               'and what changed since the quarter before')
    if mine.empty:
        ds.empty('No public shareholder over 1% read for this company yet.')
        return
    ch = public_holders.changes(mine)
    last, prev = ch['quarter_end'].max(), ch['prev_quarter_end'].max()
    note = (f'vs {kit.day(prev)}' if pd.notna(prev) else 'no earlier quarter read, so no change shown')
    filed_last = (pd.to_datetime(mine_sh['quarter_end'], errors='coerce').max()
                  if mine_sh is not None and not mine_sh.empty and 'quarter_end' in mine_sh else pd.NaT)
    if pd.notna(filed_last) and filed_last > last:   # the newer filing named no one, or is not read yet: said
        note += f'; the {kit.day(filed_last)} filing names none here (not read yet, or no one over 1%)'
    ds.html(ds.sub(f'At {kit.day(last)}', f'{kit.plural(int(ch["change"].ne("exited").sum()), "holder")}, largest first · {note}')
            + ds.list_html(holder_rows(ch), [ds.Col('h', 'Holder'), ds.Col('t', 'Type', phone=False),
                                             ds.Col('p', '% of company', True), ds.Col('c', 'Since last quarter')]))



# ---- The glance (owner, 19 Nov 2026: "not glance-worthy to take even a decision"): screens/company_glance.py computes,
# these draw ----

INSIDER_SIGNAL = {(1, True): ('promoter_buy', 'Promoter buys'), (1, False): ('officer_buy', 'Director/KMP buys'),
                  (-1, True): ('promoter_sell', 'Promoter sales'), (-1, False): ('officer_sell', 'Director/KMP sales')}
ICON = {'up': '▲', 'down': '▼', 'flat': '–', 'na': '·', 'fail': '!', 'warn': '!', 'pass': '✓', 'info': 'i'}


def _insider_evidence(ins: dict, summary) -> str:
    """The measured record of the kind of insider move the chip shows (Track record), in a few words."""
    side = cg._side(ins['net'], cg.INSIDER_MIN)
    if not side:
        return 'No signal: under ₹25 L net' if ins['rows'] else ''
    promoters = (ins['promoter_net'] > 0) if side > 0 else (ins['promoter_net'] < 0)
    code, label = INSIDER_SIGNAL[(side, bool(promoters))]
    v = evidence.verdict(summary, code)
    return f'{label}: {v["tag"].replace("Early read: ", "measured ")}'


def _month(m) -> str:
    try:
        return pd.Period(str(m), 'M').strftime('%b %Y')
    except Exception:  # noqa: BLE001 -- a month we cannot read is shown as filed
        return str(m)


def _chips_html(chips: list) -> str:
    return '<div class="cg-chips">' + ''.join(
        f'<div class="cg-chip {c.tone}"><span class="l"><i>{ICON.get(c.tone, "")}</i>{esc(c.label)}</span>'
        f'<b class="num">{esc(c.value)}</b><span class="n">{esc(c.note)}</span>'
        + (f'<span class="ev">{esc(c.evidence)}</span>' if c.evidence else '') + '</div>' for c in chips) + '</div>'


def _checks_html(rows: list) -> str:
    """The checks as a scorecard: an icon, the check, one line."""
    return '<div class="cg-checks">' + ''.join(
        f'<div class="cg-ck {f.level}"><i>{ICON.get(f.level, "")}</i><span class="k">{esc(f.name)}</span>'
        f'<span class="t">{esc(f.text)}' + (f'<em>{esc(f.evidence)}</em>' if f.evidence else '') + '</span></div>' for f in rows) + '</div>'


def _year_move(hist) -> str:
    """'Down 12.3% in a year' from the adjusted closes, over the longest span up to a year we hold."""
    if not hist or len(hist[1]) < 5:
        return ''
    days_ = pd.to_datetime(pd.Series(hist[0]))
    last = days_.iloc[-1]
    i = int((days_ >= last - pd.Timedelta(days=365)).to_numpy().argmax())
    a, b = float(hist[1][i]), float(hist[1][-1])
    if not a:
        return ''
    ch = (b / a - 1) * 100
    span = 'a year' if (last - days_.iloc[i]).days >= 350 else f'{(last - days_.iloc[i]).days // 30} months'
    return f'{"Up" if ch > 0 else "Down" if ch < 0 else "Flat"} {abs(ch):.1f}% in {span}'


def _chart_events(ctx, sym: str, d: pd.DataFrame) -> pd.DataFrame:
    """Deals of ₹5 Cr and over (one marker per day and side, naming the largest clients) and SAST disclosures, for
    the price chart."""
    rows = []
    if d is not None and not d.empty:
        big = d[pd.to_numeric(d['value'], errors='coerce').ge(DEAL_MARK_MIN)]
        for (day, side), g in big.assign(_d=pd.to_datetime(big['date'], errors='coerce').dt.normalize()).groupby(['_d', 'side']):
            g = g.sort_values('value', ascending=False)
            who = ', '.join(f'{c} {kit.rupees(v)}' for c, v in zip(g['client_name'].astype(str).head(2), g['value'].head(2)))
            more = f' +{len(g) - 2} more' if len(g) > 2 else ''
            rows.append({'day': day, 'kind': 'deal_buy' if side == 'BUY' else 'deal_sell',
                         'text': f'Deal {"bought" if side == "BUY" else "sold"} {kit.rupees(g["value"].sum())}: {who}{more}'})
    sa = ctx.sast
    if sa is not None and not sa.empty and 'symbol' in sa:
        for r in sa[sa['symbol'].astype(str).str.upper() == sym].to_dict('records'):
            name = str(r.get('acquirer_name') or '')
            if ideas.SECURITY_HOLDER.search(name):
                continue   # a lender's trustee: shares held as security, not a holder's move
            when = pd.to_datetime(r.get('broadcast_date'), errors='coerce')
            when = when if pd.notna(when) else pd.to_datetime(r.get('transaction_date'), errors='coerce')
            rows.append({'day': when, 'kind': 'sast',
                         'text': f'SAST: {name} {str(r.get("action_type") or "").lower()}, now {kit.pct(r.get("post_stake_pct"))}'})
    return pd.DataFrame(rows, columns=['day', 'kind', 'text'])


def _results_days(results: pd.DataFrame | None, isin) -> pd.DataFrame:
    """The days the company's results were made public, for the shaded band on the price chart."""
    if results is None or results.empty or not isin:
        return pd.DataFrame(columns=['day', 'text'])
    r = results[results['isin'] == isin]
    if 'superseded' in r:
        r = r[~r['superseded'].astype('boolean').fillna(False).astype(bool)]
    out = []
    for x in r.to_dict('records'):
        day = _day(x.get('broadcast_at'))
        if pd.isna(day):
            continue
        rev, pro = kit._finite(x.get('quarter_revenue')), kit._finite(x.get('quarter_profit'))
        out.append({'day': day.normalize(), 'text': f'Results, quarter to {kit.day(x.get("period_end"))}'
                    + (f': revenue {kit.rupees(rev)}, profit {kit.rupees(pro)}' if rev is not None else '')})
    return pd.DataFrame(out, columns=['day', 'text']).drop_duplicates('day')


def _snap(sym: str) -> dict:
    snap = store.snapshot()
    hit = snap[snap['symbol'].astype(str).str.upper() == sym] if not snap.empty and 'symbol' in snap else pd.DataFrame()
    return hit.iloc[0].to_dict() if len(hit) else {}


def _owners(mix: pd.DataFrame, delta: pd.DataFrame, mine_sh: pd.DataFrame) -> None:
    """Who owns it and who is moving: the mix by quarter, this quarter against the last."""
    from screens import proto
    if mix.empty:
        reason = ('No shareholding pattern loaded for this company yet.' if mine_sh is None or mine_sh.empty
                  else "The investor types of this company's filings are not parsed yet (or do not add up), so the mix is not drawn.")
        proto._qa('Who owns it, and who is moving?', 'Not known yet', reason, 'co-owners')
        return
    q = pd.Timestamp(mix['quarter'].max())
    if delta.empty:
        proto._qa('Who owns it, and who is moving?', f'Promoters {mix.loc[(mix["quarter"] == q) & (mix["group"] == "Promoter"), "pct"].sum():.2f}%',
                  f'% of shares at {q:%d %b %Y}; only one quarter parsed (or the one before is missing), so no change is shown.', 'co-owners')
    else:
        moved = delta[delta['pts'].abs() >= cg.QUARTER_MIN_PTS].sort_values('pts', key=abs, ascending=False)
        up = [f'{g} +{p:.2f}' for g, p in zip(moved['group'], moved['pts']) if p > 0][:2]
        dn = [f'{g} {p:.2f}' for g, p in zip(moved['group'], moved['pts']) if p < 0][:2]
        ans = ('Adding: ' + ', '.join(up) if up else '') + ('; ' if up and dn else '') + ('Cutting: ' + ', '.join(dn) if dn else '')
        proto._qa('Who owns it, and who is moving?', esc(ans + ' pts') if ans else 'Steady: no group moved 0.2 pts',
                  f'% of shares by investor type at each quarter end; the change is {q:%b %Y} against '
                  f'{pd.Timestamp(delta["prev_quarter"].iloc[0]):%b %Y}.', 'co-owners')
    st.html(cg_charts.ownership_stack(mix, cg.MIX_ORDER))
    if not delta.empty:
        st.html(ds.sub('This quarter against the last', 'points of the company')
                + cg_charts.delta_bars([(g, p, '') for g, p in zip(delta['group'], delta['pts'])], floor=0.005))
    table, missing = ownership.by_quarter(mine_sh)
    if not table.empty and not table.drop(columns='change').isna().all().all():
        with st.expander('Every type, every quarter'):
            st.html(_ownership_html(table, missing))


def _house_names() -> dict:
    """Fund house key -> name as AMFI lists it (collectors/mf_portfolios/houses.py); {} when not importable."""
    try:
        from collectors.mf_portfolios.houses import HOUSES, PENSION
        return {h.key: h.name for h in list(HOUSES) + list(PENSION)}
    except Exception:  # noqa: BLE001 -- names fall back to the house key
        return {}


def _funds(fm: dict | None, ch: pd.DataFrame, stock_month: pd.DataFrame, isin, tot_sh, srow_mf=None) -> None:
    """Which fund houses hold it, their month-end trend, and who added or cut last month."""
    from screens import proto
    names = _house_names()
    houses, trend = cg.fund_houses(ch, isin, tot_sh, {k: v.replace(' Mutual Fund', '') for k, v in names.items()}, limit=10)
    collected = int(cg._mf(ch)['amc'].nunique()) if ch is not None and not ch.empty and 'amc' in ch else 0
    filed = f'Mutual funds hold {srow_mf:.2f}% by the company\'s own filing.' if kit._finite(srow_mf) is not None else ''
    if houses.empty or fm is None:
        why = ("The fund houses' month-end portfolios are not collected yet." if not collected else
               f'None of the {collected} fund houses collected held it at a month end. ') + (' ' + filed if filed else '')
        proto._qa('Which funds hold it?', 'No fund house in our data', why.strip(), 'co-funds')
        return
    held = houses[houses['shares'] > 0]
    pct = held['pct'].sum() if held['pct'].notna().any() else None
    ans = f'{len(held)} fund house{"s" * (len(held) != 1)}' + (f' hold {pct:.2f}% of the company' if pct is not None else ' hold it')
    why = (f'Month-end {_month(fm["month"])} portfolios of the {collected} houses collected, active and index schemes together; '
           f'{fm["adding"]} added, {fm["cutting"]} cut' + (f', {fm["new"]} started' if fm['new'] else '')
           + (f', {fm["exit"]} sold out' if fm['exit'] else '') + '. ' + _movers(houses) + filed)
    proto._qa('Which funds hold it?', esc(ans), why.strip(), 'co-funds')
    rows = []
    for r in houses.head(10).to_dict('records'):
        tr = trend[trend['house'] == r['house']].sort_values('month')
        vals = list(tr['pct'] if 'pct' in tr else tr['shares'])
        c = kit._finite(r.get('change'))
        tone = 'up' if c and c > 0 else 'down' if c and c < 0 else 'flat'
        kind = r.get('kind')
        chg = ('new' if kind == 'new' else 'sold out' if kind == 'exit' or r['shares'] <= 0 else
               (('+' if c > 0 else '−') + _sh(abs(c))) if c else 'unchanged')
        line = cg_charts.spark(vals, 96, 28, tone) if len(vals) > 1 else '<span class="cg-nospark">one month</span>'
        rows.append(f'<div class="cg-fh"><span class="nm">{esc(r["house"])}</span>{line}'
                    f'<span class="v num">{kit.pct(r["pct"], 2) if kit._finite(r.get("pct")) is not None else _sh(r["shares"])}'
                    f'<em>{_sh(r["shares"])} shares</em></span><span class="c num {tone}">{esc(chg)}</span></div>')
    # st.markdown, not st.html: st.html's sanitiser drops inline SVG (the trend lines)
    st.markdown(ds.sub('Fund houses', f'% of the company · {trend["month"].nunique()} month ends · shares added or cut in {_month(fm["month"])}')
                + '<div class="cg-fhs">' + ''.join(rows) + '</div>'
                + (f'<p class="dt-foot">{len(houses) - 10} more houses hold smaller amounts.</p>' if len(houses) > 10 else ''),
                unsafe_allow_html=True)


def _sh(n) -> str:
    """A share count short, in Indian units: 4.94 Cr, 62.0 L, 4,481."""
    v = kit._finite(n)
    if v is None:
        return '—'
    a = abs(v)
    return f'{a / 1e7:,.2f} Cr' if a >= 1e7 else f'{a / 1e5:,.1f} L' if a >= 1e5 else kit.shares(a)


def _movers(houses: pd.DataFrame) -> str:
    """'Added most: Axis (+9.00 L shares); cut most: SBI (−6.00 L). ' from the month's change per house."""
    c = pd.to_numeric(houses['change'], errors='coerce')
    up, dn = houses[c > 0].assign(_c=c).sort_values('_c', ascending=False), houses[c < 0].assign(_c=c).sort_values('_c')
    part = []
    if len(up):
        part.append(f'Added most: {up["house"].iloc[0]} (+{_sh(up["_c"].iloc[0])} shares)')
    if len(dn):
        part.append(f'cut most: {dn["house"].iloc[0]} (−{_sh(-dn["_c"].iloc[0])})')
    return ('; '.join(part) + '. ') if part else ''


def _growth(results: pd.DataFrame | None, isin) -> None:
    """Is the business growing? Revenue and profit, quarter by quarter, with the change on a year ago and the margin."""
    from screens import proto
    g, basis = cg.growth(results, isin)
    if g.empty:
        proto._qa('Is the business growing?', 'No results read yet',
                  "No quarter with revenue in NSE's integrated-filing XBRL for this company in our data (collected from 15 Oct "
                  "2026; banks, NBFCs and insurers file revenue under other names, not read here).", 'co-growth')
        return
    last = g.iloc[-1]
    q = pd.Timestamp(last['period_end'])
    if last['rev_yoy'] is not None and last['rev_yoy'] == last['rev_yoy']:
        ans = f'Revenue {last["rev_yoy"]:+.1f}% on a year ago' + (f', profit {last["profit_yoy"]:+.1f}%'
                                                               if last['profit_yoy'] is not None and last['profit_yoy'] == last['profit_yoy'] else '')
    else:
        ans = f'Revenue {kit.rupees(last["revenue"])} in the quarter'
    why = (f'Quarter to {q:%d %b %Y}, {basis}' + (f', net margin {last["margin"]:.1f}%' if last['margin'] == last['margin'] and last['margin'] is not None else '')
           + f'. {kit.plural(len(g), "quarter")} in our data'
           + ('' if g['rev_yoy'].notna().any() else '; no year-ago quarter yet, so no year-on-year change') + '.')
    proto._qa('Is the business growing?', esc(ans), why, 'co-growth')

    def yoy(v):
        return (f'{v:+.0f}% y/y', 'up' if v > 0 else 'down') if v is not None and v == v else ('', '')
    st.html(ds.sub('Revenue', 'a quarter, ₹ Cr · change on a year ago')
            + cg_charts.columns([{'label': f'{pd.Timestamp(r["period_end"]):%b %y}', 'value': r['revenue'],
                                  'top': f'{r["revenue"] / 1e7:,.0f}', 'sub': yoy(r['rev_yoy'])[0], 'sub_tone': yoy(r['rev_yoy'])[1]}
                                 for r in g.to_dict('records')]))
    st.html(ds.sub('Profit', 'a quarter, ₹ Cr · net margin')
            + cg_charts.columns([{'label': f'{pd.Timestamp(r["period_end"]):%b %y}', 'value': r['profit'],
                                  'top': f'{r["profit"] / 1e7:,.0f}' if r['profit'] is not None else '',
                                  'tone': 'pos' if (r['profit'] or 0) >= 0 else 'down',
                                  'sub': f'{r["margin"]:.1f}%' if r['margin'] is not None and r['margin'] == r['margin'] else ''}
                                 for r in g.to_dict('records')]))
    if g['derived'].any():
        st.html('<p class="dt-foot">A half-year filing\'s quarter is its year to date less the quarter before (marked as derived in the data).</p>')


def render():
    """One company as a decision page (19 Nov 2026, the module's docstring): the verdict band, the price with every
    decision on it and the checks, who owns it and which funds, the business, then every decision and filing."""
    ctx = load()
    if not need_data(ctx):
        return
    sym = _pick_symbol(ctx)
    if not sym:
        from screens import companies_list
        companies_list.render_list()
        return
    sec = ctx.securities[ctx.securities['nse_symbol'].astype(str).str.upper() == sym] if not ctx.securities.empty else pd.DataFrame()
    # A BSE-only company is opened by its BSE code (the top search, 14 Nov 2026): found by code, its rows by ISIN
    if sec.empty and not ctx.securities.empty and 'bse_code' in ctx.securities and sym.isdigit():
        sec = ctx.securities[ctx.securities['bse_code'].astype(str).str.split('.').str[0] == sym]
    sec_isin = sec['isin'].dropna().iloc[0] if len(sec) and 'isin' in sec and sec['isin'].notna().any() else None

    def mine(f: pd.DataFrame) -> pd.DataFrame:
        """This company's rows: by NSE symbol, or by ISIN (a BSE-only company has no NSE symbol)."""
        if f is None or f.empty:
            return pd.DataFrame() if f is None else f
        hit = f['nse_symbol'].astype(str).str.upper() == sym if 'nse_symbol' in f else pd.Series(False, index=f.index)
        if sec_isin and 'isin' in f:
            hit |= f['isin'] == sec_isin
        return f[hit]
    t = mine(ctx.trades).copy()
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

    e = mine(ctx.eligible)
    win = e[e['seen'] > ctx.ref - pd.Timedelta(days=365)]
    prom = win[win['person_role'].isin(signals.PROMOTER_ROLES)]
    off = win[win['person_role'].isin(['director', 'kmp'])]
    d = mine(ctx.deals) if not ctx.deals.empty else pd.DataFrame()
    d_all = d
    if not d.empty:
        d = d[~d['client_is_market_maker'].astype('boolean').fillna(False) & d['is_primary'].astype('boolean').fillna(False)]
        d = d_all = d.assign(also_filed=signals.deals_also_filed(d, ctx.trades))   # every deal, for the history below
        d = d[d['date'] > ctx.deals['date'].max() - pd.Timedelta(days=365)]
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

    # ---- The facts the glance is built from (each from the clean tables; nothing filled) ----
    q = sym.replace('&', '%26')
    ident = [f'<span class="mono">{esc(sym)}</span>']
    for k, label in (('bse_code', 'BSE '), ('isin', '')):
        if k in rec and pd.notna(rec.get(k)):
            ident.append(f'{label}<span class="mono">{esc(str(rec.get(k)))}</span>')
    ident += [esc(str(rec.get(k))) for k in ('sector', 'industry') if k in rec and pd.notna(rec.get(k))]
    ident.append(f'<a href="https://www.nseindia.in/get-quotes/equity?symbol={q}" target="_blank" rel="noopener">NSE ↗</a>')
    latest = _latest_trade(e, ctx.prices, now)
    signed_mcap = (prom['pct_of_mcap'] * prom['side'].map({'BUY': 1, 'SELL': -1})).sum() if not prom.empty else 0.0

    sold = prom[prom['side'] == 'SELL']
    cheap = ideas.issue_events(raises.get('Preferential issue'), ctx.ref, mine_sh, days=365, allottees=store.table('preferential_allottees'))
    tp = t[t['is_primary'].astype('boolean').fillna(False)] if not t.empty else t
    late = (tp[(pd.to_datetime(tp['broadcast_date'], errors='coerce') > ctx.ref - pd.Timedelta(days=365))
               & ((tp.get('insider_filed_late') == True) | (tp.get('company_filed_late') == True))]  # noqa: E712
            if not tp.empty else tp)
    fl = with_flags(pd.DataFrame({'isin': [isin]})) if isin else pd.DataFrame()
    tflags = fl['trade_flags'].iloc[0] if 'trade_flags' in fl else None
    tnotes = (fl['trade_flag_notes'].iloc[0] if 'trade_flag_notes' in fl else None) or tflags
    d_real = d[~d['also_filed'].astype(bool)] if not d.empty else d
    stock_month, mf_ch = store.table('mf_stock_month'), store.table('mf_changes')
    tot_sh = (pd.to_numeric(mine_sh.sort_values('quarter_end')['total_shares'], errors='coerce').dropna()
              if len(mine_sh) and 'total_shares' in mine_sh else pd.Series(dtype=float))
    tot_sh = float(tot_sh.iloc[-1]) if len(tot_sh) else None

    ins = cg.insider_flow(e, ctx.ref)
    fm = cg.fund_month(stock_month, isin)
    mix = cg.ownership_mix(mine_sh)
    delta = cg.mix_delta(mix)
    dflow = cg.deal_flow(d_real, ctx.ref)
    flags = cg.red_flags(pledge, tflags if isinstance(tflags, list) else None, tnotes if isinstance(tnotes, list) else None,
                         len(late), list(cheap.loc[cheap['list'] == 'warn', 'sentence']) if not cheap.empty else [],
                         cg.results_doubts(ctx.results, isin), float(sold['value'].sum()) if not sold.empty else 0.0,
                         pd.to_numeric(sold['pct_of_mcap'], errors='coerce').sum() if not sold.empty else None, enc)
    chips = cg.chips(ins, fm, delta, dflow, flags, _insider_evidence(ins, summary), _month, cg.insider_flow(e, ctx.ref, 365))
    sentence, lean = cg.verdict(chips, flags, dflow)

    # ---- The verdict band: the answer in one sentence, the groups behind it as chips ----
    ds._reset()
    day_note = ''
    if hist and len(hist[1]) >= 2:
        c0, c1 = float(hist[1][-2]), float(hist[1][-1])
        ch_ = (c1 / c0 - 1) * 100
        day_note = f'<span class="{"up" if ch_ > 0 else "down" if ch_ < 0 else ""}">{ch_:+.2f}%</span> on {kit.day(hist[0][-1], with_year=False)}'
    quote = [f'<b class="num">{esc(kit.price(now))}</b> {day_note}' if now else '<b>No price</b> in our NSE/BSE files']
    if pr is not None and pd.notna(pr.get('pct_off_high')):
        quote.append(f'{pr["pct_off_high"] * 100:+.1f}% from the 52-week high')
    if kit._finite(mcap):
        quote.append(f'{esc(kit.rupees(mcap))} market cap' + (f' · {esc(str(pr["mcap_bucket"]))}' if pr is not None and isinstance(pr.get('mcap_bucket'), str) else ''))
    dek = (f'Latest decision: {latest["who"]} ({latest["role"]}) {"bought" if latest["side"] == "BUY" else "sold"} {kit.rupees(latest["value"])} '
           f'on the market, made public {kit.day(latest["seen"])}.' if latest else 'No promoter, director or KMP has traded on the market in our data.')
    st.html(f'<div class="head ds-head co-head"><div class="ds-kicker">{" · ".join(ident)}</div>'
            f'<div class="co-name">{esc(str(name))}</div><div class="co-quote">{" <span class=sep>·</span> ".join(quote)}</div>'
            f'<h1 class="co-verdict {lean}">{esc(sentence)}</h1><p class="ds-dek">{esc(dek)}</p></div>'
            + _chips_html(chips)
            + '<div class="qa-toc"><a href="#co-price">Price and every decision</a><a href="#co-checks">Anything wrong?</a>'
              '<a href="#co-owners">Who owns it?</a><a href="#co-funds">Which funds hold it?</a><a href="#co-growth">Is it growing?</a>'
              '<a href="#co-detail">Every decision</a></div>')

    # ---- 1. The price with every decision on it | the checks ----
    from screens import proto
    left, right = st.container(key='co_g1').columns([5, 3], gap='large')
    with left:
        yr = _year_move(hist)
        proto._qa('What has the price done?', esc(yr) if yr else 'No price history',
                  'Insiders ▲▼ on the day made public, deals of ₹5 Cr and over ■, SAST stake crossings ●, results days shaded. '
                  'Hover a day for who.', 'co-price')
        # decision-makers only (audit 19 Nov 2026: about 30 staff and relatives' sales drew red marks beside "Promoter
        # sales: none"); their trades stay counted under "money by who"
        dm = e[e['person_role'].isin(signals.DECISION_ROLES)] if 'person_role' in e else e
        marks = dm.assign(role=dm['person_role'].map(kit.role))
        chart = lwchart.price_chart(*hist, marks, key=sym, events=_chart_events(ctx, sym, d_real),
                                    bands=_results_days(ctx.results, isin)) if hist else None
        if chart is None:
            st.html('<p class="dt-empty">No price history for this stock in our NSE/BSE price files yet.</p>')
        else:
            st.html(chart, unsafe_allow_javascript=True)
            st.html('<div class="cg-mk"><span><i class="ar up">▲</i>insider buy</span><span><i class="ar down">▼</i>insider sale</span>'
                    '<span><i class="sq up"></i>deal bought</span><span><i class="sq down"></i>deal sold</span>'
                    '<span><i class="ci"></i>SAST crossing</span><span><i class="bd"></i>results day</span></div>')
    with right:
        red = [f for f in flags if f.level == 'fail']
        warn = [f for f in flags if f.level == 'warn']
        proto._qa('Is anything wrong with it?', 'No red flags' if not red and not warn else
                  f'{len(red)} red flag{"s" * (len(red) != 1)}' + (f', {len(warn)} to check' if warn else '') if red else
                  f'No red flags; {len(warn)} to check',
                  'Each check over 12 months, today\'s NSE lists for surveillance.', 'co-checks')
        rows = list(flags)
        if headroom:
            rows.append(cg.Flag('Room to 75%', 'info', f'{headroom.value} · {headroom.note}'))
        st.html(_checks_html(rows))

    # ---- 2. Who owns it and who is moving | which funds hold it ----
    left, right = st.container(key='co_g2').columns(2, gap='large')
    with left:
        _owners(mix, delta, mine_sh)
    with right:
        _funds(fm, mf_ch, stock_month, isin, tot_sh, srow_mf=_snap(sym).get('mf'))

    # ---- 3. Is the business growing | money in and out ----
    left, right = st.container(key='co_g3').columns(2, gap='large')
    with left:
        _growth(ctx.results, isin)
    with right:
        others_ = win[~win['person_role'].isin(list(signals.PROMOTER_ROLES) + ['director', 'kmp'])]
        flows = [('Promoters', prom['signed_value'].sum(), f'{kit.pct(signed_mcap, 2, signed=True)} of the company'),
                 ('Directors and KMP', off['signed_value'].sum(), kit.plural(off['person_id'].nunique(), 'person', 'people')),
                 ('Staff and relatives', others_['signed_value'].sum(), 'not decision-makers'),
                 ('Others in deals', d_real['signed_value'].sum() if not d_real.empty else 0.0, 'bulk/block, market makers out')]
        top = max(flows[:2], key=lambda x: abs(x[1]))
        proto._qa('Who put money in, and who took it out?',
                  (f'{"Promoters" if top[0] == "Promoters" else "Directors"} {"put in" if top[1] > 0 else "took out"} net {esc(kit.rupees(abs(top[1])))}'
                   if top[1] else 'No promoter or director traded'),
                  'Net open-market money over 12 months, each rupee once.', 'co-money')
        st.html(cg_charts.delta_bars([(label, v, note) for label, v, note in flows], fmt=lambda v: kit.rupees(v, signed=True)))

    # ---- 4. Every decision in detail: insiders, deals, stake changes (the topic pages' dense tables), then stories ----
    st.html('<div id="co-detail"></div>')
    # over the page's date range (owner, 19 Nov 2026: "a date selector or a date range selector must be present", PR 291);
    # the range also cuts "Every filing". The glance above keeps its own fixed windows, named on each chip.
    ds.section('Every decision in detail', 'Insider decisions, deals, stake changes and every filing below, over these dates')
    with ds.inside():
        rng = dates.range_picker('company', *dates.bounds(t['broadcast_date'] if 'broadcast_date' in t else None,
                                                          d_all['date'] if not d_all.empty else None, hi=ctx.ref),
                                 default='1y', caption=True)
        # bought against sold over the same dates: decision-makers' open-market trades, and deals by real buyers and sellers
        dmw = e[e['person_role'].isin(signals.DECISION_ROLES) & rng.mask(e['seen'])] if not e.empty else e
        dlr = d_all[rng.mask(d_all['date']) & ~d_all['also_filed'].astype(bool)] if not d_all.empty else d_all
        bars = {'insiders': cg_charts.split_bar(dmw.loc[dmw['side'] == 'BUY', 'value'].sum(), dmw.loc[dmw['side'] == 'SELL', 'value'].sum())
                if not dmw.empty else '',
                'deals': cg_charts.split_bar(dlr.loc[dlr['side'] == 'BUY', 'value'].sum(), dlr.loc[dlr['side'] == 'SELL', 'value'].sum())
                if not dlr.empty else ''}
        proto.company_tables(ctx, isin, sym, rng=rng, bars=bars)
    if other:
        ds.section('Raises, pledges and big holders', '12 months')
        ds.stories(other)

    # ---- The holders by name ----
    pg = store.table('promoter_group')
    if not pg.empty and 'symbol' in pg:
        pg = pg[pg['symbol'].astype(str).str.upper() == sym]
        if not pg.empty:
            ds.section('Who are the promoters?', 'The promoter group named in the latest shareholding pattern')
            last = pg['quarter_end'].max()
            pg = pg[pg['quarter_end'] == last].sort_values('shares', ascending=False)
            rows = [{'m': esc(str(r.get('member_name') or '')), 'c': esc(str(r.get('sub_category') or '')),
                     'p': kit.pct(r.get('pct_of_company'), 2) if kit._finite(r.get('pct_of_company')) is not None else '—',
                     'pl': kit.shares(r.get('pledged_shares')) if kit._finite(r.get('pledged_shares')) else '—'} for r in pg.head(15).to_dict('records')]
            ds.html(ds.sub(f'Promoter group at {kit.day(last)}', f'{kit.plural(len(pg), "member")}, largest first'
                           + (f'; {len(pg) - 15} smaller not listed' if len(pg) > 15 else ''))
                    + ds.list_html(rows, [ds.Col('m', 'Member'), ds.Col('c', 'Category', phone=False), ds.Col('p', '% of company', True),
                                          ds.Col('pl', 'Pledged shares', True, phone=False)]))

    _public_holders(store.table('public_holders'), sym, isin, mine_sh)

    # ---- Every filing, the noise one tap away ----
    tl = _timeline(ctx, sym, t, d_all, raises)
    if not tl.empty:   # inside the range; dates ahead of the data's date (meetings, ex-dates) with a range that runs to it
        ahead = pd.to_datetime(tl['date'], errors='coerce').gt(pd.Timestamp(ctx.ref)) & (rng.end_ts >= pd.Timestamp(ctx.ref))
        tl = tl[rng.mask(tl['date']) | ahead]
    ds.section('Every filing', f'{dates.describe(rng)}, newest first; a row opens to its facts and the filing. Staff trades, ESOPs, '
                               'gifts and transfers are off until picked')
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
            limit=200, height=2800, key=f'co_tlt_{sym}', empty_text=f'No filings for this company, {dates.describe(rng)}.',
            detail=lambda r: facts(r['_facts'], r['_links']))
