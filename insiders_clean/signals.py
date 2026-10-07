"""Signals from the clean tables, as decided in docs/SIGNALS.md (07 Oct 2026).

Pure functions on DataFrames; the site and the signal lab both call these,
so a threshold changes in one place.

Eligible insider rows: open-market (`is_market`), primary copy (`is_primary`),
not held back (`needs_review`). Token buys are labelled and never ranked.
"""
from __future__ import annotations

import re

import pandas as pd

SPOTLIGHT_PCT_30D = 0.15      # one person's open-market buys, % of market cap, rolling 30 days
FLOAT_ABSORBER_PCT_90D = 0.5  # same, rolling 90 days
TOKEN_MAX_VALUE = 25e5        # Rs.25 lakh ...
TOKEN_MIN_MCAP = 5000e7       # ... in a company above Rs.5,000 Cr
CLUSTER_DAYS = 30
HIGH_PLEDGE_PCT = 15.0        # promoter pledge as % of promoter shares
DECISION_ROLES = ('promoter', 'promoter_group', 'director', 'kmp')
PROMOTER_ROLES = ('promoter', 'promoter_group')
_CORPORATE = re.compile(r'\b(limited|ltd|llp|private|pvt|trust|holdings?|investments?|ventures?|'
                        r'enterprises?|capital|fund|corporation|company|inc)\b', re.IGNORECASE)


def as_of(trades: pd.DataFrame) -> pd.Timestamp | None:
    """The latest broadcast date in the data: 'today' for the site, so a
    page never claims a session the data doesn't have."""
    if trades is None or trades.empty:
        return None
    d = pd.to_datetime(trades['broadcast_date'], errors='coerce').dropna()
    return d.max().normalize() if len(d) else None


def eligible(trades: pd.DataFrame) -> pd.DataFrame:
    t = trades.copy()
    for c in ('is_market', 'is_primary', 'needs_review'):
        t[c] = t[c].astype('boolean').fillna(False)
    t = t[t['is_market'] & t['is_primary'] & ~t['needs_review']].copy()
    t['date'] = pd.to_datetime(t['trade_date_to'], errors='coerce')
    t['seen'] = pd.to_datetime(t['broadcast_date'], errors='coerce')
    for c in ('value', 'pct_of_mcap', 'market_cap', 'signed_value'):
        t[c] = pd.to_numeric(t[c], errors='coerce')
    t['is_token'] = (t['person_role'].isin(PROMOTER_ROLES) & (t['side'] == 'BUY')
                     & (t['value'] < TOKEN_MAX_VALUE) & (t['market_cap'] > TOKEN_MIN_MCAP))
    return t


def family_key(person_name, person_id) -> str:
    """Promoter entities of one family count once in a cluster. Individuals
    are keyed by surname (last word); companies, trusts and funds by their
    own ID. A heuristic: it can merge unrelated people sharing a surname,
    which only ever makes a cluster harder to reach, never easier."""
    name = str(person_name or '').strip()
    if not name or _CORPORATE.search(name):
        return f'entity:{person_id}'
    return 'family:' + name.split()[-1].lower()


def person_windows(t: pd.DataFrame, ref: pd.Timestamp) -> pd.DataFrame:
    """Per company and person: open-market buys in the 30 and 90 days to `ref`."""
    buys = t[(t['side'] == 'BUY') & ~t['is_token'] & t['person_role'].isin(DECISION_ROLES)
             & (t['seen'] <= ref) & (t['seen'] > ref - pd.Timedelta(days=90))].dropna(subset=['isin'])
    if buys.empty:
        return pd.DataFrame(columns=['isin', 'person_id', 'person_name', 'person_role', 'company', 'nse_symbol',
                                     'value_30d', 'pct_30d', 'trades_30d', 'value_90d', 'pct_90d', 'last_seen'])
    in30 = buys['seen'] > ref - pd.Timedelta(days=30)
    g = buys.assign(v30=buys['value'].where(in30, 0), p30=buys['pct_of_mcap'].where(in30, 0), n30=in30.astype(int))
    out = g.groupby(['isin', 'person_id'], as_index=False).agg(
        person_name=('person_name', 'last'), person_role=('person_role', 'last'), company=('company', 'last'),
        nse_symbol=('nse_symbol', 'last'), value_30d=('v30', 'sum'), pct_30d=('p30', 'sum'),
        trades_30d=('n30', 'sum'), value_90d=('value', 'sum'), pct_90d=('pct_of_mcap', 'sum'),
        last_seen=('seen', 'max'))
    return out


