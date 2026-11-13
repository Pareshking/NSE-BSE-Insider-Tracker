"""The clean rows behind a few companies (read-only), for audits: SYMBOLS=comma list of NSE symbols.

For each symbol: its securities and universe rows, every shareholding quarter (holding, pledge, XBRL status,
ISIN), and its pledge filings in insider_trades of the last 120 days with the fields that decide netting.
Prints only; writes nothing to R2, calls no exchange.
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

pd.set_option('display.width', 250)
pd.set_option('display.max_columns', 40)
pd.set_option('display.max_colwidth', 28)


def show(title: str, df: pd.DataFrame, cols: list[str]) -> None:
    print(f'--- {title}: {len(df)} rows')
    if len(df):
        print(df[[c for c in cols if c in df]].to_string(index=False))


def mcap_gap(r2) -> int:
    """For the rows with no NSE symbol still on `latest` or `none`: how many have shares in issue on file for a quarter on or before
    the trade, how many have a BSE close within 10 days before the trade, and what the BSE price layer and shareholding hold."""
    import pandas as pd

    from clean_writer import get
    from insiders_clean import day_range, market_cap
    shares = market_cap.shares_frame(read_parquet(r2, 'clean/current/bse_shareholding.parquet'),
                                     read_parquet(r2, 'clean/current/shareholding.parquet'))
    from datetime import date
    closes, info = market_cap.load_bse_closes(lambda k: get(r2, k), day_range.months_between(date(2025, 10, 8), date.today()))
    print('BSE price layer:', {k: v for k, v in info.items() if k != 'months_unreadable'}, 'unreadable:', list(info['months_unreadable']))
    print(f'shares in issue: {len(shares)} rows, {shares["isin"].nunique()} ISINs; BSE closes: {len(closes)} rows, {closes["isin"].nunique()} ISINs, '
          f'{closes["date"].min().date()} to {closes["date"].max().date()}')
    for name, date_col in (('insider_trades', 'trade_date_to'), ('deals', 'date')):
        t = read_parquet(r2, f'clean/current/{name}.parquet')
        x = t[t['nse_symbol'].isna() & t['market_cap_basis'].isin(['latest', 'none'])].copy()
        x['_day'] = pd.to_datetime(x[date_col], errors='coerce').dt.normalize()
        has_isin = x['isin'].notna()
        sh_ok = x.merge(shares.assign(_q=shares['quarter_end']), on='isin', how='left').assign(_ok=lambda d: d['_q'].notna() & (d['_q'] <= d['_day']))
        sh_any = set(shares['isin'])
        cl_any = set(closes['isin'])
        have_sh = sh_ok.groupby(level=0).size().index if False else None
        got_sh = set(sh_ok.loc[sh_ok['_ok'], 'isin'])
        print(f'--- {name}: {len(x)} rows still on latest/none; no ISIN: {int((~has_isin).sum())}; ISIN has any shares: '
              f'{int(x["isin"].isin(sh_any).sum())}; any shares dated on or before the trade: {int(x["isin"].isin(got_sh).sum())}; ISIN has any BSE close: '
              f'{int(x["isin"].isin(cl_any).sum())}; distinct ISINs: {x["isin"].nunique()}, with shares: {len(set(x["isin"]) & sh_any)}, '
              f'with closes: {len(set(x["isin"]) & cl_any)}')
        print('    trade months of those rows:', x['_day'].dt.to_period('M').astype(str).value_counts().sort_index().to_dict())
    return 0


def mcap_basis(r2) -> int:
    """market_cap_basis counts of the clean insider and deal tables, with a few BSE-only rows on `shares_x_close`. Read only."""
    for name, date_col in (('insider_trades', 'trade_date_to'), ('deals', 'date')):
        t = read_parquet(r2, f'clean/current/{name}.parquet')
        print(f'--- {name}: {len(t)} rows; market_cap_basis:', t['market_cap_basis'].value_counts(dropna=False).to_dict())
        x = t[t['market_cap_basis'].eq('shares_x_close')]
        print(f'    BSE-only rows on shares_x_close: {len(x)}; with no NSE symbol: {int(x["nse_symbol"].isna().sum())}')
        left = t[t['nse_symbol'].isna()]
        print(f'    rows with no NSE symbol: {len(left)}; of them by basis:', left['market_cap_basis'].value_counts(dropna=False).to_dict())
        cols = [c for c in ('company', date_col, 'value', 'market_cap', 'market_cap_at_trade', 'market_cap_date', 'pct_of_mcap') if c in x]
        if len(x):
            print(x.sort_values('value', ascending=False)[cols].head(8).to_string(index=False))
    return 0


def fund_names(r2) -> int:
    """Institutional client names of the primary, non-market-maker deals, largest total value first, with the manager
    line (if any) each already has: where the next `fund_managers.csv` lines are worth writing. Names only; no write."""
    from insiders_clean import fund_managers
    deals = read_parquet(r2, 'clean/current/deals.parquet')
    d = deals[deals['is_primary'].astype(bool) & ~deals['client_is_market_maker'].astype(bool)]
    d = d[d['client_type'].isin(['mutual_fund', 'fpi', 'insurer', 'pension', 'bank', 'pms_aif', 'fund_other'])]
    g = d.groupby('client_name').agg(value=('value', 'sum'), legs=('value', 'size'), type=('client_type', 'first'))
    g = g.sort_values('value', ascending=False).head(400)
    g['manager'] = [fund_managers.manager_of(n)[0] or '' for n in g.index]
    print(f'--- {len(g)} largest institutional names (Rs Cr total, legs, type, manager line)')
    for n, r in g.iterrows():
        print(f'{r["value"] / 1e7:10.1f} | {int(r["legs"]):4d} | {r["type"]:11s} | {r["manager"]:14s} | {n}')
    return 0


def results_quarters(r2) -> int:
    """Rows of clean/current/results per quarter end, consolidated or standalone, with XBRL status ok; and the companies
    whose Sep 2026 quarter has a Sep 2025 quarter in the table (what the Results page's year-ago column needs)."""
    r = read_parquet(r2, 'clean/current/results.parquet')
    if r is None or r.empty:
        print('clean/current/results.parquet: empty or missing')
        return 0
    r = r.assign(_end=pd.to_datetime(r['period_end'], errors='coerce'),
                 _basis=r['consolidated'].astype(str).str.strip().str.lower().str.startswith('consolidated').map({True: 'cons', False: 'stand'}),
                 _ok=r['xbrl_status'].fillna('ok').eq('ok') if 'xbrl_status' in r else True)
    print(f'results rows: {len(r)}; xbrl ok: {int(r["_ok"].sum())}; broadcast from {r["broadcast_at"].min()} to {r["broadcast_at"].max()}')
    q = r[r['_ok']].groupby([r['_end'].dt.to_period('Q'), '_basis']).size().unstack(fill_value=0)
    print(q.tail(12).to_string())
    now = set(r.loc[r['_ok'] & (r['_end'] == '2026-09-30'), 'isin'].dropna())
    ago = set(r.loc[r['_ok'] & (r['_end'] == '2025-09-30'), 'isin'].dropna())
    print(f'companies with a Sep 2026 quarter: {len(now)}; of them with Sep 2025 too: {len(now & ago)}')
    return 0


def results_xbrl(r2, syms: list[str]) -> int:
    """RESULTS_XBRL:SYM,...: each Sep 2026 results filing of these companies from the archive, its plain duration
    contexts (start, end, days) with RevenueFromOperations and ProfitLossForPeriod as filed, TypeOfReportingPeriod,
    and the quarter the clean layer took (13 Nov 2026: Godfrey Phillips and Tega at +150% / +950%)."""
    import json
    from insiders_clean import results
    a = read_parquet(r2, 'archive/nse_events/results/year=2026.parquet')
    if a is None or a.empty:
        print('archive results 2026: empty or missing')
        return 0
    for sym in syms:
        g = a[(a['symbol'].astype(str).str.upper() == sym) & a['period_end'].astype(str).str.startswith('2026-09')]
        print(f'\n===== {sym}: {len(g)} filings ending Sep 2026')
        for r in g.to_dict('records'):
            print(f"-- {r.get('consolidated')} {r.get('revision')} broadcast {r.get('broadcast_at')} status {r.get('xbrl_status')}")
            try:
                p = json.loads(r['xbrl_json'])
            except (TypeError, ValueError):
                print('   no xbrl_json')
                continue
            q, y = results.periods(p)
            for k, c in p['contexts'].items():
                if c['instant'] or c['dimension'] or not c['start']:
                    continue
                f = p['facts'].get(k, {})
                if 'RevenueFromOperations' not in f and 'DateOfEndOfReportingPeriod' not in f:
                    continue
                days = results._days(c)
                print(f"   {k:12} {c['start']} - {c['end']} ({days} d) revenue {f.get('RevenueFromOperations')} profit "
                      f"{f.get('ProfitLossForPeriod')} type {f.get('TypeOfReportingPeriod')}{' <- quarter' if k == q else ''}{' <- ytd' if k == y else ''}")
    return 0


def deal_days(r2, start: str = '2026-09-28', end: str = '2026-10-16') -> int:
    """TODO item 18: were the 07 and 08 Oct 2026 NSE block deals (blocked that night) written later? Counts per day,
    feed and exchange in the clean deals table, primary rows, market makers included and apart."""
    d = read_parquet(r2, 'clean/current/deals.parquet')
    if d is None or d.empty:
        print('clean/current/deals.parquet: empty or missing')
        return 0
    d = d.assign(_day=pd.to_datetime(d['date'], errors='coerce').dt.normalize())
    w = d[(d['_day'] >= start) & (d['_day'] <= end)]
    print(f'deals {start} to {end}: {len(w)} rows of {len(d)}; columns feeds/exchange/is_primary present:',
          {c: c in d for c in ('feeds', 'exchange', 'is_primary', 'client_is_market_maker')})
    if w.empty:
        return 0
    g = w.assign(primary=w['is_primary'].astype('boolean').fillna(False)).groupby(
        ['_day', 'exchange', 'feeds', 'primary'], dropna=False).size().unstack(['exchange', 'feeds', 'primary'], fill_value=0)
    print(g.to_string())
    return 0



def data_pack(r2) -> int:
    """Every table in clean/current/ and artifacts/: rows, each column's type, fill, distinct count, range or top
    values, and the newest rows as samples (owner 12 Nov: the design brief is written from the data, not the pages)."""
    from clean_writer import list_keys
    keys = sorted(k for pre in ('clean/current/', 'artifacts/') for k in list_keys(r2, pre) if k.endswith('.parquet'))
    print(f'DATA PACK: {len(keys)} tables')
    for key in keys:
        try:
            d = read_parquet(r2, key)
        except Exception as exc:   # one unreadable table must not hide the rest
            print(f'\n===== {key}: unreadable ({type(exc).__name__})')
            continue
        if d is None:
            continue
        print(f'\n===== {key}: {len(d)} rows, {d.shape[1]} columns')
        for c in d.columns:
            s = d[c]
            fill = s.notna().mean() * 100 if len(s) else 0
            try:
                nun = s.nunique(dropna=True)
            except TypeError:   # lists or dicts in the cells
                print(f'  {c} [{s.dtype}] fill {fill:.0f}% (nested)')
                continue
            line = f'  {c} [{s.dtype}] fill {fill:.0f}%, {nun} distinct'
            if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s) and s.notna().any():
                q = s.dropna().quantile([0, .1, .5, .9, 1]).tolist()
                line += ', min/p10/p50/p90/max ' + '/'.join(f'{x:.4g}' for x in q)
            elif pd.api.types.is_datetime64_any_dtype(s) and s.notna().any():
                line += f', {s.min()} .. {s.max()}'
            elif nun and nun <= 25:
                line += ', ' + '; '.join(f'{str(k)[:40]}={v}' for k, v in s.value_counts().head(12).items())
            elif s.notna().any():
                line += f', e.g. {str(s.dropna().iloc[0])[:70]!r}'
            print(line)
        dates = [c for c in d.columns if pd.api.types.is_datetime64_any_dtype(d[c])]
        dates.sort(key=lambda c: -d[c].notna().sum())
        sample = d.sort_values(dates[0], ascending=False) if dates and d[dates[0]].notna().any() else d
        cols = [c for c in d.columns if not c.endswith(('_json', '_raw')) and c not in ('xbrl_json',)][:22]
        print('  -- newest rows:')
        print(sample[cols].head(6).astype(str).apply(lambda col: col.str.slice(0, 32)).to_string(index=False))
    return 0


