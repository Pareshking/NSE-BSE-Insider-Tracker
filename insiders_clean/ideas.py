"""Today's two short lists (redesign of 21 Oct 2026, docs/REVAMP_PLAN.md and the
blueprint the owner approved): "Worth a look", at most 10 companies where people
with skin in the game bought on the market at a size that matters, and "Watch
out", at most 5 where they sold or pledged.

Rules (owner, 21 Oct):
* Who: one decision-maker per promoter group (every filer filed as Promoter or
  Promoter Group, plus members named in the shareholding pattern), otherwise per
  person (signals.decision_makers). Tranches over the window are combined, so a
  promoter buying Rs 1 lakh a day is seen as the steady buyer they are.
* Size floor, per decision-maker over WINDOW days: at least MIN_VALUE and
  MIN_PCT of the company; or ALONE_PCT of the company whatever the rupees; or
  buying on STEADY_DAYS separate days (steady accumulation).
* Gate: an idea is shown only while one of its signals has an "ahead" early read
  in the measured track record, or is not measured yet but is supported by
  published studies (STUDIES). A kind that has done worse than the index stays
  searchable in Filings, never on Today.
* Order: % of the company bought (shares over total shares from the shareholding
  XBRL where filed, else value over market cap at the trade), then the latest.
No score is shown: each idea carries its reasons.
"""
from __future__ import annotations

import pandas as pd

from . import evidence, signals

WINDOW = 90
MIN_VALUE = 25e5        # Rs 25 lakh
MIN_PCT = 0.05          # % of the company
ALONE_PCT = 0.25        # qualifies on its own, for a company too small for Rs 25 lakh to mean much
STEADY_DAYS = 10        # separate buying days in the window
MAX_IDEAS, MAX_WARNINGS = 10, 5
PLEDGE_RISE_PTS = 5.0   # pledge up this many points of promoter shares in the latest quarter
# Signal kinds -> the track-record signal that measures them; STUDIES: supported by published work
# (docs/PRODUCT.md, research) and so shown while not yet measured here.
MEASURED_BY = {'Promoter buying': 'promoter_buy', 'Director or KMP buying': 'officer_buy', 'Cluster': 'cluster',
               'Spotlight': 'spotlight', 'Promoter selling': 'promoter_sell'}
STUDIES = {'promoter_buy', 'officer_buy', 'cluster'}


def _shares_out(sh: pd.DataFrame | None) -> dict:
    """ISIN -> total shares in the latest shareholding XBRL."""
    if sh is None or sh.empty or 'total_shares' not in sh:
        return {}
    s = sh.dropna(subset=['isin']).assign(total=pd.to_numeric(sh['total_shares'], errors='coerce'))
    s = s.dropna(subset=['total']).sort_values('quarter_end').drop_duplicates('isin', keep='last')
    return dict(zip(s['isin'], s['total']))


