"""Mutual fund month-end portfolios: find, fetch, store raw, parse, archive, rebuild the clean tables.

    python scripts/mf_portfolios.py --month 2026-10 [--month 2026-09 ...] [--house sbi ...] [--dry-run]
    python scripts/mf_portfolios.py --latest 2          # the last two published month-ends (by the 10th rule)

For each fund house (collectors/mf_portfolios/houses.py) and month: find the file on its disclosure page, download
it, save the exact bytes for the write-once raw layer (raw_v2/amc/{house}/portfolio_month/, via raw_capture and the
raw_flush step), parse it (insiders_clean/mf_holdings.py) and keep

    archive/mf_holdings/month=YYYY-MM/{house}.parquet     one row per ISIN the house held at that month-end

A house or month that is not found or does not parse is reported with the reason and left out; nothing is filled in.
Then the clean tables are rebuilt from every archived month:

    clean/current/mf_holdings.parquet     house, month, ISIN, shares, value (Rs lakh), schemes
    clean/current/mf_changes.parquet      house, month, ISIN, shares before and after, change, kind (new/added/cut/exit/held)
    clean/current/mf_stock_month.parquet  month, ISIN: houses adding / cutting / new / exiting, net shares
    clean/reports/mf_portfolios/{run date}.json   per house and month: found, file, sheets read, lines, ISINs, why not

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
         'stock': 'clean/current/mf_stock_month.parquet'}
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


def _download(url: str, timeout: int = 180) -> tuple[bytes, str | None, int]:
    import requests
    r = requests.get(url, headers={'User-Agent': find.UA}, timeout=timeout)
    return r.content, r.headers.get('Content-Type'), r.status_code


def collect_house(house, months: list[str], browser=None) -> list[dict]:
    """One result per month: {'house', 'month', 'found', 'files', 'rows' (DataFrame) or 'why'}."""
    from raw_capture import capture
    out = []
    links = []
    if house.api is None:
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
        urls = find.candidates(links, month, house)
        res = {'house': house.key, 'month': month, 'found': bool(urls), 'links_on_page': len(links), 'files': urls}
        if not urls:
            res['why'] = 'no file for the month on the page'
            out.append(res)
            continue
        frames, reports = [], []
        for u in urls:
            try:
                body, ctype, status = _download(u)
            except Exception as exc:  # noqa: BLE001
                reports.append({'url': u, 'error': f'{type(exc).__name__}: {exc}'[:200]})
                continue
            capture('amc', f'{house.key}/portfolio_month', body, url=u, status=status, content_type=ctype,
                    covers={'month': month})
            if status != 200:
                reports.append({'url': u, 'error': f'HTTP {status}'})
                continue
            try:
                df, rep = mf_holdings.parse_workbook(body, u.split('?')[0].rsplit('/', 1)[-1])
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
    put_parquet(r2, CLEAN['holdings'], h)
    months = sorted(h['month'].unique())
    ch = []
    for prev, cur in zip(months, months[1:]):
        ch.append(mf_holdings.changes(h[h['month'] == cur], h[h['month'] == prev], factors=None))
    chg = pd.concat(ch, ignore_index=True) if ch else pd.DataFrame()
    if len(chg):
        put_parquet(r2, CLEAN['changes'], chg)
        stock = pd.concat([mf_holdings.by_stock(chg[chg['month'] == m]).assign(month=m) for m in chg['month'].unique()],
                          ignore_index=True)
        put_parquet(r2, CLEAN['stock'], stock)
    return {'months': months, 'houses_by_month': h.groupby('month')['amc'].nunique().to_dict(), 'change_rows': int(len(chg))}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--month', action='append', default=[], help='YYYY-MM, repeatable')
    ap.add_argument('--latest', type=int, default=0, help='the last N published month-ends')
    ap.add_argument('--house', action='append', default=[], help='house key, repeatable (default: all)')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args(argv)
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
    try:
        for h in houses:
            for res in collect_house(h, months, browser):
                rows = res.pop('rows', None)
                if rows is not None:
                    hold = mf_holdings.holdings(rows, h.key, res['month'])
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
