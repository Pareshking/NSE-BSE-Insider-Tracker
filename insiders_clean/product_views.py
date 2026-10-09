"""Pure functions behind the Phase 3 pages (no Streamlit, no I/O) so they can be tested.

Labels follow docs/RESEARCH.md: no insider-buy or deal signal has a proven edge (section J.3), so these are
review lists, not alerts. Insider sells are a caution flag, not a trade signal.
"""
from __future__ import annotations

import pandas as pd

from . import events as evm

LAKH = 1e5
NO_EDGE_NOTE = ('No proven edge: in the Jan-Jun 2026 development sample promoter buys beat Nifty 500, but so did insider '
                'sells and most events are micro caps, so this is not evidence of insider information '
                '(docs/RESEARCH.md J.3). This is a review list, not a buy signal.')


def _window(ev: pd.DataFrame, asof, days: int) -> pd.DataFrame:
    d = pd.to_datetime(ev['broadcast_date'])
    return ev[(d <= pd.Timestamp(asof)) & (d > pd.Timestamp(asof) - pd.Timedelta(days=int(days)))]


BADGE_ACCUMULATION = 'Contextual Accumulation (No Proven Standalone Edge)'
MIN_PCT_OF_MCAP = 0.05      # percent of market cap (proxy for share of equity)



WINDOWS = (90, 180, 365)    # 1 quarter, 2 quarters (SEBI contra-trade window), trailing year
CAMPAIGN_GAP_DAYS = 90      # buys separated by no more than a quarter belong to one campaign
BADGE_ESTIMATE = 'pct_of_mcap is ESTIMATED: value / market cap on the disclosure day, a proxy for share of equity'


def _signed_promoter(trades: pd.DataFrame) -> pd.DataFrame:
    """Promoter / promoter-group open-market events with buys positive and sells negative (value and % of market cap)."""
    parts = []
    for side, sign in (('BUY', 1), ('SELL', -1)):
        e = evm.insider_events(trades, side, roles=evm.PROMOTER_ROLES)
        parts.append(e.assign(value=e['value'] * sign, pct_of_mcap=e['pct_of_mcap'] * sign))
    return pd.concat(parts, ignore_index=True)


def promoter_absorption(trades: pd.DataFrame, asof, windows=WINDOWS, min_value: float = 25 * LAKH,
                        min_pct: float = MIN_PCT_OF_MCAP) -> pd.DataFrame:
    """Cumulative promoter NET open-market flow (buys minus sells) per security over each window, and the net share of
    market cap absorbed (ESTIMATED proxy). `sustained` = net positive in every window with data. A security shows when
    any window nets at least `min_value` or `min_pct` percent of market cap. The clean layer starts 1 Jan 2026, so the
    365-day window covers only the data we hold; `history_days` says how much."""
    ev = _signed_promoter(trades)
    cols = ['isin', 'company', *[f'net_{w}d' for w in windows], *[f'pct_{w}d' for w in windows],
            *[f'gross_sold_{w}d' for w in windows], 'sustained', 'last_buy', 'badge']
    if ev.empty:
        return pd.DataFrame(columns=cols)
    g = pd.DataFrame({'isin': ev['isin'].unique()})
    for w in windows:
        win = _window(ev, asof, w)
        a = win.groupby('isin').agg(**{f'net_{w}d': ('value', 'sum'), f'pct_{w}d': ('pct_of_mcap', 'sum')})
        a[f'gross_sold_{w}d'] = -win[win['value'] < 0].groupby('isin')['value'].sum()
        g = g.merge(a, left_on='isin', right_index=True, how='left')
    num = [c for c in g.columns if c != 'isin']
    g[num] = g[num].fillna(0.0)
    names = trades.dropna(subset=['isin']).drop_duplicates('isin').set_index('isin')['company'] if 'company' in trades else None
    g['company'] = g['isin'].map(names) if names is not None else g['isin']
    nets = g[[f'net_{w}d' for w in windows]]
    g['sustained'] = (nets > 0).all(axis=1)
    lb = ev[ev['value'] > 0].groupby('isin')['broadcast_date'].max()
    g['last_buy'] = g['isin'].map(lb)
    g['badge'] = BADGE_ACCUMULATION
    big = pd.Series(False, index=g.index)
    for w in windows:
        big |= (g[f'net_{w}d'] >= min_value) | (g[f'pct_{w}d'] >= min_pct)
    g = g[big].sort_values(['sustained', f'net_{windows[-1]}d'], ascending=False)
    return g[cols].reset_index(drop=True)


