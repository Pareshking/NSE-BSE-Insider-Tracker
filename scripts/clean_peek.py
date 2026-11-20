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


def trades_and_deals(r2, sym: str) -> int:
    """TRADES:SYM: a company's insider market rows and bulk/block deals, Oct-Nov 2026, as cleaned (14 Nov 2026: why a
    placement or a cross is or is not labelled)."""
    t = read_parquet(r2, 'clean/current/insider_trades.parquet')
    d = read_parquet(r2, 'clean/current/deals.parquet')
    pd.set_option('display.width', 250)
    pd.set_option('display.max_columns', 30)
    if t is not None:
        # an NSE symbol or a BSE code (19 Nov 2026: BSE-only companies such as Millworks 544826)
        x = t[((t['nse_symbol'].astype(str).str.upper() == sym) | (t['bse_code'].astype(str) == sym))
              & (t['trade_date_to'].astype(str) >= '2026-10-01')]
        cols = [c for c in ('person_name', 'person_role', 'side', 'kind', 'is_market', 'is_primary', 'exchange', 'quantity', 'value',
                            'trade_date_from', 'trade_date_to', 'holding_before', 'holding_after', 'app_id', 'source_id',
                            'broadcast_ts', 'cross_with', 'placement_buyers', 'group_transfer_by_deal') if c in x]
        print(f'insider rows {sym}: {len(x)}')
        print(x[cols].to_string())
    if d is not None:
        y = d[((d['nse_symbol'].astype(str).str.upper() == sym) | (d['bse_code'].astype(str) == sym))
              & (d['date'].astype(str) >= '2026-10-01')]
        cols = [c for c in ('date', 'exchange', 'client_name', 'side', 'quantity', 'price', 'client_is_promoter', 'matched_pair',
                            'client_is_market_maker', 'two_way_bought', 'two_way_sold', 'counterparties') if c in y]
        print(f'deals {sym}: {len(y)}')
        print(y[cols].to_string())
    return 0


def sizes(r2) -> int:
    """SIZES: objects and bytes per top-level folder, and per second level for the three largest (read-only, 15 Nov
    2026: the owner asked why the bucket holds 11.89 GB)."""
    import os as _os
    bucket = _os.environ.get('R2_BUCKET_NAME')
    top, sub = {}, {}
    token = None
    while True:
        kw = {'Bucket': bucket}
        if token:
            kw['ContinuationToken'] = token
        resp = r2.list_objects_v2(**kw)
        for o in resp.get('Contents', []):
            parts = o['Key'].split('/')
            t = parts[0]
            n, b = top.get(t, (0, 0))
            top[t] = (n + 1, b + o['Size'])
            k2 = '/'.join(parts[:3 if t == 'raw_v2' else 2]) if len(parts) > 2 else t
            n, b = sub.get(k2, (0, 0))
            sub[k2] = (n + 1, b + o['Size'])
        if not resp.get('IsTruncated'):
            break
        token = resp['NextContinuationToken']
    total = sum(b for _, b in top.values())
    print(f'TOTAL {sum(n for n, _ in top.values()):,} objects, {total / 1e9:.2f} GB')
    for t, (n, b) in sorted(top.items(), key=lambda kv: -kv[1][1]):
        print(f'{t + "/":<14} {n:>9,} objects {b / 1e9:>8.3f} GB  {100 * b / total:5.1f}%')
    big = [t for t, _ in sorted(top.items(), key=lambda kv: -kv[1][1])[:4]]
    for t in big:
        print(f'-- inside {t}/')
        for k, (n, b) in sorted(((k, v) for k, v in sub.items() if k.startswith(t + '/')), key=lambda kv: -kv[1][1])[:25]:
            print(f'   {k + "/":<40} {n:>9,} objects {b / 1e9:>8.3f} GB')
    return 0


def compress_age(r2) -> int:
    """COMPRESS: per raw_v2 dataset and per other top folder, how much a sample gzips to, and bytes by age (read-only,
    15 Nov 2026: the owner wants the bucket at 1 GB or less)."""
    import gzip as _gz
    import os as _os
    import random
    from datetime import datetime, timezone
    bucket = _os.environ.get('R2_BUCKET_NAME')
    now = datetime.now(timezone.utc)
    groups = {}
    token = None
    while True:
        kw = {'Bucket': bucket}
        if token:
            kw['ContinuationToken'] = token
        resp = r2.list_objects_v2(**kw)
        for o in resp.get('Contents', []):
            parts = o['Key'].split('/')
            g = '/'.join(parts[:3]) if parts[0] == 'raw_v2' and len(parts) > 3 else '/'.join(parts[:2]) if len(parts) > 2 else parts[0]
            groups.setdefault(g, []).append((o['Key'], o['Size'], (now - o['LastModified']).days))
        if not resp.get('IsTruncated'):
            break
        token = resp['NextContinuationToken']
    rows = []
    for g, objs in groups.items():
        total = sum(s for _, s, _ in objs)
        if total < 5e6:
            continue
        old90 = sum(s for _, s, a in objs if a > 90)
        old180 = sum(s for _, s, a in objs if a > 180)
        sample = random.Random(0).sample(objs, min(25, len(objs)))
        raw_b = gz_b = 0
        for k, sz, _ in sample:
            if sz > 20e6:
                continue
            body = r2.get_object(Bucket=bucket, Key=k)['Body'].read()
            raw_b += len(body)
            gz_b += len(_gz.compress(body, 9))
        ratio = gz_b / raw_b if raw_b else 1.0
        rows.append((g, len(objs), total, ratio, old90, old180, max(a for _, _, a in objs)))
    rows.sort(key=lambda r: -r[2])
    print(f"{'group':<44}{'objs':>8}{'GB':>8}{'gz x':>7}{'GB if gz':>10}{'GB >90d':>9}{'GB >180d':>10}{'oldest d':>9}")
    t = tg = 0
    for g, n, total, ratio, o90, o180, oldest in rows:
        t += total
        tg += total * min(ratio, 1.0)
        print(f"{g:<44}{n:>8,}{total / 1e9:>8.3f}{(1 / ratio if ratio else 0):>7.1f}{total * min(ratio, 1.0) / 1e9:>10.3f}"
              f"{o90 / 1e9:>9.3f}{o180 / 1e9:>10.3f}{oldest:>9}")
    print(f"TOTAL listed groups {t / 1e9:.2f} GB; if every group were gzipped {tg / 1e9:.2f} GB")
    return 0


