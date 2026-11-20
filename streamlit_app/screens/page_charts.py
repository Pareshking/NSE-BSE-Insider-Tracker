"""The arithmetic behind the charts on Insiders, Deals and Stakes (owner, 19 Nov 2026: "Not even pages have visualization
to understand bought or sold"). Plain pandas on the page's own frames, so each is tested in tests/test_page_charts.py;
screens/proto.py draws the result with ui/charts.py. Nothing here cleans: the rows are the clean tables' as the page
already filtered them to its date range.
"""
from __future__ import annotations

import pandas as pd

from insiders_clean import participants, signals

# ---- Insiders ---------------------------------------------------------------------------------------------------------


def insider_daily_net(eligible: pd.DataFrame | None, start, end) -> pd.DataFrame:
    """Net open-market buying by promoters, directors and KMP, one row per calendar day from `start` to `end` (both
    included) by the day the filing was made public (`seen`): day, buy, sell, net (rupees). Token buys are left out, as
    in the decisions (insiders_clean/ideas.decisions); every size counts, including the decisions under the page's bar.
    A day with no filing has buy = sell = 0 and net NaN, so the strip leaves its slot empty. Empty with no rows."""
    cols = ['day', 'buy', 'sell', 'net']
    if eligible is None or eligible.empty or not {'seen', 'side', 'value', 'person_role'} <= set(eligible.columns):
        return pd.DataFrame(columns=cols)
    t = eligible[eligible['person_role'].isin(signals.DECISION_ROLES) & eligible['side'].isin(['BUY', 'SELL'])]
    if 'is_token' in t:
        t = t[~(t['side'].eq('BUY') & t['is_token'].astype('boolean').fillna(False))]
    seen = pd.to_datetime(t['seen'], errors='coerce')
    if getattr(seen.dt, 'tz', None) is not None:
        seen = seen.dt.tz_convert('Asia/Kolkata').dt.tz_localize(None)
    s, e = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    t = t.assign(_d=seen.dt.normalize(), _v=pd.to_numeric(t['value'], errors='coerce').fillna(0.0))
    t = t[(t['_d'] >= s) & (t['_d'] <= e)]
    days = pd.date_range(s, e, freq='D')
    if t.empty or len(days) == 0:
        return pd.DataFrame(columns=cols)
    p = t.pivot_table(index='_d', columns='side', values='_v', aggfunc='sum', fill_value=0.0)
    p = p.reindex(days)
    buy = p['BUY'] if 'BUY' in p else pd.Series(float('nan'), index=days)
    sell = p['SELL'] if 'SELL' in p else pd.Series(float('nan'), index=days)
    filed = buy.notna() | sell.notna()
    out = pd.DataFrame({'day': days, 'buy': buy.fillna(0.0).to_numpy(), 'sell': sell.fillna(0.0).to_numpy()})
    out['net'] = (out['buy'] - out['sell']).where(filed.to_numpy())
    return out


def insider_net_by_company(d: pd.DataFrame | None, names: dict | None = None) -> pd.DataFrame:
    """The page's decisions netted per company: company, isin, net_pct (% of the company bought less sold), net_value
    (rupees), tag (who: "promoter", "director / KMP", or "bought and sold"). Sorted by net_pct, largest buy first.
    Empty when there are no decisions."""
    cols = ['isin', 'company', 'net_pct', 'net_value', 'tag']
    if d is None or d.empty or not {'isin', 'side', 'pct_of_company', 'value'} <= set(d.columns):
        return pd.DataFrame(columns=cols)
    names = names or {}
    sign = d['side'].map({'BUY': 1.0, 'SELL': -1.0}).fillna(0.0)
    x = d.assign(_p=pd.to_numeric(d['pct_of_company'], errors='coerce').fillna(0.0) * sign,
                 _v=pd.to_numeric(d['value'], errors='coerce').fillna(0.0) * sign,
                 _pg=d['promoter_group'].astype(bool) if 'promoter_group' in d else False)
    rows = []
    for isin, g in x.groupby('isin', sort=False):
        sides = set(g['side'])
        who = ('bought and sold' if len(sides) > 1 else 'promoter' if g['_pg'].all()
               else 'director / KMP' if not g['_pg'].any() else 'promoter, director / KMP')
        first = g.iloc[0]
        rows.append({'isin': isin, 'company': str(names.get(isin) or first.get('company') or first.get('nse_symbol') or isin),
                     'net_pct': float(g['_p'].sum()), 'net_value': float(g['_v'].sum()), 'tag': who})
    return pd.DataFrame(rows, columns=cols).sort_values('net_pct', ascending=False, kind='stable').reset_index(drop=True)


