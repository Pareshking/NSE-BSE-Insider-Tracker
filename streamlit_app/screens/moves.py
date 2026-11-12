"""Every page's content as 5W-2H stories, from the clean tables (redesign of 12 Nov 2026). The site never cleans: the
rules that decide what is real money stay in insiders_clean/ideas.py and are reused here unchanged; this module only
arranges each decision so the reader does no arithmetic, and counts what it leaves out as noise (`club`).

Builders return (stories, club lines, numbers for the stat strip). They are cached per data day and period.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st
from data import store
from ui import kit
from ui.ds import Story
from ui.kit import esc

from insiders_clean import evidence, ideas, signals
from screens.ctx import split_since, with_flags

INSIDER_SCOPE = 'On the exchange, own money: ESOPs, gifts, transfers inside the group and pledges are not counted'
LATE_DAYS = 14            # made public this many days or more after the last trade: said in amber (as on Today since 23 Oct)
DEAL_MIN_PCT = ideas.FUND_NET_PCT   # a deal shown at 0.25% of the company and up ...
DEAL_MIN_VALUE = ideas.BIG_VALUE    # ... or Rs 25 Cr and up; the rest clubbed
NOT_MARKET = {'esop': 'ESOP allotments and exercises', 'gift': 'gifts', 'off_market': 'off-market and inter-se transfers',
              'preferential': 'preferential allotments (see Raises)', 'pledge': 'pledges (see Risks)', 'pledge_release': 'pledge releases',
              'pledge_invoke': 'pledge invocations', 'scheme': 'schemes of arrangement', 'conversion': 'conversions', 'other': 'other non-market filings'}
# Why a kind matters, where it is not measured on our own history: what the published studies found (docs/PRODUCT.md,
# "What the research found"), or the plain rule. Never our opinion.
WHY = {
    'Promoters pay up': 'Promoters paying at or above market price: positive in an Indian study (Anshuman, Panchapagesan & '
                        'Subrahmanyam 2019); not measured on our data',
    'Cheap shares to promoters': 'Shares to promoters below market: about −8.6% around the event in the same Indian study; an avoid flag',
    'QIP': 'Institutions buying new shares: dilution for holders, priced by the institutions', 'Preferential to others': 'New shares to outside investors: dilution',
    'Rights issue': 'New shares offered to every holder: dilution unless taken up',
    'Buyback at a premium': 'The company buying its own shares above the price now',
    'Pledge created': 'Pledged promoter shares: a crash-risk flag in published studies (Kalia 2024)',
    'Pledge rising': 'Pledged promoter shares: a crash-risk flag in published studies (Kalia 2024)',
    'Pledge invoked': 'A lender sold or took pledged shares: forced selling', 'Pledge released': 'Pledge reduced: less forced-selling risk',
    'Big investor in': 'A holder crossed 5% or added 2%+ (SAST filing)', 'Big investor out': 'A holder fell below 5% or sold 2%+ (SAST filing)',
    'Mutual funds adding': 'Quarterly shareholding filing: a quarter-end change, not a trade this period',
    'Mutual funds trimming': 'Quarterly shareholding filing: a quarter-end change, not a trade this period',
    'Foreign investors adding': 'Quarterly shareholding filing: a quarter-end change, not a trade this period',
    'Foreign investors trimming': 'Quarterly shareholding filing: a quarter-end change, not a trade this period',
}


# ---- Shared pieces -------------------------------------------------------------------------------------------------

def lookups(ctx) -> tuple[dict, dict, dict]:
    """(prices by ISIN, latest shareholding by ISIN, display names by ISIN)."""
    pcols = [c for c in ('isin', 'latest_close', 'market_cap', 'pct_off_high', 'mcap_bucket', 'low_52w', 'high_52w') if c in ctx.prices]
    px = {i: r for i, r in zip(ctx.prices['isin'], ctx.prices[pcols].to_dict('records'))} if not ctx.prices.empty else {}
    hold = {}
    sh = ctx.shareholding
    if sh is not None and not sh.empty and 'isin' in sh:
        s = sh.assign(_q=pd.to_datetime(sh['quarter_end'], errors='coerce')).sort_values('_q')
        cols = [c for c in ('isin', 'quarter_end', 'promoter_holding_pct', 'promoter_pledge_pct', 'total_shares') if c in s]
        hold = {r['isin']: r for r in s[cols].dropna(subset=['isin']).to_dict('records')}
    sec = ctx.securities
    names = (dict(zip(sec['isin'], sec['display_name'])) if sec is not None and not sec.empty and {'isin', 'display_name'} <= set(sec) else {})
    return px, hold, names


def market_line(sym, p: dict | None) -> str:
    """symbol · size · market cap · price · from the 52-week high (trusted HTML)."""
    p = p or {}
    bits = [f'<span class="mono">{esc(str(sym or ""))}</span>'] if sym else []
    if isinstance(p.get('mcap_bucket'), str):
        bits.append(esc(p['mcap_bucket']))
    if kit._finite(p.get('market_cap')):
        bits.append(kit.rupees(p['market_cap']))
    if kit._finite(p.get('latest_close')):
        bits.append(kit.price(p['latest_close']))
    if kit._finite(p.get('pct_off_high')) is not None:
        bits.append(f'{kit.pct(p["pct_off_high"] * 100, 0, signed=True)} from 52W high')
    return ' · '.join(bits)


def watch(isin, p: dict | None, h: dict | None, flags) -> tuple[str, bool]:
    """Pledge, today's tradability flags: the checks a reader would otherwise open a company page for."""
    out, warn = [], False
    pl = (h or {}).get('promoter_pledge_pct')
    if pl is not None and pd.notna(pl):
        out.append(f'{kit.pct(pl, 1)} of promoter shares pledged')
        warn |= pl > signals.HIGH_PLEDGE_PCT
    if isinstance(flags, list) and flags:
        out.append(', '.join(flags))
        warn = True
    elif isinstance(flags, list):
        out.append('no NSE surveillance flag')
    return ' · '.join(out), warn


