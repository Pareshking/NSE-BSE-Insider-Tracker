"""The corporate data as it really is in the clean tables (read-only), for the data chain audit of 22 Oct 2026:
shareholding and pledges, preferential / QIP / rights issues, buybacks, corporate actions and the split/bonus
adjustment of prices, results, market cap and the Rs 100 Cr universe. SECTIONS (comma list) picks parts;
SYMBOLS adds companies to look at row by row. Prints only; writes nothing to R2, calls no exchange.
"""
from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from r2_writer import BUCKET, r2_client  # noqa: E402
from clean_writer import list_keys, read_parquet  # noqa: E402

from insiders_clean import adjust  # noqa: E402

pd.set_option('display.width', 260)
pd.set_option('display.max_columns', 40)
pd.set_option('display.max_colwidth', 40)
pd.set_option('display.max_rows', 400)


def show(title, df, cols=None, n=40):
    print(f'--- {title}: {len(df)} rows')
    if df is not None and len(df):
        d = df[[c for c in cols if c in df]] if cols else df
        print(d.head(n).to_string(index=False))


def vc(s, n=25):
    return s.astype(str).value_counts(dropna=False).head(n).to_string().replace('\n', '\n     ')


def table(r2, name):
    df = read_parquet(r2, f'clean/current/{name}.parquet')
    return df if df is not None else pd.DataFrame()


def num(s):
    return pd.to_numeric(s, errors='coerce')


