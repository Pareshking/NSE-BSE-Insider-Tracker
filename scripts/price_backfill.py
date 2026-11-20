"""Backfill and nightly increment of daily UDiFF bhavcopy prices for NSE and BSE.

Every downloaded file is stored byte for byte in raw_v2 (write-once). Parsed days are written to
`prices/daily/{exchange}/{YYYY-MM}.parquet` (derived, rebuilt per month; prices as printed, never adjusted).
Weekday with a 404 = no session (holiday); recorded in the report, not guessed. Stops on a 403/429.
Prints aggregate counts only (the repo is public).
"""
from __future__ import annotations

import argparse
import io
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from insiders_clean import index_close, market_cap, prices  # noqa: E402

UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0 Safari/537.36'
# name -> (raw label, url template, parser, output prefix, validator).
# NSE_PR is NSE's PR zip: its mcap file gives shares in issue and market cap per day (point in time);
# the zip also holds the day's corporate-action file (`bc`), kept as raw bytes for later parsing.
SOURCES = {
    'NSE': ('nse_udiff_cm', 'https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{ymd}_F_0000.csv.zip',
            lambda b: prices.parse_udiff(b, 'NSE'), 'prices/daily/nse', prices.validate_day),
    'BSE': ('bse_udiff_cm', 'https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{ymd}_F_0000.CSV',
            lambda b: prices.parse_udiff(b, 'BSE'), 'prices/daily/bse', prices.validate_day),
    'NSE_PR': ('nse_pr_zip', 'https://archives.nseindia.com/archives/equities/bhavcopy/pr/PR{dmy2}.zip',
               market_cap.parse_mcap, 'marketcap/daily/nse', market_cap.validate),
    # NSE index closing values (Nifty 500 is the research baseline).
    'NSE_IDX': ('nse_index_close', 'https://nsearchives.nseindia.com/content/indices/ind_close_all_{dmy}.csv',
                index_close.parse_index, 'indices/daily/nse', index_close.validate),
}
KEYS = {'NSE': ['date', 'exchange', 'isin', 'symbol', 'series'], 'BSE': ['date', 'exchange', 'isin', 'symbol', 'series'],
        'NSE_PR': ['date', 'symbol', 'series'], 'NSE_IDX': ['date', 'symbol']}
PAUSE = 0.6


class Stop(Exception):
    pass


def weekdays(start: date, end: date):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def key(exchange: str, month: str) -> str:
    return f'{SOURCES[exchange][3]}/{month}.parquet'


def load_month(client, bucket, exchange, month):
    try:
        body = client.get_object(Bucket=bucket, Key=key(exchange, month))['Body'].read()
        return pd.read_parquet(io.BytesIO(body))
    except Exception as e:  # noqa: BLE001
        if 'NoSuchKey' in str(e) or '404' in str(e):
            return None
        raise


def fetch(session, store, exchange, day):
    label, tmpl, parse, _, _ = SOURCES[exchange]
    url = tmpl.format(ymd=f'{day:%Y%m%d}', dmy2=f'{day:%d%m%y}', dmy=f'{day:%d%m%Y}')
    r = session.get(url, timeout=45)
    if r.status_code in (403, 429):
        raise Stop(f'{exchange} {r.status_code}')
    if r.status_code == 404 or not r.content:
        return None
    if 'html' in (r.headers.get('Content-Type') or '').lower() or r.content.lstrip()[:1] == b'<':
        return None  # BSE answers a missing day with its home page and status 200 (VERIFIED 09 Oct 2026)
    if r.status_code != 200:
        raise RuntimeError(f'{exchange} {day} status {r.status_code}')
    if store is not None:
        store.put('exchange_files', label, r.content, url=url, status=200,
                  content_type=r.headers.get('Content-Type'), covers={'day': day.isoformat()})
    return parse(r.content)


CALENDAR_KEY = 'reference/nse_calendar.json'


def weekend_sessions(client, bucket) -> set[date]:
    """Weekend days NSE traded (reference/nse_calendar.json, kept by update_calendar.py, which probes every day):
    the Sunday sessions of a Budget day or Muhurat trading. Weekdays alone left them out of the layer (audit 19 Nov
    2026: 1 Feb and 8 Nov 2026), and the next session's base prices then read as resets (insiders_clean/adjust.py)."""
    import json
    try:
        st = json.loads(client.get_object(Bucket=bucket, Key=CALENDAR_KEY)['Body'].read())
    except Exception as e:  # noqa: BLE001 -- no calendar: weekdays only, as before
        print(f'calendar not read ({type(e).__name__}); weekdays only')
        return set()
    days = set()
    for x in list(st.get('traded', [])) + list(st.get('special_sessions', [])):
        try:
            d = date.fromisoformat(str(x)[:10])
        except ValueError:
            continue
        if d.weekday() >= 5:
            days.add(d)
    return days


