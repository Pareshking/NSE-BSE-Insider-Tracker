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
BSE is asked first for scrips NSE cannot cover (no NSE symbol for the ISIN, or NSE gave no classification), then for
the rest: NSE refused its quote API from GitHub's runners on 19 Nov 2026 (HTTP 403 on www.nseindia.com and
www.nseindia.in), so until it answers BSE's classification stands for every company. NSE wins whenever it has one. NSE and BSE run side by side, each at its own client's pace (NSE 3-5 s a call, BSE 4-6 s); a refusal
(401/403/429) stops that exchange for the run. New answers go to DIR/{nse,bse}.parquet, rewritten every 25 answers.

Saved as it goes (19 and 20 Nov 2026 two full runs lost every answer: the raw flush and the artifact upload ran only
at the end, and the timeout cancelled them): every 200 answers or 10 minutes the fetch stores its raw captures so far
in raw_v2/ (16 side by side) and this run's answers in staging/industry/{run}/{nse,bse}.parquet. Neither needs the
r2-archive-writes lock (raw is write-once and named by content; the staging key is the run's own).

Resumes: what is due is decided against the archive with every run's checkpoint laid over it, so repeated runs that
are each cut off converge. When R2 holds neither an archive nor a checkpoint for an exchange, the answers already in
raw_v2/ (nse/quote_equity, bse/comheadernew) are parsed again first.

`build` lays all of that (archive, every checkpoint, raw when neither exists, DIR if given) together (the later
answer for a symbol wins), writes the archive back, and rebuilds clean/current/industry.parquet (NSE, else BSE, else
the VR export, labelled in `source`) and clean/reports/industry/{date}.json, then deletes checkpoints older than two
days. It is the only step that writes archive/ and clean/, so the workflow runs it alone in the r2-archive-writes
group; `fetch` (hours on a full run) holds no lock.
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

# The quote API sits behind NSE's quote page: the session first visits the home page and that page for its cookies,
# and each call names the page as its Referer, as NSE's own page does. The host is a setting (NSE_QUOTE_HOST) because
# the probe on 19 Nov 2026 found the client's www.nseindia.in refused (403) for this API from GitHub's runners.
NSE_HOSTS = ('https://www.nseindia.com', NSE_BASE)
NSE_HOST = os.environ.get('NSE_QUOTE_HOST', '').strip().rstrip('/') or NSE_HOSTS[0]
BSE_HEADER = 'ComHeadernew/w'
BSE_LIST = 'ListofScripData/w'
BSE_LIST_PARAMS = {'Group': '', 'Scripcode': '', 'industry': '', 'segment': 'Equity', 'status': 'Active'}
ARCHIVE = {'nse': 'archive/industry/nse.parquet', 'bse': 'archive/industry/bse.parquet'}
CLEAN_KEY = 'clean/current/industry.parquet'
SECURITIES_KEY = 'clean/current/securities.parquet'
VR_PATH = ROOT / 'reference_data' / 'security_master_20260901.csv'
IST = timezone(timedelta(hours=5, minutes=30))
CHECKPOINT = 25          # the local folder (the run's artifact) is rewritten every this many answers
STAGING_PREFIX = 'staging/industry/'   # {run}/{nse,bse}.parquet: each run's answers so far (Saver), read by the build
SAVE_EVERY = 200         # answers between two pushes to R2 while fetching
SAVE_MINUTES = 10        # ... or minutes, whichever comes first
FLUSH_WORKERS = 16       # raw captures stored side by side
STAGING_KEEP_DAYS = 2    # a checkpoint older than this is deleted by the build once merged (a run lasts < 6 hours)
EXCHANGES = (('nse', I.NSE_ARCHIVE_COLUMNS, 'nse_symbol'), ('bse', I.BSE_ARCHIVE_COLUMNS, 'bse_code'))
STOP_AFTER_ERRORS = 10   # unreadable answers in a row: the exchange is sending something else; stop it
# BSE's quote header is slow to answer (speed test 20 Nov 2026, PR #313, GitHub runner: 3.5 s an answer one at a time
# with a 1 s pause; 0.13 s an answer four at a time, 40 of 40 answered, no refusal). So BSE is asked by BSE_WORKERS
# side by side, each with its own session and a BSE_WORKER_PACE pause; the first refusal (401/403/429) stops all of
# them for the run (no browser fallback, no retry around it). ~4,849 scrips: about an hour instead of 6-7.
BSE_WORKERS = int(os.environ.get('INDUSTRY_BSE_WORKERS', '4'))
BSE_WORKER_PACE = (1.0, 2.0)


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
        pd.DataFrame(list(rows), columns=columns).to_parquet(path, index=False, compression='zstd')


def nse_warm(nse: NSEClient, host: str, symbol: str | None):
    """Cookies from the home page and one quote page (best effort; the answer to the API call is what counts)."""
    nse._warm = True   # the client's own warm-up visits its default host, not this one
    for url in (f'{host}/', f'{host}/get-quotes/equity?symbol={symbol}' if symbol else None):
        if url:
            try:
                nse.s.get(url, timeout=30, headers={'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8'})
            except Exception:  # noqa: BLE001
                pass


def fetch_nse(symbols, report: dict, deadline: float, out: Path | None = None, nse: NSEClient | None = None,
              echo: bool = False, host: str | None = None, key: str = 'nse', rows: list | None = None) -> pd.DataFrame:
    """`rows`: the list the answers are appended to as they arrive (fetch's Saver reads it while this runs)."""
    host = host or NSE_HOST
    nse = nse or NSEClient()
    if symbols and not nse._warm:
        nse_warm(nse, host, symbols[0])
    current = {}

    def hook(url, r):
        capture('nse', 'quote_equity', r.content, url=url, status=r.status_code,
                content_type=r.headers.get('Content-Type'), covers={'symbol': current.get('symbol')})
        if echo:
            print(f'--- {url} ({len(r.content)} bytes)\n{r.text[:3000]}')
    nse.on_response = hook
    rows = [] if rows is None else rows
    errors, rep = 0, report.setdefault(key, {'asked': len(symbols)})
    rep['host'] = host
    for n, sym in enumerate(symbols):
        if time.monotonic() > deadline:
            rep['stopped'] = f'time budget reached after {n} symbols'
            break
        current['symbol'] = sym
        try:
            nse.s.headers['Referer'] = f'{host}/get-quotes/equity?symbol={sym}'
            j = nse.get(f'{host}/api/quote-equity?symbol={sym}', timeout=30)
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
    df = pd.DataFrame(list(rows), columns=I.NSE_ARCHIVE_COLUMNS)
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
              echo: bool = False, rows: list | None = None, key: str = 'bse',
              stop: threading.Event | None = None) -> pd.DataFrame:
    """`key`: where in `report` this fetcher reports; `stop`: set by any worker on a refusal, ends the others."""
    bse = bse or BSEClient(raw=RawCapture())
    rows = [] if rows is None else rows
    errors, rep = 0, report.setdefault(key, {})
    rep['asked'] = len(codes)
    mine = []
    for n, code in enumerate(codes):
        if time.monotonic() > deadline:
            rep['stopped'] = f'time budget reached after {n} scrips'
            break
        if stop is not None and stop.is_set():
            rep['stopped'] = f'another worker was refused; stopped after {n} scrips'
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
            if stop is not None:
                stop.set()
            break
        except ValueError:
            payload = None   # an HTML error page where JSON was due
        except Exception as exc:  # noqa: BLE001
            rep.setdefault('fetch_errors', []).append(f'{code}: {type(exc).__name__}: {str(exc)[:160]}')
        row = I.parse_bse(payload, code)
        row['fetched_at'] = now_utc()
        rows.append(row)
        mine.append(row)
        errors = errors + 1 if row['status'] == 'error' else 0
        if errors >= STOP_AFTER_ERRORS:
            rep['stopped'] = f'{errors} unreadable answers in a row after {n + 1} scrips'
            if stop is not None:
                stop.set()
            break
        if len(rows) % CHECKPOINT == 0:
            _save(rows, I.BSE_ARCHIVE_COLUMNS, out)
    _save(rows, I.BSE_ARCHIVE_COLUMNS, out)
    df = pd.DataFrame(mine, columns=I.BSE_ARCHIVE_COLUMNS)
    rep.update(fetched=int(len(df)), calls=bse.calls, via=bse.via, status=df['status'].value_counts().to_dict())
    return df