def shareholding(r2, ctx):
    print('\n################ SHAREHOLDING')
    sh = ctx['sh']
    print('columns:', list(sh.columns))
    sh = sh.copy()
    sh['quarter_end'] = pd.to_datetime(sh['quarter_end'], errors='coerce')
    latest = sh.sort_values(['quarter_end', 'submission_date']).drop_duplicates('symbol', keep='last')
    print(f'rows {len(sh)}, companies {sh["symbol"].nunique()}')
    print('  latest quarter of each company:\n     ' + vc(latest['quarter_end'].dt.date, 8))
    print('  xbrl_status of latest:\n     ' + vc(latest['xbrl_status'].astype(str).str.split(':').str[0]))
    print('  shareholding_stale of latest:\n     ' + vc(latest['shareholding_stale']))
    uni = ctx['uni_in']
    lu = latest[latest['isin'].isin(uni)]
    print(f'  in universe: {len(lu)} companies; latest xbrl not ok: {int(lu["xbrl_status"].astype(str).ne("ok").sum())};'
          f' stale (pledge carried from an earlier quarter): {int(lu["shareholding_stale"].astype("boolean").fillna(False).sum())}')
    st = lu[lu['shareholding_stale'].astype('boolean').fillna(False)]
    show('latest rows with a carried pledge (sample)', st.sort_values('quarter_end'),
         ['symbol', 'quarter_end', 'submission_date', 'xbrl_status', 'promoter_holding_pct', 'promoter_pledge_pct',
          'promoter_pledged_shares', 'promoter_shares'], 20)
    # where did the carried value come from
    if len(st):
        prev = sh[sh['symbol'].isin(st['symbol'])].sort_values('quarter_end')
        show('their quarters', prev[prev['symbol'].isin(st['symbol'].head(5))],
             ['symbol', 'quarter_end', 'xbrl_status', 'promoter_holding_pct', 'promoter_pledge_pct', 'promoter_pledged_shares',
              'promoter_shares', 'shareholding_stale'], 30)
    ps, ts = num(lu['promoter_shares']), num(lu['total_shares'])
    base = num(lu['pct_base_shares']) if 'pct_base_shares' in lu else pd.Series(np.nan, index=lu.index)
    listed = num(lu['promoter_holding_pct'])
    ok = lu['xbrl_status'].astype(str).eq('ok')
    d_total = (listed - ps / ts * 100).where(ok)
    d_base = (listed - ps / base * 100).where(ok)
    print(f'  promoter % (NSE listing) vs promoter/total shares (XBRL): |diff|>0.05 in {int((d_total.abs() > 0.05).sum())}'
          f' of {int(d_total.notna().sum())}; vs promoter/(total less DR): {int((d_base.abs() > 0.05).sum())} of {int(d_base.notna().sum())}')
    big = lu.assign(listed=listed, by_total=ps / ts * 100, by_base=ps / base * 100, d=d_total.abs()).sort_values('d', ascending=False)
    show('largest gaps listing vs XBRL', big[big['d'] > 0.05],
         ['symbol', 'quarter_end', 'listed', 'by_total', 'by_base', 'promoter_shares', 'total_shares', 'pct_base_shares', 'dr_shares'], 15)
    pl = num(lu['promoter_pledged_shares'])
    calc = (pl / ps * 100).where(ps > 0)
    dp = (num(lu['promoter_pledge_pct']) - calc).abs()
    print(f'  pledge % vs pledged/promoter shares: |diff|>0.05 in {int((dp > 0.05).sum())} (non-stale {int(((dp > 0.05) & ~lu["shareholding_stale"].astype("boolean").fillna(False)).sum())})')
    show('pledge gaps', lu.assign(calc=calc, d=dp).sort_values('d', ascending=False).query('d > 0.05'),
         ['symbol', 'quarter_end', 'xbrl_status', 'shareholding_stale', 'promoter_pledge_pct', 'calc', 'promoter_pledged_shares', 'promoter_shares'], 15)
    hp = lu.assign(of_company=pl / ts * 100).sort_values('promoter_pledge_pct', ascending=False)
    show('highest pledges (of promoter shares; of the company)', hp,
         ['symbol', 'quarter_end', 'promoter_holding_pct', 'promoter_pledge_pct', 'of_company', 'promoter_encumbered_pct'], 12)
    dup = sh[sh.duplicated(['isin', 'quarter_end'], keep=False) & sh['isin'].notna()]
    show('two rows for one ISIN and quarter', dup.sort_values(['isin', 'quarter_end']),
         ['isin', 'symbol', 'quarter_end', 'submission_date', 'promoter_holding_pct'], 12)
    no_sh = ctx['uni'][ctx['uni']['in_universe'].astype(bool) & ~ctx['uni']['isin'].isin(set(sh['isin'].dropna()))]
    bsh = ctx['bsh']
    no_any = no_sh[~no_sh['isin'].isin(set(bsh['isin'].dropna()) if len(bsh) else set())]
    print(f'  universe companies with no NSE shareholding row: {len(no_sh)} (of them on BSE shareholding: {len(no_sh) - len(no_any)}; none: {len(no_any)})')
    show('universe companies with no shareholding at all (largest first)', no_any.sort_values('market_cap', ascending=False),
         ['isin', 'company', 'nse_symbol', 'bse_code', 'market_cap'], 25)
    old = lu[lu['quarter_end'] < pd.Timestamp('2026-06-30')]
    show('universe companies whose latest NSE quarter is before Jun 2026', old.sort_values('quarter_end'),
         ['symbol', 'isin', 'quarter_end', 'submission_date', 'promoter_holding_pct'], 20)
    if len(bsh):
        print('\n  bse_shareholding columns:', list(bsh.columns))
        print('  bse xbrl_status:\n     ' + vc(bsh['xbrl_status'].astype(str).str.split(':').str[0]) if 'xbrl_status' in bsh else '')
        bsh = bsh.copy()
        bsh['quarter_end'] = pd.to_datetime(bsh['quarter_end'], errors='coerce')
        bl = bsh.sort_values('quarter_end').drop_duplicates('isin', keep='last')
        both = bl.merge(latest[['isin', 'quarter_end', 'promoter_holding_pct', 'promoter_pledge_pct']], on=['isin', 'quarter_end'],
                        suffixes=('_bse', '_nse'))
        dd = (num(both['promoter_holding_pct_bse']) - num(both['promoter_holding_pct_nse'])).abs()
        print(f'  same ISIN and quarter on both: {len(both)}; promoter % differs >0.05 in {int((dd > 0.05).sum())}')
        show('BSE vs NSE promoter % gaps', both.assign(d=dd).sort_values('d', ascending=False).query('d > 0.05'),
             ['isin', 'quarter_end', 'promoter_holding_pct_bse', 'promoter_holding_pct_nse', 'promoter_pledge_pct_bse', 'promoter_pledge_pct_nse'], 10)
    for sym in ctx['symbols']:
        q = sh[sh['symbol'].astype(str).str.upper() == sym].sort_values('quarter_end')
        show(f'{sym} shareholding', q, ['isin', 'isin_filed', 'quarter_end', 'submission_date', 'record_id', 'revised', 'xbrl_status',
                                         'promoter_holding_pct', 'promoter_shares', 'total_shares', 'pct_base_shares', 'dr_shares',
                                         'promoter_pledged_shares', 'promoter_pledge_pct', 'shareholding_stale'])