def results_check(r2) -> int:
    """RESULTS_CHECK: before deleting raw_v2/nse/results_xbrl/ (owner, 15 Nov 2026: "delete it as we already have the
    data, right? Confirm it first"): every archived results filing read OK has its facts in xbrl_json, they parse back,
    the clean table can be rebuilt from them, and how many raw objects there are (blobs and fetch records)."""
    import json
    import os as _os
    from insiders_clean import results
    bucket = _os.environ.get('R2_BUCKET_NAME')
    frames = []
    for y in (2025, 2026):
        a = read_parquet(r2, f'archive/nse_events/results/year={y}.parquet')
        if a is not None:
            frames.append(a)
    a = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    print(f'archive results rows: {len(a)}; status: {a["xbrl_status"].astype(str).value_counts().to_dict()}')
    ok = a[a['xbrl_status'].astype(str).eq('ok')]
    empty = ok['xbrl_json'].isna() | ok['xbrl_json'].astype(str).str.len().lt(50)
    print(f'ok rows: {len(ok)}; ok rows with no facts stored: {int(empty.sum())}')
    bad = facts = 0
    for js in ok['xbrl_json'].dropna():
        try:
            p = json.loads(js)
            n = sum(len(v) for v in p.get('facts', {}).values())
            facts += n
            if n == 0:
                bad += 1
        except (TypeError, ValueError):
            bad += 1
    print(f'ok rows whose stored facts do not parse or are empty: {bad}; facts stored in all: {facts:,}')
    rebuilt = results.clean(a)
    print(f'clean table rebuilt from the archive alone: {len(rebuilt)} rows, quarter revenue present in '
          f'{int(pd.to_numeric(rebuilt["quarter_revenue"], errors="coerce").notna().sum())}')
    blobs = fetches = other = 0
    token = None
    while True:
        kw = {'Bucket': bucket, 'Prefix': 'raw_v2/nse/results_xbrl/'}
        if token:
            kw['ContinuationToken'] = token
        resp = r2.list_objects_v2(**kw)
        for o in resp.get('Contents', []):
            k = o['Key']
            if '/blobs/' in k:
                blobs += 1
            elif '/fetches/' in k:
                fetches += 1
            else:
                other += 1
        if not resp.get('IsTruncated'):
            break
        token = resp['NextContinuationToken']
    print(f'raw_v2/nse/results_xbrl: {blobs} blobs, {fetches} fetch records, {other} other')
    urls = set(ok['xbrl_url'].dropna())
    print(f'distinct XBRL links of ok rows: {len(urls)}')
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
                blob = __import__('clean_writer').get_blob(r2, bkey) if bkey else None
                print('  ' + (_body_excerpt(blob, ext).replace('\n', '\n  ') if blob is not None else f'(blob not found; record keys {list(rec)})'))
                if len(shown) >= 3:
                    break
    return 0

def results_orphans(r2) -> int:
    """RESULTS_ORPHANS (15 Nov 2026): results XBRL fetched OK into raw_v2 whose link is not on any archive row. Each
    link is looked up in every saved NSE results listing (raw_v2/nse/results_list) to say what it is: a filing the
    archive holds under a newer link (revised XBRL), a filing missing from the archive (a gap), or a link no saved
    listing names. Read-only."""
    import json
    from collections import Counter
    from concurrent.futures import ThreadPoolExecutor
    from clean_writer import get, get_blob, list_keys
    from insiders_clean import results
    frames = [f for f in (read_parquet(r2, f'archive/nse_events/results/year={y}.parquet') for y in (2025, 2026, 2027))
              if f is not None]
    a = pd.concat(frames, ignore_index=True)
    arch_urls = set(a['xbrl_url'].dropna())
    by_event = a.set_index('event_id')
    print(f'archive: {len(a):,} rows, {a["event_id"].nunique():,} filings, {len(arch_urls):,} links')

    def rec(k):
        try:
            return json.loads(get(r2, k) or b'{}')
        except ValueError:
            return {}
    with ThreadPoolExecutor(24) as ex:
        xrecs = list(ex.map(rec, [k for k in list_keys(r2, 'raw_v2/nse/results_xbrl/fetches/') if k.endswith('.json')]))
        lrecs = list(ex.map(rec, [k for k in list_keys(r2, 'raw_v2/nse/results_list/fetches/') if k.endswith('.json')]))
    orphans = {r['url']: r for r in xrecs if r.get('http_status') == 200 and r.get('url') and r['url'] not in arch_urls}
    print(f'raw results XBRL fetch records: {len(xrecs):,}; distinct links not in the archive: {len(orphans):,}')

    def listing(r):
        try:
            body = get_blob(r2, r['blob_key'])
            j = json.loads(body)
            return results.filing_rows(j.get('data', []) if isinstance(j, dict) else j)
        except Exception:  # noqa: BLE001 -- an unreadable page is counted, not fatal
            return None
    with ThreadPoolExecutor(24) as ex:
        pages = list(ex.map(listing, [r for r in lrecs if r.get('http_status') == 200 and r.get('blob_key')]))
    unreadable = sum(p is None for p in pages)
    listed = pd.concat([p for p in pages if p is not None and not p.empty], ignore_index=True)
    print(f'saved listing pages: {len(pages):,} ({unreadable} unreadable); listing rows: {len(listed):,}, '
          f'filings {listed["event_id"].nunique():,}')
    first = listed.drop_duplicates('xbrl_url').set_index('xbrl_url')
    kinds, gap_rows = Counter(), []
    for url in orphans:
        if url not in first.index:
            kinds['not_in_any_saved_listing'] += 1
            continue
        row = first.loc[url]
        eid = row['event_id']
        if eid in by_event.index:
            cur = by_event.loc[eid]
            cur = cur.iloc[0] if isinstance(cur, pd.DataFrame) else cur
            kinds['filing_in_archive_under_another_link/' + str(cur['xbrl_status']).split(':')[0]] += 1
        else:
            kinds['filing_missing_from_archive'] += 1
            gap_rows.append(row)
    print('orphan links by what they are: ' + json.dumps(dict(kinds)))
    if gap_rows:
        g = pd.DataFrame(gap_rows)
        print('missing filings by quarter end: ' + json.dumps(g['period_end'].value_counts().sort_index().to_dict()))
        print('missing filings by broadcast month: '
              + json.dumps(g['broadcast_date'].astype(str).str[:7].value_counts().sort_index().to_dict()))
        print(g[['symbol', 'period_end', 'broadcast_date', 'revision', 'consolidated']].head(10).to_string(index=False))
    # listed filings (any saved page) never in the archive, whether or not their XBRL was fetched
    never = listed[~listed['event_id'].isin(by_event.index)].drop_duplicates('event_id')
    print(f'listed filings never in the archive (any reason): {len(never):,}; by quarter end: '
          + json.dumps(never['period_end'].value_counts().sort_index().tail(8).to_dict()))
    return 0


