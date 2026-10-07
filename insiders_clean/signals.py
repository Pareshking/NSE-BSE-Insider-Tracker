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
