"""Nightly: market-wide flows (FPI, DII, mutual funds) -> clean/current/market_flows.parquet.

    python scripts/market_flows.py [--dry-run] [--from YYYY-MM-DD --to YYYY-MM-DD] [--sources nse,nsdl,sebi,sectors]

Sources and their fields are in insiders_clean/market_flows.py; each was fetched from this code's own requests on
19 Nov 2026. Each answer is saved byte for byte for the write-once raw layer (scripts/raw_capture.py; the
nightly's raw_flush step stores it in raw_v2/{nse|nsdl|sebi}/...), parsed, and kept in

    archive/market_flows/{nse|nsdl|sebi}/year=YYYY.parquet     one row per date, segment and category
    archive/market_flows/nsdl_sector/year=YYYY.parquet         one row per fortnight and sector

A later fetch of the same day replaces it. Then clean/current/market_flows.parquet and
clean/current/fpi_sector_flows.parquet are rebuilt from the archive, and clean/reports/market_flows/{date}.json
says what each source gave.

Nightly (no dates): NSE's two answers (the latest day only: NSE keeps no history behind them), NSDL's and SEBI's
month pages for this month and the last (both pages run from the 1st to the date asked, so a missed night is
filled by the next), and NSDL's newest fortnightly sector report not yet stored. With --from/--to: NSDL and SEBI
month by month and the sector reports in the range (NSE has no history; it is skipped with a note).
A refusal (401/403/429, or SEBI's firewall page, 530) stops that source for the run; the others go on.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from html import unescape
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from collectors.nse_events.client import BASE as NSE_BASE, Blocked, NSEClient  # noqa: E402
from insiders_clean import market_flows as M  # noqa: E402
from raw_capture import capture  # noqa: E402

NSE_URLS = {'fiidiiTradeReact': f'{NSE_BASE}/api/fiidiiTradeReact', 'fiidiiTradeNse': f'{NSE_BASE}/api/fiidiiTradeNse'}
NSE_DATASET = {'fiidiiTradeReact': 'fiidii_all', 'fiidiiTradeNse': 'fiidii_nse'}
NSDL = 'https://www.fpi.nsdl.co.in'
NSDL_ARCHIVE = f'{NSDL}/web/Reports/Archive.aspx'
NSDL_SECTOR_LIST = f'{NSDL}/web/Reports/FPI_Fortnightly_Selection.aspx'
SEBI_MF = 'https://www.sebi.gov.in/sebiweb/other/OtherAction.do?doMfdTrendsSearch=yes'
ARCHIVE = 'archive/market_flows/'
CLEAN_KEY = 'clean/current/market_flows.parquet'
SECTOR_KEY = 'clean/current/fpi_sector_flows.parquet'
WINDOW_START = '2025-10-08'    # insiders_clean/pipeline.py: the product window
SOURCES = ('nse', 'nsdl', 'sebi', 'sectors')
IST = timezone(timedelta(hours=5, minutes=30))
BROWSER = {'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'),
           'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
           'Accept-Language': 'en-US,en;q=0.9'}


class Web:
    """NSDL and SEBI: one browser identity (NSDL closes the connection on a bare client), 2-4 s between calls,
    retries on network errors and 5xx, and a hard stop on a refusal."""

    def __init__(self, pause=(2.0, 4.0), retries=3, session=None, sleep=time.sleep):
        self.s = session or requests.Session()
        self.s.headers.update(BROWSER)
        self.pause, self.retries, self.sleep, self.calls = pause, retries, sleep, 0

    def fetch(self, method: str, url: str, **kw) -> requests.Response:
        last = None
        for _ in range(self.retries):
            if self.calls:
                self.sleep(random.uniform(*self.pause))
            self.calls += 1
            try:
                r = self.s.request(method, url, timeout=60, **kw)
            except requests.RequestException as exc:
                last = exc
                continue
            if r.status_code in (401, 403, 429, 530):
                raise Blocked(f'HTTP {r.status_code} for {url}')
            if r.status_code >= 500:
                last = RuntimeError(f'HTTP {r.status_code}')
                continue
            if r.status_code != 200:
                raise RuntimeError(f'HTTP {r.status_code} for {url}')
            return r
        raise RuntimeError(f'{url}: gave up after {self.retries} tries ({last})')


def hidden_fields(html: str, names=None) -> dict:
    """The form's hidden inputs (ASP.NET view state, SEBI's token) as the page gave them."""
    out = {}
    for tag in re.findall(r'<input[^>]*>', html):
        n = re.search(r'name="([^"]+)"', tag)
        if not n or 'type="hidden"' not in tag.replace("'", '"'):
            continue
        if names is None or n.group(1) in names:
            v = re.search(r'value="([^"]*)"', tag)
            out[n.group(1)] = unescape(v.group(1)) if v else ''
    return out


def month_ends(start: date, end: date) -> list[date]:
    """The last day of each month from start's to end's, the final one clipped to `end`."""
    out, d = [], date(start.year, start.month, 1)
    while d <= end:
        nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
        out.append(min(nxt - timedelta(days=1), end))
        d = nxt
    return out


# ---- fetchers: each returns parsed rows and notes; raw bytes are captured on arrival -------------

def fetch_nse(nse: NSEClient, day: date, report: dict) -> pd.DataFrame:
    frames = []
    nse.warm_up()
    for name, url in NSE_URLS.items():
        try:
            j = nse.get(url)
        except Blocked as exc:
            report['notes'].append(f'nse: refused ({exc}); no further NSE calls')
            break
        except Exception as exc:  # noqa: BLE001 -- one endpoint failing must not stop the other
            report['notes'].append(f'nse {name}: fetch failed ({type(exc).__name__}: {exc})')
            continue
        try:
            df = M.parse_nse(j, name)
        except Exception as exc:  # noqa: BLE001
            report['notes'].append(f'nse {name}: not parsed ({type(exc).__name__}: {exc})')
            continue
        frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=M.COLUMNS)


def _nse_capture(nse: NSEClient, day: date):
    def hook(url, r):
        name = url.rsplit('/', 1)[-1].split('?')[0]
        capture('nse', NSE_DATASET.get(name, name), r.content, url=url, status=r.status_code,
                content_type=r.headers.get('Content-Type'), covers={'day': day.isoformat()})
    nse.on_response = hook


def fetch_nsdl(web: Web, months: list[date], report: dict) -> pd.DataFrame:
    frames = []
    for to in months:
        try:
            page = web.fetch('GET', NSDL_ARCHIVE)
            form = hidden_fields(page.text)
            form.update({'__EVENTTARGET': 'btnSubmit1', '__EVENTARGUMENT': '', 'hdnFlag': '', 'HdnValexceldata': '',
                         'hdnDate': to.strftime('%d-%b-%Y'), 'txtDate': to.strftime('%d-%b-%Y')})
            r = web.fetch('POST', NSDL_ARCHIVE, data=form, headers={'Referer': NSDL_ARCHIVE, 'Origin': NSDL})
        except Blocked as exc:
            report['notes'].append(f'nsdl: refused ({exc}); no further NSDL calls')
            break
        except Exception as exc:  # noqa: BLE001
            report['notes'].append(f'nsdl {to:%b %Y}: fetch failed ({type(exc).__name__}: {exc})')
            continue
        capture('nsdl', 'fpi_daily', r.content, url=NSDL_ARCHIVE, params={'hdnDate': to.strftime('%d-%b-%Y')},
                status=r.status_code, content_type=r.headers.get('Content-Type'),
                covers={'from': to.replace(day=1).isoformat(), 'to': to.isoformat()})
        notes = []
        try:
            df = M.parse_nsdl_daily(r.text, notes)
        except Exception as exc:  # noqa: BLE001
            report['notes'].append(f'nsdl {to:%b %Y}: not parsed ({type(exc).__name__}: {exc})')
            continue
        report['notes'] += notes
        if df.attrs.get('short'):
            report.setdefault('short', []).append(f'nsdl {to:%b %Y}')
        frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=M.COLUMNS)


def fetch_sebi(web: Web, months: list[date], report: dict) -> pd.DataFrame:
    frames = []
    for to in months:
        try:
            page = web.fetch('GET', SEBI_MF)
            form = hidden_fields(page.text, names=('currdate', 'org.apache.struts.taglib.html.TOKEN'))
            form['date'] = to.strftime('%d-%m-%Y')
            r = web.fetch('POST', SEBI_MF, data=form, headers={'Referer': SEBI_MF, 'Origin': 'https://www.sebi.gov.in'})
        except Blocked as exc:
            report['notes'].append(f'sebi: refused ({exc}); no further SEBI calls')
            break
        except Exception as exc:  # noqa: BLE001
            report['notes'].append(f'sebi {to:%b %Y}: fetch failed ({type(exc).__name__}: {exc})')
            continue
        capture('sebi', 'mf_trends', r.content, url=SEBI_MF, params={'date': form['date']}, status=r.status_code,
                content_type=r.headers.get('Content-Type'),
                covers={'from': to.replace(day=1).isoformat(), 'to': to.isoformat()})
        notes = []
        try:
            df = M.parse_sebi(r.text, notes)
        except Exception as exc:  # noqa: BLE001
            report['notes'].append(f'sebi {to:%b %Y}: not parsed ({type(exc).__name__}: {exc})')
            continue
        report['notes'] += notes
        if df.attrs.get('short'):
            report.setdefault('short', []).append(f'sebi {to:%b %Y}')
        frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=M.COLUMNS)


def fetch_sectors(web: Web, start: date | None, end: date, have: set, report: dict, newest: int = 2) -> pd.DataFrame:
    """Sector reports with a fortnight end in [start, end]; nightly (start None) the newest `newest` not in `have`."""
    try:
        page = web.fetch('GET', NSDL_SECTOR_LIST)
    except Exception as exc:  # noqa: BLE001
        report['notes'].append(f'sectors: list not fetched ({type(exc).__name__}: {exc})')
        return pd.DataFrame(columns=M.SECTOR_COLUMNS)
    capture('nsdl', 'fpi_sector_list', page.content, url=NSDL_SECTOR_LIST, status=page.status_code,
            content_type=page.headers.get('Content-Type'), covers={'day': end.isoformat()})
    options = [(d, p) for d, p in M.sector_options(page.text) if d <= end]
    if start is not None:
        todo = [(d, p) for d, p in options if d >= start]
    else:
        todo = [(d, p) for d, p in options[:newest] if d not in have]
    report['sector_reports_listed'] = len(options)
    frames = []
    for d, path in todo:
        url = NSDL + path
        try:
            r = web.fetch('GET', url)
        except Blocked as exc:
            report['notes'].append(f'sectors: refused ({exc}); no further NSDL calls')
            break
        except Exception as exc:  # noqa: BLE001
            report['notes'].append(f'sectors {d}: fetch failed ({type(exc).__name__}: {exc})')
            continue
        capture('nsdl', 'fpi_sectors', r.content, url=url, status=r.status_code,
                content_type=r.headers.get('Content-Type'), covers={'fortnight_end': d.isoformat()})
        try:
            df = M.parse_nsdl_sectors(r.text)
        except Exception as exc:  # noqa: BLE001
            report['notes'].append(f'sectors {d}: not parsed ({type(exc).__name__}: {exc})')
            continue
        if df['fortnight_end'].iloc[0].date() != d:
            report['notes'].append(f'sectors {d}: the report is for {df["fortnight_end"].iloc[0]:%d %b %Y}; kept by its own date')
        frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=M.SECTOR_COLUMNS)


# ---- archive and clean ------------------------------------------------------

def store(r2, source: str, new: pd.DataFrame, keys, date_col: str = 'date') -> pd.DataFrame | None:
    """Merge `new` into its year partitions (a later fetch of a key wins); return every archived row."""
    from clean_writer import list_keys, put_parquet, read_parquet
    prefix = f'{ARCHIVE}{source}/'
    if new is not None and not new.empty:
        new = new.assign(fetched_at=pd.Timestamp.now(tz='UTC').tz_localize(None))
        for year, part in new.groupby(pd.to_datetime(new[date_col]).dt.year):
            key = f'{prefix}year={year}.parquet'
            put_parquet(r2, key, M.merge(read_parquet(r2, key), part.reset_index(drop=True), keys))
    frames = [read_parquet(r2, k) for k in sorted(list_keys(r2, prefix)) if k.endswith('.parquet')]
    frames = [f for f in frames if f is not None and not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else None


def build_sectors(archive: pd.DataFrame | None) -> pd.DataFrame:
    if archive is None or archive.empty:
        return pd.DataFrame(columns=M.SECTOR_COLUMNS)
    df = archive.copy()
    df['fortnight_end'] = pd.to_datetime(df['fortnight_end'])
    df = df[df['fortnight_end'] >= pd.Timestamp(WINDOW_START)].drop_duplicates(['fortnight_end', 'sector'], keep='last')
    return df[M.SECTOR_COLUMNS].sort_values(['fortnight_end', 'sector'], ascending=[False, True]).reset_index(drop=True)


def latest_by_source(df: pd.DataFrame) -> dict:
    if df is None or df.empty:
        return {}
    return {s: str(pd.to_datetime(g['date']).max().date()) for s, g in df.groupby('source')}


def collect(day: date, start: date | None, end: date, sources, report: dict, have_sectors=frozenset(),
            nse: NSEClient | None = None, web: Web | None = None) -> dict:
    """Fetch and parse every source asked for. Returns {source: rows}."""
    out = {}
    web = web or Web()
    if 'nse' in sources:
        if start is not None and end < day:
            report['notes'].append('nse: no history (NSE answers the latest day only); skipped for a past range')
        else:
            nse = nse or NSEClient()
            _nse_capture(nse, day)
            out['nse'] = fetch_nse(nse, day, report)
            report['nse_calls'] = nse.calls
    months = month_ends(start, end) if start is not None else month_ends((end.replace(day=1) - timedelta(days=1)), end)
    if 'nsdl' in sources:
        out['nsdl'] = fetch_nsdl(web, months, report)
    if 'sebi' in sources:
        out['sebi'] = fetch_sebi(web, months, report)
    if 'sectors' in sources:
        out['nsdl_sector'] = fetch_sectors(web, start, end, set(have_sectors), report)
    report['web_calls'] = web.calls
    report['parsed'] = {k: int(len(v)) for k, v in out.items()}
    report['latest'] = {k: (str(pd.to_datetime(v[col]).max().date()) if len(v) else None)
                        for k, v in out.items() for col in ['fortnight_end' if k == 'nsdl_sector' else 'date']}
    return out


def run(r2, day: date, start: date | None, end: date, sources, nse: NSEClient | None = None,
        web: Web | None = None) -> dict:
    from clean_writer import list_keys, put, put_parquet, read_parquet
    report = {'run_date': day.isoformat(), 'from': start.isoformat() if start else None, 'to': end.isoformat(),
              'notes': []}
    have = set()
    if 'sectors' in sources and start is None:
        frames = [read_parquet(r2, k) for k in list_keys(r2, f'{ARCHIVE}nsdl_sector/') if k.endswith('.parquet')]
        have = {d.date() for f in frames if f is not None for d in pd.to_datetime(f['fortnight_end']).unique()}
    got = collect(day, start, end, sources, report, have, nse=nse, web=web)
    flows = []
    for source in ('nse', 'nsdl', 'sebi'):
        hist = store(r2, source, got.get(source), M.COLUMNS[:4])
        if hist is not None:
            flows.append(hist)
    table = M.build(pd.concat(flows, ignore_index=True) if flows else None, WINDOW_START)
    put_parquet(r2, CLEAN_KEY, table)
    sec_hist = store(r2, 'nsdl_sector', got.get('nsdl_sector'), ('fortnight_end', 'sector'), 'fortnight_end')
    sectors = build_sectors(sec_hist)
    put_parquet(r2, SECTOR_KEY, sectors)
    report['clean'] = {'rows': int(len(table)), 'latest': latest_by_source(table),
                       'days': {s: int(g['date'].nunique()) for s, g in table.groupby('source')},
                       'sector_rows': int(len(sectors)),
                       'sector_latest': str(sectors['fortnight_end'].max().date()) if len(sectors) else None}
    put(r2, f'clean/reports/market_flows/{day.isoformat()}.json', json.dumps(report, indent=2, default=str).encode(),
        'application/json')
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--dry-run', action='store_true', help='fetch and parse, print counts, write nothing to R2')
    ap.add_argument('--from', dest='start', help='backfill from this day (YYYY-MM-DD)')
    ap.add_argument('--to', dest='end', help='backfill to this day (default today)')
    ap.add_argument('--sources', default=','.join(SOURCES), help=f'comma list of {",".join(SOURCES)}')
    a = ap.parse_args(argv)
    td = os.environ.get('TARGET_DATE', '').strip()
    day = date.fromisoformat(td) if td else datetime.now(IST).date()
    start = date.fromisoformat(a.start) if a.start else None
    end = min(date.fromisoformat(a.end), day) if a.end else day
    if start is not None and start > end:
        ap.error('--from is after --to')
    sources = [s.strip() for s in a.sources.split(',') if s.strip()]
    if set(sources) - set(SOURCES):
        ap.error(f'unknown source in {a.sources}')
    if a.dry_run:
        report = {'run_date': day.isoformat(), 'notes': []}
        collect(day, start, end, sources, report)
    else:
        from r2_writer import r2_client
        report = run(r2_client(), day, start, end, sources)
    print(json.dumps({k: v for k, v in report.items() if k != 'notes'}, default=str))
    for n in report['notes']:
        print(f'  note: {n}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
