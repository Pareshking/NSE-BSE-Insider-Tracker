"""Batch job: the site's price artifacts in R2, so pages never load the full price table. Derived, rewritten each run.

  artifacts/prices_summary_slim.parquet  one row per ISIN: latest close, 52-week range, size bucket
  artifacts/price_history.parquet        adjusted daily closes, last ~400 days, for every ISIN in our filings
  artifacts/market_strip.json            Nifty 500 / Smallcap 250 / Microcap 250: level, vs 200-day average, 1 month
  artifacts/track_events.parquet         every signal event with its forward returns (insiders_clean/track.py)
  artifacts/track_summary.parquet        per signal and horizon: cases, median excess vs Nifty 500, share that beat it
  ledger/forward/<run time>.parquet      forward record: events that fired since the last run, write-once, never edited
  artifacts/forward_outcomes.parquet     every forward-record row with its returns so far (derived, rewritten each run)
  artifacts/basket_positions.parquet     model basket positions from the forward record (insiders_clean/basket.py)
  artifacts/basket_nav.parquet           model basket and Nifty 500, daily, 100 at the first entry"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from insiders_clean import adjust, basket, evidence, slim, track  # noqa: E402
from price_coverage import load_prefix  # noqa: E402

SUMMARY_KEY = 'artifacts/prices_summary_slim.parquet'
HISTORY_KEY, STRIP_KEY = 'artifacts/price_history.parquet', 'artifacts/market_strip.json'
EVENTS_KEY, TRACK_KEY = 'artifacts/track_events.parquet', 'artifacts/track_summary.parquet'
FORWARD_KEY = 'artifacts/forward_outcomes.parquet'
BASKET_POS_KEY, BASKET_NAV_KEY = 'artifacts/basket_positions.parquet', 'artifacts/basket_nav.parquet'


def put(client, bucket, key, df):
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    client.put_object(Bucket=bucket, Key=key, Body=buf.getvalue())


def _flags_now(client, bucket) -> dict:
    """ISIN -> today's tradability flags as text (clean/current/tradability.parquet), {} if absent."""
    try:
        t = pd.read_parquet(io.BytesIO(client.get_object(Bucket=bucket, Key='clean/current/tradability.parquet')['Body'].read()))
    except Exception as e:  # noqa: BLE001 -- no flags table: rows are stamped without flags
        print(f'forward: tradability not read ({e})')
        return {}
    return {i: ','.join(f) for i, f in zip(t['isin'], t['trade_flags']) if f is not None and len(f)}


def filed_actions(client, bucket) -> pd.DataFrame | None:
    """The filed corporate actions (clean/current/actions.parquet from NSE, bse_actions.parquet from BSE) that
    classify a price reset as a bonus or split (insiders_clean/adjust.py). None when neither is there yet."""
    frames = []
    for table in ('actions', 'bse_actions'):
        try:
            frames.append(pd.read_parquet(io.BytesIO(
                client.get_object(Bucket=bucket, Key=f'clean/current/{table}.parquet')['Body'].read())))
        except Exception as e:  # noqa: BLE001 -- without actions the ratio guess decides, as before
            print(f'adjust: {table} not read ({e})')
    frames = [f for f in frames if len(f)]
    return pd.concat(frames, ignore_index=True) if frames else None


def forward(client, bucket, ev, close, nifty, sized, size_of, summ):
    """Append the events that fired since the last run to the forward record
    (a new write-once file per run), stamped with the evidence verdict and the
    tradability flags of that night; rewrite the outcomes of every row and the
    model basket built from them."""
    ledger = load_prefix(client, bucket, track.LEDGER_PREFIX)
    run_at = pd.Timestamp.now(tz='UTC').tz_localize(None).floor('s')
    new = track.new_ledger_rows(ev, ledger, close, run_at)
    if len(new):
        flags = _flags_now(client, bucket)
        new['evidence'] = new['signal'].map(lambda s: evidence.verdict(summ, s)['kind'])
        new['trade_flags'] = new['isin'].map(flags).fillna('')
    if len(new):
        key = f'{track.LEDGER_PREFIX}{run_at:%Y-%m-%dT%H%M%S}.parquet'
        try:
            client.head_object(Bucket=bucket, Key=key)
            print(f'forward: {key} exists, not overwritten')
            return
        except Exception:  # noqa: BLE001 -- absent: write it
            put(client, bucket, key, new)
        ledger = pd.concat([ledger, new], ignore_index=True)
    print(f'forward: {len(new)} new rows, {len(ledger)} in the record')
    if len(ledger):
        ledger['day'] = pd.to_datetime(ledger['day'])
        put(client, bucket, FORWARD_KEY, track.forward_returns(ledger, close, nifty, sized, size_of))
        pos = basket.positions(ledger, close)
        put(client, bucket, BASKET_POS_KEY, pos)
        put(client, bucket, BASKET_NAV_KEY, basket.nav(pos, close, nifty))
        print(f'basket: {len(pos)} positions, {int((pos["status"] == "open").sum()) if len(pos) else 0} open')


