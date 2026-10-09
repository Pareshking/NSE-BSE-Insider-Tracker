"""Pre-registered evaluation on the DEVELOPMENT period against one broad baseline (Nifty 500), at multi-quarter horizons.

Registered in docs/RESEARCH.md section J before it was run. Reports absolute return and excess return vs Nifty 500.
The hold-out (events after 2026-06-30) is scored only with --final. Aggregate output only (public repo).
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
from insiders_clean.index_close import BASELINE  # noqa: E402
from price_coverage import load_prefix  # noqa: E402

LAKH = 1e5
HZ = (60, 120)
RISK_HZ = (20, 60, 120)
MATURE_120_END = pd.Timestamp('2026-04-30')     # 120-session results: January to April disclosures only


def adjusted_panels(px: pd.DataFrame):
    f = adjust.inherit_nse(adjust.implied_factors(px))
    adj = adjust.adjust_as_of(f, px[['exchange', 'isin', 'date', 'close']].dropna(), px['date'].max())
    px = px.merge(adj[['exchange', 'isin', 'date', 'adj_close']], on=['exchange', 'isin', 'date'], how='left')
    ratio = (px['adj_close'] / px['close']).where(px['close'] > 0)
    px['open'] = px['open'] * ratio
    px['close'] = px['adj_close']
    return ev.price_panel(px, 'close'), ev.price_panel(px, 'open')


def stats(r: pd.DataFrame, col: str) -> dict:
    s = ev.summarise(r, col)
    if s.get('n', 0) > 1:
        s['mde_5pct_80pwr'] = ev.mde(s['sd'], s['n'])
    return s


def evaluate(events: pd.DataFrame, close, op, nifty, label: str, horizons=HZ) -> dict:
    r = ev.forward_returns(events, close, op, horizons=horizons)
    r = ev.excess(r, ev.index_returns(nifty, close.index, r['entry_pos'], r['entry_basis'], horizons=horizons), horizons)
    out = {'label': label, 'events': int(len(events))}
    for h in horizons:
        d = r
        if h == 120:
            d = r[pd.to_datetime(r['broadcast_date']) <= MATURE_120_END]
            out['PRELIMINARY — SAMPLE MATURING (120 sessions: Jan–Apr 2026 disclosures only)'] = True
        out[f'abs_{h}'] = stats(d, f'ret_{h}')
        out[f'excess_{h}_vs_nifty500'] = stats(d, f'ex_{h}')
        out[f'nifty500_{h}'] = stats(d, f'idx_{h}')
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
    ix = load_prefix(client, bucket, 'indices/daily/')
    ix['date'] = pd.to_datetime(ix['date'])
    nifty = ix[ix['symbol'] == BASELINE].drop_duplicates('date').set_index('date')['close'].sort_index()
    trades = pd.read_parquet(io.BytesIO(client.get_object(Bucket=bucket, Key='clean/current/insider_trades.parquet')['Body'].read()))
    prom = evm.insider_events(trades, 'BUY', roles=evm.PROMOTER_ROLES)
    prom['prior_30d'] = evm.prior_buys(prom)
    allbuy = evm.insider_events(trades, 'BUY')
    sells = evm.insider_events(trades, 'SELL')
    sets = [('P1 promoter/promoter-group open-market buys', prom, HZ),
            ('P2 promoter, day value >= Rs 25 lakh', prom[prom['value'] >= 25 * LAKH], HZ),
            ('P3 promoter, day value >= Rs 50 lakh', prom[prom['value'] >= 50 * LAKH], HZ),
            ('P4 promoter, repeat buy within 30 days', prom[prom['prior_30d'] >= 1], HZ),
            ('P5 promoter, repeat within 30 days and >= Rs 25 lakh', prom[(prom['prior_30d'] >= 1) & (prom['value'] >= 25 * LAKH)], HZ),
            ('R0 all insider open-market buys (reference)', allbuy, HZ),
            ('H2 all insider open-market sells (risk flag)', sells, RISK_HZ)]
    results = []
    for label, e, hz in sets:
        dev, hold = evm.split(e)
        use = hold if a.final else dev
        results.append(evaluate(use, close, op, nifty, label + (' [HOLD-OUT]' if a.final else ' [dev]'), hz))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'results.json').write_text(json.dumps(results, indent=2, default=str))
    print(json.dumps(results, indent=2, default=str))
    return 0


if __name__ == '__main__':
    sys.exit(main())