def fetch_bse_parallel(codes, report: dict, deadline: float, out: Path | None = None, rows: list | None = None,
                       workers: int = BSE_WORKERS, client_factory=None) -> pd.DataFrame:
    """`codes` dealt round-robin to `workers` threads, each with its own BSEClient (BSE_WORKER_PACE, no browser
    fallback); answers go to the shared `rows` as they arrive (the Saver reads it). One worker refused stops all.
    The local file is written once at the end (workers would race on it)."""
    rows = [] if rows is None else rows
    rep = report.setdefault('bse', {})
    rep.update(asked=len(codes), workers=workers)
    make = client_factory or (lambda: BSEClient(raw=RawCapture(), pace=BSE_WORKER_PACE, allow_in_page=False))
    stop = threading.Event()
    clients = [make() for _ in range(max(1, workers))]
    sub = {}
    threads = [threading.Thread(target=fetch_bse, args=(codes[w::len(clients)], sub, deadline, None, c),
                                kwargs={'rows': rows, 'key': f'w{w}', 'stop': stop})
               for w, c in enumerate(clients)]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        for c in clients:
            c.close()
    _save(rows, I.BSE_ARCHIVE_COLUMNS, out)
    df = pd.DataFrame(list(rows), columns=I.BSE_ARCHIVE_COLUMNS)
    rep.update(fetched=int(len(df)), calls=sum(c.calls for c in clients), via='requests',
               status=df['status'].value_counts().to_dict(), by_worker=sub)
    stopped = [v['stopped'] for v in sub.values() if v.get('stopped') and 'another worker' not in v['stopped']]
    if stopped:
        rep['stopped'] = stopped[0]
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
    """Scrips NSE cannot classify first (no NSE symbol for the ISIN, or NSE answered without a classification),
    then the rest."""
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
    first = scrips.loc[~scrips['isin'].isin(on_nse), 'bse_code'].astype(str).tolist()
    # then the scrips NSE should cover: NSE refused its quote API from GitHub's runners on 19 Nov 2026, so BSE's
    # answer stands for them until NSE answers (NSE still wins in the clean table)
    then = scrips.loc[scrips['isin'].isin(on_nse), 'bse_code'].astype(str).tolist()
    todo = I.due(first, bse_archive, 'bse_code', now, None) + I.due(then, bse_archive, 'bse_code', now, None)
    return todo if limit is None else todo[:max(0, int(limit))]