def decisions(t: pd.DataFrame, ref: pd.Timestamp, side: str, sh: pd.DataFrame | None = None,
              days: int = WINDOW) -> pd.DataFrame:
    """One row per company and decision-maker who bought (or sold) on the market in the window: who,
    value, shares, % of the company, buying days, first and last day made public, average price."""
    w = t[(t['side'] == side) & t['person_role'].isin(signals.DECISION_ROLES) & (t['seen'] <= ref)
          & (t['seen'] > ref - pd.Timedelta(days=days))].dropna(subset=['isin', 'person_id'])
    if side == 'BUY' and 'is_token' in w:
        w = w[~w['is_token'].astype('boolean').fillna(False)]
    if w.empty:
        return pd.DataFrame()
    out = []
    total = _shares_out(sh)
    for isin, g in w.groupby('isin'):
        people = g.drop_duplicates('person_id')
        dm = signals.decision_makers(people)
        g = g.assign(dm=g['person_id'].map(dm))
        for key, x in g.groupby('dm'):
            roles = set(x['person_role'])
            group = bool(roles & set(signals.PROMOTER_ROLES)) or (
                'promoter_group_id' in x and x['promoter_group_id'].map(lambda v: isinstance(v, str) and bool(v)).any())
            shares = pd.to_numeric(x['quantity'], errors='coerce').sum()
            value = pd.to_numeric(x['value'], errors='coerce').sum()
            pct = (shares / total[isin] * 100) if total.get(isin) else pd.to_numeric(x['pct_of_mcap'], errors='coerce').sum()
            trade_days = pd.to_datetime(x['trade_date_to'], errors='coerce').dt.normalize().nunique()
            out.append({'isin': isin, 'company': x['company'].iloc[-1], 'nse_symbol': x['nse_symbol'].iloc[-1],
                        'dm': key, 'promoter_group': group, 'roles': sorted(roles),
                        'people': x['person_name'].drop_duplicates().tolist(), 'value': value, 'shares': shares,
                        'pct_of_company': pct, 'pct_basis': 'shares' if total.get(isin) else 'value',
                        'days': int(trade_days), 'first': x['seen'].min(), 'last': x['seen'].max(),
                        'trade_from': pd.to_datetime(x['trade_date_from'], errors='coerce').min(),
                        'trade_to': pd.to_datetime(x['trade_date_to'], errors='coerce').max(),
                        'avg_price': value / shares if shares else None, 'filings': len(x)})
    return pd.DataFrame(out)


def _qualifies(d: pd.DataFrame) -> pd.Series:
    return (((d['value'] >= MIN_VALUE) & (d['pct_of_company'] >= MIN_PCT)) | (d['pct_of_company'] >= ALONE_PCT)
            | (d['days'] >= STEADY_DAYS))


def _who(r) -> str:
    if r['promoter_group']:
        n = len(r['people'])
        return 'Promoter group' + (f' ({n} entities)' if n > 1 else f' ({r["people"][0]})')
    role = signals.ROLE_WORDS.get(r['roles'][0], 'insider') if r['roles'] else 'insider'
    return f'{role[:1].upper() + role[1:]} {r["people"][0]}'


def _when(r) -> str:
    a, b = r['trade_from'], r['trade_to']
    if pd.isna(b):
        return ''
    if r['days'] >= STEADY_DAYS:
        return f'on {r["days"]} days since {a:%d %b}'
    return f'{a:%d %b}' if pd.isna(a) or a.normalize() == b.normalize() else (
        f'{a:%d}–{b:%d %b}' if a.month == b.month else f'{a:%d %b}–{b:%d %b}')


def _verdicts(summary: pd.DataFrame | None) -> dict:
    return {k: evidence.verdict(summary, v)['kind'] for k, v in MEASURED_BY.items()}


def _passes(kinds: list[str], verdicts: dict) -> bool:
    for k in kinds:
        sig, v = MEASURED_BY.get(k), verdicts.get(k)
        if sig and (v == 'leaning_positive' or (v in ('not_measured', 'few') and sig in STUDIES)):
            return True
    return False