def record(kind: str, summary) -> tuple[str, str]:
    """(sentence, verdict kind) for a measured kind; ('', '') when the kind is not measured."""
    code = ideas.MEASURED_BY.get(kind)
    if not code:
        return '', ''
    v = evidence.verdict(summary, code)
    if v['kind'] == 'not_measured':
        return 'Not measured on our data yet', 'not_measured'
    return v['text'].replace(evidence.CAVEAT, '').rstrip('.') + ' (under a year of history)', v['kind']


def _flags(isins) -> dict:
    df = with_flags(pd.DataFrame({'isin': list(dict.fromkeys(isins))}))
    return dict(zip(df['isin'], df['trade_flags'])) if 'trade_flags' in df else {}


def _span(a, b) -> str:
    a, b = pd.to_datetime(a, errors='coerce'), pd.to_datetime(b, errors='coerce')
    if pd.isna(b):
        return ''
    if pd.isna(a) or a.normalize() == b.normalize():
        return kit.day(b, with_year=False)
    return f'{a:%d %b}–{b:%d %b}' if a.month != b.month else f'{a:%d}–{b:%d %b}'


def is_new(when, ref) -> bool:
    return ref is not None and pd.notna(when) and pd.Timestamp(when).normalize() >= pd.Timestamp(ref).normalize()


def _paid_now(ctx, isin, avg, trade_to, now) -> tuple[str, float | None]:
    if not kit._finite(avg) or not kit._finite(now):
        return '', None
    f = float(split_since(pd.DataFrame({'isin': [isin], 'trade_date_to': [trade_to]}), ctx.prices).iloc[0])
    if f != f:
        return f'Paid {kit.price(avg)} on average (a split since: not comparable)', None
    paid = avg * f
    move = (now / paid - 1) * 100
    return f'Paid {kit.price(paid)} on average · now {kit.price(now)} · {move:+.1f}%', move