def results_failed(r2) -> int:
    """RESULTS_FAILED (15 Nov 2026): every results filing whose XBRL was not read (status failed), with what was kept:
    the link, whether a raw copy exists, and the first bytes of it. Read-only."""
    import json
    from clean_writer import get, get_blob, list_keys
    frames = [f for f in (read_parquet(r2, f'archive/nse_events/results/year={y}.parquet') for y in (2025, 2026, 2027))
              if f is not None]
    a = pd.concat(frames, ignore_index=True)
    bad = a[a['xbrl_status'].astype(str).str.startswith('failed')]
    print(f'failed results filings: {len(bad)}; ' + json.dumps(bad['xbrl_status'].astype(str).value_counts().to_dict()))
    from concurrent.futures import ThreadPoolExecutor
    want = set(bad['xbrl_url'])

    def read(k):
        try:
            return json.loads(get(r2, k) or b'{}')
        except ValueError:
            return {}
    with ThreadPoolExecutor(24) as ex:   # 4,000 small reads: one at a time ran past the job limit
        recs = list(ex.map(read, list_keys(r2, 'raw_v2/nse/results_xbrl/fetches/')))
    blob_of = {r['url']: r for r in recs if r.get('url') in want}
    for _, r in bad.sort_values('broadcast_at').iterrows():
        rec = blob_of.get(r['xbrl_url'])
        head = ''
        if rec and rec.get('blob_key'):
            body = get_blob(r2, rec['blob_key']) or b''
            if rec['blob_key'].endswith('.gz'):
                import gzip
                body = gzip.decompress(body)
            head = body[:160].decode('utf-8', 'replace').replace('\n', ' ')
        print(f"  {r['symbol']:<12} {r['period_end']} {str(r['broadcast_date'])} {r['revision']:<9} {r['xbrl_status']:<22} "
              f"raw={'yes ' + str(rec.get('bytes')) if rec else 'no'} {r['xbrl_url']}")
        if head:
            print(f'      starts: {head}')
    return 0


def results_windows(r2) -> int:
    """RESULTS_WINDOWS (15 Nov 2026): for each listing window kept in raw_v2/nse/results_list, NSE's own totalCount
    against the distinct filings our saved pages hold, so a short quarter is told apart from a short listing. Read-only."""
    import json
    from collections import defaultdict
    from concurrent.futures import ThreadPoolExecutor
    from clean_writer import get, get_blob, list_keys
    from insiders_clean import results

    def rec(k):
        try:
            return json.loads(get(r2, k) or b'{}')
        except ValueError:
            return {}
    with ThreadPoolExecutor(24) as ex:
        recs = [r for r in ex.map(rec, [k for k in list_keys(r2, 'raw_v2/nse/results_list/fetches/') if k.endswith('.json')])
                if r.get('http_status') == 200 and r.get('blob_key')]

    def body(r):
        try:
            return r, json.loads(get_blob(r2, r['blob_key']))
        except Exception:  # noqa: BLE001
            return r, None
    with ThreadPoolExecutor(24) as ex:
        pages = list(ex.map(body, recs))
    total, seqs, quarters = {}, defaultdict(set), defaultdict(lambda: defaultdict(int))
    for r, j in pages:
        import re as _re
        m = _re.search(r'from_date=([0-9-]+).*?to_date=([0-9-]+)', str(r.get('url', '')))
        c = r.get('covers') or r.get('params') or {}
        w = (m[1], m[2]) if m else (c.get('from'), c.get('to'))
        if not isinstance(j, dict):
            continue
        total[w] = max(total.get(w, 0), int(j.get('totalCount') or 0))
        df = results.filing_rows(j.get('data', []))
        for sid, qe in zip(df['seq_id'], df['period_end']):
            if sid not in seqs[w]:
                seqs[w].add(sid)
                quarters[w][str(qe)[:7]] += 1
    print('window (from..to)            NSE count  we hold  short   top quarters')
    def day(x):   # dd-mm-yyyy in NSE's link
        try:
            d, mth, y = str(x[0]).split('-')
            return f'{y}-{mth}-{d}'
        except ValueError:
            return str(x[0])
    for w in sorted(total, key=day):
        got = len(seqs[w])
        top = sorted(quarters[w].items(), key=lambda kv: -kv[1])[:3]
        print(f'  {w[0]}..{w[1]}  {total[w]:>9,} {got:>8,} {total[w] - got:>6,}   {top}')
    return 0


def raw_deal_legs(r2, code: str, day: str) -> int:
    """RAW_DEALS:BSECODE_OR_SYMBOL:YYYY-MM-DD: the archived bulk and block rows of one security on one day, both
    exchanges, as filed (19 Nov 2026: IIFL Finance's seller showed twice the shares its buyers took)."""
    from clean_writer import read_archive
    for ex in ('bse', 'nse'):
        for cat in ('bulk_deals', 'block_deals'):
            a = read_archive(r2, ex, cat)
            if a is None or a.empty:
                print(f'--- {ex} {cat}: empty'); continue
            hit = a.apply(lambda r: any(str(v).strip().upper() == code for v in r.values), axis=1)
            x = a[hit]
            x = x[x.astype(str).apply(lambda r: r.str.contains(day).any() or r.str.contains(pd.Timestamp(day).strftime('%d-%m-%Y')).any()
                                      or r.str.contains(pd.Timestamp(day).strftime('%d/%m/%Y')).any(), axis=1)]
            print(f'--- {ex} {cat}: {len(x)} rows; columns {list(a.columns)}')
            if len(x):
                print(x.to_string(max_colwidth=40))
    return 0


def _months(start: pd.Timestamp, end: pd.Timestamp) -> list[str]:
    return [p.strftime('%Y-%m') for p in pd.period_range(start.to_period('M'), end.to_period('M'), freq='M')]