def spotlight(t: pd.DataFrame, ref: pd.Timestamp) -> pd.DataFrame:
    w = person_windows(t, ref)
    return w[w['pct_30d'] >= SPOTLIGHT_PCT_30D].sort_values('pct_30d', ascending=False)


def float_absorbers(t: pd.DataFrame, ref: pd.Timestamp) -> pd.DataFrame:
    w = person_windows(t, ref)
    return w[w['pct_90d'] >= FLOAT_ABSORBER_PCT_90D].sort_values('pct_90d', ascending=False)


def clusters(t: pd.DataFrame, ref: pd.Timestamp) -> pd.DataFrame:
    """Companies with 2+ distinct buyers in the last 30 days, including a
    director/KMP or promoter entities that are not one family."""
    buys = t[(t['side'] == 'BUY') & ~t['is_token'] & t['person_role'].isin(DECISION_ROLES)
             & (t['seen'] <= ref) & (t['seen'] > ref - pd.Timedelta(days=CLUSTER_DAYS))].dropna(subset=['isin'])
    rows = []
    for isin, g in buys.groupby('isin'):
        people = g.drop_duplicates('person_id')
        if len(people) < 2:
            continue
        has_officer = people['person_role'].isin(['director', 'kmp']).any()
        families = {family_key(n, p) for n, p in zip(people['person_name'], people['person_id'])}
        if not has_officer and len(families) < 2:
            continue
        rows.append({'isin': isin, 'company': g['company'].iloc[-1], 'nse_symbol': g['nse_symbol'].iloc[-1],
                     'buyers': len(people), 'families': len(families), 'has_officer': bool(has_officer),
                     'roles': ', '.join(sorted(set(people['person_role']))),
                     'value': g['value'].sum(), 'pct_of_mcap': g['pct_of_mcap'].sum(), 'last_seen': g['seen'].max()})
    return pd.DataFrame(rows).sort_values('pct_of_mcap', ascending=False) if rows else pd.DataFrame(
        columns=['isin', 'company', 'nse_symbol', 'buyers', 'families', 'has_officer', 'roles', 'value',
                 'pct_of_mcap', 'last_seen'])


def latest_shareholding(sh: pd.DataFrame | None) -> pd.DataFrame:
    """One row per company: its latest quarter's holdings and pledge."""
    if sh is None or sh.empty:
        return pd.DataFrame(columns=['symbol', 'isin', 'promoter_holding_pct', 'public_holding_pct',
                                     'promoter_pledge_pct', 'shareholding_stale', 'quarter_end'])
    s = sh.copy()
    s['quarter_end'] = pd.to_datetime(s['quarter_end'], errors='coerce')
    for c in ('promoter_holding_pct', 'public_holding_pct', 'promoter_pledge_pct'):
        s[c] = pd.to_numeric(s.get(c), errors='coerce')
    return s.sort_values('quarter_end').drop_duplicates('symbol', keep='last')


