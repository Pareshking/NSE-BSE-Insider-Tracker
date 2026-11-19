"""Dashboard: the market picture on one screen (owner, 19 Nov 2026: "Why don't we have a beautiful dashboard?").

Each tile answers "who is buying what, should I look?" from the clean tables only, says how far its evidence goes
(docs/PRODUCT.md rule 4) and links to the page with the rows behind it. A table that is empty or not collected yet
says so in its tile; nothing is filled in.

The arithmetic is in the pure functions at the top (tests/test_dashboard.py); `render` only draws.
"""
from __future__ import annotations

import pandas as pd
from ui import kit
from ui.kit import esc
from ui.theme import C

from insiders_clean import evidence, ideas, signals

INSIDER_DAYS = 30
DEAL_DAYS = 30
SAST_DAYS = 30
RESULTS_DAYS = 45          # a results season: the filings of the last six weeks
SEASON_GAP = 91            # the season before: the same window a quarter earlier
COMING_DAYS = 7
SPARK_WEEKS = 12
THRESHOLDS = (5, 10, 15, 20, 25, 50, 75)   # as screens/proto.py
NSE_SEGMENTS = ('cash_nse_bse_msei', 'cash_nse')   # as screens/market_flows.py
MF_MIN_NET_CR = 1.0        # as screens/funds.py: a stock's net under Rs 1 Cr is counted, not listed
CONVERGE_MIN_INSIDER = ideas.MIN_VALUE   # insiders' buying of Rs 25 lakh and up in the window counts as buying
FUND_TYPES = signals.FUND_TYPES


# ---- small pieces ---------------------------------------------------------------------------------------------------

def _f(v) -> float | None:
    return kit._finite(v)


def crore(v_cr, signed: bool = True) -> str:
    """A figure already in Rs crore: '+₹1,234 Cr', '−₹56.20 Cr'."""
    v = _f(v_cr)
    return '—' if v is None else kit.rupees(v * 1e7, signed=signed)


def spark(values, bars: bool = True) -> str:
    """A sparkline as plain HTML (st.html allows no SVG): one column per value about a zero line, `p` for a positive
    value and `n` for a negative one (`q`, neutral, when `bars` is False: a count or a share). A missing value keeps its
    slot empty. '' with fewer than two values. Colours come from look.css; only positions are written here."""
    vals = [_f(v) for v in values]
    real = [v for v in vals if v is not None]
    if len(real) < 2:
        return ''
    lo, hi = min(real + [0.0]), max(real + [0.0])
    span = (hi - lo) or 1.0
    zero = hi / span * 100          # the zero line, % from the top
    wd = 100 / len(vals)
    cols = []
    for i, v in enumerate(vals):
        if v is None:
            continue
        ht = max(abs(v) / span * 100, 3.0)
        top = zero - ht if v >= 0 else zero
        cls = ('p' if v >= 0 else 'n') if bars else 'q'
        last = ' last' if i == len(vals) - 1 else ''
        cols.append(f'<i class="{cls}{last}" style="left:{i * wd + wd * 0.15:.2f}%;width:{wd * 0.7:.2f}%;'
                    f'top:{max(top, 0.0):.2f}%;height:{ht:.2f}%"></i>')
    return f'<span class="dash-spark" aria-hidden="true"><i class="z" style="top:{zero:.2f}%"></i>{"".join(cols)}</span>'


def delta_html(now, before, fmt, label: str) -> str:
    """'▲ +₹12 Cr vs the 30 days before' in the up or down class; a plain line when there is no earlier figure."""
    a, b = _f(now), _f(before)
    if a is None or b is None:
        return '<div class="dash-delta">No earlier period in the data</div>'
    d = a - b
    if not any(ch in '123456789' for ch in fmt(d)):   # a change that rounds to nothing is no change
        return f'<div class="dash-delta">■ Unchanged {esc(label)}</div>'
    cls = 'dash-delta-up' if d > 0 else 'dash-delta-down' if d < 0 else ''
    arrow = '▲' if d > 0 else '▼' if d < 0 else '■'
    return f'<div class="dash-delta {cls}">{arrow} {esc(fmt(d))} {esc(label)}</div>'


def weekly(df: pd.DataFrame | None, when: str, ref, weeks: int = SPARK_WEEKS, value: str | None = None,
           mask: pd.Series | None = None) -> list[float]:
    """Sum of `value` (or a row count) per 7-day bin, the last bin ending on `ref`, oldest first."""
    if df is None or df.empty or when not in df:
        return []
    t = pd.to_datetime(df[when], errors='coerce')
    if getattr(t.dt, 'tz', None) is not None:
        t = t.dt.tz_localize(None)
    end = pd.Timestamp(ref).normalize() + pd.Timedelta(days=1)
    v = pd.to_numeric(df[value], errors='coerce').fillna(0.0) if value else pd.Series(1.0, index=df.index)
    if mask is not None:
        v = v.where(mask, 0.0)
    out = []
    for k in range(weeks, 0, -1):
        lo, hi = end - pd.Timedelta(days=7 * k), end - pd.Timedelta(days=7 * (k - 1))
        out.append(float(v[(t >= lo) & (t < hi)].sum()))
    return out


class Window:
    """The period of the insider, deal and SAST figures: `days` to `end`, both counted, and its words."""

    def __init__(self, end, days: int):
        self.end, self.days = pd.Timestamp(end).normalize(), int(days)
        self.short = f'{self.days} days' if self.days != 1 else '1 day'
        self.span = f'in {self.short}'
        self.before = f'vs the {self.short} before'


# ---- 1. KPI figures -------------------------------------------------------------------------------------------------

def _decision_rows(elig: pd.DataFrame | None, ref) -> pd.DataFrame:
    if elig is None or elig.empty or 'seen' not in elig:
        return pd.DataFrame()
    x = elig[elig['person_role'].isin(signals.DECISION_ROLES) & elig['isin'].notna() & elig['seen'].notna()
             & (elig['seen'] <= pd.Timestamp(ref) + pd.Timedelta(days=1))]
    tok = x['is_token'].astype('boolean').fillna(False) if 'is_token' in x else pd.Series(False, index=x.index)
    return x[~(x['side'].eq('BUY') & tok)]


def _promoter_mask(x: pd.DataFrame) -> pd.Series:
    named = (x['promoter_group_id'].map(lambda v: isinstance(v, str) and bool(v)) if 'promoter_group_id' in x
             else pd.Series(False, index=x.index))
    return named | x['person_role'].isin(signals.PROMOTER_ROLES)


def insider_kpi(elig: pd.DataFrame | None, ref, days: int = INSIDER_DAYS) -> dict | None:
    """Decision-makers' open-market buying less selling (token buys out) over `days` and the period before
    (ideas.insider_breadth), the companies where a promoter bought, and weekly sparklines of both."""
    b = ideas.insider_breadth(elig, pd.Timestamp(ref), days) if elig is not None and not elig.empty else None
    if b is None:
        return None
    x = _decision_rows(elig, ref)
    ref = pd.Timestamp(ref)
    pb = x[x['side'].eq('BUY') & _promoter_mask(x)]

    def cos(lo, hi):
        return int(pb.loc[(pb['seen'] > lo) & (pb['seen'] <= hi), 'isin'].nunique())
    d = pd.Timedelta(days=days)
    end = ref + pd.Timedelta(days=1)
    before = b.get('before')
    signed = pd.to_numeric(x['value'], errors='coerce').fillna(0.0) * x['side'].map({'BUY': 1.0, 'SELL': -1.0}).fillna(0.0)
    xs = x.assign(_signed=signed)
    weeks_pc = []
    for k in range(SPARK_WEEKS, 0, -1):
        lo, hi = end - pd.Timedelta(days=7 * k), end - pd.Timedelta(days=7 * (k - 1))
        weeks_pc.append(float(pb.loc[(pb['seen'] >= lo) & (pb['seen'] < hi), 'isin'].nunique()))
    return {'net': b['buy_value'] - b['sell_value'], 'buy': b['buy_value'], 'sell': b['sell_value'],
            'buy_companies': b['buy_companies'],
            'net_before': (before['buy_value'] - before['sell_value']) if before else None,
            'promoter_companies': cos(ref - d, end), 'promoter_companies_before': cos(ref - 2 * d, ref - d) if before else None,
            'spark': weekly(xs, 'seen', ref, value='_signed'), 'spark_promoter': weeks_pc}


