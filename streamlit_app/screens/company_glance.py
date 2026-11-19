"""The Company page at a glance (owner, 19 Nov 2026, on /company: "Completely useless design and not glance-worthy to take
even a decision, doesn't even inspire confidence"). The page now answers one question in ten seconds: is smart money
accumulating or leaving this stock, and is anything wrong with it?

Pure functions over the clean tables (no Streamlit), so every number on the verdict band is tested
(tests/test_company_page.py):

  insider_flow    decision-makers' open-market buying and selling, 90 days
  fund_month      mutual funds' month-end change in the stock (mf_stock_month)
  ownership_mix   the ownership mix by quarter, seven groups, only quarters whose investor types add up
  mix_delta       this quarter against the last, points, per group
  fund_houses     which fund houses hold it, shares and % of the company, the change last month; the month-end trend
  deal_flow       bulk and block deals by real buyers and sellers, 90 days
  growth          8 quarters of revenue and profit, year-on-year and margin, from the results XBRL
  red_flags       pledge, surveillance, late filings, cheap issues, results doubts, promoter selling
  chips           one chip per group with its evidence status (docs/PRODUCT.md rule 4)
  verdict         the one sentence built from the chips and the flags

Nothing is filled: a group with no data is a chip that says what is missing, and it never counts as buying or selling.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

DECISION_ROLES = ('promoter', 'promoter_group', 'director', 'kmp')   # insiders_clean/signals.py
PROMOTER_ROLES = ('promoter', 'promoter_group')
HIGH_PLEDGE_PCT = 15.0          # signals.HIGH_PLEDGE_PCT

FLOW_DAYS = 90
INSIDER_MIN = 25e5              # ₹25 lakh: under this net, insiders are not "moving" (the track record's minimum size)
FUND_MIN_CR = 1.0               # ₹1 Cr: the Funds page's floor for a stock's net buying or selling in a month
DEAL_MIN = 1e7                  # ₹1 Cr net in deals
QUARTER_MIN_PTS = 0.20          # a quarter's change in a group's holding under this many points is "steady"

# Ownership groups, the parser's investor types they add up (docs/DATA_DICTIONARY.md, shareholding). Retail takes in
# HNIs: both are resident individuals, split only by ₹2 lakh of nominal capital.
MIX = [('Promoter', ('promoter',)), ('Mutual funds', ('mf',)), ('Insurance', ('insurance',)), ('FPI', ('fpi',)),
       ('Other DII', ('banks_fi', 'aif', 'other_dii')), ('Retail', ('retail', 'hni')),
       ('Others', ('corporate', 'other_foreign', 'govt', 'other_public', 'non_public_other'))]
MIX_ORDER = [g for g, _ in MIX]
DII_GROUPS = ('Mutual funds', 'Insurance', 'Other DII')

SURVEILLANCE = ('ASM', 'GSM', 'ESM', 'IBC')   # a trade flag naming one of these is an NSE surveillance stage


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) != float('inf') else None


def _cr(v: float) -> str:
    """₹ in crore, short: ₹3,488 Cr, ₹65.8 Cr, ₹42 L."""
    a = abs(v)
    sign = '−' if v < 0 else ''
    if a >= 1e10:
        return f'{sign}₹{a / 1e7:,.0f} Cr'
    if a >= 1e7:
        return f'{sign}₹{a / 1e7:,.1f} Cr'
    if a >= 1e5:
        return f'{sign}₹{a / 1e5:,.0f} L'
    return f'{sign}₹{a:,.0f}'


def signed_cr(v: float) -> str:
    return ('+' if v > 0 else '') + _cr(v)


# ---- insiders ------------------------------------------------------------------------------------------------------------

def insider_flow(e: pd.DataFrame | None, ref, days: int = FLOW_DAYS) -> dict:
    """Open-market buying and selling by promoters, directors and KMP made public in the `days` to `ref` (token buys are
    not buying, as on the snapshot). {'buy', 'sell', 'net', 'buyers', 'sellers', 'promoter_net', 'rows'}."""
    out = {'buy': 0.0, 'sell': 0.0, 'net': 0.0, 'buyers': 0, 'sellers': 0, 'promoter_net': 0.0, 'rows': 0, 'days': days}
    if e is None or e.empty or not {'seen', 'side', 'value', 'person_role'} <= set(e.columns):
        return out
    ref = pd.Timestamp(ref)
    seen = pd.to_datetime(e['seen'], errors='coerce')
    x = e[e['person_role'].isin(DECISION_ROLES) & (seen > ref - pd.Timedelta(days=days)) & (seen <= ref)]
    if 'is_token' in x:
        x = x[~x['is_token'].astype('boolean').fillna(False).astype(bool)]
    v = pd.to_numeric(x['value'], errors='coerce').fillna(0.0)
    b, s = x['side'].eq('BUY'), x['side'].eq('SELL')
    who = x['person_id'] if 'person_id' in x else x.get('person_name', pd.Series(index=x.index, dtype=object))
    prom = x['person_role'].isin(PROMOTER_ROLES)
    out.update(buy=float(v[b].sum()), sell=float(v[s].sum()), buyers=int(who[b].nunique()), sellers=int(who[s].nunique()),
               rows=int(len(x)), promoter_net=float(v[b & prom].sum() - v[s & prom].sum()))
    out['net'] = out['buy'] - out['sell']
    return out


# ---- mutual funds --------------------------------------------------------------------------------------------------------

def _mf(df: pd.DataFrame | None) -> pd.DataFrame:
    """Mutual fund houses only (pension managers apart, as on the Funds page); a table written before `house_kind`
    existed is all mutual funds."""
    if df is None or df.empty:
        return pd.DataFrame()
    k = df['house_kind'].fillna('mf') if 'house_kind' in df else pd.Series('mf', index=df.index)
    return df[k == 'mf']


def fund_month(stock_month: pd.DataFrame | None, isin) -> dict | None:
    """The stock's latest month-end change across mutual fund houses (active schemes: index funds and ETFs apart), or
    None when the fund portfolios hold no row for it. 'latest' says whether that month is the newest collected."""
    sm = _mf(stock_month)
    if sm.empty or not isin or 'isin' not in sm:
        return None
    mine = sm[sm['isin'] == isin]
    if mine.empty:
        return None
    r = mine.sort_values('month').iloc[-1]
    return {'month': str(r['month']), 'latest': str(r['month']) == str(sm['month'].max()),
            'net_cr': _num(r.get('active_net_cr')) or 0.0, 'adding': int(_num(r.get('houses_adding')) or 0),
            'cutting': int(_num(r.get('houses_cutting')) or 0), 'new': int(_num(r.get('houses_new')) or 0),
            'exit': int(_num(r.get('houses_exit')) or 0), 'holding': int(_num(r.get('houses_holding')) or 0)}


def fund_houses(changes: pd.DataFrame | None, isin, total_shares=None, names: dict | None = None,
                limit: int = 8) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(houses, trend) for one stock from the houses' month-end portfolios (mf_changes: houses present in both months).

    houses: one row per house at the stock's latest month: house, shares, pct (of the company's total shares, when
    known), change (shares since the month before), kind (new / added / cut / exit / held / passive), largest first;
    a house that sold out is kept, last. trend: house, month, shares for the `limit` largest houses, every month
    collected (the earliest from `shares_before`)."""
    names = names or {}
    ch = _mf(changes)
    empty = pd.DataFrame(columns=['house', 'shares', 'pct', 'change', 'kind']), pd.DataFrame(columns=['house', 'month', 'shares'])
    if ch.empty or not isin or 'isin' not in ch:
        return empty
    x = ch[ch['isin'] == isin].copy()
    if x.empty:
        return empty
    x['house'] = x['amc'].map(lambda k: names.get(k) or str(k))
    x['shares'] = pd.to_numeric(x['shares'], errors='coerce').fillna(0.0)
    last = x['month'].max()
    now = x[x['month'] == last]
    tot = _num(total_shares)
    houses = pd.DataFrame({'house': now['house'], 'shares': now['shares'],
                           'pct': now['shares'] / tot * 100 if tot else float('nan'),
                           'change': pd.to_numeric(now.get('change'), errors='coerce'),
                           'kind': now.get('kind', pd.Series('', index=now.index)).astype(str)})
    houses = houses.assign(_out=houses['shares'].le(0)).sort_values(['_out', 'shares'], ascending=[True, False]).drop(columns='_out')
    keep = list(houses.loc[houses['shares'] > 0, 'house'].head(limit))
    pts = [x[['house', 'month', 'shares']]]
    if 'shares_before' in x:   # the month before the first month of changes, from its "before" column
        first = x[x['month'] == x['month'].min()]
        prev = (pd.Period(str(first['month'].iloc[0]), 'M') - 1).strftime('%Y-%m')
        pts.append(pd.DataFrame({'house': first['house'], 'month': prev,
                                 'shares': pd.to_numeric(first['shares_before'], errors='coerce')}))
    trend = pd.concat(pts, ignore_index=True).dropna()
    trend = trend[trend['house'].isin(keep)].drop_duplicates(['house', 'month'], keep='first').sort_values(['house', 'month'])
    if tot:
        trend = trend.assign(pct=trend['shares'] / tot * 100)
    return houses.reset_index(drop=True), trend.reset_index(drop=True)