def pct_arrow(v: float) -> str:
    """A change in % of the company with its direction: ▲ 0.42%, ▼ 1.09%."""
    return f'{"▲" if v > 0 else "▼"} {abs(v):.2f}%'


# ---- Deals ------------------------------------------------------------------------------------------------------------

BUYER_GROUPS = ('Mutual funds', 'Insurers', 'Foreign investors', 'Promoters', 'Others')
_GROUP_OF_TYPE = {'mutual_fund': 'Mutual funds', 'insurer': 'Insurers', 'fpi': 'Foreign investors'}


def buyer_group(client_type, is_promoter) -> str:
    """The Deals page's five groups: a client the exchange marks as the company's promoter is "Promoters" whatever its
    name; then mutual funds, insurers and foreign investors by insiders_clean/participants' type; everyone else (banks,
    pension funds, AIFs, companies, individuals, unknown names) "Others"."""
    if bool(is_promoter) and not pd.isna(is_promoter):
        return 'Promoters'
    return _GROUP_OF_TYPE.get(client_type, 'Others')


def _real_legs(deals: pd.DataFrame | None) -> pd.DataFrame:
    """Deal legs without market makers (they buy and sell in equal measure; docs/PRODUCT.md, 07 Oct 2026)."""
    if deals is None or deals.empty or not {'side', 'value'} <= set(deals.columns):
        return pd.DataFrame()
    mm = (deals['client_is_market_maker'].astype('boolean').fillna(False) if 'client_is_market_maker' in deals
          else pd.Series(False, index=deals.index))
    d = deals[~mm & deals['side'].isin(['BUY', 'SELL'])]
    if 'client_type' in d:
        d = d[~d['client_type'].eq('prop_hft')]
    return d


def deals_by_buyer_group(deals: pd.DataFrame | None) -> pd.DataFrame:
    """Bought and sold in rupees per buyer group (BUYER_GROUPS order, groups with nothing left out): group, buy, sell,
    net, legs. The type is the clean layer's client_type, or participants.classify on the client's name where the
    column is missing. Market makers left out; every size counts."""
    cols = ['group', 'buy', 'sell', 'net', 'legs']
    d = _real_legs(deals)
    if d.empty:
        return pd.DataFrame(columns=cols)
    kind = (d['client_type'] if 'client_type' in d
            else d['client_name'].map(lambda n: participants.classify(n)[0]) if 'client_name' in d
            else pd.Series('unknown', index=d.index))
    prom = d['client_is_promoter'] if 'client_is_promoter' in d else pd.Series(False, index=d.index)
    d = d.assign(_g=[buyer_group(k, p) for k, p in zip(kind, prom)], _v=pd.to_numeric(d['value'], errors='coerce').fillna(0.0))
    g = d.groupby('_g')
    out = pd.DataFrame({'buy': d[d['side'].eq('BUY')].groupby('_g')['_v'].sum(),
                        'sell': d[d['side'].eq('SELL')].groupby('_g')['_v'].sum(), 'legs': g.size()}).fillna(0.0)
    out['net'] = out['buy'] - out['sell']
    out['legs'] = out['legs'].astype(int)
    out = out.reindex([x for x in BUYER_GROUPS if x in out.index]).rename_axis('group').reset_index()
    return out[cols]


def deals_net_by_company(deals: pd.DataFrame | None, names: dict | None = None) -> pd.DataFrame:
    """Net rupees per company over the page's deals (bought less sold, market makers left out): isin, company, net,
    legs, tag ("promoter sold" when a promoter sold in the company's deals). Largest net buy first. Every leg of a deal
    has a buyer and a seller only when both sides are in the bulk list, so a company's net is the side the exchange
    named: a promoter's block sold to many unnamed buyers reads as net selling."""
    cols = ['isin', 'company', 'net', 'legs', 'tag']
    d = _real_legs(deals)
    if d.empty or 'isin' not in d:
        return pd.DataFrame(columns=cols)
    names = names or {}
    sign = d['side'].map({'BUY': 1.0, 'SELL': -1.0})
    prom = (d['client_is_promoter'].astype('boolean').fillna(False) if 'client_is_promoter' in d
            else pd.Series(False, index=d.index))
    d = d.assign(_v=pd.to_numeric(d['value'], errors='coerce').fillna(0.0) * sign, _ps=prom & d['side'].eq('SELL'))
    rows = []
    for isin, g in d.groupby('isin', sort=False):
        first = g.iloc[0]
        rows.append({'isin': isin, 'company': str(names.get(isin) or first.get('company') or first.get('nse_symbol') or isin),
                     'net': float(g['_v'].sum()), 'legs': len(g), 'tag': 'promoter sold' if g['_ps'].any() else ''})
    return pd.DataFrame(rows, columns=cols).sort_values('net', ascending=False, kind='stable').reset_index(drop=True)


