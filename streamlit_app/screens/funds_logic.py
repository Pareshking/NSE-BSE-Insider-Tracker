"""The Funds explorer's arithmetic, apart from the page so it can be tested without Streamlit.

Everything here reads the clean fund tables as they are written by scripts/mf_portfolios.py (insiders_clean/mf_holdings.py):

    mf_changes      per house, month, ISIN: shares and active shares at the two month-ends, `change`, `active_change`,
                    `kind` (new / added / cut / exit / held / passive), `house_kind` (mf / pension)
    mf_stock_month  per month, house kind, ISIN: `price` (the houses' filed value over their shares), houses adding ...
    mf_coverage     quarter-end months: collected mutual fund houses' shares against the mutual-fund shares filed

A window is one month-end or several in a row ("last 3 months"): a house's net is the sum of its monthly changes, and
its status compares what it held at the window's start with what it holds at its end, so "new" over 6 months means a
house that held none six month-ends ago and holds some now. Rupees are each month's change at that month's filed
price; a stock every collected house left in a month has no filed price that month and is valued at the month-end
before (the price the houses last valued it at), never at a price from elsewhere.

Active (the default) reads active schemes only (index funds and ETFs, which buy by rule, kept apart); `passive=True`
reads every scheme.
"""
from __future__ import annotations

import pandas as pd

MIN_NET_CR = 1.0           # a stock's net buying or selling under Rs 1 Cr is counted, not listed
COMPLETE_SHARE = 0.9       # a month is complete when at least this share of the most houses ever compared is in it
RANGES = {'Month': 1, '3 months': 3, '6 months': 6, '12 months': 12}
LEVELS = ('macro', 'sector', 'industry', 'basic_industry')
LEVEL_LABEL = {'macro': 'Macro sector', 'sector': 'Sector', 'industry': 'Industry', 'basic_industry': 'Basic industry'}
UNCLASSIFIED = 'Not classified'
STATUS_WORD = {'new': 'New', 'added': 'Added', 'cut': 'Cut', 'exit': 'Sold out', 'held': 'Held', 'none': 'In and out'}


def by_kind(df: pd.DataFrame | None, kind: str) -> pd.DataFrame | None:
    """Rows of one house kind: 'mf' (mutual funds; a table written before the column existed is all mutual funds) or
    'pension' (NPS pension fund managers)."""
    if df is None or df.empty:
        return df
    k = df['house_kind'].astype(object).fillna('mf') if 'house_kind' in df else pd.Series('mf', index=df.index)
    return df[k == kind]


def months(df: pd.DataFrame | None) -> list[str]:
    """The month-ends in a table, newest first."""
    return sorted(df['month'].dropna().unique(), reverse=True) if df is not None and not df.empty and 'month' in df else []


def houses_by_month(ch: pd.DataFrame | None) -> dict:
    """{month: fund houses compared that month} (a house is compared when it was collected at both month-ends)."""
    if ch is None or ch.empty:
        return {}
    return {m: int(n) for m, n in ch.groupby('month')['amc'].nunique().items()}


def default_month(ch: pd.DataFrame | None, ms: list[str] | None = None) -> str | None:
    """The newest complete month: the newest with at least COMPLETE_SHARE of the most houses compared in any month.
    A month still coming in (the houses file by the 10th; a backfill month half done) is offered, not opened on."""
    ms = ms if ms is not None else months(ch)
    if not ms:
        return None
    n = houses_by_month(ch)
    if not n:
        return ms[0]
    top = max(n.values())
    return next((m for m in ms if n.get(m, 0) >= COMPLETE_SHARE * top), ms[0])


def window(ms: list[str], month: str, n: int) -> list[str]:
    """The `n` month-ends up to and including `month`, oldest first (fewer when the data starts later)."""
    up = sorted(m for m in ms if m <= month)
    return up[-n:] if n > 0 else up[-1:]


def _prices(stock: pd.DataFrame) -> pd.DataFrame:
    """(month, isin) -> price, with the month-end before's price where no collected house holds it any more."""
    if stock is None or stock.empty or 'price' not in stock:
        return pd.DataFrame(columns=['month', 'isin', 'price'])
    p = stock[['month', 'isin', 'price']].drop_duplicates(['month', 'isin']).sort_values(['isin', 'month'])
    before = p.groupby('isin')['price'].shift(1)
    p = p.assign(price=p['price'].fillna(before))
    return p


