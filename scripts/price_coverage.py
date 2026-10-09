"""Read-only coverage report for the native price layer (aggregate numbers only; the repo is public).

Checks: (1) every stored price/market-cap day has its raw file in raw_v2 (counts compared per day);
(2) share of 2026 clean insider and deal events with an entry price and enough history, by exchange of the price;
(3) structural adjustment factors per exchange and NSE-vs-BSE agreement on dual-listed ISINs;
(4) how much of the 2026 disclosure universe is BSE-only (no NSE price for the ISIN);
(5) NSE point-in-time market cap coverage of events.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from insiders_clean import adjust  # noqa: E402

DATE_COLS = ('trade_date_to', 'date')


def load_prefix(client, bucket, prefix) -> pd.DataFrame:
    frames, token = [], None
    while True:
        kw = {'Bucket': bucket, 'Prefix': prefix}
        if token:
            kw['ContinuationToken'] = token
        r = client.list_objects_v2(**kw)
        for o in r.get('Contents', []):
            if o['Key'].endswith('.parquet'):
                frames.append(pd.read_parquet(io.BytesIO(client.get_object(Bucket=bucket, Key=o['Key'])['Body'].read())))
        token = r.get('NextContinuationToken')
        if not r.get('IsTruncated'):
            break
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def raw_days(client, bucket, label) -> set[str]:
    """Days covered by fetch records of one raw_v2 dataset."""
    days, token = set(), None
    prefix = f'raw_v2/exchange_files/{label}/'
    while True:
        kw = {'Bucket': bucket, 'Prefix': prefix}
        if token:
            kw['ContinuationToken'] = token
        r = client.list_objects_v2(**kw)
        for o in r.get('Contents', []):
            if '/blobs/' in o['Key'] or not o['Key'].endswith('.json'):
                continue
            try:
                rec = json.loads(client.get_object(Bucket=bucket, Key=o['Key'])['Body'].read())
                d = (rec.get('covers') or {}).get('day')
                if d:
                    days.add(d)
            except Exception:  # noqa: BLE001
                pass
        token = r.get('NextContinuationToken')
        if not r.get('IsTruncated'):
            break
    return days


def event_coverage(events: pd.DataFrame, sessions: pd.DataFrame, name: str) -> dict:
    """Per event: entry session within 7 days after the event date, sessions of history before it."""
    col = next((c for c in DATE_COLS if c in events.columns), None)
    if col is None or 'isin' not in events.columns or sessions.empty:
        return {'events': int(len(events)), 'note': 'no date/isin column or no prices'}
    ev = events.dropna(subset=[col]).copy()
    ev['_d'] = pd.to_datetime(ev[col], errors='coerce')
    ev = ev.dropna(subset=['_d'])
    ev = ev[ev['_d'] >= '2026-01-01']
    has_isin = ev['isin'].fillna('').astype(str).str.len() > 0
    out = {'events_2026': int(len(ev)), 'with_isin': int(has_isin.sum())}
    by_isin = {k: g['date'].to_numpy() for k, g in sessions.groupby('isin')}
    entry = 0
    hist = {5: 0, 20: 0, 60: 0, 120: 0, 250: 0}
    for isin, d in zip(ev.loc[has_isin, 'isin'], ev.loc[has_isin, '_d']):
        arr = by_isin.get(isin)
        if arr is None:
            continue
        after = arr[(arr > np.datetime64(d)) & (arr <= np.datetime64(d + pd.Timedelta(days=7)))]
        before = (arr <= np.datetime64(d)).sum()
        entry += len(after) > 0
        for k in hist:
            hist[k] += before >= k
    n = max(int(has_isin.sum()), 1)
    out.update({'with_entry_price': int(entry), 'entry_share_of_isin_events': round(entry / n, 3),
                **{f'history_ge_{k}_sessions': int(v) for k, v in hist.items()}})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='coverage')
    a = ap.parse_args(argv)
    import r2_writer
    client, bucket = r2_writer.r2_client(), r2_writer.BUCKET
    rep = {}
    px = load_prefix(client, bucket, 'prices/daily/')
    mc = load_prefix(client, bucket, 'marketcap/daily/')
    rep['price_rows'] = int(len(px))
    rep['marketcap_rows'] = int(len(mc))
    if len(px):
        px['date'] = pd.to_datetime(px['date'])
        rep['price_days'] = {ex: int(g['date'].nunique()) for ex, g in px.groupby('exchange')}
        rep['price_date_range'] = {ex: [str(g['date'].min().date()), str(g['date'].max().date())] for ex, g in px.groupby('exchange')}
        rep['validation'] = adjust.coverage(adjust.implied_factors(px))
        for label, ex in (('nse_udiff_cm', 'NSE'), ('bse_udiff_cm', 'BSE')):
            stored = {str(d.date()) for d in px.loc[px['exchange'] == ex, 'date'].unique()}
            raw = raw_days(client, bucket, label)
            rep.setdefault('raw_preserved', {})[ex] = {'parquet_days': len(stored), 'raw_days': len(raw), 'parquet_days_without_raw': len(stored - raw)}
        f = adjust.implied_factors(px)
        st = f[f['kind'] == 'split_bonus']
        rep['structural_events'] = {ex: int((st['exchange'] == ex).sum()) for ex in ('NSE', 'BSE')}
        # for every NSE split/bonus, did BSE (if it traded the ISIN that day) show the same reset?
        nse_ev = st[st['exchange'] == 'NSE'][['isin', 'date', 'factor']]
        bse_all = f[f['exchange'] == 'BSE'][['isin', 'date', 'factor', 'kind']].rename(columns={'factor': 'bse_factor', 'kind': 'bse_kind'})
        j = nse_ev.merge(bse_all, on=['isin', 'date'], how='inner')
        rep['nse_split_bonus_seen_on_bse'] = {
            'nse_events_also_on_bse': int(len(j)),
            'bse_same_reset_within_2pct': int(((j['bse_factor'] / j['factor'] - 1).abs() < 0.02).sum()),
            'bse_kind_counts': {str(k): int(v) for k, v in j['bse_kind'].value_counts().items()}}
        nse_isins = set(px.loc[px['exchange'] == 'NSE', 'isin'])
        sess = adjust.session_frame(px)
        for name in ('insider_trades', 'deals'):
            try:
                ev = pd.read_parquet(io.BytesIO(client.get_object(Bucket=bucket, Key=f'clean/current/{name}.parquet')['Body'].read()))
            except Exception as e:  # noqa: BLE001
                rep[name] = {'error': type(e).__name__}
                continue
            rep[name] = event_coverage(ev, sess.drop_duplicates(['isin', 'date']), name)
            if 'isin' in ev.columns:
                ids = ev['isin'].dropna().astype(str)
                ids = ids[ids != '']
                rep[name]['isin_events_not_on_nse_price_table'] = int((~ids.isin(nse_isins)).sum())
                rep[name]['isin_events_total'] = int(len(ids))
    if len(mc):
        mc['date'] = pd.to_datetime(mc['date'])
        rep['marketcap_days'] = int(mc['date'].nunique())
        rep['marketcap_date_range'] = [str(mc['date'].min().date()), str(mc['date'].max().date())]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'coverage.json').write_text(json.dumps(rep, indent=2, default=str))
    md = '### Price layer coverage (aggregate)\n\n```json\n' + json.dumps(rep, indent=2, default=str) + '\n```\n'
    (out / 'coverage.md').write_text(md)
    print(md)
    return 0


if __name__ == '__main__':
    sys.exit(main())