# ---- Insiders: one story per decision-maker and company ------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False, max_entries=8)
def insiders(_ctx, ref_key: str, side: str, days: int, isin: str | None = None) -> tuple:
    """(stories, club lines, stats) for open-market buying or selling by promoters, directors and KMP in the period;
    one company's when `isin` is given (its page)."""
    ctx, ref = _ctx, _ctx.ref
    summary = store.artifact('artifacts/track_summary.parquet')
    px, hold, names = lookups(ctx)
    elig = ctx.eligible if isin is None or ctx.eligible.empty else ctx.eligible[ctx.eligible['isin'] == isin]
    trades = ctx.trades if isin is None or ctx.trades.empty else ctx.trades[ctx.trades['isin'] == isin]
    d = ideas.decisions(elig, ref, side, ctx.shareholding, days)
    if d.empty:
        shown, below = d, d
    else:
        pg = d['promoter_group'].astype(bool)
        keep = ideas._qualifies(d) if side == 'BUY' else (pg & ideas._qualifies(d)) | (~pg & (d['value'] >= ideas.BIG_VALUE))
        shown, below = d[keep], d[~keep]
        shown = shown.sort_values(['value'], ascending=False, kind='stable')
    flags = _flags(shown['isin']) if not shown.empty else {}
    out = []
    verb = 'bought' if side == 'BUY' else 'sold'
    for r in shown.to_dict('records'):
        isin, p, h = r['isin'], px.get(r['isin']), hold.get(r['isin'])
        kind = ('Promoter buying' if r['promoter_group'] else 'Director or KMP buying') if side == 'BUY' else \
            ('Promoter selling' if r['promoter_group'] else 'Director or KMP selling')
        why, verdict = record(kind, summary)
        who = ideas._who(r)
        lag = (pd.Timestamp(r['last']).normalize() - pd.Timestamp(r['trade_to']).normalize()).days if pd.notna(r['trade_to']) else None
        _, move = _paid_now(ctx, isin, r['avg_price'], r['trade_to'], (p or {}).get('latest_close'))
        own = r.get('own_change')
        when = _span(r['trade_from'], r['trade_to'])
        late = lag is not None and lag >= LATE_DAYS
        # One sentence carries who, what, how much and when; one line of numbers; an amber line only when something needs
        # a look (owner, 12 Nov: 5W-2H is a checklist of what to cover, not labels to print; "still busy").
        facts = [f'{own:+.1f}% to their own holding' if side == 'BUY' else f'{own:.1f}% of their own holding'] if own is not None and pd.notna(own) else []
        if move is not None:
            facts.append(f'paid {kit.price(r["avg_price"])} · {move:+.1f}% since')
        if r['days'] > 1:
            facts.append(f'on {r["days"]} trading days')
        w_txt, w_warn = watch(isin, p, h, flags.get(isin))
        note = '; '.join(x for x in ((f'made public {lag} days after the trade' if late else ''), (w_txt if w_warn else '')) if x)
        st_ = Story(
            company=names.get(isin) or r['company'], href=kit.company_href(r['nse_symbol']), market=market_line(r['nse_symbol'], p),
            lede=f'{who} {verb} {r["pct_of_company"]:.2f}% of the company on the market' + (f', {when}' if when else '')
                 + (f' (made public {kit.day(r["last"], with_year=False)})' if not late and pd.notna(r['last']) else ''),
            big=kit.rupees(r['value']), facts=facts, note=note,
            tags=([('New', 'new')] if is_new(r['last'], ref) else []) + ([('Measured ahead', 'ok')] if verdict == 'leaning_positive' else []))
        st_.move = move
        st_.verdict = verdict
        st_.isin = isin
        out.append(st_)
    # What was left out, counted (owner, 12 Nov: club what is not worth showing).
    club = []
    if not below.empty:
        club.append(f'<b>{len(below):,}</b> smaller {"buying" if side == "BUY" else "selling"} {"decision" if len(below) == 1 else "decisions"} by promoters, directors and KMP '
                    + (f'under ₹{ideas.MIN_VALUE / 1e5:.0f} L or {ideas.MIN_PCT:g}% of the company' if side == 'BUY' else
                       f'under the bar (promoters ₹{ideas.MIN_VALUE / 1e5:.0f} L and {ideas.MIN_PCT:g}%; directors and KMP ₹{ideas.BIG_VALUE / 1e7:.0f} Cr)')
                    + f': <b>{kit.rupees(below["value"].sum())}</b> in all, '
                    f'the largest {below["pct_of_company"].max():.3f}% of a company')
    e = elig
    win = e[(e['side'] == side) & (e['seen'] <= ref) & (e['seen'] > ref - pd.Timedelta(days=days))] if not e.empty else e
    if not win.empty:
        staff = win[~win['person_role'].isin(signals.DECISION_ROLES)]
        if len(staff):
            pm = pd.to_numeric(staff['pct_of_mcap'], errors='coerce')
            club.append(f'<b>{len(staff):,}</b> {"trade" if len(staff) == 1 else "trades"} by designated persons, employees and relatives in '
                        f'<b>{staff["isin"].nunique():,}</b> {"company" if staff["isin"].nunique() == 1 else "companies"}: <b>{kit.rupees(pd.to_numeric(staff["value"], errors="coerce").sum())}</b>, '
                        f'the largest {pm.max():.3f}% of a company' if pm.notna().any() else '')
        if side == 'BUY' and 'is_token' in win:
            tok = win[win['is_token'].astype('boolean').fillna(False) & win['person_role'].isin(signals.DECISION_ROLES)]
            if len(tok):
                club.append(f'<b>{len(tok):,}</b> token buys (under ₹25 L in companies above ₹5,000 Cr): '
                            f'<b>{kit.rupees(pd.to_numeric(tok["value"], errors="coerce").sum())}</b>')
    t = trades
    if not t.empty:
        seen = pd.to_datetime(t['broadcast_date'], errors='coerce')
        nm = t[t['is_primary'].astype('boolean').fillna(False) & ~t['is_market'].astype('boolean').fillna(False)
               & (seen <= ref + pd.Timedelta(days=1)) & (seen > ref - pd.Timedelta(days=days))]
        if side == 'SELL' and len(nm):   # once, on the selling side of the page
            for k, n in nm['kind'].fillna('other').value_counts().items():
                club.append(f'<b>{n:,}</b> {esc(NOT_MARKET.get(k, str(k).replace("_", " ")))}: not a decision to buy or sell on the market')
    stats = {'n': len(out), 'value': float(shown['value'].sum()) if not shown.empty else 0.0,
             'companies': int(shown['isin'].nunique()) if not shown.empty else 0}
    return out, club, stats