def house_rows(ch: pd.DataFrame, stock: pd.DataFrame, ms: list[str], houses: list[str] | None = None,
               passive: bool = False) -> pd.DataFrame:
    """One row per house and ISIN over the window `ms`: shares at its start and end, net shares, net rupees (crore),
    status (new / added / cut / exit / held / none). `houses`: only these house keys (None: all)."""
    cols = ['amc', 'isin', 'name', 'start', 'end', 'net', 'net_cr', 'status', 'last_month']
    if ch is None or ch.empty or not ms:
        return pd.DataFrame(columns=cols)
    c = ch[ch['month'].isin(ms)]
    if houses:
        c = c[c['amc'].isin(houses)]
    if c.empty:
        return pd.DataFrame(columns=cols)
    after, before, delta = ('shares', 'shares_before', 'change') if passive else ('active_shares', 'active_before', 'active_change')
    c = c[['amc', 'month', 'isin', 'name', after, before, delta]].merge(_prices(stock), on=['month', 'isin'], how='left')
    c['_cr'] = c[delta] * c['price'] / 1e7
    # The house's own first and last month in the window: a stock it did not hold at either end of an earlier pair
    # has no row then, so its start is zero; a stock with no row in the house's last month is no longer held.
    first = c.groupby('amc')['month'].transform('min')
    last = c.groupby('amc')['month'].transform('max')
    c = c.sort_values('month')
    c['_start'] = c[before].where(c['month'].eq(first), 0.0)
    c['_end'] = c[after].where(c['month'].eq(last), 0.0)
    g = c.groupby(['amc', 'isin'], sort=False)
    out = g.agg(name=('name', 'last'), start=('_start', 'first'), end=('_end', 'last'), net=(delta, 'sum'),
                net_cr=('_cr', 'sum'), _n=('_cr', 'count'), last_month=('month', 'max')).reset_index()
    out['net_cr'] = out['net_cr'].where(out.pop('_n').gt(0))   # no month valued: blank, not zero
    s, e = out['start'], out['end']
    out['status'] = 'held'
    out.loc[s.gt(0) & e.gt(0) & out['net'].gt(0), 'status'] = 'added'
    out.loc[s.gt(0) & e.gt(0) & out['net'].lt(0), 'status'] = 'cut'
    out.loc[s.eq(0) & e.gt(0), 'status'] = 'new'
    out.loc[s.gt(0) & e.eq(0), 'status'] = 'exit'
    out.loc[s.eq(0) & e.eq(0), 'status'] = 'none'   # bought and sold out inside the window, or held only by index funds
    return out[cols]


def stock_window(hr: pd.DataFrame, total_shares: dict | None = None) -> pd.DataFrame:
    """Per ISIN from `house_rows`: houses adding, cutting, new, exiting, holding at the end; net shares and rupees;
    the rupees of the new positions and of the exits; % of the company where its total shares are known."""
    cols = ['isin', 'name', 'houses_adding', 'houses_cutting', 'houses_new', 'houses_exit', 'houses_holding', 'net',
            'net_cr', 'new_cr', 'exit_cr', 'pct_of_company']
    if hr is None or hr.empty:
        return pd.DataFrame(columns=cols)
    x = hr.assign(_add=hr['net'].gt(0), _cut=hr['net'].lt(0), _new=hr['status'].eq('new'), _exit=hr['status'].eq('exit'),
                  _hold=hr['end'].gt(0), _ncr=hr['net_cr'].where(hr['status'].eq('new')),
                  _xcr=hr['net_cr'].where(hr['status'].eq('exit')))
    out = x.groupby('isin', sort=False).agg(
        name=('name', 'last'), houses_adding=('_add', 'sum'), houses_cutting=('_cut', 'sum'), houses_new=('_new', 'sum'),
        houses_exit=('_exit', 'sum'), houses_holding=('_hold', 'sum'), net=('net', 'sum'), net_cr=('net_cr', 'sum'),
        new_cr=('_ncr', 'sum'), exit_cr=('_xcr', 'sum'), _n=('net_cr', 'count'), _nn=('_ncr', 'count'),
        _nx=('_xcr', 'count')).reset_index()
    for k, n in (('net_cr', '_n'), ('new_cr', '_nn'), ('exit_cr', '_nx')):   # a blank stays blank, not zero
        out[k] = out[k].where(out.pop(n).gt(0))
    for k in ('houses_adding', 'houses_cutting', 'houses_new', 'houses_exit', 'houses_holding'):
        out[k] = out[k].astype(int)
    tot = pd.to_numeric(out['isin'].map(total_shares or {}), errors='coerce')
    out['pct_of_company'] = (out['net'] / tot * 100).where(tot.gt(0))
    return out[cols]


