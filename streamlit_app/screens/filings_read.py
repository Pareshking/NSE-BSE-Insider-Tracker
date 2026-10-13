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


def card_html(r: dict, price: dict | None = None, history: dict | None = None, before: list[str] | None = None) -> str:
    """One filing as a card: what happened (headline and points, every number in them found in the filing),
    its key terms, the figures of a periodic update with the change we compute, the filing's own words, and
    the stock's moves. Older reads without a headline show their checked values only."""
    price = price or {}
    fields = [f for f in _json(r.get('fields'), []) if f.get('shown') and f.get('name') in FIELD]
    metrics = [dict(m, _i=i) for i, m in enumerate(_json(r.get('metrics'), [])) if m.get('shown')]
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
        both = ' ' + kit.tag('2 readers agree', 'buy') if agreed.get(f'metric:{m["_i"]}') is True else ''
        figs += (f'<tr><td>{esc(_metric_label(m))}{both}</td><td class="n">{esc(metric_text(m))}</td>'
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

    also = list(r.get('also_filed') if r.get('also_filed') is not None else [])

    def _also(a) -> str:
        t = esc(f'{a["exchange"]} {pd.Timestamp(a["broadcast_at"]).tz_convert("Asia/Kolkata").strftime("%d %b, %H:%M")}')
        sub = a.get('subject')
        t += f' ({esc(str(sub))})' if sub and sub != r.get('subject') else ''
        url = a.get('file_url')
        return f'<a href="{esc(str(url))}" target="_blank" rel="noopener">{t}</a>' if url else t
    also_html = ' · '.join(_also(a) for a in also)
    moves = ''.join(f'<span>{lbl} <b class="{"up" if v > 0 else "down" if v < 0 else ""}">{esc(kit.pct(v, 1, signed=True))}</b></span>'
                    for lbl, v in _moves(r.get('isin'), history))
    cap = _mcap(r, price)
    return (f'<article class="rc">'
            f'<div class="rc-top"><a class="rc-sym" href="{kit.company_href(sym)}" target="_self">{esc(str(sym or ""))}</a>'
            f'<span class="rc-cap">{esc(cap)}</span>'
            f'<span class="rc-t">{esc(when.strftime("%d %b, %H:%M")) if when is not None else ""} · {esc(str(r.get("exchange") or ""))}</span></div>'
            f'<div class="rc-tags">{kit.tag(category, "info")}<span class="rc-s">{esc(str(r.get("subject") or ""))}</span></div>'
            f'<h4 class="rc-h">{esc(title)}</h4>{body}{figs}{_before_html(before)}{terms}{src}'
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
    for c in ('subject', 'file_url'):
        r = r if c in r else r.assign(**{c: None})
    copy = r['status'].ne('read') & r['same_as'].isin(r['event_id'])
    keep = ['event_id', 'exchange', 'broadcast_at', 'subject', 'file_url']
    also = {k: g[keep].to_dict('records') for k, g in r[copy].sort_values('broadcast_at').groupby('same_as')}
    r = r[~copy].copy()
    r['also_filed'] = r['event_id'].map(lambda e: also.get(e, []))
    return same_deal(r).sort_values('broadcast_at', ascending=False)


DEAL_HOURS = 24


def _figures(r) -> set[float]:
    """The shown numbers of a read (fields and metrics) that can name a deal: sizes, prices, share counts."""
    out = set()
    for f in _json(r.get('fields'), []) + _json(r.get('metrics'), []):
        n = f.get('number')
        if f.get('shown') and isinstance(n, (int, float)) and n == n and abs(n) >= 1:
            out.add(round(float(n), 2))
    return out


def same_deal(r: pd.DataFrame) -> pd.DataFrame:
    """Different files on one deal (Aegis, 13 Oct: a press release and the board's outcome, both US$ 809M for
    89.8% of Tristar) are one card: same company and category, made public within DEAL_HOURS, and sharing a
    number of 100 or more, or two numbers. The card kept is the one with the most shown values; the others
    go in its `also_filed`, with their subject and link."""
    if r.empty:
        return r
    r = r.reset_index(drop=True)
    who = r['isin'].where(r['isin'].notna(), r['symbol']) if 'isin' in r else r['symbol']
    figs = [_figures(x) for x in r.to_dict('records')]
    at = pd.to_datetime(r['broadcast_at'], errors='coerce', utc=True)
    shown = pd.to_numeric(r['shown'], errors='coerce').fillna(0)
    parent = list(range(len(r)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for _, idx in r.groupby([who, r['category']]).groups.items():
        idx = list(idx)
        for a in idx:
            for b in idx:
                if a < b and abs((at[a] - at[b]).total_seconds()) <= DEAL_HOURS * 3600:
                    both = figs[a] & figs[b]
                    if len(both) >= 2 or any(abs(n) >= 100 for n in both):
                        parent[root(b)] = root(a)
    groups = {}
    for i in range(len(r)):
        groups.setdefault(root(i), []).append(i)
    rows = []
    for idx in groups.values():
        lead = max(idx, key=lambda i: (shown[i], -at[i].value if pd.notna(at[i]) else 0))
        rec = r.loc[lead].to_dict()
        others = [r.loc[i].to_dict() for i in idx if i != lead]
        extra = [{k: o.get(k) for k in ('event_id', 'exchange', 'broadcast_at', 'subject', 'file_url')} for o in others]
        extra += [a for o in others for a in (o.get('also_filed') or [])]
        rec['also_filed'] = sorted(list(rec.get('also_filed') or []) + extra, key=lambda a: str(a.get('broadcast_at')))
        rows.append(rec)
    return pd.DataFrame(rows)


def _before_html(lines) -> str:
    if not lines:
        return ''
    return ('<div class="rc-box rc-before"><p class="rc-lbl">Before this</p><ul class="rc-pts">'
            + ''.join(f'<li>{x}</li>' for x in lines) + '</ul></div>')


EARLIER_DAYS, INSIDER_DAYS = 90, 30


def before_this(r: dict, reads: pd.DataFrame | None, price: dict | None, holding: dict | None,
                insiders: pd.DataFrame | None) -> list[str]:
    """Context from our own tables, every figure computed here, never by a model: the company's earlier
    filings read (last EARLIER_DAYS), the issue price against the last close, the size against market cap,
    promoter holding and pledge (latest quarter), and insiders' open-market trades (last INSIDER_DAYS)."""
    out, isin, sym = [], r.get('isin'), r.get('symbol')
    at = pd.to_datetime(r.get('broadcast_at'), errors='coerce', utc=True)
    fields = {f['name']: f for f in _json(r.get('fields'), []) if f.get('shown')}
    price = price or {}
    close = price.get('latest_close')
    for name in ('price_per_share', 'max_price_per_share'):
        f = fields.get(name)
        if f and f.get('currency') == 'INR' and f.get('number') and close and close == close:
            gap = (f['number'] / close - 1) * 100
            when = f' ({kit.day(price.get("last_date"), with_year=False)})' if price.get('last_date') else ''
            word = 'above' if gap > 0 else 'below'
            out.append(f'The price of <b>{esc(kit.price(f["number"]))}</b> is <b>{esc(kit.pct(abs(gap), 1))}</b> {word} '
                       f'the last close of {esc(kit.price(close))}{esc(when)}.')
            break
    amt, cap = fields.get('amount'), price.get('market_cap') or r.get('market_cap')
    if amt and amt.get('currency') == 'INR' and amt.get('number') and cap and cap == cap:
        out.append(f'The size is <b>{esc(kit.pct(amt["number"] / cap * 100, 1))}</b> of the company\'s market cap '
                   f'({esc(kit.rupees(cap))}).')
    if holding:
        pct, pledge = holding.get('promoter_holding_pct'), holding.get('promoter_pledge_pct')
        if pct is not None and pct == pct:
            q = f' ({kit.day(holding["quarter_end"])})' if holding.get('quarter_end') is not None else ''
            pl = (f', <b>{esc(kit.pct(pledge, 1))}</b> of it pledged' if pledge is not None and pledge == pledge and pledge > 0
                  else ', none of it pledged' if pledge == 0 else '')
            out.append(f'Promoters hold <b>{esc(kit.pct(pct, 1))}</b>{esc(q)}{pl}.')
    if insiders is not None and not insiders.empty and isin:
        t = insiders[(insiders['isin'] == isin) & (insiders['seen'] >= (at.tz_convert(None).normalize() if pd.notna(at) else
                     pd.Timestamp.now()) - np.timedelta64(INSIDER_DAYS, 'D'))]
        for side, word in (('BUY', 'bought'), ('SELL', 'sold')):
            x = t[t['side'] == side]
            if len(x):
                out.append(f'Insiders {word} <b>{esc(kit.rupees(x["value"].sum()))}</b> on the market in '
                           f'{kit.plural(len(x), "filing")} in the last {INSIDER_DAYS} days.')
    if reads is not None and not reads.empty and pd.notna(at):
        e = reads[((reads['isin'] == isin) if isin and 'isin' in reads else (reads['symbol'] == sym))
                  & reads['status'].eq('read') & reads['category'].notna() & reads['category'].ne('routine')
                  & reads['event_id'].ne(r.get('event_id'))]
        t = pd.to_datetime(e['broadcast_at'], errors='coerce', utc=True)
        e = e[(t < at - np.timedelta64(DEAL_HOURS, 'h')) & (t >= at - np.timedelta64(EARLIER_DAYS, 'D'))]
        for x in e.sort_values('broadcast_at', ascending=False).head(3).to_dict('records'):
            h = _json(x.get('headline'), None)
            what = h['text'] if isinstance(h, dict) and h.get('shown') else CATEGORY.get(x['category'], x['category'])
            day = pd.Timestamp(x['broadcast_at']).tz_convert('Asia/Kolkata').strftime('%d %b')
            out.append(f'{esc(day)}: {esc(str(what))}.')
    return out


LEGEND = ('<p class="evl">' + kit.tag('in the filing', 'info') + 'quoted word for word '
          + kit.tag('table row', 'warn') + 'found in one table of the filing, column not proven '
          + kit.tag('2 readers agree', 'buy') + 'a second model read the same value</p>')


def cards_html(r: pd.DataFrame, reads: pd.DataFrame, ctx=None, history: dict | None = None, limit: int = LIMIT) -> str:
    """The cards of `r` (rows from `recent`), with each company's price, holding and insider context."""
    prices = getattr(ctx, 'prices', None)
    by_isin = (prices.drop_duplicates('isin').set_index('isin').to_dict('index')
               if prices is not None and not prices.empty and 'isin' in prices else {})
    sh = getattr(ctx, 'shareholding', None)
    holdings = ({} if sh is None or sh.empty or 'isin' not in sh else
                sh.sort_values('quarter_end').drop_duplicates('isin', keep='last').set_index('isin').to_dict('index'))
    insiders = getattr(ctx, 'eligible', None)

    def card(x):
        p = by_isin.get(x.get('isin'))
        return card_html(x, p, history, before_this(x, reads, p, holdings.get(x.get('isin')), insiders))
    return '<div class="rds">' + ''.join(card(x) for x in r.head(limit).to_dict('records')) + '</div>'


def render(reads: pd.DataFrame, since: pd.Timestamp, ctx=None, history: dict | None = None) -> None:
    """The Brief's card: waits for its data (nothing shown before the reader has written its table)."""
    r = recent(reads, since)
    if r.empty:
        return
    with kit.card('Filings read', 'br_reads', f'since {kit.day(since)}: values checked against the filing\'s own words'):
        st.html(LEGEND + cards_html(r, reads, ctx, history)
                + '<p class="evl"><a href="/filings" target="_self">Every filing read, with filters →</a></p>')
