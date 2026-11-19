"""Mutual fund month-end portfolios: find, fetch, store raw, parse, archive, rebuild the clean tables.

    python scripts/mf_portfolios.py --month 2026-10 [--month 2026-09 ...] [--house sbi ...] [--dry-run]
    python scripts/mf_portfolios.py --latest 2          # the last two published month-ends (by the 10th rule)

For each fund house (collectors/mf_portfolios/houses.py) and month: find the file on its disclosure page, download
it, save the exact bytes for the write-once raw layer (raw_v2/amc/{house}/portfolio_month/, via raw_capture and the
raw_flush step), parse it (insiders_clean/mf_holdings.py) and keep

    archive/mf_holdings/month=YYYY-MM/{house}.parquet     one row per ISIN the house held at that month-end

A house or month that is not found or does not parse is reported with the reason and left out; nothing is filled in.
Then the clean tables are rebuilt from every archived month:

    clean/current/mf_holdings.parquet     house, month, ISIN, shares, value (Rs lakh), schemes, kind (mf / pension)
    clean/current/mf_changes.parquet      house, month, ISIN, shares before and after, change, kind (new/added/cut/exit/held),
                                          house_kind (mf / pension)
    clean/current/mf_stock_month.parquet  month, house_kind, ISIN: houses adding / cutting / new / exiting, net shares
    clean/current/mf_coverage.parquet     quarter-end month: collected mutual fund houses' shares / mutual-fund shares the
                                          companies filed (pension funds left out: the filing's figure is mutual funds')
    clean/current/mf_scheme_changes.parquet   house, scheme, month, ISIN: shares at the start (split/bonus applied) and
                                          end, change, value, status (new/added/cut/exit/held), passive, scheme key,
                                          scheme_seen (both month-ends or one), change_cr at the stock table's price
    clean/current/mf_scheme_month.parquet  per house, scheme and month: net, bought and sold rupees, stocks moved
    clean/current/mf_scheme_moves.parquet  the site's slim cut: active schemes, rows that moved, the last 12 months
    clean/current/mf_scheme_coverage.parquet  per house-month: schemes read, equity schemes read, AMFI's open-ended equity
                                          schemes for the house that month-end (its NAV report), matched, flag
    clean/reports/mf_portfolios/{run date}.json   per house and month: found, file, sheets read, lines, ISINs, why not

Scheme by scheme: every house-month collected is also kept as archive/mf_schemes/ and archive/mf_scheme_list/. For
house-months archived before (19 Nov 2026), --schemes reads them again from the raw files stored, else downloads them
again, and keeps them only when they add up to the archived house rows. AMFI's NAV report for each archived month-end's
last working day is read once (archive/amfi_schemes/, raw in raw_v2/amfi/nav_history/) unless --no-amfi.
mf_stock_month also carries total_shares: the company's shares on the month-end's basis (its last filing, a split or
bonus since applied), which "% of the company" divides by.

The NPS pension fund managers (houses with kind='pension', keys nps_...) are collected the same way and kept in the
same tables, marked by kind, so the Funds page can keep them apart from mutual funds.

--dry-run fetches and parses and prints counts; it writes nothing to R2.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from collectors.mf_portfolios import find  # noqa: E402
from collectors.mf_portfolios.houses import BY_KEY, HOUSES  # noqa: E402
from insiders_clean import mf_holdings  # noqa: E402

ARCHIVE = 'archive/mf_holdings/'
SCHEME_ARCHIVE = 'archive/mf_schemes/'          # month=YYYY-MM/{house}.parquet: scheme x ISIN rows (scheme_holdings)
SCHEME_LIST_ARCHIVE = 'archive/mf_scheme_list/'  # month=YYYY-MM/{house}.parquet: every scheme read (scheme_list)
AMFI_ARCHIVE = 'archive/amfi_schemes/'          # month=YYYY-MM.parquet: AMFI's schemes per house on the month-end
CLEAN = {'holdings': 'clean/current/mf_holdings.parquet', 'changes': 'clean/current/mf_changes.parquet',
         'stock': 'clean/current/mf_stock_month.parquet', 'coverage': 'clean/current/mf_coverage.parquet',
         'scheme_changes': 'clean/current/mf_scheme_changes.parquet', 'scheme_month': 'clean/current/mf_scheme_month.parquet',
         'scheme_moves': 'clean/current/mf_scheme_moves.parquet', 'scheme_coverage': 'clean/current/mf_scheme_coverage.parquet'}
ADD_UP_TOLERANCE = 0.5   # shares: scheme rows summed per ISIN must equal the archived house row to within this
IST = timezone(timedelta(hours=5, minutes=30))
PUBLISH_DAY = 10   # SEBI: a month-end portfolio is on the house's site by the 10th of the next month


def latest_months(n: int, today: date) -> list[str]:
    """The last `n` month-ends whose portfolios must be out by `today`."""
    y, m = today.year, today.month - (1 if today.day > PUBLISH_DAY else 2)
    out = []
    for _ in range(n):
        while m <= 0:
            m += 12
            y -= 1
        out.append(f'{y}-{m:02d}')
        m -= 1
    return out


def expand(spec: str) -> list[str]:
    """'2025-10..2026-01' or '2026-09 2026-10' -> the months, in order."""
    out = []
    for part in spec.split():
        if '..' in part:
            a, b = part.split('..')
            out += [str(p) for p in pd.period_range(a, b, freq='M')]
        else:
            out.append(str(pd.Period(part, 'M')))
    return sorted(set(out))


def _download(url: str, timeout: int = 180) -> tuple[bytes, str | None, int]:
    import requests
    r = requests.get(url, headers={'User-Agent': find.UA}, timeout=timeout)
    return r.content, r.headers.get('Content-Type'), r.status_code


def collect_house(house, months: list[str], browser=None) -> list[dict]:
    """One result per month: {'house', 'month', 'found', 'files', 'rows' (DataFrame) or 'why'}."""
    from raw_capture import capture
    out = []
    links = []
    if house.api is None and house.pages is None:
        try:
            links = find.links_rendered(house.page, browser, house.click) if house.render else find.links_plain(house.page)
        except Exception as exc:  # noqa: BLE001
            return [{'house': house.key, 'month': m, 'found': False, 'why': f'page not read ({type(exc).__name__}: {exc})'[:300]}
                    for m in months]
    for month in months:
        if house.api is not None:   # the page's own JSON call, asked for this month
            try:
                links = house.api(month)
            except Exception as exc:  # noqa: BLE001
                out.append({'house': house.key, 'month': month, 'found': False,
                            'why': f'list not read ({type(exc).__name__}: {exc})'[:300]})
                continue
        if house.pages is not None:   # a page per month: its links name no month, so the month is added to their text
            label = pd.Period(month, 'M').strftime('%B %Y')
            links = []
            try:
                for pg in house.pages(month):
                    got = find.links_rendered(pg, browser, house.click) if house.render else find.links_plain(pg)
                    links += [(f'{label} {t}', h) for t, h in got]
            except Exception as exc:  # noqa: BLE001
                out.append({'house': house.key, 'month': month, 'found': False,
                            'why': f'page not read ({type(exc).__name__}: {exc})'[:300]})
                continue
        urls = find.candidates(links, month, house)
        res = {'house': house.key, 'month': month, 'found': bool(urls), 'links_on_page': len(links), 'files': urls}
        if not urls:
            res['why'] = 'no file for the month on the page'
            out.append(res)
            continue
        frames, reports = [], []
        for u in urls:
            try:
                body, ctype, status = find.fetch_rendered(u, browser) if house.browser_fetch else _download(u)
            except Exception as exc:  # noqa: BLE001
                reports.append({'url': u, 'error': f'{type(exc).__name__}: {exc}'[:200]})
                continue
            capture('amc', f'{house.key}/portfolio_month', body, url=u, status=status, content_type=ctype,
                    covers={'month': month})
            if status != 200:
                reports.append({'url': u, 'error': f'HTTP {status}'})
                continue
            try:
                df, rep = mf_holdings.parse_workbook(body, u.split('?')[0].rsplit('/', 1)[-1], house.value_unit)
            except Exception as exc:  # noqa: BLE001
                reports.append({'url': u, 'error': f'not parsed ({type(exc).__name__}: {exc})'[:200]})
                continue
            rep['url'] = u
            reports.append(rep)
            frames.append(df)
        res['parse'] = reports
        rows = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        if rows.empty or not mf_holdings.is_equity(rows['isin']).any():
            res['found'] = False
            res['why'] = 'file(s) read but no equity holding lines' if frames else 'no file downloaded and parsed'
        else:
            res['rows'] = rows
        out.append(res)
    return out


def put_schemes(r2, house, month: str, rows: pd.DataFrame) -> pd.DataFrame:
    """Archive one house-month scheme by scheme (scheme x ISIN rows and the list of schemes read); returns the rows."""
    from clean_writer import put_parquet
    sc = mf_holdings.scheme_holdings(rows, house.key, month, house.name)
    put_parquet(r2, f'{SCHEME_ARCHIVE}month={month}/{house.key}.parquet', sc)
    put_parquet(r2, f'{SCHEME_LIST_ARCHIVE}month={month}/{house.key}.parquet',
                mf_holdings.scheme_list(rows, house.key, month, house.name))
    return sc


def add_up(sc: pd.DataFrame, hold: pd.DataFrame) -> int:
    """ISINs where the scheme rows' shares, summed, differ from the house row archived for the same month (or are on
    one side only). 0: the scheme table is the house table split by scheme."""
    a = sc.groupby('isin')['shares'].sum() if len(sc) else pd.Series(dtype=float)
    b = hold.groupby('isin')['shares'].sum() if len(hold) else pd.Series(dtype=float)
    return int((a.sub(b, fill_value=0).abs() > ADD_UP_TOLERANCE).sum())


def raw_rows(r2, house, months: set) -> dict:
    """{month: parsed rows} from the raw files already stored for this house (raw_v2/amc/{house}/portfolio_month/):
    the HTTP-200 fetches whose record covers the month, the latest fetch of each address, every one parsed as the
    collector parses it. A month with no such fetch is not in the result."""
    import json
    from concurrent.futures import ThreadPoolExecutor

    from clean_writer import get, get_blob, list_keys
    keys = [k for k in list_keys(r2, f'raw_v2/amc/{house.key}/portfolio_month/fetches/') if k.endswith('.json')]
    if not keys:
        return {}
    with ThreadPoolExecutor(16) as pool:
        recs = [json.loads(b) for b in pool.map(lambda k: get(r2, k), keys) if b]
    by: dict = {}
    for r in sorted(recs, key=lambda r: r.get('fetched_at_utc', '')):
        m = (r.get('covers') or {}).get('month')
        if m in months and r.get('http_status') == 200 and not r.get('content_check'):
            by.setdefault(m, {})[r['url']] = r          # the latest fetch of each address
    out = {}
    for m, urls in by.items():
        frames = []
        for u, r in urls.items():
            try:
                df, _ = mf_holdings.parse_workbook(get_blob(r2, r['blob_key']), u.split('?')[0].rsplit('/', 1)[-1],
                                                   house.value_unit)
                frames.append(df)
            except Exception as exc:  # noqa: BLE001 -- a file that does not parse is left out; add_up then says so
                print(f'{house.key} {m}: raw {u[:100]} not parsed ({type(exc).__name__})')
        if frames:
            out[m] = pd.concat([f for f in frames if len(f)] or frames[:1], ignore_index=True)
    return out


def backfill_schemes(r2, houses, browser=None, fetch: bool = True) -> dict:
    """Scheme rows for every archived house-month that has none: read again from the raw files stored, else (with
    `fetch`) downloaded again from the house's page (stored raw as any fetch). Written only when they add up to the
    archived house rows (`add_up`): a file that differs from the one archived is reported, never mixed in. The house
    archive is not touched. Returns per house: months written, from raw or fetched, and why the others were not."""
    from clean_writer import list_keys, read_parquet
    arch = {k[len(ARCHIVE):] for k in list_keys(r2, ARCHIVE) if k.endswith('.parquet')}
    have = {k[len(SCHEME_ARCHIVE):] for k in list_keys(r2, SCHEME_ARCHIVE) if k.endswith('.parquet')}
    rep = {}
    for h in houses:
        todo = sorted(k.split('/')[0][6:] for k in arch - have if k.endswith(f'/{h.key}.parquet'))
        if not todo:
            continue
        r = rep.setdefault(h.key, {'from_raw': [], 'fetched': [], 'not_written': {}})
        got = {m: ('from_raw', rows) for m, rows in raw_rows(r2, h, set(todo)).items()}
        left = [m for m in todo if m not in got]
        if left and fetch:
            for res in collect_house(h, left, browser):
                if 'rows' in res:
                    got[res['month']] = ('fetched', res['rows'])
                else:
                    r['not_written'][res['month']] = res.get('why', 'not found')
        for m in todo:
            if m not in got:
                r['not_written'].setdefault(m, 'no raw file and not fetched')
                continue
            how, rows = got[m]
            hold = read_parquet(r2, f'{ARCHIVE}month={m}/{h.key}.parquet')
            sc = mf_holdings.scheme_holdings(rows, h.key, m, h.name)
            bad = add_up(sc, hold)
            if bad:
                r['not_written'][m] = f'{how}: {bad} ISINs do not add up to the archived house rows'
                continue
            put_schemes(r2, h, m, rows)
            r[how].append(m)
        print(json.dumps({h.key: r}))
    return rep


def amfi_list(month: str, tries: int = 3) -> tuple[pd.DataFrame, dict]:
    """AMFI's NAV report for the month-end's last working day (the latest of the last
    `tries` weekdays up to the month-end unless an earlier one lists over 1% more NAV lines), parsed
    (`mf_holdings.parse_amfi_nav`, `amfi_schemes`), and what was asked. Stored raw (raw_v2/amfi/nav_history/)."""
    import requests
    from raw_capture import capture
    end = mf_holdings.month_end(month)
    days = [d for d in pd.date_range(end - pd.Timedelta(days=10), end) if d.weekday() < 5][-tries:]
    best, info = None, {'month': month, 'asked': []}
    for d in reversed(days):
        url = mf_holdings.AMFI_NAV_URL.format(day=d.strftime('%d-%b-%Y'))
        try:
            r = requests.get(url, headers={'User-Agent': find.UA}, timeout=120)
        except Exception as exc:  # noqa: BLE001
            info['asked'].append({'day': str(d.date()), 'error': f'{type(exc).__name__}'})
            continue
        capture('amfi', 'nav_history', r.content, url=url, status=r.status_code, content_type=r.headers.get('Content-Type'),
                covers={'date': str(d.date()), 'month': month})
        nav = mf_holdings.parse_amfi_nav(r.content.decode('utf-8', 'replace')) if r.status_code == 200 else pd.DataFrame()
        info['asked'].append({'day': str(d.date()), 'status': r.status_code, 'nav_lines': int(len(nav))})
        # The latest day, unless an earlier one lists clearly more (a holiday or a half-filled day): 29 Oct 2026 had one
        # NAV line more than the 30th, which is the month-end's last working day.
        if len(nav) and (best is None or len(nav) > 1.01 * len(best[1])):
            best = (d, nav)
    if best is None:
        return pd.DataFrame(), info
    info['day'] = str(best[0].date())
    out = mf_holdings.amfi_schemes(best[1], {h.key: h.name for h in HOUSES}).assign(month=month)
    return out, info


def backfill_amfi(r2, months: list[str]) -> dict:
    """AMFI's scheme list for every archived month that has none yet (archive/amfi_schemes/month=YYYY-MM.parquet)."""
    from clean_writer import list_keys, put_parquet
    have = {k[len(AMFI_ARCHIVE):] for k in list_keys(r2, AMFI_ARCHIVE)}
    rep = {}
    for m in months:
        if f'month={m}.parquet' in have:
            continue
        df, info = amfi_list(m)
        if len(df):
            put_parquet(r2, f'{AMFI_ARCHIVE}month={m}.parquet', df)
        rep[m] = info
        print(json.dumps({'amfi': info}))
    return rep