def symbol_prices(r2, sym: str, start: str, end: str) -> int:
    """PRICES:SYMBOL:FROM:TO: one company's price layer around a jump (19 Nov 2026: IIFL Finance from ~330 to ~600
    in July 2026). Every print under the symbol or its ISINs on both exchanges, all series, as printed; the implied
    factors with their kind and basis; the closes the site draws (artifacts/price_history.parquet); the filed
    corporate actions, the rights issues and the board meetings of those ISINs. Read only."""
    from clean_writer import list_keys
    from insiders_clean import adjust
    lo, hi = pd.Timestamp(start), pd.Timestamp(end)
    sec = read_parquet(r2, 'clean/current/securities.parquet')
    s = sec[sec['nse_symbol'].astype(str).str.upper() == sym] if sec is not None else pd.DataFrame()
    show('securities', s, ['isin', 'nse_symbol', 'bse_code', 'display_name', 'market_cap'])
    isins = set(s['isin'].dropna()) if len(s) else set()
    have = {k for k in list_keys(r2, 'prices/daily/') if k.endswith('.parquet')}
    frames = []
    for ex in ('nse', 'bse'):
        for m in _months(lo - pd.Timedelta(days=40), pd.Timestamp.today()):
            k = f'prices/daily/{ex}/{m}.parquet'
            if k in have:
                frames.append(read_parquet(r2, k))
    px = pd.concat([f for f in frames if f is not None], ignore_index=True)
    px['date'] = pd.to_datetime(px['date'])
    hit = px['symbol'].astype(str).str.upper().eq(sym) | px['isin'].isin(isins)
    isins |= set(px.loc[hit, 'isin'].dropna())
    # Any ISIN of the same issuer and security type (first nine characters): a new ISIN after a split or a
    # consolidation, or a partly paid line from a rights issue.
    stems = {i[:9] for i in isins if isinstance(i, str) and len(i) == 12}
    hit |= px['isin'].astype(str).str[:9].isin(stems)
    mine = px[hit].copy()
    print(f'prices read: {len(px)} rows, {px["date"].min().date()} to {px["date"].max().date()}; this company: {len(mine)} rows')
    print('--- prints by exchange, ISIN, symbol, series (first, last, rows):')
    print(mine.groupby(['exchange', 'isin', 'symbol', 'series'])['date'].agg(['min', 'max', 'size']).to_string())
    win = mine[(mine['date'] >= lo) & (mine['date'] <= hi)].sort_values(['date', 'exchange', 'isin', 'series'])
    show(f'prints {start} to {end}', win, ['date', 'exchange', 'isin', 'symbol', 'series', 'open', 'high', 'low', 'close',
                                          'prev_close', 'volume', 'value'])
    acts = [a for a in (read_parquet(r2, f'clean/current/{t}.parquet') for t in ('actions', 'bse_actions')) if a is not None and len(a)]
    acts = pd.concat(acts, ignore_index=True) if acts else None
    mine_acts = None
    if acts is not None:
        sm = acts['symbol'].astype(str).str.upper().eq(sym) if 'symbol' in acts else False
        mine_acts = acts[acts['isin'].isin(isins) | sm]
        show('filed corporate actions (clean actions + bse_actions)', mine_acts.sort_values('ex_date'),
             ['isin', 'symbol', 'purpose', 'subject', 'ex_date', 'record_date', 'ratio', 'face_value', 'rights_issue_price',
              'face_value_from', 'face_value_to', 'dividend_per_share'])
        show('expected factors', adjust.expected_factors(mine_acts), ['isin', 'ex_date', 'expected', 'split_bonus'])
    arch = [read_parquet(r2, k) for k in list_keys(r2, 'archive/nse_events/actions/') if k.endswith('.parquet')]
    arch = [a for a in arch if a is not None and len(a)]
    if arch:
        a = pd.concat(arch, ignore_index=True)
        a = a[a['isin'].isin(isins) | a['symbol'].astype(str).str.upper().eq(sym)]
        show('archived NSE actions (all kept purposes)', a.sort_values('ex_date'), ['isin', 'symbol', 'series', 'purpose', 'subject',
                                                                                   'ex_date', 'first_seen'])
    for t in ('rights', 'meetings', 'bse_meetings'):
        r = read_parquet(r2, f'clean/current/{t}.parquet')
        if r is None or r.empty:
            print(f'--- {t}: empty or missing'); continue
        m = r['isin'].isin(isins) if 'isin' in r else pd.Series(False, index=r.index)
        if 'symbol' in r:
            m |= r['symbol'].astype(str).str.upper().eq(sym)
        x = r[m]
        dc = next((c for c in ('meeting_date', 'record_date', 'date', 'broadcast_date') if c in x), None)
        if dc is not None:
            d = pd.to_datetime(x[dc], errors='coerce')
            x = x[(d >= lo - pd.Timedelta(days=120)) & (d <= hi + pd.Timedelta(days=30))]
        print(f'--- {t}: {len(x)} rows; columns {list(r.columns)[:30]}')
        if len(x):
            print(x.head(20).to_string(max_colwidth=60))
    f = adjust.implied_factors(mine, actions=mine_acts)
    f = adjust.inherit_nse(f)
    fw = f[(f['date'] >= lo) & (f['date'] <= hi)]
    show('implied factors in the window, kind not none', fw[fw['kind'] != 'none'],
         ['exchange', 'isin', 'symbol', 'date', 'close', 'prev_close', 'last_close', 'factor', 'kind', 'kind_basis'])
    s2 = adjust.session_frame(mine).sort_values(['exchange', 'isin', 'date'])
    s2['move'] = s2.groupby(['exchange', 'isin'])['close'].pct_change()
    big = s2[(s2['date'] >= lo) & (s2['date'] <= hi) & (s2['move'].abs() >= 0.2)]
    show('one-day close moves of 20% or more (most traded series)', big, ['exchange', 'isin', 'symbol', 'series', 'date', 'close',
                                                                         'prev_close', 'move', 'volume'])
    h = read_parquet(r2, 'artifacts/price_history.parquet')
    if h is not None:
        h = h[h['isin'].isin(isins)]
        h = h.assign(date=pd.to_datetime(h['date']))
        hw = h[(h['date'] >= lo) & (h['date'] <= hi)].sort_values(['isin', 'date'])
        hw = hw.assign(move=hw.groupby('isin')['close'].pct_change())
        show('site line (artifacts/price_history.parquet)', hw, ['isin', 'date', 'close', 'move'])
    summ = read_parquet(r2, 'artifacts/prices_summary_slim.parquet')
    if summ is not None:
        show('prices_summary_slim', summ[summ['isin'].isin(isins)], list(summ.columns))
    from insiders_clean import slim
    close, _, f3, raw = slim.adjusted_and_raw(mine, actions=mine_acts)
    print('--- side-window rows of this company:', adjust.side_series_rows(mine))
    for i in close.columns:
        line = pd.DataFrame({'raw': raw[i], 'adjusted (this branch)': close[i]}).loc[lo:hi].dropna(how='all')
        line['move'] = line['adjusted (this branch)'].pct_change()
        print(f'--- {i}: line recomputed with this code, {len(line)} sessions; largest |move| {line["move"].abs().max():.3f}')
        print(line[line['move'].abs() >= 0.03].to_string())
    return 0


def bse_raw_actions(r2) -> pd.DataFrame:
    """Every corporate action kept in raw_v2/bse/corporate_actions, parsed with this branch's parser, with the ISIN of
    its BSE code from clean securities: what bse_actions will hold once BSE's history is fetched again."""
    import json
    from clean_writer import get_blob, list_keys
    from collectors.bse import parsers as bse_parsers
    rows = []
    for k in sorted({k[:-3] if k.endswith('.gz') else k for k in list_keys(r2, 'raw_v2/bse/corporate_actions/blobs/')}):
        b = get_blob(r2, k)
        try:
            j = json.loads(b.decode('utf-8', errors='replace')) if b is not None else []
        except ValueError:
            continue
        j = j.get('Table', []) if isinstance(j, dict) else j
        rows += [r for r in j if isinstance(r, dict)]
    df, dropped = bse_parsers.parse_actions(rows)
    sec = read_parquet(r2, 'clean/current/securities.parquet')
    code = sec.dropna(subset=['bse_code']).assign(_c=lambda d: d['bse_code'].astype(str).str.split('.').str[0])
    df['isin'] = df['bse_code'].astype(str).map(code.drop_duplicates('_c').set_index('_c')['isin'])
    print(f'BSE raw actions reparsed: {len(df)} kept, {dropped} dropped, {int(df["isin"].notna().sum())} with an ISIN; purposes',
          df['purpose'].value_counts().to_dict())
    return df


