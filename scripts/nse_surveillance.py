"""Nightly: NSE surveillance lists and price bands -> tradability flags per ISIN.

    python scripts/nse_surveillance.py [--dry-run]

Fetches NSE's ASM, GSM and ESM lists and the security list with price bands (insiders_clean/tradability.py says
what each holds), saves each answer byte for byte for the write-once raw layer (scripts/raw_capture.py; the
nightly's raw_flush step stores it in raw_v2/nse/{asm|gsm|esm|sec_list}/), and keeps one parsed snapshot a day in

    archive/tradability/surveillance/year=YYYY.parquet   one row per day, list and ISIN
    archive/tradability/sec_list/year=YYYY.parquet       one row per day, symbol and series (band)

A rerun the same day replaces that day's snapshot. Then it rebuilds clean/current/tradability.parquet from the
snapshots and the last three months of NSE bhavcopy (prices/daily/nse/), and writes
clean/reports/tradability/{date}.json. A 401/403/429 stops the NSE calls; the table is still rebuilt from the
snapshots already stored, and its `as_of` says which day they are from. Prints counts only.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from collectors.nse_events.client import Blocked, NSEClient  # noqa: E402
from insiders_clean import tradability  # noqa: E402
from raw_capture import capture  # noqa: E402

SOURCES = {'asm': 'https://www.nseindia.com/api/reportASM', 'gsm': 'https://www.nseindia.com/api/reportGSM',
           'esm': 'https://www.nseindia.com/api/reportESM',
           'sec_list': 'https://nsearchives.nseindia.com/content/equities/sec_list.csv'}
ARCHIVE = {'surveillance': 'archive/tradability/surveillance/', 'sec_list': 'archive/tradability/sec_list/'}
CLEAN_KEY = 'clean/current/tradability.parquet'
PRICE_MONTHS = 3
IST = timezone(timedelta(hours=5, minutes=30))


def get_bytes(nse: NSEClient, url: str) -> requests.Response:
    """The client's own pacing, retries and hard stop, but the response itself (exact bytes for raw)."""
    nse.warm_up()
    last = None
    for _ in range(nse.retries):
        nse._wait()
        try:
            r = nse.s.get(url, timeout=60)
        except requests.RequestException as exc:
            last = exc
            continue
        if r.status_code in (401, 403, 429):
            raise Blocked(f'HTTP {r.status_code} for {url}')
        if r.status_code >= 500:
            last = RuntimeError(f'HTTP {r.status_code}')
            continue
        if r.status_code != 200:
            raise RuntimeError(f'HTTP {r.status_code} for {url}')
        if r.content.lstrip()[:1] == b'<':
            last = RuntimeError('an HTML page in place of data')
            continue
        return r
    raise RuntimeError(f'{url}: gave up after {nse.retries} tries ({last})')


def fetch_all(nse: NSEClient, day: date, report: dict) -> dict:
    """name -> body bytes for every source that answered; stops at the first refusal."""
    out = {}
    for name, url in SOURCES.items():
        try:
            r = get_bytes(nse, url)
        except Blocked as exc:
            report['notes'].append(f'{name}: NSE refused ({exc}); no further NSE calls')
            break
        except Exception as exc:  # noqa: BLE001 -- one source failing must not stop the others
            report['notes'].append(f'{name}: fetch failed ({type(exc).__name__}: {exc})')
            continue
        capture('nse', name, r.content, url=url, status=r.status_code, content_type=r.headers.get('Content-Type'),
                covers={'day': day.isoformat()})
        out[name] = r.content
    return out


def parse_all(bodies: dict, day: date, report: dict):
    surv = sec = None
    if all(k in bodies for k in ('asm', 'gsm', 'esm')):  # a part-day snapshot would end every "since" run
        try:
            surv = tradability.parse_surveillance(*(json.loads(bodies[k]) for k in ('asm', 'gsm', 'esm')), day)
        except Exception as exc:  # noqa: BLE001
            report['notes'].append(f'surveillance: not parsed ({type(exc).__name__}: {exc})')
    elif any(k in bodies for k in ('asm', 'gsm', 'esm')):
        report['notes'].append('surveillance: not every list answered; no snapshot kept for today')
    if 'sec_list' in bodies:
        try:
            sec = tradability.parse_sec_list(bodies['sec_list'], day)
        except Exception as exc:  # noqa: BLE001
            report['notes'].append(f'sec_list: not parsed ({type(exc).__name__}: {exc})')
    return surv, sec


