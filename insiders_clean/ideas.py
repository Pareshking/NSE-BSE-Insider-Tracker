"""Today, the dashboard (redesign of 21 Oct 2026, docs/REVAMP_PLAN.md and the
blueprint the owner approved): across every listed company, for a period of one
day, 7, 30 or 90 days, "Worth a look" (people with skin in the game put money in at
a size that matters) and "Watch out" (they took money out, pledged, or took cheap
shares), each in a few groups.

Rules (owner, 21 Oct):
* Who: one decision-maker per promoter group (every filer filed as Promoter or
  Promoter Group, plus members named in the shareholding pattern), otherwise per
  person (signals.decision_makers). Tranches over the period are combined, so a
  promoter buying Rs 1 lakh a day is seen as the steady buyer they are.
* Size floor, per decision-maker over the period: at least MIN_VALUE and MIN_PCT
  of the company; or ALONE_PCT of the company whatever the rupees; or buying on
  STEADY_DAYS separate days (steady accumulation).
* Evidence does not pick: promoters buy for the quarters and years ahead, and a
  few months of the track record is short-term noise. Every kind is shown with
  its measured read as a tag (ahead, behind, no edge, few cases, not measured).
* Order: % of the company (shares over total shares from the shareholding XBRL
  where filed, else value over market cap at the trade), then the latest.
"""
from __future__ import annotations

import re

import pandas as pd

from . import evidence, signals

WINDOW = 90
MIN_VALUE = 25e5        # Rs 25 lakh
MIN_PCT = 0.05          # % of the company
ALONE_PCT = 0.25        # qualifies on its own, for a company too small for Rs 25 lakh to mean much
STEADY_DAYS = 10        # separate buying days in the window
MAX_IDEAS, MAX_WARNINGS = 10, 5
PER_GROUP = 8           # rows shown per group on Today; the rest counted, all in Filings
PLEDGE_RISE_PTS = 5.0   # pledge up this many points of promoter shares in the latest quarter
PERIODS = {'Today': 1, 'Last 7 days': 7, 'Last 30 days': 30, 'Last 90 days': 90}
# Signal kinds -> the track-record signal that measures them (the tag each row carries).
MEASURED_BY = {'Promoter buying': 'promoter_buy', 'Director or KMP buying': 'officer_buy', 'Cluster': 'cluster',
               'Spotlight': 'spotlight', 'Promoter selling': 'promoter_sell'}


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
    # The decision-maker of each row, as signals.decision_makers does it but for every company at once (a
    # loop per company took 6 of Today's 8 seconds): the promoter group is one, led by its first filer, made
    # of everyone whose first filing here says Promoter or Promoter Group or whom the shareholding pattern
    # names; anyone else stands alone.
    named = (w['promoter_group_id'].map(lambda v: isinstance(v, str) and bool(v)) if 'promoter_group_id' in w
             else pd.Series(False, index=w.index))
    w = w.assign(_row_pg=named | w['person_role'].isin(signals.PROMOTER_ROLES),
                 _q=pd.to_numeric(w['quantity'], errors='coerce'), _v=pd.to_numeric(w['value'], errors='coerce'),
                 _p=pd.to_numeric(w['pct_of_mcap'], errors='coerce'),
                 _to=pd.to_datetime(w['trade_date_to'], errors='coerce'), _from=pd.to_datetime(w['trade_date_from'], errors='coerce'))
    first = w.drop_duplicates(['isin', 'person_id'])
    pg = first.set_index(['isin', 'person_id'])['_row_pg']
    w['_pg'] = pg.reindex(pd.MultiIndex.from_frame(w[['isin', 'person_id']])).to_numpy()
    lead = first[first['_row_pg']].groupby('isin')['person_id'].first()
    w['dm'] = w['person_id'].where(~w['_pg'], w['isin'].map(lead))
    w['_day'] = w['_to'].dt.normalize()
    g = w.groupby(['isin', 'dm'], sort=False)
    out = g.agg(company=('company', 'last'), nse_symbol=('nse_symbol', 'last'), promoter_group=('_row_pg', 'any'),
                value=('_v', 'sum'), shares=('_q', 'sum'), pct_mcap=('_p', 'sum'), days=('_day', 'nunique'),
                first=('seen', 'min'), last=('seen', 'max'), trade_from=('_from', 'min'), trade_to=('_to', 'max'),
                filings=('seen', 'size')).reset_index()
    out['roles'] = g['person_role'].agg(lambda s: sorted(set(s))).to_numpy()
    out['people'] = g['person_name'].agg(lambda s: list(dict.fromkeys(s))).to_numpy()
    total = out['isin'].map(_shares_out(sh))
    out['pct_of_company'] = (out['shares'] / total * 100).where(total.gt(0), out['pct_mcap'])
    out['pct_basis'] = total.gt(0).map({True: 'shares', False: 'value'})
    out['avg_price'] = (out['value'] / out['shares']).where(out['shares'].ne(0))
    out['days'] = out['days'].astype(int)
    out['promoter_group'] = out['promoter_group'].astype(bool)
    return out.drop(columns='pct_mcap')


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