# ---- Stakes -----------------------------------------------------------------------------------------------------------


def crossings(before, after, thresholds) -> list[tuple[int, str]]:
    """Every threshold a stake went through, with its direction: [(5, 'up'), (10, 'up')] for 4% -> 12%; [] when it
    crossed none or a figure is missing."""
    try:
        b, a = float(before), float(after)
    except (TypeError, ValueError):
        return []
    if pd.isna(b) or pd.isna(a) or a == b:
        return []
    lo, hi = sorted((b, a))
    return [(t, 'up' if a > b else 'down') for t in thresholds if lo < t <= hi]


def crossing_counts(moves: pd.DataFrame | None, thresholds) -> pd.DataFrame:
    """SAST filings per threshold crossed, up and down: threshold, up, down (every threshold, zeros kept). `moves` has
    before and after (% of the company)."""
    out = pd.DataFrame({'threshold': list(thresholds), 'up': 0, 'down': 0})
    if moves is None or moves.empty or not {'before', 'after'} <= set(moves.columns):
        return out
    up, down = dict.fromkeys(thresholds, 0), dict.fromkeys(thresholds, 0)
    for b, a in zip(moves['before'], moves['after']):
        for t, way in crossings(b, a, thresholds):
            (up if way == 'up' else down)[t] += 1
    out['up'] = out['threshold'].map(up)
    out['down'] = out['threshold'].map(down)
    return out


def stake_moves(sa: pd.DataFrame | None, names: dict | None = None) -> pd.DataFrame:
    """SAST Reg 29 filings that moved a stake, as the Stakes table lists them: inter-se transfers, moves under 0.1% and
    held-back or encumbrance rows left out. company, holder, label ("Company · holder"), moved (points, a sale
    negative), before (derived: after less the move), after, promoter."""
    cols = ['company', 'holder', 'label', 'moved', 'before', 'after', 'promoter']
    if sa is None or sa.empty or 'percent_equity_traded' not in sa:
        return pd.DataFrame(columns=cols)
    names = names or {}
    moved = pd.to_numeric(sa['percent_equity_traded'], errors='coerce')
    keep = moved.notna() & moved.abs().ge(0.1)
    if 'mode' in sa:
        keep &= ~sa['mode'].astype(str).str.lower().str.contains('inter')
    if 'held_back_reason' in sa:
        keep &= ~sa['held_back_reason'].map(lambda v: isinstance(v, str) and bool(v))
    x = sa[keep]
    if x.empty:
        return pd.DataFrame(columns=cols)
    after = pd.to_numeric(x['post_stake_pct'], errors='coerce') if 'post_stake_pct' in x else pd.Series(float('nan'), index=x.index)
    mv = moved[keep]
    co = [str(names.get(i) or c or s or '') for i, c, s in zip(x.get('isin', pd.Series(None, index=x.index)),
                                                           x.get('company_display', x.get('company', pd.Series('', index=x.index))),
                                                           x.get('symbol', pd.Series('', index=x.index)))]
    holder = x['acquirer_name'].fillna('').astype(str) if 'acquirer_name' in x else pd.Series('', index=x.index)
    out = pd.DataFrame({'company': co, 'holder': holder.to_numpy(), 'moved': mv.to_numpy(), 'after': after.to_numpy(),
                        'promoter': (x['is_promoter'].astype('boolean').fillna(False).to_numpy() if 'is_promoter' in x else False)})
    out['before'] = out['after'] - out['moved']
    out['label'] = [f'{c} · {h}' if h else c for c, h in zip(out['company'], out['holder'])]
    return out[cols]