# ---- what is already on file: archive, staging checkpoints, raw ---------------------------------

def run_name() -> str:
    """The run's own staging folder: GitHub's run id and attempt, else the UTC time."""
    rid = os.environ.get('GITHUB_RUN_ID', '').strip()
    if rid:
        return f"{rid}-{os.environ.get('GITHUB_RUN_ATTEMPT', '1').strip() or '1'}"
    return now_utc().strftime('local-%Y%m%dT%H%M%S')


def staging_objects(r2) -> list[dict]:
    """[{'Key', 'LastModified'?}] under staging/industry/ (LastModified absent in the test double)."""
    from clean_writer import BUCKET
    out, token = [], None
    while True:
        kw = {'Bucket': BUCKET, 'Prefix': STAGING_PREFIX}
        if token:
            kw['ContinuationToken'] = token
        resp = r2.list_objects_v2(**kw)
        out += resp.get('Contents', [])
        if not resp.get('IsTruncated'):
            return out
        token = resp['NextContinuationToken']


def read_staging(r2, report: dict | None = None) -> dict:
    """Every run's checkpoint (staging/industry/{run}/{nse,bse}.parquet), merged per exchange: the later answer for a
    symbol wins. {'nse': df|None, 'bse': df|None}."""
    from clean_writer import read_parquet
    objs = [o for o in staging_objects(r2) if o['Key'].endswith(('/nse.parquet', '/bse.parquet'))]
    frames = {'nse': [], 'bse': []}
    for o in objs:
        df = read_parquet(r2, o['Key'])
        if df is not None and not df.empty:
            frames[o['Key'].rsplit('/', 1)[1].split('.')[0]].append(df)
    out = {k: I.merge(None, pd.concat(frames[k], ignore_index=True), key, cols) if frames[k] else None
           for k, cols, key in EXCHANGES}
    if report is not None:
        report['staging'] = {'objects': len(objs), **{k: 0 if v is None else int(len(v)) for k, v in out.items()}}
    return out


