"""Filings read by the announcement reader (clean/current/announcement_reads.parquet, written through the
day by scripts/announcement_reader.py): one card per filing, every value with its quote and evidence.

Only values that passed the reader's checks are shown (quote found in the filing; a number's digits in its
quote; an amount's unit backed by the quote). `exact`: the quote is in the filing word for word; `table`:
its words stand in one table block of the filing, which cannot prove the column. Values held back are
counted on the card, with their reasons, never shown."""
from __future__ import annotations

import json
from html import escape as esc

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


def card_html(r: dict) -> str:
    fields = [f for f in _json(r.get('fields'), []) if f.get('shown') and f.get('name') in FIELD]
    metrics = [m for m in _json(r.get('metrics'), []) if m.get('shown')]
    agreed = _json(r.get('agreed'), {})
    held = [f for f in _json(r.get('fields'), []) + _json(r.get('metrics'), [])
            if not f.get('shown') and f.get('reason') != NOT_HELD]
    when = pd.Timestamp(r['broadcast_at']).tz_convert('Asia/Kolkata') if r.get('broadcast_at') else None
    rows = []
    for f in fields:
        both = kit.tag('2 readers agree', 'buy') if agreed.get(f['name']) is True else ''
        rows.append(f'<li><b>{esc(FIELD[f["name"]])}</b> <span class="rd-v">{esc(value_text(f))}</span>'
                    f'{_evidence(f.get("evidence"))}{both}<q>{esc(str(f.get("quote") or ""))}</q></li>')
    for m in metrics[:6]:
        period = str(m.get('period') or '').strip()
        label = ' '.join(x for x in (str(m.get('label') or ''),
                                     f'({period})' if period.lower() not in NO_PERIOD else '') if x)
        rows.append(f'<li><b>{esc(label)}</b> <span class="rd-v">{esc(metric_text(m))}</span>'
                    f'{_evidence(m.get("evidence"))}<q>{esc(str(m.get("quote") or ""))}</q></li>')
    reasons = pd.Series([h.get('reason') for h in held if h.get('reason')], dtype=object).value_counts()
    because = '; '.join(f'{k} ×{n}' if n > 1 else k for k, n in sorted(reasons.items()))
    held_html = (f'<p class="rd-held">{kit.plural(len(held), "value")} held back: {esc(because)}</p>'
                 if held else '')
    also = r.get('also_filed') or []
    also_html = ('<p class="rd-s">Also filed: ' + ' · '.join(
        esc(f'{a["exchange"]} {pd.Timestamp(a["broadcast_at"]).tz_convert("Asia/Kolkata").strftime("%d %b, %H:%M")}')
        for a in also) + '</p>') if also else ''
    sym = r.get('symbol')
    return (f'<article class="rd">'
            f'<header><a href="{kit.company_href(sym)}" target="_self">{esc(str(r.get("company") or sym))}</a>'
            f'{kit.tag(CATEGORY.get(r.get("category"), str(r.get("category"))), "info")}'
            f'{kit.tag(r.get("exchange") or "", "mute")}'
            f'<span class="rd-t">{esc(when.strftime("%d %b, %H:%M IST")) if when is not None else ""}</span></header>'
            f'<p class="rd-s">{esc(str(r.get("subject") or ""))}</p>'
            f'{also_html}<ul>{"".join(rows)}</ul>{held_html}'
            f'<footer><a href="{esc(str(r.get("file_url") or "#"))}" target="_blank" rel="noopener">The filing</a>'
            f' · read by {esc(str(r.get("reader") or ""))}</footer></article>')


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


def render(reads: pd.DataFrame, since: pd.Timestamp) -> None:
    """The Brief's card: waits for its data (nothing shown before the reader has written its table)."""
    r = recent(reads, since)
    if r.empty:
        return
    with kit.card('Filings read', 'br_reads', f'since {kit.day(since)}: values checked against the filing\'s own words'):
        st.html('<p class="evl">' + kit.tag('in the filing', 'info') + 'quoted word for word '
                + kit.tag('table row', 'warn') + 'found in one table of the filing, column not proven '
                + kit.tag('2 readers agree', 'buy') + 'a second model read the same value</p>'
                + '<div class="rds">' + ''.join(card_html(x) for x in r.head(LIMIT).to_dict('records')) + '</div>')