def worth_a_look(t: pd.DataFrame, ref: pd.Timestamp, sh: pd.DataFrame | None = None,
                 summary: pd.DataFrame | None = None, limit: int = MAX_IDEAS, days: int = WINDOW) -> pd.DataFrame:
    """At most `limit` companies, one row each: the sentence, the size, the reasons (`kinds`), the
    decision-makers behind it. `t` is the eligible insider table (signals.eligible)."""
    d = decisions(t, ref, 'BUY', sh, days)
    if d.empty:
        return d
    d = d[_qualifies(d)]
    if d.empty:
        return d
    clus = set(signals.clusters(t, ref)['isin']) if not t.empty else set()
    spot = set(signals.spotlight(t, ref)['isin']) if not t.empty else set()
    verdicts = _verdicts(summary)
    by: dict[str, list] = {}
    for r in d.sort_values('pct_of_company', ascending=False, kind='stable').to_dict('records'):
        by.setdefault(r['isin'], []).append(r)
    rows = []
    for isin, g in by.items():
        top = g[0]
        kinds = (['Promoter buying'] if any(x['promoter_group'] for x in g) else []) \
            + (['Director or KMP buying'] if any(not x['promoter_group'] and set(x['roles']) & {'director', 'kmp'} for x in g) else []) \
            + (['Cluster'] if isin in clus else []) + (['Spotlight'] if isin in spot else []) \
            + (['Steady accumulation'] if any(x['days'] >= STEADY_DAYS for x in g) else [])
        pct = sum(x['pct_of_company'] for x in g)
        value, shares = sum(x['value'] for x in g), sum(x['shares'] for x in g)
        lead = _who(top) if len(g) == 1 else f'{_who(top)} and {len(g) - 1} more'
        rows.append({'isin': isin, 'company': top['company'], 'nse_symbol': top['nse_symbol'],
                     'sentence': f'{lead} bought {pct:.2f}% of the company on the market{", " + _when(top) if _when(top) else ""}',
                     'pct_of_company': pct, 'pct_basis': top['pct_basis'], 'value': value,
                     'avg_price': value / shares if shares else None,
                     'trade_to': max(x['trade_to'] for x in g), 'last': max(x['last'] for x in g), 'kinds': kinds,
                     'decision_makers': len(g), 'reads': {k: verdicts.get(k) for k in kinds if k in MEASURED_BY}})
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values(['pct_of_company', 'last'], ascending=[False, False]).head(limit).reset_index(drop=True)


def watch_out(t: pd.DataFrame, ref: pd.Timestamp, sh: pd.DataFrame | None = None,
              limit: int = MAX_WARNINGS, days: int = WINDOW) -> pd.DataFrame:
    """At most `limit` companies where the promoter group sold on the market past the same floors, largest
    % of the company first. Pledges are pledge_events."""
    rows = []
    d = decisions(t, ref, 'SELL', sh, days)
    if not d.empty:
        d = d[d['promoter_group'] & _qualifies(d)]
        by: dict[str, list] = {}
        for r in d.sort_values('pct_of_company', ascending=False, kind='stable').to_dict('records'):
            by.setdefault(r['isin'], []).append(r)
        for isin, g in by.items():
            top = g[0]
            pct = sum(x['pct_of_company'] for x in g)
            value, shares = sum(x['value'] for x in g), sum(x['shares'] for x in g)
            rows.append({'isin': isin, 'company': top['company'], 'nse_symbol': top['nse_symbol'], 'kind': 'Promoter selling',
                         'sentence': f'{_who(top)} sold {pct:.2f}% of the company on the market{", " + _when(top) if _when(top) else ""}',
                         'size': pct, 'value': value, 'last': max(x['last'] for x in g),
                         'avg_price': value / shares if shares else None,
                         'trade_to': max(x['trade_to'] for x in g), 'decision_makers': len(g)})
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values(['size', 'last'], ascending=[False, False]).head(limit).reset_index(drop=True)