def answers_from_raw(r2, exchange: str, workers: int = FLUSH_WORKERS, report: dict | None = None) -> pd.DataFrame:
    """Every industry answer kept in raw_v2/ (write-once, from every run that reached its raw flush, even one cut off
    halfway: 19 and 20 Nov 2026), parsed again exactly as the fetch parsed it, the later answer per symbol kept."""
    import gzip
    from concurrent.futures import ThreadPoolExecutor

    from clean_writer import get, get_blob, list_keys
    src, ds = I.RAW_DATASETS[exchange]
    cols, key = {k: (c, kk) for k, c, kk in EXCHANGES}[exchange]
    keys = [k for k in list_keys(r2, f'raw_v2/{src}/{ds}/fetches/') if k.endswith('.json')]
    blobs: dict[str, bytes | None] = {}

    def one(k):
        try:
            rec = json.loads(get(r2, k) or b'null')
            bk = rec.get('blob_key') if isinstance(rec, dict) else None
            if not bk:
                return None, 'no record'
            if bk not in blobs:
                packed = get(r2, bk + '.gz') if rec.get('stored_as') == 'gzip' else None
                blobs[bk] = gzip.decompress(packed) if packed is not None else get_blob(r2, bk)
            row = I.parse_raw(exchange, rec, blobs[bk])
            return row, None if row is not None else 'not an answer'
        except Exception as exc:  # noqa: BLE001 -- one unreadable record is counted, not fatal
            return None, f'unreadable ({type(exc).__name__})'
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        results = list(pool.map(one, keys))
    rows = [r for r, _ in results if r is not None]
    skipped: dict[str, int] = {}
    for _, why in results:
        if why:
            skipped[why] = skipped.get(why, 0) + 1
    df = I.merge(None, pd.DataFrame(rows, columns=cols), key, cols) if rows else pd.DataFrame(columns=cols)
    if report is not None:
        days: dict[str, int] = {}
        for k in keys:
            d = k.split('/fetches/')[1][:10]
            days[d] = days.get(d, 0) + 1
        report.setdefault('raw', {})[exchange] = {
            'fetch_records': len(keys), 'answers': len(rows), 'skipped': skipped, 'fetch_days': days,
            'symbols': int(len(df)), 'status': df['status'].value_counts().to_dict() if len(df) else {}}
    return df


def on_file(r2, report: dict, workers: int = FLUSH_WORKERS) -> tuple[dict, dict, dict]:
    """What R2 already holds per exchange: (archive, staging, from raw). Raw is parsed only for an exchange with
    neither an archive nor a checkpoint (the first run after 19-20 Nov 2026's lost runs)."""
    from clean_writer import read_parquet
    arch = {k: read_parquet(r2, ARCHIVE[k]) for k in ARCHIVE}
    for k, a in arch.items():
        report[f'{k}_archive_rows'] = 0 if a is None else int(len(a))
    staged = read_staging(r2, report)
    raw = {}
    for k, _, _ in EXCHANGES:
        nothing = (arch[k] is None or arch[k].empty) and (staged[k] is None or staged[k].empty)
        raw[k] = answers_from_raw(r2, k, workers, report) if nothing else None
    return arch, staged, raw


def known_answers(arch: dict, *layers: dict) -> dict:
    """The archive with the checkpoints, raw and a local fetch folder laid over it (the later answer wins)."""
    out = {}
    for k, cols, key in EXCHANGES:
        new = [d.get(k) for d in layers if d.get(k) is not None and not d.get(k).empty]
        out[k] = I.merge(arch.get(k), pd.concat(new, ignore_index=True) if new else None, key, cols)
    return out


