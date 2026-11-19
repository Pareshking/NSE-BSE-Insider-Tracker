"""Industry classification (four official levels) -> clean/current/industry.parquet.

    python scripts/industry.py fetch --out DIR [--limit 400] [--minutes 75] [--sources nse,bse]
    python scripts/industry.py build --in DIR
    python scripts/industry.py probe --out DIR --nse ABB,INFY --bse 500002      (no R2: fetch, print, keep raw)

Sources and fields: insiders_clean/industry.py. Every answer is saved byte for byte for the write-once raw layer the
moment it arrives (scripts/raw_capture.py; scripts/raw_flush.py stores it in raw_v2/nse/quote_equity/,
raw_v2/bse/comheadernew/ and raw_v2/bse/scrip_list/), then parsed.

`fetch` reads R2 only: the NSE symbols of clean/current/securities.parquet, BSE's list of active equity scrips (one
call), and archive/industry/{nse,bse}.parquet to see what is due. Due = never fetched, then the oldest answers past
their age (an `ok` after 30 days, anything else after 7), at most `--limit` per exchange and within `--minutes`.
BSE is asked only for scrips NSE cannot cover (no NSE symbol for the ISIN, or NSE gave no classification), since NSE
wins. NSE and BSE run side by side, each at its own client's pace (NSE 3-5 s a call, BSE 4-6 s); a refusal
(401/403/429) stops that exchange for the run. New answers go to DIR/{nse,bse}.parquet, rewritten every 25 answers
so a stopped run keeps what it read.

`build` lays DIR's answers over archive/industry/ (the later answer for a symbol wins), writes the archive back,
and rebuilds clean/current/industry.parquet (NSE, else BSE, else the VR export, labelled in `source`) and
clean/reports/industry/{date}.json. It is the only step that writes archive/ and clean/, so the workflow runs it
alone in the r2-archive-writes group; `fetch` (hours on a full run) holds no lock.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from collectors.bse.client import API as BSE_API, BSEClient, Blocked as BSEBlocked  # noqa: E402
from collectors.nse_events.client import BASE as NSE_BASE, Blocked as NSEBlocked, NSEClient  # noqa: E402
from insiders_clean import industry as I  # noqa: E402
from raw_capture import capture  # noqa: E402

NSE_QUOTE = f'{NSE_BASE}/api/quote-equity'
BSE_HEADER = 'ComHeadernew/w'
BSE_LIST = 'ListofScripData/w'
BSE_LIST_PARAMS = {'Group': '', 'Scripcode': '', 'industry': '', 'segment': 'Equity', 'status': 'Active'}
ARCHIVE = {'nse': 'archive/industry/nse.parquet', 'bse': 'archive/industry/bse.parquet'}
CLEAN_KEY = 'clean/current/industry.parquet'
SECURITIES_KEY = 'clean/current/securities.parquet'
VR_PATH = ROOT / 'reference_data' / 'security_master_20260901.csv'
IST = timezone(timedelta(hours=5, minutes=30))
CHECKPOINT = 25
STOP_AFTER_ERRORS = 10   # unreadable answers in a row: the exchange is sending something else; stop it


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class RawCapture:
    """BSEClient's raw hook, kept locally for raw_flush (no R2 secrets needed while fetching)."""

    def put(self, source, dataset, body, *, url, status=200, params=None, content_type=None, covers=None):
        capture(source, dataset, body, url=url, params=params, status=status, content_type=content_type,
                covers=covers)


# ---- fetchers ---------------------------------------------------------------------------------

def _save(rows: list, columns, path: Path | None):
    if path is not None:
        pd.DataFrame(rows, columns=columns).to_parquet(path, index=False)