# ---- ownership --------------------------------------------------------------------------------------------------------

def ownership_mix(rows: pd.DataFrame | None, quarters: int = 8) -> pd.DataFrame:
    """Long table quarter, group, pct (% of shares, SEBI's base) for the company's latest `quarters` quarters whose
    investor types were parsed and add up (`categories_check == 'match'`); any other quarter is left out, never
    filled. Groups in MIX order."""
    cols = ['quarter', 'group', 'pct']
    if rows is None or rows.empty or 'quarter_end' not in rows or 'categories_check' not in rows:
        return pd.DataFrame(columns=cols)
    r = rows.assign(_q=pd.to_datetime(rows['quarter_end'], errors='coerce')).dropna(subset=['_q'])
    r = r[r['categories_check'].eq('match').fillna(False).astype(bool)]
    r = r.sort_values('_q').drop_duplicates('_q', keep='last').tail(quarters)
    out = []
    for x in r.to_dict('records'):
        vals = []
        for g, types in MIX:
            v = [_num(x.get(f'{t}_pct')) for t in types]
            if any(a is None for a in v):
                break
            vals.append((g, float(sum(v))))
        else:
            out += [{'quarter': x['_q'], 'group': g, 'pct': p} for g, p in vals]
    return pd.DataFrame(out, columns=cols)


