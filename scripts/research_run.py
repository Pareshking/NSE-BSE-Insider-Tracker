"""Run pre-registered tests H1/H2 (insider market purchases/sales) and H8 (deal net direction) on the DEVELOPMENT period.

The hold-out (events after 2026-06-30) is never scored unless --final is passed, and --final is for the single
final evaluation. Output is aggregate statistics only (public repo). Every run is a variant: append it to the
variant log in docs/RESEARCH.md.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from insiders_clean import adjust, events as evm, evaluate as ev  # noqa: E402
from price_coverage import load_prefix  # noqa: E402

HZ = (5, 20, 60)


def adjusted_panels(px: pd.DataFrame):
    f = adjust.implied_factors(px)
    last = px['date'].max()
    closes = px[['exchange', 'isin', 'date', 'close']].dropna()
    adj = adjust.adjust_as_of(f, closes, last)
    # open is scaled by the same adjustment ratio as the close of that row
    px = px.merge(adj[['exchange', 'isin', 'date', 'adj_close']], on=['exchange', 'isin', 'date'], how='left')
    ratio = (px['adj_close'] / px['close']).where(px['close'] > 0)
    px['adj_open'] = px['open'] * ratio
    px['close'] = px['adj_close']
    px['open'] = px['adj_open']
    return ev.price_panel(px, 'close'), ev.price_panel(px, 'open')


def evaluate(events: pd.DataFrame, close, op, label: str, conservative=False, buckets=None) -> dict:
    r = ev.forward_returns(events, close, op, horizons=HZ, conservative=conservative)
    bm = ev.benchmark_returns(close, r['entry_pos'], r['entry_basis'], horizons=HZ)
    r = ev.abnormal(r, bm, horizons=HZ)
    out = {'label': label, 'events': int(len(events)), 'conservative_entry': conservative}
    if buckets is not None and len(buckets):
        eg = r['isin'].map(buckets)
        bs = ev.benchmark_returns(close, r['entry_pos'], r['entry_basis'], horizons=HZ, groups=buckets, event_groups=eg)
        for h in HZ:
            r[f'sz_{h}'] = r[f'ret_{h}'] - bs[f'bm_{h}']
        out['events_with_size_bucket'] = int(eg.notna().sum())
        out['by_bucket'] = {str(k): int(v) for k, v in eg.value_counts().items()}
        for h in HZ:
            s = ev.summarise(r, f'sz_{h}')
            if s.get('n', 0) > 1:
                s['mde_5pct_80pwr'] = ev.mde(s['sd'], s['n'])
            out[f'ar_{h}_vs_size_matched'] = s
    for h in HZ:
        s = ev.summarise(r, f'ar_{h}')
        if s.get('n', 0) > 1:
            s['mde_5pct_80pwr'] = ev.mde(s['sd'], s['n'])
        out[f'ar_{h}_vs_market'] = s
        out[f'ret_{h}_gross'] = ev.summarise(r, f'ret_{h}')
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='research')
    ap.add_argument('--final', action='store_true', help='score the hold-out (once, at the end)')
    a = ap.parse_args(argv)
    import r2_writer
    client, bucket = r2_writer.r2_client(), r2_writer.BUCKET
    px = load_prefix(client, bucket, 'prices/daily/')
    px['date'] = pd.to_datetime(px['date'])
    close, op = adjusted_panels(px)
    mc = load_prefix(client, bucket, 'marketcap/daily/')
    mc['date'] = pd.to_datetime(mc['date'])
    buckets = ev.size_buckets(mc, px)
    rd = lambda k: pd.read_parquet(io.BytesIO(client.get_object(Bucket=bucket, Key=k)['Body'].read()))  # noqa: E731
    trades, deals = rd('clean/current/insider_trades.parquet'), rd('clean/current/deals.parquet')
    sets = {'H1 insider market BUY': evm.insider_events(trades, 'BUY'), 'H2 insider market SELL': evm.insider_events(trades, 'SELL'),
            'H8 deals net BUY': evm.deal_events(deals).query("side == 'BUY'"), 'H8 deals net SELL': evm.deal_events(deals).query("side == 'SELL'")}
    results = []
    for label, e in sets.items():
        dev, hold = evm.split(e)
        use = hold if a.final else dev
        for cons in (False, True):
            results.append(evaluate(use, close, op, label + (' [HOLD-OUT]' if a.final else ' [dev]'), cons, buckets))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'results.json').write_text(json.dumps(results, indent=2, default=str))
    md = '### Pre-registered tests (aggregate)\n\n```json\n' + json.dumps(results, indent=2, default=str) + '\n```\n'
    (out / 'results.md').write_text(md)
    print(md)
    return 0


if __name__ == '__main__':
    sys.exit(main())