def lists(sw: pd.DataFrame, min_cr: float = MIN_NET_CR) -> dict:
    """The page's four lists from `stock_window`: bought and sold (net Rs `min_cr` Cr and over, by rupees), new
    entries (stocks where a house opened a position, most houses first) and complete exits (most houses first), and
    how many stocks moved by less than `min_cr`."""
    if sw is None or sw.empty:
        e = sw if sw is not None else pd.DataFrame()
        return {'bought': e, 'sold': e, 'new': e, 'exits': e, 'small': 0}
    big = sw['net_cr'].abs().ge(min_cr)
    return {
        'bought': sw[big & sw['net_cr'].gt(0)].sort_values('net_cr', ascending=False),
        'sold': sw[big & sw['net_cr'].lt(0)].sort_values('net_cr'),
        'new': sw[sw['houses_new'].ge(1)].sort_values(['houses_new', 'new_cr'], ascending=False, na_position='last'),
        'exits': sw[sw['houses_exit'].ge(1)].sort_values(['houses_exit', 'exit_cr'], ascending=[False, True], na_position='last'),
        'small': int((~big & sw['net'].ne(0)).sum()),
    }


def kpis(sw: pd.DataFrame, hr: pd.DataFrame) -> dict:
    """The window's figures: net rupees (crore; blank values left out), stocks bought and sold (any amount), positions
    opened and closed and in how many stocks, the most bought and most sold stock (by rupees)."""
    if sw is None or sw.empty:
        return {'net_cr': 0.0, 'bought': 0, 'sold': 0, 'new_positions': 0, 'new_stocks': 0, 'exit_positions': 0,
                'exit_stocks': 0, 'top_bought': None, 'top_sold': None, 'unvalued': 0}
    v = sw.dropna(subset=['net_cr'])
    up, dn = v[v['net_cr'].gt(0)], v[v['net_cr'].lt(0)]
    return {
        'net_cr': float(v['net_cr'].sum()),
        'bought': int(sw['net'].gt(0).sum()), 'sold': int(sw['net'].lt(0).sum()),
        'new_positions': int(hr['status'].eq('new').sum()), 'new_stocks': int(sw['houses_new'].gt(0).sum()),
        'exit_positions': int(hr['status'].eq('exit').sum()), 'exit_stocks': int(sw['houses_exit'].gt(0).sum()),
        'top_bought': up.sort_values('net_cr', ascending=False).iloc[0].to_dict() if len(up) else None,
        'top_sold': dn.sort_values('net_cr').iloc[0].to_dict() if len(dn) else None,
        'unvalued': int((sw['net_cr'].isna() & sw['net'].ne(0)).sum()),
    }


# ---- Filters -----------------------------------------------------------------------------------------------------

def industry_frame(industry: pd.DataFrame | None, securities: pd.DataFrame | None) -> pd.DataFrame:
    """isin -> macro, sector, industry, basic_industry: the four-level classification (`industry` table) where it has
    rows, else the security master's sector and industry (two levels; macro and basic industry blank)."""
    if industry is not None and not industry.empty and 'isin' in industry and any(c in industry for c in LEVELS):
        d = industry.dropna(subset=['isin']).drop_duplicates('isin', keep='last')
        return d.reindex(columns=['isin', *LEVELS]).reset_index(drop=True)
    if securities is not None and not securities.empty and 'isin' in securities and ('sector' in securities or 'industry' in securities):
        d = securities.dropna(subset=['isin']).drop_duplicates('isin')
        return d.reindex(columns=['isin', *LEVELS]).reset_index(drop=True)
    return pd.DataFrame(columns=['isin', *LEVELS])


def _clean(s: pd.Series) -> pd.Series:
    s = s.astype('string').str.strip()
    return s.where(s.ne('') & s.notna())


def levels_with_data(ind: pd.DataFrame) -> list[str]:
    """The classification levels that have any value (a level with none is not offered)."""
    return [lv for lv in LEVELS if lv in ind and _clean(ind[lv]).notna().any()]


def cascade_options(ind: pd.DataFrame, picks: dict) -> dict:
    """{level: sorted values} for each level with data, each narrowed by the picks of the levels above it."""
    out, d = {}, ind
    for lv in levels_with_data(ind):
        out[lv] = sorted(_clean(d[lv]).dropna().unique().tolist())
        if picks.get(lv):
            d = d[_clean(d[lv]).eq(picks[lv])]
    return out


def filter_isins(ind: pd.DataFrame, picks: dict) -> set | None:
    """ISINs matching every picked level; None when nothing is picked (no filter)."""
    picks = {k: v for k, v in picks.items() if v}
    if not picks:
        return None
    d = ind
    for lv, v in picks.items():
        if lv in d:
            d = d[_clean(d[lv]).eq(v)]
    return set(d['isin'])


def next_level(ind: pd.DataFrame, picks: dict) -> str | None:
    """The level to roll up by: the one under the deepest pick (sector when nothing is picked and it has data), or
    the deepest level picked when there is none under it."""
    lv = levels_with_data(ind)
    if not lv:
        return None
    picked = [x for x in lv if picks.get(x)]
    if not picked:
        return 'sector' if 'sector' in lv else lv[0]
    i = lv.index(picked[-1])
    return lv[i + 1] if i + 1 < len(lv) else lv[i]