def mix_delta(mix: pd.DataFrame | None) -> pd.DataFrame:
    """This quarter against the last parsed one: group, pts, now, before, quarter, prev_quarter. Empty with under two
    quarters, or when the two are more than 120 days apart (a skipped quarter is not "last quarter")."""
    cols = ['group', 'pts', 'now', 'before', 'quarter', 'prev_quarter']
    if mix is None or mix.empty:
        return pd.DataFrame(columns=cols)
    qs = sorted(mix['quarter'].unique())
    if len(qs) < 2 or (pd.Timestamp(qs[-1]) - pd.Timestamp(qs[-2])).days > 120:
        return pd.DataFrame(columns=cols)
    a = mix[mix['quarter'] == qs[-1]].set_index('group')['pct']
    b = mix[mix['quarter'] == qs[-2]].set_index('group')['pct']
    return pd.DataFrame([{'group': g, 'pts': float(a[g] - b[g]), 'now': float(a[g]), 'before': float(b[g]),
                          'quarter': pd.Timestamp(qs[-1]), 'prev_quarter': pd.Timestamp(qs[-2])}
                         for g in MIX_ORDER if g in a and g in b], columns=cols)


# ---- deals ---------------------------------------------------------------------------------------------------------------

def deal_flow(d: pd.DataFrame | None, ref, days: int = FLOW_DAYS) -> dict:
    """Bulk and block deals by real buyers and sellers (the caller leaves market makers and copies of insider filings
    out) in the `days` to `ref`: {'buy', 'sell', 'net', 'n', 'top_buyer', 'top_seller'}."""
    out = {'buy': 0.0, 'sell': 0.0, 'net': 0.0, 'n': 0, 'top_buyer': '', 'top_seller': '', 'days': days}
    if d is None or d.empty or not {'date', 'side', 'value'} <= set(d.columns):
        return out
    ref = pd.Timestamp(ref)
    when = pd.to_datetime(d['date'], errors='coerce')
    x = d[(when > ref - pd.Timedelta(days=days)) & (when <= ref)]
    if x.empty:
        return out
    v = pd.to_numeric(x['value'], errors='coerce').fillna(0.0)
    who = x['client_name'].astype(str) if 'client_name' in x else pd.Series('', index=x.index)
    b, s = x['side'].eq('BUY'), x['side'].eq('SELL')
    out.update(buy=float(v[b].sum()), sell=float(v[s].sum()), n=int(len(x)))
    out['net'] = out['buy'] - out['sell']
    if b.any():
        out['top_buyer'] = str(v[b].groupby(who[b]).sum().idxmax())
    if s.any():
        out['top_seller'] = str(v[s].groupby(who[s]).sum().idxmax())
    return out


