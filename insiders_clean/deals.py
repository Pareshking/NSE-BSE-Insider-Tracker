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
3. NSE/BSE copies of one leg are both kept and linked; NSE is primary.
4. `counterparties`: who was on the other side in that security that day,
   so a promoter's block sale shows who bought it.

Intraday round trips (same client buying and selling the same size on the
same day) are already dropped by scripts/r2_writer.py before data reaches R2.
"""
from __future__ import annotations

import hashlib
import json

import numpy as np
import pandas as pd

from .dates import parse_dates
from .entities import add_entity_columns
from .insider import VALUE_SHARE_OF_MCAP_REVIEW, _col, _num
from .securities import SecurityMaster, display_name

MAX_COUNTERPARTIES = 5


def _id(parts) -> str:
    return hashlib.sha1('|'.join('' if p is None else str(p) for p in parts).encode()).hexdigest()[:16]


def clean_deals(raw: pd.DataFrame, master: SecurityMaster, report, run_date) -> pd.DataFrame:
    """canonical bulk + block rows (both exchanges; `exchange` and
    `category` columns) -> clean deals."""
    t = report.table('deals')
    if raw is None or raw.empty:
        return pd.DataFrame()
    t['input_rows'] += len(raw)
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
    df['isin'] = [r[0] or w for r, w in zip(resolved, writer_isin)]
    df['security_match'] = [r[1] if r[0] or not w else 'writer_isin' for r, w in zip(resolved, writer_isin)]
    df['security_key'] = df['isin'].fillna(df['exchange'] + ':' + df['symbol'].astype(str))
    report.unmatched(df.loc[df['isin'].isna(), ['exchange', 'symbol', 'company_raw']]
                     .rename(columns={'company_raw': 'name'}).astype(str).drop_duplicates()
                     .assign(table='deals').to_dict('records'))

    # 1. same execution in both feeds
    trade_key = ['exchange', 'security_key', 'client_id', 'date', 'side', 'quantity', 'price']
    df = df.sort_values('feed')  # 'block' before 'bulk': the block copy is kept
    feeds = df.groupby(trade_key, dropna=False)['feed'].transform(lambda s: ','.join(sorted(set(s))))
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
                 value=('value', 'sum'), trades=('source_id', 'size'),
                 feeds=('feeds', lambda s: ','.join(sorted({f for v in s for f in v.split(',')}))),
                 source_ids=('source_id', lambda s: json.dumps(list(s)))).reset_index()
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
    legs['pct_of_mcap'] = (legs['value'] / legs['market_cap'] * 100).where(legs['market_cap'] > 0)
    legs['signed_value'] = legs['value'] * legs['side'].map({'BUY': 1, 'SELL': -1})
    legs['deal_id'] = [_id(p) for p in zip(legs['exchange'], legs['security_key'], legs['client_id'],
                                            legs['date'], legs['side'])]

    # 4. other side of the tape in that security that day
    day_key = ['exchange', 'security_key', 'date']
    by_side = (legs.dropna(subset=['client_name']).sort_values('value', ascending=False)
               .groupby(day_key + ['side'], dropna=False)['client_name']
               .agg(lambda s: '; '.join(s.head(MAX_COUNTERPARTIES))))
    opposite = legs['side'].map({'BUY': 'SELL', 'SELL': 'BUY'})
    legs['counterparties'] = [by_side.get((e, k, d, o)) if o else None for e, k, d, o in
                              zip(legs['exchange'], legs['security_key'], legs['date'], opposite)]

    # 3. NSE/BSE copies of one leg
    legs['is_primary'] = True
    legs['primary_id'] = None
    legs['listed_on'] = legs['exchange']
    linkable = legs.dropna(subset=['isin', 'client_id', 'date', 'side'])
    for _, grp in linkable.groupby(['isin', 'client_id', 'date', 'side', 'quantity']):
        if grp['exchange'].nunique() < 2:
            continue
        nse = grp[grp['exchange'] == 'nse']
        primary = nse.index[0] if len(nse) else grp.index[0]
        others = grp.index.drop(primary)
        legs.loc[others, 'is_primary'] = False
        legs.loc[others, 'primary_id'] = legs.at[primary, 'deal_id']
        legs.loc[grp.index, 'listed_on'] = ','.join(sorted(grp['exchange'].unique()))

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
            'client_id', 'client_name', 'side', 'quantity', 'price', 'value', 'signed_value',
            'trades', 'market_cap', 'pct_of_mcap', 'counterparties', 'source_ids',
            'flags', 'needs_review']
    out = legs[cols].reset_index(drop=True)
    t['output_rows'] += len(out)
    t['by_exchange'] = out['exchange'].value_counts().to_dict()
    return out