def mcap_isins(prices: pd.DataFrame | None, buckets: list[str] | None) -> set | None:
    """ISINs in the picked market-cap buckets (slim prices' `mcap_bucket`); None when none is picked."""
    if not buckets:
        return None
    if prices is None or prices.empty or 'mcap_bucket' not in prices:
        return set()
    return set(prices.loc[prices['mcap_bucket'].isin(buckets), 'isin'])


def apply_isins(df: pd.DataFrame, *sets) -> pd.DataFrame:
    """Rows whose ISIN is in every given set (a None set does not filter)."""
    for s in sets:
        if s is not None and df is not None and not df.empty:
            df = df[df['isin'].isin(s)]
    return df


def rollup(sw: pd.DataFrame, ind: pd.DataFrame, level: str | None) -> pd.DataFrame:
    """Net rupees (crore) per value of `level`, most bought first: label, net_cr, stocks, bought, sold. Stocks with no
    classification are one row, 'Not classified'; stocks with no rupee value are left out of the sum."""
    cols = ['label', 'net_cr', 'stocks', 'bought', 'sold']
    if sw is None or sw.empty or not level:
        return pd.DataFrame(columns=cols)
    lab = sw['isin'].map(dict(zip(ind['isin'], _clean(ind[level])))) if level in ind else pd.Series(index=sw.index, dtype=object)
    x = sw.assign(label=lab.fillna(UNCLASSIFIED).astype(str)).dropna(subset=['net_cr'])
    if x.empty:
        return pd.DataFrame(columns=cols)
    out = x.groupby('label').agg(net_cr=('net_cr', 'sum'), stocks=('isin', 'nunique'),
                                 bought=('net_cr', lambda s: float(s[s > 0].sum())),
                                 sold=('net_cr', lambda s: float(s[s < 0].sum()))).reset_index()
    return out.sort_values('net_cr', ascending=False).reset_index(drop=True)[cols]


def coverage_at(cov: pd.DataFrame | None, month: str) -> dict | None:
    """The coverage measured at the quarter end at or before `month` (the latest one when none is that early)."""
    if cov is None or cov.empty or 'weighted_ratio' not in cov:
        return None
    c = cov.dropna(subset=['weighted_ratio']).sort_values('month')
    if c.empty:
        return None
    on = c[c['month'] <= month]
    return (on if len(on) else c).iloc[-1].to_dict()


def missing_houses(collected: set, catalogue: list, not_collected: list) -> dict:
    """Which mutual fund houses are in the month and which are not: `catalogue` (key, name) of every house the
    collector reads, `not_collected` (name, why) of houses it does not read. A house the collector reads but that
    is not in the month is named with 'not in this month'."""
    names = dict(catalogue)
    absent = [(names[k], 'collected, but not in this month (not filed or not read yet)') for k in names if k not in collected]
    return {'in': sorted(names[k] for k in collected if k in names), 'absent': absent, 'not_collected': list(not_collected)}


# ---- Lists by company size ---------------------------------------------------------------------------------------

def by_pct(sw: pd.DataFrame, side: str = 'buy') -> pd.DataFrame:
    """Stocks ranked by the share of the company bought (`side='buy'`) or sold, then houses adding (cutting), then
    rupees: where small and mid caps show, since rupees always put the largest companies on top. Stocks whose total
    shares are not known are left out (no share to rank by)."""
    if sw is None or sw.empty:
        return sw
    p = sw.dropna(subset=['pct_of_company'])
    if side == 'buy':
        return p[p['net'].gt(0)].sort_values(['pct_of_company', 'houses_adding', 'net_cr'], ascending=[False, False, False])
    return p[p['net'].lt(0)].sort_values(['pct_of_company', 'houses_cutting', 'net_cr'], ascending=[True, False, True])


def bucket_rollup(sw: pd.DataFrame, size: dict, buckets=('Large', 'Mid', 'Small', 'Micro')) -> pd.DataFrame:
    """Per market-cap bucket: net rupees (crore), stocks bought, stocks sold; stocks with no bucket as 'No size'."""
    cols = ['bucket', 'net_cr', 'bought', 'sold', 'stocks']
    if sw is None or sw.empty:
        return pd.DataFrame(columns=cols)
    x = sw.assign(bucket=sw['isin'].map(size).fillna('No size'), _b=sw['net'].gt(0), _s=sw['net'].lt(0))
    out = x.groupby('bucket').agg(net_cr=('net_cr', 'sum'), bought=('_b', 'sum'), sold=('_s', 'sum'),
                                  stocks=('isin', 'nunique')).reset_index()
    out[['bought', 'sold']] = out[['bought', 'sold']].astype(int)
    order = {b: i for i, b in enumerate(list(buckets) + ['No size'])}
    return out.sort_values('bucket', key=lambda s: s.map(order)).reset_index(drop=True)[cols]