def _concat(r2, prefix: str) -> pd.DataFrame:
    from clean_writer import list_keys, read_parquet
    frames = [read_parquet(r2, k) for k in sorted(k for k in list_keys(r2, prefix) if k.endswith('.parquet'))]
    frames = [f for f in frames if f is not None and len(f)]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def scheme_tables(h: pd.DataFrame, chg: pd.DataFrame, stock: pd.DataFrame, sc: pd.DataFrame, lists: pd.DataFrame,
                  amfi: pd.DataFrame, factors: dict) -> dict:
    """The scheme tables from the scheme archive: changes (every scheme, valued at the stock table's month price),
    per scheme-month, the site's slim moves, and the scheme count check; plus `checks`, per month the house-ISIN rows
    where the schemes' change does not add up to the house table's (0 expected)."""
    kinds = h.drop_duplicates('amc').set_index('amc')['kind'].to_dict() if 'kind' in h else {}
    out = {'checks': {}}
    parts = []
    months = sorted(sc['month'].unique()) if len(sc) else []
    for prev, cur in zip(months, months[1:]):
        x = mf_holdings.scheme_changes(sc[sc['month'] == cur], sc[sc['month'] == prev], factors.get(cur))
        if len(x):
            parts.append(x)
    s = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=mf_holdings.SCHEME_CHANGE_COLS)
    s = s.assign(house_kind=s['amc'].map(kinds).fillna('mf'))
    s = mf_holdings.value_scheme_changes(s, stock)
    if len(s) and len(chg):
        a = s.groupby(['month', 'amc', 'isin'])['change'].sum()
        pairs = set(zip(s['month'], s['amc']))   # house-months not read scheme by scheme are not compared
        c = chg[[(m, x) in pairs for m, x in zip(chg['month'], chg['amc'])]]
        d = a.sub(c.groupby(['month', 'amc', 'isin'])['change'].sum(), fill_value=0)
        out['checks'] = {m: int(n) for m, n in (d.abs() > ADD_UP_TOLERANCE).groupby(level=0).sum().items()}
    out['scheme_changes'] = s
    out['scheme_month'] = mf_holdings.scheme_month(s)
    out['scheme_moves'] = mf_holdings.scheme_moves(s)
    cov = mf_holdings.scheme_coverage(lists, amfi if len(amfi) else None, kinds)
    # House-months archived but not read scheme by scheme: listed, so the count check names them rather than skips them.
    seen = set(zip(cov['month'], cov['amc'])) if len(cov) else set()
    miss = h[['month', 'amc']].drop_duplicates()
    miss = miss[[(m, a) not in seen for m, a in zip(miss['month'], miss['amc'])]]
    if len(miss):
        cov = pd.concat([cov, miss.assign(house_kind=miss['amc'].map(kinds).fillna('mf'), flag='not read scheme by scheme')],
                        ignore_index=True)
    out['scheme_coverage'] = cov.sort_values(['month', 'amc']).reset_index(drop=True)
    return out