def _dirs(r2, prefix):
    """Sub-folders of a prefix, without listing every object under it."""
    from clean_writer import BUCKET
    out, token = [], None
    while True:
        kw = {'Bucket': BUCKET, 'Prefix': prefix, 'Delimiter': '/'}
        if token:
            kw['ContinuationToken'] = token
        r = r2.list_objects_v2(**kw)
        out += [c['Prefix'] for c in r.get('CommonPrefixes', [])]
        if not r.get('IsTruncated'):
            return out
        token = r['NextContinuationToken']


def _body_excerpt(body: bytes, ext: str) -> str:
    import json
    text = body.decode('utf-8', errors='replace')
    if ext == 'json':
        try:
            j = json.loads(text)
        except ValueError:
            return text[:2500]
        rows = j if isinstance(j, list) else next((v for v in j.values() if isinstance(v, list)), None) if isinstance(j, dict) else None
        if rows is not None:
            head = {k: v for k, v in j.items() if not isinstance(v, list)} if isinstance(j, dict) else {}
            return (f'top level: {list(j)[:15] if isinstance(j, dict) else "list"}; {len(rows)} rows; other fields {json.dumps(head)[:300]}\n'
                    + '\n'.join(json.dumps(r, ensure_ascii=False)[:1200] for r in rows[:3]))
        return json.dumps(j, ensure_ascii=False)[:2500]
    if ext in ('csv', 'txt'):
        return '\n'.join(text.splitlines()[:8])[:2500]
    if ext in ('xml', 'html'):
        return text[:3000]
    return f'(binary {ext}, {len(body)} bytes)'