def campaigns(trades: pd.DataFrame, asof, days: int = 365, gap_days: int = CAMPAIGN_GAP_DAYS,
              min_value: float = 25 * LAKH) -> pd.DataFrame:
    """Promoter buy events grouped into multi-quarter campaigns: consecutive buy days at most `gap_days` apart share a
    campaign. Gross buys and the sales inside the campaign span are both shown, so a buy-then-sell is visible."""
    buys = _window(evm.insider_events(trades, 'BUY', roles=evm.PROMOTER_ROLES), asof, days)
    sells = _window(evm.insider_events(trades, 'SELL', roles=evm.PROMOTER_ROLES), asof, days)
    cols = ['isin', 'company', 'start', 'end', 'span_days', 'buy_days', 'bought', 'sold', 'net', 'pct_of_mcap']
    if buys.empty:
        return pd.DataFrame(columns=cols)
    b = buys.sort_values(['isin', 'broadcast_date']).copy()
    new = b.groupby('isin')['broadcast_date'].diff().dt.days.gt(gap_days).fillna(True)
    b['cid'] = new.cumsum()
    rows = []
    for _, c in b.groupby('cid'):
        isin, start, end = c['isin'].iloc[0], c['broadcast_date'].min(), c['broadcast_date'].max()
        s = sells[(sells['isin'] == isin) & (sells['broadcast_date'] >= start) & (sells['broadcast_date'] <= end)]
        rows.append(dict(isin=isin, start=start, end=end, span_days=int((end - start).days), buy_days=int(c['broadcast_date'].nunique()),
                         bought=c['value'].sum(), sold=s['value'].sum(), net=c['value'].sum() - s['value'].sum(),
                         pct_of_mcap=c['pct_of_mcap'].sum() - s['pct_of_mcap'].sum()))
    out = pd.DataFrame(rows)
    names = trades.dropna(subset=['isin']).drop_duplicates('isin').set_index('isin')['company'] if 'company' in trades else None
    out['company'] = out['isin'].map(names) if names is not None else out['isin']
    return out[out['net'] >= min_value].sort_values('net', ascending=False)[cols].reset_index(drop=True)


def promoter_selling(trades: pd.DataFrame, asof, windows=WINDOWS, min_value: float = 25 * LAKH) -> pd.DataFrame:
    """Cumulative promoter net SELLING (sales minus buys, positive = net seller) per security over each window."""
    ev = _signed_promoter(trades)
    cols = ['isin', 'company', *[f'sold_{w}d' for w in windows], *[f'pct_{w}d' for w in windows]]
    if ev.empty:
        return pd.DataFrame(columns=cols)
    g = pd.DataFrame({'isin': ev['isin'].unique()})
    for w in windows:
        a = _window(ev, asof, w).groupby('isin').agg(**{f'sold_{w}d': ('value', lambda s: -s.sum()), f'pct_{w}d': ('pct_of_mcap', lambda s: -s.sum())})
        g = g.merge(a, left_on='isin', right_index=True, how='left')
    num = [c for c in g.columns if c != 'isin']
    g[num] = g[num].fillna(0.0)
    names = trades.dropna(subset=['isin']).drop_duplicates('isin').set_index('isin')['company'] if 'company' in trades else None
    g['company'] = g['isin'].map(names) if names is not None else g['isin']
    keep = pd.Series(False, index=g.index)
    for w in windows:
        keep |= g[f'sold_{w}d'] >= min_value
    return g[keep].sort_values(f'sold_{windows[-1]}d', ascending=False)[cols].reset_index(drop=True)


def block_bulk_accumulation(deals: pd.DataFrame, asof, days: int = 90, min_value: float = 1e7) -> pd.DataFrame:
    """Net-buy bulk/block deals per security (market makers excluded), by net value over the last `days`."""
    ev = _window(evm.deal_events(deals), asof, days)
    if ev.empty:
        return pd.DataFrame(columns=['isin', 'net_value', 'days'])
    g = ev.groupby('isin').agg(net_value=('net_value', 'sum'), days=('broadcast_date', 'nunique')).reset_index()
    return g[g['net_value'] >= min_value].sort_values('net_value', ascending=False).reset_index(drop=True)