# ---- Deals: who sold, who took it, as one story per company and day ------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False, max_entries=6)
def deals(_ctx, ref_key: str, days: int, isin: str | None = None) -> tuple:
    ctx, ref = _ctx, _ctx.ref
    summary = store.artifact('artifacts/track_summary.parquet')
    px, hold, names = lookups(ctx)
    dl = ctx.deals if isin is None or ctx.deals is None or ctx.deals.empty else ctx.deals[ctx.deals['isin'] == isin]
    if dl is None or dl.empty:
        return [], [], {'n': 0, 'value': 0.0, 'companies': 0}
    prim = dl['is_primary'].astype('boolean').fillna(False)
    mm = dl['client_is_market_maker'].astype('boolean').fillna(False)
    when = pd.to_datetime(dl['date'], errors='coerce')
    inwin = (when <= ref) & (when > ref - pd.Timedelta(days=days))
    real = dl[prim & ~mm & inwin].dropna(subset=['isin']).copy()
    n_mm = int((prim & mm & inwin).sum())
    if real.empty:
        return [], ([f'<b>{n_mm:,}</b> market-maker legs (they buy and sell in equal measure)'] if n_mm else []), {'n': 0, 'value': 0.0, 'companies': 0}
    real['_q'] = pd.to_numeric(real['quantity'], errors='coerce')
    real['_v'] = pd.to_numeric(real['value'], errors='coerce')
    real['_day'] = pd.to_datetime(real['date'], errors='coerce').dt.normalize()
    out, small = [], []
    for (isin, day), g in real.groupby(['isin', '_day'], sort=False):
        total = (hold.get(isin) or {}).get('total_shares')
        bq, sq = g.loc[g['side'] == 'BUY', '_q'].sum(), g.loc[g['side'] == 'SELL', '_q'].sum()
        bv, sv = g.loc[g['side'] == 'BUY', '_v'].sum(), g.loc[g['side'] == 'SELL', '_v'].sum()
        pct = max(bq, sq) / total * 100 if total and total > 0 else pd.to_numeric(g['pct_of_mcap'], errors='coerce').abs().max()
        value = max(bv, sv)
        if not ((pct is not None and pd.notna(pct) and pct >= DEAL_MIN_PCT) or value >= DEAL_MIN_VALUE):
            small.append(value)
            continue
        out.append((isin, day, g, pct, value, bv, sv, bq, sq, total))
    out.sort(key=lambda x: -x[4])
    flags = _flags([x[0] for x in out]) if out else {}
    stories = []

    def party(g, side):
        x = g[g['side'] == side]
        if x.empty:
            return []
        by = x.groupby('client_name', sort=False).agg(v=('_v', 'sum'), q=('_q', 'sum'), t=('client_type', 'first'),
                                                     prom=('client_is_promoter', 'any')).sort_values('v', ascending=False)
        return [(n, r['v'], r['q'], ('promoter' if r['prom'] else str(r['t'] or '').replace('_', ' '))) for n, r in by.iterrows()]

    for isin, day, g, pct, value, bv, sv, bq, sq, total in out:
        p, h = px.get(isin), hold.get(isin)
        sym = g['nse_symbol'].dropna().iloc[0] if g['nse_symbol'].notna().any() else None
        buyers, sellers = party(g, 'BUY'), party(g, 'SELL')

        def names_of(lst):
            return ', '.join(f'{n} ({t})' if t and t != 'nan' else n for n, _, _, t in lst[:3]) + (f' and {len(lst) - 3} more' if len(lst) > 3 else '')
        sh = lambda q: f'{q / total * 100:.2f}% of the company' if total and total > 0 else kit.shares(q) + ' shares'  # noqa: E731
        if sellers and buyers:
            lede = f'{sellers[0][0]} sold {sh(sq)}; {buyers[0][0]} bought {sh(buyers[0][2])}' + (f' and {len(buyers) - 1} others took the rest' if len(buyers) > 1 else '')
        elif sellers:
            lede = f'{sellers[0][0]} sold {sh(sq)}' + (f' with {len(sellers) - 1} other sellers' if len(sellers) > 1 else '') + '; the buyers were under the reporting size'
        else:
            lede = f'{buyers[0][0]} bought {sh(bq)}' + (f' with {len(buyers) - 1} other buyers' if len(buyers) > 1 else '') + '; the sellers were under the reporting size'
        avg = (bv + sv) / (bq + sq) if (bq + sq) else None
        now = (p or {}).get('latest_close')
        price = ''
        if kit._finite(avg) and kit._finite(now):
            f = float(split_since(pd.DataFrame({'isin': [isin], 'trade_date_to': [day]}), ctx.prices).iloc[0])
            if f == f:
                price = f'Deal price {kit.price(avg * f)} · now {kit.price(now)} · {(now / (avg * f) - 1) * 100:+.1f}%'
        prom_sold = any(t == 'promoter' for *_, t in sellers)
        fund_bought = any(t in ('mutual fund', 'insurer', 'foreign portfolio investor', 'foreign investor') for *_, t in buyers)
        why = []
        if prom_sold:
            why.append('A promoter selling through a deal: money out of the promoters')
        if fund_bought:
            rec, _ = record('Fund buying', summary)
            why.append('Funds buying in deals: ' + (rec[0].lower() + rec[1:] if rec else 'not measured'))
        w_txt, w_warn = watch(isin, p, h, flags.get(isin))
        feeds = ', '.join(sorted({str(x).lower() for x in g['feeds'].dropna()})) or 'bulk'
        exch = ', '.join(sorted({str(x).upper() for x in g['exchange'].dropna()}))
        facts = [x for x in (price.replace('Deal price ', 'at ').replace(' · now ', ', now ') if price else '',
                             f'{feeds} deal on {exch}' if exch else f'{feeds} deal', kit.day(day, with_year=False)) if x]
        stories.append(Story(
            company=names.get(isin) or str(g['company'].iloc[-1]), href=kit.company_href(sym) if sym else '', market=market_line(sym, p),
            lede=lede, big=kit.rupees(value), facts=facts, note=w_txt if w_warn else '',
            tags=([('New', 'new')] if is_new(day, ref) else []) + ([('Promoter sold', 'warn')] if prom_sold else [])))
    club = []
    if small:
        club.append(f'<b>{len(small):,}</b> smaller deals (under {DEAL_MIN_PCT:g}% of the company and ₹{DEAL_MIN_VALUE / 1e7:.0f} Cr): '
                    f'<b>{kit.rupees(sum(small))}</b> in all')
    if n_mm:
        club.append(f'<b>{n_mm:,}</b> market-maker legs: they buy and sell in equal measure, not a view on the company')
    return stories, club, {'n': len(stories), 'value': float(sum(x[4] for x in out)), 'companies': len({x[0] for x in out})}


