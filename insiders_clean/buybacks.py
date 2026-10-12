"""Buybacks: one row per buyback, with its price and route where NSE's
structured lists give them (TODO 12). No I/O; collectors/nse_events/run_daily.py
calls build() and writes clean/current/buybacks.parquet.

Sources, all NSE, confirmed 12 Oct 2026:
* tender offers (`/api/liveTenderPast-issues`, `liveTenderActive-issues`):
  buybacks by tender offer since 2015 with the offer price, shares sought,
  shares tendered and the offer dates. Route = tender offer.
* daily buyback reports (`/api/corporates-daily-buyback`): a company buying
  back on the market files one each day. Route = open market; the maximum
  price is only in the PDF announcement, so it stays empty.
* corporate actions with a 'Buy Back' purpose (record date, no price, no
  route). Matched to a tender offer of the same symbol that opens on or after
  the record date and within TENDER_AFTER_RECORD_DAYS; unmatched ones keep an
  empty route rather than a guess.
"""
from __future__ import annotations

import hashlib

import pandas as pd

TENDER_AFTER_RECORD_DAYS = 60   # tender opens within this many days of the record date
OPEN_MARKET_GAP_DAYS = 90       # daily reports further apart than this start a new buyback
SINCE = pd.Timestamp('2025-01-01')  # tender buybacks kept from here (the product year and its lead-in)

COLUMNS = ['buyback_id', 'symbol', 'company', 'route', 'offer_price', 'shares_sought', 'offer_value',
           'shares_tendered', 'times_tendered', 'offer_open', 'offer_close', 'record_date', 'ex_date',
           'daily_reports', 'first_report', 'last_report', 'source']


def _id(*parts) -> str:
    return hashlib.sha1('|'.join(str(p) for p in parts).encode()).hexdigest()[:20]


def _d(s):
    return pd.to_datetime(s, errors='coerce')


def build(tenders: pd.DataFrame | None, daily: pd.DataFrame | None, actions: pd.DataFrame | None) -> tuple[pd.DataFrame, dict]:
    """(buybacks, report counts)."""
    rep = {}
    rows = []
    t = tenders[tenders['offer_type'] == 'buyback'].copy() if tenders is not None and not tenders.empty else pd.DataFrame()
    if not t.empty:
        t['offer_open'], t['offer_close'] = _d(t['offer_open']), _d(t['offer_close'])
        t = t[t['offer_open'] >= SINCE]
    a = actions[actions['purpose'] == 'buyback'].copy() if actions is not None and not actions.empty else pd.DataFrame()
    used = set()
    for r in a.to_dict('records'):
        rec = _d(r.get('record_date'))
        rec = rec if pd.notna(rec) else _d(r.get('ex_date'))
        match = None
        if pd.notna(rec) and not t.empty:
            c = t[(t['symbol'] == r['symbol']) & (t['offer_open'] >= rec)
                  & (t['offer_open'] <= rec + pd.Timedelta(days=TENDER_AFTER_RECORD_DAYS))]
            if len(c):
                match = c.sort_values('offer_open').iloc[0]
        row = {'symbol': r['symbol'], 'company': r.get('company_display') or r.get('company'),
               'isin': r.get('isin'), 'record_date': _d(r.get('record_date')), 'ex_date': _d(r.get('ex_date')),
               'source': 'NSE corporate actions'}
        if match is not None:
            used.add(match['event_id'])
            row.update(_tender_fields(match), source='NSE corporate actions + tender offers')
        row['buyback_id'] = _id('bb', r['symbol'], row['record_date'], row.get('offer_open'))
        rows.append(row)
    for _, m in (t[~t['event_id'].isin(used)].iterrows() if not t.empty else []):
        rows.append({'symbol': m['symbol'], 'company': m.get('company'), **_tender_fields(m), 'source': 'NSE tender offers',
                     'buyback_id': _id('bb', m['symbol'], None, m['offer_open'])})
    dl = daily.copy() if daily is not None and not daily.empty else pd.DataFrame()
    if not dl.empty:
        dl['report_date'] = _d(dl['report_date'])
        dl = dl.dropna(subset=['symbol', 'report_date']).sort_values(['symbol', 'report_date'])
        dl['run'] = dl.groupby('symbol')['report_date'].diff().gt(pd.Timedelta(days=OPEN_MARKET_GAP_DAYS)).groupby(dl['symbol']).cumsum()
        for (sym, _), g in dl.groupby(['symbol', 'run']):
            rows.append({'symbol': sym, 'company': g['company'].iloc[-1], 'route': 'open market',
                         'daily_reports': len(g), 'first_report': g['report_date'].min(), 'last_report': g['report_date'].max(),
                         'source': 'NSE daily buyback reports', 'buyback_id': _id('bb-om', sym, g['report_date'].min())})
    out = pd.DataFrame(rows).reindex(columns=COLUMNS + ['isin']) if rows else pd.DataFrame(columns=COLUMNS + ['isin'])
    for c in ('offer_open', 'offer_close', 'record_date', 'ex_date', 'first_report', 'last_report'):
        out[c] = _d(out[c])
    out['latest'] = out[['offer_open', 'record_date', 'last_report']].max(axis=1)
    out = out.sort_values('latest', ascending=False, kind='stable').drop(columns='latest').reset_index(drop=True)
    rep.update(rows=len(out), tender=int((out['route'] == 'tender offer').sum()),
               open_market=int((out['route'] == 'open market').sum()), no_route=int(out['route'].isna().sum()),
               actions_matched=len(used), actions=len(a))
    return out, rep


def _tender_fields(m) -> dict:
    price, sought = m.get('offer_price'), m.get('shares_sought')
    return {'route': 'tender offer', 'offer_price': price, 'shares_sought': sought,
            'offer_value': price * sought if pd.notna(price) and pd.notna(sought) else None,
            'shares_tendered': m.get('shares_tendered'), 'times_tendered': m.get('times_tendered'),
            'offer_open': m.get('offer_open'), 'offer_close': m.get('offer_close')}