def company_board(t: pd.DataFrame, deals: pd.DataFrame | None, sh: pd.DataFrame | None,
                  ref: pd.Timestamp, days: int = 90) -> pd.DataFrame:
    """One row per company with insider activity in the window: promoter and
    officer net flow, deal flow excluding market makers, factor badges."""
    win = t[(t['seen'] <= ref) & (t['seen'] > ref - pd.Timedelta(days=days))].dropna(subset=['isin'])
    if win.empty:
        return pd.DataFrame()
    prom = win['person_role'].isin(PROMOTER_ROLES)
    off = win['person_role'].isin(['director', 'kmp'])
    board = win.groupby('isin').agg(company=('company', 'last'), nse_symbol=('nse_symbol', 'last'),
                                    market_cap=('market_cap', 'last'), last_seen=('seen', 'max'))
    board['promoter_net'] = win[prom].groupby('isin')['signed_value'].sum()
    board['officer_net'] = win[off].groupby('isin')['signed_value'].sum()
    signed_pct = win['pct_of_mcap'] * win['side'].map({'BUY': 1, 'SELL': -1})
    board['promoter_net_pct'] = signed_pct[prom].groupby(win.loc[prom, 'isin']).sum()
    board['insiders'] = win[win['person_role'].isin(DECISION_ROLES)].groupby('isin')['person_id'].nunique()
    board = board.fillna({'promoter_net': 0, 'officer_net': 0, 'promoter_net_pct': 0, 'insiders': 0})
    if deals is not None and not deals.empty:
        d = deals.copy()
        d['date'] = pd.to_datetime(d['date'], errors='coerce')
        mm = d['client_is_market_maker'].astype('boolean').fillna(False) if 'client_is_market_maker' in d else False
        d = d[(~mm) & d['is_primary'].astype('boolean').fillna(False)
              & (d['date'] <= ref) & (d['date'] > ref - pd.Timedelta(days=days))]
        board['deals_net'] = pd.to_numeric(d['signed_value'], errors='coerce').groupby(d['isin']).sum()
    else:
        board['deals_net'] = None
    spot = set(spotlight(t, ref)['isin'])
    absorb = set(float_absorbers(t, ref)['isin'])
    clus = set(clusters(t, ref)['isin'])
    # One row per ISIN: two symbols (or a re-listing) can share one.
    shl = (latest_shareholding(sh).dropna(subset=['isin']).drop_duplicates('isin', keep='last').set_index('isin')
           if sh is not None and not sh.empty else pd.DataFrame())
    board = board.reset_index()
    if not shl.empty:
        board['pledge_pct'] = board['isin'].map(shl['promoter_pledge_pct'])
        board['public_pct'] = board['isin'].map(shl['public_holding_pct'])
    else:
        board['pledge_pct'] = None
        board['public_pct'] = None
    badges = []
    for _, r in board.iterrows():
        b = []
        if r['isin'] in spot:
            b.append('Spotlight')
        if r['isin'] in absorb:
            b.append('Float absorber')
        if r['isin'] in clus:
            b.append('Cluster')
        if r['promoter_net_pct'] <= -SPOTLIGHT_PCT_30D:
            b.append('Promoter selling')
        if pd.notna(r['pledge_pct']) and r['pledge_pct'] > HIGH_PLEDGE_PCT:
            b.append(f'High pledge {r["pledge_pct"]:.0f}%')
        badges.append(b)
    board['badges'] = badges
    return board.sort_values('promoter_net_pct', ascending=False).reset_index(drop=True)


# --- page building blocks (owner's page spec, 07-08 Oct 2026) ------------------

LARGE_HANDSHAKE_VALUE = 10e7      # Rs.10 Cr ...
LARGE_HANDSHAKE_PCT = 0.5         # ... or 0.5% of market cap
SMALL_CAP_MAX_MCAP = 5000e7       # "small caps" for the institutional footprint
ROLE_WORDS = {'promoter': 'promoter', 'promoter_group': 'promoter group', 'director': 'director', 'kmp': 'KMP'}


def float_pct(value, market_cap, public_pct):
    """A trade as a % of free float: value / (market cap x public holding %).
    None when either denominator is unknown, never a guess."""
    try:
        v, m, p = float(value), float(market_cap), float(public_pct)
    except (TypeError, ValueError):
        return None
    if not (m > 0 and p > 0) or pd.isna(v):
        return None
    return v / (m * p / 100) * 100