def audit_table(trades: pd.DataFrame, deals: pd.DataFrame, isin: str) -> pd.DataFrame:
    """Chronological list of the filings and deals behind the chart for one security, newest first, with the
    exchange's own file link where the clean layer carries one (NSE insider filings)."""
    t = trades[trades['isin'] == isin]
    rows = pd.DataFrame({'date': pd.to_datetime(t['broadcast_date']), 'kind': 'Insider ' + t['side'].fillna('?').astype(str)
                         + t['is_market'].map(lambda v: '' if str(v).lower() in ('true', '1') else ' (non-market)'),
                         'who': t.get('person_role'), 'value': t['value'], 'quantity': t['quantity'], 'exchange': t['exchange'],
                         'link': t['source_url'] if 'source_url' in t else None, 'id': t['trade_id']})
    d = deals[deals['isin'] == isin]
    if len(d):
        dd = pd.DataFrame({'date': pd.to_datetime(d['date']), 'kind': 'Deal ' + d.get('feeds', pd.Series('', index=d.index)).astype(str)
                           + ' ' + d['side'].fillna('?').astype(str), 'who': d.get('client_name'), 'value': d['value'],
                           'quantity': d['quantity'], 'exchange': d['exchange'], 'link': None, 'id': d.get('deal_id')})
        rows = pd.concat([rows, dd], ignore_index=True)
    return rows.sort_values('date', ascending=False).reset_index(drop=True)


def freshness(frames: dict[str, tuple[pd.DataFrame, str]], today=None) -> pd.DataFrame:
    """name -> (frame, date column): rows, latest date and age in days."""
    today = pd.Timestamp(today or pd.Timestamp.now().normalize())
    rows = []
    for name, (df, col) in frames.items():
        last = pd.to_datetime(df[col], errors='coerce').max() if df is not None and len(df) and col in df else pd.NaT
        rows.append({'dataset': name, 'rows': 0 if df is None else int(len(df)),
                     'latest': last, 'age_days': None if pd.isna(last) else int((today - last).days)})
    return pd.DataFrame(rows)


def active_campaigns(trades: pd.DataFrame, asof, gap_days: int = CAMPAIGN_GAP_DAYS) -> pd.DataFrame:
    """The latest promoter buying campaign per security (all stored history). `active` = at least two buy days and the
    last buy within `gap_days` of `asof`, i.e. the campaign could still extend under the same gap rule."""
    c = campaigns(trades, asof, days=10_000, gap_days=gap_days, min_value=float('-inf'))
    cols = ['isin', 'campaign_start', 'campaign_end', 'campaign_buys', 'active', 'span']
    if c.empty:
        return pd.DataFrame(columns=cols)
    c = c.sort_values('end').drop_duplicates('isin', keep='last')
    out = pd.DataFrame({'isin': c['isin'], 'campaign_start': c['start'], 'campaign_end': c['end'], 'campaign_buys': c['buy_days']})
    out['active'] = (out['campaign_buys'] >= 2) & ((pd.Timestamp(asof) - out['campaign_end']).dt.days <= gap_days)
    out['span'] = [f"{s:%d %b %y} - {e:%d %b %y} ({n} buy days)" if n > 1 else f"{s:%d %b %y} (1 buy day)"
                   for s, e, n in zip(out['campaign_start'], out['campaign_end'], out['campaign_buys'])]
    return out[cols].reset_index(drop=True)


HORIZONS = {'90D': 90, '180D': 180, '365D': 365}
BUCKET_ORDER = ('Large', 'Mid', 'Small', 'Micro')