# ---- the business ----------------------------------------------------------------------------------------------------

def growth(results: pd.DataFrame | None, isin, quarters: int = 8) -> tuple[pd.DataFrame, str]:
    """(quarters, basis): the latest `quarters` quarters of revenue and profit on one basis (consolidated where the
    company files it, else standalone), oldest first, with year-on-year change against the same quarter a year before
    (when we hold it) and net margin. A revised filing replaces the one it supersedes; a filing whose quarter and year
    to date disagree is left out (neither is used, insiders_clean/results.py)."""
    cols = ['period_end', 'revenue', 'profit', 'margin', 'rev_yoy', 'profit_yoy', 'derived']
    if results is None or results.empty or not isin or 'isin' not in results:
        return pd.DataFrame(columns=cols), ''
    r = results[results['isin'] == isin].copy()
    if 'superseded' in r:
        r = r[~r['superseded'].astype('boolean').fillna(False).astype(bool)]
    if 'ytd_disagrees' in r:
        r = r[~r['ytd_disagrees'].astype('boolean').fillna(False).astype(bool)]
    r['revenue'] = pd.to_numeric(r.get('quarter_revenue'), errors='coerce')
    r['profit'] = pd.to_numeric(r.get('quarter_profit'), errors='coerce')
    r = r.dropna(subset=['revenue'])
    if r.empty:
        return pd.DataFrame(columns=cols), ''
    cons = r['consolidated'].astype(str).str.strip().str.lower().str.startswith('consolidated') if 'consolidated' in r \
        else pd.Series(False, index=r.index)
    basis = 'consolidated' if cons.any() else 'standalone'
    r = r[cons] if cons.any() else r
    r['period_end'] = pd.to_datetime(r['period_end'], errors='coerce').dt.normalize()
    when = pd.to_datetime(r.get('broadcast_at'), errors='coerce', utc=True) if 'broadcast_at' in r else pd.Series(pd.NaT, index=r.index)
    r = r.assign(_w=when).dropna(subset=['period_end']).sort_values(['period_end', '_w']).drop_duplicates('period_end', keep='last')
    by = r.set_index('period_end')
    out = []
    for pe, x in by.iterrows():
        ago = by.loc[(by.index.year == pe.year - 1) & (by.index.month == pe.month)]
        a = ago.iloc[0] if len(ago) else None
        rev_yoy = (x['revenue'] / a['revenue'] - 1) * 100 if a is not None and a['revenue'] and a['revenue'] > 0 else None
        p0 = a['profit'] if a is not None else None
        profit_yoy = ((x['profit'] / p0 - 1) * 100 if p0 is not None and p0 == p0 and p0 > 0 and x['profit'] == x['profit']
                      else None)
        out.append({'period_end': pe, 'revenue': float(x['revenue']), 'profit': _num(x['profit']),
                    'margin': (float(x['profit']) / float(x['revenue']) * 100) if _num(x['profit']) is not None and x['revenue'] > 0 else None,
                    'rev_yoy': rev_yoy, 'profit_yoy': profit_yoy,
                    'derived': bool(x.get('quarter_derived')) if x.get('quarter_derived') == x.get('quarter_derived') else False})
    return pd.DataFrame(out, columns=cols).tail(quarters).reset_index(drop=True), basis


def results_doubts(results: pd.DataFrame | None, isin) -> int:
    """Filings of the company whose quarter's revenue is above its own year to date (one of the two is wrong as filed)."""
    if results is None or results.empty or not isin or 'ytd_disagrees' not in results:
        return 0
    r = results[results['isin'] == isin]
    return int(r['ytd_disagrees'].astype('boolean').fillna(False).astype(bool).sum())


# ---- flags, chips and the verdict --------------------------------------------------------------------------------------

@dataclass
class Flag:
    """One check: level 'fail' (a red flag), 'warn' (to look at) or 'pass'; `evidence` its status (rule 4)."""
    name: str
    level: str
    text: str
    evidence: str = ''