def worth_a_look(t: pd.DataFrame, ref: pd.Timestamp, sh: pd.DataFrame | None = None,
                 summary: pd.DataFrame | None = None, limit: int = MAX_IDEAS) -> pd.DataFrame:
    """At most `limit` companies, one row each: the sentence, the size, the reasons (`kinds`), the
    decision-makers behind it. `t` is the eligible insider table (signals.eligible)."""
    d = decisions(t, ref, 'BUY', sh)
    if d.empty:
        return d
    d = d[_qualifies(d)]
    if d.empty:
        return d
    clus = set(signals.clusters(t, ref)['isin']) if not t.empty else set()
    spot = set(signals.spotlight(t, ref)['isin']) if not t.empty else set()
    verdicts = _verdicts(summary)
    rows = []
    for isin, g in d.groupby('isin'):
        g = g.sort_values('pct_of_company', ascending=False)
        top = g.iloc[0]
        kinds = (['Promoter buying'] if g['promoter_group'].any() else []) \
            + (['Director or KMP buying'] if (~g['promoter_group'] & g['roles'].map(lambda r: bool(set(r) & {'director', 'kmp'}))).any() else []) \
            + (['Cluster'] if isin in clus else []) + (['Spotlight'] if isin in spot else []) \
            + (['Steady accumulation'] if (g['days'] >= STEADY_DAYS).any() else [])
        if not _passes(kinds, verdicts):
            continue
        pct = g['pct_of_company'].sum()
        lead = _who(top) if len(g) == 1 else f'{_who(top)} and {len(g) - 1} more'
        rows.append({'isin': isin, 'company': top['company'], 'nse_symbol': top['nse_symbol'],
                     'sentence': f'{lead} bought {pct:.2f}% of the company on the market{", " + _when(top) if _when(top) else ""}',
                     'pct_of_company': pct, 'pct_basis': top['pct_basis'], 'value': g['value'].sum(),
                     'avg_price': g['value'].sum() / g['shares'].sum() if g['shares'].sum() else None,
                     'trade_to': g['trade_to'].max(), 'last': g['last'].max(), 'kinds': kinds,
                     'decision_makers': len(g), 'reads': {k: verdicts.get(k) for k in kinds if k in MEASURED_BY}})
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values(['pct_of_company', 'last'], ascending=[False, False]).head(limit).reset_index(drop=True)


def watch_out(t: pd.DataFrame, ref: pd.Timestamp, sh: pd.DataFrame | None = None,
              limit: int = MAX_WARNINGS) -> pd.DataFrame:
    """At most `limit` companies where promoters sold past the same floors, or pledged 5+ points more
    of their shares in the latest quarter: the sentence and the size, largest first."""
    rows = []
    d = decisions(t, ref, 'SELL', sh)
    if not d.empty:
        d = d[d['promoter_group'] & _qualifies(d)]
        for isin, g in d.groupby('isin'):
            pct = g['pct_of_company'].sum()
            top = g.sort_values('pct_of_company').iloc[-1]
            rows.append({'isin': isin, 'company': top['company'], 'nse_symbol': top['nse_symbol'], 'kind': 'Promoter selling',
                         'sentence': f'{_who(top)} sold {pct:.2f}% of the company on the market{", " + _when(top) if _when(top) else ""}',
                         'size': pct, 'value': g['value'].sum(), 'last': g['last'].max()})
    if sh is not None and not sh.empty and 'promoter_pledge_pct' in sh:
        s = sh.dropna(subset=['isin']).assign(pl=pd.to_numeric(sh['promoter_pledge_pct'], errors='coerce'),
                                              q=pd.to_datetime(sh['quarter_end'], errors='coerce')).sort_values('q')
        for isin, g in s.groupby('isin'):
            g = g.dropna(subset=['pl']).drop_duplicates('q', keep='last')
            if len(g) < 2:
                continue
            a, b = g.iloc[-2], g.iloc[-1]
            if b['pl'] - a['pl'] >= PLEDGE_RISE_PTS:
                rows.append({'isin': isin, 'company': b.get('company') or b.get('symbol'), 'nse_symbol': b.get('symbol'),
                             'kind': 'Pledge rising',
                             'sentence': f'Promoters pledged {b["pl"]:.1f}% of their shares, up from {a["pl"]:.1f}% a quarter earlier',
                             'size': b['pl'] - a['pl'], 'value': None, 'last': b['q']})
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    # One measure per order (audit W17): sales first, by % of the company; then pledge rises, by points.
    out['_k'] = (out['kind'] != 'Promoter selling').astype(int)
    out = out.sort_values(['_k', 'size', 'last'], ascending=[True, False, False]).drop_duplicates('isin')
    return out.drop(columns='_k').head(limit).reset_index(drop=True)


# --- Every other kind of filing, across the whole market (owner, 21 Oct: "one can not see 5000 company
# pages to find other details"). Each builder returns events with the same fields; `today()` merges them
# with the insider buys and sales into the two lists, one row per company, one size measure (% of the
# company), the company led by its largest event and every kind shown as a chip.
EVENT_COLS = ['isin', 'company', 'nse_symbol', 'list', 'kind', 'pct_of_company', 'sentence', 'value', 'last',
              'avg_price', 'trade_to', 'decision_makers']