def issues(r2, ctx):
    print('\n################ ISSUES')
    pref = table(r2, 'preferential')
    print('preferential columns:', list(pref.columns))
    print('  stage:\n     ' + vc(pref['stage']))
    print('  allottee_category x stage:\n     ' + pd.crosstab(pref['allottee_category'].astype(str), pref['stage']).to_string().replace('\n', '\n     '))
    print('  instruments:\n     ' + vc(pref['instruments']))
    print('  link_status:\n     ' + vc(pref['link_status']))
    print('  amount_unreliable:', int(pref['amount_unreliable'].sum()))
    ls = pref[pref['stage'] == 'listing'].copy()
    implied = num(ls['shares_allotted']) * num(ls['offer_price'])
    ratio = num(ls['amount_raised']) / implied
    print('  listing: amount_raised / (shares x price) quantiles:', ratio.quantile([.01, .05, .25, .5, .75, .95, .99]).round(3).to_dict())
    ls['ratio'] = ratio
    show('listing rows with ratio not ~1', ls[(ratio < 0.9) | (ratio > 1.1)],
         ['symbol', 'posted_on', 'allotment_date', 'instruments', 'offer_price', 'shares_allotted', 'amount_raised', 'amount_total', 'ratio'], 25)
    warr = pref[pref['instruments'].astype(str).str.contains('arrant', na=False)]
    show('rows with warrants among the instruments', warr.sort_values('posted_on', ascending=False),
         ['symbol', 'stage', 'posted_on', 'board_date', 'allotment_date', 'instruments', 'offer_price', 'shares_allotted',
          'securities_proposed', 'amount_raised', 'amount_total', 'allottee_category', 'link_status'], 30)
    for c in ('amount_total', 'amount_raised'):
        v = num(pref[c])
        print(f'  {c} quantiles (Cr):', (v.quantile([.01, .5, .9, .99, 1.0]) / 1e7).round(2).to_dict())
    top = pref.assign(_a=num(pref['amount_raised']).fillna(num(pref['amount_total']))).sort_values('_a', ascending=False)
    show('largest amounts', top, ['symbol', 'company', 'stage', 'posted_on', 'instruments', 'offer_price', 'shares_allotted',
                                  'securities_proposed', 'amount_raised', 'amount_total'], 15)
    # implied price of approvals: amount_total / securities_proposed vs filed price
    ip = pref[pref['stage'] == 'in_principle'].copy()
    ip['per_security'] = num(ip['amount_total']) / num(ip['securities_proposed'])
    ip['vs_icdr'] = ip['per_security'] / num(ip['icdr_min_price'])
    print('  in-principle amount_total / securities_proposed over the filed ICDR minimum:', ip['vs_icdr'].quantile([.01, .05, .25, .5, .75, .95, .99]).round(3).to_dict())
    show('approvals whose amount is far from proposed x ICDR minimum', ip[(ip['vs_icdr'] < 0.5) | (ip['vs_icdr'] > 3)],
         ['symbol', 'posted_on', 'instruments', 'securities_proposed', 'icdr_min_price', 'amount_total', 'per_security', 'vs_icdr'], 20)
    sec_isins = ctx['sec_isins']
    out = pref[~pref['isin'].isin(ctx['uni_in'])]
    print(f'  preferential rows outside the universe: {len(out)}; ISIN unknown to the security master: {int((~pref["isin"].isin(sec_isins)).sum())}')
    unk = pref[~pref['isin'].isin(sec_isins)]
    show('preferential rows with an ISIN the master does not know', unk, ['symbol', 'isin', 'company', 'stage', 'posted_on'], 20)
    # vs market on the split basis, as screens/ctx.issue_rows does it
    px = ctx['px']
    p = px.drop_duplicates('isin').set_index('isin')
    ls = pref[pref['stage'] == 'listing'].copy()
    when = pd.to_datetime(ls['allotment_date'], errors='coerce').fillna(pd.to_datetime(ls['listing_date'], errors='coerce'))
    split = pd.to_datetime(ls['isin'].map(p['last_split_date']), errors='coerce')
    f = num(ls['isin'].map(p['last_split_factor']))
    nspl = num(ls['isin'].map(p['n_splits'])).fillna(0)
    fac = pd.Series(1.0, index=ls.index).where(~(split.notna() & (when < split)), f)
    ls['close'] = num(ls['isin'].map(p['latest_close']))
    ls['last_date'] = ls['isin'].map(p['last_date'])
    ls['factor'], ls['n_splits'], ls['split_date'] = fac, nspl, split
    ls['vs_market'] = (num(ls['offer_price']) * fac / ls['close'] - 1) * 100
    print('  listing vs_market quantiles:', ls['vs_market'].quantile([.01, .05, .5, .95, .99]).round(1).to_dict(),
          f'no close: {int(ls["close"].isna().sum())}')
    show('listing rows where the offer is >150% above or <-80% below today', ls[(ls['vs_market'] > 150) | (ls['vs_market'] < -80)],
         ['symbol', 'isin', 'allotment_date', 'offer_price', 'factor', 'n_splits', 'split_date', 'close', 'last_date', 'vs_market'], 25)
    acts = ctx['acts']
    sb = acts[acts['purpose'].isin(['split', 'bonus'])]
    ls2 = ls.merge(sb[['symbol', 'purpose', 'ex_date', 'ratio', 'face_value_from', 'face_value_to']], on='symbol', how='inner')
    ls2 = ls2[pd.to_datetime(ls2['ex_date'], errors='coerce') > pd.to_datetime(ls2['allotment_date'], errors='coerce')]
    show('allotments followed by a filed split or bonus', ls2,
         ['symbol', 'isin', 'allotment_date', 'offer_price', 'purpose', 'ex_date', 'ratio', 'face_value_from', 'face_value_to', 'factor',
          'close', 'vs_market'], 25)
    al = table(r2, 'preferential_allottees')
    print('\n  preferential_allottees columns:', list(al.columns), 'rows', len(al))
    if len(al):
        print('  security_type:\n     ' + vc(al['security_type']))
        print('  promoter:\n     ' + vc(al['promoter']))
    for name in ('rights', 'qip'):
        t = table(r2, name)
        print(f'\n  {name}: rows {len(t)} columns {list(t.columns)}')
        if t.empty:
            continue
        print('  stage:\n     ' + vc(t['stage']))
        price = 'issue_price' if name == 'qip' else 'offer_price'
        lt = t[t['stage'] == 'listing']
        r = num(lt['amount_raised']) / (num(lt['shares_allotted']) * num(lt[price]))
        print(f'  {name} listing amount / (shares x price):', r.quantile([.01, .5, .99]).round(3).to_dict())
        show(f'{name} latest', t.sort_values('posted_on', ascending=False),
             ['symbol', 'stage', 'posted_on', price, 'ratio', 'shares_allotted', 'amount_raised', 'amount_total', 'record_date',
              'allotment_date', 'floor_price', 'discount_per_share'], 15)
    # the filings archive: a warrant listing filing as NSE sent it
    keys = sorted(k for k in list_keys(r2, 'archive/nse_events/issues/') if k.endswith('.parquet'))
    fl = pd.concat([read_parquet(r2, k) for k in keys], ignore_index=True) if keys else pd.DataFrame()
    print(f'\n  issue filings archive: {len(fl)} rows; by kind/stage:\n     ' + vc(fl['kind'] + '/' + fl['stage']))
    for kind, stage in (('preferential', 'listing'), ('preferential', 'in_principle')):
        x = fl[(fl['kind'] == kind) & (fl['stage'] == stage)]
        if len(x):
            keysets = x['raw_json'].map(lambda s: tuple(sorted(json.loads(s).keys())) if isinstance(s, str) else ())
            print(f'  {kind}/{stage} raw keys (most common):', keysets.value_counts().index[0])
            print('  e.g.', x['raw_json'].iloc[-1][:1500])
    wl = fl[(fl['kind'] == 'preferential') & fl['raw_json'].astype(str).str.contains('arrant', na=False)]
    print(f'  preferential filings whose NSE row mentions warrants: {len(wl)}')
    for s in wl['raw_json'].head(3):
        print('   ', s[:1200])
    xb = fl[(fl['kind'] == 'preferential') & (fl['stage'] == 'in_principle') & fl['xbrl_json'].notna()]
    for s in xb['xbrl_json'].tail(2):
        print('  in-principle xbrl e.g.', s[:2500])