def red_flags(pledge=None, trade_flags=None, trade_notes=None, late: int = 0, cheap: list | None = None, doubts: int = 0,
              promoter_sold: float = 0.0, promoter_sold_pct=None, encumbered=None) -> list[Flag]:
    """Every standing check, in the order a reader weighs them. `trade_flags` None means the stock is not in NSE's
    tradability list (not known), [] means nothing flagged."""
    out = []
    p = _num(pledge)
    if p is None:
        out.append(Flag('Pledge', 'na', 'No shareholding filing in the data'))
    else:
        enc = _num(encumbered)
        extra = f'; {enc:.1f}% encumbered in all' if enc is not None and enc > p + 0.05 else ''
        out.append(Flag('Pledge', 'fail' if p > HIGH_PLEDGE_PCT else 'warn' if p > 0 else 'pass',
                        (f'{p:.1f}% of promoter shares pledged' if p > 0 else 'No promoter shares pledged') + extra,
                        'Studies: a crash-risk filter (Kalia 2024)' if p > 0 else ''))
    if trade_flags is None:
        out.append(Flag('Surveillance', 'na', "Not known: not in NSE's list"))
    else:
        flags = [str(f) for f in trade_flags]
        notes = [str(n) for n in (trade_notes or flags)]
        surv = [f for f in flags if any(s in f.upper() for s in SURVEILLANCE)]
        out.append(Flag('Surveillance', 'fail' if surv else 'warn' if flags else 'pass',
                        ' · '.join(notes) if flags else 'No NSE surveillance or trade-for-trade flag', 'NSE list today' if flags else ''))
    out.append(Flag('Late filings', 'warn' if late else 'pass',
                    f'{late} insider filing{"s" * (late != 1)} made late in 12 months' if late else 'None in 12 months'))
    cheap = [c for c in (cheap or []) if c]
    out.append(Flag('Cheap issues', 'warn' if cheap else 'pass', '; '.join(cheap) if cheap else 'None in 12 months',
                    'Studies: -8.6% around the event (Anshuman et al. 2019)' if cheap else ''))
    out.append(Flag('Results filings', 'warn' if doubts else 'pass',
                    f"{doubts} filing{'s' * (doubts != 1)} whose quarter is above its own year to date" if doubts
                    else 'No filing contradicts itself'))
    sold_pct = _num(promoter_sold_pct)
    out.append(Flag('Promoter selling', 'warn' if promoter_sold > 0 else 'pass',
                    (f'{_cr(promoter_sold)} sold on the market in 12 months' + (f', {sold_pct:.2f}% of the company' if sold_pct else ''))
                    if promoter_sold > 0 else 'None on the market in 12 months'))
    return out


@dataclass
class Chip:
    """One group on the verdict band. tone: 'up' (buying), 'down' (selling), 'flat' (steady), 'na' (no data);
    'fail' / 'warn' / 'pass' on the red-flag chip. `moving` +1 / -1 / 0 is what the verdict counts."""
    key: str
    label: str
    value: str
    note: str
    tone: str
    evidence: str
    moving: int = 0
    extra: dict = field(default_factory=dict)


def _side(v: float, floor: float) -> int:
    return 1 if v >= floor else -1 if v <= -floor else 0


