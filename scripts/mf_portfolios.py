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

Every line too (owner, 21 Nov 2026: nothing may exist only in raw): each file read is also kept line by line, debt,
money market, cash, derivatives, headings and totals included, in archive/mf_lines/month=YYYY-MM/{house}.parquet, and
each sheet not read (no ISIN and Quantity header) or file not read in archive/mf_sheets_skipped/ with the reason. Both
are merged by the file's sha256, so every raw file's lines stay. --lines fills them from the raw files already stored
(once for the months collected before; again, it reads only files not yet in them). The equity tables are unchanged.

The NPS pension fund managers (houses with kind='pension', keys nps_...) are collected the same way and kept in the
same tables, marked by kind, so the Funds page can keep them apart from mutual funds.

--dry-run fetches and parses and prints counts; it writes nothing to R2.

Houses are read side by side, each house a different site: the houses that use the browser one after another on the
main thread, the others in a pool of MF_HOUSE_WORKERS threads (default 6; 1 = one house at a time, as before). Each
house's own requests stay one after another with their pacing as before. The report lists houses in the houses
list's order whatever order they finish in; a line is printed per house-month as it finishes.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import threading
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
LINES_ARCHIVE = 'archive/mf_lines/'             # month=YYYY-MM/{house}.parquet: every line of every file (line_rows)
SKIPPED_ARCHIVE = 'archive/mf_sheets_skipped/'  # month=YYYY-MM/{house}.parquet: every sheet (or file) not read, and why
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


def uses_browser(house) -> bool:
    """A house read or downloaded in the shared browser: a rendered page, a browser download, or a list reader that
    drives a page (apis2.BROWSER_READERS)."""
    from collectors.mf_portfolios import apis2
    return bool(house.render or house.browser_fetch or house.api in apis2.BROWSER_READERS)


def house_workers() -> int:
    """How many plain-HTTP houses are read side by side (MF_HOUSE_WORKERS, default 6; 1 = one house at a time)."""
    import os
    try:
        return max(1, int(os.environ.get('MF_HOUSE_WORKERS', '6')))
    except ValueError:
        return 6


_PRINT = threading.Lock()


def _log(obj, limit: int | None = 400) -> None:
    """One whole line per call, from any thread (cut to `limit` characters)."""
    line = json.dumps(obj, default=str)
    with _PRINT:
        print(line[:limit] if limit else line, flush=True)


def run_houses(houses, work, workers: int | None = None) -> list:
    """work(house) for every house, once; returns the results in the order of `houses`, whatever order they finish in.

    Each house is a different site, so houses run side by side while each house's own requests stay one after another
    as before (no site is asked more often than now). Houses that use the shared browser (`uses_browser`) run on the
    calling thread, one after another, since Playwright's sync API answers only on the thread that started it; the
    others go to a pool of `workers` threads meanwhile. `work` reports its own failures; an exception it lets out is
    returned in that house's place (an Exception object), so one house never stops the others."""
    from concurrent.futures import ThreadPoolExecutor
    workers = house_workers() if workers is None else max(1, workers)
    out: dict = {}

    def one(h):
        try:
            return work(h)
        except Exception as exc:  # noqa: BLE001 - the house is reported, the run goes on
            return exc

    plain = [h for h in houses if not uses_browser(h)]
    if workers == 1:   # one house at a time, in order, as before
        for h in houses:
            out[h.key] = one(h)
    else:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix='mf-house') as pool:
            futs = {h.key: pool.submit(one, h) for h in plain}
            for h in houses:
                if uses_browser(h):
                    out[h.key] = one(h)
            for k, f in futs.items():
                out[k] = f.result()
    return [(h, out[h.key]) for h in houses]


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
        frames, reports, lines, skipped = [], [], [], []
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
                df, rep, ln, sk = file_lines(body, u, house.value_unit)
            except Exception as exc:  # noqa: BLE001
                try:   # the lines failed: the equity rows are still read exactly as before, the file listed as not read
                    df, rep = mf_holdings.parse_workbook(body, _name(u), house.value_unit)
                    ln, sk = None, not_read(body, u, exc, 'lines')
                except Exception as exc:  # noqa: BLE001
                    reports.append({'url': u, 'error': f'not parsed ({type(exc).__name__}: {exc})'[:200]})
                    skipped.append(not_read(body, u, exc))
                    continue
            rep['url'] = u
            reports.append(rep)
            frames.append(df)
            if ln is not None:
                lines.append(ln)
            skipped.append(sk)
        res['parse'] = reports
        if lines or skipped:   # every line of every file read, kept whether or not the month has equity
            res['lines'] = pd.concat(lines, ignore_index=True) if lines else _empty_lines()
            res['skipped_sheets'] = pd.concat(skipped, ignore_index=True)
            res['all_lines'] = int(len(res['lines']))
            res['sheets_skipped'] = int(len(res['skipped_sheets']))
        rows = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        if rows.empty or not mf_holdings.is_equity(rows['isin']).any():
            res['found'] = False
            if frames:
                res['why'] = 'file(s) read but no equity holding lines'
            else:   # each file's own answer (an HTTP 404 from the house's server, a parse error ...), as the report has it
                errs = sorted({r['error'] for r in reports if r.get('error')})
                res['why'] = 'no file downloaded and parsed' + (f' ({"; ".join(errs)})' if errs else '')
        else:
            res['rows'] = rows
        out.append(res)
    return out