def price_jump_audit(r2, check=(), reparse_bse=False) -> int:
    """PRICE_JUMPS: the price-jump audit (insiders_clean/price_jumps.py) on the whole price layer with this branch's
    code, as Precompute slim assets will write it; the series in the layer; the most suspect moves. Read only.
    PRICE_JUMPS_BSE_RAW: the same with BSE's raw actions reparsed by this branch (bse_raw_actions) added."""
    from insiders_clean import adjust, price_jumps, slim
    from insiders_clean.pipeline import PRODUCT_START
    from price_coverage import load_prefix
    from r2_writer import BUCKET
    px = load_prefix(r2, BUCKET, 'prices/daily/')
    px['date'] = pd.to_datetime(px['date'])
    print(f'prices: {len(px)} rows, {px["date"].min().date()} to {px["date"].max().date()}')
    print('rows by exchange and series (top 40):')
    print(px.groupby(['exchange', 'series']).size().sort_values(ascending=False).head(40).to_string())
    acts = [a for a in (read_parquet(r2, f'clean/current/{t}.parquet') for t in ('actions', 'bse_actions')) if a is not None and len(a)]
    if reparse_bse:
        acts.append(bse_raw_actions(r2))
    acts = pd.concat(acts, ignore_index=True) if acts else None
    left_out = adjust.side_series_rows(px)
    print('side-window rows left out:', left_out)
    close, _, f, raw = slim.adjusted_and_raw(px, actions=acts)
    print('adjust coverage:', adjust.coverage(f))
    lost = f[f['kind_basis'] == 'previous_session_missing']
    print('sessions after one the layer lacks (exchange, date: rows):',
          {f'{e} {d:%Y-%m-%d}': int(n) for (e, d), n in lost.groupby(['exchange', 'date']).size().items()})
    import json
    from clean_writer import get
    cal = json.loads(get(r2, 'reference/nse_calendar.json') or b'{}')
    wk = sorted(d for d in cal.get('traded', []) if pd.Timestamp(d).weekday() >= 5)
    print('calendar: weekend days traded:', wk[-10:], '; special sessions:', cal.get('special_sessions', [])[-10:])
    held = {e: sorted({f'{d:%Y-%m-%d}' for d in pd.to_datetime(px.loc[px['exchange'] == e, 'date'].unique()) if d.weekday() >= 5}) for e in ('NSE', 'BSE')}
    print('price layer: weekend days held:', held)
    uni = read_parquet(r2, 'clean/current/universe.parquet')
    uni = set(uni.loc[uni['in_universe'].astype(bool), 'isin']) if uni is not None and 'in_universe' in uni else None
    meta = (px.dropna(subset=['isin']).assign(_nse=lambda d: d['exchange'].eq('NSE')).sort_values(['_nse', 'date'])
            .drop_duplicates('isin', keep='last')[['isin', 'symbol', 'name']])
    for sym in check:
        for i in meta.loc[meta['symbol'].astype(str).str.upper() == sym, 'isin']:
            line = close[i].dropna() if i in close else pd.Series(dtype=float)
            if line.empty:
                continue
            yr = line.loc[line.index.max() - pd.Timedelta(days=365):]
            ff = f[(f['isin'] == i) & (f['kind'] == 'split_bonus')]
            print(f'--- {sym} {i}: last {line.iloc[-1]:.2f} on {line.index[-1]:%Y-%m-%d}; a year {yr.iloc[-1] / yr.iloc[0] - 1:+.1%} '
                  f'(from {yr.iloc[0]:.2f} on {yr.index[0]:%Y-%m-%d}); 52w high {yr.max():.2f}, low {yr.min():.2f}; largest one-day '
                  f'|move| {yr.pct_change().abs().max():.3f}; factors applied {ff[["exchange", "date", "factor", "kind_basis"]].to_dict("records")}')
    rows = price_jumps.jumps(raw, close, f, acts, start=PRODUCT_START, universe=uni, meta=meta)
    rep = price_jumps.report(rows, raw, start=PRODUCT_START, left_out=left_out)
    print({k: v for k, v in rep.items() if k != 'rows'})
    cols = ['symbol', 'isin', 'date', 'prev_date', 'gap_days', 'prev_close', 'close', 'raw_move', 'adj_move', 'factor', 'kind',
            'kind_basis', 'actions', 'in_universe']
    for s in price_jumps.STATUSES:
        x = rows[rows['status'] == s]
        if 'in_universe' in x and x['in_universe'].notna().any():
            xu = x[x['in_universe'].astype(bool)]
            print(f'\n--- {s}: {len(x)} moves, {x["isin"].nunique()} companies; in the study universe {len(xu)} moves, '
                  f'{xu["isin"].nunique()} companies')
            x = pd.concat([xu, x[~x['in_universe'].astype(bool)]])
        else:
            print(f'\n--- {s}: {len(x)} moves, {x["isin"].nunique()} companies')
        if len(x):
            print(x[cols].head(40).to_string(index=False))
    return 0


def market_flows_check(r2) -> int:
    """MARKET_FLOWS: is November 2026's FPI equity figure real (19 Nov: +Rs 1,06,229 Cr on the Dashboard)? The clean
    NSDL rows per reporting date and segment (duplicates, exchange against primary market), every month's total, the
    archive's fetches, NSDL's own "Total for November" from the newest raw page, and NSE's provisional days."""
    import json
    import re

    from clean_writer import get, list_keys
    from insiders_clean import market_flows as M
    from insiders_clean import raw_store
    f = read_parquet(r2, 'clean/current/market_flows.parquet')
    if f is None or f.empty:
        print('clean/current/market_flows.parquet: empty or missing')
        return 0
    f = f.assign(date=pd.to_datetime(f['date']))
    print('rows by source/category/segment:')
    print(f.groupby(['source', 'category', 'segment']).size().to_string())
    n = f[(f['source'] == 'nsdl') & (f['date'] >= '2026-11-01')]
    dup = n[n.duplicated(['date', 'segment'], keep=False)]
    print(f'\n--- NSDL Nov 2026: {len(n)} rows, {n["date"].nunique()} reporting dates, duplicated (date, segment): {len(dup)}')
    piv = n[n['segment'].isin(['equity', 'equity_exchange', 'equity_primary', 'total'])].pivot_table(
        index='date', columns='segment', values='net_cr', aggfunc=['sum', 'count'])
    print(piv.to_string())
    eq = n[n['segment'].isin(['equity', 'equity_exchange', 'equity_primary'])].groupby('segment')['net_cr'].sum()
    print('Nov sums:', eq.round(2).to_dict())
    m = f[(f['source'] == 'nsdl') & f['segment'].isin(['equity', 'equity_exchange', 'equity_primary'])]
    print('\n--- NSDL equity net by month (Rs Cr), all months held:')
    print(m.pivot_table(index=m['date'].dt.strftime('%Y-%m'), columns='segment', values='net_cr', aggfunc='sum').round(0).to_string())
    a = read_parquet(r2, 'archive/market_flows/nsdl/year=2026.parquet')
    if a is not None and not a.empty:
        a = a.assign(date=pd.to_datetime(a['date']))
        an = a[(a['date'] >= '2026-11-01') & (a['segment'] == 'equity')]
        print(f'\n--- archive nsdl 2026, Nov equity: {len(an)} rows, dates {an["date"].nunique()}, '
              f'fetched_at values: {an["fetched_at"].astype(str).value_counts().to_dict() if "fetched_at" in an else "none"}')
    keys = sorted(k for k in list_keys(r2, 'raw_v2/nsdl/fpi_daily/fetches/2026-11') if k.endswith('.json'))
    print(f'\n--- raw NSDL fetches in Nov 2026: {len(keys)}')
    for k in keys[-3:]:
        print('   ', k)
    if keys:
        rec = json.loads(get(r2, keys[-1]))
        print('newest fetch record:', {x: rec.get(x) for x in ('url', 'params', 'status', 'fetched_at', 'covers', 'sha256', 'blob_key', 'bytes')})
        blob = rec.get('blob_key') or next((b for b in list_keys(r2, f"raw_v2/nsdl/fpi_daily/blobs/{rec['sha256'][:2]}/{rec['sha256']}")), None)
        body = raw_store.read_blob(lambda key: get(r2, key), blob) if blob else None
        if body is None:
            print('newest raw page: blob not found')
        else:
            html = body.decode('utf-8', 'ignore')
            i = html.find('Daily Trends in FPI Investments')
            html = html[html.rfind('<table', 0, i):]
            on = False
            for cells, _ in M._rows(html):
                c = list(cells)
                if c and c[0].startswith('Total for '):
                    on = c[0].startswith('Total for November')
                    print('NSDL page:', c)
                elif on and len(c) >= 4 and (c[0] in ('Primary market & others', 'Sub-total')):
                    print('NSDL page:', c)
                    if c[0] == 'Sub-total':
                        on = False
            notes = []
            d = M.parse_nsdl_daily(body.decode('utf-8', 'ignore'), notes)
            print('parsed again: equity days sum', round(float(d.loc[d['segment'] == 'equity', 'net_cr'].sum()), 2), 'notes:', notes)
    nse = f[(f['source'] == 'nse') & (f['category'] == 'fpi')]
    print('\n--- NSE provisional FII/FPI days held:')
    print(nse[['date', 'segment', 'buy_cr', 'sell_cr', 'net_cr']].sort_values(['date', 'segment']).to_string(index=False))
    print('NSE days held sum by segment:', nse.groupby('segment')['net_cr'].sum().round(2).to_dict())
    return 0