# --- Every other kind of filing, across the whole market (owner, 21 Oct: "one can not see 5000 company
# pages to find other details"). Each builder returns events with the same fields; `today()` merges them
# with the insider buys and sales into the two lists, one row per company, one size measure (% of the
# company), the company led by its largest event and every kind shown as a chip.
EVENT_COLS = ['isin', 'company', 'nse_symbol', 'list', 'kind', 'pct_of_company', 'sentence', 'value', 'last',
              'avg_price', 'trade_to', 'decision_makers']
BIG_STAKE = 5.0          # SAST Reg 29(1): crossing 5%
BIG_CHANGE = 2.0         # SAST Reg 29(2): a change of 2% or more
FUND_NET_PCT = 0.25      # funds' net bulk/block buying or selling over the period, % of the company
ISSUE_PREMIUM = 0.0      # promoters paying at or above today's price
BUYBACK_PREMIUM = 10.0   # tender offer at least 10% above today's price
MEASURED_BY.update({'Fund buying': 'fund_deal_buy'})


def _ev(rows) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=EVENT_COLS)


def _filings(n: int) -> str:
    return f'{n} filing' + ('' if n == 1 else 's')


def _in_window(when: pd.Series, ref: pd.Timestamp, days: int) -> pd.Series:
    return (when <= ref + pd.Timedelta(days=1)) & (when > ref - pd.Timedelta(days=days))


def insider_events(t, ref, sh=None, summary=None, days: int = WINDOW) -> pd.DataFrame:
    """Insider buys (Worth a look) and promoter sales (Watch out), from the two lists above."""
    rows = []
    look = worth_a_look(t, ref, sh, summary, limit=10_000, days=days)
    for r in look.to_dict('records') if not look.empty else []:
        for k in r['kinds']:
            rows.append({'isin': r['isin'], 'company': r['company'], 'nse_symbol': r['nse_symbol'], 'list': 'look',
                         'kind': k, 'pct_of_company': r['pct_of_company'], 'sentence': r['sentence'], 'value': r['value'],
                         'last': r['last'], 'avg_price': r['avg_price'], 'trade_to': r['trade_to'],
                         'decision_makers': r['decision_makers']})
    warn = watch_out(t, ref, sh, limit=10_000, days=days)
    for r in warn.to_dict('records') if not warn.empty else []:
        if r['kind'] == 'Promoter selling':
            rows.append({'isin': r['isin'], 'company': r['company'], 'nse_symbol': r['nse_symbol'], 'list': 'warn',
                         'kind': r['kind'], 'pct_of_company': r['size'], 'sentence': r['sentence'], 'value': r['value'],
                         'last': r['last'], 'avg_price': r['avg_price'], 'trade_to': r['trade_to'],
                         'decision_makers': r['decision_makers']})
    return _ev(rows)