def _house_failed(house, months: list[str], done: list[dict], exc: Exception) -> list[dict]:
    """The results so far, and every month not yet reported marked not found with the error: nothing filled in."""
    why = f'collector error ({type(exc).__name__}: {exc})'[:300]
    seen = {r['month'] for r in done}
    left = [{'house': house.key, 'month': m, 'found': False, 'why': why} for m in months if m not in seen]
    for res in left:
        _log(res)
    return done + left


def run_house(house, months: list[str], browser=None, r2=None) -> list[dict]:
    """Collect one house's months, archive each one found (unless `r2` is None, a dry run), print a line per month,
    and return the report's results for the house. An error stops this house only: the months it did not reach are
    reported with it (`_house_failed`)."""
    out: list[dict] = []
    try:
        for res in collect_house(house, months, browser):
            rows = res.pop('rows', None)
            keep_lines(r2, house, res)
            if rows is not None:
                hold = mf_holdings.holdings(rows, house.key, res['month']).assign(kind=house.kind)
                res['isins'] = int(len(hold))
                res['value_cr'] = round(float(hold['value_lakh'].sum()) / 100, 1)
                sl = mf_holdings.scheme_list(rows, house.key, res['month'], house.name)
                eq = sl[sl['equity_lines'].gt(0)]
                res['schemes'] = {'read': int(len(sl)), 'equity': int(len(eq)),
                                  'active_equity': int((~eq['passive'].astype(bool)).sum())}
                if r2 is not None:
                    from clean_writer import put_parquet
                    put_parquet(r2, f'{ARCHIVE}month={res["month"]}/{house.key}.parquet', hold)
                    put_schemes(r2, house, res['month'], rows)
            out.append(res)
            _log({k: v for k, v in res.items() if k not in ('parse',)})
    except Exception as exc:  # noqa: BLE001 - this house is reported, the others go on
        return _house_failed(house, months, out, exc)
    return out


def _name(url: str) -> str:
    return url.split('?')[0].rsplit('/', 1)[-1]


def _empty_lines() -> pd.DataFrame:
    return pd.DataFrame(columns=['file', 'blob_sha256', *mf_holdings.LINE_COLS])


def _empty_skipped() -> pd.DataFrame:
    return pd.DataFrame(columns=['file', 'blob_sha256', *mf_holdings.SKIPPED_COLS])


def file_lines(body: bytes, url: str, value_unit: str):
    """One downloaded (or raw) file parsed: `parse_workbook`'s rows and report as before, plus every line and every
    skipped sheet, each tagged with the file's name and the sha256 of its bytes (the raw blob's name)."""
    from insiders_clean.raw_store import sha256_hex
    df, rep, ln, sk = mf_holdings.parse_workbook_lines(body, _name(url), value_unit)
    tag = {'file': _name(url), 'blob_sha256': sha256_hex(body)}
    return (df, rep, ln.assign(**tag)[['file', 'blob_sha256', *mf_holdings.LINE_COLS]],
            sk.assign(**tag)[['file', 'blob_sha256', *mf_holdings.SKIPPED_COLS]])


def not_read(body: bytes, url: str, exc: Exception, what: str = 'file') -> pd.DataFrame:
    """A file that is not a workbook we can read: one row in the skipped table with the reason (no line made up)."""
    from insiders_clean.raw_store import sha256_hex
    return pd.DataFrame([{'file': _name(url), 'blob_sha256': sha256_hex(body), 'workbook': '', 'sheet': '',
                          'reason': f'{what} not read ({type(exc).__name__}: {exc})'[:300], 'rows': 0, 'filled_rows': 0}])