def buybacks(r2, ctx):
    print('\n################ BUYBACKS')
    bb = table(r2, 'buybacks')
    print('columns:', list(bb.columns))
    print('  route:\n     ' + vc(bb['route']))
    show('all buybacks', bb, ['symbol', 'isin', 'route', 'offer_price', 'shares_sought', 'offer_value', 'shares_tendered',
                              'times_tendered', 'offer_open', 'offer_close', 'record_date', 'ex_date', 'daily_reports',
                              'first_report', 'last_report', 'source'], 80)
    tn = read_parquet(r2, 'clean/current/tenders.parquet')
    if tn is not None:
        print('  tenders offer_type:\n     ' + vc(tn['offer_type']) + '\n  issue_type:\n     ' + vc(tn['issue_type']))
        show('tender buybacks since 2025', tn[(tn['offer_type'] == 'buyback') & (pd.to_datetime(tn['offer_open'], errors='coerce') >= '2025-01-01')],
             ['symbol', 'offer_type_raw', 'issue_type', 'offer_price', 'shares_sought', 'accepted_price', 'offer_open', 'offer_close', 'status'], 40)
    db = read_parquet(r2, 'clean/current/daily_buybacks.parquet')
    if db is not None and len(db):
        show('daily buyback reports (latest)', db.sort_values('report_date', ascending=False), ['symbol', 'report_date', 'text'], 10)


