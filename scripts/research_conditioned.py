"""Conditioned cuts of H1 (insider open-market BUY) on the DEVELOPMENT period. Cuts C1..C9 are registered in
docs/RESEARCH.md before this was run. Primary metric: 20-session abnormal return vs size-matched peers, judged at the
Bonferroni-adjusted level for the number of cuts. Aggregate output only. Hold-out only with --final."""
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
from insiders_clean import events as evm, evaluate as ev  # noqa: E402
from price_coverage import load_prefix  # noqa: E402
from research_run import HZ, adjusted_panels  # noqa: E402

LAKH = 1e5


def cuts(e: pd.DataFrame) -> dict[str, pd.Series]:
    big = e['value'] >= 10 * LAKH
    pm = e['pct_of_mcap'] >= 0.05
    return {
        'C0 all insider market buys (baseline)': pd.Series(True, index=e.index),
        'C1 promoter / promoter group': e['promoter'],
        'C2 non-promoter (director, KMP, designated, other)': ~e['promoter'],
        'C3 value >= Rs 10 lakh': big,
        'C4 value >= Rs 50 lakh': e['value'] >= 50 * LAKH,
        'C5 value >= 0.05% of market cap': pm,
        'C6 breadth: 2+ insiders or a prior buy in 30 days': (e['n_people'] >= 2) | (e['prior_30d'] >= 1),
        'C7 drawdown > 20% from 252-session high': e['drawdown'] < -0.20,
        'C8 promoter and value >= 0.05% of market cap': e['promoter'] & pm,
        'C9 promoter and drawdown > 20%': e['promoter'] & (e['drawdown'] < -0.20),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='research')
    ap.add_argument('--final', action='store_true')
    a = ap.parse_args(argv)
    import r2_writer
    from research_run import evaluate
    client, bucket = r2_writer.r2_client(), r2_writer.BUCKET
    px = load_prefix(client, bucket, 'prices/daily/')
    px['date'] = pd.to_datetime(px['date'])
    close, op = adjusted_panels(px)
    mc = load_prefix(client, bucket, 'marketcap/daily/')
    mc['date'] = pd.to_datetime(mc['date'])
    buckets = ev.size_buckets(mc, px)
    trades = pd.read_parquet(io.BytesIO(client.get_object(Bucket=bucket, Key='clean/current/insider_trades.parquet')['Body'].read()))
    allb = evm.insider_events(trades, 'BUY')
    allb['prior_30d'] = evm.prior_buys(allb)
    allb['drawdown'] = evm.drawdown_at_signal(allb, close)
    dev, hold = evm.split(allb)
    use = hold if a.final else dev
    n_cuts = len(cuts(use)) - 1
    level = 100 * (1 - 0.05 / n_cuts)
    results = []
    for name, m in cuts(use).items():
        sub = use[m.fillna(False)]
        r = evaluate(sub, close, op, name, False, buckets)
        # re-score the primary metric at the adjusted level
        rr = ev.forward_returns(sub, close, op, horizons=HZ)
        bm = ev.benchmark_returns(close, rr['entry_pos'], rr['entry_basis'], horizons=HZ, groups=buckets, event_groups=rr['isin'].map(buckets))
        rr['sz_20'] = rr['ret_20'] - bm['bm_20']
        r['primary_ar_20_vs_size_adj'] = ev.summarise(rr, 'sz_20', level=level)
        r['adjusted_level'] = level
        results.append(r)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'conditioned.json').write_text(json.dumps(results, indent=2, default=str))
    print(json.dumps(results, indent=2, default=str))
    return 0


if __name__ == '__main__':
    sys.exit(main())