def pledge_events(trades: pd.DataFrame, ref: pd.Timestamp, sh=None, days: int = WINDOW) -> pd.DataFrame:
    """Promoters pledging (Watch out) or releasing a pledge (Worth a look). From the PIT filings of the
    period, net per company: shares released and pledged again (a renewal, a change of lender) are no new
    pledge (Aequs, Sep-Oct 2026: 10.05 crore shares pledged, released, pledged again). And from a
    shareholding XBRL made public in the period whose pledge moved 5+ points of promoter shares from the
    quarter before, both quarters parsed. Size: shares over total shares."""
    rows = []
    total = _shares_out(sh)
    if trades is not None and not trades.empty and 'kind' in trades:
        t = trades[trades['is_primary'].astype('boolean').fillna(False) & ~trades['needs_review'].astype('boolean').fillna(False)
                   & trades['person_role'].isin(signals.PROMOTER_ROLES)
                   & trades['kind'].isin(['pledge_create', 'pledge_revoke'])].copy()
        t['seen'] = pd.to_datetime(t['broadcast_date'], errors='coerce')
        t = t[_in_window(t['seen'], ref, days)].dropna(subset=['isin'])
        t['q'] = pd.to_numeric(t['quantity'], errors='coerce') * t['kind'].map({'pledge_create': 1, 'pledge_revoke': -1})
        for isin, g in t.groupby('isin'):
            net = g['q'].sum()
            pct = abs(net) / total[isin] * 100 if total.get(isin) else None
            if pct is None or pct < MIN_PCT:
                continue
            made, freed = int((g['kind'] == 'pledge_create').sum()), int((g['kind'] == 'pledge_revoke').sum())
            how = f' ({made} pledged, {freed} released)' if made and freed else f' ({_filings(len(g))})'
            rows.append({'isin': isin, 'company': g['company'].iloc[-1], 'nse_symbol': g['nse_symbol'].iloc[-1],
                         'list': 'warn' if net > 0 else 'look', 'kind': 'Pledge created' if net > 0 else 'Pledge released',
                         'pct_of_company': pct,
                         'sentence': f'Promoters {"pledged" if net > 0 else "released"} a net {pct:.2f}% of the company{how}',
                         'value': None, 'last': g['seen'].max()})
    if sh is not None and not sh.empty and {'promoter_pledged_shares', 'total_shares', 'promoter_pledge_pct'} <= set(sh.columns):
        filed = sh['submission_date'] if 'submission_date' in sh else sh['quarter_end']
        s = sh.assign(q=pd.to_datetime(sh['quarter_end'], errors='coerce'), filed=pd.to_datetime(filed, errors='coerce'),
                      pl=pd.to_numeric(sh['promoter_pledge_pct'], errors='coerce'),
                      ps=pd.to_numeric(sh['promoter_pledged_shares'], errors='coerce'),
                      ts=pd.to_numeric(sh['total_shares'], errors='coerce')).dropna(subset=['isin'])
        if 'xbrl_status' in s:
            s = s[s['xbrl_status'].fillna('ok') == 'ok']
        if 'shareholding_stale' in s:
            s = s[~s['shareholding_stale'].astype('boolean').fillna(False)]
        s = s.dropna(subset=['pl']).sort_values('q').drop_duplicates(['isin', 'q'], keep='last')
        two = s.groupby('isin').tail(2)
        prev = two.groupby('isin').head(1).set_index('isin')
        last = two.groupby('isin').tail(1).set_index('isin')
        last = last[last.index.isin(prev.index) & (last['q'] != prev['q'].reindex(last.index))]
        prev = prev.reindex(last.index)
        last = last.assign(when=last['filed'].fillna(last['q']), move=last['pl'] - prev['pl'])
        last = last[last['move'].abs().ge(PLEDGE_RISE_PTS) & last['ts'].gt(0) & _in_window(last['when'], ref, days)]
        for isin, b in last.iterrows():
            a = prev.loc[isin]
            move, when = b['move'], b['when']
            pct = abs(b['ps'] - a['ps']) / b['ts'] * 100 if pd.notna(b['ps']) and pd.notna(a['ps']) else 0.0
            rows.append({'isin': isin, 'company': b.get('company') or b.get('symbol'), 'nse_symbol': b.get('symbol'),
                         'list': 'warn' if move > 0 else 'look', 'kind': 'Pledge rising' if move > 0 else 'Pledge released',
                         'pct_of_company': pct,
                         'sentence': f'Promoters pledged {b["pl"]:.1f}% of their shares at {b["q"]:%b %Y}, '
                                     f'{"up" if move > 0 else "down"} from {a["pl"]:.1f}% a quarter earlier',
                         'value': None, 'last': when})
    return _ev(rows)


# A SAST filing by a lender's trustee or security agent, or by a bank branch, is a pledge or its release
# (the shares are held as security), not an investor buying or selling: Vedanta's tap bonds (GLAS Agency,
# Citicorp, Kroll, Axis Trustee), Orient Green (Catalyst Trusteeship), Horizon Industrial Parks and Manipal
# (Deutsche Bank AG, Singapore Branch; Vistra ITCL), Oct 2026.
SECURITY_HOLDER = re.compile(r'truste|security agent|\bagent\b|on behalf of|debenture|for the holders|facility agreement'
                             r'|\blenders?\b|\bglas\b|vistra|\bitcl\b|madison pacific|citicorp international'
                             r'|international trust|\bbank\b.*\bbranch\b', re.I)


