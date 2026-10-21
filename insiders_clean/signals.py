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
# Institutional client types (insiders_clean/participants.INSTITUTIONAL, kept here to avoid an import cycle)
FUND_TYPES = ('mutual_fund', 'insurer', 'pension', 'bank', 'fpi', 'pms_aif', 'fund_other')
_CORPORATE = re.compile(r'\b(limited|ltd|llp|private|pvt|trust|holdings?|investments?|ventures?|'
                        r'enterprises?|capital|fund|corporation|company|inc)\b', re.IGNORECASE)


def as_of(trades: pd.DataFrame) -> pd.Timestamp | None:
    """The latest broadcast date in the data: 'today' for the site, so a
    page never claims a session the data doesn't have."""
    if trades is None or trades.empty:
        return None
    t = trades   # held-back rows and exchange copies don't set the date (audit W20)
    if 'is_primary' in t:
        t = t[t['is_primary'].astype('boolean').fillna(False)]
    if 'needs_review' in t:
        t = t[~t['needs_review'].astype('boolean').fillna(False)]
    d = pd.to_datetime(t['broadcast_date'], errors='coerce').dropna()
    today = pd.Timestamp.now(tz='Asia/Kolkata').tz_localize(None).normalize()
    d = d[d.dt.normalize() <= today]   # a date typed in the future in a filing never moves 'today'
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