class Saver:
    """Pushes a running fetch to R2 as it goes, so a run cut off by its timeout or a cancel keeps its work (19 and 20
    Nov 2026 lost every answer: the raw flush and the artifact upload ran only at the end). Every `every` new answers
    or `minutes` minutes: the raw captures so far go to raw_v2/ (write-once, `workers` side by side), then every answer
    of this run to staging/industry/{run}/{nse,bse}.parquet, which the build and the next fetch read. Neither write
    needs the r2-archive-writes lock: raw is write-once and named by content, and the staging key is this run's own.
    A failed save is counted and tried again at the next one; it never stops the fetch."""

    def __init__(self, r2, run: str, live: dict | None = None, every: int = SAVE_EVERY,
                 minutes: float = SAVE_MINUTES, workers: int = FLUSH_WORKERS, raw_dir: Path | None = None,
                 clock=time.monotonic):
        self.r2, self.run, self.live, self.every, self.seconds = r2, run, live or {}, every, minutes * 60
        self.workers, self.raw_dir, self.clock = workers, raw_dir, clock
        self.saved_answers, self.last = 0, clock()
        self.stats = {'saves': 0, 'failed_saves': 0, 'raw_stored': 0, 'raw_left': 0, 'errors': []}

    def answers(self) -> int:
        return sum(len(v) for v in self.live.values())

    def due(self) -> bool:
        n = self.answers()
        return n > self.saved_answers and (n - self.saved_answers >= self.every or
                                           self.clock() - self.last >= self.seconds)

    def key(self, exchange: str) -> str:
        return f'{STAGING_PREFIX}{self.run}/{exchange}.parquet'

    def save(self, report: dict | None = None) -> dict:
        import raw_capture
        import raw_flush
        from clean_writer import BUCKET, put, put_parquet
        n = self.answers()
        try:
            res = raw_flush.flush(self.r2, self.raw_dir or raw_capture.DIR, bucket=BUCKET, commit_label='industry',
                                  workers=self.workers)
            self.stats['raw_stored'] += res['stored']
            self.stats['raw_left'] = res['failed']   # still on disk, tried again at the next save
            if res['errors']:
                self.stats['errors'] = (self.stats['errors'] + res['errors'][:2])[-5:]
            for k, cols, _ in EXCHANGES:
                rows = list(self.live.get(k) or [])
                if rows:
                    put_parquet(self.r2, self.key(k), pd.DataFrame(rows, columns=cols))
            if report is not None:
                try:   # the fetch threads may be adding to it right now: skipped this time, written at the next save
                    text = json.dumps(report, indent=2, default=str)
                except RuntimeError:
                    text = None
                if text is not None:
                    put(self.r2, f'{STAGING_PREFIX}{self.run}/fetch_report.json', text.encode(), 'application/json')
            self.stats['saves'] += 1
            self.saved_answers = n
        except Exception as exc:  # noqa: BLE001
            self.stats['failed_saves'] += 1
            self.stats['errors'] = (self.stats['errors'] + [f'{type(exc).__name__}: {str(exc)[:160]}'])[-5:]
        self.last = self.clock()
        print(f'saved {n} answers to R2: {json.dumps(self.stats, default=str)}', flush=True)
        return self.stats


# ---- runs -------------------------------------------------------------------------------------

def fetch(r2, out: Path, sources, limit: int | None, minutes: float, report: dict,
          nse: NSEClient | None = None, bse: BSEClient | None = None, saver: Saver | None = None,
          run: str | None = None) -> dict:
    """Resumes: what is due is decided against the archive with every run's checkpoint laid over it (and, when R2 has
    neither, the answers in raw_v2/), so a run cut off halfway is taken up where it stopped by the next one."""
    from clean_writer import put_parquet, read_parquet
    out.mkdir(parents=True, exist_ok=True)
    now = now_utc()
    deadline = time.monotonic() + minutes * 60
    run = run or run_name()
    report['run'] = run
    sec = read_parquet(r2, SECURITIES_KEY)
    report['securities_rows'] = None if sec is None else int(len(sec))
    arch, staged, raw = on_file(r2, report)
    for k, df in raw.items():   # rebuilt from raw: kept as a checkpoint, so neither the build nor the next run redoes it
        if df is not None and not df.empty:
            put_parquet(r2, f'{STAGING_PREFIX}{run}-raw/{k}.parquet', df)
    known = known_answers(arch, staged, raw)
    report['known_answers'] = {k: int(len(v)) for k, v in known.items()}
    live = {'nse': [], 'bse': []}
    saver = saver if saver is not None else Saver(r2, run)
    saver.live = live
    threads = []
    if 'nse' in sources:
        todo = nse_due(sec, known['nse'], now, limit)
        report['nse'] = {'due': len(todo)}
        report['nse']['asked'] = len(todo)
        threads.append(threading.Thread(target=fetch_nse, args=(todo, report, deadline, out / 'nse.parquet', nse),
                                        kwargs={'rows': live['nse']}))
    if 'bse' in sources:
        def run_bse():
            client = bse or BSEClient(raw=RawCapture())
            try:
                scrips = bse_list(client, report)
            except Exception as exc:  # noqa: BLE001 -- no list, no BSE this run
                report.setdefault('bse', {})['stopped'] = f'scrip list not fetched ({type(exc).__name__}: {exc})'
                return
            todo = bse_due(scrips, sec, known['nse'], known['bse'], now, limit)
            report['bse']['due'] = len(todo)
            try:
                if bse is None and BSE_WORKERS > 1:
                    fetch_bse_parallel(todo, report, deadline, out / 'bse.parquet', rows=live['bse'])
                else:
                    fetch_bse(todo, report, deadline, out / 'bse.parquet', client, rows=live['bse'])
            finally:
                client.close()
        threads.append(threading.Thread(target=run_bse))
    for t in threads:
        t.start()
    while any(t.is_alive() for t in threads):
        for t in threads:
            t.join(timeout=2)
        if saver.due():
            saver.save(report)
    report['saves'] = saver.save(report)
    (out / 'fetch_report.json').write_text(json.dumps(report, indent=2, default=str))
    return report