def chips(ins: dict, fm: dict | None, delta: pd.DataFrame | None, deals: dict, flags: list[Flag],
          insider_evidence: str = '', month_label=None) -> list[Chip]:
    """The verdict band's chips, each with its evidence status. A group whose data is missing says so (tone 'na')."""
    out = []
    m = _side(ins['net'], INSIDER_MIN)
    if ins['rows']:
        val = signed_cr(ins['net']) if ins['net'] else '₹0 net'
        note = f'bought {_cr(ins["buy"])} · sold {_cr(ins["sell"])}'
    else:
        val, note = 'No trades', 'no promoter, director or KMP traded on the market'
    out.append(Chip('insiders', f'Insiders, {ins["days"]} days', val, note, 'up' if m > 0 else 'down' if m < 0 else 'flat',
                    insider_evidence or 'Not measured', m))
    if fm is None:
        out.append(Chip('mf', 'Mutual funds, month-end', 'Not held', 'no collected fund house holds it', 'na',
                        'Fund houses\' own portfolios', 0))
    else:
        m = _side(fm['net_cr'], FUND_MIN_CR)
        label = month_label(fm['month']) if month_label else fm['month']
        out.append(Chip('mf', f'Mutual funds, {label}', signed_cr(fm['net_cr'] * 1e7) if fm['net_cr'] else '₹0 net',
                        f'{fm["adding"]} adding · {fm["cutting"]} cutting · {fm["holding"]} holding'
                        + (f' · {fm["new"]} new' if fm['new'] else '') + (f' · {fm["exit"]} out' if fm['exit'] else ''),
                        'up' if m > 0 else 'down' if m < 0 else 'flat', 'Exploratory: not measured', m))
    if delta is None or delta.empty:
        for key, label in (('fpi', 'Foreign investors'), ('dii', 'Domestic institutions')):
            out.append(Chip(key, f'{label}, quarter', '—', 'investor types not parsed for two quarters in a row', 'na',
                            'Shareholding pattern', 0))
    else:
        d = delta.set_index('group')
        q = pd.Timestamp(delta['quarter'].iloc[0])
        for key, label, groups in (('fpi', 'Foreign investors', ('FPI',)), ('dii', 'Domestic institutions', DII_GROUPS)):
            pts = float(sum(d.loc[g, 'pts'] for g in groups if g in d.index))
            now = float(sum(d.loc[g, 'now'] for g in groups if g in d.index))
            m = _side(pts, QUARTER_MIN_PTS)
            out.append(Chip(key, f'{label}, {q:%b %Y} qtr', f'{pts:+.2f} pts', f'now {now:.2f}% of the company',
                            'up' if m > 0 else 'down' if m < 0 else 'flat', 'Exploratory: not measured', m))
    m = _side(deals['net'], DEAL_MIN)
    if deals['n']:
        out.append(Chip('deals', f'Bulk and block, {deals["days"]} days', signed_cr(deals['net']) if deals['net'] else '₹0 net',
                        f'bought {_cr(deals["buy"])} · sold {_cr(deals["sell"])}', 'up' if m > 0 else 'down' if m < 0 else 'flat',
                        'Studies: weak (copying bulk deals)', m))
    else:
        out.append(Chip('deals', f'Bulk and block, {deals["days"]} days', 'None', 'no deal by a real buyer or seller', 'flat', '', 0))
    red = [f for f in flags if f.level == 'fail']
    warn = [f for f in flags if f.level == 'warn']
    if red:
        out.append(Chip('flags', 'Red flags', f'{len(red)} red' + (f' · {len(warn)} to check' if warn else ''),
                        ' · '.join(f.name for f in red + warn), 'fail', red[0].evidence or 'Checks below'))
    elif warn:
        out.append(Chip('flags', 'Red flags', 'None', f'{len(warn)} to check: ' + ', '.join(f.name.lower() for f in warn), 'warn',
                        'Checks below'))
    else:
        out.append(Chip('flags', 'Red flags', 'None', 'every check passed' if all(f.level == 'pass' for f in flags)
                        else 'some checks not known', 'pass', 'Checks below'))
    return out


NAMES = {'insiders': 'insiders', 'mf': 'mutual funds', 'fpi': 'foreign investors', 'dii': 'domestic institutions',
         'deals': 'big buyers in deals'}
SELLERS = {'deals': 'big sellers in deals'}


def _join(xs: list[str]) -> str:
    return xs[0] if len(xs) == 1 else ', '.join(xs[:-1]) + ' and ' + xs[-1]


def verdict(cs: list[Chip], flags: list[Flag]) -> tuple[str, str]:
    """(sentence, lean). lean: 'accumulating', 'leaving', 'mixed' or 'quiet'. Deals count only when nobody else moves:
    a block's buyer and seller are both in it, and copying bulk deals is weak in the studies (docs/PRODUCT.md)."""
    core = [c for c in cs if c.key in ('insiders', 'mf', 'fpi', 'dii')]
    buy = [NAMES[c.key] for c in core if c.moving > 0]
    sell = [NAMES[c.key] for c in core if c.moving < 0]
    if not buy and not sell:
        d = next((c for c in cs if c.key == 'deals'), None)
        if d is not None and d.moving:
            (buy if d.moving > 0 else sell).append(NAMES['deals'] if d.moving > 0 else SELLERS['deals'])
    if buy and not sell:
        head, lean = f'{_join(buy)} are buying', 'accumulating'
    elif sell and not buy:
        head, lean = f'{_join(sell)} are selling', 'leaving'
    elif buy and sell:
        head, lean = f'{_join(buy)} buying, {_join(sell)} selling', 'mixed'
    else:
        head, lean = 'No clear move by insiders or funds', 'quiet'
    red = [f for f in flags if f.level == 'fail']
    warn = [f for f in flags if f.level == 'warn']
    if red:
        tail = f'red flag: {red[0].text[0].lower() + red[0].text[1:]}' if len(red) == 1 else f'{len(red)} red flags ({_join([f.name.lower() for f in red])})'
    else:
        tail = 'no red flags' + (f', {len(warn)} thing{"s" * (len(warn) != 1)} to check' if warn else '')
    s = f'{head}; {tail}'
    return s[0].upper() + s[1:], lean
