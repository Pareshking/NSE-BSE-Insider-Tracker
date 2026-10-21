"""Bulk and block deals -> the clean `deals` table.

Grain: one row per client, security, day and side ("leg"). That is the
grain every signal needs (a fund's footprint, net flow in a stock), and the
one a reader recognises: ACMEUNIV's three same-day buys by one client are
one decision, shown as one line with `trades` = 3.

Steps, each counted in the cleaning report:
1. Same trade in both feeds. NSE and BSE each publish a bulk and a block
   feed, and one execution can appear in both (Ather Energy, 28 Aug 2026:
   one deal shown as Bulk SELL + Bulk BUY + Block SELL + Block BUY). Same
   exchange, client, security, day, side, quantity and price in both feeds
   -> one row, `feeds` = 'block,bulk'.
2. Same-day roll-up: legs with the same client, security, day and side are
   summed; price becomes the volume-weighted average.
3. NSE and BSE legs are separate executions (each exchange publishes the
   deals done on its own platform): both are primary and both count. Equal
   legs on the two exchanges are marked `same_size_on_other_exchange`.
4. `counterparties`: who was on the other side in that security that day,
   so a promoter's block sale shows who bought it.

Intraday round trips (same client buying and selling the same size on the
same day) are flagged by scripts/r2_writer.py (`intraday_round_trip`), kept
in the raw layer, and excluded here with a counted reason.
"""
from __future__ import annotations

import hashlib
import json

import numpy as np
import pandas as pd

from . import market_cap
from .dates import parse_dates
from .entities import add_entity_columns, per_group
from .insider import VALUE_SHARE_OF_MCAP_REVIEW, _col, _num
from .missing import as_flag, present
from .securities import SecurityMaster, display_name

MAX_COUNTERPARTIES = 5
# Market makers and arbitrage desks. On NSE bulk/block deals from 09 Jul to
# 07 Oct 2026, 31 clients with 50+ legs made 62% of all legs, and 30 of them
# bought and sold within 20% of the same value (Junomoneta, QE Securities,
# HRTI, Microcurves, NK Securities, iRage, AlphaGrep, Jump ...). They supply
# liquidity; they are not building positions, so they are labelled and kept
# out of signals. Measured per calendar quarter, so a fund that buys one
# year and sells the next is not mistaken for one.
MM_MIN_LEGS_PER_QUARTER = 40
MM_MIN_BALANCE = 0.8


def _id(parts) -> str:
    return hashlib.sha1('|'.join('' if p is None else str(p) for p in parts).encode()).hexdigest()[:16]


CSV_SOURCES = ('nse_nightly_deals_csv', 'nse_historical_deals_csv')


def _drop_json_copies(raw: pd.DataFrame, report) -> pd.DataFrame:
    """The nightly collector used to read the JSON form of NSE's deals feed
    (capped at 70 rows a call) and now reads the uncapped CSV. A deal both
    forms returned is in the archive twice with different row ids. Where a CSV
    row and an older-form row agree on exchange, feed, day, symbol, client,
    side, quantity and price, the older-form copy goes (counted). Only across
    forms: rows of one form are never compared with each other. (Rows with
    identical content share a row id, so the archive keeps them once whatever
    the form; the raw bytes in raw_v2 keep every line.)"""
    if 'source' not in raw.columns:
        return raw
    src = raw['source'].astype('string')
    is_csv = src.isin(CSV_SOURCES).fillna(False).to_numpy(dtype=bool, copy=True)
    if not is_csv.any() or is_csv.all():
        return raw
    client = (_col(raw, 'canonical_client').astype('string').str.upper()
              .str.replace(r'[^A-Z0-9]+', ' ', regex=True).str.strip())
    key = (raw['exchange'].astype(str) + '|' + raw['category'].astype(str) + '|'
           + parse_dates(_col(raw, 'canonical_event_date', 'BD_DT_DATE')).astype(str) + '|'
           + _col(raw, 'canonical_symbol', 'BD_SYMBOL').astype(str) + '|' + client.astype(str) + '|'
           + _col(raw, 'canonical_side').astype(str) + '|' + _num(_col(raw, 'canonical_quantity')).astype(str)
           + '|' + _num(_col(raw, 'canonical_price')).round(2).astype(str))
    csv_keys = set(key[is_csv])
    older_copy = (~is_csv) & key.isin(csv_keys).to_numpy(dtype=bool, copy=True)
    if older_copy.any():
        report.removed('deals', 'same_deal_in_older_json_form', _col(raw.loc[older_copy], 'canonical_event_id'))
        raw = raw.loc[~older_copy]
    return raw