def first_held(stock: pd.DataFrame | None, win: list[str]) -> set:
    """ISINs no collected house held at any earlier month-end: the first month the stock is in the table falls in the
    window, is later than the table's first month, and nobody held it at the month-end before. Usually a new listing
    (an IPO allotment), sometimes a first purchase of a listed stock; the page names both."""
    if stock is None or stock.empty or not win:
        return set()
    lo = stock['month'].min()
    s = stock.sort_values('month').drop_duplicates('isin')
    before = s['active_before'] if 'active_before' in s else pd.Series(0.0, index=s.index)
    hit = s['month'].isin(win) & s['month'].gt(lo) & pd.to_numeric(before, errors='coerce').fillna(0).eq(0)
    return set(s.loc[hit, 'isin'])


# ---- Bulk and block deals of the month so far ------------------------------------------------------------------

DEAL_TYPES = ('mutual_fund', 'insurer', 'pension', 'fpi', 'pms_aif', 'fund_other')


def deal_rows(deals: pd.DataFrame | None, start, end, types=DEAL_TYPES) -> pd.DataFrame:
    """Bulk and block deal legs from `start` to `end` (days, inclusive) by funds of `types` (the client type read from
    the name, insiders_clean/participants.py): primary legs, market makers and the company's own promoters out."""
    if deals is None or deals.empty or 'client_type' not in deals:
        return pd.DataFrame()
    d = deals
    if 'is_primary' in d:
        d = d[d['is_primary'].astype('boolean').fillna(False)]
    for flag in ('client_is_market_maker', 'client_is_promoter'):
        if flag in d:
            d = d[~d[flag].astype('boolean').fillna(False)]
    d = d[d['client_type'].isin(types)]
    dt = pd.to_datetime(d['date'], errors='coerce')
    d = d[dt.ge(pd.Timestamp(start).normalize()) & dt.lt(pd.Timestamp(end).normalize() + pd.Timedelta(days=1))]
    d = d.dropna(subset=['isin'])
    if d.empty:
        return d
    v = pd.to_numeric(d['signed_value'], errors='coerce') if 'signed_value' in d else \
        pd.to_numeric(d['value'], errors='coerce') * d['side'].map({'BUY': 1, 'SELL': -1})
    who = d['investor_group'] if 'investor_group' in d else d['client_name']
    return d.assign(_v=v, _who=who.where(who.notna(), d['client_name'])).dropna(subset=['_v'])


def deals_by_stock(d: pd.DataFrame) -> pd.DataFrame:
    """Per ISIN: net rupees by each fund type (a column per type), the net of all, gross bought and sold, how many
    named funds bought and sold, the largest buyers' names; largest net either way first."""
    cols = ['isin', 'company', 'net', 'bought', 'sold', 'buyers', 'sellers', 'top_buyers', *DEAL_TYPES]
    if d is None or d.empty:
        return pd.DataFrame(columns=cols)
    p = d.pivot_table(index='isin', columns='client_type', values='_v', aggfunc='sum', fill_value=0.0)
    p = p.reindex(columns=list(DEAL_TYPES), fill_value=0.0)
    x = d.assign(_b=d['_v'].clip(lower=0), _s=(-d['_v']).clip(lower=0))
    g = x.groupby('isin')
    out = pd.DataFrame({'company': g['company'].last() if 'company' in x else g['isin'].first(),
                        'net': g['_v'].sum(), 'bought': g['_b'].sum(), 'sold': g['_s'].sum(),
                        'buyers': x[x['_v'] > 0].groupby('isin')['_who'].nunique(),
                        'sellers': x[x['_v'] < 0].groupby('isin')['_who'].nunique()}).join(p)
    by = x[x['_v'] > 0].groupby(['isin', '_who'])['_v'].sum().reset_index().sort_values('_v', ascending=False)
    out['top_buyers'] = by.groupby('isin')['_who'].agg(lambda s: list(s.head(4)))
    out['top_buyers'] = out['top_buyers'].apply(lambda v: v if isinstance(v, list) else [])
    out[['buyers', 'sellers']] = out[['buyers', 'sellers']].fillna(0).astype(int)
    out = out.reset_index()
    return out.reindex(out['net'].abs().sort_values(ascending=False).index).reset_index(drop=True)[cols]


