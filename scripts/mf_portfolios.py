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
    clean/reports/mf_portfolios/{run date}.json   per house and month: found, file, sheets read, lines, ISINs, why not

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
CLEAN = {'holdings': 'clean/current/mf_holdings.parquet', 'changes': 'clean/current/mf_changes.parquet',
         'stock': 'clean/current/mf_stock_month.parquet', 'coverage': 'clean/current/mf_coverage.parquet'}
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
    ch = []
    for prev, cur in zip(months, months[1:]):
        f = mf_holdings.share_factors(acts, prev, cur)
        ch.append(mf_holdings.changes(h[h['month'] == cur], h[h['month'] == prev], factors=f))
    chg = pd.concat(ch, ignore_index=True) if ch else pd.DataFrame()
    if len(chg):
        chg = mf_holdings.tag_house_kind(chg, h)
        put_parquet(r2, CLEAN['changes'], chg)
        put_parquet(r2, CLEAN['stock'], mf_holdings.stock_months(chg))
    # How much of the industry the collected houses are: at each quarter-end month, their shares against the mutual-fund
    # shares each company filed in its shareholding pattern for that quarter end (never claimed, measured).
    sh = read_parquet(r2, 'clean/current/shareholding.parquet')
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
    return {'months': months, 'houses_by_month': h.groupby('month')['amc'].nunique().to_dict(), 'change_rows': int(len(chg)),
            'coverage': cov}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--month', action='append', default=[], help='YYYY-MM, repeatable')
    ap.add_argument('--latest', type=int, default=0, help='the last N published month-ends')
    ap.add_argument('--house', action='append', default=[], help='house key, repeatable (default: all)')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--refetch', action='store_true', help='fetch a house-month again even when it is archived')
    ap.add_argument('--expand', help='print the months of a range spec and exit')
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
                    if r2 is not None:
                        from clean_writer import put_parquet
                        put_parquet(r2, f'{ARCHIVE}month={res["month"]}/{h.key}.parquet', hold)
                report['houses'].setdefault(h.key, []).append(res)
                print(json.dumps({k: v for k, v in res.items() if k not in ('parse',)}, default=str)[:400])
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