def main() -> int:
    import r2_writer
    client, bucket = r2_writer.r2_client(), r2_writer.BUCKET
    px = load_prefix(client, bucket, 'prices/daily/')
    px['date'] = pd.to_datetime(px['date'])
    close, _, factors = slim.adjusted_panels(px, actions=filed_actions(client, bucket))
    print(f'adjust: {adjust.coverage(factors)}')
    meta = (px.dropna(subset=['isin']).assign(_nse=lambda d: d['exchange'].eq('NSE')).sort_values(['_nse', 'date'])
            .drop_duplicates('isin', keep='last')[['isin', 'symbol', 'name', 'exchange']])
    mc = load_prefix(client, bucket, 'marketcap/daily/')
    if len(mc):
        mc['date'] = pd.to_datetime(mc['date'])
        mc = mc[mc['date'] == mc['date'].max()]
    summary = slim.price_summary(close, meta, factors, mc if len(mc) else None)
    put(client, bucket, SUMMARY_KEY, summary)
    print(f'slim: isins {len(summary)}, with bucket {int(summary["mcap_bucket"].notna().sum())}, last session {close.index.max():%Y-%m-%d}')
    clean = {}
    for table in ('insider_trades', 'deals', 'universe'):
        try:
            clean[table] = pd.read_parquet(io.BytesIO(
                client.get_object(Bucket=bucket, Key=f'clean/current/{table}.parquet')['Body'].read()))
        except Exception as e:  # noqa: BLE001 -- a missing clean table means no lines for it, not a failed run
            print(f'history: {table} not read ({e})')
    # Study universe (insiders_clean/universe.py, latest market cap): the site draws no other company,
    # so neither its price lines nor its track record events are kept.
    uni = (set(clean['universe'].loc[clean['universe']['in_universe'].astype(bool), 'isin'])
           if 'universe' in clean and 'in_universe' in clean['universe'] else None)
    isins = set().union(*(set(clean[t]['isin'].dropna()) for t in ('insider_trades', 'deals') if t in clean))
    if uni is not None:
        isins &= uni
    hist = slim.price_history(close, isins)
    put(client, bucket, HISTORY_KEY, hist)
    print(f'history: isins {hist["isin"].nunique()} of {len(isins)} in filings, rows {len(hist)}')
    ix = load_prefix(client, bucket, 'indices/daily/nse/')
    if len(ix):
        ix['date'] = pd.to_datetime(ix['date'])
        strip = slim.market_strip(ix)
        client.put_object(Bucket=bucket, Key=STRIP_KEY, Body=json.dumps(strip).encode())
        print(f'strip: {strip}')
        nifty = ix[ix['symbol'] == 'Nifty 500'].drop_duplicates('date').set_index('date')['close'].sort_index()
        if 'insider_trades' in clean and len(nifty):
            ev = track.events(clean['insider_trades'], clean.get('deals'), close)
            if uni is not None:
                print(f'track: {int((~ev["isin"].isin(uni)).sum())} of {len(ev)} events left out (under Rs 100 Cr today, or no market cap)')
                ev = ev[ev['isin'].isin(uni)]
            sized = {name: ix[ix['symbol'] == name].drop_duplicates('date').set_index('date')['close'].sort_index()
                     for name in track.SIZE_INDEX.values()}
            sized = {k: v for k, v in sized.items() if len(v)}
            print(f'track: size-matched indices found {sorted(sized)}; missing {sorted(set(track.SIZE_INDEX.values()) - set(sized))}')
            size_of = summary.dropna(subset=['mcap_bucket']).set_index('isin')['mcap_bucket'].to_dict()
            fr = track.forward_returns(ev, close, nifty, sized, size_of)
            fr = track.restrictions(fr, px[px['exchange'] == 'NSE'] if 'exchange' in px else px)
            print(f'track: {int(fr["restricted"].sum())} of {len(fr)} events not freely tradable on the day (T2T, SME or locked days)')
            put(client, bucket, EVENTS_KEY, fr)
            summ = track.summary(fr)
            put(client, bucket, TRACK_KEY, summ)
            forward(client, bucket, ev, close, nifty, sized, size_of, summ)
            print(f'track: events {len(fr)}; ' + '; '.join(
                f"{r.signal} {r.horizon} n={r.cases} med={r.median_excess:+.2f}" for r in summ.itertuples() if r.horizon == '1M'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