BIG_STAKE = 5.0          # SAST Reg 29(1): crossing 5%
BIG_CHANGE = 2.0         # SAST Reg 29(2): a change of 2% or more
FUND_NET_PCT = 0.25      # funds' net bulk/block buying or selling, % of the company, 30 days
ISSUE_PREMIUM = 0.0      # promoters paying at or above today's price
BUYBACK_PREMIUM = 10.0   # tender offer at least 10% above today's price
MEASURED_BY.update({'Fund buying': 'fund_deal_buy'})


def _ev(rows) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=EVENT_COLS)


def _filings(n: int) -> str:
    return f'{n} filing' + ('' if n == 1 else 's')


def _in_window(when: pd.Series, ref: pd.Timestamp, days: int) -> pd.Series:
    return (when <= ref + pd.Timedelta(days=1)) & (when > ref - pd.Timedelta(days=days))


def insider_events(t, ref, sh=None, summary=None) -> pd.DataFrame:
    """Insider buys (Worth a look) and promoter sales (Watch out), from the two lists above."""
    rows = []
    look = worth_a_look(t, ref, sh, summary, limit=10_000)
    for r in look.to_dict('records') if not look.empty else []:
        for k in r['kinds']:
            rows.append({'isin': r['isin'], 'company': r['company'], 'nse_symbol': r['nse_symbol'], 'list': 'look',
                         'kind': k, 'pct_of_company': r['pct_of_company'], 'sentence': r['sentence'], 'value': r['value'],
                         'last': r['last'], 'avg_price': r['avg_price'], 'trade_to': r['trade_to'],
                         'decision_makers': r['decision_makers']})
    warn = watch_out(t, ref, sh, limit=10_000)
    for r in warn.to_dict('records') if not warn.empty else []:
        if r['kind'] == 'Promoter selling':
            rows.append({'isin': r['isin'], 'company': r['company'], 'nse_symbol': r['nse_symbol'], 'list': 'warn',
                         'kind': r['kind'], 'pct_of_company': r['size'], 'sentence': r['sentence'], 'value': r['value'],
                         'last': r['last']})
    return _ev(rows)