def fetch_nse(symbols, report: dict, deadline: float, out: Path | None = None, nse: NSEClient | None = None,
              echo: bool = False) -> pd.DataFrame:
    nse = nse or NSEClient()
    current = {}

    def hook(url, r):
        capture('nse', 'quote_equity', r.content, url=url, status=r.status_code,
                content_type=r.headers.get('Content-Type'), covers={'symbol': current.get('symbol')})
        if echo:
            print(f'--- {url} ({len(r.content)} bytes)\n{r.text[:3000]}')
    nse.on_response = hook
    rows, errors, rep = [], 0, report.setdefault('nse', {'asked': len(symbols)})
    for n, sym in enumerate(symbols):
        if time.monotonic() > deadline:
            rep['stopped'] = f'time budget reached after {n} symbols'
            break
        current['symbol'] = sym
        try:
            j = nse.get(f'{NSE_QUOTE}?symbol={sym}', timeout=30)
        except NSEBlocked as exc:
            rep['stopped'] = f'refused ({exc}) after {n} symbols'
            break
        except Exception as exc:  # noqa: BLE001 -- one symbol failing is that symbol's error
            j = None
            rep.setdefault('fetch_errors', []).append(f'{sym}: {type(exc).__name__}: {str(exc)[:160]}')
        row = I.parse_nse(j, sym)
        row['fetched_at'] = now_utc()
        rows.append(row)
        errors = errors + 1 if row['status'] == 'error' else 0
        if errors >= STOP_AFTER_ERRORS:
            rep['stopped'] = f'{errors} unreadable answers in a row after {n + 1} symbols'
            break
        if len(rows) % CHECKPOINT == 0:
            _save(rows, I.NSE_ARCHIVE_COLUMNS, out)
    _save(rows, I.NSE_ARCHIVE_COLUMNS, out)
    df = pd.DataFrame(rows, columns=I.NSE_ARCHIVE_COLUMNS)
    rep.update(fetched=int(len(df)), calls=nse.calls, status=df['status'].value_counts().to_dict())
    return df


def bse_list(bse: BSEClient, report: dict) -> pd.DataFrame:
    body = bse.get(BSE_LIST, BSE_LIST_PARAMS, 'scrip_list', {'segment': 'Equity', 'status': 'Active'})
    try:
        payload = json.loads(body.decode('utf-8', errors='replace'))
    except ValueError:
        raise BSEBlocked(f'not JSON from {BSE_LIST} ({body[:60]!r})') from None
    df = I.parse_bse_list(payload)
    report.setdefault('bse', {})['active_scrips'] = len(payload) if isinstance(payload, list) else None
    report['bse']['company_scrips'] = int(len(df))
    return df


def fetch_bse(codes, report: dict, deadline: float, out: Path | None = None, bse: BSEClient | None = None,
              echo: bool = False) -> pd.DataFrame:
    bse = bse or BSEClient(raw=RawCapture())
    rows, errors, rep = [], 0, report.setdefault('bse', {})
    rep['asked'] = len(codes)
    for n, code in enumerate(codes):
        if time.monotonic() > deadline:
            rep['stopped'] = f'time budget reached after {n} scrips'
            break
        payload = None
        try:
            body = bse.get(BSE_HEADER, {'quotetype': 'EQ', 'scripcode': code, 'seriesid': ''}, 'comheadernew',
                           {'scripcode': code})
            if echo:
                print(f'--- {BSE_API}{BSE_HEADER}?scripcode={code} ({len(body)} bytes)\n{body[:3000].decode("utf-8", "replace")}')
            payload = json.loads(body.decode('utf-8', errors='replace'))
        except BSEBlocked as exc:
            rep['stopped'] = f'refused ({exc}) after {n} scrips'
            break
        except ValueError:
            payload = None   # an HTML error page where JSON was due
        except Exception as exc:  # noqa: BLE001
            rep.setdefault('fetch_errors', []).append(f'{code}: {type(exc).__name__}: {str(exc)[:160]}')
        row = I.parse_bse(payload, code)
        row['fetched_at'] = now_utc()
        rows.append(row)
        errors = errors + 1 if row['status'] == 'error' else 0
        if errors >= STOP_AFTER_ERRORS:
            rep['stopped'] = f'{errors} unreadable answers in a row after {n + 1} scrips'
            break
        if len(rows) % CHECKPOINT == 0:
            _save(rows, I.BSE_ARCHIVE_COLUMNS, out)
    _save(rows, I.BSE_ARCHIVE_COLUMNS, out)
    df = pd.DataFrame(rows, columns=I.BSE_ARCHIVE_COLUMNS)
    rep.update(fetched=int(len(df)), calls=bse.calls, via=bse.via, status=df['status'].value_counts().to_dict())
    return df


