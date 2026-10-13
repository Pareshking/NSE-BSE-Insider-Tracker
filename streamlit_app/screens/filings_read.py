"""Filings read by the announcement reader (clean/current/announcement_reads.parquet, written through the
day by scripts/announcement_reader.py): one card per filing, every value with its quote and evidence.

Only values that passed the reader's checks are shown (quote found in the filing; a number's digits in its
quote; an amount's unit backed by the quote). `exact`: the quote is in the filing word for word; `table`:
its words stand in one table block of the filing, which cannot prove the column. Values held back are
counted on the card, with their reasons, never shown."""
from __future__ import annotations

import json
import re
from html import escape as esc

import numpy as np
import pandas as pd
import streamlit as st
from ui import kit

CATEGORY = {
    'buyback_open_market': 'Buyback, open market', 'buyback_tender': 'Buyback, tender offer', 'qip': 'QIP',
    'preferential': 'Preferential issue', 'warrant_conversion': 'Warrants converted', 'rights': 'Rights issue',
    'open_offer': 'Open offer', 'debt_issue': 'Debt issue', 'capex': 'Capacity / investment',
    'product_launch': 'Product launch', 'order_win': 'Order win', 'business_update': 'Business update',
    'auditor_resignation': 'Auditor resigned', 'rating_upgrade': 'Rating raised', 'rating_downgrade': 'Rating lowered',
    'rating_reaffirmed': 'Rating kept', 'deal_or_dispute': 'Deal or dispute',
}
FIELD = {'price_per_share': 'Price a share', 'max_price_per_share': 'Up to, a share', 'shares': 'Shares',
         'amount': 'Size', 'discount_pct': 'Discount', 'allottee_is_promoter': 'To promoters', 'ratio': 'Ratio',
         'record_date': 'Record date', 'offer_pct': 'Offer size', 'capacity_from': 'Capacity before',
         'capacity_to': 'Capacity after'}
SHOWN_STATUSES = ('read', 'same_file', 'same_text')
LIMIT = 40
NOT_HELD = 'entity labels not shown yet'   # by design for now, so not counted as held back on the card
NO_PERIOD = ('', 'n/a', 'na', '-', 'none', 'not stated')


def _json(v, empty):
    try:
        return json.loads(v) if isinstance(v, str) and v else empty
    except ValueError:
        return empty


def _money(n, currency) -> str:
    cur = str(currency or 'INR').upper()
    if cur == 'INR':
        return kit.rupees(n)
    return f'{cur} {n / 1e9:,.2f} bn' if abs(n) >= 1e9 else f'{cur} {n / 1e6:,.1f} M' if abs(n) >= 1e6 else f'{cur} {n:,.0f}'


def _as_written(f: dict) -> str:
    return ' '.join(str(x) for x in (f.get('value'), f.get('unit')) if x not in (None, ''))


def value_text(f: dict) -> str:
    """A checked value as the site writes it; our own conversion, never the model's. A sum of money gets a
    currency only when the filing writes one (the reader reads it from the quote or the filing's currency);
    otherwise it is written as the filing writes it, never with Rs assumed."""
    name, n, cur = f.get('name'), f.get('number'), f.get('currency')
    if name in ('price_per_share', 'max_price_per_share') and n is not None:
        return kit.price(n) if cur == 'INR' else _money(n, cur) if cur else _as_written(f)
    if name == 'shares' and n is not None:
        return kit.shares(n)
    if name == 'amount' and n is not None:
        return _money(n, cur) if cur else _as_written(f)
    if name in ('discount_pct', 'offer_pct') and n is not None:
        return kit.pct(n)
    if name == 'record_date' and f.get('date'):
        return kit.day(pd.Timestamp(f['date']))
    if name == 'allottee_is_promoter':
        return {True: 'Yes', False: 'No'}.get(f.get('flag'), '?')
    return str(f.get('value'))


def metric_text(m: dict) -> str:
    n, unit = m.get('number'), str(m.get('unit') or '').strip().lower()
    if n is None:
        return str(m.get('value'))
    if unit in ('percent', '%'):
        return kit.pct(n)
    if unit in ('rupees', 'rs', 'thousand', 'lakh', 'lakhs', 'crore', 'crores', 'cr', 'million', 'mn', 'billion', 'bn'):
        return _money(n, m['currency']) if m.get('currency') else _as_written(m)   # no currency: as written
    return f'{kit.indian(n)} {esc(str(m.get("unit") or ""))}'.strip()


def _evidence(e) -> str:
    return kit.tag('in the filing', 'info') if e == 'exact' else kit.tag('table row', 'warn') if e == 'table' else ''