def pledge_events(trades: pd.DataFrame, ref: pd.Timestamp, sh=None, days: int = WINDOW) -> pd.DataFrame:
    """Promoters pledging (Watch out) or releasing a pledge (Worth a look): the PIT filings of the window,
    and the latest quarter's change of 5+ points in the shareholding XBRL. Size: shares over total shares."""
    rows = []
    total = _shares_out(sh)
    if trades is not None and not trades.empty and 'kind' in trades:
        t = trades[trades['is_primary'].astype('boolean').fillna(False) & ~trades['needs_review'].astype('boolean').fillna(False)
                   & trades['person_role'].isin(signals.PROMOTER_ROLES)].copy()
        t['seen'] = pd.to_datetime(t['broadcast_date'], errors='coerce')
        t = t[_in_window(t['seen'], ref, days)]
        for kind, lst, word in (('pledge_create', 'warn', 'pledged'), ('pledge_revoke', 'look', 'released a pledge on')):
            for isin, g in t[t['kind'] == kind].dropna(subset=['isin']).groupby('isin'):
                q = pd.to_numeric(g['quantity'], errors='coerce').sum()
                pct = q / total[isin] * 100 if total.get(isin) else None
                if pct is None or pct < MIN_PCT:
                    continue
                rows.append({'isin': isin, 'company': g['company'].iloc[-1], 'nse_symbol': g['nse_symbol'].iloc[-1], 'list': lst,
                             'kind': 'Pledge created' if lst == 'warn' else 'Pledge released', 'pct_of_company': pct,
                             'sentence': f'Promoters {word} {pct:.2f}% of the company ({_filings(len(g))})',
                             'value': None, 'last': g['seen'].max()})
    if sh is not None and not sh.empty and {'promoter_pledged_shares', 'total_shares', 'promoter_pledge_pct'} <= set(sh.columns):
        s = sh.dropna(subset=['isin']).assign(q=pd.to_datetime(sh['quarter_end'], errors='coerce'),
                                              pl=pd.to_numeric(sh['promoter_pledge_pct'], errors='coerce'),
                                              ps=pd.to_numeric(sh['promoter_pledged_shares'], errors='coerce'),
                                              ts=pd.to_numeric(sh['total_shares'], errors='coerce')).sort_values('q')
        for isin, g in s.groupby('isin'):
            g = g.dropna(subset=['pl']).drop_duplicates('q', keep='last')
            if len(g) < 2:
                continue
            a, b = g.iloc[-2], g.iloc[-1]
            move = b['pl'] - a['pl']
            if abs(move) < PLEDGE_RISE_PTS or not b['ts']:
                continue
            pct = abs(b['ps'] - a['ps']) / b['ts'] * 100 if pd.notna(b['ps']) and pd.notna(a['ps']) else 0.0
            direction = 'up' if move > 0 else 'down'
            rows.append({'isin': isin, 'company': b.get('company') or b.get('symbol'), 'nse_symbol': b.get('symbol'),
                         'list': 'warn' if move > 0 else 'look', 'kind': 'Pledge rising' if move > 0 else 'Pledge released',
                         'pct_of_company': pct,
                         'sentence': f'Promoters pledged {b["pl"]:.1f}% of their shares at {b["q"]:%b %Y}, '
                                     f'{direction} from {a["pl"]:.1f}% a quarter earlier',
                         'value': None, 'last': b['q']})
    return _ev(rows)


def stake_events(sast: pd.DataFrame | None, ref: pd.Timestamp, days: int = WINDOW) -> pd.DataFrame:
    """Big investors (not promoters) crossing 5% or adding 2%+ (Worth a look), or selling 2%+ or falling
    below 5% (Watch out), from SAST Reg 29 disclosures. Size: the % of the company they bought or sold."""
    if sast is None or sast.empty or 'isin' not in sast:
        return _ev([])
    s = sast[~sast['is_promoter'].astype('boolean').fillna(False)].copy()
    when = pd.to_datetime(s['broadcast_date'], errors='coerce') if 'broadcast_date' in s else pd.Series(pd.NaT, index=s.index)
    if 'transaction_date' in s:
        when = when.fillna(pd.to_datetime(s['transaction_date'], errors='coerce'))
    s['when'] = when
    s = s[_in_window(s['when'], ref, days)].dropna(subset=['isin'])
    rows = []
    for r in s.to_dict('records'):
        bought = pd.to_numeric(r.get('pct_acquired'), errors='coerce')
        sold = pd.to_numeric(r.get('pct_sold'), errors='coerce')
        after = pd.to_numeric(r.get('post_stake_pct'), errors='coerce')
        name = str(r.get('acquirer_name') or 'An investor')
        holds = f', now holds {after:.2f}%' if pd.notna(after) else ''
        base = {'isin': r['isin'], 'company': r.get('company') or r.get('symbol'), 'nse_symbol': r.get('symbol'),
                'value': None, 'last': r['when']}
        if pd.notna(bought) and bought > 0 and (bought >= BIG_CHANGE or (pd.notna(after) and after >= BIG_STAKE > after - bought)):
            rows.append({**base, 'list': 'look', 'kind': 'Big investor in', 'pct_of_company': float(bought),
                         'sentence': f'{name} bought {bought:.2f}% of the company{holds}'})
        elif pd.notna(sold) and sold > 0 and (sold >= BIG_CHANGE or (pd.notna(after) and after < BIG_STAKE <= after + sold)):
            rows.append({**base, 'list': 'warn', 'kind': 'Big investor out', 'pct_of_company': float(sold),
                         'sentence': f'{name} sold {sold:.2f}% of the company{holds}'})
    return _ev(rows)