def keep_lines(r2, house, res: dict) -> None:
    """Take the lines and skipped sheets out of a collect_house result (the report keeps only their counts) and, unless
    `r2` is None (a dry run), archive them."""
    lines, skipped = res.pop('lines', None), res.pop('skipped_sheets', None)
    if r2 is not None and (lines is not None or skipped is not None):
        put_lines(r2, house, res['month'], lines, skipped)


def _merge_by_blob(old: pd.DataFrame | None, new: pd.DataFrame, shas: set) -> pd.DataFrame:
    """The stored rows of files not read this time, then this time's rows: a file read again replaces its own rows, and
    another file of the same month (a new version at a new address) keeps its own, so every raw file's lines stay."""
    if old is None or old.empty:
        return new.reset_index(drop=True)
    keep = old[~old['blob_sha256'].isin(shas)]
    return pd.concat([keep, new], ignore_index=True) if len(new) else keep.reset_index(drop=True)


def put_lines(r2, house, month: str, lines: pd.DataFrame | None, skipped: pd.DataFrame | None) -> dict:
    """Archive one house-month's lines (archive/mf_lines/) and skipped sheets (archive/mf_sheets_skipped/), merged by
    the file's sha256 with what is stored. Returns the rows each now holds."""
    from clean_writer import put_parquet, read_parquet
    lines = _empty_lines() if lines is None else lines
    skipped = _empty_skipped() if skipped is None else skipped
    shas = set(lines['blob_sha256']) | set(skipped['blob_sha256'])
    out = {}
    for prefix, df in ((LINES_ARCHIVE, lines), (SKIPPED_ARCHIVE, skipped)):
        key = f'{prefix}month={month}/{house.key}.parquet'
        df = df.assign(amc=house.key, month=month)
        df = df[['amc', 'month', *[c for c in df.columns if c not in ('amc', 'month')]]]
        merged = _merge_by_blob(read_parquet(r2, key), df, shas)
        for c in ('row', 'rows', 'filled_rows'):
            if c in merged:
                merged[c] = pd.to_numeric(merged[c]).astype('int64')
        put_parquet(r2, key, merged)
        out[prefix] = int(len(merged))
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


def add_up_detail(sc: pd.DataFrame, hold: pd.DataFrame, files: list | None = None) -> dict:
    """What differs when scheme rows do not add up (nothing is forced): ISINs on one side only, the shares ratio over
    the ISINs on both, how many ISINs are off by a whole multiple (a file read twice), and the files and schemes read."""
    a = sc.groupby('isin')['shares'].sum() if len(sc) else pd.Series(dtype=float)
    b = hold.groupby('isin')['shares'].sum() if hold is not None and len(hold) else pd.Series(dtype=float)
    both = a.index.intersection(b.index)
    ratio = (a[both] / b[both].where(b[both] != 0)).dropna()
    off = ratio[(ratio - 1).abs() > 1e-6]
    names = [u.split('?')[0].rsplit('/', 1)[-1] for u in files or []]
    return {'scheme_isins': int(len(a)), 'house_isins': int(len(b)), 'only_schemes': int(len(a.index.difference(b.index))),
            'only_house': int(len(b.index.difference(a.index))), 'both_differ': int(len(off)),
            'ratio_median': round(float(off.median()), 4) if len(off) else None,
            'whole_multiple': int(((off - off.round()).abs() < 1e-6).sum()) if len(off) else 0,
            'scheme_shares': float(a.sum()), 'house_shares': float(b.sum()),
            'files': len(names), 'file_names_twice': len(names) - len(set(names)),
            'schemes': int(sc['scheme_key'].nunique()) if len(sc) else 0}


RAW_FILES: dict = {}   # (house, month) -> the raw addresses raw_rows read, for add_up_detail


def raw_records(r2, house) -> list[dict]:
    """Every fetch record stored for this house's month-end files (raw_v2/amc/{house}/portfolio_month/fetches/)."""
    from concurrent.futures import ThreadPoolExecutor

    from clean_writer import get, list_keys
    keys = [k for k in list_keys(r2, f'raw_v2/amc/{house.key}/portfolio_month/fetches/') if k.endswith('.json')]
    if not keys:
        return []
    with ThreadPoolExecutor(16) as pool:
        return [json.loads(b) for b in pool.map(lambda k: get(r2, k), keys) if b]


def raw_rows(r2, house, months: set) -> dict:
    """{month: parsed rows} from the raw files already stored for this house (raw_v2/amc/{house}/portfolio_month/):
    the HTTP-200 fetches whose record covers the month, the latest fetch of each address, every one parsed as the
    collector parses it. A month with no such fetch is not in the result."""
    from clean_writer import get_blob
    recs = raw_records(r2, house)
    if not recs:
        return {}
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
            RAW_FILES[(house.key, m)] = list(urls)
    return out