def mf_stock(r2, sym: str, pattern: str = '') -> int:
    """MF_STOCK:SYMBOL[:regex] (19 Nov): every fund table row behind one company on the Funds page (mf_holdings,
    mf_changes, mf_stock_month, its shareholding total_shares, actions), ISINs found by symbol and by name, and the
    scheme lines in the raw portfolio files of the houses that moved it in the latest two months. Read-only."""
    import json
    import re

    from clean_writer import get, get_blob, list_keys
    from insiders_clean import mf_holdings
    sec = read_parquet(r2, 'clean/current/securities.parquet')
    h = read_parquet(r2, 'clean/current/mf_holdings.parquet')
    ch = read_parquet(r2, 'clean/current/mf_changes.parquet')
    st = read_parquet(r2, 'clean/current/mf_stock_month.parquet')
    sh = read_parquet(r2, 'clean/current/shareholding.parquet')
    s = sec[sec['nse_symbol'].astype(str).str.upper() == sym]
    show('securities', s, ['isin', 'nse_symbol', 'bse_code', 'display_name', 'market_cap', 'listing_status'])
    isins = set(s['isin'].dropna())
    rx = re.compile(pattern, re.I) if pattern else None
    if rx is not None:
        isins |= set(h.loc[h['name'].astype(str).str.contains(rx), 'isin'])
    print('ISINs:', sorted(isins))
    hh = h[h['isin'].isin(isins)]
    show('mf_holdings', hh.sort_values(['month', 'amc']),
         ['month', 'amc', 'isin', 'name', 'shares', 'active_shares', 'value_lakh', 'schemes', 'active_schemes', 'kind'])
    print('per month and ISIN: houses, shares, value (lakh), implied price (value*1e5/shares)')
    g = hh.groupby(['month', 'isin']).agg(houses=('amc', 'nunique'), shares=('shares', 'sum'), value=('value_lakh', 'sum'))
    g['price'] = g['value'] * 1e5 / g['shares']
    print(g.to_string())
    ib = ch['isin_before'] if 'isin_before' in ch else pd.Series(index=ch.index, dtype=object)
    cc = ch[ch['isin'].isin(isins) | ib.isin(isins)]
    show('mf_changes', cc.sort_values(['month', 'amc']),
         ['month', 'amc', 'isin', 'isin_before', 'shares_before', 'shares', 'factor', 'change', 'active_before',
          'active_shares', 'active_change', 'kind', 'value_lakh', 'house_kind'])
    show('mf_stock_month', st[st['isin'].isin(isins)].sort_values('month'), list(st.columns))
    q = sh[sh['isin'].isin(isins) | (sh['symbol'].astype(str).str.upper() == sym)]
    show('shareholding', q.sort_values('quarter_end'), ['isin', 'symbol', 'quarter_end', 'total_shares', 'mf_shares',
                                                        'promoter_holding_pct', 'submission_date'])
    px = read_parquet(r2, 'artifacts/prices_summary_slim.parquet')
    if px is not None:
        show('prices_summary_slim', px[px['isin'].isin(isins)], list(px.columns)[:12])
    for k in ('clean/current/actions.parquet', 'clean/current/bse_actions.parquet'):
        a = read_parquet(r2, k)
        if a is not None and 'isin' in a:
            print(k, 'columns:', list(a.columns)[:30])
            show(k, a[a['isin'].isin(isins)], list(a.columns)[:14])
    # The raw scheme lines of the houses that moved it in the latest two months
    ms = sorted(ch['month'].unique())[-2:]
    movers = sorted(set(cc.loc[cc['month'].isin(ms) & cc['change'].ne(0), 'amc']))
    print('houses that moved it in', ms, ':', movers)
    want = set(ms) | {str(pd.Period(ms[0], 'M') - 1)}
    for amc in movers:
        recs = []
        for k in list_keys(r2, f'raw_v2/amc/{amc}/portfolio_month/fetches/'):
            if k.endswith('.json'):
                r = json.loads(get(r2, k))
                if (r.get('covers') or {}).get('month') in want and r.get('http_status') == 200:
                    recs.append(r)
        print(f'--- {amc}: {len(recs)} raw fetches for {sorted(want)}')
        seen = set()
        for r in sorted(recs, key=lambda r: r['fetched_at_utc']):
            if r['sha256'] in seen:
                continue
            seen.add(r['sha256'])
            body = get_blob(r2, r['blob_key'])
            try:
                df, rep = mf_holdings.parse_workbook(body, r['url'].split('?')[0].rsplit('/', 1)[-1])
            except Exception as e:  # noqa: BLE001
                print('   not parsed', r['url'][:120], e)
                continue
            hit = df['isin'].isin(isins)
            if rx is not None:
                hit |= df['name'].astype(str).str.contains(rx)
            x = df[hit]
            if len(x):
                print(f'   {r["covers"].get("month")} {r["fetched_at_utc"][:16]} {r["url"][:110]}')
                print(x[['sheet', 'scheme', 'isin', 'name', 'quantity', 'value_lakh', 'pct_aum']].to_string(index=False))
    return 0


