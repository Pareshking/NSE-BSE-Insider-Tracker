"""One-off probe: what do NSE's and BSE's public daily equity files look like?

    python scripts/bhavcopy_probe.py --out probe/ [--no-r2]

Downloads, for a recent trading day and for a day in Jan 2025, each candidate
file, stores the exact bytes in the write-once raw layer (raw_v2/) when R2
credentials are present, and reports status, size, hash, zip members, CSV
header, row count, series/group counts and two sample rows. Public market
data only; nothing personal. Candidate URLs are patterns the repo already
uses (scripts/update_calendar.py) plus the BSE UDiFF equity file. It records
what it finds; it does not assume any pattern works.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
import zipfile
from datetime import date, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

UA = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0 Safari/537.36')


def candidates(day: date):
    """(label, url) for one day."""
    ymd, dmy, dmy2 = f'{day:%Y%m%d}', f'{day:%d%m%Y}', f'{day:%d%m%y}'
    yield 'nse_udiff_cm', f'https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{ymd}_F_0000.csv.zip'
    yield 'nse_pr_zip', f'https://archives.nseindia.com/archives/equities/bhavcopy/pr/PR{dmy2}.zip'
    mon = f'{day:%b}'.upper()
    yield 'nse_old_cm_bhav', (f'https://nsearchives.nseindia.com/content/historical/EQUITIES/{day:%Y}/{mon}/'
                              f'cm{day:%d}{mon}{day:%Y}bhav.csv.zip')
    yield 'bse_udiff_cm', f'https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{ymd}_F_0000.CSV'
    yield 'bse_old_eq', f'https://www.bseindia.com/download/BhavCopy/Equity/EQ_ISINCODE_{dmy2}.zip'
    yield 'bse_old_eq_std', f'https://www.bseindia.com/download/BhavCopy/Equity/BSE_EQ_BHAVCOPY_{dmy}.ZIP'


def last_weekday(d: date) -> date:
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def describe_csv(body: bytes) -> dict:
    text = body.decode('utf-8-sig', errors='replace')
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return {'csv_rows': 0}
    header = [h.strip() for h in rows[0]]
    out = {'csv_header': header, 'csv_rows': len(rows) - 1, 'sample_rows': rows[1:3]}
    for col in ('SctySrs', 'SERIES', 'Series', 'Group', 'GROUP', 'FinInstrmTp', 'SCTY_SRS', 'SC_GROUP'):
        if col in header:
            i = header.index(col)
            counts = {}
            for r in rows[1:]:
                if len(r) > i:
                    counts[r[i].strip()] = counts.get(r[i].strip(), 0) + 1
            out[f'counts_{col}'] = dict(sorted(counts.items(), key=lambda kv: -kv[1])[:12])
    return out


def inspect(body: bytes) -> dict:
    info = {}
    if body[:2] == b'PK':
        try:
            z = zipfile.ZipFile(io.BytesIO(body))
            info['zip_members'] = [{'name': n.filename, 'bytes': n.file_size} for n in z.infolist()][:12]
            for n in z.infolist():
                if n.filename.lower().endswith(('.csv', '.txt')):
                    info['first_csv_member'] = n.filename
                    info.update(describe_csv(z.read(n.filename)))
                    break
        except Exception as e:  # noqa: BLE001
            info['zip_error'] = f'{type(e).__name__}: {e}'
    else:
        head = body[:300].decode('utf-8', errors='replace')
        if head.lstrip().lower().startswith(('<!doctype', '<html')):
            info['looks_like'] = 'html (blocked or not found page)'
            info['head'] = head[:160]
        else:
            info.update(describe_csv(body))
    return info


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='probe')
    ap.add_argument('--no-r2', action='store_true')
    args = ap.parse_args(argv)
    store = None
    if not args.no_r2:
        try:
            import r2_writer
            from insiders_clean.raw_store import RawStore
            store = RawStore(r2_writer.r2_client(), bucket=r2_writer.BUCKET, collector='bhavcopy_probe')
        except Exception as e:  # noqa: BLE001
            print(f'no R2 store: {type(e).__name__}: {e}')
    s = requests.Session()
    s.headers.update({'User-Agent': UA, 'Accept': '*/*'})
    days = [last_weekday(date.today() - timedelta(days=1)), date(2025, 1, 15)]
    results = []
    for day in days:
        for label, url in candidates(day):
            rec = {'day': day.isoformat(), 'label': label, 'url': url}
            try:
                r = s.get(url, timeout=40)
                rec.update(status=r.status_code, bytes=len(r.content), content_type=r.headers.get('Content-Type'))
                if r.status_code == 200 and r.content:
                    rec['sha256'] = hashlib.sha256(r.content).hexdigest()
                    rec.update(inspect(r.content))
                    if store is not None:
                        saved = store.put('exchange_files', label, r.content, url=url, status=200,
                                          content_type=r.headers.get('Content-Type'), covers={'day': day.isoformat()})
                        rec['raw_key'] = saved['blob_key']
            except Exception as e:  # noqa: BLE001
                rec['error'] = f'{type(e).__name__}: {e}'
            results.append(rec)
            print(json.dumps({k: v for k, v in rec.items() if k not in ('sample_rows', 'csv_header')}, default=str)[:300])
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'probe.json').write_text(json.dumps(results, indent=2, default=str))
    md = ['# Bhavcopy probe', '', '| day | file | status | bytes | rows | columns |', '|---|---|---:|---:|---:|---|']
    for r in results:
        md.append(f"| {r['day']} | {r['label']} | {r.get('status', r.get('error', ''))} | {r.get('bytes', '')} | "
                  f"{r.get('csv_rows', '')} | {', '.join(r.get('csv_header', []))[:260]} |")
    (out / 'probe.md').write_text('\n'.join(md) + '\n')
    print('\n'.join(md))
    return 0


if __name__ == '__main__':
    sys.exit(main())