def build(r2, src: Path | None, day, report: dict, dry_run: bool = False) -> dict:
    """Rebuilds from everything already in R2 (the archive, every run's checkpoint, and raw_v2/ when neither exists)
    plus a local fetch folder if there is one. Writes the archive back, then clean/; checkpoints older than
    STAGING_KEEP_DAYS (their runs long over, their answers now in the archive) are deleted after that."""
    from clean_writer import BUCKET, put, put_parquet, read_parquet
    local = {}
    for k in ARCHIVE:
        f = src / f'{k}.parquet' if src is not None else None
        local[k] = pd.read_parquet(f) if f is not None and f.exists() else None
        report[f'{k}_new_answers'] = 0 if local[k] is None else int(len(local[k]))
    arch, staged, raw = on_file(r2, report)
    merged = known_answers(arch, staged, raw, local)
    for k, _, _ in EXCHANGES:
        added = sum(0 if d.get(k) is None else int(len(d[k])) for d in (staged, raw, local))
        report[f'{k}_archive'] = {'rows_before': 0 if arch[k] is None else int(len(arch[k])),
                                  'rows': int(len(merged[k])),
                                  'status': merged[k]['status'].value_counts().to_dict() if len(merged[k]) else {}}
        if not dry_run and added and len(merged[k]):
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
        # a checkpoint this old belongs to a run long over; its answers were merged into the archive written above
        cutoff = pd.Timestamp(now_utc() - timedelta(days=STAGING_KEEP_DAYS), tz='UTC')
        old = [o['Key'] for o in staging_objects(r2)
               if o.get('LastModified') is not None and pd.Timestamp(o['LastModified']) < cutoff]
        for i in range(0, len(old), 1000):   # at most 1,000 keys a call
            r2.delete_objects(Bucket=BUCKET, Delete={'Objects': [{'Key': k} for k in old[i:i + 1000]]})
        report['staging_deleted'] = len(old)
    return report


NSE_NEXT = 'https://www.nseindia.com/api/NextApi/apiClient/GetQuoteApi'


def probe_nse_package(symbols, report: dict):
    """The `nse` package's HTTP/2 session (as scripts/update_calendar.py uses on the runners): the old quote API and
    NSE's newer quote API (NextApi getSymbolData / getMetaData), each answer printed and captured."""
    import tempfile
    rep = report.setdefault('nse_package', {})
    try:
        from nse import NSE
        n = NSE(tempfile.mkdtemp(), server=True)
    except Exception as exc:  # noqa: BLE001
        rep['error'] = f'{type(exc).__name__}: {exc}'
        return
    for sym in symbols[:2]:
        for name, url, params in (
                ('quote_equity', f'{NSE_HOSTS[0]}/api/quote-equity', {'symbol': sym}),
                ('next_symbol_data', NSE_NEXT, {'functionName': 'getSymbolData', 'marketType': 'N', 'series': 'EQ',
                                                'symbol': sym}),
                ('next_meta_data', NSE_NEXT, {'functionName': 'getMetaData', 'symbol': sym})):
            time.sleep(3)
            try:
                r = n._session.get(url, params=params, timeout=30)
            except Exception as exc:  # noqa: BLE001
                rep[f'{sym} {name}'] = f'{type(exc).__name__}: {exc}'
                continue
            rep[f'{sym} {name}'] = f'HTTP {r.status_code}, {len(r.content)} bytes'
            if r.status_code == 200:
                capture('nse', name, r.content, url=url, params=params, status=r.status_code,
                        content_type=r.headers.get('content-type'), covers={'symbol': sym})
            print(f'--- {name} {sym} HTTP {r.status_code}\n{r.text[:6000]}')


def probe(out: Path, symbols, codes, report: dict) -> dict:
    """No R2: fetch the given symbols and codes, print each answer and its parsed row, keep raw captures."""
    out.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + 15 * 60
    for n, host in enumerate(NSE_HOSTS if symbols else ()):
        df = fetch_nse(symbols, report, deadline, out / f'nse_{n}.parquet', NSEClient(), echo=True, host=host,
                       key=f'nse_{n}')
        print(host); print(df.to_string())
    if symbols:
        probe_nse_package(symbols, report)
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