def actions(r2, ctx):
    print('\n################ CORPORATE ACTIONS AND PRICE ADJUSTMENT')
    a = ctx['acts']
    print('actions columns:', list(a.columns))
    print('  purpose:\n     ' + vc(a['purpose']))
    sp = a[a['purpose'] == 'split']
    bo = a[a['purpose'] == 'bonus']
    print(f'  splits {len(sp)}, face values not read: {int(num(sp["face_value_from"]).isna().sum())}; bonuses {len(bo)}, ratio not read: {int(bo["ratio"].isna().sum())}')
    show('splits with no face values read', sp[num(sp['face_value_from']).isna()], ['symbol', 'isin', 'ex_date', 'subject'], 20)
    show('bonuses with no ratio read', bo[bo['ratio'].isna()], ['symbol', 'isin', 'ex_date', 'subject'], 20)
    ba = table(r2, 'bse_actions')
    print('  bse_actions columns:', list(ba.columns), 'rows', len(ba))
    if len(ba):
        print('  bse purpose:\n     ' + vc(ba['purpose']))
        bsp = ba[ba['purpose'] == 'split']
        print(f'  bse splits {len(bsp)}, face values not read: {int(num(bsp.get("face_value_from", pd.Series(dtype=float))).isna().sum())};'
              f' bse bonus ratio not read: {int(ba.loc[ba["purpose"] == "bonus", "ratio"].isna().sum()) if "ratio" in ba else "n/a"}')
        show('bse splits/bonuses with nothing read', ba[((ba['purpose'] == 'split') & num(ba.get('face_value_from')).isna())
                                                        | ((ba['purpose'] == 'bonus') & ba['ratio'].isna())],
             [c for c in ba.columns if c not in ('raw_json',)][:10], 15)
    ev = pd.concat([sp, bo], ignore_index=True)
    ev['ex_date'] = pd.to_datetime(ev['ex_date'], errors='coerce')
    ev = ev[(ev['ex_date'] >= '2025-06-01') & (ev['ex_date'] <= ctx['last_session'])].sort_values('ex_date')
    print(f'  splits and bonuses with ex-date Jun 2025 .. last session: {len(ev)}')
    px = ctx['raw_px']
    f = ctx['factors']
    summ = ctx['px'].set_index('isin')
    rows = []
    for r in ev.to_dict('records'):
        sym, d = r['symbol'], r['ex_date']
        n = px[(px['exchange'] == 'NSE') & (px['symbol'] == sym)]
        before = n[n['date'] < d].sort_values('date').tail(1)
        after = n[n['date'] >= d].sort_values('date').head(1)
        isin_b = before['isin'].iloc[0] if len(before) else None
        isin_a = after['isin'].iloc[0] if len(after) else None
        fa = f[(f['exchange'] == 'NSE') & (f['isin'] == isin_a) & (f['date'] == (after['date'].iloc[0] if len(after) else None))]
        exp = adjust._ratio_factor(r['ratio']) if r['purpose'] == 'bonus' else (num(pd.Series([r['face_value_to']])).iloc[0] / num(pd.Series([r['face_value_from']])).iloc[0])
        s_new = summ.loc[isin_a] if isin_a in summ.index else None
        rows.append({'symbol': sym, 'purpose': r['purpose'], 'ex': d.date(), 'ratio': r['ratio'] or f"{r['face_value_from']}->{r['face_value_to']}",
                     'expected': round(exp, 4) if pd.notna(exp) else None, 'isin_filed': r['isin'], 'isin_before': isin_b, 'isin_after': isin_a,
                     'close_before': before['close'].iloc[0] if len(before) else None,
                     'prev_close_after': after['prev_close'].iloc[0] if len(after) else None,
                     'factor': round(fa['factor'].iloc[0], 4) if len(fa) and pd.notna(fa['factor'].iloc[0]) else None,
                     'kind': fa['kind'].iloc[0] if len(fa) else None, 'basis': fa['kind_basis'].iloc[0] if len(fa) else None,
                     'summ_split': s_new['last_split_date'] if s_new is not None else None,
                     'summ_n': s_new['n_splits'] if s_new is not None else None})
    res = pd.DataFrame(rows)
    show('each split / bonus: NSE prints around the ex-date and what the adjustment did', res, None, 200)
    if len(res):
        print('  kind applied:\n     ' + vc(res['kind']) + '\n  ISIN changed across the ex-date: ' + str(int((res['isin_before'] != res['isin_after']).sum())))
        changed = res[res['isin_before'].notna() & (res['isin_before'] != res['isin_after'])]
        # what the site has for the old and new ISIN
        it = ctx['trades']
        for r in changed.head(12).to_dict('records'):
            o, nw = r['isin_before'], r['isin_after']
            so = summ.loc[o] if o in summ.index else None
            sn = summ.loc[nw] if nw in summ.index else None
            to = it[it['isin'] == o] if len(it) else it
            tn = it[(it['isin'] == nw) & (pd.to_datetime(it['trade_date_to'], errors='coerce') < pd.Timestamp(r['ex']))] if len(it) else it
            h = ctx['hist']
            print(f"  {r['symbol']} {r['purpose']} {r['ex']}: old {o} summary last_date {so['last_date'] if so is not None else '-'} close {so['latest_close'] if so is not None else '-'}"
                  f" | new {nw} first history {h[h['isin'] == nw]['date'].min() if len(h) else '-'} split_date {sn['last_split_date'] if sn is not None else '-'}"
                  f" | insider rows under old ISIN {len(to)}, under new ISIN dated before ex {len(tn)}"
                  + (f" (paid {num(tn['price']).median():.2f} vs close {sn['latest_close']:.2f})" if len(tn) and sn is not None else ''))
    # BSE-only splits
    print('  factors by kind and basis (all):', adjust.coverage(f))
    mism = f[f['kind_basis'].isin(['action_mismatch', 'action_not_split_bonus'])]
    show('resets on a filed action not applied (mismatch / not split-bonus)', mism.sort_values('date', ascending=False),
         ['exchange', 'isin', 'symbol', 'date', 'close', 'prev_close', 'last_close', 'factor', 'kind', 'kind_basis'], 30)
    lg = f[(f['kind'] == 'other_large') & (f['kind_basis'] == '') & (f['date'] >= '2025-10-01')]
    show('other large resets with no action filed since Oct 2025 (not applied)', lg.sort_values('date', ascending=False),
         ['exchange', 'isin', 'symbol', 'date', 'close', 'prev_close', 'last_close', 'factor'], 30)