def raw_pack(r2) -> int:
    """What NSE and BSE send us, as kept in raw_v2/ (owner 12 Nov: the design brief is written from the raw exchange
    data, not the cleaned tables): per dataset, how many days were fetched, the latest fetch records (URL, params) and
    an excerpt of the bytes. Read-only."""
    import json
    from clean_writer import get
    print('RAW PACK: raw_v2/')
    for src in _dirs(r2, 'raw_v2/'):
        for ds in _dirs(r2, src):
            days = sorted(_dirs(r2, ds + 'fetches/'))
            if not days:
                print(f'\n===== {ds}: no fetches/ folder; sub-folders: {[d[len(ds):] for d in _dirs(r2, ds)][:12]}')
                continue
            print(f'\n===== {ds}: {len(days)} fetch days, {days[0][len(ds) + 8:-1]} .. {days[-1][len(ds) + 8:-1]}')
            r = r2.list_objects_v2(Bucket=__import__('clean_writer').BUCKET, Prefix=days[-1], MaxKeys=1000)
            recs = sorted(o['Key'] for o in r.get('Contents', []))
            print(f'  fetches on the last day: {len(recs)}{"+" if r.get("IsTruncated") else ""}')
            shown = set()
            for key in recs[::-1]:
                rec = json.loads(get(r2, key) or b'{}')
                url = str(rec.get('url', ''))
                base = url.split('?')[0]
                if base in shown:
                    continue
                shown.add(base)
                print(f'  -- fetch: {json.dumps({k: rec.get(k) for k in ("url", "params", "http_status", "content_type", "bytes", "covers", "fetched_at_utc")}, default=str)[:600]}')
                bkey = rec.get('blob_key') or ''
                ext = bkey.rsplit('.', 1)[-1] if '.' in bkey else 'bin'
                blob = get(r2, bkey) if bkey else None
                print('  ' + (_body_excerpt(blob, ext).replace('\n', '\n  ') if blob is not None else f'(blob not found; record keys {list(rec)})'))
                if len(shown) >= 3:
                    break
    return 0