def merge_day(r2, prefix: str, new: pd.DataFrame | None, day: date) -> pd.DataFrame | None:
    """Replace `day` in its year partition with `new`; return every snapshot stored."""
    from clean_writer import list_keys, put_parquet, read_parquet
    if new is not None and not new.empty:
        key = f'{prefix}year={day.year}.parquet'
        old = read_parquet(r2, key)
        old = old[pd.to_datetime(old['date']) != pd.Timestamp(day)] if old is not None else None
        put_parquet(r2, key, pd.concat([old, new], ignore_index=True) if old is not None and len(old) else new)
    frames = [read_parquet(r2, k) for k in sorted(list_keys(r2, prefix)) if k.endswith('.parquet')]
    frames = [f for f in frames if f is not None and not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else None


def recent_prices(r2, months: int = PRICE_MONTHS) -> pd.DataFrame:
    from clean_writer import list_keys, read_parquet
    keys = sorted(k for k in list_keys(r2, 'prices/daily/nse/') if k.endswith('.parquet'))[-months:]
    frames = [read_parquet(r2, k) for k in keys]
    frames = [f for f in frames if f is not None and not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def summary(t: pd.DataFrame) -> dict:
    labels = pd.Series([f.split(' ')[0] if not f[0].isdigit() else f for x in t['trade_flags'] for f in x], dtype=str)
    return {'isins': int(len(t)), 'flagged': int(t['trade_flags'].map(len).gt(0).sum()),
            'by_flag': {k: int(v) for k, v in labels.value_counts().items()},
            'as_of': str(t['as_of'].max())[:10] if t['as_of'].notna().any() else None,
            'last_price_date': str(t['last_price_date'].max())[:10] if t['last_price_date'].notna().any() else None,
            'band_matched': int(t['band_pct'].notna().sum())}


def run(r2, nse: NSEClient, day: date) -> dict:
    from clean_writer import put, put_parquet
    report = {'run_date': day.isoformat(), 'notes': []}
    bodies = fetch_all(nse, day, report)
    surv, sec = parse_all(bodies, day, report)
    report['fetched'] = {k: len(v) for k, v in bodies.items()}
    report['parsed'] = {'surveillance': 0 if surv is None else len(surv), 'sec_list': 0 if sec is None else len(sec)}
    surv_hist = merge_day(r2, ARCHIVE['surveillance'], surv, day)
    sec_hist = merge_day(r2, ARCHIVE['sec_list'], sec, day)
    if sec_hist is not None:
        sec_hist = sec_hist[pd.to_datetime(sec_hist['date']) == pd.to_datetime(sec_hist['date']).max()]
    px = recent_prices(r2)
    table = tradability.build(surv_hist, sec_hist, px)
    put_parquet(r2, CLEAN_KEY, table)
    report['clean'] = summary(table)
    report['snapshot_days'] = 0 if surv_hist is None else int(pd.to_datetime(surv_hist['date']).nunique())
    report['nse_calls'] = nse.calls
    put(r2, f'clean/reports/tradability/{day.isoformat()}.json', json.dumps(report, indent=2, default=str).encode(),
        'application/json')
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--dry-run', action='store_true', help='fetch and parse, print counts, write nothing to R2')
    a = ap.parse_args(argv)
    td = os.environ.get('TARGET_DATE', '').strip()
    day = date.fromisoformat(td) if td else datetime.now(IST).date()
    if a.dry_run:
        report = {'run_date': day.isoformat(), 'notes': []}
        surv, sec = parse_all(fetch_all(NSEClient(), day, report), day, report)
        if surv is not None:
            report['clean'] = summary(tradability.build(surv, sec, None))
    else:
        from r2_writer import r2_client
        report = run(r2_client(), NSEClient(), day)
    print(json.dumps({k: v for k, v in report.items() if k != 'notes'}, default=str))
    for n in report['notes']:
        print(f'  note: {n}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