def results(r2, ctx):
    print('\n################ RESULTS')
    r = table(r2, 'results')
    print('columns:', list(r.columns), 'rows', len(r))
    for c in ('consolidated', 'audited', 'period_type', 'rounding', 'kind', 'revision', 'xbrl_status', 'reporting_quarter'):
        if c in r:
            print(f'  {c}:\n     ' + vc(r[c].astype(str).str.split(':').str[0], 12))
    key = ['isin', 'period_end', 'consolidated']
    dup = r[r.duplicated(key, keep=False) & r['isin'].notna()]
    print(f'  rows sharing isin+period_end+basis: {len(dup)}; revisions among them: {int(dup["revision"].astype(str).str.contains("Revis", na=False).sum())}')
    show('duplicates (sample)', dup.sort_values(key), ['symbol', 'period_end', 'consolidated', 'revision', 'broadcast_at', 'quarter_revenue', 'quarter_profit'], 16)
    rv = num(r['quarter_revenue'])
    print('  quarter_revenue quantiles (Cr):', (rv.quantile([.01, .1, .5, .9, .99]) / 1e7).round(2).to_dict())
    m = r.merge(ctx['uni'][['isin', 'market_cap']], on='isin', how='left')
    m['rev_to_mcap'] = num(m['quarter_revenue']) / num(m['market_cap'])
    low = m[(m['rev_to_mcap'] < 1e-4) & num(m['market_cap']).gt(500e7)]
    show('revenue under 0.01% of market cap in companies over Rs 500 Cr (unit?)', low.sort_values('rev_to_mcap'),
         ['symbol', 'period_end', 'consolidated', 'kind', 'rounding', 'quarter_revenue', 'quarter_profit', 'market_cap', 'rev_to_mcap'], 20)
    hi = m[m['rev_to_mcap'] > 5]
    show('revenue over 5x market cap (unit?)', hi.sort_values('rev_to_mcap', ascending=False),
         ['symbol', 'period_end', 'consolidated', 'kind', 'rounding', 'quarter_revenue', 'market_cap', 'rev_to_mcap'], 20)
    q_vs_y = num(r['quarter_revenue']) / num(r['ytd_revenue'])
    print('  quarter / ytd revenue:', q_vs_y.quantile([.01, .5, .99]).round(3).to_dict(),
          f'quarter > ytd: {int((q_vs_y > 1.001).sum())}')
    pt = r.get('period_type')
    if 'ytd_start' in r:
        months = (pd.to_datetime(r['period_end'], errors='coerce').dt.to_period('M').astype('int64')
                  - pd.to_datetime(r['ytd_start'], errors='coerce').dt.to_period('M').astype('int64') + 1)
        print('  months in ytd:\n     ' + vc(months.where(r['ytd_start'].notna())))
    for sym in ctx['symbols'] + ['HCLTECH', 'RELIANCE', 'TCS', 'ITC']:
        show(f'{sym} results', r[r['symbol'].astype(str).str.upper() == sym].sort_values('broadcast_at', ascending=False),
             ['symbol', 'isin', 'period_end', 'consolidated', 'audited', 'revision', 'rounding', 'period_type', 'quarter_revenue', 'quarter_profit',
              'ytd_revenue', 'ytd_start', 'xbrl_url'], 6)