def mf_raw(r2) -> int:
    """MF_RAW (19 Nov): raw month-end portfolio files per house (raw_v2/amc/), by key listing only (no record read:
    reading each record one by one ran past the job's 15 minutes), against the archived house-months."""
    from collections import Counter, defaultdict

    from clean_writer import list_keys
    arch = defaultdict(list)
    for k in list_keys(r2, 'archive/mf_holdings/'):
        if k.endswith('.parquet'):
            arch[k.rsplit('/', 1)[1][:-8]].append(k.split('month=')[1].split('/')[0])
    keys = list_keys(r2, 'raw_v2/amc/')
    fetch, blobs, days = Counter(), Counter(), defaultdict(Counter)
    for k in keys:
        parts = k.split('/')
        house = parts[2]
        if '/fetches/' in k:
            fetch[house] += 1
            days[house][k.split('/fetches/')[1][:10]] += 1
        elif '/blobs/' in k:
            blobs[house] += 1
    print(f'{len(keys)} raw amc keys; {sum(len(v) for v in arch.values())} archived house-months')
    for house in sorted(set(arch) | set(fetch)):
        ms = sorted(arch.get(house, []))
        print(f'{house:14s} archived {len(ms):2d} ({ms[0] if ms else "-"}..{ms[-1] if ms else "-"}) | raw fetches '
              f'{fetch[house]:4d}, blobs {blobs[house]:4d} | fetch days {dict(sorted(days[house].items()))}')
    return 0


def mf_schemes(r2, month: str = '2026-10') -> int:
    """MF_SCHEMES[:YYYY-MM] (19 Nov): per house with raw files for the month, the schemes read from them against AMFI's
    open-ended equity schemes for the house that month-end (the scheme count check, mf_holdings.scheme_coverage), and
    whether the scheme rows add up to the archived house rows. Read-only: nothing is written to R2."""
    import mf_portfolios as mp
    from clean_writer import read_parquet
    from collectors.mf_portfolios.houses import HOUSES, NOT_COLLECTED
    from insiders_clean import mf_holdings as m
    amfi, info = mp.amfi_list(month)
    print('AMFI:', info)
    lists, adds = [], {}
    for h in HOUSES:
        got = mp.raw_rows(r2, h, {month})
        if month not in got:
            continue
        rows = got[month]
        lists.append(m.scheme_list(rows, h.key, month, h.name))
        hold = read_parquet(r2, f'{mp.ARCHIVE}month={month}/{h.key}.parquet')
        adds[h.key] = mp.add_up(m.scheme_holdings(rows, h.key, month, h.name), hold) if hold is not None else 'no archive'
    cov = m.scheme_coverage(pd.concat(lists, ignore_index=True), amfi if len(amfi) else None,
                            {h.key: h.kind for h in HOUSES})
    cov['isins_not_adding_up'] = cov['amc'].map(adds)
    pd.set_option('display.max_colwidth', 120)
    print(cov.drop(columns=['amfi_not_matched']).to_string(index=False))
    print('\nAMFI equity schemes not matched by name, per house:')
    for r in cov.to_dict('records'):
        if r.get('amfi_not_matched'):
            print(f'  {r["amc"]}: {r["amfi_not_matched"][:600]}')
    if len(amfi):
        eq = amfi[amfi['open_ended'] & amfi['category'].eq('equity')]
        per = eq.groupby('house').agg(amc=('amc', 'first'), equity=('scheme_key', 'nunique')).reset_index()
        print('\nAMFI open-ended equity schemes per house (every house on the list; amc blank = not collected):')
        print(per.to_string(index=False))
    print('not collected:', NOT_COLLECTED)
    return 0


SCHEME_WORDS = r'demerg|scheme|arrangement|amalgam|capital reduction|reduction of capital|spin'


def raw_actions(r2, syms: list[str]) -> int:
    """RAW_ACTIONS:SYM,SYM2: every corporate-action row the exchanges sent for these companies, as kept in raw_v2/
    (NSE's API feed raw_v2/nse/actions, BSE's raw_v2/bse/corporate_actions, the `bc` file of NSE's PR zip
    raw_v2/exchange_files/nse_pr_zip), whatever the purpose, with whether parsers.action_purpose keeps it; and over
    all of raw, the scheme / demerger rows the parser drops. Read only (20 Nov 2026, price-jump audit)."""
    import io as _io
    import json
    import re
    import zipfile
    from clean_writer import get_blob, list_keys
    from collectors.nse_events.parsers import action_purpose
    sec = read_parquet(r2, 'clean/current/securities.parquet')
    s = sec[sec['nse_symbol'].astype(str).str.upper().isin(syms)] if sec is not None else pd.DataFrame()
    show('securities', s, ['isin', 'nse_symbol', 'bse_code', 'display_name'])
    isins = set(s['isin'].dropna())
    codes = {str(c).split('.')[0] for c in s['bse_code'].dropna()} if 'bse_code' in s else set()
    stems = {i[:9] for i in isins if isinstance(i, str) and len(i) == 12}

    def blobs(prefix):
        return sorted({k[:-3] if k.endswith('.gz') else k for k in list_keys(r2, prefix + 'blobs/')})

    def json_rows(body):
        try:
            j = json.loads(body.decode('utf-8', errors='replace'))
        except ValueError:
            return []
        if isinstance(j, dict):
            j = next((v for v in j.values() if isinstance(v, list)), [])
        return [r for r in j if isinstance(r, dict)] if isinstance(j, list) else []

    for label, prefix, sym_f, isin_f, subj_f, ex_f in (
            ('NSE API', 'raw_v2/nse/actions/', 'symbol', 'isin', 'subject', 'exDate'),
            ('BSE', 'raw_v2/bse/corporate_actions/', 'scrip_code', None, 'Purpose', 'Ex_date')):
        keys = blobs(prefix)
        rows = []
        for k in keys:
            b = get_blob(r2, k)
            rows += json_rows(b) if b is not None else []
        d = pd.DataFrame(rows)
        print(f'\n===== {label} raw ({prefix}): {len(keys)} blobs, {len(d)} rows')
        if d.empty:
            continue
        d = d.drop_duplicates([c for c in (sym_f, subj_f, ex_f) if c in d])
        d['_kept'] = d[subj_f].map(action_purpose)
        ex = pd.to_datetime(d[ex_f], errors='coerce', dayfirst=True)
        print(f'  unique rows {len(d)}; ex-dates {ex.min()} .. {ex.max()}; dropped by the parser {int(d["_kept"].isna().sum())}')
        sch = d[d[subj_f].astype(str).str.contains(SCHEME_WORDS, case=False, regex=True)]
        print(f'  scheme / demerger rows: {len(sch)} (of them dropped {int(sch["_kept"].isna().sum())})')
        cols = [c for c in (sym_f, isin_f, 'comp', 'long_name', subj_f, ex_f, 'recDate', 'RD_Date', '_kept') if c and c in d]
        if len(sch):
            print(sch[cols].to_string(index=False, max_colwidth=70))
        m = d[sym_f].astype(str).str.upper().str.split('.').str[0].isin(set(syms) | codes)
        if isin_f and isin_f in d:
            m |= d[isin_f].isin(isins) | d[isin_f].astype(str).str[:9].isin(stems)
        print(f'  -- rows of {syms}: {int(m.sum())}')
        if m.any():
            print(d[m][cols].to_string(index=False, max_colwidth=70))
    keys = blobs('raw_v2/exchange_files/nse_pr_zip/')
    rows = []
    for k in keys:
        b = get_blob(r2, k)
        try:
            z = zipfile.ZipFile(_io.BytesIO(b))
        except Exception:   # noqa: BLE001
            continue
        for n in z.namelist():
            if re.match(r'(?i)^bc\d{6}\.csv$', n.split('/')[-1]):
                try:
                    f = pd.read_csv(_io.BytesIO(z.read(n)), dtype=str)
                except Exception:   # noqa: BLE001
                    continue
                f.columns = [c.strip().upper() for c in f.columns]
                rows.append(f.assign(_file=n))
    d = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    print(f'\n===== NSE PR zip bc files: {len(keys)} zips, {len(rows)} bc files, {len(d)} rows; columns {list(d.columns)}')
    if len(d) and 'PURPOSE' in d:
        d = d.apply(lambda c: c.str.strip() if c.dtype == object else c)
        d = d.drop_duplicates([c for c in d.columns if c != '_file'])
        d['_kept'] = d['PURPOSE'].map(action_purpose)
        sch = d[d['PURPOSE'].astype(str).str.contains(SCHEME_WORDS, case=False, regex=True)]
        print(f'  unique rows {len(d)}; scheme / demerger rows {len(sch)}')
        if len(sch):
            print(sch.to_string(index=False, max_colwidth=70))
        m = d['SYMBOL'].astype(str).str.upper().isin(syms) if 'SYMBOL' in d else pd.Series(False, index=d.index)
        print(f'  -- rows of {syms}: {int(m.sum())}')
        if m.any():
            print(d[m].to_string(index=False, max_colwidth=70))
    return 0