def rebuild(r2) -> dict:
    """The clean tables from every archived month."""
    from clean_writer import list_keys, put_parquet, read_parquet
    keys = sorted(k for k in list_keys(r2, ARCHIVE) if k.endswith('.parquet'))
    frames = [read_parquet(r2, k) for k in keys]
    h = pd.concat([f for f in frames if f is not None and len(f)], ignore_index=True) if frames else pd.DataFrame()
    if h.empty:
        return {'months': 0}
    h['kind'] = h['kind'].fillna('mf') if 'kind' in h else 'mf'   # months archived before pension funds were added
    put_parquet(r2, CLEAN['holdings'], h)
    months = sorted(h['month'].unique())
    acts = [read_parquet(r2, k) for k in ('clean/current/actions.parquet', 'clean/current/bse_actions.parquet')]
    acts = pd.concat([a for a in acts if a is not None and len(a)], ignore_index=True) if any(
        a is not None and len(a) for a in acts) else None
    ch, factors = [], {}
    for prev, cur in zip(months, months[1:]):
        f = factors[cur] = mf_holdings.share_factors(acts, prev, cur)
        ch.append(mf_holdings.changes(h[h['month'] == cur], h[h['month'] == prev], factors=f))
    chg = pd.concat(ch, ignore_index=True) if ch else pd.DataFrame()
    sh = read_parquet(r2, 'clean/current/shareholding.parquet')
    stock = pd.DataFrame()
    if len(chg):
        chg = mf_holdings.tag_house_kind(chg, h)
        put_parquet(r2, CLEAN['changes'], chg)
        stock = mf_holdings.stock_months(chg)
        # The company's shares on the month-end's basis (a split or bonus since its last filing applied): what "% of
        # the company" divides by, so a split is never read as a large share of the company bought.
        tot = mf_holdings.company_shares(sh, acts, months)
        stock = stock.merge(tot, on=['month', 'isin'], how='left')
        put_parquet(r2, CLEAN['stock'], stock)
    # Scheme by scheme, from the scheme archive (house-months archived before it existed are added by --schemes).
    sc, lists, amfi = _concat(r2, SCHEME_ARCHIVE), _concat(r2, SCHEME_LIST_ARCHIVE), _concat(r2, AMFI_ARCHIVE)
    schemes = {}
    if len(sc) or len(lists):
        schemes = scheme_tables(h, chg, stock, sc, lists, amfi, factors)
        for k in ('scheme_changes', 'scheme_month', 'scheme_moves', 'scheme_coverage'):
            put_parquet(r2, CLEAN[k], schemes[k])
    # How much of the industry the collected houses are: at each quarter-end month, their shares against the mutual-fund
    # shares each company filed in its shareholding pattern for that quarter end (never claimed, measured).
    cov = []
    if sh is not None and len(sh) and {'isin', 'quarter_end', 'mf_shares'} <= set(sh.columns):
        sh = sh.assign(_q=pd.to_datetime(sh['quarter_end'], errors='coerce').dt.to_period('M').astype(str))
        hm = h[h['kind'] == 'mf']   # mutual funds only: the filed figure is the mutual-fund holding, not pension funds'
        for mth in months:
            filed = sh[sh['_q'] == mth][['isin', 'mf_shares']]
            if len(filed) and (hm['month'] == mth).any():
                c = mf_holdings.coverage(hm[hm['month'] == mth], filed)
                cov.append({'month': mth, 'houses': int(hm.loc[hm['month'] == mth, 'amc'].nunique()), **c})
    if cov:
        put_parquet(r2, CLEAN['coverage'], pd.DataFrame(cov))
    sch = {}
    if schemes:
        sc_ch, cv = schemes['scheme_changes'], schemes['scheme_coverage']
        sch = {'scheme_change_rows': int(len(sc_ch)), 'site_move_rows': int(len(schemes['scheme_moves'])),
               'houses_by_month': sc_ch.groupby('month')['amc'].nunique().to_dict() if len(sc_ch) else {},
               'not_adding_up': schemes['checks'],
               'flagged': cv[cv['flag'].astype(str).ne('')][['month', 'amc', 'flag']].to_dict('records')[-80:]}
    return {'months': months, 'houses_by_month': h.groupby('month')['amc'].nunique().to_dict(), 'change_rows': int(len(chg)),
            'coverage': cov, 'schemes': sch}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--month', action='append', default=[], help='YYYY-MM, repeatable')
    ap.add_argument('--latest', type=int, default=0, help='the last N published month-ends')
    ap.add_argument('--house', action='append', default=[], help='house key, repeatable (default: all)')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--refetch', action='store_true', help='fetch a house-month again even when it is archived')
    ap.add_argument('--expand', help='print the months of a range spec and exit')
    ap.add_argument('--schemes', action='store_true',
                    help='archive scheme by scheme every archived house-month that is not yet: from raw, else fetched again')
    ap.add_argument('--no-amfi', action='store_true', help="do not read AMFI's scheme list for months that have none")
    a = ap.parse_args(argv)
    if a.expand is not None:
        print(' '.join(expand(a.expand)))
        return 0
    months = sorted(set(a.month) | set(latest_months(a.latest, datetime.now(IST).date()) if a.latest else set()))
    if not months:
        ap.error('give --month or --latest')
    houses = [BY_KEY[k] for k in a.house] if a.house else HOUSES
    r2 = None
    if not a.dry_run:
        from r2_writer import r2_client
        r2 = r2_client()
    browser = pw = None
    if any(h.render for h in houses):
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        import os
        exe = os.environ.get('CHROMIUM_PATH')   # a browser installed apart from the Python package (local runs)
        browser = pw.chromium.launch(**({'executable_path': exe, 'args': ['--no-sandbox']} if exe else {}))
    report = {'run_date': datetime.now(IST).date().isoformat(), 'months': months, 'houses': {}}
    have = set()
    if r2 is not None and not a.refetch:
        from clean_writer import list_keys
        have = {k[len(ARCHIVE):] for k in list_keys(r2, ARCHIVE)}
    try:
        for h in houses:
            todo = [mth for mth in months if f'month={mth}/{h.key}.parquet' not in have]
            if not todo:
                continue
            for res in collect_house(h, todo, browser):
                rows = res.pop('rows', None)
                if rows is not None:
                    hold = mf_holdings.holdings(rows, h.key, res['month']).assign(kind=h.kind)
                    res['isins'] = int(len(hold))
                    res['value_cr'] = round(float(hold['value_lakh'].sum()) / 100, 1)
                    sl = mf_holdings.scheme_list(rows, h.key, res['month'], h.name)
                    eq = sl[sl['equity_lines'].gt(0)]
                    res['schemes'] = {'read': int(len(sl)), 'equity': int(len(eq)),
                                      'active_equity': int((~eq['passive'].astype(bool)).sum())}
                    if r2 is not None:
                        from clean_writer import put_parquet
                        put_parquet(r2, f'{ARCHIVE}month={res["month"]}/{h.key}.parquet', hold)
                        put_schemes(r2, h, res['month'], rows)
                report['houses'].setdefault(h.key, []).append(res)
                print(json.dumps({k: v for k, v in res.items() if k not in ('parse',)}, default=str)[:400])
        if r2 is not None and a.schemes:
            report['schemes_backfill'] = backfill_schemes(r2, houses, browser)
        if r2 is not None and not a.no_amfi:
            from clean_writer import list_keys
            arch = sorted({k[len(ARCHIVE):].split('/')[0][6:] for k in list_keys(r2, ARCHIVE) if k.endswith('.parquet')})
            report['amfi'] = backfill_amfi(r2, arch)
    finally:
        if browser is not None:
            browser.close()
            pw.stop()
    if r2 is not None:
        from clean_writer import put
        report['clean'] = rebuild(r2)
        put(r2, f'clean/reports/mf_portfolios/{report["run_date"]}.json', json.dumps(report, indent=2, default=str).encode(),
            'application/json')
        print(json.dumps(report['clean'], default=str))
    found = sum(r['found'] for rs in report['houses'].values() for r in rs)
    total = sum(len(rs) for rs in report['houses'].values())
    print(f'found {found} of {total} house-months')
    return 0


if __name__ == '__main__':
    sys.exit(main())