def deals_by_fund(d: pd.DataFrame) -> pd.DataFrame:
    """Per named fund (the investor group, else the name as filed): type, bought, sold, net, stocks, the stock with
    the largest net either way; largest net either way first."""
    cols = ['fund', 'type', 'bought', 'sold', 'net', 'stocks', 'largest', 'largest_isin', 'largest_net']
    if d is None or d.empty:
        return pd.DataFrame(columns=cols)
    x = d.assign(_b=d['_v'].clip(lower=0), _s=(-d['_v']).clip(lower=0))
    if 'company' not in x:
        x = x.assign(company=x['isin'])
    per = x.groupby(['_who', 'isin']).agg(net=('_v', 'sum'), company=('company', 'last')).reset_index()
    per = per.assign(_a=per['net'].abs()).sort_values('_a', ascending=False).drop_duplicates('_who').set_index('_who')
    g = x.groupby('_who')
    out = pd.DataFrame({'type': g['client_type'].agg(lambda s: s.mode().iloc[0]), 'bought': g['_b'].sum(),
                        'sold': g['_s'].sum(), 'net': g['_v'].sum(), 'stocks': g['isin'].nunique()})
    out = out.join(per[['company', 'isin', 'net']].rename(columns={'company': 'largest', 'isin': 'largest_isin',
                                                                    'net': 'largest_net'}))
    out = out.rename_axis('fund').reset_index()
    return out.reindex(out['net'].abs().sort_values(ascending=False).index).reset_index(drop=True)[cols]


# ---- Coverage --------------------------------------------------------------------------------------------------

MIN_COVERAGE_COMPANIES = 200   # under this many companies with the mutual-fund line read, coverage is not stated as a share


def quarter_month(ms: list[str], month: str) -> str | None:
    """The newest quarter-end month (Mar, Jun, Sep, Dec) at or before `month` among `ms`."""
    q = [m for m in ms if m <= month and int(m[5:7]) % 3 == 0]
    return max(q) if q else None


def coverage_live(ch: pd.DataFrame, stock: pd.DataFrame, shareholding: pd.DataFrame | None, qm: str | None) -> dict | None:
    """At quarter-end month `qm`: the shares the houses compared that month held (every scheme) against the
    mutual-fund shares each company filed for that quarter end, over every company with both, weighted by value at
    the houses' month-end price (share counts do not add across companies). With the number of companies the houses
    hold, so a ratio over a few companies reads as what it is."""
    if not qm or ch is None or ch.empty or shareholding is None or shareholding.empty or \
            not {'isin', 'quarter_end', 'mf_shares'} <= set(shareholding.columns):
        return None
    c = ch[ch['month'] == qm]
    held = c[c['shares'].gt(0)].groupby('isin')['shares'].sum()
    q = pd.to_datetime(shareholding['quarter_end'], errors='coerce').dt.to_period('M').astype(str)
    f = shareholding[q.eq(qm)].dropna(subset=['isin'])
    f = f.assign(_mf=pd.to_numeric(f['mf_shares'], errors='coerce')).dropna(subset=['_mf'])
    f = f[f['_mf'].gt(0)].drop_duplicates('isin', keep='last').set_index('isin')['_mf']
    both = held.index.intersection(f.index)
    out = {'month': qm, 'houses': int(c['amc'].nunique()), 'held_companies': int(len(held)), 'companies': int(len(both))}
    if not len(both):
        return out
    px = stock[stock['month'] == qm].drop_duplicates('isin').set_index('isin')['price'] \
        if stock is not None and not stock.empty else pd.Series(dtype=float)
    p = pd.to_numeric(px.reindex(both), errors='coerce')
    ok = (p.notna() & p.gt(0)).to_numpy()
    if ok.any():
        i = both[ok]
        out['ratio'] = float((held[i] * p[i]).sum() / (f[i] * p[i]).sum())
    else:
        out['ratio'] = float(held[both].sum() / f[both].sum())
    out['median_ratio'] = float((held[both] / f[both]).clip(upper=5).median())
    return out


# ---- How each house is positioning -----------------------------------------------------------------------------

BROAD_SHARE = 0.40   # a house moved this share or more of the positions it held the same way, on share counts: "broad"
TOP_N = 10           # concentration: the weight of a house's ten largest holdings


def _weights(v: pd.Series, key: pd.Series) -> pd.Series:
    t = v.sum()
    return (v.groupby(key).sum() / t * 100) if t > 0 else pd.Series(dtype=float)