# ---- what is due ------------------------------------------------------------------------------

def company_securities(sec: pd.DataFrame | None) -> pd.DataFrame:
    if sec is None or sec.empty:
        return pd.DataFrame(columns=['isin', 'nse_symbol', 'bse_code'])
    sec = sec.reindex(columns=['isin', 'nse_symbol', 'bse_code']).copy()
    sec['isin'] = sec['isin'].astype('string').str.strip().str.upper()
    # an ETF or fund unit (INF...) has no industry; a row without an ISIN may still be a company's symbol
    return sec[sec['isin'].isna() | sec['isin'].str.startswith('INE', na=False)]


def nse_due(sec, archive, now, limit) -> list[str]:
    syms = company_securities(sec)['nse_symbol'].dropna().astype(str).str.strip().str.upper()
    return I.due(sorted(set(syms) - {''}), archive, 'nse_symbol', now, limit)


def bse_due(scrips: pd.DataFrame, sec, nse_archive, bse_archive, now, limit) -> list[str]:
    """Scrips NSE cannot classify: no NSE symbol for the ISIN, or NSE answered without a classification."""
    s = company_securities(sec).dropna(subset=['isin'])
    s = s[s['nse_symbol'].notna() & s['nse_symbol'].astype(str).str.strip().ne('')]
    isin_of = dict(zip(s['nse_symbol'].astype(str).str.strip().str.upper(), s['isin']))
    on_nse = set(s['isin'])
    if nse_archive is not None and not nse_archive.empty:
        a = nse_archive
        ok = a['status'] == I.OK
        nse_ok = set(a.loc[ok, 'isin'].dropna())
        # answered without a classification (or not known to NSE): BSE may have one
        failed = {i if isinstance(i, str) and i else isin_of.get(str(sym)) for sym, i in
                  zip(a.loc[~ok & a['status'].ne('error'), 'nse_symbol'], a.loc[~ok & a['status'].ne('error'), 'isin'])}
        on_nse = (on_nse - failed) | nse_ok
    codes = scrips.loc[~scrips['isin'].isin(on_nse), 'bse_code'].astype(str).tolist()
    return I.due(codes, bse_archive, 'bse_code', now, limit)


# ---- runs -------------------------------------------------------------------------------------

def fetch(r2, out: Path, sources, limit: int | None, minutes: float, report: dict,
          nse: NSEClient | None = None, bse: BSEClient | None = None) -> dict:
    from clean_writer import read_parquet
    out.mkdir(parents=True, exist_ok=True)
    now = now_utc()
    deadline = time.monotonic() + minutes * 60
    sec = read_parquet(r2, SECURITIES_KEY)
    arch = {k: read_parquet(r2, v) for k, v in ARCHIVE.items()}
    report['securities_rows'] = None if sec is None else int(len(sec))
    for k, a in arch.items():
        report[f'{k}_archive_rows'] = 0 if a is None else int(len(a))
    threads = []
    if 'nse' in sources:
        todo = nse_due(sec, arch['nse'], now, limit)
        report['nse'] = {'due': len(todo)}
        report['nse']['asked'] = len(todo)
        threads.append(threading.Thread(target=fetch_nse, args=(todo, report, deadline, out / 'nse.parquet', nse)))
    if 'bse' in sources:
        def run_bse():
            client = bse or BSEClient(raw=RawCapture())
            try:
                scrips = bse_list(client, report)
            except Exception as exc:  # noqa: BLE001 -- no list, no BSE this run
                report.setdefault('bse', {})['stopped'] = f'scrip list not fetched ({type(exc).__name__}: {exc})'
                return
            todo = bse_due(scrips, sec, arch['nse'], arch['bse'], now, limit)
            report['bse']['due'] = len(todo)
            try:
                fetch_bse(todo, report, deadline, out / 'bse.parquet', client)
            finally:
                client.close()
        threads.append(threading.Thread(target=run_bse))
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    (out / 'fetch_report.json').write_text(json.dumps(report, indent=2, default=str))
    return report