def universe(r2, ctx):
    print('\n################ MARKET CAP AND UNIVERSE')
    u, sec = ctx['uni'], ctx['sec']
    print('universe:', len(u), ' why:\n     ' + vc(u['why']))
    print('securities columns:', list(sec.columns))
    s = sec.copy()
    s['basis'] = np.where(s['nse_market_cap'].notna(), 'nse', np.where(s['bse_market_cap'].notna(), 'bse', 'none')) if 'nse_market_cap' in s else 'n/a'
    print('  market cap basis:\n     ' + vc(s['basis']))
    it = ctx['trades']
    if len(it):
        seen = pd.to_datetime(it['broadcast_date'], errors='coerce')
        recent = it[seen >= seen.max() - pd.Timedelta(days=90)]
        out = recent[~recent['isin'].isin(ctx['uni_in'])]
        why = out['isin'].map(u.set_index('isin')['why']).fillna('ISIN not in universe table')
        print(f'  insider filings, last 90 days: {len(recent)}; cut by the universe: {len(out)}; by why:\n     ' + vc(why))
        nm = out[why.ne('under Rs 100 Cr')].drop_duplicates('isin')
        show('companies with filings cut for no market cap / unknown ISIN', nm, ['isin', 'company', 'nse_symbol', 'bse_code', 'exchange'], 25)
    mc = ctx['mcap_daily']
    if len(mc):
        last = mc['date'].max()
        m = mc[mc['date'] == last].drop_duplicates('symbol').set_index('symbol')['market_cap']
        s2 = s.dropna(subset=['nse_symbol'])
        s2 = s2.assign(daily=s2['nse_symbol'].map(m))
        d = (num(s2['market_cap']) / s2['daily'] - 1).abs()
        print(f'  securities.market_cap vs NSE daily file of {last.date()}: compared {int(d.notna().sum())}, off >5%: {int((d > 0.05).sum())}')
        show('largest gaps', s2.assign(d=d).sort_values('d', ascending=False), ['isin', 'nse_symbol', 'market_cap', 'daily', 'd'], 10)
        edge = u[num(u['market_cap']).between(80e7, 125e7)]
        print(f'  companies between Rs 80 and 125 Cr: {len(edge)}')
    sh = ctx['sh']
    if len(mc) and len(sh):
        l = sh.sort_values('quarter_end').drop_duplicates('symbol', keep='last')
        size = mc[mc['date'] == mc['date'].max()].drop_duplicates('symbol').set_index('symbol')
        if 'issue_size' in size:
            l = l.assign(issue=l['symbol'].map(size['issue_size']))
            d = (num(l['total_shares']) / l['issue'] - 1).abs()
            print(f'  shareholding total shares vs NSE issue size today: off >2%: {int((d > 0.02).sum())} of {int(d.notna().sum())}')
            show('largest', l.assign(d=d).sort_values('d', ascending=False), ['symbol', 'quarter_end', 'total_shares', 'issue', 'd'], 12)