BUCKET = {'Large': 'Largecap', 'Mid': 'Midcap', 'Small': 'Smallcap', 'Micro': 'Microcap'}
# A number as filings write it, with its currency or unit: bold in the card's sentences.
# A figure as filings write it, with its currency or its unit ('₹120 Cr', 'CAD 94.5 million', '32%'): bold in the
# card's sentences; plain numbers (dates, counts without a unit) stay plain.
_CUR = r'(?:₹|Rs\.?|INR|US\$|USD|CAD|EUR|GBP|SGD|AED|JOD|£|€|\$)\s?'
_UNIT = r'\s?(?:%|Cr\b|crores?\b|lakhs?\b|million\b|mn\b|bn\b|billion\b|M\b|units?\b|TPD\b|MW\b|KL\b)'
_N = r'\d(?:[\d,]*\d)?(?:\.\d+)?'
_FIGURE = re.compile(rf'{_CUR}{_N}(?:{_UNIT})?|{_N}{_UNIT}', re.IGNORECASE)


def _bold_figures(text: str) -> str:
    return _FIGURE.sub(lambda m: f'<b>{m.group(0)}</b>', esc(text))


def _moves(isin, history) -> list[tuple[str, float]]:
    """1W, 1M, 1Y price moves (%) from the split-adjusted closes the site has (blank where too short)."""
    h = (history or {}).get(isin) if isin else None
    if not h or len(h[0]) < 2:
        return []
    s = pd.Series(list(h[1]), index=pd.DatetimeIndex(h[0]), dtype='float64').dropna()
    out = []
    for label, days in (('1W', 7), ('1M', 30), ('1Y', 365)):
        past = s.loc[:s.index[-1] - np.timedelta64(days, 'D')] if len(s) else s
        if len(past) and past.iloc[-1]:   # the last close on or before the day that long ago
            out.append((label, (s.iloc[-1] / past.iloc[-1] - 1) * 100))
    return out


def _mcap(r: dict, price: dict) -> str:
    cap = price.get('market_cap') if price.get('market_cap') == price.get('market_cap') else None
    cap = cap or r.get('market_cap')
    size = BUCKET.get(price.get('mcap_bucket'), '')
    parts = [f'₹{kit.indian(cap / 1e7)} Cr' if cap and cap == cap else '', size]
    return ' · '.join(p for p in parts if p)


def _metric_label(m: dict) -> str:
    period = str(m.get('period') or '').strip()
    return ' '.join(x for x in (str(m.get('label') or ''), f'({period})' if period.lower() not in NO_PERIOD else '') if x)