# ---- Every other kind (raises, buybacks, pledges, holders): the ideas events, as stories -----------------------------

@st.cache_data(ttl=3600, show_spinner=False, max_entries=8)
def events(_ctx, ref_key: str, days: int) -> pd.DataFrame:
    """Every ideas event of the period with its kind (not one per company: each event is its own story)."""
    from screens.ctx import issue_rows, qip_rows, rights_rows
    from screens import buybacks
    ctx, ref, sh = _ctx, _ctx.ref, _ctx.shareholding
    issues = issue_rows(ctx.preferential, ctx.prices) if ctx.preferential is not None and not ctx.preferential.empty else None
    qip, rights = qip_rows(store.table('qip'), ctx.prices), rights_rows(ctx.rights, ctx.prices)
    bb = buybacks.rows(store.table('buybacks'), ctx.prices, ctx.meetings)
    parts = [ideas.pledge_events(ctx.trades, ref, sh, days=days, enc=ctx.encumbrances), ideas.stake_events(ctx.sast, ref, days=days),
             ideas.issue_events(issues, ref, sh, days=days, allottees=store.table('preferential_allottees')),
             ideas.buyback_events(bb, ref, sh, days=days), ideas.raise_events(issues, qip, rights, ref, sh, days=days),
             ideas.holder_events(store.snapshot(), ref, days=days)]
    parts = [x for x in parts if x is not None and not x.empty]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=ideas.EVENT_COLS)