def meetings(r2, ctx):
    print('\n################ BOARD MEETINGS AND THE TRADING WINDOW')
    m = table(r2, 'meetings')
    print('meetings columns:', list(m.columns), 'rows', len(m))
    m['meeting_date'] = pd.to_datetime(m['meeting_date'], errors='coerce')
    print('  meetings by month:\n     ' + vc(m['meeting_date'].dt.to_period('M'), 20))
    print('  results flag:', int(m['results'].astype('boolean').fillna(False).sum()))
    it = ctx['trades']
    if len(it) and 'results_date' in it:
        mk = it[it['is_market'].astype('boolean').fillna(False) & it['is_primary'].astype('boolean').fillna(False)]
        print(f'  market trades with a results date: {int(mk["results_date"].notna().sum())} of {len(mk)}; window-open buys: {int(mk["window_open_buy"].astype("boolean").fillna(False).sum())}')
        td = pd.to_datetime(mk['trade_date_to'], errors='coerce')
        rd = pd.to_datetime(mk['results_date'], errors='coerce')
        q_end = td.dt.to_period('Q').dt.start_time - pd.Timedelta(days=1)
        inside = mk[rd.notna() & (td > q_end) & (rd < q_end)]
        print(f'  market trades after a quarter end whose results date is from the quarter before (window may be closed): {len(inside)}')


def main() -> int:
    r2 = r2_client()
    sections = [x.strip() for x in os.environ.get('SECTIONS', 'shareholding,issues,buybacks,actions,results,universe,meetings').split(',') if x.strip()]
    symbols = [x.strip().upper() for x in os.environ.get('SYMBOLS', '').split(',') if x.strip()]
    ctx = {'symbols': symbols}
    ctx['uni'] = table(r2, 'universe')
    ctx['uni_in'] = set(ctx['uni'].loc[ctx['uni']['in_universe'].astype(bool), 'isin'])
    ctx['sec'] = table(r2, 'securities')
    ctx['sec_isins'] = set(ctx['sec']['isin'].dropna())
    ctx['sh'] = table(r2, 'shareholding')
    ctx['bsh'] = table(r2, 'bse_shareholding')
    ctx['acts'] = pd.concat([table(r2, 'actions')], ignore_index=True)
    body = r2.get_object(Bucket=BUCKET, Key='artifacts/prices_summary_slim.parquet')['Body'].read()
    ctx['px'] = pd.read_parquet(io.BytesIO(body))
    ctx['hist'] = pd.read_parquet(io.BytesIO(r2.get_object(Bucket=BUCKET, Key='artifacts/price_history.parquet')['Body'].read()))
    ctx['trades'] = table(r2, 'insider_trades')
    if 'actions' in sections:
        keys = [k for k in list_keys(r2, 'prices/daily/') if k.endswith('.parquet') and k.split('/')[-1][:7] >= '2025-04']
        cols = ['date', 'exchange', 'isin', 'symbol', 'series', 'close', 'prev_close', 'value']
        px = pd.concat([read_parquet(r2, k)[cols] for k in keys], ignore_index=True)
        px['date'] = pd.to_datetime(px['date'])
        ctx['raw_px'] = px
        ctx['last_session'] = px['date'].max()
        acts = pd.concat([table(r2, 'actions'), table(r2, 'bse_actions')], ignore_index=True)
        ctx['factors'] = adjust.inherit_nse(adjust.implied_factors(px, actions=acts))
    ctx['mcap_daily'] = pd.DataFrame()
    if 'universe' in sections:
        keys = sorted(k for k in list_keys(r2, 'marketcap/daily/nse/') if k.endswith('.parquet'))[-1:]
        if keys:
            mc = read_parquet(r2, keys[-1])
            mc['date'] = pd.to_datetime(mc['date'])
            ctx['mcap_daily'] = mc
    for name in sections:
        try:
            globals()[name](r2, ctx)
        except Exception as e:  # noqa: BLE001 -- one section failing must not hide the others
            import traceback
            print(f'!! section {name} failed: {type(e).__name__}: {e}')
            traceback.print_exc()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