def _flows(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or df.empty or not {'date', 'source', 'segment', 'category', 'net_cr'} <= set(df.columns):
        return pd.DataFrame(columns=['date', 'source', 'segment', 'category', 'net_cr'])
    return df.assign(date=pd.to_datetime(df['date'], errors='coerce').dt.normalize(),
                     net_cr=pd.to_numeric(df['net_cr'], errors='coerce')).dropna(subset=['date'])


def flow_days(df: pd.DataFrame | None, source: str, category: str, segments) -> pd.DataFrame:
    """date, net_cr of one source and category, on the first of `segments` it has, oldest first."""
    f = _flows(df)
    rows = f[(f['source'] == source) & (f['category'] == category)]
    for seg in segments:
        part = rows[rows['segment'] == seg]
        if not part.empty:
            return part.groupby('date', as_index=False)['net_cr'].sum().sort_values('date').assign(segment=seg)
    return pd.DataFrame(columns=['date', 'net_cr', 'segment'])


def flow_months(days: pd.DataFrame) -> pd.DataFrame:
    """month (YYYY-MM), net_cr, days, last date, from daily rows."""
    if days is None or days.empty:
        return pd.DataFrame(columns=['month', 'net_cr', 'days', 'last'])
    m = days.assign(month=days['date'].dt.strftime('%Y-%m'))
    return m.groupby('month', as_index=False).agg(net_cr=('net_cr', 'sum'), days=('date', 'nunique'), last=('date', 'max'))


def fpi_kpi(df: pd.DataFrame | None) -> dict | None:
    """FPIs' equity net: NSDL's month to date (settled; reporting dates) against last month, the latest
    exchange-provisional day from NSE beside it. None when neither source has rows."""
    nsdl = flow_days(df, 'nsdl', 'fpi', ('equity',))
    nse = flow_days(df, 'nse', 'fpi', NSE_SEGMENTS)
    if nsdl.empty and nse.empty:
        return None
    out = {'nse_day': None, 'nse_net': None, 'mtd': None, 'month': None, 'prev': None, 'mtd_days': 0, 'last': None, 'spark': []}
    if not nse.empty:
        out['nse_day'], out['nse_net'] = nse['date'].iloc[-1], float(nse['net_cr'].iloc[-1])
    if not nsdl.empty:
        mo = flow_months(nsdl)
        cur = mo.iloc[-1]
        out.update(mtd=float(cur['net_cr']), month=cur['month'], mtd_days=int(cur['days']), last=cur['last'],
                   prev=float(mo.iloc[-2]['net_cr']) if len(mo) > 1 else None, prev_month=mo.iloc[-2]['month'] if len(mo) > 1 else None,
                   spark=nsdl['net_cr'].tail(20).tolist())
    return out


def dii_kpi(df: pd.DataFrame | None) -> dict | None:
    """DIIs' cash-market net from NSE's provisional figures: the latest day and the day before it (NSE answers only the
    latest day, so the history is what the nightly has kept since its first run)."""
    nse = flow_days(df, 'nse', 'dii', NSE_SEGMENTS)
    if nse.empty:
        return None
    cur = nse['date'].iloc[-1]
    month = nse[nse['date'].dt.strftime('%Y-%m') == cur.strftime('%Y-%m')]
    return {'day': cur, 'net': float(nse['net_cr'].iloc[-1]), 'before': float(nse['net_cr'].iloc[-2]) if len(nse) > 1 else None,
            'before_day': nse['date'].iloc[-2] if len(nse) > 1 else None, 'days_kept': len(nse), 'first': nse['date'].iloc[0],
            'month_days': len(month), 'month_net': float(month['net_cr'].sum()), 'spark': nse['net_cr'].tail(20).tolist()}


def mf_kind(stock: pd.DataFrame | None, kind: str = 'mf') -> pd.DataFrame:
    if stock is None or stock.empty or 'month' not in stock:
        return pd.DataFrame()
    k = stock['house_kind'].fillna('mf') if 'house_kind' in stock else pd.Series('mf', index=stock.index)
    return stock[k == kind]


def mf_kpi(stock: pd.DataFrame | None) -> dict | None:
    """Active mutual fund schemes' net buying over all stocks, latest month-end against the month before (Rs crore)."""
    s = mf_kind(stock)
    if s.empty or 'active_net_cr' not in s:
        return None
    by = s.assign(_n=pd.to_numeric(s['active_net_cr'], errors='coerce')).groupby('month')['_n'].sum().sort_index()
    cur = s[s['month'] == by.index[-1]]
    n = pd.to_numeric(cur['active_net_cr'], errors='coerce')
    return {'month': by.index[-1], 'net': float(by.iloc[-1]), 'before': float(by.iloc[-2]) if len(by) > 1 else None,
            'prev_month': by.index[-2] if len(by) > 1 else None, 'bought': int(n.ge(MF_MIN_NET_CR).sum()),
            'sold': int(n.le(-MF_MIN_NET_CR).sum()), 'spark': by.tolist()}


def real_deals(deals: pd.DataFrame | None) -> pd.DataFrame:
    """Deal legs that are a real buyer or seller: one exchange copy, market makers out."""
    if deals is None or deals.empty:
        return pd.DataFrame()
    prim = deals['is_primary'].astype('boolean').fillna(False) if 'is_primary' in deals else pd.Series(True, index=deals.index)
    mm = (deals['client_is_market_maker'].astype('boolean').fillna(False) if 'client_is_market_maker' in deals
          else pd.Series(False, index=deals.index))
    d = deals[prim & ~mm]
    return d.assign(date=pd.to_datetime(d['date'], errors='coerce'))


def deals_kpi(deals: pd.DataFrame | None, ref, days: int = DEAL_DAYS) -> dict | None:
    """Rupees bought in bulk and block deals by real buyers (the buy legs, so a deal is counted once) over `days`, the
    period before, and how much of it was funds."""
    d = real_deals(deals)
    if d.empty:
        return None
    ref = pd.Timestamp(ref).normalize()
    b = d[d['side'].eq('BUY')].assign(_v=lambda x: pd.to_numeric(x['value'], errors='coerce').fillna(0.0))
    fund = b['client_type'].isin(FUND_TYPES) if 'client_type' in b else pd.Series(False, index=b.index)
    end = ref + pd.Timedelta(days=1)
    now = (b['date'] > ref - pd.Timedelta(days=days)) & (b['date'] < end)
    prev = (b['date'] > ref - pd.Timedelta(days=2 * days)) & (b['date'] <= ref - pd.Timedelta(days=days))
    has_prev = bool(len(d)) and d['date'].min() <= ref - pd.Timedelta(days=2 * days) + pd.Timedelta(days=3)
    return {'value': float(b.loc[now, '_v'].sum()), 'before': float(b.loc[prev, '_v'].sum()) if has_prev else None,
            'funds': float(b.loc[now & fund, '_v'].sum()), 'companies': int(b.loc[now, 'isin'].nunique()),
            'spark': weekly(b, 'date', ref, value='_v'), 'last': d['date'].max()}


def profit_growth(r: pd.DataFrame | None, lo, hi) -> dict:
    """Of the results filed in (lo, hi] with a year-ago quarter in our history, how many grew their quarter's profit
    (half-year-only filings and figures held back as doubtful left out)."""
    if r is None or r.empty or '_at' not in r:
        return {'n': 0, 'up': 0, 'share': None, 'filed': 0}
    w = r[(r['_at'] > lo) & (r['_at'] <= hi)]
    half = w['half_year'].astype('boolean').fillna(False) if 'half_year' in w else pd.Series(False, index=w.index)
    p, py = pd.to_numeric(w['quarter_profit'], errors='coerce'), pd.to_numeric(w.get('profit_year'), errors='coerce')
    ok = ~half & p.notna() & py.notna()
    if 'doubt' in w:
        ok &= w['doubt'].fillna('').eq('')
    n, up = int(ok.sum()), int((ok & (p > py)).sum())
    return {'n': n, 'up': up, 'share': up / n * 100 if n else None, 'filed': len(w)}


def results_kpi(r: pd.DataFrame | None, ref, days: int = RESULTS_DAYS) -> dict | None:
    if r is None or r.empty:
        return None
    end = pd.Timestamp(ref) + pd.Timedelta(days=1)
    now = profit_growth(r, end - pd.Timedelta(days=days), end)
    lag = pd.Timedelta(days=SEASON_GAP)
    before = profit_growth(r, end - lag - pd.Timedelta(days=days), end - lag)
    spark = []
    for k in range(8, 0, -1):
        g = profit_growth(r, end - pd.Timedelta(days=7 * k), end - pd.Timedelta(days=7 * (k - 1)))
        spark.append(g['share'] if g['n'] >= 10 else None)
    return {**now, 'before': before['share'] if before['n'] >= 30 else None, 'before_n': before['n'], 'spark': spark}


def sast_moves(sa: pd.DataFrame | None, ref, days: int) -> pd.DataFrame:
    """SAST Reg 29 rows made public in the `days` to `ref` that are a holder's own move (held-back rows, inter-se
    transfers and moves under 0.1% out), with the threshold each crossed ('' for none) and its direction."""
    cols = ['isin', 'company', 'symbol', 'acquirer_name', 'before', 'after', 'cross', 'up', '_f']
    if sa is None or sa.empty or 'broadcast_ts' not in sa:
        return pd.DataFrame(columns=cols)
    f = pd.to_datetime(sa['broadcast_ts'], errors='coerce', format='mixed', utc=True).dt.tz_localize(None)
    ref = pd.Timestamp(ref)
    x = sa.assign(_f=f.to_numpy())
    x = x[(x['_f'] > ref - pd.Timedelta(days=days)) & (x['_f'] <= ref + pd.Timedelta(days=1))]
    if x.empty:
        return pd.DataFrame(columns=cols)
    held = x['held_back_reason'].notna() if 'held_back_reason' in x else pd.Series(False, index=x.index)
    inter = x['mode'].astype(str).str.lower().str.contains('inter') if 'mode' in x else pd.Series(False, index=x.index)
    moved = pd.to_numeric(x.get('percent_equity_traded'), errors='coerce')
    after = pd.to_numeric(x.get('post_stake_pct'), errors='coerce')
    x = x.assign(before=after - moved, after=after)[~held & ~inter & ~(moved.abs() < 0.1)]

    def crossed(b, a):
        if _f(b) is None or _f(a) is None:
            return ''
        lo, hi = sorted((b, a))
        hit = [t for t in THRESHOLDS if lo < t <= hi]
        return (f'{hit[0]}%' if len(hit) == 1 else f'{hit[0]}–{hit[-1]}%') if hit else ''
    x = x.assign(cross=[crossed(b, a) for b, a in zip(x['before'], x['after'])], up=x['after'] > x['before'])
    return x.reindex(columns=cols + [c for c in x.columns if c not in cols])


def sast_kpi(sa: pd.DataFrame | None, ref, days: int = SAST_DAYS) -> dict | None:
    if sa is None or sa.empty:
        return None
    now, prev = sast_moves(sa, ref, days), sast_moves(sa, pd.Timestamp(ref) - pd.Timedelta(days=days), days)
    c, p = now[now['cross'] != ''], prev[prev['cross'] != '']
    sm = sast_moves(sa, ref, 7 * SPARK_WEEKS)
    spark = weekly(sm[sm['cross'] != ''], '_f', ref)
    return {'n': len(c), 'in': int(c['up'].sum()), 'out': int((~c['up'].astype(bool)).sum()), 'before': len(p),
            'spark': spark}


# ---- 3. Where the smart money agrees --------------------------------------------------------------------------------

def convergence(elig: pd.DataFrame | None, ref, stock: pd.DataFrame | None, sa: pd.DataFrame | None,
                deals: pd.DataFrame | None, names: dict | None = None) -> tuple[pd.DataFrame, dict]:
    """Companies where insiders bought AND at least one other group bought in the same window: active mutual funds at
    the latest month-end, a holder crossing up or adding 2%+ (SAST, promoters out), or a fund buying in a bulk or block
    deal. The window runs from the first day of that month-end's month to `ref`, so the fund month sits inside it.
    Ranked by how many groups bought, then by the insiders' rupees. Returns (rows, the window)."""
    names = names or {}
    ref = pd.Timestamp(ref).normalize()
    s = mf_kind(stock)
    month = s['month'].max() if not s.empty else None
    start = pd.Period(month, 'M').start_time if month is not None else ref - pd.Timedelta(days=INSIDER_DAYS)
    win = {'start': start, 'end': ref, 'month': month}
    x = _decision_rows(elig, ref)
    if x.empty:
        return pd.DataFrame(), win
    x = x[(x['seen'] >= start) & (x['seen'] <= ref + pd.Timedelta(days=1))]
    buy = x[x['side'].eq('BUY')].assign(_v=lambda f: pd.to_numeric(f['value'], errors='coerce').fillna(0.0))
    sell = x[x['side'].eq('SELL')].assign(_v=lambda f: pd.to_numeric(f['value'], errors='coerce').fillna(0.0))
    ins = buy.groupby('isin').agg(insider_cr=('_v', 'sum'), company=('company', 'last'), symbol=('nse_symbol', 'last'))
    ins['insider_cr'] = (ins['insider_cr'] - sell.groupby('isin')['_v'].sum().reindex(ins.index).fillna(0.0)) / 1e7
    ins['promoter'] = buy.assign(_pg=_promoter_mask(buy)).groupby('isin')['_pg'].any()
    ins = ins[ins['insider_cr'] * 1e7 >= CONVERGE_MIN_INSIDER]
    if ins.empty:
        return pd.DataFrame(), win
    out = ins.copy()
    if month is not None:
        m = s[s['month'] == month].assign(_n=lambda f: pd.to_numeric(f['active_net_cr'], errors='coerce'))
        m = m.drop_duplicates('isin').set_index('isin')
        out['mf_cr'] = out.index.map(m['_n'])
        out['mf_houses'] = out.index.map(m['houses_adding']) if 'houses_adding' in m else None
    else:
        out['mf_cr'], out['mf_houses'] = float('nan'), None
    out['mf'] = pd.to_numeric(out['mf_cr'], errors='coerce').ge(MF_MIN_NET_CR)
    sm = sast_moves(sa, ref, (ref - start).days + 1)
    if not sm.empty:
        prom = sm['is_promoter'].astype('boolean').fillna(False) if 'is_promoter' in sm else pd.Series(False, index=sm.index)
        big = sm[~prom & sm['up'].astype(bool)]
        out['holder'] = out.index.isin(set(big['isin'].dropna()))
        out['holder_name'] = out.index.map(big.dropna(subset=['isin']).drop_duplicates('isin').set_index('isin')['acquirer_name'])
    else:
        out['holder'], out['holder_name'] = False, None
    d = real_deals(deals)
    if not d.empty and 'client_type' in d:
        prom = d['client_is_promoter'].astype('boolean').fillna(False) if 'client_is_promoter' in d else pd.Series(False, index=d.index)
        fb = d[d['side'].eq('BUY') & d['client_type'].isin(FUND_TYPES) & ~prom & (d['date'] >= start) & (d['date'] <= ref + pd.Timedelta(days=1))]
        out['deal'] = out.index.isin(set(fb['isin'].dropna()))
        out['deal_name'] = out.index.map(fb.dropna(subset=['isin']).drop_duplicates('isin').set_index('isin')['client_name'])
    else:
        out['deal'], out['deal_name'] = False, None
    out['groups'] = 1 + out[['mf', 'holder', 'deal']].astype(bool).sum(axis=1)
    out = out[out['groups'] >= 2].reset_index()
    out['name'] = [names.get(i) or c for i, c in zip(out['isin'], out['company'])]
    return out.sort_values(['groups', 'insider_cr'], ascending=False, kind='stable').reset_index(drop=True), win


# ---- 5. Funds by sector, 6. FPI sectors, 7. coming up ---------------------------------------------------------------

def sector_map(industry: pd.DataFrame | None, securities: pd.DataFrame | None) -> tuple[dict, str]:
    """ISIN -> sector by the Funds page's rule (screens/funds_logic.industry_frame: the four-level industry table
    where it has rows, else the security master), and which of the two was used."""
    from screens import funds_logic
    ind = funds_logic.industry_frame(industry, securities)
    src = 'industry' if industry is not None and not industry.empty and 'isin' in industry else 'securities'
    i = ind.dropna(subset=['sector'])
    i = i[i['sector'].astype(str).str.strip().ne('')]
    return (dict(zip(i['isin'], i['sector'])), src) if not i.empty else ({}, '')


def mf_month_lists(stock: pd.DataFrame | None, month=None, n: int = 5) -> tuple[pd.DataFrame, pd.DataFrame]:
    s = mf_kind(stock)
    if s.empty:
        return s, s
    month = month or s['month'].max()
    x = s[s['month'] == month].assign(_n=lambda f: pd.to_numeric(f['active_net_cr'], errors='coerce'))
    return (x[x['_n'] >= MF_MIN_NET_CR].sort_values('_n', ascending=False).head(n),
            x[x['_n'] <= -MF_MIN_NET_CR].sort_values('_n').head(n))


def mf_by_sector(stock: pd.DataFrame | None, smap: dict, month=None, n: int = 10) -> tuple[pd.DataFrame, float]:
    """Active funds' net Rs crore per sector for the month, the `n` largest by size (either way), and the share of the
    month's gross net moves whose stock has no sector."""
    s = mf_kind(stock)
    if s.empty or not smap:
        return pd.DataFrame(columns=['sector', 'net_cr']), 1.0
    month = month or s['month'].max()
    x = s[s['month'] == month].assign(_n=lambda f: pd.to_numeric(f['active_net_cr'], errors='coerce').fillna(0.0))
    x = x.assign(sector=x['isin'].map(smap))
    gross = x['_n'].abs().sum()
    unplaced = float(x.loc[x['sector'].isna(), '_n'].abs().sum() / gross) if gross else 0.0
    g = x.dropna(subset=['sector']).groupby('sector', as_index=False)['_n'].sum().rename(columns={'_n': 'net_cr'})
    g = g.reindex(g['net_cr'].abs().sort_values(ascending=False).index).head(n)
    return g.sort_values('net_cr', ascending=False).reset_index(drop=True), unplaced


def fpi_sectors(df: pd.DataFrame | None) -> tuple[pd.Timestamp | None, pd.DataFrame]:
    """The latest fortnight's net FPI equity investment by sector (Grand Total out), largest buying first."""
    if df is None or df.empty or not {'fortnight_end', 'sector', 'net_equity_cr'} <= set(df.columns):
        return None, pd.DataFrame(columns=['sector', 'net_equity_cr'])
    f = df.assign(_e=pd.to_datetime(df['fortnight_end'], errors='coerce'))
    last = f['_e'].max()
    x = f[(f['_e'] == last) & ~f['sector'].astype(str).str.strip().str.lower().eq('grand total')]
    x = x.assign(net_equity_cr=pd.to_numeric(x['net_equity_cr'], errors='coerce')).dropna(subset=['net_equity_cr'])
    return last, x[['sector', 'net_equity_cr'] + [c for c in ('period_start',) if c in x]].sort_values('net_equity_cr', ascending=False).reset_index(drop=True)


def fpi_top(x: pd.DataFrame, n: int = 6) -> pd.DataFrame:
    """The `n` largest buys and `n` largest sales of a sector table (largest buying first), for a chart that stays short."""
    if x.empty:
        return x
    buy = x[x['net_equity_cr'] > 0].nlargest(n, 'net_equity_cr')
    sell = x[x['net_equity_cr'] < 0].nsmallest(n, 'net_equity_cr')
    return pd.concat([buy, sell]).sort_values('net_equity_cr', ascending=False).reset_index(drop=True)


ACTION_WORDS = {'buyback': 'Buyback', 'bonus': 'Bonus', 'split': 'Split', 'rights': 'Rights', 'consolidation': 'Consolidation'}


def coming_up(upcoming: pd.DataFrame | None, actions: pd.DataFrame | None, meetings: pd.DataFrame | None, ref,
              days: int = COMING_DAYS) -> tuple[pd.DataFrame, dict]:
    """The next `days` days: board meetings on fund raising, buybacks, preferential or rights issues, tender windows
    closing and lock-ins ending (filings_all._upcoming), and record dates of buybacks, bonuses, splits and rights.
    Dividend record dates and results meetings are counted, not listed."""
    ref = pd.Timestamp(ref).normalize()
    end = ref + pd.Timedelta(days=days)
    rows = []
    if upcoming is not None and not upcoming.empty:
        u = upcoming.assign(_d=pd.to_datetime(upcoming['date'], errors='coerce').dt.normalize())
        for r in u[(u['_d'] >= ref) & (u['_d'] <= end)].to_dict('records'):
            rows.append({'date': r['_d'], 'isin': r.get('isin'), 'company': r.get('company'), 'symbol': r.get('symbol'),
                         'kind': r.get('kind'), 'what': r.get('what'), 'value': r.get('value')})
    counts = {'dividends': 0, 'results_meetings': 0}
    if actions is not None and not actions.empty and 'purpose' in actions:
        rd = pd.to_datetime(actions['record_date'], errors='coerce') if 'record_date' in actions else pd.Series(pd.NaT, index=actions.index)
        ex = pd.to_datetime(actions['ex_date'], errors='coerce') if 'ex_date' in actions else pd.Series(pd.NaT, index=actions.index)
        a = actions.assign(_d=rd.fillna(ex).dt.normalize(), _p=actions['purpose'].astype(str).str.lower())
        a = a[(a['_d'] >= ref) & (a['_d'] <= end)]
        counts['dividends'] = int(a.loc[a['_p'].eq('dividend'), 'symbol' if 'symbol' in a else '_p'].nunique())
        a = a[a['_p'].isin(ACTION_WORDS)].drop_duplicates(['symbol', '_p', '_d'] if 'symbol' in a else ['_p', '_d'])
        for r in a.to_dict('records'):
            rows.append({'date': r['_d'], 'isin': r.get('isin'), 'company': r.get('company'), 'symbol': r.get('symbol'),
                         'kind': 'record', 'what': f'Record date: {ACTION_WORDS[r["_p"]].lower()}', 'value': None,
                         'detail': r.get('subject')})
    if meetings is not None and not meetings.empty and 'meeting_date' in meetings and 'results' in meetings:
        md = pd.to_datetime(meetings['meeting_date'], errors='coerce').dt.normalize()
        res = meetings['results'].astype('boolean').fillna(False) & (md >= ref) & (md <= end)
        counts['results_meetings'] = int(meetings.loc[res, 'symbol'].nunique()) if 'symbol' in meetings else int(res.sum())
    out = pd.DataFrame(rows)
    if not out.empty:
        # one row per company, day and event: a company's several lock-ins ending the same day are one line, sized in all
        out = out.assign(_k=out['symbol'].fillna(out['company']).fillna(out['isin']).astype(str),
                         value=pd.to_numeric(out['value'], errors='coerce'))
        out = (out.groupby(['date', '_k', 'kind', 'what'], as_index=False, sort=False, dropna=False)
               .agg(isin=('isin', 'first'), company=('company', 'first'), symbol=('symbol', 'first'),
                    value=('value', lambda v: v.sum(min_count=1)), n=('_k', 'size'))
               .drop(columns='_k'))
        out = out.sort_values(['date', 'kind'], kind='stable').reset_index(drop=True)
    return out, counts


def evidence_tag(summary: pd.DataFrame | None, code: str | None, fallback: str) -> tuple[str, str]:
    """(label, tone) of a tile's evidence: the measured verdict when the track record has the signal, else `fallback`
    ('Not measured', 'Context, not a signal', ...)."""
    if code:
        v = evidence.verdict(summary, code)
        if v['kind'] != 'not_measured':
            return v['tag'], {'buy': 'up', 'sell': 'dn'}.get(v['tone'], '')
    return fallback, ''


def headline(ins: dict | None, fpi: dict | None, mf: dict | None, span: str = 'in 30 days') -> str:
    """The page's news as a sentence, from the figures the cards show; parts with no data are left out."""
    parts = []
    if ins:
        n = ins['net']
        parts.append(f'Insiders were net {"buyers" if n >= 0 else "sellers"} of <b>{esc(kit.rupees(abs(n)))}</b> {span}')
    if fpi and fpi.get('mtd') is not None:
        word = 'bought' if fpi['mtd'] >= 0 else 'sold'
        parts.append(f'FPIs have {word} <b>{esc(crore(abs(fpi["mtd"]), signed=False))}</b> this month')
    if mf:
        word = 'added' if mf['net'] >= 0 else 'cut'
        parts.append(f'mutual funds {word} <b>{esc(crore(abs(mf["net"]), signed=False))}</b> in {pd.Period(mf["month"], "M").strftime("%B")}')
    if not parts:
        return 'The market picture fills in as the nightly tables arrive'
    s = parts[0] if len(parts) == 1 else '; '.join(parts[:-1]) + ' and ' + parts[-1]
    return s[:1].upper() + s[1:]


# ---- drawing --------------------------------------------------------------------------------------------------------

def _chart_base(chart):
    return chart.configure(font='Inter', background=C['bg']).configure_view(stroke=None).configure_axis(
        labelColor=C['ink-3'], titleColor=C['ink-3'], domain=False, ticks=False, labelFontSize=11.5, gridColor=C['line'],
        labelPadding=6).configure_legend(labelColor=C['ink-2'], title=None, orient='top', symbolType='square', labelFontSize=12)


def flows_chart(months: pd.DataFrame):
    """Diverging monthly bars, one colour per series (sign shows the direction)."""
    import altair as alt
    domain = list(dict.fromkeys(months['series']))
    rng = [{'FPIs (NSDL)': C['series-fpi'], 'Mutual funds (SEBI)': C['series-mf'], 'DIIs (NSE)': C['series-dii']}[s] for s in domain]
    base = alt.Chart(months).encode(
        x=alt.X('label:N', sort=list(dict.fromkeys(months['label'])), title=None, axis=alt.Axis(labelAngle=0, grid=False)),
        xOffset=alt.XOffset('series:N', sort=domain))
    bars = base.mark_bar(cornerRadius=2, size=14).encode(
        y=alt.Y('net_cr:Q', title=None, axis=alt.Axis(format='~s', tickCount=5, labelExpr="'₹' + datum.label + ' Cr'")),
        color=alt.Color('series:N', scale=alt.Scale(domain=domain, range=rng)),
        tooltip=[alt.Tooltip('series:N', title='Who'), alt.Tooltip('label:N', title='Month'),
                 alt.Tooltip('net_cr:Q', title='Net ₹ Cr', format=',.0f'), alt.Tooltip('days:Q', title='Days in the data')])
    zero = alt.Chart(pd.DataFrame({'y': [0]})).mark_rule(color=C['ink-4'], strokeWidth=1).encode(y='y:Q')
    return _chart_base((bars + zero).properties(height=260))


def hbar_chart(df: pd.DataFrame, label: str, value: str):
    """Horizontal bars either side of zero, the Funds page's chart (ui/charts.diverging_bars), every row kept."""
    from ui import charts
    return charts.diverging_bars(df, label=label, value=value, unit='₹ Cr', limit=len(df))


def _ev(label: str, tone: str = '') -> str:
    return f'<span class="dash-ev {tone}" title="How far the evidence goes (docs/PRODUCT.md)">{esc(label)}</span>'


def _card(title: str, value: str, tone: str, sub: str, delta: str, spark: str, ev: tuple[str, str], href: str) -> str:
    tag = 'a' if href else 'div'
    link = f' href="{esc(href, quote=True)}" target="_self"' if href else ''
    return (f'<{tag} class="dash-card dash-kpi {tone}"{link}><div class="dash-l">{esc(title)}</div>'
            f'<b class="dash-v {tone}">{value}</b><div class="dash-sub">{sub}</div>{delta}'
            f'<div class="dash-foot">{spark}{_ev(*ev)}</div></{tag}>')


def _missing_card(title: str, why: str) -> str:
    return (f'<div class="dash-card dash-kpi dash-missing"><div class="dash-l">{esc(title)}</div>'
            f'<b class="dash-v">—</b><div class="dash-sub">{esc(why)}</div></div>')


def _tone(v) -> str:
    v = _f(v)
    return '' if v is None or v == 0 else 'up' if v > 0 else 'down'


def _q(question: str, answer: str, why: str = '', anchor: str = '', ev: tuple[str, str] | None = None, href: str = '',
       link: str = '') -> str:
    return (f'<h2 class="dt-h2 dash-h2" id="{esc(anchor, quote=True)}">{esc(question)}</h2>'
            f'<p class="qa-answer">{answer}</p>'
            + (f'<p class="qa-why">{why}' + (' ' + _ev(*ev) if ev else '') + '</p>' if why or ev else ''))


def _foot(href: str, text: str) -> str:
    return f'<p class="dt-foot"><a href="{esc(href, quote=True)}" target="_self">{esc(text)} →</a></p>'


def _safe(fn, *a):
    """Draw a tile; a failure is said in its place, never hidden and never the whole page."""
    import streamlit as st
    try:
        fn(*a)
    except Exception as exc:  # noqa: BLE001
        st.html(f'<p class="dt-empty">This tile could not be drawn: {esc(type(exc).__name__)}: {esc(str(exc)[:200])}</p>')


def _month(m) -> str:
    return pd.Period(m, 'M').strftime('%B %Y') if m is not None else ''


def render():
    import streamlit as st
    from data import store

    from screens.ctx import load, need_data
    from screens.proto import _strip

    ctx = load()
    if not need_data(ctx):
        return
    ref = pd.Timestamp(ctx.ref)
    from screens import moves
    px, _, names = moves.lookups(ctx)
    summary = store.artifact('artifacts/track_summary.parquet')
    flows = store.table('market_flows')
    stock = store.table('mf_stock_month')
    _strip(ctx, ['insider filings, deals and SAST to this day', 'fund month-ends, NSDL, SEBI and NSE flows each with its own date'])
    head = st.empty()
    # the window of the insider, deal and SAST figures (ui/dates.py); funds, flows and results keep their own periods
    from ui import dates
    elig = ctx.eligible
    rng = dates.range_picker('dashboard', *dates.bounds(elig['seen'] if elig is not None and 'seen' in elig else None,
                                                         hi=ctx.ref), default='1m', presets=('1w', '1m', '3m', '6m'))
    w = Window(rng.end_ts, rng.days)
    ins = insider_kpi(elig, w.end, w.days)
    fpi = fpi_kpi(flows)
    mf = mf_kpi(stock)
    head.html(f'<div class="head ds-head dash-head"><div class="ds-kicker">Dashboard · {ref:%d %b %Y}</div>'
            f'<h1>{headline(ins, fpi, mf, w.span)}</h1>'
            '<p class="ds-dek">Who is buying what, and should you look. Each figure links to the page with its rows; '
            'the grey tag on each says how far its evidence goes.</p></div>'
            '<div class="qa-toc"><a href="#flows">Market flows</a><a href="#agree">Where the smart money agrees</a>'
            '<a href="#leaders">Insider buying</a><a href="#funds">Funds</a><a href="#fpi-sectors">FPI sectors</a>'
            '<a href="#coming">Coming up</a></div>')
    _safe(_kpis, ctx, ref, w, summary, flows, stock, ins, fpi, mf)
    _safe(_flows_tile, flows)
    _safe(_agree_tile, ctx, ref, stock, names)
    _safe(_leaders_tile, ctx, w, px, names, summary)
    _safe(_funds_tile, ctx, stock, names)
    _safe(_fpi_sector_tile)
    _safe(_coming_tile, ctx, ref)


def _kpis(ctx, ref, w, summary, flows, stock, ins, fpi, mf):
    import streamlit as st

    from screens import more_pages
    cards = []
    pct_word = lambda d: f'{d:+,.0f}'
    if ins:
        cards.append(_card(f'Insider net buying · {w.short}', esc(kit.rupees(ins['net'], signed=True)), _tone(ins['net']),
                           f'{esc(kit.rupees(ins["buy"]))} bought, {esc(kit.rupees(ins["sell"]))} sold',
                           delta_html(ins['net'], ins['net_before'], lambda d: kit.rupees(d, signed=True), w.before),
                           spark(ins['spark']), evidence_tag(summary, 'promoter_buy', 'Not measured'), '/insiders'))
        cards.append(_card('Companies with a promoter buying', f'{ins["promoter_companies"]:,}', '',
                           f'of {ins["buy_companies"]:,} with any insider buying, {w.short}',
                           delta_html(ins['promoter_companies'], ins['promoter_companies_before'], pct_word, w.before),
                           spark(ins['spark_promoter'], bars=False), evidence_tag(summary, 'promoter_buy', 'Not measured'), '/insiders'))
    else:
        cards += [_missing_card(f'Insider net buying · {w.short}', 'No open-market insider filings in the data yet.'),
                  _missing_card('Companies with a promoter buying', 'No open-market insider filings in the data yet.')]
    if fpi:
        if fpi['mtd'] is not None:
            sub = f'{_month(fpi["month"])} to date, {fpi["mtd_days"]} NSDL reports to {kit.day(fpi["last"], with_year=False)}'
            if fpi['nse_net'] is not None:
                sub += f' · NSE {kit.day(fpi["nse_day"], with_year=False)}: {crore(fpi["nse_net"])} provisional'
            cards.append(_card('FPI net, equity', esc(crore(fpi['mtd'])), _tone(fpi['mtd']), esc(sub),
                               delta_html(fpi['mtd'], fpi['prev'], crore, f'vs all of {_month(fpi.get("prev_month")).split(" ")[0]}' if fpi['prev'] is not None else ''),
                               spark(fpi['spark']), ('Context, not a stock signal', ''), '#flows'))
        else:
            cards.append(_card('FPI net, cash market', esc(crore(fpi['nse_net'])), _tone(fpi['nse_net']),
                               esc(f'NSE provisional, {kit.day(fpi["nse_day"], with_year=False)}; NSDL month to date not collected'),
                               '', '', ('Context, not a stock signal', ''), '#flows'))
    else:
        cards.append(_missing_card('FPI net, equity', 'Market flows (NSE, NSDL) are not collected yet.'))
    dii = dii_kpi(flows)
    if dii:
        note = (f'NSE provisional, {kit.day(dii["day"], with_year=False)} · month to date: {dii["month_days"]} '
                f'{"day" if dii["month_days"] == 1 else "days"} kept, {crore(dii["month_net"])} (NSE gives the latest day only)')
        cards.append(_card('DII net, cash market · latest day', esc(crore(dii['net'])), _tone(dii['net']), esc(note),
                           delta_html(dii['net'], dii['before'], crore, f'vs {kit.day(dii["before_day"], with_year=False)}') if dii['before'] is not None
                           else '<div class="dash-delta">No earlier day kept yet</div>',
                           spark(dii['spark']), ('Context, not a stock signal', ''), '#flows'))
    else:
        cards.append(_missing_card('DII net, cash market', 'NSE\'s FII/DII figures are not collected yet.'))
    if mf:
        cards.append(_card('Mutual funds, net active buying', esc(crore(mf['net'])), _tone(mf['net']),
                           esc(f'{_month(mf["month"])} month-end · {mf["bought"]} stocks bought, {mf["sold"]} sold (₹1 Cr+)'),
                           delta_html(mf['net'], mf['before'], crore, f'vs {_month(mf.get("prev_month")).split(" ")[0]}') if mf['before'] is not None
                           else '<div class="dash-delta">First month collected</div>',
                           spark(mf['spark']), ('Not measured', ''), '/funds'))
    else:
        cards.append(_missing_card('Mutual funds, net active buying', 'Fund houses\' month-end portfolios are not collected yet.'))
    dk = deals_kpi(ctx.deals, w.end, w.days)
    if dk:
        share = f' · {dk["funds"] / dk["value"] * 100:.0f}% by funds' if dk['value'] > 0 else ''
        cards.append(_card(f'Bulk and block deals · {w.short}', esc(kit.rupees(dk['value'])), '',
                           esc(f'bought by real buyers in {dk["companies"]:,} companies{share}; market makers out'),
                           delta_html(dk['value'], dk['before'], lambda d: kit.rupees(d, signed=True), w.before),
                           spark(dk['spark'], bars=False), evidence_tag(summary, 'fund_deal_buy', 'Studies: weak'), '/deals'))
    else:
        cards.append(_missing_card(f'Bulk and block deals · {w.short}', 'No deals in the data yet.'))
    rk = results_kpi(more_pages._latest_results(ctx, RESULTS_DAYS + SEASON_GAP + 7) if ctx.results is not None else None, ref)
    if rk and rk['n']:
        cards.append(_card('Results: profit up year on year', f'{rk["share"]:.0f}%', _tone(rk['share'] - 50),
                           esc(f'{rk["up"]:,} of {rk["n"]:,} companies with a year-ago quarter, filed in the last {RESULTS_DAYS} days'),
                           delta_html(rk['share'], rk['before'], lambda d: f'{d:+.0f} pts', 'vs the season before') if rk['before'] is not None
                           else f'<div class="dash-delta">The season before: {rk["before_n"]} comparable filings, too few</div>',
                           spark(rk['spark'], bars=False), ('Filed figures', ''), '/results'))
    else:
        cards.append(_missing_card('Results: profit up year on year', 'No results with a year-ago quarter in the last six weeks.'))
    sk = sast_kpi(ctx.sast, w.end, w.days)
    if sk is not None:
        cards.append(_card(f'Holders crossing a threshold · {w.short}', f'{sk["n"]:,}', '',
                           esc(f'{sk["in"]} crossed up, {sk["out"]} fell below a 5, 10, 15, 20, 25, 50 or 75% line (SAST)'),
                           delta_html(sk['n'], sk['before'], pct_word, w.before),
                           spark(sk['spark'], bars=False), ('Not measured', ''), '/stakes'))
    else:
        cards.append(_missing_card('Holders crossing a threshold', 'No SAST filings in the data yet.'))
    st.html('<div class="dash-grid">' + ''.join(cards) + '</div>')


def _flows_tile(flows):
    import streamlit as st
    fpi_d = flow_days(flows, 'nsdl', 'fpi', ('equity',))
    mf_d = flow_days(flows, 'sebi', 'mf', ('equity',))
    dii_d = flow_days(flows, 'nse', 'dii', NSE_SEGMENTS)
    parts = []
    for name, d in (('FPIs (NSDL)', fpi_d), ('Mutual funds (SEBI)', mf_d), ('DIIs (NSE)', dii_d)):
        m = flow_months(d)
        if not m.empty:
            parts.append(m.assign(series=name))
    if not parts:
        st.html(_q('Is foreign or domestic money coming in?', 'Not collected yet',
                   'The market flows (NSE, NSDL, SEBI) fill in after the first nightly run.', 'flows'))
        return
    m = pd.concat(parts, ignore_index=True)
    months = sorted(m['month'].unique())[-12:]
    m = m[m['month'].isin(months)].assign(label=lambda f: f['month'].map(lambda x: pd.Period(x, 'M').strftime('%b %y')))
    last = m[m['month'] == months[-1]].set_index('series')['net_cr']
    ans = ' · '.join(f'{s.split(" (")[0]} {crore(v)}' for s, v in last.items())
    why = (f'Net equity buying a month, ₹ crore. {_month(months[-1])} is to date. FPIs from NSDL\'s custodian reports (reporting dates); '
           'mutual funds from SEBI (about two weeks behind); ')
    why += ('DIIs from NSE\'s provisional figures, which give only the latest day, so their bars hold only the days kept since the nightly began.'
            if not dii_d.empty else 'DIIs: NSE gives the latest day only and none is kept yet.')
    st.html(_q('Is foreign or domestic money coming in?', esc(ans) + f' <span class="dash-when">in {pd.Period(months[-1], "M").strftime("%B")} so far</span>',
               esc(why), 'flows', ('Context, not a stock signal', '')))
    st.altair_chart(flows_chart(m), width='stretch')


def _agree_tile(ctx, ref, stock, names):
    import streamlit as st

    from screens.proto import _company, _table
    rows, win = convergence(ctx.eligible, ref, stock, ctx.sast, ctx.deals, names)
    span = f'{win["start"]:%d %b} to {win["end"]:%d %b}'
    if rows.empty:
        st.html(_q('Where does the smart money agree?', 'Nowhere yet',
                   esc(f'No company where insiders bought (₹25 L or more, {span}) and mutual funds added at the '
                       f'{_month(win["month"]) or "latest"} month-end, a big holder added (SAST) or a fund bought in a bulk or block deal.'
                       + ('' if win['month'] else ' Fund month-ends are not collected yet.')),
                   'agree', ('Exploratory: not measured', 'wn')))
        return
    n3 = int((rows['groups'] >= 3).sum())
    st.html(_q('Where does the smart money agree?', esc(', '.join(rows['name'].head(3))),
               esc(f'{len(rows)} companies where insiders bought, net of their sales, from {span} and another group bought too'
                   + (f'; {n3} with three or more groups' if n3 else '') + '. Mutual funds: active schemes at the '
                   f'{_month(win["month"])} month-end; holders: SAST filings, promoters out; deals: funds buying in bulk or block deals.'),
               'agree', ('Exploratory: not measured', 'wn')))
    out = []
    for r in rows.head(12).to_dict('records'):
        chips = '<span class="dt-chip up">Insiders</span>' + (' <span class="dt-chip">promoter</span>' if r.get('promoter') else '')
        chips += ' <span class="dt-chip up">Mutual funds</span>' if r.get('mf') else ''
        chips += f' <span class="dt-chip up" title="{esc(str(r.get("holder_name") or ""), quote=True)}">Big holder</span>' if r.get('holder') else ''
        chips += f' <span class="dt-chip up" title="{esc(str(r.get("deal_name") or ""), quote=True)}">Fund deal</span>' if r.get('deal') else ''
        houses = _f(r.get('mf_houses'))
        out.append({'co': _company(r['name'], r.get('symbol')), 'who': chips, 'ins': esc(crore(r['insider_cr'], signed=False)),
                    'mf': (esc(crore(r['mf_cr'])) + (f' <span class="mute">· {int(houses)} houses</span>' if houses else ''))
                          if r.get('mf') else '<span class="mute">–</span>'})
    st.html(_table([('co', 'Company', 'l'), ('who', 'Who bought', 'l'), ('ins', 'Insiders, net', 'r'), ('mf', 'Mutual funds', 'r ph')], out))
    st.html(_foot('/insiders', 'Insiders: every decision past the bar') + _foot('/funds', 'Funds: the month-end lists'))


def _leaders_tile(ctx, w, px, names, summary):
    import streamlit as st

    from screens import moves
    from screens.proto import _company, _decisions, _num, _table, day_multiple
    d, clubbed = _decisions(ctx, w.days, w.end)
    b = d[d['side'] == 'BUY'].sort_values('value', ascending=False) if not d.empty else d
    ev = evidence_tag(summary, 'promoter_buy', 'Not measured')
    if b.empty:
        st.html(_q('Who put the most money in?', f'No buy past the bar {w.span}', '', 'leaders', ev))
        return
    top = b.head(10)
    big = top.iloc[0]
    rec = moves.record('Promoter buying', summary)[0]
    st.html(_q('Who put the most money in?', esc(f'{names.get(big["isin"]) or big["company"]}: {kit.rupees(big["value"])}'),
               esc(f'The 10 largest open-market buys by promoters and directors {w.span}, of {len(b)} past the bar ({clubbed} smaller clubbed). '
                   '"× a day" is the buy against the stock\'s average day of trading (20 sessions).'
                   + (f' Promoter buying, measured on our filings: {rec}.' if rec else '')), 'leaders', ev))
    rows = []
    for r in top.to_dict('records'):
        p = px.get(r['isin']) or {}
        _, move = moves._paid_now(ctx, r['isin'], r['avg_price'], r['trade_to'], p.get('latest_close'))
        rows.append({'co': _company(names.get(r['isin']) or r['company'], r['nse_symbol']),
                     'who': esc(moves._short_who(r)) + (' <span class="dt-chip up">first in 12 months</span>' if r.get('prior_months') == 0 else ''),
                     'val': f'<b>{esc(kit.rupees(r["value"]))}</b>', 'pct': _num(r['pct_of_company'], '{:.2f}%'),
                     'adv': _num(day_multiple(r['value'], p.get('adv_20d')), '{:.1f}×'),
                     'since': (f'<span class="{"up" if move > 0 else "dn" if move < 0 else ""}">{move:+.1f}%</span>' if move is not None
                               else '<span class="mute">–</span>')})
    st.html(_table([('co', 'Company', 'l'), ('who', 'Who', 'l ph'), ('val', '₹ value', 'r'), ('pct', '% of co.', 'r'),
                    ('adv', '× a day', 'r'), ('since', 'Since paid', 'r ph')], rows))
    st.html(_foot('/insiders', 'All insider decisions'))


def _funds_tile(ctx, stock, names):
    import streamlit as st
    from data import store

    from screens.proto import _company, _table
    s = mf_kind(stock)
    if s.empty:
        st.html(_q('What are fund managers buying?', 'Not collected yet',
                   'The fund houses\' month-end portfolios fill this in after their first collection.', 'funds', ('Not measured', '')))
        return
    month = s['month'].max()
    bought, sold = mf_month_lists(stock, month)
    sec = ctx.securities
    syms = dict(zip(sec['isin'], sec['nse_symbol'])) if sec is not None and not sec.empty and 'nse_symbol' in sec else {}
    st.html(_q('What are fund managers buying?', esc(', '.join((names.get(i) or n) for i, n in zip(bought['isin'].head(3), bought['name'].head(3))) or 'No net buying'),
               esc(f'Active mutual fund schemes, {_month(month)} month-end against the month before (index funds and ETFs out), at the month-end price.'),
               'funds', ('Not measured', '')))

    def tbl(x):
        return _table([('co', 'Company', 'l'), ('net', 'Net', 'r'), ('h', 'Houses + / −', 'r ph')],
                      [{'co': _company(names.get(r['isin']) or r.get('name'), syms.get(r['isin'])), 'net': f'<b>{esc(crore(r["_n"]))}</b>',
                        'h': f'<span class="up">{int(r["houses_adding"])}</span> / <span class="dn">{int(r["houses_cutting"])}</span>'}
                       for r in x.to_dict('records')])
    left, right = st.columns(2, gap='large')
    with left:
        st.html('<p class="dash-sub-h">Bought most</p>' + (tbl(bought) if len(bought) else '<p class="dt-empty">None of ₹1 Cr or more.</p>'))
    with right:
        st.html('<p class="dash-sub-h">Sold most</p>' + (tbl(sold) if len(sold) else '<p class="dt-empty">None of ₹1 Cr or more.</p>'))
    smap, source = sector_map(store.industry_table(), sec)
    g, unplaced = mf_by_sector(stock, smap, month)
    if g.empty:
        st.html('<p class="dt-empty">No sector to group the month\'s buying by: neither the industry table nor the security master has one.</p>')
    else:
        where = 'the official classification (NSE, else BSE, else Value Research)' if source == 'industry' else 'the security master'
        st.html(f'<p class="dash-sub-h">Net by sector <span>the 10 largest either way · sector from {where}'
                + (f'; {unplaced * 100:.0f}% of the month\'s moves have no sector and are left out' if unplaced >= 0.01 else '') + '</span></p>')
        st.altair_chart(hbar_chart(g, 'sector', 'net_cr'), width='stretch')
    st.html(_foot('/funds', 'Funds: bought, sold, new positions and exits'))


def _fpi_sector_tile():
    import streamlit as st
    from data import store
    end, x = fpi_sectors(store.table('fpi_sector_flows'))
    if x.empty:
        st.html(_q('Where are foreign investors putting money?', 'Not collected yet',
                   'NSDL\'s fortnightly sector-wise FPI report fills this in after the market flows job reads it.', 'fpi-sectors',
                   ('Context, not a stock signal', '')))
        return
    start = pd.to_datetime(x['period_start'].iloc[0], errors='coerce') if 'period_start' in x else pd.NaT
    top_in = x[x['net_equity_cr'] > 0].head(2)['sector'].tolist()
    top_out = x[x['net_equity_cr'] < 0].sort_values('net_equity_cr').head(2)['sector'].tolist()
    ans = ('In: ' + ', '.join(top_in) if top_in else 'No sector bought') + ('; out: ' + ', '.join(top_out) if top_out else '')
    span = f'{start:%d %b} to {end:%d %b %Y}' if pd.notna(start) else f'the fortnight to {end:%d %b %Y}'
    st.html(_q('Where are foreign investors putting money?', esc(ans),
               esc(f'Net FPI equity investment by sector, {span} (NSDL, fortnightly; BSE\'s sector names). The total of all sectors: '
                   f'{crore(x["net_equity_cr"].sum())}.'), 'fpi-sectors', ('Context, not a stock signal', '')))
    top = fpi_top(x)
    if len(top) < len(x):
        st.html(f'<p class="dash-sub-h">The {len(top)} largest either way <span>of {len(x)} sectors</span></p>')
    st.altair_chart(hbar_chart(top, 'sector', 'net_equity_cr'), width='stretch')


def _coming_tile(ctx, ref):
    import streamlit as st

    from screens import filings_all
    from screens.proto import _company, _table
    raw, _ = filings_all._upcoming(ctx, ctx.ref, filings_all._names(ctx))
    rows, counts = coming_up(raw, ctx.actions, ctx.meetings, ref)
    extra = []
    if counts['results_meetings']:
        extra.append(f'{counts["results_meetings"]} board meetings on results')
    if counts['dividends']:
        extra.append(f'{counts["dividends"]} dividend record dates')
    why = (f'Board meetings on fund raising, a buyback, a preferential or rights issue; tender offers closing; lock-ins ending; record dates '
           f'for buybacks, bonuses, splits and rights, {ref:%d %b} to {ref + pd.Timedelta(days=COMING_DAYS):%d %b}.'
           + (f' Counted, not listed: {", ".join(extra)}.' if extra else ''))
    if rows.empty:
        st.html(_q('What is coming up this week?', 'Nothing announced for the next 7 days', esc(why), 'coming', ('As announced', '')))
        st.html(_foot('/calendar', 'Calendar: the next 30 days'))
        return
    st.html(_q('What is coming up this week?', esc(f'{len(rows)} events in the next 7 days'), esc(why), 'coming', ('As announced', '')))
    out = []
    for r in rows.head(25).to_dict('records'):
        when = f'{r["date"]:%a %d %b}'
        tone = 'wn' if r['kind'] in ('lockin', 'tender') else ''
        out.append({'d': esc(when), 'co': _company(r.get('company'), r.get('symbol')),
                    'what': f'<span class="dt-chip {tone}">{esc(str(r.get("what") or ""))}</span>'
                            + (f' <span class="mute">× {int(r["n"])}</span>' if r.get('n', 1) > 1 else ''),
                    'v': esc(kit.rupees(r['value'])) if (_f(r.get('value')) or 0) > 0 else ''})
    st.html(_table([('d', 'When', 'l'), ('co', 'Company', 'l'), ('what', 'Event', 'l'), ('v', 'Size', 'r ph')], out))
    if len(rows) > 25:
        st.html(f'<p class="dt-empty">The first 25 of {len(rows)}; the Calendar has them all.</p>')
    st.html(_foot('/calendar', 'Calendar: the next 30 days'))