def actions_coverage(r2) -> int:
    """ACTIONS_COVERAGE: what the action tables hold, by ex-date month and purpose (NSE archive, clean actions,
    clean bse_actions), when the NSE rows were first seen, and how many rows have an ISIN. Read only (20 Nov)."""
    from clean_writer import list_keys
    arch = [read_parquet(r2, k) for k in list_keys(r2, 'archive/nse_events/actions/') if k.endswith('.parquet')]
    arch = [a for a in arch if a is not None and len(a)]
    tabs = {'archive/nse_events/actions': pd.concat(arch, ignore_index=True) if arch else pd.DataFrame()}
    for t in ('actions', 'bse_actions'):
        tabs[f'clean/current/{t}'] = read_parquet(r2, f'clean/current/{t}.parquet')
    for name, d in tabs.items():
        if d is None or d.empty:
            print(f'--- {name}: empty')
            continue
        ex = pd.to_datetime(d['ex_date'], errors='coerce')
        print(f'--- {name}: {len(d)} rows, ex-dates {ex.min()} .. {ex.max()}; columns {list(d.columns)}')
        if 'first_seen' in d:
            fs = pd.to_datetime(d['first_seen'], errors='coerce')
            print('  first_seen by month:', fs.dt.to_period('M').astype(str).value_counts().sort_index().to_dict())
        if 'isin' in d:
            print(f'  rows with an ISIN: {int(d["isin"].notna().sum())}')
        if 'series' in d:
            print('  series:', d['series'].astype(str).value_counts().head(15).to_dict())
        print(pd.crosstab(ex.dt.to_period('M').astype(str), d['purpose'].astype(str)).to_string())
    return 0


def main() -> int:
    r2 = r2_client()
    syms = [x.strip().upper() for x in os.environ.get('SYMBOLS', '').split(',') if x.strip()]
    if syms == ['MARKET_FLOWS']:   # is November's FPI equity figure real (19 Nov)
        return market_flows_check(r2)
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
    if syms == ['RESULTS_CHECK']:   # is everything in the raw results XBRL also in the archive (15 Nov)
        return results_check(r2)
    if syms == ['RESULTS_WINDOWS']:   # NSE's count per results listing window against what we hold (15 Nov)
        return results_windows(r2)
    if syms == ['RESULTS_FAILED']:   # results filings whose XBRL was not read, with the raw kept (15 Nov)
        return results_failed(r2)
    if syms == ['RESULTS_ORPHANS']:   # raw results XBRL whose link is on no archive row: what they are (15 Nov)
        return results_orphans(r2)
    if syms == ['COMPRESS']:   # gzip ratio and age per folder (15 Nov)
        return compress_age(r2)
    if syms == ['SIZES']:   # objects and bytes per folder (15 Nov)
        return sizes(r2)
    if syms and syms[0].startswith('RAW_DEALS:'):   # one security-day of raw bulk and block rows (19 Nov)
        _, code, day = syms[0].split(':')
        return raw_deal_legs(r2, code, day)
    if syms == ['PRICE_JUMPS_BSE_RAW']:   # the audit with BSE's raw actions reparsed by this branch (20 Nov)
        return price_jump_audit(r2, [], reparse_bse=True)
    if syms and syms[0].split(':')[0] == 'PRICE_JUMPS':   # every 40% one-day move on the site's lines (19 Nov); PRICE_JUMPS:SYM,SYM2 also prints those lines
        return price_jump_audit(r2, [syms[0].split(':', 1)[1]] + syms[1:] if ':' in syms[0] else [])
    if syms == ['ACTIONS_COVERAGE']:   # the action tables by ex-date month and purpose (20 Nov)
        return actions_coverage(r2)
    if syms and syms[0].startswith('RAW_ACTIONS:'):   # every raw action row of these companies, any purpose (20 Nov)
        return raw_actions(r2, [syms[0].split(':', 1)[1]] + syms[1:])
    if syms and syms[0].startswith('PRICES:'):  # one company's prints, factors, site line and actions (19 Nov)
        _, sym, start, end = syms[0].split(':')
        return symbol_prices(r2, sym, start, end)
    if syms and syms[0].startswith('TRADES:'):  # a company's insider rows and deals as cleaned (14 Nov)
        return trades_and_deals(r2, syms[0].split(':', 1)[1])
    if syms and syms[0].startswith('RESULTS_XBRL:'):   # a company's Sep 2026 results filings as filed (13 Nov)
        return results_xbrl(r2, [syms[0].split(':', 1)[1]] + syms[1:])
    if syms == ['DEAL_DAYS']:    # TODO 18: bulk and block deals per day and exchange around 07-08 Oct 2026
        return deal_days(r2)
    if syms and syms[0].startswith('MF_STOCK:'):   # one company's fund rows and raw scheme lines (19 Nov)
        parts = syms[0].split(':')
        return mf_stock(r2, parts[1], parts[2] if len(parts) > 2 else '')
    if syms and syms[0].startswith('MF_SCHEMES'):   # schemes read per house against AMFI's list (19 Nov)
        return mf_schemes(r2, *syms[0].split(':')[1:2])
    if syms == ['MF_RAW']:   # raw portfolio fetches per house-month against the archive (19 Nov)
        return mf_raw(r2)
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