def house_positioning(ch: pd.DataFrame, stock: pd.DataFrame, size: dict | None = None, sector: dict | None = None,
                      ms: list[str] | None = None) -> pd.DataFrame:
    """One row per house and month (active schemes): positions added, cut, new, exited; net rupees bought; that as a %
    of the house's equity before (`flow_pct`); the share of the positions it held that it trimmed (cut or sold out) and
    added to (breadth), flagged 'broad trim' / 'broad add' at BROAD_SHARE; the change in its large / mid / small /
    micro mix, its three largest sector shifts, and its top-10 weight before and after.

    Before and after are valued at the same price, this month-end's (the month-end before's for a stock no house holds
    now), so they differ only by share counts, which is the decision, never by the market: a fall in prices does not
    read as selling, and `flow_pct` is shares bought over shares held before, both at this month's price. A house
    whose schemes take in SIP money shows it as a flow spread over what it already holds; it is not told apart."""
    cols = ['amc', 'month', 'held_before', 'added', 'cut', 'new', 'exit', 'net_cr', 'prior_cr', 'flow_pct', 'trimmed_pct',
            'added_pct', 'broad', 'mix_shift', 'sector_shift', 'top10_before', 'top10_after']
    if ch is None or ch.empty:
        return pd.DataFrame(columns=cols)
    c = ch if ms is None else ch[ch['month'].isin(ms)]
    c = c[['amc', 'month', 'isin', 'active_shares', 'active_before', 'active_change', 'kind']].merge(
        _prices(stock), on=['month', 'isin'], how='left').dropna(subset=['price'])
    c = c.assign(v1=c['active_shares'] * c['price'], v0=c['active_before'] * c['price'], dv=c['active_change'] * c['price'])
    size, sector = size or {}, sector or {}
    c['_size'] = c['isin'].map(size).fillna('No size')
    c['_sec'] = c['isin'].map(sector).fillna(UNCLASSIFIED)
    rows = []
    for (amc, m), g in c.groupby(['amc', 'month'], sort=True):
        held = int(g['active_before'].gt(0).sum())
        kinds = g['kind'].value_counts()
        prior, net = float(g['v0'].sum()), float(g['dv'].sum())
        trimmed, added = int(kinds.get('cut', 0) + kinds.get('exit', 0)), int(kinds.get('added', 0))
        tp, ap = (trimmed / held, added / held) if held else (None, None)
        broad = ('broad trim' if tp is not None and tp >= BROAD_SHARE else
                 'broad add' if ap is not None and ap >= BROAD_SHARE else '')
        mix = _weights(g['v1'], g['_size']).subtract(_weights(g['v0'], g['_size']), fill_value=0)
        sec = _weights(g['v1'], g['_sec']).subtract(_weights(g['v0'], g['_sec']), fill_value=0)
        sec = sec.reindex(sec.abs().sort_values(ascending=False).index).head(3)
        top = lambda v: float(v.nlargest(TOP_N).sum() / v.sum() * 100) if v.sum() > 0 else None  # noqa: E731
        rows.append({'amc': amc, 'month': m, 'held_before': held, 'added': added, 'cut': int(kinds.get('cut', 0)),
                     'new': int(kinds.get('new', 0)), 'exit': int(kinds.get('exit', 0)), 'net_cr': net / 1e7,
                     'prior_cr': prior / 1e7, 'flow_pct': net / prior * 100 if prior > 0 else None,
                     'trimmed_pct': tp * 100 if tp is not None else None, 'added_pct': ap * 100 if ap is not None else None,
                     'broad': broad, 'mix_shift': {k: float(v) for k, v in mix.items()},
                     'sector_shift': [(k, float(v)) for k, v in sec.items()],
                     'top10_before': top(g['v0']), 'top10_after': top(g['v1'])})
    return pd.DataFrame(rows, columns=cols)


# ---- Scheme by scheme --------------------------------------------------------------------------------------------
# mf_scheme_moves (insiders_clean/mf_holdings.scheme_moves): active schemes, one row per house, scheme, month and ISIN
# where the scheme's shares moved, with the shares at the two month-ends and the change in rupees at the month's filed
# price. A row that did not move is not in it, so a scheme's shares at a window's start are the start of its first row
# in the window and at the end the end of its last one. mf_scheme_month names the schemes.

def scheme_rows(moves: pd.DataFrame | None, ms: list[str], houses: list[str] | None = None) -> pd.DataFrame:
    """One row per house, scheme and ISIN over the window `ms`: start, end, net shares, net rupees (crore), status
    (new / added / cut / exit / none), and `one_end`: the scheme was not in the house's files at both month-ends of
    some month in the window (a new scheme, a scheme gone, or a name that changed)."""
    cols = ['amc', 'scheme_key', 'isin', 'start', 'end', 'net', 'net_cr', 'status', 'one_end']
    if moves is None or moves.empty or not ms:
        return pd.DataFrame(columns=cols)
    m = moves[moves['month'].astype(str).isin(ms)]
    if houses:
        m = m[m['amc'].astype(str).isin(houses)]
    if m.empty:
        return pd.DataFrame(columns=cols)
    m = pd.DataFrame({'amc': m['amc'].astype(str), 'scheme_key': m['scheme_key'].astype(str), 'isin': m['isin'].astype(str),
                      'month': m['month'].astype(str), 's0': m['shares_start'].astype(float), 's1': m['shares_end'].astype(float),
                      'cr': m['change_cr'].astype(float), 'oe': m['scheme_seen'].astype(str).ne('both')}).sort_values('month')
    m['d'] = m['s1'] - m['s0']
    g = m.groupby(['amc', 'scheme_key', 'isin'], sort=False)
    out = g.agg(start=('s0', 'first'), end=('s1', 'last'), net=('d', 'sum'), net_cr=('cr', 'sum'), _n=('cr', 'count'),
                one_end=('oe', 'max')).reset_index()
    out['net_cr'] = out['net_cr'].where(out.pop('_n').gt(0))
    s, e = out['start'], out['end']
    out['status'] = 'held'
    out.loc[s.gt(0) & e.gt(0) & out['net'].gt(0), 'status'] = 'added'
    out.loc[s.gt(0) & e.gt(0) & out['net'].lt(0), 'status'] = 'cut'
    out.loc[s.eq(0) & e.gt(0), 'status'] = 'new'
    out.loc[s.gt(0) & e.eq(0), 'status'] = 'exit'
    out.loc[s.eq(0) & e.eq(0), 'status'] = 'none'
    return out[cols]