def fund_events(deals: pd.DataFrame | None, trades: pd.DataFrame | None, ref: pd.Timestamp, days: int = 30) -> pd.DataFrame:
    """Funds' net buying (Worth a look) or selling (Watch out) in bulk/block deals over `days`: institutional
    client types only (insiders_clean/participants.py), market makers out, a deal that is an insider's own
    filed trade left to the insider lists. Size: net % of the company."""
    if deals is None or deals.empty or 'client_type' not in deals:
        return _ev([])
    d = deals[deals['is_primary'].astype('boolean').fillna(False) & ~deals['client_is_market_maker'].astype('boolean').fillna(False)
              & deals['client_type'].isin(signals.FUND_TYPES)].copy()
    d['date'] = pd.to_datetime(d['date'], errors='coerce')
    d = d[(d['date'] <= ref) & (d['date'] > ref - pd.Timedelta(days=days))].dropna(subset=['isin'])
    if trades is not None and not trades.empty and len(d):
        d = d[~signals.deals_also_filed(d, trades)]
    if d.empty:
        return _ev([])
    sign = d['side'].map({'BUY': 1, 'SELL': -1})
    d = d.assign(net_pct=pd.to_numeric(d['pct_of_mcap'], errors='coerce') * sign,
                 net_val=pd.to_numeric(d['value'], errors='coerce') * sign)
    rows = []
    for isin, g in d.groupby('isin'):
        net = g['net_pct'].sum()
        if abs(net) < FUND_NET_PCT:
            continue
        side = 'BUY' if net > 0 else 'SELL'
        names = g.loc[g['side'] == side, 'client_name'].drop_duplicates().tolist()
        lead = (names[0] + (f' and {len(names) - 1} more' if len(names) > 1 else '')) if names else 'Funds'
        verb = 'bought' if net > 0 else 'sold'
        rows.append({'isin': isin, 'company': g['company'].iloc[-1], 'nse_symbol': g['nse_symbol'].iloc[-1],
                     'list': 'look' if net > 0 else 'warn', 'kind': 'Fund buying' if net > 0 else 'Funds selling',
                     'pct_of_company': abs(net),
                     'sentence': f'{lead} {verb} a net {abs(net):.2f}% of the company in bulk/block deals',
                     'value': abs(g['net_val'].sum()), 'last': g['date'].max()})
    return _ev(rows)


def issue_events(issues: pd.DataFrame | None, ref: pd.Timestamp, sh=None, days: int = WINDOW) -> pd.DataFrame:
    """Preferential shares or warrants to promoters at or above today's price (Worth a look: promoters pay
    up) or below it (Watch out: cheap shares to themselves). `issues` is screens.ctx.issue_rows output, whose
    `vs_market` puts the offer on today's split basis against today's close. Size: shares allotted (or
    proposed) over total shares."""
    if issues is None or issues.empty or 'vs_market' not in issues or 'allottee_category' not in issues:
        return _ev([])
    total = _shares_out(sh)
    s = issues[issues['allottee_category'].isin(['PROMOTER', 'MIXED'])].copy()
    s['when'] = pd.to_datetime(s['posted_on'], errors='coerce')
    s = s[_in_window(s['when'], ref, days)]
    rows = []
    for r in s.to_dict('records'):
        vs = pd.to_numeric(r.get('vs_market'), errors='coerce')
        isin = r.get('isin')
        if pd.isna(vs) or not isinstance(isin, str):
            continue
        n = pd.to_numeric(r.get('shares_allotted'), errors='coerce')
        if pd.isna(n):
            n = pd.to_numeric(r.get('securities_proposed'), errors='coerce')
        pct = float(n / total[isin] * 100) if pd.notna(n) and total.get(isin) else 0.0
        what = 'warrants' if 'warrant' in str(r.get('instruments') or '').lower() else 'shares'
        who = 'promoters' if r.get('allottee_category') == 'PROMOTER' else 'promoters and others'
        up = vs >= ISSUE_PREMIUM
        where = 'above' if up else 'below'
        size = f', {pct:.2f}% of the company' if pct else ''
        stage = str(r.get('status') or '').lower()
        rows.append({'isin': isin, 'company': r.get('company') or r.get('symbol'), 'nse_symbol': r.get('symbol'),
                     'list': 'look' if up else 'warn', 'kind': 'Promoters pay up' if up else 'Cheap shares to promoters',
                     'pct_of_company': pct,
                     'sentence': f'Preferential {what} to {who} at {abs(vs):.1f}% {where} the price now{size} ({stage})',
                     'value': pd.to_numeric(r.get('amount'), errors='coerce'), 'last': r['when']})
    return _ev(rows)