def clean_deals(raw: pd.DataFrame, master: SecurityMaster, report, run_date,
                market_cap_daily: pd.DataFrame | None = None) -> pd.DataFrame:
    """canonical bulk + block rows (both exchanges; `exchange` and
    `category` columns) -> clean deals. `market_cap_daily`
    (insiders_clean.market_cap.load_daily) dates the market cap behind
    `pct_of_mcap`; without it every leg takes the latest."""
    t = report.table('deals')
    if raw is None or raw.empty:
        return pd.DataFrame()
    t['input_rows'] += len(raw)
    # Intraday round trips are flagged by the writer, never dropped from raw;
    # they are excluded here, counted, and the archive keeps them.
    if 'intraday_round_trip' in raw.columns:
        rt = as_flag(raw['intraday_round_trip'])
        if rt.any():
            report.removed('deals', 'intraday_round_trip', _col(raw.loc[rt], 'canonical_event_id'))
            raw = raw.loc[~rt]
        if raw.empty:
            return pd.DataFrame()
    raw = _drop_json_copies(raw, report)
    df = pd.DataFrame(index=raw.index)
    df['source_id'] = _col(raw, 'canonical_event_id')
    df['exchange'] = raw['exchange'].astype(str).str.lower()
    df['feed'] = raw['category'].astype(str).str.replace('_deals', '', regex=False)
    df['symbol'] = _col(raw, 'canonical_symbol', 'BD_SYMBOL', 'security_code')
    df['company_raw'] = _col(raw, 'canonical_company', 'BD_SCRIP_NAME', 'company')
    df['client_raw'] = _col(raw, 'canonical_client', 'BD_CLIENT_NAME', 'person')
    df['side'] = _col(raw, 'canonical_side')
    df['quantity'] = _num(_col(raw, 'canonical_quantity'))
    df['price'] = _num(_col(raw, 'canonical_price'))
    df['date'] = parse_dates(_col(raw, 'canonical_event_date', 'BD_DT_DATE', 'event_date'))
    df = add_entity_columns(df, 'client_raw', prefix='client')

    resolved = [master.resolve(ex, s) for ex, s in zip(df['exchange'], df['symbol'])]
    writer_isin = _col(raw, 'canonical_isin')
    df['isin'] = [r[0] or (w if present(w) else None) for r, w in zip(resolved, writer_isin)]
    df['security_match'] = [r[1] if r[0] or not present(w) else 'writer_isin' for r, w in zip(resolved, writer_isin)]
    df['security_key'] = df['isin'].fillna(df['exchange'] + ':' + df['symbol'].astype(str))
    report.unmatched(df.loc[df['isin'].isna(), ['exchange', 'symbol', 'company_raw']]
                     .rename(columns={'company_raw': 'name'}).astype(str).drop_duplicates()
                     .assign(table='deals').to_dict('records'))

    # 1. same execution in both feeds
    trade_key = ['exchange', 'security_key', 'client_id', 'date', 'side', 'quantity', 'price']
    df = df.sort_values('feed')  # 'block' before 'bulk': the block copy is kept
    g = df.groupby(trade_key, dropna=False, sort=False)
    feeds = pd.Series(per_group(g.ngroup().to_numpy(), df['feed'], lambda c: ','.join(sorted(set(c)))),
                      dtype=object)[g.ngroup().to_numpy()].set_axis(df.index)
    dup = df.duplicated(subset=trade_key, keep='first')
    report.removed('deals', 'same_trade_in_both_feeds', df.loc[dup, 'source_id'])
    df = df.assign(feeds=feeds)[~dup].copy()

    # 2. same-day roll-up per client, security, day, side
    df['value'] = df['quantity'] * df['price']
    leg_key = ['exchange', 'security_key', 'client_id', 'date', 'side']
    g = df.groupby(leg_key, dropna=False, sort=False)
    legs = g.agg(isin=('isin', 'first'), security_match=('security_match', 'first'),
                 symbol=('symbol', 'first'), company_raw=('company_raw', 'first'),
                 client_name=('client_name', 'first'), quantity=('quantity', 'sum'),
                 value=('value', 'sum'), trades=('source_id', 'size')).reset_index()
    codes = g.ngroup().to_numpy()  # same group order as the agg (sort=False)
    legs['feeds'] = per_group(codes, df['feeds'], lambda c: ','.join(sorted({f for v in c for f in v.split(',')})))
    legs['source_ids'] = per_group(codes, df['source_id'], lambda c: json.dumps(list(c)))
    rolled = len(df) - len(legs)
    if rolled:
        t['rolled_up_rows'] = t.get('rolled_up_rows', 0) + int(rolled)
    legs['price'] = (legs['value'] / legs['quantity']).where(legs['quantity'] > 0)

    recs = {i: master.record(i) for i in legs['isin'].dropna().unique()}
    legs['company'] = [(recs.get(i) or {}).get('display_name') or display_name(c)
                       for i, c in zip(legs['isin'], legs['company_raw'])]
    legs['nse_symbol'] = legs['isin'].map(lambda i: (recs.get(i) or {}).get('nse_symbol'))
    legs['bse_code'] = legs['isin'].map(lambda i: (recs.get(i) or {}).get('bse_code'))
    legs['market_cap'] = pd.to_numeric(legs['isin'].map(lambda i: (recs.get(i) or {}).get('market_cap')),
                                       errors='coerce')
    # % of market cap on the deal's day (NSE's daily mcap file); `market_cap` stays the latest (audit W1).
    at = market_cap.at_trade_date(legs['nse_symbol'], legs['date'], market_cap_daily, legs['market_cap'],
                                  fallback_symbols=legs['symbol'].where(legs['exchange'].eq('nse')))
    for c in at.columns:
        legs[c] = at[c].to_numpy()
    t['market_cap_basis'] = {str(k): int(v) for k, v in legs['market_cap_basis'].value_counts().items()}
    legs['pct_of_mcap'] = (legs['value'] / legs['market_cap_at_trade'] * 100).where(legs['market_cap_at_trade'] > 0)
    legs['signed_value'] = legs['value'] * legs['side'].map({'BUY': 1, 'SELL': -1})
    legs['deal_id'] = [_id(p) for p in zip(legs['exchange'], legs['security_key'], legs['client_id'],
                                            legs['date'], legs['side'])]

    # Market makers, per client per quarter, each quarter judged on the 91 days
    # ending at its last day -- or at the latest deal for the quarter still
    # running. Counting only the quarter's own days failed at a quarter start:
    # on 07 Oct 2026, seven days into Q4, no desk had 40 legs yet, and QE
    # Securities, iRage, HRTI and Junomoneta showed up as "handshakes".
    dates = pd.to_datetime(legs['date'])
    quarter = dates.dt.to_period('Q')
    latest = dates.max()
    side_val = legs.assign(_buy=legs['value'].where(legs['side'] == 'BUY', 0.0),
                           _sell=legs['value'].where(legs['side'] == 'SELL', 0.0))
    is_mm, mm_clients = {}, set()  # dict lookups: a Series.get per leg is slow on a full history
    for q in quarter.dropna().unique():
        end = min(q.end_time.normalize(), latest)
        win = side_val[(dates > end - pd.Timedelta(days=91)) & (dates <= end)]
        per = win.groupby('client_id').agg(n=('deal_id', 'size'), b=('_buy', 'sum'), s=('_sell', 'sum'))
        balance = per[['b', 's']].min(axis=1) / per[['b', 's']].max(axis=1).replace(0, np.nan)
        for c in per.index[(per['n'] >= MM_MIN_LEGS_PER_QUARTER) & (balance >= MM_MIN_BALANCE)]:
            is_mm[(c, q)] = True
            mm_clients.add(c)
    legs['client_is_market_maker'] = [bool(is_mm.get((c, q), False)) for c, q in zip(legs['client_id'], quarter)]
    t['market_maker_clients'] = sorted(mm_clients)[:50]
    t['market_maker_legs'] = int(legs['client_is_market_maker'].sum())

    # 4. other side of the tape in that security that day
    day_key = ['exchange', 'security_key', 'date']
    # Real buyers and sellers first, market makers after them.
    ranked = (legs.dropna(subset=['client_name'])
              .sort_values(['client_is_market_maker', 'value'], ascending=[True, False]))
    gs = ranked.groupby(day_key + ['side'], dropna=False)
    by_side = pd.Series(per_group(gs.ngroup().to_numpy(), ranked['client_name'],
                                  lambda c: '; '.join(c[:MAX_COUNTERPARTIES])),
                        index=gs.size().index, dtype=object)
    opposite = legs['side'].map({'BUY': 'SELL', 'SELL': 'BUY'})
    names_by_side = by_side.to_dict()
    # A missing date is looked up as before (the index holds it as NaN).
    legs['counterparties'] = [(names_by_side.get((e, k, d, o)) if d is not None else by_side.get((e, k, d, o)))
                              if o else None for e, k, d, o in
                              zip(legs['exchange'], legs['security_key'], legs['date'], opposite)]

    # 3. NSE and BSE legs are separate executions. Each exchange publishes the
    # bulk and block deals done on its own platform (the 0.5% bulk test is per
    # exchange), so a client's NSE leg and BSE leg on one day are two trades,
    # even of equal size: both stay primary and both count (audit W8). The
    # columns `is_primary`, `primary_id` and `listed_on` stay for the tables'
    # shape; equal-size legs on the other exchange are only marked
    # (`same_size_on_other_exchange`) and counted, for the production check.
    legs['is_primary'] = True
    legs['primary_id'] = None
    legs['listed_on'] = legs['exchange']
    twin_key = ['isin', 'client_id', 'date', 'side', 'quantity']
    keyed = legs.dropna(subset=['isin', 'client_id', 'date', 'side', 'quantity'])
    both = keyed.groupby(twin_key)['exchange'].transform('nunique') > 1
    legs['same_size_on_other_exchange'] = False
    legs.loc[both[both].index, 'same_size_on_other_exchange'] = True
    twins = keyed[both]
    same_price = (twins.groupby(twin_key)['price'].transform(lambda p: p.max() - p.min())
                  <= 0.0005 * twins['price']) if len(twins) else pd.Series(dtype=bool)
    t['same_size_on_both_exchanges'] = {'legs': int(both.sum()), 'legs_at_the_same_price': int(same_price.sum())}

    flags = [[] for _ in range(len(legs))]

    def flag(mask, name):
        for i in np.flatnonzero(np.asarray(mask.fillna(False), dtype=bool)):
            flags[i].append(name)

    flag(legs['isin'].isna(), 'unmatched_security')
    flag(~(legs['price'] > 0) | ~(legs['quantity'] > 0), 'missing_price_or_quantity')
    flag(legs['side'].isna(), 'missing_side')
    flag(legs['pct_of_mcap'] > VALUE_SHARE_OF_MCAP_REVIEW * 100, 'value_over_25pct_of_mcap')
    flag(pd.to_datetime(legs['date']) > pd.Timestamp(run_date), 'date_in_future')
    legs['flags'] = [','.join(f) for f in flags]
    legs['needs_review'] = legs['flags'] != ''
    report.flagged('deals', flags)

    cols = ['deal_id', 'exchange', 'listed_on', 'is_primary', 'primary_id', 'feeds', 'date',
            'isin', 'security_match', 'company', 'nse_symbol', 'bse_code', 'symbol',
            'client_id', 'client_name', 'client_is_market_maker', 'side', 'quantity', 'price', 'value', 'signed_value',
            'trades', 'market_cap', 'market_cap_at_trade', 'market_cap_date', 'market_cap_basis', 'pct_of_mcap',
            'same_size_on_other_exchange', 'counterparties', 'source_ids',
            'flags', 'needs_review']
    out = legs[cols].reset_index(drop=True)
    t['output_rows'] += len(out)
    t['by_exchange'] = out['exchange'].value_counts().to_dict()
    return out