def backfill_schemes(r2, houses, browser=None, fetch: bool = True) -> dict:
    """Scheme rows for every archived house-month that has none: read again from the raw files stored, else (with
    `fetch`) downloaded again from the house's page (stored raw as any fetch). Written only when they add up to the
    archived house rows (`add_up`): a file that differs from the one archived is reported, never mixed in. The house
    archive is not touched. Returns per house: months written, from raw or fetched, and why the others were not."""
    from clean_writer import list_keys
    arch = {k[len(ARCHIVE):] for k in list_keys(r2, ARCHIVE) if k.endswith('.parquet')}
    have = {k[len(SCHEME_ARCHIVE):] for k in list_keys(r2, SCHEME_ARCHIVE) if k.endswith('.parquet')}
    todo ={h.key: sorted(k.split('/')[0][6:] for k in arch - have if k.endswith(f'/{h.key}.parquet')) for h in houses}
    rep = {}
    # House by house side by side (run_houses): each house's raw reads, fetches and writes are its own.
    for h, r in run_houses([h for h in houses if todo[h.key]],
                           lambda h: _backfill_house(r2, h, todo[h.key], browser, fetch)):
        if isinstance(r, Exception):
            why = f'collector error ({type(r).__name__}: {r})'[:300]
            r = {'from_raw': [], 'fetched': [], 'not_written': {m: why for m in todo[h.key]}}
            _log({h.key: r})
        rep[h.key] = r
    return rep


def _backfill_house(r2, h, todo: list[str], browser=None, fetch: bool = True) -> dict:
    """backfill_schemes for one house's months; returns its report entry (and prints it). An error stops this house
    only: the months it had not written are reported with it."""
    r = {'from_raw': [], 'fetched': [], 'not_written': {}}
    try:
        _backfill_months(r2, h, todo, browser, fetch, r)
    except Exception as exc:  # noqa: BLE001 - this house is reported, the others go on
        why = f'collector error ({type(exc).__name__}: {exc})'[:300]
        for m in todo:
            if m not in r['from_raw'] and m not in r['fetched']:
                r['not_written'].setdefault(m, why)
    _log({h.key: r}, limit=None)
    return r


def _backfill_months(r2, h, todo: list[str], browser, fetch: bool, r: dict) -> None:
    from clean_writer import read_parquet
    got ={m: ('from_raw', rows) for m, rows in raw_rows(r2, h, set(todo)).items()}
    left = [m for m in todo if m not in got]
    if left and fetch:
        for res in collect_house(h, left, browser):
            keep_lines(r2, h, res)
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
        if bad and how == 'from_raw' and fetch:
            # The raw store can hold more than the archived set (a file fetched again at a new address, say):
            # the house's current files are the other copy; kept only if they add up, as any fetch.
            r.setdefault('differs', {})[f'{m} from_raw'] = add_up_detail(sc, hold, RAW_FILES.get((h.key, m)))
            res = next(iter(collect_house(h, [m], browser)), {})
            if res:
                keep_lines(r2, h, res)
            if 'rows' in res:
                how, rows = 'fetched', res['rows']
                sc = mf_holdings.scheme_holdings(rows, h.key, m, h.name)
                bad2 = add_up(sc, hold)
                if bad2:
                    r['differs'][f'{m} fetched'] = add_up_detail(sc, hold, res.get('files'))
                    bad = f'{bad} (from raw), {bad2} (fetched again)'
                else:
                    bad = 0
        if bad:
            r['not_written'][m] = f'{how}: {bad} ISINs do not add up to the archived house rows'
            if not any(k.startswith(m) for k in r.get('differs', {})):
                r.setdefault('differs', {})[m] = add_up_detail(sc, hold, RAW_FILES.get((h.key, m)) if how == 'from_raw' else None)
            continue
        put_schemes(r2, h, m, rows)
        r[how].append(m)


def backfill_lines(r2, houses) -> dict:
    """Every line of every raw file already stored (raw_v2/amc/{house}/portfolio_month/: HTTP 200, any month a fetch
    record covers, each distinct file once) into archive/mf_lines/ and archive/mf_sheets_skipped/, for files whose
    sha256 is in neither yet: run once to fill the months collected before the lines archive existed; run again, it
    reads only what is new. Nothing is downloaded. Returns per house: months written, files read, lines, sheets
    skipped, files not read, blobs missing."""
    rep = {}
    for h, r in run_houses(list(houses), lambda h: _backfill_lines_house(r2, h)):
        if isinstance(r, Exception):
            r = {'error': f'{type(r).__name__}: {r}'[:300]}
            _log({h.key: r}, limit=None)
        rep[h.key] = r
    return rep


