"""The trading data on real rows (read-only), for the data chain audit of 22 Oct 2026: insider trades, pledges,
bulk/block deals, SAST, and what Today builds from them. Prints only; writes nothing to R2, calls no exchange.

SECTIONS=comma list (insider,dups,roles,price,deals,sast,pledge,timing,holding,today) picks what to print; empty = all.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from r2_writer import r2_client  # noqa: E402
from clean_writer import read_parquet  # noqa: E402

from insiders_clean import ideas, signals  # noqa: E402
from insiders_clean.bse_events import with_bse  # noqa: E402

pd.set_option('display.width', 260)
pd.set_option('display.max_columns', 40)
pd.set_option('display.max_colwidth', 40)
pd.set_option('display.max_rows', 400)

WANT = {x.strip() for x in os.environ.get('SECTIONS', '').split(',') if x.strip()}
TR_COLS = ['company', 'exchange', 'is_primary', 'listed_on', 'person_name', 'person_role', 'person_category_raw', 'kind',
           'side', 'mode_raw', 'transaction_type_raw', 'quantity', 'value', 'price', 'holding_before', 'holding_after',
           'trade_date_from', 'trade_date_to', 'broadcast_date', 'app_id', 'isin', 'symbol', 'price_check', 'flags']


def on(name: str) -> bool:
    return not WANT or name in WANT


def head(title: str) -> None:
    print(f'\n######## {title}')


def show(df: pd.DataFrame, cols=None, n=25) -> None:
    if df is None or df.empty:
        print('  (none)')
        return
    cols = [c for c in (cols or df.columns) if c in df]
    print(df[cols].head(n).to_string(index=False))


def b(s) -> pd.Series:
    return s.astype('boolean').fillna(False)


def main() -> int:
    r2 = r2_client()
    tr = read_parquet(r2, 'clean/current/insider_trades.parquet')
    deals = read_parquet(r2, 'clean/current/deals.parquet')
    sast = read_parquet(r2, 'clean/current/sast.parquet')
    bsast = read_parquet(r2, 'clean/current/bse_sast.parquet')
    sh = read_parquet(r2, 'clean/current/shareholding.parquet')
    print('insider_trades columns:', list(tr.columns))
    print('deals columns:', list(deals.columns))
    print('sast columns:', list(sast.columns))
    print('bse_sast columns:', list(bsast.columns))
    prim = tr[b(tr['is_primary'])].copy()
    for c in ('value', 'quantity', 'pct_of_mcap', 'holding_before', 'holding_after'):
        prim[c] = pd.to_numeric(prim[c], errors='coerce')
    ref = signals.as_of(tr)
    print('as of', ref)

    if on("insider"):
        head('kind x transaction_type_raw (all rows)')
        print(pd.crosstab(tr['kind'].astype(str), tr['transaction_type_raw'].astype(str)).to_string())
        head('mode_raw (every value) x kind')
        m = tr.groupby([tr['mode_raw'].astype(str), tr['kind'].astype(str), tr['exchange']]).size().unstack(fill_value=0)
        print(m.to_string())
        head('kind missing: exchange x transaction type x side')
        miss = tr[tr['kind'].eq('missing')]
        print(miss.groupby(['exchange', miss['transaction_type_raw'].astype(str), miss['side'].astype(str),
                            b(miss['is_primary'])]).size().to_string())
        head('kind missing: 25 largest (all rows)')
        show(miss.assign(_v=pd.to_numeric(miss['value'], errors='coerce')).sort_values('_v', ascending=False), TR_COLS)
        head('kind unrecognised / other: mode_raw values')
        print(tr[tr['kind'].isin(['unrecognised', 'other'])]['mode_raw'].astype(str).value_counts().head(40).to_string())
        head('Thyrocare and JB Chemicals rows (large)')
        sel = tr[tr['company'].astype(str).str.contains('Thyrocare|JB Chem', case=False)
                 & (pd.to_numeric(tr['quantity'], errors='coerce') > 1e6)]
        show(sel.sort_values(['company', 'trade_date_to']), TR_COLS + ['source_id', 'primary_id', 'security_match'], 40)

    if on('dups'):
        head('duplicate primaries: same company, person, quantity, trade_date_to (any side/kind)')
        p = prim.assign(_co=prim['isin'].fillna(prim['company'].astype(str).str.lower()),
                        _side=prim['side'].fillna('-'))
        key = ['_co', 'person_id', 'quantity', 'trade_date_to']
        g = p.dropna(subset=['person_id', 'quantity']).groupby(key, dropna=False)
        n = g['trade_id'].transform('size')
        d = p.loc[n[n > 1].index]
        print('rows', len(d), 'groups', d.groupby(key).ngroups)
        combo = d.groupby(key).agg(ex=('exchange', lambda s: ','.join(sorted(s))),
                                   sides=('_side', lambda s: ','.join(sorted(s))),
                                   kinds=('kind', lambda s: ','.join(sorted(set(s)))),
                                   noisin=('isin', lambda s: int(s.isna().sum())),
                                   apps=('app_id', lambda s: s.nunique()), v=('value', 'max'))
        print(combo.groupby(['ex', 'sides']).size().sort_values(ascending=False).head(30).to_string())
        print('-- kinds differ in group:', int((combo['kinds'].str.contains(',')).sum()))
        cross = combo[combo['ex'].str.contains('bse') & combo['ex'].str.contains('nse')]
        print('-- groups with an nse and a bse primary:', len(cross), ' value of the extra copies Rs',
              round(cross['v'].sum() / 1e7, 1), 'Cr')
        print('   by sides:', cross['sides'].value_counts().head(10).to_dict())
        print('   by kinds:', cross['kinds'].value_counts().head(15).to_dict())
        print('   with an isin missing:', int((cross['noisin'] > 0).sum()))
        same_side = cross[cross['sides'].map(lambda s: len(set(s.split(','))) == 1)]
        print('-- nse+bse same side (true duplicates?):', len(same_side), 'value Rs', round(same_side['v'].sum() / 1e7, 1), 'Cr')
        top = same_side.sort_values('v', ascending=False).head(12).reset_index()
        for _, r in top.iterrows():
            rows = p[(p['_co'] == r['_co']) & (p['person_id'] == r['person_id']) & (p['quantity'] == r['quantity'])
                     & (p['trade_date_to'] == r['trade_date_to'])]
            show(rows, TR_COLS + ['trade_date_from', 'security_match'], 6)
            print()
        nse_only = combo[~combo['ex'].str.contains('bse')]
        print('-- nse-only duplicate groups:', len(nse_only), nse_only['sides'].value_counts().head(5).to_dict())
        top = nse_only[nse_only['sides'].map(lambda s: len(set(s.split(','))) == 1)].sort_values('v', ascending=False).head(6).reset_index()
        for _, r in top.iterrows():
            rows = p[(p['_co'] == r['_co']) & (p['person_id'] == r['person_id']) & (p['quantity'] == r['quantity'])
                     & (p['trade_date_to'] == r['trade_date_to'])]
            show(rows, TR_COLS + ['nse_submission_type', 'prev_app_id'], 6)
            print()
        bse_only = combo[~combo['ex'].str.contains('nse')]
        print('-- bse-only duplicate groups:', len(bse_only), bse_only['sides'].value_counts().head(5).to_dict())
        top = bse_only[bse_only['sides'].map(lambda s: len(set(s.split(','))) == 1)].sort_values('v', ascending=False).head(6).reset_index()
        for _, r in top.iterrows():
            rows = p[(p['_co'] == r['_co']) & (p['person_id'] == r['person_id']) & (p['quantity'] == r['quantity'])
                     & (p['trade_date_to'] == r['trade_date_to'])]
            show(rows, TR_COLS + ['trade_date_from'], 6)
            print()
        el = signals.eligible(tr)
        ek = el.assign(_co=el['isin'].fillna(el['company'].astype(str)))
        ed = ek[ek.duplicated(['_co', 'person_id', 'side', 'quantity', 'trade_date_to'], keep=False)]
        print('-- eligible (signal) rows duplicated on company, person, side, quantity, date:', len(ed),
              ' by exchange', ed['exchange'].value_counts().to_dict(), ' value Rs', round(pd.to_numeric(ed['value'], errors='coerce').sum() / 2e7, 1), 'Cr')

    if on('roles'):
        head('person_category_raw x person_role (all rows)')
        print(pd.crosstab(tr['person_category_raw'].astype(str), tr['person_role'].astype(str)).to_string())
        el = signals.eligible(tr)
        rel = el[el['person_category_raw'].astype(str).str.contains('relative', case=False)]
        head('eligible market rows filed as a relative: category x role x side')
        print(rel.groupby([rel['person_category_raw'].astype(str), 'person_role', 'side']).size().to_string())
        show(rel.sort_values('value', ascending=False), TR_COLS, 15)
        head('eligible rows by role x category (BUY)')
        e = el[el['side'].eq('BUY')]
        print(e.groupby(['person_role', e['person_category_raw'].astype(str)]).size().to_string())

    if on('price'):
        head('price_check x kind (primary)')
        print(pd.crosstab(prim['kind'].astype(str), prim['price_check'].astype(str)).to_string())
        el = signals.eligible(tr)
        head('eligible (signal) rows by price_check')
        print(el['price_check'].astype(str).value_counts().to_string())
        print('value share by price_check:', (el.groupby(el['price_check'].astype(str))['value'].sum() / el['value'].sum()).round(3).to_dict())
        for pc in ('no_print', 'no_price', 'span_too_long', 'no_isin'):
            head(f'eligible, price_check {pc}: 10 largest')
            show(el[el['price_check'].eq(pc)].sort_values('value', ascending=False), TR_COLS + ['day_low', 'day_high'], 10)
        head('market rows below / above (marked only, in signals): 15 largest')
        show(el[el['price_check'].isin(['below', 'above'])].sort_values('value', ascending=False),
             TR_COLS + ['day_low', 'day_high'], 15)
        head('eligible BUY, 20 largest % of market cap')
        show(el[el['side'].eq('BUY')].sort_values('pct_of_mcap', ascending=False),
             TR_COLS + ['pct_of_mcap', 'day_low', 'day_high'], 20)
        head('eligible SELL, 12 largest % of market cap')
        show(el[el['side'].eq('SELL')].sort_values('pct_of_mcap', ascending=False),
             TR_COLS + ['pct_of_mcap', 'day_low', 'day_high'], 12)

    if on('deals'):
        d = deals.copy()
        d['value'] = pd.to_numeric(d['value'], errors='coerce')
        head('deals: client_type x rule')
        if 'client_type_rule' in d:
            print(d.groupby(['client_type', 'client_type_rule']).size().to_string())
        nm = d[~b(d['client_is_market_maker'])]
        for ty in ('fpi', 'fund_other', 'pms_aif', 'broker', 'corporate', 'trust', 'unknown'):
            head(f'deals: type {ty}, 30 largest clients by gross value (non market maker)')
            x = nm[nm['client_type'].eq(ty)].groupby(['client_name', 'client_type_rule'] if 'client_type_rule' in nm else ['client_name'])
            print(x['value'].agg(['sum', 'size']).sort_values('sum', ascending=False).head(30).assign(sum=lambda f: (f['sum'] / 1e7).round(1)).to_string())
        head('deals: fund-typed clients that filed as insiders in the same company')
        ins = tr[['isin', 'person_id', 'person_role', 'person_name']].dropna().drop_duplicates(['isin', 'person_id'])
        f = nm[nm['client_type'].isin(signals.FUND_TYPES)].merge(ins, left_on=['isin', 'client_id'], right_on=['isin', 'person_id'])
        print('legs', len(f), 'value Rs', round(f['value'].sum() / 1e7, 1), 'Cr; by role', f['person_role'].value_counts().to_dict())
        show(f.sort_values('value', ascending=False), ['date', 'company', 'exchange', 'client_name', 'client_type', 'person_role', 'side', 'quantity', 'value'], 20)
        head('deals: promoters (filed in PIT as promoter/group) by client_type')
        pr = nm.merge(ins[ins['person_role'].isin(signals.PROMOTER_ROLES)], left_on=['isin', 'client_id'], right_on=['isin', 'person_id'])
        print(pr['client_type'].value_counts().to_dict())
        head('deals: same client, security, day on both sides (non market maker), not netted at the leg')
        two = nm.groupby(['isin', 'client_id', 'date'])['side'].transform('nunique') > 1
        rt = nm[two]
        print('legs', len(rt), 'clients', rt['client_id'].nunique(), 'gross Rs', round(rt['value'].sum() / 1e7, 1), 'Cr; by type',
              rt['client_type'].value_counts().to_dict())
        net = rt.groupby(['isin', 'client_id', 'date']).agg(company=('company', 'first'), name=('client_name', 'first'),
                                                             ty=('client_type', 'first'), net=('signed_value', 'sum'),
                                                             gross=('value', 'sum'), ex=('exchange', lambda s: ','.join(sorted(set(s)))))
        net['net_share'] = (net['net'].abs() / net['gross']).round(3)
        print(net.sort_values('gross', ascending=False).head(15).to_string())
        print('-- same-day both sides across exchanges only:', int((net['ex'] == 'bse,nse').sum()))
        head('deals: same size on the other exchange')
        if 'same_size_on_other_exchange' in d:
            s2 = d[b(d['same_size_on_other_exchange'])]
            print('legs', len(s2))
            show(s2.sort_values(['date', 'client_name']), ['date', 'company', 'exchange', 'feeds', 'client_name', 'side', 'quantity', 'price', 'value'], 20)
        head('Today fund events (90 days)')
        fe = ideas.fund_events(deals, tr, ref, days=90, sh=sh)
        show(fe.sort_values('pct_of_company', ascending=False), ['company', 'list', 'kind', 'pct_of_company', 'sentence', 'value', 'last'], 25)

    if on('sast'):
        for name, s in (('sast (nse)', sast), ('bse_sast', bsast)):
            head(f'{name}: non-promoter rows by mode x action_type')
            np_ = s[~b(s['is_promoter'])]
            print(np_.groupby([np_['mode'].astype(str), np_['action_type'].astype(str)]).size().sort_values(ascending=False).head(50).to_string())
        both = with_bse(sast, bsast)
        print('with_bse rows', len(both), 'listed_on', both['listed_on'].value_counts().to_dict() if 'listed_on' in both else '')
        np_ = both[~b(both['is_promoter'])]
        enc = np_[np_['mode'].astype(str).str.contains('pledge|encumb|release|invo|revo|security|lien|nda|non.?disposal', case=False)]
        head('SAST non-promoter rows whose mode is a pledge or encumbrance')
        enc = enc.assign(security_holder=enc['acquirer_name'].fillna('').astype(str).str.contains(ideas.SECURITY_HOLDER))
        print('rows', len(enc), 'caught by SECURITY_HOLDER', int(enc['security_holder'].sum()))
        show(enc.sort_values('trade_date_to', ascending=False),
             ['company', 'acquirer_name', 'mode', 'action_type', 'pct_acquired', 'pct_sold', 'post_stake_pct', 'trade_date_to', 'listed_on', 'security_holder'], 40)
        head('Today stake events (90 days), with the filing behind each')
        ev = ideas.stake_events(both, ref, days=90)
        print('events', len(ev), ev['kind'].value_counts().to_dict())
        sm = np_.assign(when=pd.to_datetime(np_.get('transaction_date'), errors='coerce'))
        sm = sm[(sm['when'] <= ref) & (sm['when'] > ref - pd.Timedelta(days=90))]
        sm = sm[~sm['acquirer_name'].fillna('').astype(str).str.contains(ideas.SECURITY_HOLDER)]
        print('-- the non-promoter SAST rows of 90 days by mode (what stake_events reads):')
        print(sm.groupby([sm['mode'].astype(str), sm['action_type'].astype(str), sm['listed_on'].astype(str)]).size().sort_values(ascending=False).head(40).to_string())
        x = sm[~sm['mode'].astype(str).str.lower().isin(['open market', 'market'])]
        x = x.assign(p=pd.to_numeric(x['pct_acquired'], errors='coerce').fillna(0) + pd.to_numeric(x['pct_sold'], errors='coerce').fillna(0))
        print('-- not on market, 40 largest %:')
        show(x.sort_values('p', ascending=False), ['company', 'acquirer_name', 'mode', 'action_type', 'instrument', 'pct_acquired', 'pct_sold',
                                                   'post_stake_pct', 'trade_date_to', 'listed_on', 'regulation'], 40)
        head('SAST post_stake_pct > 100 or pct > 100 (base errors)')
        for c in ('post_stake_pct', 'pct_acquired', 'pct_sold'):
            v = pd.to_numeric(both[c], errors='coerce')
            print(c, 'over 100:', int((v > 100).sum()), ' negative:', int((v < 0).sum()))

    if on('pledge'):
        pl = tr[tr['kind'].astype(str).str.startswith('pledge') | tr['transaction_type_raw'].astype(str).str.contains('PLEDGE|REVOKE|INVOKE')]
        head('pledge rows: kind x exchange x primary, quantity missing')
        print(pl.groupby(['kind', 'exchange', b(pl['is_primary']), pl['quantity'].isna()]).size().to_string())
        head('pledge rows needing review (left out of pledge events): flags')
        print(pl[b(pl['needs_review'])]['flags'].value_counts().head(15).to_string())
        inv = prim[prim['kind'].eq('pledge_invoke')]
        head('pledge invocations (primary), 20 largest: not on Today')
        show(inv.sort_values('quantity', ascending=False), TR_COLS, 20)
        pe = ideas.pledge_events(tr, ref, sh, days=90)
        head('Today pledge events (90 days)')
        show(pe.sort_values('pct_of_company', ascending=False), ['company', 'list', 'kind', 'pct_of_company', 'sentence', 'last'], 30)

    if on('dups2'):
        el = signals.eligible(tr)
        ek = el.assign(_co=el['isin'].fillna(el['company'].astype(str)))
        k5 = ['_co', 'person_id', 'side', 'quantity', 'trade_date_to']
        ed = ek[ek.duplicated(k5, keep=False)].copy()
        head('eligible duplicates: why (per group)')
        rows = []
        for _, g in ed.groupby(k5):
            rows.append({'company': g['company'].iloc[0], 'person': g['person_name'].iloc[0], 'side': g['side'].iloc[0],
                         'qty': g['quantity'].iloc[0], 'to': g['trade_date_to'].iloc[0], 'n': len(g),
                         'ex': ','.join(sorted(g['exchange'])), 'same_value': g['value'].nunique() == 1,
                         'value_close': (g['value'].max() - g['value'].min()) <= max(2.0, 1e-6 * g['value'].max()),
                         'same_holding': g['holding_before'].nunique(dropna=False) == 1,
                         'chain': bool(set(g['holding_after'].dropna()) & set(g['holding_before'].dropna())),
                         'apps': ','.join(g['app_id'].astype(str)), 'types': ','.join(g['nse_submission_type'].astype(str)),
                         'bcast': ','.join(pd.to_datetime(g['broadcast_date']).dt.strftime('%d%b%y').fillna('-')),
                         'value_cr': round(float(g['value'].max()) / 1e7, 2), 'from': ','.join(pd.to_datetime(g['trade_date_from']).dt.strftime('%d%b%y').fillna('-'))})
        why = pd.DataFrame(rows)
        if len(why):
            print(why.groupby(['ex', 'same_value', 'value_close', 'same_holding', 'chain']).agg(groups=('n', 'size'), cr=('value_cr', 'sum')).to_string())
            print(why.sort_values('value_cr', ascending=False).head(40).to_string(index=False))
        head('NSE+BSE primaries of one trade whose kinds differ (any kind), by kind pair')
        p = prim.assign(_co=prim['isin'].fillna(prim['company'].astype(str).str.lower()))
        k4 = ['_co', 'person_id', 'quantity', 'trade_date_to']
        g = p.dropna(subset=['person_id', 'quantity']).groupby(k4)
        multi = p.loc[g['trade_id'].transform('size').gt(1).reindex(p.index, fill_value=False)]
        pairs = multi.groupby(k4).filter(lambda x: x['exchange'].nunique() == 2 and x['kind'].nunique() > 1)
        kp = pairs.groupby(k4).apply(lambda x: ' / '.join(f"{e}:{k}:{m}" for e, k, m in sorted(zip(x['exchange'], x['kind'], x['mode_raw'].astype(str)))))
        print(kp.value_counts().head(30).to_string())
        for pat in ('esop', 'other', 'allotment:'):
            sel = kp[kp.str.contains('market') & kp.str.contains(pat)]
            head(f'kind pairs with market and {pat}: rows')
            for key in list(sel.index)[:6]:
                show(p.set_index(k4).loc[[key]].reset_index(), TR_COLS + ['is_market'], 4)
        head('market rows whose NSE/BSE copy says another kind (signals read the market copy)')
        mk = pairs[pairs['kind'].eq('market')]
        print('rows', len(mk), 'eligible', int(b(mk['is_market']).sum()), 'value Rs', round(pd.to_numeric(mk['value'], errors='coerce').sum() / 1e7, 1), 'Cr')

    if on('intra'):
        el = signals.eligible(tr)
        pr = el[el['person_role'].isin(signals.PROMOTER_ROLES)]
        head('promoter-group market buys and sales of the same shares on the same day (another filer)')
        buys = pr[pr['side'].eq('BUY')][['isin', 'company', 'trade_date_to', 'quantity', 'person_name', 'value', 'price', 'broadcast_date']]
        sells = pr[pr['side'].eq('SELL')][['isin', 'trade_date_to', 'quantity', 'person_name', 'value', 'price']]
        m = buys.merge(sells, on=['isin', 'trade_date_to', 'quantity'], suffixes=('_buy', '_sell'))
        m = m[m['person_name_buy'] != m['person_name_sell']]
        print('pairs', len(m), 'companies', m['isin'].nunique(), 'value Rs', round(m['value_buy'].sum() / 1e7, 1), 'Cr')
        show(m.sort_values('value_buy', ascending=False), None, 30)
        head('promoter buys and sales of one company on one day, any size (group buys from group)')
        day = pr.groupby(['isin', 'trade_date_to', 'side'])['quantity'].sum().unstack()
        both = day.dropna()
        print('company-days with both sides:', len(both))
        print(both.assign(ratio=(both.min(axis=1) / both.max(axis=1)).round(3)).sort_values('BUY', ascending=False).head(20).to_string())

    if on('fundpromoter'):
        nm = deals[~b(deals['client_is_market_maker']) & deals['client_type'].isin(signals.FUND_TYPES)].copy()
        nm['value'] = pd.to_numeric(nm['value'], errors='coerce')
        both = with_bse(sast, bsast)
        promo = both[b(both['is_promoter'])][['isin', 'acquirer_id', 'acquirer_name']].dropna().drop_duplicates(['isin', 'acquirer_id'])
        head('fund-typed deal clients that file SAST as promoters of the same company')
        f = nm.merge(promo, left_on=['isin', 'client_id'], right_on=['isin', 'acquirer_id'])
        print('legs', len(f), 'value Rs', round(f['value'].sum() / 1e7, 1), 'Cr')
        show(f.sort_values('value', ascending=False), ['date', 'company', 'client_name', 'client_type', 'client_type_rule', 'side', 'quantity', 'value'], 25)
        head('fund-typed deal clients whose name starts like a promoter filer of the same company (PIT or SAST)')
        names = pd.concat([tr.loc[tr['person_role'].isin(signals.PROMOTER_ROLES), ['isin', 'person_id']].rename(columns={'person_id': 'pid'}),
                           promo[['isin', 'acquirer_id']].rename(columns={'acquirer_id': 'pid'})]).dropna().drop_duplicates()
        stem = lambda s: '-'.join(str(s).split('-')[:2])  # noqa: E731
        names['stem'] = names['pid'].map(stem)
        nm['stem'] = nm['client_id'].map(stem)
        f2 = nm.merge(names[['isin', 'stem', 'pid']], on=['isin', 'stem'])
        f2 = f2[f2['client_id'] != f2['pid']].drop_duplicates(['deal_id'])
        print('legs', len(f2), 'value Rs', round(f2['value'].sum() / 1e7, 1), 'Cr')
        show(f2.sort_values('value', ascending=False), ['date', 'company', 'client_name', 'pid', 'client_type', 'side', 'quantity', 'value'], 25)
        for co in ('EPL', 'Gland Pharma', 'Foseco', 'Dr. Agarwal'):
            head(f'{co}: insider promoter rows (any kind) Aug-Oct 2026 and SAST')
            x = tr[tr['company'].astype(str).str.startswith(co) & (pd.to_datetime(tr['trade_date_to'], errors='coerce') >= '2026-08-01')]
            show(x, TR_COLS, 12)
            s = both[both['company'].astype(str).str.contains(co, case=False, regex=False) & (pd.to_datetime(both['trade_date_to'], errors='coerce') >= '2026-08-01')]
            show(s, ['company', 'acquirer_name', 'is_promoter', 'mode', 'action_type', 'pct_acquired', 'pct_sold', 'post_stake_pct', 'trade_date_to', 'listed_on'], 12)
            d = deals[deals['company'].astype(str).str.startswith(co) & (pd.to_datetime(deals['date'], errors='coerce') >= '2026-08-01')]
            show(d, ['date', 'exchange', 'client_name', 'client_type', 'side', 'quantity', 'price', 'value'], 15)

    if on('sectype'):
        from clean_writer import read_archive
        for ex in ('nse', 'bse'):
            a = read_archive(r2, ex, 'insider_trading')
            head(f'archive {ex} insider_trading: {0 if a is None else len(a)} rows')
            if a is None:
                continue
            cols = [c for c in a.columns if any(w in c.lower() for w in ('sec', 'instrument', 'type'))]
            print('columns:', cols)
            for c in cols:
                print(f'-- {c}:', a[c].astype(str).value_counts().head(15).to_dict())
            st = next((c for c in ('secType', 'security_type', 'canonical_security_type') if c in a), None)
            if st:
                j = tr.merge(a[['canonical_event_id', st]].rename(columns={'canonical_event_id': 'source_id'}), on='source_id', how='left')
                e = signals.eligible(j)
                print(f'-- eligible rows by {st}:', e[st].astype(str).value_counts().head(15).to_dict())
                odd = e[~e[st].astype(str).str.lower().str.contains('equity|share|^none$|^nan$|^$', regex=True)]
                show(odd.sort_values('value', ascending=False), TR_COLS + [st], 20)

    if on('pgroup'):
        from insiders_clean import promoter_group as pgm
        pg = read_parquet(r2, 'clean/current/promoter_group.parquet')
        head(f'promoter_group members: {0 if pg is None else len(pg)} rows')
        if pg is not None and not pg.empty:
            lists = pgm.latest_lists(pg)
            ids = set(zip(lists['co'], lists['member_id'])) | set(zip(lists['co'], lists['member_alt_id'].dropna()))
            d = deals[~b(deals['client_is_market_maker'])].copy()
            d['value'] = pd.to_numeric(d['value'], errors='coerce')
            d['member'] = [(i, c) in ids for i, c in zip(d['isin'], d['client_id'])]
            f = d[d['member'] & d['client_type'].isin(signals.FUND_TYPES)]
            print('fund-typed legs by promoter-group members:', len(f), 'Rs', round(f['value'].sum() / 1e7, 1), 'Cr')
            show(f.sort_values('value', ascending=False), ['date', 'company', 'client_name', 'client_type', 'side', 'quantity', 'value'], 25)
            allm = d[d['member']]
            print('all legs by members:', len(allm), allm['client_type'].value_counts().to_dict())
            for sym in ('GLAND', 'EPL', 'FOSECOIND', 'TENNIND'):
                x = pg[pg['symbol'].astype(str).str.upper().eq(sym)]
                q = x['quarter_end'].max() if len(x) else None
                print(f'-- {sym} latest {q}:', x[x['quarter_end'] == q]['member_name'].astype(str).tolist()[:12])

    if on('after'):
        # What the fixes of this branch change, applied to the clean rows of today (before the next Clean only).
        from insiders_clean import insider as ins
        from insiders_clean import promoter_group as pgm
        head('after: roles re-read from the filed category')
        new_role = tr['person_category_raw'].map(ins.classify_role)
        moved = tr[(new_role != tr['person_role']) & tr['person_role_source'].eq('filing')]
        print(pd.crosstab(moved['person_role'], new_role[moved.index]).to_string())
        el_before = signals.eligible(tr)
        t2 = tr.copy()
        t2.loc[moved.index, 'person_role'] = new_role[moved.index]
        head('after: kinds from the transaction type (kind missing before)')
        by_type = tr['transaction_type_raw'].map(ins.kind_from_type)
        hit = tr['kind'].eq('missing') & by_type.notna()
        print(pd.crosstab(by_type[hit], tr.loc[hit, 'exchange']).to_string())
        head('after: one trade kept more than once (primaries, refiled with other holdings)')
        p2 = t2[b(t2['is_primary'])].copy()
        for c in ('value', 'quantity', 'holding_before', 'holding_after'):
            p2[c] = pd.to_numeric(p2[c], errors='coerce')
        p2['_value_key'] = p2['value'].round(-1)
        p2['_key_to'] = p2['trade_date_to'].where(p2['exchange'] != 'bse', p2['trade_date_from'])
        p2 = p2.sort_values('broadcast_date', ascending=False)
        refiled = ins._refiled_with_other_holdings(p2, ['exchange', 'isin', 'symbol', 'person_id', 'side', 'quantity', '_value_key',
                                                       'trade_date_from', '_key_to', 'holding_before', 'holding_after'])
        r = p2.loc[refiled]
        print('rows', len(r), 'by exchange', r['exchange'].value_counts().to_dict(), 'Rs', round(r['value'].sum() / 1e7, 1), 'Cr;',
              'eligible among them', int(r.index.isin(el_before.index).sum()))
        show(r.sort_values('value', ascending=False), TR_COLS, 12)
        head('after: promoter-group transfers on the market (primaries)')
        gt = ins._promoter_group_transfers(p2.assign(kind=p2['kind'].astype(str)))
        g = p2[gt]
        print('rows', len(g), 'companies', g['isin'].nunique(), 'Rs', round(g['value'].sum() / 1e7, 1), 'Cr')
        t2.loc[refiled, 'is_primary'] = False
        t2.loc[g.index, 'is_market'] = False
        t2.loc[g.index, 'kind'] = 'inter_se'
        el_after = signals.eligible(t2)
        for side in ('BUY', 'SELL'):
            head(f'after: Today insider events (90 days), {side}: before vs after')
            fn = ideas.worth_a_look if side == 'BUY' else ideas.watch_out
            a, z = fn(el_before, ref, sh, limit=10_000), fn(el_after, ref, sh, limit=10_000)
            ka = set(a['company']) if len(a) else set()
            kz = set(z['company']) if len(z) else set()
            print('gone:', sorted(ka - kz)[:30])
            print('new:', sorted(kz - ka)[:30])
            if len(a) and len(z):
                col = 'pct_of_company' if 'pct_of_company' in a else 'size'
                m = a.set_index('company')[col].to_frame('before').join(z.set_index('company')[col].to_frame('after'), how='inner')
                ch = m[(m['before'] - m['after']).abs() > 0.01]
                print('size changed:', ch.round(2).head(20).to_dict('index'))
        head('after: clusters (30 days) before vs after')
        ca, cz = signals.clusters(el_before, ref), signals.clusters(el_after, ref)
        print('gone:', sorted(set(ca['company']) - set(cz['company'])), ' new:', sorted(set(cz['company']) - set(ca['company'])))
        head('after: deal clients who are promoters; Today fund and promoter-deal events')
        pg = read_parquet(r2, 'clean/current/promoter_group.parquet')
        dm, rep = pgm.mark_deal_promoters(deals, pg, t2)
        print(rep)
        x = dm[dm['client_is_promoter'] & dm['client_type'].isin(signals.FUND_TYPES)]
        show(x.assign(value=pd.to_numeric(x['value'], errors='coerce')).sort_values('value', ascending=False),
             ['date', 'company', 'client_name', 'client_type', 'client_promoter_basis', 'side', 'quantity', 'value'], 15)
        fa, fz = ideas.fund_events(deals, tr, ref, days=90, sh=sh), ideas.fund_events(dm, t2, ref, days=90, sh=sh)
        m = fa.set_index('company')[['kind', 'pct_of_company']].join(fz.set_index('company')[['kind', 'pct_of_company']],
                                                                     how='outer', lsuffix='_before', rsuffix='_after')
        print(m[(m['kind_before'] != m['kind_after']) | ((m['pct_of_company_before'] - m['pct_of_company_after']).abs() > 0.01)]
              .round(2).to_string())
        pe = ideas.promoter_deal_events(dm, t2, ref, days=90, sh=sh)
        show(pe.sort_values('pct_of_company', ascending=False), ['company', 'list', 'kind', 'pct_of_company', 'sentence'], 20)
        head('after: pledge invocations and SAST events (90 days)')
        pv = ideas.pledge_events(t2, ref, sh, days=90)
        show(pv[pv['kind'].eq('Pledge invoked')], ['company', 'kind', 'pct_of_company', 'sentence', 'last'], 20)
        st = ideas.stake_events(with_bse(sast, bsast), ref, days=90)
        show(st[st['sentence'].str.contains(r'\(', regex=True)].sort_values('pct_of_company', ascending=False),
             ['company', 'kind', 'pct_of_company', 'sentence'], 15)

    if on('enc'):
        from insiders_clean import insider as ins
        enc = read_parquet(r2, 'clean/current/encumbrances.parquet')
        head(f'SAST Reg 31 encumbrances: {0 if enc is None else len(enc)} rows')
        if enc is not None and not enc.empty:
            print(pd.crosstab(enc['event_type'].astype(str), enc['encumbrance_type'].astype(str)).to_string())
            print('broadcast', enc['broadcast_date'].min(), '..', enc['broadcast_date'].max())
            for sym in ('THYROCARE', 'VIKRAMSOLR', 'SIGACHI', 'HUBTOWN', 'AEQUS', 'JAYNECOIND', 'PARADEEP'):
                x = enc[enc['symbol'].astype(str).str.upper().eq(sym)]
                print(f'-- {sym}: {len(x)}')
                show(x.sort_values('event_from'), ['promoter_name', 'lender', 'event_type', 'encumbrance_type', 'event_from', 'event_to',
                                                    'shares', 'pct_of_company', 'broadcast_date'], 8)
            # PIT pledge rows (primary, promoter roles) against Reg 31: same NSE symbol and promoter, shares within 1%,
            # the trade dates within 7 days of the event's.
            want = {'Creation': 'pledge_create', 'Release': 'pledge_revoke', 'Invocation': 'pledge_invoke'}
            e = enc.assign(sym=enc['symbol'].astype(str).str.upper(), pid=enc['promoter_id'],
                           d=pd.to_datetime(enc['event_to'], errors='coerce').fillna(pd.to_datetime(enc['event_from'], errors='coerce')),
                           sh=pd.to_numeric(enc['shares'], errors='coerce'), k=enc['event_type'].map(want))
            p = prim[prim['person_role'].isin(signals.PROMOTER_ROLES)].copy()
            p['kind2'] = p['kind'].where(~(p['kind'].eq('missing') & p['transaction_type_raw'].map(ins.kind_from_type).notna()),
                                         p['transaction_type_raw'].map(ins.kind_from_type))
            p = p[p['kind2'].astype(str).str.startswith('pledge') | p['kind'].eq('missing')]
            p = p.assign(sym=p['nse_symbol'].astype(str).str.upper(), d=pd.to_datetime(p['trade_date_to'], errors='coerce'))
            m = p.merge(e[['sym', 'pid', 'd', 'sh', 'k', 'encumbrance_type']], left_on=['sym', 'person_id'], right_on=['sym', 'pid'],
                        suffixes=('', '_e'))
            m = m[(m['d'] - m['d_e']).abs().dt.days.le(7)]
            m = m[m['quantity'].isna() | ((m['quantity'] - m['sh']).abs() <= (m['sh'] * 0.01).clip(lower=1))]
            m = m.drop_duplicates('trade_id')
            print('PIT pledge rows in the window of the Reg 31 data matched to an event:', len(m))
            print(pd.crosstab(m['kind2'].astype(str), m['k'].astype(str)).to_string())
            print('-- kind before the fix (missing) of matched rows:', m.loc[m['kind'].eq('missing'), 'k'].value_counts().to_dict())
            print('-- Reg 31 type of matched rows:', m['encumbrance_type'].value_counts().to_dict())
            lo = e['d'].min()
            pw = p[p['d'] >= lo]
            print('PIT promoter pledge rows since', lo, ':', len(pw), ' matched', int(pw['trade_id'].isin(m['trade_id']).sum()))
            ew = e[e['sym'].isin(set(prim['nse_symbol'].dropna().astype(str).str.upper()))]
            print('Reg 31 events of companies with PIT rows:', len(ew), ' by type', ew['k'].value_counts().to_dict())

    if on('timing'):
        from insiders_clean import trading_window
        el = signals.eligible(tr)
        head(f'timing of the {len(el)} open-market rows the signals read: trade to public, in sessions')
        lag = pd.to_numeric(el['trade_to_public_sessions'], errors='coerce')
        print(lag.describe(percentiles=[.5, .75, .9, .95, .99]).round(1).to_string())
        bins = pd.cut(lag, [-1, 2, 5, 10, 30, 60, 10_000], labels=['0-2', '3-5', '6-10', '11-30', '31-60', '61+'])
        print(pd.crosstab(bins, el['exchange'], margins=True).to_string())
        print('insider_filed_late', b(el['insider_filed_late']).sum(), ' company_filed_late', b(el['company_filed_late']).sum(),
              ' no lag (a date missing)', int(lag.isna().sum()))
        print('value Rs Cr by lag:', (pd.to_numeric(el['value'], errors='coerce').groupby(bins, observed=False).sum() / 1e7).round(0).to_dict())
        late = el[lag.gt(30)].assign(_lag=lag[lag.gt(30)])
        show(late.sort_values('value', ascending=False), ['company', 'person_name', 'person_role', 'side', 'value', 'trade_date_to',
                                                          'intimation_date', 'broadcast_date', '_lag', 'exchange'], 15)
        # The chart marks the day made public (screens/ctx._marks uses `seen` = broadcast_date): count marks a
        # trade-date chart would put elsewhere by more than 5 sessions.
        print('marks more than 5 sessions after the trade:', int(lag.gt(5).sum()))

        head('open-market rows inside a closed trading window (quarter end to 48 hours after that quarter\'s results)')
        nse_m = read_parquet(r2, 'clean/current/meetings.parquet')
        meet = with_bse(pd.DataFrame() if nse_m is None else nse_m, read_parquet(r2, 'clean/current/bse_meetings.parquet'))
        rd = trading_window.results_dates(meet)
        day = pd.to_datetime(el['trade_date_from'], errors='coerce').fillna(pd.to_datetime(el['trade_date_to'], errors='coerce'))
        qe = day.dt.to_period('Q').dt.start_time - pd.Timedelta(days=1)
        x = el.assign(_day=day, _qe=qe, key=el['isin'].astype('string'))
        x2 = el.assign(_day=day, _qe=qe, key='sym:' + el['nse_symbol'].astype('string').str.upper())
        both = pd.concat([x, x2]).dropna(subset=['key', '_day'])
        j = both[['trade_id', 'key', '_day', '_qe']].merge(rd[['key', 'results_date']], on='key')
        j = j[(j['results_date'] > j['_qe']) & (j['results_date'] <= j['_qe'] + pd.Timedelta(days=100))]
        first = j.sort_values('results_date').drop_duplicates('trade_id')
        known = el['trade_id'].isin(first['trade_id'])
        closed = first[first['_day'] < first['results_date'] + pd.Timedelta(days=trading_window.WINDOW_HOURS_DAYS)]
        c = el[el['trade_id'].isin(closed['trade_id'])].merge(closed[['trade_id', 'results_date']], on='trade_id')
        print('rows with that quarter\'s results date known:', int(known.sum()), 'of', len(el), '; inside the closed window:', len(c),
              f'(Rs {pd.to_numeric(c["value"], errors="coerce").sum() / 1e7:,.0f} Cr)')
        if len(c):
            print(pd.crosstab(c['person_role'], c['side'], margins=True).to_string())
            show(c.sort_values('value', ascending=False), ['company', 'person_name', 'person_role', 'side', 'value', 'trade_date_from',
                                                           'trade_date_to', 'results_date', 'broadcast_date', 'mode_raw'], 25)

    if on('holding'):
        el = signals.eligible(tr)
        head('holding before / after against the shares traded (holding_check)')
        print('all primary rows:', prim['holding_check'].value_counts().to_dict())
        print('rows the signals read:', el['holding_check'].value_counts().to_dict())
        d = el[el['holding_check'].astype(str).str.startswith(('differs', 'against'))]
        show(d.sort_values('value', ascending=False), ['company', 'person_name', 'side', 'quantity', 'holding_before', 'holding_after',
                                                       'value', 'holding_check', 'flags', 'exchange'], 15)
        if 'holding_change_pct' in el:
            tot = None
            if sh is not None and {'isin', 'total_shares', 'quarter_end'} <= set(sh.columns):
                tot = sh.sort_values('quarter_end').drop_duplicates('isin', keep='last').set_index('isin')['total_shares']
            if tot is not None:
                mine = pd.to_numeric(el['quantity'], errors='coerce') / el['isin'].map(tot) * 100
                filed = pd.to_numeric(el['holding_change_pct'], errors='coerce').abs()
                ok = mine.notna() & filed.notna()
                gap = (mine - filed).abs()[ok]
                print('% of the company, shares / latest total shares vs as filed: rows', int(ok.sum()),
                      ' within 0.01 pt', int(gap.le(0.01).sum()), ' 0.01-0.1', int(gap.between(0.01, 0.1, inclusive='right').sum()),
                      ' over 0.1', int(gap.gt(0.1).sum()))
                w = el[ok].assign(_mine=mine[ok], _filed=filed[ok], _gap=gap)
                show(w.sort_values('_gap', ascending=False), ['company', 'person_name', 'quantity', '_mine', '_filed', '_gap', 'trade_date_to'], 12)

    if on('cases'):
        head('cases: rows behind the findings')
        tv = pd.to_datetime(tr['trade_date_to'], errors='coerce')
        for co, a, z in (('Thyrocare', '2026-08-10', '2026-08-20'), ('VIP Industries', '2025-12-20', '2025-12-28'),
                         ('Mkventures', '2026-09-20', '2026-09-26'), ('Bajaj Finserv', '2026-04-27', '2026-04-27'),
                         ('Info Edge', '2026-08-18', '2026-08-20'), ('Innova Captab', '2026-09-30', '2026-09-30'),
                         ('Vikram Solar', '2026-02-19', '2026-02-19'), ('Stylam', '2026-02-17', '2026-02-17')):
            x = tr[tr['company'].astype(str).str.startswith(co) & (tv >= a) & (tv <= z)]
            print(f'-- {co} {a}..{z}: {len(x)} rows')
            show(x.sort_values(['person_name', 'exchange']), TR_COLS + ['source_id', 'primary_id', 'needs_review', 'source_url'], 30)

    if on('today'):
        el = signals.eligible(tr)
        head('Today insider events (90 days)')
        ev = ideas.insider_events(el, ref, sh, None, days=90)
        show(ev.sort_values('pct_of_company', ascending=False).drop_duplicates('isin'),
             ['company', 'list', 'kind', 'pct_of_company', 'sentence', 'value', 'last'], 40)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
