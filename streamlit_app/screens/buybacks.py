"""Buybacks with their price and route (clean/current/buybacks.parquet,
insiders_clean/buybacks.py): a card for the Capital raises page and timeline
events for the Company page. The site only reads the table; the offer price
against today's close is the one sum done here."""
from __future__ import annotations

import pandas as pd
from ui import kit

from screens.ctx import with_prices

ROUTE = {'tender offer': 'Tender offer', 'open market': 'Open market'}


def rows(bb: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    if bb is None or bb.empty:
        return pd.DataFrame()
    r = with_prices(bb.copy(), prices)
    r['nse_symbol'] = r['symbol']
    r['how'] = r['route'].map(ROUTE)
    r['when'] = pd.to_datetime(r['offer_open'], errors='coerce').fillna(pd.to_datetime(r['record_date'], errors='coerce')) \
        .fillna(pd.to_datetime(r['first_report'], errors='coerce'))
    offer, close = pd.to_numeric(r['offer_price'], errors='coerce'), pd.to_numeric(r['latest_close'], errors='coerce')
    r['vs_market'] = ((offer / close - 1) * 100).where(offer.gt(0) & close.gt(0))
    r['note'] = r['route'].map({'open market': 'daily reports filed'}).fillna('') + \
        r['daily_reports'].map(lambda n: f': {int(n)}' if pd.notna(n) else '')
    return r.sort_values('when', ascending=False, na_position='last', kind='stable').reset_index(drop=True)


def card(bb: pd.DataFrame, prices: pd.DataFrame) -> None:
    r = rows(bb, prices)
    if r.empty:
        return
    with kit.card('Buybacks', 'cr_bb', 'offer price against the market, and the route'):
        kit.table(r, [
            kit.Col('when', 'Starts', 'date', help='Tender opening day; else the record date, or the first daily report of an open-market buyback'),
            kit.Col('company', 'Company', 'co'), kit.Col('how', 'Route', sub='note'),
            kit.Col('offer_price', 'Offer price', 'price'), kit.Col('latest_close', 'Market price now', 'price', phone=False),
            kit.Col('vs_market', 'Offer vs market now', 'spct', help='Positive = the company offers more than today\'s price'),
            kit.Col('offer_value', 'Size', 'money', phone=False), kit.Col('times_tendered', 'Tendered ×', 'num', phone=False),
            kit.Col('record_date', 'Record date', 'date', phone=False)], limit=100, download='buybacks')
        kit.caption("Tender offers: price, shares sought and times tendered from NSE's tender-offer list. Open market: the "
                    "company files a daily buyback report with NSE; its maximum price is only in the PDF announcement, so "
                    "it is blank. A 'Buy Back' corporate action with no tender record on NSE shows no route. Market price "
                    "now is the latest close in our price files, not the price when the buyback was announced.")


def events(bb: pd.DataFrame, prices: pd.DataFrame) -> list[dict]:
    """Company timeline events, one per buyback."""
    out = []
    for x in rows(bb, prices).to_dict('records'):
        meta = [f'record date {kit.day(x["record_date"])}' if pd.notna(x.get('record_date')) else '',
                f'offer open {kit.day(x["offer_open"])}–{kit.day(x["offer_close"])}' if pd.notna(x.get('offer_open')) else '',
                f'{kit.pct(x["vs_market"], 1, signed=True)} vs market now' if kit._finite(x.get('vs_market')) is not None else '',
                f'{kit.indian(x["daily_reports"])} daily reports to {kit.day(x["last_report"])}' if pd.notna(x.get('daily_reports')) else '']
        out.append({'date': x['when'], 'kind': 'action', 'meta': meta,
                    'amount': kit.price(x['offer_price']) if kit._finite(x.get('offer_price')) is not None else '',
                    'title': 'Buyback' + (f' · {kit.esc(x["how"].lower())}' if isinstance(x.get('how'), str) else ' · route not on NSE')})
    return out