def stake_events(sast: pd.DataFrame | None, ref: pd.Timestamp, days: int = WINDOW) -> pd.DataFrame:
    """Big investors (not promoters) crossing 5% or adding 2%+ (Worth a look), or selling 2%+ or falling
    below 5% (Watch out), from SAST Reg 29 disclosures; lenders' trustees and agents holding shares as
    security left out (SECURITY_HOLDER), a filing seen on both exchanges counted once. Size: the % of the
    company they bought or sold."""
    if sast is None or sast.empty or 'isin' not in sast:
        return _ev([])
    s = sast[~sast['is_promoter'].astype('boolean').fillna(False)
             & ~sast['acquirer_name'].fillna('').astype(str).str.contains(SECURITY_HOLDER)].copy()
    when = pd.to_datetime(s['broadcast_date'], errors='coerce') if 'broadcast_date' in s else pd.Series(pd.NaT, index=s.index)
    if 'transaction_date' in s:
        when = when.fillna(pd.to_datetime(s['transaction_date'], errors='coerce'))
    s['when'] = when
    s = s[_in_window(s['when'], ref, days)].dropna(subset=['isin'])
    same = [c for c in ('isin', 'acquirer_name', 'pct_acquired', 'pct_sold', 'post_stake_pct') if c in s]
    s = s.sort_values('when').drop_duplicates(same, keep='last')
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


def fund_events(deals: pd.DataFrame | None, trades: pd.DataFrame | None, ref: pd.Timestamp, days: int = WINDOW) -> pd.DataFrame:
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


# The groups each list is shown in, in this order. A company sits in the first group any of its kinds
# belongs to, led by its largest event there; its other kinds are chips and their sentences are listed.
GROUPS = {
    'look': [('Insiders buying', ['Promoter buying', 'Director or KMP buying', 'Cluster', 'Spotlight', 'Steady accumulation']),
             ('Promoters pay up', ['Promoters pay up']),
             ('Pledges released', ['Pledge released']),
             ('Big investors and funds in', ['Big investor in', 'Fund buying']),
             ('Buybacks at a premium', ['Buyback at a premium'])],
    'warn': [('Promoters selling', ['Promoter selling']),
             ('Pledges', ['Pledge created', 'Pledge rising']),
             ('Cheap shares to promoters', ['Cheap shares to promoters']),
             ('Big investors and funds out', ['Big investor out', 'Funds selling'])],
}


def _group(lst: str, kinds: list) -> tuple:
    for i, (name, members) in enumerate(GROUPS[lst]):
        if set(kinds) & set(members):
            return i, name, members
    return len(GROUPS[lst]), 'Other', kinds


def today(events: list, summary: pd.DataFrame | None = None) -> tuple:
    """(worth a look, watch out): one row per company and list, in its group (GROUPS), led by its largest
    event in that group, every kind as a chip with its measured read; ordered by group, then % of the
    company, then the latest. Nothing is left out on its read (owner, 21 Oct): the read is a tag."""
    parts = [e for e in events if e is not None and not e.empty]
    if not parts:
        return _ev([]), _ev([])
    ev = pd.concat(parts, ignore_index=True)
    reads = _verdicts(summary)
    out = []
    for lst in ('look', 'warn'):
        x = ev[ev['list'] == lst].dropna(subset=['isin'])
        rows = []
        for isin, g in x.groupby('isin'):
            kinds = list(dict.fromkeys(g['kind']))
            order, name, members = _group(lst, kinds)
            g = g.assign(_in=g['kind'].isin(members)).sort_values(['_in', 'pct_of_company', 'last'], ascending=False)
            lead = g.iloc[0].drop(labels='_in').to_dict()
            lead.update(kinds=kinds, group=name, group_order=order, reads={k: reads.get(k) or 'not_measured' for k in kinds},
                        others=[t for t in g['sentence'].drop_duplicates() if t != lead['sentence']])
            rows.append(lead)
        r = pd.DataFrame(rows)
        out.append(r.sort_values(['group_order', 'pct_of_company', 'last'], ascending=[True, False, False]).reset_index(drop=True)
                   if not r.empty else r)
    return out[0], out[1]