def months(start: date, end: date, extra=()):
    """Weekdays, and the `extra` days (weekend sessions) between start and end, grouped by calendar month, oldest
    first."""
    cur, out = None, []
    for d in sorted(set(weekdays(start, end)) | {x for x in extra if start <= x <= end}):
        m = f'{d:%Y-%m}'
        if m != cur and out:
            yield cur, out
            out = []
        cur = m
        out.append(d)
    if out:
        yield cur, out


def run(start, end, exchanges, client=None, bucket=None, store=None, dry=False, sleep=time.sleep, extra=()):
    """One month at a time: fetch, then write that month's parquet and print progress right away,
    so an interrupted run keeps what it finished and the log shows where it is. `extra`: weekend sessions to fetch
    too (weekend_sessions)."""
    s = requests.Session()
    s.headers.update({'User-Agent': UA, 'Accept': '*/*'})
    totals = {}
    for ex in exchanges:
        t = {'sessions': 0, 'no_file': 0, 'rows': 0, 'already': 0, 'errors': 0, 'problems': {}}
        for month, days in months(start, end, extra):
            old = load_month(client, bucket, ex, month) if client is not None else None
            frames = []
            for day in days:
                if old is not None and (old['date'] == pd.Timestamp(day)).any():
                    t['already'] += 1
                    continue
                try:
                    df = fetch(s, store, ex, day)
                except Stop:
                    raise
                except Exception as e:  # noqa: BLE001
                    t['errors'] += 1
                    print(f'  {ex} {day}: {type(e).__name__}', flush=True)
                    continue
                sleep(PAUSE)
                if df is None:
                    t['no_file'] += 1
                    continue
                dated = pd.to_datetime(df['date'], errors='coerce').dropna() if 'date' in df else pd.Series(dtype='datetime64[ns]')
                if len(dated) and not (dated == pd.Timestamp(day)).any():
                    # A file for another day (never seen; guards the weekend fetches): not stored under this one.
                    t['wrong_day'] = t.get('wrong_day', 0) + 1
                    print(f'  {ex} {day}: file dated otherwise, not kept', flush=True)
                    continue
                t['sessions'] += 1
                t['rows'] += len(df)
                for k, v in SOURCES[ex][4](df).items():
                    if k not in ('rows', 'listed') and v:
                        t['problems'][k] = t['problems'].get(k, 0) + v
                frames.append(df)
            if frames:
                merged = pd.concat([old, *frames]) if old is not None else pd.concat(frames)
                merged = merged.drop_duplicates(KEYS[ex]).sort_values(['date', 'symbol'])
                if not dry and client is not None:
                    buf = io.BytesIO()
                    merged.to_parquet(buf, index=False, compression='zstd')
                    client.put_object(Bucket=bucket, Key=key(ex, month), Body=buf.getvalue())
            print(f'  {ex} {month}: new days {len(frames)} of {len(days)}', flush=True)
        totals[ex] = t
        print(f'{ex}: {t}', flush=True)
    return totals


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--from', dest='start', default='2025-01-01')
    ap.add_argument('--to', dest='end', default='')
    ap.add_argument('--exchange', default='NSE,BSE,NSE_PR')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args(argv)
    start = datetime.strptime(a.start, '%Y-%m-%d').date()
    end = datetime.strptime(a.end, '%Y-%m-%d').date() if a.end else date.today() - timedelta(days=1)
    client = bucket = store = None
    try:
        import r2_writer
        from insiders_clean.raw_store import RawStore
        client, bucket = r2_writer.r2_client(), r2_writer.BUCKET
        store = None if a.dry_run else RawStore(client, bucket=bucket, collector='price_backfill')
    except Exception as e:  # noqa: BLE001
        print(f'no R2: {type(e).__name__}: {e}')
    try:
        extra = weekend_sessions(client, bucket) if client is not None else set()
        print(f'weekend sessions in range: {sorted(d.isoformat() for d in extra if start <= d <= end)}')
        run(start, end, [x.strip().upper() for x in a.exchange.split(',')], client, bucket, store, a.dry_run, extra=extra)
    except Stop as e:
        print(f'STOPPED: {e}')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