def decision_makers(people: pd.DataFrame) -> pd.Series:
    """person_id -> decision-maker key, for the buyers of one company (one row
    per person). The company's promoter group is one decision-maker: every filer
    whose own filing says Promoter or Promoter Group (the exchange's category),
    and anyone the shareholding pattern names as a member (`promoter_group_id`,
    insiders_clean/promoter_group.py) even when filed under another category.
    Directors and KMP outside the group stand alone. (21 Oct, audit D1: the
    surname rule split one family into five; the filed category is the rule.)"""
    ids = list(people['person_id'])
    parent = {i: i for i in ids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    groups = people['promoter_group_id'] if 'promoter_group_id' in people else pd.Series(None, index=people.index)
    first: dict[str, str] = {}
    for pid, role, g in zip(ids, people['person_role'], groups):
        keys = ['promoter group'] if (isinstance(g, str) and g) or role in PROMOTER_ROLES else []
        for k in keys:
            if k in first:
                parent[find(pid)] = find(first[k])
            else:
                first[k] = pid
    return pd.Series({i: find(i) for i in ids}, dtype=object)


def decision_text(people: pd.DataFrame, dm: pd.Series) -> str:
    """'4 buyers, 2 decision-makers: promoter group (3), director'."""
    groups = people['promoter_group_id'] if 'promoter_group_id' in people else pd.Series(None, index=people.index)
    linked = (groups.map(lambda g: isinstance(g, str) and bool(g)) | people['person_role'].isin(PROMOTER_ROLES)).to_numpy()
    roots = people['person_id'].map(dm).to_numpy()
    parts = []
    for root in dict.fromkeys(roots):
        sel = roots == root
        n = int(sel.sum())
        if linked[sel].any():
            parts.append('promoter group' + (f' ({n})' if n > 1 else ''))
        elif n > 1:
            parts.append(f'one family by surname ({n})')
        else:  # a promoter-role filer not in the group list reads 'promoter', never 'promoter group'
            r = people['person_role'].to_numpy()[sel][0]
            parts.append('promoter' if r in PROMOTER_ROLES else ROLE_WORDS.get(r, 'insider'))
    k, b = len(parts), len(people)
    return f'{b} buyer{"s" if b != 1 else ""}, {k} decision-maker{"s" if k != 1 else ""}: ' + ', '.join(parts)


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
    """Companies with 2+ distinct decision-makers buying in the last 30 days
    (docs/SIGNALS.md): each director or KMP, each promoter family, and the
    promoter group as one (decision_makers). With no promoter-group links this
    is the rule of 07 Oct: 2+ buyers including a director/KMP, or promoters of
    two families."""
    buys = t[(t['side'] == 'BUY') & ~t['is_token'] & t['person_role'].isin(DECISION_ROLES)
             & (t['seen'] <= ref) & (t['seen'] > ref - pd.Timedelta(days=CLUSTER_DAYS))].dropna(subset=['isin'])
    rows = []
    for isin, g in buys.groupby('isin'):
        people = g.drop_duplicates('person_id')
        if len(people) < 2:
            continue
        dm = decision_makers(people)
        if dm.nunique() < 2:
            continue
        linked = int(people['promoter_group_id'].notna().sum()) if 'promoter_group_id' in people else 0
        rows.append({'isin': isin, 'company': g['company'].iloc[-1], 'nse_symbol': g['nse_symbol'].iloc[-1],
                     'buyers': len(people), 'decision_makers': int(dm.nunique()), 'group_buyers': linked,
                     'has_officer': bool(people['person_role'].isin(['director', 'kmp']).any()),
                     'roles': ', '.join(sorted(set(people['person_role']))), 'who': decision_text(people, dm),
                     'value': g['value'].sum(), 'pct_of_mcap': g['pct_of_mcap'].sum(), 'last_seen': g['seen'].max()})
    return pd.DataFrame(rows).sort_values('pct_of_mcap', ascending=False) if rows else pd.DataFrame(
        columns=['isin', 'company', 'nse_symbol', 'buyers', 'decision_makers', 'group_buyers', 'has_officer',
                 'roles', 'who', 'value', 'pct_of_mcap', 'last_seen'])


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
    # Token buys (under Rs 25 L in companies above Rs 5,000 Cr) are labelled, never ranked (07 Oct; audit W12).
    token = win['is_token'].astype('boolean').fillna(False) if 'is_token' in win else pd.Series(False, index=win.index)
    prom = win['person_role'].isin(PROMOTER_ROLES) & ~token
    off = win['person_role'].isin(['director', 'kmp'])
    board = win.groupby('isin').agg(company=('company', 'last'), nse_symbol=('nse_symbol', 'last'),
                                    market_cap=('market_cap', 'last'), last_seen=('seen', 'max'))
    board['promoter_net'] = win[prom].groupby('isin')['signed_value'].sum()
    board['officer_net'] = win[off].groupby('isin')['signed_value'].sum()
    signed_pct = win['pct_of_mcap'] * win['side'].map({'BUY': 1, 'SELL': -1})
    board['promoter_net_pct'] = signed_pct[prom].groupby(win.loc[prom, 'isin']).sum()
    dec = win[win['person_role'].isin(DECISION_ROLES)]
    board['insiders'] = dec.groupby('isin')['person_id'].nunique()
    # Breadth with the promoter group counted once.
    board['decision_makers'] = pd.Series({i: decision_makers(g.drop_duplicates('person_id')).nunique()
                                          for i, g in dec.groupby('isin')}, dtype=float)
    board = board.fillna({'promoter_net': 0, 'officer_net': 0, 'promoter_net_pct': 0, 'insiders': 0,
                          'decision_makers': 0})
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
    g['pct_of_float'] = pd.to_numeric(pd.Series([float_pct(v, m, pub.get(i)) for v, m, i in zip(g['value'], g['market_cap'], g['isin'])],
                                                index=g.index, dtype=object), errors='coerce')  # numeric: blank, not 'None'
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
    # Net each client first: one who bought and sold that day is a net seller
    # or a net buyer, never on both sides of the same handshake.
    d['_signed'] = pd.to_numeric(d['signed_value'], errors='coerce')
    d['_spct'] = pd.to_numeric(d['pct_of_mcap'], errors='coerce') * d['side'].map({'BUY': 1, 'SELL': -1})
    keys = ['_sec', 'date']
    net = d.groupby(keys + ['client_id', 'client_name'], as_index=False, dropna=False).agg(
        v=('_signed', 'sum'), p=('_spct', 'sum'))
    join = lambda x: '; '.join(x.astype(str))  # noqa: E731
    sell = net[net['v'] < 0].sort_values('v').groupby(keys).agg(
        sellers=('client_name', join), sv=('v', 'sum'), sp=('p', 'sum'), seller_ids=('client_id', list))
    buy = net[net['v'] > 0].sort_values('v', ascending=False).groupby(keys).agg(
        buyers=('client_name', join), bv=('v', 'sum'))
    m = sell.join(buy, how='inner')
    if m.empty:
        return pd.DataFrame()
    first = d.groupby(keys).agg(isin=('isin', 'first'), company=('company', 'first'),
                                nse_symbol=('nse_symbol', 'first'), market_cap=('market_cap', 'first'))
    m = m.join(first).reset_index()
    out = pd.DataFrame({
        'date': m['date'], 'isin': m['isin'], 'company': m['company'], 'nse_symbol': m['nse_symbol'],
        'sellers': m['sellers'], 'buyers': m['buyers'],
        'seller_is_promoter': [any((i, c) in promoters for c in ids) for i, ids in zip(m['isin'], m['seller_ids'])],
        'matched_value': [min(-a, b) for a, b in zip(m['sv'], m['bv'])],
        'pct_of_mcap_sold': -m['sp'], 'market_cap': m['market_cap']})
    out['large'] = (out['matched_value'] >= LARGE_HANDSHAKE_VALUE) | (out['pct_of_mcap_sold'] >= LARGE_HANDSHAKE_PCT)
    return out.sort_values(['date', 'matched_value'], ascending=False).reset_index(drop=True)


def small_cap_accumulation(deals: pd.DataFrame, ref: pd.Timestamp | None = None, days: int = 30,
                           funds_only: bool = True) -> pd.DataFrame:
    """Small caps (under Rs.5,000 Cr) that funds net-bought in bulk/block deals
    over the last `days` days: who, net value, % of market cap. `funds_only`
    keeps the institutional client types (insiders_clean/participants.py);
    without the type column (older clean tables) every real client counts."""
    if deals is None or deals.empty:
        return pd.DataFrame()
    d = deals.copy()
    d['date'] = pd.to_datetime(d['date'], errors='coerce')
    mm = d['client_is_market_maker'].astype('boolean').fillna(False) if 'client_is_market_maker' in d else False
    d = d[(~mm) & d['is_primary'].astype('boolean').fillna(False)]
    if funds_only and 'client_type' in d:   # the title says funds (audit W18)
        d = d[d['client_type'].isin(FUND_TYPES)]
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
    """Per company, who bought: e.g. '1 director, 2 promoters · 4 trades', with
    '· 2 decision-makers' when the promoter group (or one family) counts once."""
    w = t[(t['side'] == 'BUY') & t['person_role'].isin(DECISION_ROLES) & ~t['is_token']
          & (t['seen'] <= ref) & (t['seen'] > ref - pd.Timedelta(days=days))].dropna(subset=['isin'])
    out = {}
    for isin, g in w.groupby('isin'):
        uniq = g.drop_duplicates('person_id')
        people = uniq['person_role'].map(ROLE_WORDS).value_counts()
        parts = [f'{n} ' + ('promoter-group members' if r == 'promoter group' and n > 1 else
                            r + ('s' if n > 1 and r != 'KMP' else '')) for r, n in people.items()]
        k = decision_makers(uniq).nunique()
        dm = (f' · {k} decision-maker' + ('s' if k != 1 else '')) if k < len(uniq) else ''
        out[isin] = f'{", ".join(parts)}{dm} · {len(g)} trade' + ('s' if len(g) != 1 else '')
    return pd.Series(out, dtype=object)


def with_tradability(df: pd.DataFrame, trad: pd.DataFrame | None) -> pd.DataFrame:
    """Adds `trade_flags` and `trade_flag_notes` (lists, empty when NSE shows nothing) by ISIN from
    clean/current/tradability.parquet. A column, never a filter: surveillance, trade-for-trade, SME, a tight band or
    circuit-locked days are for the reader (and the lab) to weigh. Blank (None) where the ISIN is not in the table
    (BSE-only names, or no table yet). Today's flags only: they say nothing about the day of an older filing."""
    if df is None or df.empty or 'isin' not in df:
        return df
    if trad is None or trad.empty:
        return df.assign(trade_flags=None, trade_flag_notes=None)
    t = trad.drop_duplicates('isin').set_index('isin')
    as_list = lambda v: list(v) if v is not None and not isinstance(v, float) else None  # noqa: E731
    return df.assign(trade_flags=df['isin'].map(t['trade_flags']).map(as_list),
                     trade_flag_notes=df['isin'].map(t['trade_flag_notes']).map(as_list))


def deals_also_filed(deals: pd.DataFrame, trades: pd.DataFrame) -> pd.Series:
    """True for a bulk/block deal that is the same trade as an insider's own
    filing: the same person (client_id = person_id, one key space), company and
    side, with the deal's date inside the filing's trade dates. Such a buy is
    counted once, under the insider (audit W7, D6)."""
    out = pd.Series(False, index=deals.index)
    if deals is None or deals.empty or trades is None or trades.empty:
        return out
    t = trades.dropna(subset=['isin', 'person_id']).copy()
    t['_to'] = pd.to_datetime(t['trade_date_to'], errors='coerce')
    t['_from'] = pd.to_datetime(t['trade_date_from'], errors='coerce').fillna(t['_to'])
    t = t.dropna(subset=['_to'])
    key = t.groupby(['isin', 'person_id', 'side'])
    spans = {k: list(zip(g['_from'], g['_to'])) for k, g in key}
    dd = pd.to_datetime(deals['date'], errors='coerce')
    for i, isin, cid, side, day in zip(deals.index, deals['isin'], deals['client_id'], deals['side'], dd):
        for a, b in spans.get((isin, cid, side), ()):
            if pd.notna(day) and a.normalize() <= day.normalize() <= b.normalize():
                out.at[i] = True
                break
    return out