def main() -> int:
    r2 = r2_client()
    syms = [x.strip().upper() for x in os.environ.get('SYMBOLS', '').split(',') if x.strip()]
    if syms == ['MCAP_GAP']:     # why a BSE-only row is still on the latest market cap: no shares, or no BSE close
        return mcap_gap(r2)
    if syms == ['MCAP_BASIS']:   # how each row's market cap was dated, and BSE-only examples of the new basis
        return mcap_basis(r2)
    if syms == ['RAW_PACK']:      # what the exchanges send, from raw_v2/, for the design brief (12 Nov)
        return raw_pack(r2)
    if syms == ['DATA_PACK']:     # every clean table profiled, for the design brief (12 Nov)
        return data_pack(r2)
    if syms == ['RESULTS_QUARTERS']:   # results rows per quarter end and basis: how far back the backfill reached
        return results_quarters(r2)
    if syms and syms[0].startswith('RESULTS_XBRL:'):   # a company's Sep 2026 results filings as filed (13 Nov)
        return results_xbrl(r2, [syms[0].split(':', 1)[1]] + syms[1:])
    if syms == ['DEAL_DAYS']:    # TODO 18: bulk and block deals per day and exchange around 07-08 Oct 2026
        return deal_days(r2)
    if syms == ['FUND_NAMES']:   # the fund names in the deals with no manager line yet (insiders_clean/fund_managers.csv)
        return fund_names(r2)
    sec = read_parquet(r2, 'clean/current/securities.parquet')
    uni = read_parquet(r2, 'clean/current/universe.parquet')
    sh = read_parquet(r2, 'clean/current/shareholding.parquet')
    tr = read_parquet(r2, 'clean/current/insider_trades.parquet')
    print('shareholding columns:', [c for c in sh.columns if not c.endswith(('_shares', '_pct')) or c.startswith('promoter')])
    print('insider_trades columns:', list(tr.columns))
    for sym in syms:
        print(f'\n===== {sym}')
        s = sec[sec['nse_symbol'].astype(str).str.upper() == sym]
        show('securities', s, ['isin', 'nse_symbol', 'bse_code', 'display_name', 'market_cap'])
        isins = set(s['isin'].dropna())
        if uni is not None and 'isin' in uni:
            show('universe', uni[uni['isin'].isin(isins)], list(uni.columns)[:8])
        q = sh[(sh['symbol'].astype(str).str.upper() == sym) | sh['isin'].isin(isins)]
        show('shareholding', q.sort_values('quarter_end'),
             ['isin', 'symbol', 'quarter_end', 'submission_date', 'promoter_holding_pct', 'promoter_shares', 'total_shares',
              'promoter_pledged_shares', 'promoter_pledge_pct', 'xbrl_status', 'shareholding_stale', 'categories_status'])
        t = tr[tr['isin'].isin(isins) | (tr['nse_symbol'].astype(str).str.upper() == sym)] if 'nse_symbol' in tr else tr[tr['isin'].isin(isins)]
        t = t[t['kind'].astype(str).str.startswith('pledge')] if 'kind' in t else t.iloc[0:0]
        show('pledge filings', t.sort_values('broadcast_date') if 'broadcast_date' in t else t,
             ['broadcast_date', 'exchange', 'is_primary', 'primary_id', 'person_id', 'kind', 'side', 'quantity', 'value',
              'holding_before', 'holding_after', 'trade_date_from', 'trade_date_to', 'app_id', 'source_id', 'mode_raw',
              'transaction_type_raw', 'listed_on'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