def card_html(r: dict, price: dict | None = None, history: dict | None = None) -> str:
    """One filing as a card: what happened (headline and points, every number in them found in the filing),
    its key terms, the figures of a periodic update with the change we compute, the filing's own words, and
    the stock's moves. Older reads without a headline show their checked values only."""
    price = price or {}
    fields = [f for f in _json(r.get('fields'), []) if f.get('shown') and f.get('name') in FIELD]
    metrics = [m for m in _json(r.get('metrics'), []) if m.get('shown')]
    headline = _json(r.get('headline'), None)
    headline = headline if isinstance(headline, dict) and headline.get('shown') else None
    points = [p for p in _json(r.get('points'), []) if p.get('shown')]
    agreed = _json(r.get('agreed'), {})
    held = [f for f in _json(r.get('fields'), []) + _json(r.get('metrics'), []) + _json(r.get('points'), [])
            if not f.get('shown') and f.get('reason') != NOT_HELD]
    when = pd.Timestamp(r['broadcast_at']).tz_convert('Asia/Kolkata') if r.get('broadcast_at') else None
    sym = r.get('symbol')
    category = CATEGORY.get(r.get('category'), str(r.get('category') or ''))

    title = headline['text'] if headline else (
        f'{r.get("company") or sym}: {category.lower()}'
        + (f', {value_text(next(f for f in fields if f["name"] == "amount"))}' if any(f['name'] == 'amount' for f in fields) else ''))
    body = ''.join(f'<li>{_bold_figures(p["text"])}</li>' for p in points)
    body = f'<ul class="rc-pts">{body}</ul>' if body else ''

    terms = ''.join(
        f'<div><dt>{esc(FIELD[f["name"]])}</dt><dd>{esc(value_text(f))}'
        f'{" " + kit.tag("2 readers agree", "buy") if agreed.get(f["name"]) is True else ""}</dd></div>' for f in fields)
    terms = f'<div class="rc-box"><p class="rc-lbl">Key terms</p><dl class="rc-terms">{terms}</dl></div>' if terms else ''

    figs = ''
    for m in metrics[:6]:
        ch = m.get('change_pct')
        tone = '' if ch is None else ' up' if ch > 0 else ' down' if ch < 0 else ''
        figs += (f'<tr><td>{esc(_metric_label(m))}</td><td class="n">{esc(metric_text(m))}</td>'
                 f'<td class="n rc-ch{tone}">{esc(kit.pct(ch, 1, signed=True) + " YoY") if ch is not None else ""}</td></tr>')
    figs = f'<div class="rc-box"><p class="rc-lbl">The figures</p><table class="rc-figs">{figs}</table></div>' if figs else ''

    quotes = [(FIELD[f['name']], f) for f in fields] + [(_metric_label(m), m) for m in metrics[:6]] + \
        [('Point', p) for p in points] + ([('Headline', headline)] if headline else [])
    src = ''.join(f'<li><span>{esc(lbl)}</span>{_evidence(q.get("evidence"))}<q>{esc(str(q.get("quote") or ""))}</q></li>'
                  for lbl, q in quotes if q.get('quote'))
    reasons = pd.Series([h.get('reason') for h in held if h.get('reason')], dtype=object).value_counts()
    because = '; '.join(f'{k} ×{n}' if n > 1 else k for k, n in sorted(reasons.items()))
    held_html = f'<p class="rd-held">{kit.plural(len(held), "value")} held back: {esc(because)}</p>' if held else ''
    src = (f'<details class="rc-src"><summary>The filing\'s own words</summary><ul>{src}</ul>{held_html}</details>'
           if src or held_html else '')

    also = r.get('also_filed') or []
    also_html = ' · '.join(
        esc(f'{a["exchange"]} {pd.Timestamp(a["broadcast_at"]).tz_convert("Asia/Kolkata").strftime("%d %b, %H:%M")}')
        for a in also)
    moves = ''.join(f'<span>{lbl} <b class="{"up" if v > 0 else "down" if v < 0 else ""}">{esc(kit.pct(v, 1, signed=True))}</b></span>'
                    for lbl, v in _moves(r.get('isin'), history))
    cap = _mcap(r, price)
    return (f'<article class="rc">'
            f'<div class="rc-top"><a class="rc-sym" href="{kit.company_href(sym)}" target="_self">{esc(str(sym or ""))}</a>'
            f'<span class="rc-cap">{esc(cap)}</span>'
            f'<span class="rc-t">{esc(when.strftime("%d %b, %H:%M")) if when is not None else ""} · {esc(str(r.get("exchange") or ""))}</span></div>'
            f'<div class="rc-tags">{kit.tag(category, "info")}<span class="rc-s">{esc(str(r.get("subject") or ""))}</span></div>'
            f'<h4 class="rc-h">{esc(title)}</h4>{body}{figs}{terms}{src}'
            f'<div class="rc-foot">{f"<span class=rc-mv>{moves}</span>" if moves else ""}'
            f'{f"<span>Also filed: {also_html}</span>" if also_html else ""}'
            f'<a href="{esc(str(r.get("file_url") or "#"))}" target="_blank" rel="noopener">The filing ↗</a>'
            f'<span class="rc-by">read by {esc(str(r.get("reader") or ""))}</span></div></article>')


def recent(reads: pd.DataFrame, since: pd.Timestamp) -> pd.DataFrame:
    """Filings with something to show, made public on or after `since`, newest first. The same file filed
    again (on the other exchange, or under another subject) is one card: the copies go in its `also_filed`."""
    if reads is None or reads.empty:
        return pd.DataFrame()
    r = reads[reads['status'].isin(SHOWN_STATUSES) & reads['category'].notna() & reads['category'].ne('routine')
              & pd.to_numeric(reads['shown'], errors='coerce').fillna(0).gt(0)]
    day = pd.to_datetime(r['broadcast_date'], errors='coerce')
    r = r[day >= since.normalize()]
    if r.empty:
        return r
    r = r if 'same_as' in r else r.assign(same_as=None)
    copy = r['status'].ne('read') & r['same_as'].isin(r['event_id'])
    also = {k: g[['exchange', 'broadcast_at']].to_dict('records')
            for k, g in r[copy].sort_values('broadcast_at').groupby('same_as')}
    r = r[~copy].copy()
    r['also_filed'] = r['event_id'].map(lambda e: also.get(e, []))
    return r.sort_values('broadcast_at', ascending=False)


def render(reads: pd.DataFrame, since: pd.Timestamp, prices: pd.DataFrame | None = None,
           history: dict | None = None) -> None:
    """The Brief's card: waits for its data (nothing shown before the reader has written its table)."""
    r = recent(reads, since)
    if r.empty:
        return
    by_isin = (prices.drop_duplicates('isin').set_index('isin').to_dict('index')
               if prices is not None and not prices.empty and 'isin' in prices else {})
    with kit.card('Filings read', 'br_reads', f'since {kit.day(since)}: values checked against the filing\'s own words'):
        st.html('<p class="evl">' + kit.tag('in the filing', 'info') + 'quoted word for word '
                + kit.tag('table row', 'warn') + 'found in one table of the filing, column not proven '
                + kit.tag('2 readers agree', 'buy') + 'a second model read the same value</p>'
                + '<div class="rds">' + ''.join(card_html(x, by_isin.get(x.get('isin')), history)
                                                for x in r.head(LIMIT).to_dict('records')) + '</div>')