def public_pct_by_isin(sh: pd.DataFrame | None) -> pd.Series:
    s = latest_shareholding(sh)
    if s.empty:
        return pd.Series(dtype=float)
    return s.dropna(subset=['isin']).drop_duplicates('isin', keep='last').set_index('isin')['public_holding_pct']


def pledge_by_isin(sh: pd.DataFrame | None) -> pd.Series:
    s = latest_shareholding(sh)
    if s.empty:
        return pd.Series(dtype=float)
    return s.dropna(subset=['isin']).drop_duplicates('isin', keep='last').set_index('isin')['promoter_pledge_pct']


def buys_in_days(t: pd.DataFrame, isin, person_id, upto: pd.Timestamp, days: int = 14) -> int:
    """How many open-market buys this person filed in this company in the
    `days` days to `upto` (the "3rd buy in 14 days" context)."""
    m = ((t['isin'] == isin) & (t['person_id'] == person_id) & (t['side'] == 'BUY')
         & (t['seen'] <= upto) & (t['seen'] > upto - pd.Timedelta(days=days)))
    return int(m.sum())


def session_by_company(t: pd.DataFrame, day: pd.Timestamp, sh: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per company, person and side for one session: tranches
    combined, value, % of market cap and of free float, trades."""
    rows = t[t['seen'].dt.normalize() == day].dropna(subset=['isin'])
    if rows.empty:
        return pd.DataFrame()
    g = rows.groupby(['isin', 'person_id', 'side'], as_index=False).agg(
        company=('company', 'last'), nse_symbol=('nse_symbol', 'last'), person_name=('person_name', 'last'),
        person_role=('person_role', 'last'), value=('value', 'sum'), pct_of_mcap=('pct_of_mcap', 'sum'),
        market_cap=('market_cap', 'last'), trades=('trade_id', 'size'), is_token=('is_token', 'all'),
        listed_on=('listed_on', 'last'))
    pub = public_pct_by_isin(sh)
    g['pct_of_float'] = [float_pct(v, m, pub.get(i)) for v, m, i in zip(g['value'], g['market_cap'], g['isin'])]
    return g.sort_values('pct_of_mcap', ascending=False)


def handshakes(deals: pd.DataFrame, trades: pd.DataFrame | None = None, days: int = 30,
               ref: pd.Timestamp | None = None) -> pd.DataFrame:
    """Who absorbed whose shares: for each security and day, the real sellers
    (market makers excluded) and the real buyers on the other side. A seller
    is marked promoter when the same name filed as promoter or promoter group
    for that company. Matched value is the smaller of the two sides."""
    if deals is None or deals.empty:
        return pd.DataFrame()
    d = deals.copy()
    d['date'] = pd.to_datetime(d['date'], errors='coerce')
    mm = d['client_is_market_maker'].astype('boolean').fillna(False) if 'client_is_market_maker' in d else False
    d = d[(~mm) & d['is_primary'].astype('boolean').fillna(False)].dropna(subset=['date'])
    if d.empty:
        return pd.DataFrame()
    ref = ref or d['date'].max()
    d = d[(d['date'] <= ref) & (d['date'] > ref - pd.Timedelta(days=days))]
    d['_sec'] = d['isin'].fillna(d['exchange'].astype(str) + ':' + d['symbol'].astype(str))
    promoters = set()
    if trades is not None and not trades.empty:
        p = trades[trades['person_role'].isin(PROMOTER_ROLES)]
        promoters = set(zip(p['isin'], p['person_id']))
    rows = []
    for (_sec, day), g in d.groupby(['_sec', 'date']):
        sell, buy = g[g['side'] == 'SELL'], g[g['side'] == 'BUY']
        if sell.empty or buy.empty:
            continue
        sv, bv = sell['value'].sum(), buy['value'].sum()
        rows.append({
            'date': day, 'isin': g['isin'].iloc[0], 'company': g['company'].iloc[0], 'nse_symbol': g['nse_symbol'].iloc[0],
            'sellers': '; '.join(sell.sort_values('value', ascending=False)['client_name'].astype(str)),
            'buyers': '; '.join(buy.sort_values('value', ascending=False)['client_name'].astype(str)),
            'seller_is_promoter': any((i, c) in promoters for i, c in zip(sell['isin'], sell['client_id'])),
            'matched_value': min(sv, bv),
            'pct_of_mcap_sold': pd.to_numeric(sell['pct_of_mcap'], errors='coerce').sum(),
            'market_cap': g['market_cap'].iloc[0]})
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out['large'] = (out['matched_value'] >= LARGE_HANDSHAKE_VALUE) | (out['pct_of_mcap_sold'] >= LARGE_HANDSHAKE_PCT)
    return out.sort_values(['date', 'matched_value'], ascending=False).reset_index(drop=True)


def small_cap_accumulation(deals: pd.DataFrame, ref: pd.Timestamp | None = None, days: int = 30) -> pd.DataFrame:
    """Small caps (under Rs.5,000 Cr) that real funds net-bought in bulk/block
    deals over the last `days` days: who, net value, % of market cap."""
    if deals is None or deals.empty:
        return pd.DataFrame()
    d = deals.copy()
    d['date'] = pd.to_datetime(d['date'], errors='coerce')
    mm = d['client_is_market_maker'].astype('boolean').fillna(False) if 'client_is_market_maker' in d else False
    d = d[(~mm) & d['is_primary'].astype('boolean').fillna(False)]
    if d.empty:
        return pd.DataFrame()
    ref = ref or d['date'].max()
    d = d[(d['date'] <= ref) & (d['date'] > ref - pd.Timedelta(days=days))
          & (pd.to_numeric(d['market_cap'], errors='coerce') < SMALL_CAP_MAX_MCAP)].dropna(subset=['isin'])
    if d.empty:
        return pd.DataFrame()
    d = d.assign(signed_pct=pd.to_numeric(d['pct_of_mcap'], errors='coerce') * d['side'].map({'BUY': 1, 'SELL': -1}))
    net_by_client = d.groupby(['isin', 'client_name'])['signed_value'].sum()
    buyers = (net_by_client[net_by_client > 0].reset_index().sort_values('signed_value', ascending=False)
              .groupby('isin')['client_name'].agg(lambda s: '; '.join(s.head(4))))
    out = d.groupby('isin').agg(company=('company', 'last'), nse_symbol=('nse_symbol', 'last'),
                                net_value=('signed_value', 'sum'), net_pct=('signed_pct', 'sum'),
                                market_cap=('market_cap', 'last'), last=('date', 'max'))
    out['net_buyers'] = buyers
    out = out[out['net_value'] > 0].reset_index()
    return out.sort_values('net_pct', ascending=False)


def insider_details(t: pd.DataFrame, ref: pd.Timestamp, days: int = 90) -> pd.Series:
    """Per company, who bought: e.g. '1 director, 2 promoters · 4 trades'."""
    w = t[(t['side'] == 'BUY') & t['person_role'].isin(DECISION_ROLES) & ~t['is_token']
          & (t['seen'] <= ref) & (t['seen'] > ref - pd.Timedelta(days=days))].dropna(subset=['isin'])
    out = {}
    for isin, g in w.groupby('isin'):
        people = g.drop_duplicates('person_id')['person_role'].map(ROLE_WORDS).value_counts()
        parts = [f'{n} {r}' + ('s' if n > 1 and r != 'KMP' else '') for r, n in people.items()]
        out[isin] = f'{", ".join(parts)} · {len(g)} trade' + ('s' if len(g) != 1 else '')
    return pd.Series(out, dtype=object)