def build(r2, src: Path | None, day, report: dict, dry_run: bool = False) -> dict:
    from clean_writer import put, put_parquet, read_parquet
    merged = {}
    for k, cols, key in (('nse', I.NSE_ARCHIVE_COLUMNS, 'nse_symbol'), ('bse', I.BSE_ARCHIVE_COLUMNS, 'bse_code')):
        new = None
        f = src / f'{k}.parquet' if src is not None else None
        if f is not None and f.exists():
            new = pd.read_parquet(f)
        old = read_parquet(r2, ARCHIVE[k])
        merged[k] = I.merge(old, new, key, cols)
        report[f'{k}_new_answers'] = 0 if new is None else int(len(new))
        report[f'{k}_archive'] = {'rows': int(len(merged[k])),
                                  'status': merged[k]['status'].value_counts().to_dict() if len(merged[k]) else {}}
        if not dry_run and new is not None and not new.empty:
            put_parquet(r2, ARCHIVE[k], merged[k])
    sec = read_parquet(r2, SECURITIES_KEY)
    vr = pd.read_csv(VR_PATH, dtype=str, keep_default_na=False) if VR_PATH.exists() else None
    table, counts = I.build(merged['nse'], merged['bse'], sec, vr)
    report['clean'] = counts
    if src is not None and (src / 'fetch_report.json').exists():
        report['fetch'] = json.loads((src / 'fetch_report.json').read_text())
    if not dry_run:
        put_parquet(r2, CLEAN_KEY, table)
        put(r2, f'clean/reports/industry/{day.isoformat()}.json', json.dumps(report, indent=2, default=str).encode(),
            'application/json')
    return report


def probe(out: Path, symbols, codes, report: dict) -> dict:
    """No R2: fetch the given symbols and codes, print each answer and its parsed row, keep raw captures."""
    out.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + 15 * 60
    if symbols:
        df = fetch_nse(symbols, report, deadline, out / 'nse.parquet', echo=True)
        print(df.to_string())
    if codes:
        client = BSEClient(raw=RawCapture())
        try:
            try:
                bse_list(client, report)
            except Exception as exc:  # noqa: BLE001
                report.setdefault('bse', {})['list_error'] = f'{type(exc).__name__}: {exc}'
            df = fetch_bse(codes, report, deadline, out / 'bse.parquet', client, echo=True)
            print(df.to_string())
        finally:
            client.close()
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    f = sub.add_parser('fetch')
    f.add_argument('--out', required=True, type=Path)
    f.add_argument('--limit', type=int, default=400, help='at most this many symbols per exchange (0 = no limit)')
    f.add_argument('--minutes', type=float, default=75, help='stop asking after this many minutes')
    f.add_argument('--sources', default='nse,bse')
    b = sub.add_parser('build')
    b.add_argument('--in', dest='src', type=Path, help='the fetch folder (absent: rebuild from the archive)')
    b.add_argument('--dry-run', action='store_true', help='build and print counts, write nothing')
    p = sub.add_parser('probe')
    p.add_argument('--out', required=True, type=Path)
    p.add_argument('--nse', default='', help='comma list of NSE symbols')
    p.add_argument('--bse', default='', help='comma list of BSE scrip codes')
    a = ap.parse_args(argv)
    td = os.environ.get('TARGET_DATE', '').strip()
    day = datetime.fromisoformat(td).date() if td else datetime.now(IST).date()
    report = {'run_date': day.isoformat(), 'cmd': a.cmd}
    if a.cmd == 'probe':
        split = lambda s: [x.strip().upper() for x in s.split(',') if x.strip()]  # noqa: E731
        probe(a.out, split(a.nse), split(a.bse), report)
    else:
        from r2_writer import r2_client
        if a.cmd == 'fetch':
            sources = [s.strip() for s in a.sources.split(',') if s.strip()]
            if set(sources) - {'nse', 'bse'}:
                ap.error(f'unknown source in {a.sources}')
            fetch(r2_client(), a.out, sources, a.limit or None, a.minutes, report)
        else:
            build(r2_client(), a.src, day, report, dry_run=a.dry_run)
    print(json.dumps(report, indent=1, default=str))
    return 0


if __name__ == '__main__':
    sys.exit(main())