def scheme_names(sm: pd.DataFrame | None) -> dict:
    """{(house, scheme key): the scheme's name as last filed} from mf_scheme_month."""
    if sm is None or sm.empty:
        return {}
    s = sm.sort_values('month').drop_duplicates(['amc', 'scheme_key'], keep='last')
    return {(str(a), str(k)): str(n) for a, k, n in zip(s['amc'], s['scheme_key'], s['scheme'])}


def scheme_totals(sr: pd.DataFrame) -> pd.DataFrame:
    """Per house and scheme from `scheme_rows`: net rupees, rupees bought and sold (stock by stock), stocks added (new
    too), cut (exits too), new, sold out, and `one_end`; largest net buying first."""
    cols = ['amc', 'scheme_key', 'net_cr', 'bought_cr', 'sold_cr', 'adding', 'cutting', 'new', 'exits', 'one_end']
    if sr is None or sr.empty:
        return pd.DataFrame(columns=cols)
    v = sr['net_cr']
    x = sr.assign(_b=v.clip(lower=0), _s=v.clip(upper=0), _a=sr['net'].gt(0), _c=sr['net'].lt(0),
                  _n=sr['status'].eq('new'), _x=sr['status'].eq('exit'))
    out = x.groupby(['amc', 'scheme_key'], sort=False).agg(
        net_cr=('net_cr', 'sum'), bought_cr=('_b', 'sum'), sold_cr=('_s', 'sum'), adding=('_a', 'sum'), cutting=('_c', 'sum'),
        new=('_n', 'sum'), exits=('_x', 'sum'), one_end=('one_end', 'max')).reset_index()
    for c in ('adding', 'cutting', 'new', 'exits'):
        out[c] = out[c].astype(int)
    return out.sort_values('net_cr', ascending=False).reset_index(drop=True)[cols]


def scheme_counts(sr: pd.DataFrame) -> pd.DataFrame:
    """Per ISIN: schemes adding and cutting over the window (net shares), schemes in the files at both month-ends only
    (a scheme seen at one end has every line new or sold out, which says nothing about a decision)."""
    if sr is None or sr.empty:
        return pd.DataFrame(columns=['isin', 'schemes_adding', 'schemes_cutting'])
    x = sr[~sr['one_end'].astype(bool)]
    return x.assign(_a=x['net'].gt(0), _c=x['net'].lt(0)).groupby('isin').agg(
        schemes_adding=('_a', 'sum'), schemes_cutting=('_c', 'sum')).reset_index()


def scheme_coverage_at(cov: pd.DataFrame | None, month: str, kind: str = 'mf') -> pd.DataFrame:
    """The scheme count check for one month-end and house kind (mf_scheme_coverage), houses flagged first."""
    if cov is None or cov.empty:
        return pd.DataFrame()
    c = cov[(cov['month'].astype(str) == month)]
    if 'house_kind' in c:
        c = c[c['house_kind'].fillna('mf') == kind]
    return c.assign(_f=c['flag'].fillna('').astype(str).eq('')).sort_values(['_f', 'amc']).drop(columns='_f')


def month_total_shares(stock: pd.DataFrame | None, month: str, fallback: dict | None = None) -> dict:
    """{isin: the company's shares on `month`'s basis}: mf_stock_month's `total_shares` (the last filing with a split or
    bonus since applied, scripts/mf_portfolios.py); `fallback` (the latest filing as is) only for a table written
    before the column existed."""
    if stock is not None and not stock.empty and 'total_shares' in stock:
        s = stock[stock['month'] == month].dropna(subset=['total_shares']).drop_duplicates('isin')
        return dict(zip(s['isin'], s['total_shares']))
    return dict(fallback or {})