def buyback_events(bb: pd.DataFrame | None, ref: pd.Timestamp, sh=None, days: int = WINDOW) -> pd.DataFrame:
    """Tender buybacks priced 10%+ above today's price that opened in the window or are still to open
    (Worth a look). `bb` is screens.buybacks.rows output. Size: shares sought over total shares."""
    if bb is None or bb.empty or 'vs_market' not in bb:
        return _ev([])
    total = _shares_out(sh)
    b = bb[(bb['route'] == 'tender') & (pd.to_numeric(bb['vs_market'], errors='coerce') >= BUYBACK_PREMIUM)].copy()
    b['when'] = pd.to_datetime(b['offer_open'], errors='coerce').fillna(pd.to_datetime(b['record_date'], errors='coerce'))
    b = b[b['when'] > ref - pd.Timedelta(days=days)]
    rows = []
    for r in b.to_dict('records'):
        isin = r.get('isin')
        n = pd.to_numeric(r.get('shares_sought'), errors='coerce')
        pct = float(n / total[isin] * 100) if isinstance(isin, str) and pd.notna(n) and total.get(isin) else 0.0
        size = f', {pct:.2f}% of the shares' if pct else ''
        rows.append({'isin': isin, 'company': r.get('company') or r.get('symbol'), 'nse_symbol': r.get('symbol'), 'list': 'look',
                     'kind': 'Buyback at a premium', 'pct_of_company': pct,
                     'sentence': f'Tender buyback at {r["vs_market"]:.0f}% above the price now{size}',
                     'value': pd.to_numeric(r.get('offer_value'), errors='coerce'), 'last': r['when']})
    return _ev(rows)


def today(events: list, summary: pd.DataFrame | None = None,
          limits: tuple = (MAX_IDEAS, MAX_WARNINGS)) -> tuple:
    """(worth a look, watch out): one row per company and list, led by its largest event (its sentence),
    every kind as a chip, ordered by % of the company then the latest. A kind our own record measures as
    doing worse than the index is left off Worth a look (it stays in Filings)."""
    parts = [e for e in events if e is not None and not e.empty]
    if not parts:
        return _ev([]), _ev([])
    ev = pd.concat(parts, ignore_index=True)
    reads = _verdicts(summary)
    behind = {k for k, v in reads.items() if v == 'drag'}
    ev = ev[~((ev['list'] == 'look') & ev['kind'].isin(behind))]
    out = []
    for lst, limit in zip(('look', 'warn'), limits):
        x = ev[ev['list'] == lst].dropna(subset=['isin'])
        rows = []
        for isin, g in x.groupby('isin'):
            g = g.sort_values(['pct_of_company', 'last'], ascending=[False, False])
            lead = g.iloc[0].to_dict()
            kinds = list(dict.fromkeys(g['kind']))
            lead.update(kinds=kinds, reads={k: reads.get(k) for k in kinds if k in MEASURED_BY},
                        others=g['sentence'].drop_duplicates().tolist()[1:])
            rows.append(lead)
        r = pd.DataFrame(rows)
        out.append(r.sort_values(['pct_of_company', 'last'], ascending=[False, False]).head(limit).reset_index(drop=True)
                   if not r.empty else r)
    return out[0], out[1]