def event_stories(ctx, ev: pd.DataFrame, kinds: set, summary=None) -> list[Story]:
    """One story per event of `kinds`, largest share of the company first."""
    if ev is None or ev.empty:
        return []
    px, hold, names = lookups(ctx)
    x = ev[ev['kind'].isin(kinds)].dropna(subset=['isin'])
    if x.empty:
        return []
    x = x.assign(_p=pd.to_numeric(x['pct_of_company'], errors='coerce')).sort_values(['_p', 'last'], ascending=[False, False], na_position='last')
    flags = _flags(x['isin'])
    out = []
    for r in x.to_dict('records'):
        isin, p, h = r['isin'], px.get(r['isin']), hold.get(r['isin'])
        pct = r['_p'] if pd.notna(r['_p']) and r['_p'] else None
        mcap = (p or {}).get('market_cap')
        if kit._finite(r.get('value')):
            much, big = kit.rupees(r['value']) + ' as filed', kit.rupees(r['value'])
        elif pct and kit._finite(mcap):
            much, big = f'about {kit.rupees(pct / 100 * mcap)}: the shares at today\'s market cap (no amount filed)', '≈ ' + kit.rupees(pct / 100 * mcap)
        else:
            much, big = '', ''
        if pct:
            much += (' · ' if much else '') + f'{pct:.2f}% of the company'
        third = (f'{r["kv3_label"]}: {r["kv3"]}' if isinstance(r.get('kv3_label'), str) and isinstance(r.get('kv3'), str)
                 and r['kv3'].strip() not in ('', '—', '-') else '')   # a number not known is left out, not shown as a dash
        rec, verdict = record(r['kind'], summary)
        w_txt, w_warn = watch(isin, p, h, flags.get(isin))
        facts = [x for x in (third, (f'{pct:.2f}% of the company' if pct else ''),
                             (kit.day(r['last'], with_year=False) if pd.notna(r.get('last')) else '')) if x]
        out.append(Story(
            company=names.get(isin) or str(r['company']), href=kit.company_href(r['nse_symbol']) if isinstance(r.get('nse_symbol'), str) else '',
            market=market_line(r.get('nse_symbol'), p), lede=str(r['sentence']), big=big, facts=facts, note=w_txt if w_warn else '',
            tags=([('New', 'new')] if is_new(r.get('last'), ctx.ref) else []) + ([('Measured ahead', 'ok')] if verdict == 'leaning_positive' else [])))
        out[-1].kind = r['kind']
    return out


def upcoming(ctx, days: int = 60) -> list[tuple[str, list[str]]]:
    """Money events ahead, by day: board meetings on fund raising or a buyback, tender closes, lock-ins ending."""
    from screens import filings_all
    _, up = filings_all._upcoming(ctx, ctx.ref, filings_all._names(ctx))
    if up is None or up.empty:
        return []
    day0 = pd.Timestamp(ctx.ref).normalize()
    up = up.assign(_d=pd.to_datetime(up['made_public'], errors='coerce').dt.normalize())
    up = up[(up['_d'] > day0 - pd.Timedelta(days=1)) & (up['_d'] <= day0 + pd.Timedelta(days=days))].sort_values('_d', kind='stable')
    out = []
    for d, g in up.groupby('_d', sort=True):
        items = []
        for r in g.to_dict('records'):
            sym = r.get('nse_symbol')
            name = esc(str(r.get('company') or sym or ''))
            link = f'<a href="{esc(kit.company_href(sym), quote=True)}" target="_self">{name}</a>' if isinstance(sym, str) and sym else f'<b>{name}</b>'
            size = kit.rupees(r['value']) if kit._finite(r.get('value')) else ''
            detail = str(r.get('what_sub') or '')[:90]
            items.append(link + f'<span>{esc(str(r.get("what") or ""))}' + (f' · {esc(size)}' if size else '') + (f' · {esc(detail)}' if detail else '') + '</span>')
        out.append((pd.Timestamp(d).strftime('%a %d %b'), items))
    return out