def screen(acc: pd.DataFrame, summary: pd.DataFrame | None, camps: pd.DataFrame | None, horizon: str = '180D',
           min_net: float = 25 * LAKH, min_pct: float = 0.0, buckets=BUCKET_ORDER, active_only: bool = False,
           min_drawdown: float = 0.0, exclude_sellers: bool = False) -> pd.DataFrame:
    """Promoter accumulation screen over the output of `promoter_absorption`. `horizon` is 90D / 180D / 365D, or
    'Sustained' (net positive in all three windows; the thresholds then apply to the 365-day figures). `min_pct` is in
    percent of market cap (ESTIMATED proxy). `min_drawdown` is a fraction (0.15 = at least 15% below the 52-week
    high) and needs the price summary. `exclude_sellers` drops any security with promoter sales in the window."""
    d = acc.copy()
    w = 365 if horizon == 'Sustained' else HORIZONS[horizon]
    if horizon == 'Sustained':
        d = d[d['sustained']]
    d['net'], d['pct'], d['sold'] = d[f'net_{w}d'], d[f'pct_{w}d'], d[f'gross_sold_{w}d']
    d = d[(d['net'] >= min_net) & (d['pct'] >= min_pct)]
    if exclude_sellers:
        d = d[d['sold'].fillna(0) <= 0]
    if summary is not None and len(summary):
        d = d.merge(summary[['isin', 'symbol', 'mcap_bucket', 'pct_off_high']], on='isin', how='left')
    else:
        d['symbol'], d['mcap_bucket'], d['pct_off_high'] = None, None, float('nan')
    if set(buckets) != set(BUCKET_ORDER):          # all four selected = no filter, so unclassified names stay
        d = d[d['mcap_bucket'].isin(buckets)]
    if min_drawdown > 0:
        d = d[d['pct_off_high'] <= -min_drawdown]
    if camps is not None and len(camps):
        d = d.merge(camps, on='isin', how='left')
    else:
        d['span'], d['active'] = None, False
    d['active'] = d['active'].eq(True)
    if active_only:
        d = d[d['active']]
    return d.sort_values('net', ascending=False).reset_index(drop=True)


def badge_text(net_180d: float, active: bool) -> str:
    """Inline badge for feeds: [Promoter Net: +Rs X Cr (180D) | Active Campaign | Contextual Accumulation]."""
    parts = [f'Promoter Net: {"+" if net_180d >= 0 else "-"}\u20b9{abs(net_180d) / 1e7:.2f} Cr (180D)']
    if active:
        parts.append('Active Campaign')
    parts.append('Contextual Accumulation')
    return '[' + ' | '.join(parts) + ']'


def accumulation_badges(trades: pd.DataFrame, asof, min_net: float = 25 * LAKH) -> dict[str, str]:
    """ISIN -> badge text for securities with promoter net buying of at least `min_net` over 180 days."""
    acc = promoter_absorption(trades, asof, min_value=1)
    acc = acc[acc['net_180d'] >= min_net]
    camps = active_campaigns(trades, asof).set_index('isin')['active'] if len(acc) else pd.Series(dtype=bool)
    return {r.isin: badge_text(r.net_180d, bool(camps.get(r.isin, False))) for r in acc.itertuples()}


def deal_alignment(deals: pd.DataFrame, camps: pd.DataFrame, asof) -> pd.DataFrame:
    """Does bulk/block net buying coincide with the latest promoter campaign? Per security: net deal value (market makers
    excluded, buys positive) on deal days from the campaign start to its end (to `asof` while the campaign is active), and
    the number of deal days. Deals carry no reliable FII/DII label, so this says only that large deals coincided."""
    cols = ['isin', 'deal_net', 'deal_days', 'deal_coincides']
    if camps is None or camps.empty or deals is None or deals.empty:
        return pd.DataFrame(columns=cols)
    ev = evm.deal_events(deals)
    c = camps.set_index('isin')
    ev = ev[ev['isin'].isin(c.index)].copy()
    if ev.empty:
        return pd.DataFrame(columns=cols)
    ev['lo'] = ev['isin'].map(c['campaign_start'])
    ev['hi'] = [pd.Timestamp(asof) if c.at[i, 'active'] else c.at[i, 'campaign_end'] for i in ev['isin']]
    ev = ev[(ev['broadcast_date'] >= ev['lo']) & (ev['broadcast_date'] <= ev['hi'])]
    if ev.empty:
        return pd.DataFrame(columns=cols)
    g = ev.groupby('isin').agg(deal_net=('net_value', 'sum'), deal_days=('broadcast_date', 'nunique')).reset_index()
    g['deal_coincides'] = g['deal_net'] > 0
    return g[cols]