def _backfill_lines_house(r2, h) -> dict:
    from clean_writer import get_blob, read_parquet
    r = {'months': [], 'files_read': 0, 'lines': 0, 'sheets_skipped': 0, 'files_not_read': 0, 'blobs_missing': 0}
    by: dict = {}
    for rec in sorted(raw_records(r2, h), key=lambda x: x.get('fetched_at_utc', '')):
        m = (rec.get('covers') or {}).get('month')
        if m and rec.get('http_status') == 200 and not rec.get('content_check') and rec.get('blob_key'):
            sha = rec.get('sha256') or rec['blob_key'].rsplit('/', 1)[-1].split('.')[0]
            by.setdefault(m, {}).setdefault(sha, rec)    # one read per distinct file (same bytes, one blob)
    for m in sorted(by):
        have = set()
        for prefix in (LINES_ARCHIVE, SKIPPED_ARCHIVE):
            old = read_parquet(r2, f'{prefix}month={m}/{h.key}.parquet')
            if old is not None and len(old):
                have |= set(old['blob_sha256'])
        todo = {sha: rec for sha, rec in by[m].items() if sha not in have}
        lines, skipped = [], []
        for sha, rec in todo.items():
            body = get_blob(r2, rec['blob_key'])
            if body is None:
                r['blobs_missing'] += 1
                continue
            r['files_read'] += 1
            try:
                _, _, ln, sk = file_lines(body, rec.get('url') or '', h.value_unit)
                lines.append(ln)
            except Exception as exc:  # noqa: BLE001 - a file that is not a workbook is recorded with the reason
                sk = not_read(body, rec.get('url') or '', exc)
                r['files_not_read'] += 1
            skipped.append(sk)
        if not skipped:
            continue
        ln = pd.concat(lines, ignore_index=True) if lines else _empty_lines()
        sk = pd.concat(skipped, ignore_index=True)
        put_lines(r2, h, m, ln, sk)
        r['months'].append(m)
        r['lines'] += int(len(ln))
        r['sheets_skipped'] += int(len(sk))
    _log({h.key: r}, limit=None)
    return r


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
    ap.add_argument('--lines', action='store_true',
                    help='archive every line of every raw file already stored that is not yet (archive/mf_lines/)')
    ap.add_argument('--no-amfi', action='store_true', help="do not read AMFI's scheme list for months that have none")
    a = ap.parse_args(argv)
    if a.expand is not None:
        print(' '.join(expand(a.expand)))
        return 0
    months = sorted(set(a.month) | set(latest_months(a.latest, datetime.now(IST).date()) if a.latest else set()))
    if not months:
        ap.error('give --month or --latest')
    houses = [BY_KEY[k] for k in dict.fromkeys(a.house)] if a.house else HOUSES
    r2 = None
    if not a.dry_run:
        from r2_writer import r2_client
        r2 = r2_client()
    # One browser for the whole run, started on this thread and shared with the list readers that drive a page (apis2):
    # Playwright's sync API allows one started instance per thread and answers only on that thread, so every house
    # that uses it runs here (run_houses) while the plain-HTTP houses are read side by side in a pool.
    browser = find.shared_browser() if any(h.render or h.browser_fetch for h in houses) else None
    report = {'run_date': datetime.now(IST).date().isoformat(), 'months': months, 'houses': {}}
    have = set()
    if r2 is not None and not a.refetch:
        from clean_writer import list_keys
        have = {k[len(ARCHIVE):] for k in list_keys(r2, ARCHIVE)}
    try:
        todo = {h.key: [mth for mth in months if f'month={mth}/{h.key}.parquet' not in have] for h in houses}
        for h, results in run_houses([h for h in houses if todo[h.key]],
                                     lambda h: run_house(h, todo[h.key], browser, r2)):
            if isinstance(results, Exception):   # run_house reports its own failures; this is a safety net
                results = _house_failed(h, todo[h.key], [], results)
            if results:
                report['houses'][h.key] = results
        if r2 is not None and a.schemes:
            report['schemes_backfill'] = backfill_schemes(r2, houses, browser)
        if r2 is not None and a.lines:
            report['lines_backfill'] = backfill_lines(r2, houses)
        if r2 is not None and not a.no_amfi:
            from clean_writer import list_keys
            arch = sorted({k[len(ARCHIVE):].split('/')[0][6:] for k in list_keys(r2, ARCHIVE) if k.endswith('.parquet')})
            report['amfi'] = backfill_amfi(r2, arch)
    finally:
        find.close_browser()
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
