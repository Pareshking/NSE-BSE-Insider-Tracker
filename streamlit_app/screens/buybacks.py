"""Buybacks with their price and route (clean/current/buybacks.parquet,
insiders_clean/buybacks.py): a card for the Capital raises page and timeline
events for the Company page. The site only reads the table; the offer price
against today's close, and against the close before the board meeting that considered it, are the sums done here."""
from __future__ import annotations

import numpy as np
import pandas as pd
from data import store
from ui import kit

from screens.ctx import split_since, with_prices

ANNOUNCE_DAYS = 120   # a buyback meeting further back than this before the record date is not this buyback's

ROUTE = {'tender offer': 'Tender offer', 'open market': 'Open market'}


def _announced(r: pd.DataFrame, meetings: pd.DataFrame | None) -> pd.Series:
    """Per buyback, the day of the board meeting that considered it: NSE's latest meeting of the symbol whose
    purpose is a buyback, in the ANNOUNCE_DAYS up to the buyback's first date. Blank when our meetings have none."""
    out = pd.Series(pd.NaT, index=r.index, dtype='datetime64[ns]')
    if meetings is None or meetings.empty or not {'buyback', 'symbol', 'meeting_date'} <= set(meetings.columns):
        return out
    m = meetings[meetings['buyback'].astype('boolean').fillna(False)]
    m = pd.DataFrame({'sym': m['symbol'].astype(str).str.upper(), 'day': pd.to_datetime(m['meeting_date'], errors='coerce')}).dropna()
    days = {s: np.sort(g['day'].to_numpy()) for s, g in m.groupby('sym')}
    for i, sym, when in zip(r.index, r['symbol'].astype(str).str.upper(), r['when']):
        d = days.get(sym)
        if d is None or pd.isna(when):
            continue
        k = np.searchsorted(d, np.datetime64(when), side='right') - 1
        if k >= 0 and (when - pd.Timestamp(d[k])).days <= ANNOUNCE_DAYS:
            out.at[i] = d[k]
    return out


def _close_before(isins: pd.Series, days: pd.Series) -> pd.Series:
    """The split-adjusted close of the last session before each day (artifacts/price_history.parquet, the last
    ~400 days): the price the market had before the board meeting. Blank outside the history."""
    hist = store.price_history()
    out = pd.Series(np.nan, index=isins.index)
    for i, isin, day in zip(isins.index, isins, days):
        h = hist.get(isin) if hist and pd.notna(day) else None
        if h is None:
            continue
        d, c = h
        k = np.searchsorted(d, np.datetime64(day), side='left') - 1
        if 0 <= k < len(d) - 1 and c[k] > 0:   # a close before the day, and the history reaches past it
            out.at[i] = c[k]
    return out


def rows(bb: pd.DataFrame, prices: pd.DataFrame, meetings: pd.DataFrame | None = None) -> pd.DataFrame:
    if bb is None or bb.empty:
        return pd.DataFrame()
    r = with_prices(bb.copy(), prices)
    r['nse_symbol'] = r['symbol']
    r['how'] = r['route'].map(ROUTE)
    r['when'] = pd.to_datetime(r['offer_open'], errors='coerce').fillna(pd.to_datetime(r['record_date'], errors='coerce')) \
        .fillna(pd.to_datetime(r['first_report'], errors='coerce'))
    offer = pd.to_numeric(r['offer_price'], errors='coerce') * split_since(r, prices, ['record_date', 'offer_open', 'first_report'])   # audit W9
    close = pd.to_numeric(r['latest_close'], errors='coerce')
    r['vs_market'] = ((offer / close - 1) * 100).where(offer.gt(0) & close.gt(0))
    # The premium an investor weighed when the buyback was announced (audit 22 Oct): the offer, on today's split
    # basis, against the adjusted close before the board meeting.
    r['announced'] = _announced(r, meetings)
    before = _close_before(r['isin'], r['announced']) if 'isin' in r else pd.Series(np.nan, index=r.index)
    r['vs_announce'] = ((offer / before - 1) * 100).where(offer.gt(0) & before.gt(0))
    r['note'] = r['route'].map({'open market': 'daily reports filed'}).fillna('') + \
        r['daily_reports'].map(lambda n: f': {int(n)}' if pd.notna(n) else '')
    return r.sort_values('when', ascending=False, na_position='last', kind='stable').reset_index(drop=True)


def card(bb: pd.DataFrame, prices: pd.DataFrame, meetings: pd.DataFrame | None = None) -> None:
    r = rows(bb, prices, meetings)
    if r.empty:
        return
    with kit.card('Buybacks', 'cr_bb', 'offer price against the market, and the route'):
        kit.table(r, [
            kit.Col('when', 'Starts', 'date', help='Tender opening day; else the record date, or the first daily report of an open-market buyback'),
            kit.Col('company', 'Company', 'co'), kit.Col('how', 'Route', sub='note'),
            kit.Col('offer_price', 'Offer price', 'price'), kit.Col('latest_close', 'Market price now', 'price', phone=False),
            kit.Col('vs_market', 'Offer vs market now', 'spct', help='Positive = the company offers more than today\'s price'),
            kit.Col('vs_announce', 'Offer vs before the board meeting', 'spct', phone=False,
                    help='The offer against the close of the session before the board meeting that considered the buyback'),
            kit.Col('offer_value', 'Size', 'money', phone=False), kit.Col('times_tendered', 'Tendered ×', 'num', phone=False),
            kit.Col('record_date', 'Record date', 'date', phone=False)], limit=100)
        kit.caption("Tender offers: price, shares sought and times tendered from NSE's tender-offer list. Open market: the "
                    "company files a daily buyback report with NSE; its maximum price is only in the PDF announcement, so "
                    "it is blank. A 'Buy Back' corporate action with no tender record on NSE shows no route. Market price "
                    "now is the latest close in our price files; the offer against the close before the board meeting is the "
                    "premium when it was announced (blank where NSE lists no buyback meeting or our prices do not reach back).")


def events(bb: pd.DataFrame, prices: pd.DataFrame, meetings: pd.DataFrame | None = None) -> list[dict]:
    """Company timeline events, one per buyback."""
    out = []
    for x in rows(bb, prices, meetings).to_dict('records'):
        meta = [f'record date {kit.day(x["record_date"])}' if pd.notna(x.get('record_date')) else '',
                f'offer open {kit.day(x["offer_open"])}–{kit.day(x["offer_close"])}' if pd.notna(x.get('offer_open')) else '',
                f'{kit.pct(x["vs_market"], 1, signed=True)} vs market now' if kit._finite(x.get('vs_market')) is not None else '',
                f'{kit.pct(x["vs_announce"], 1, signed=True)} vs the close before the board meeting of {kit.day(x["announced"])}'
                if kit._finite(x.get('vs_announce')) is not None else '',
                f'{kit.indian(x["daily_reports"])} daily reports to {kit.day(x["last_report"])}' if pd.notna(x.get('daily_reports')) else '']
        out.append({'date': x['when'], 'kind': 'action', 'meta': meta,
                    'amount': kit.price(x['offer_price']) if kit._finite(x.get('offer_price')) is not None else '',
                    'title': 'Buyback' + (f' · {kit.esc(x["how"].lower())}' if isinstance(x.get('how'), str) else ' · route not on NSE')})
    return out
