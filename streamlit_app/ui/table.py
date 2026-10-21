"""Data tables, drawn as HTML rather than st.dataframe.

A company cell with its symbol and exchanges, side pills, size bars, a
52-week range and a price line with the insider trades marked on it read far
faster than a plain grid. Tables are drawn in the page (st.html with its
script allowed), so they share the page's tokens and fonts and links are plain
links; a click on a header sorts, a row with facts behind it opens in place,
the header and first column stay pinned, and at phone width the columns
marked phone=False drop out.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib

import pandas as pd
import streamlit as st

from ui.kit import (_finite, company_href, empty, entity_href, esc, exchange_tags, flag_tags, indian, pct, price, role, rupees,
                    shares, side_tag, tag)

@dataclass(frozen=True)
class Col:
    key: str
    label: str
    kind: str = 'text'  # text co person client side money smoney pct spct bar range spark date tags num
    help: str = ''
    sub: str = ''       # a second, muted line from another column
    phone: bool = True  # shown at phone width


TAG_TONES = {'Spotlight': 'info', 'Float absorber': 'buy', 'Cluster': 'buy', 'Promoter selling': 'sell',
             'High pledge': 'warn', 'Promoter': 'warn', 'Large': 'info', 'Token': 'mute', 'Late': 'warn'}
NA = '<span class="na">—</span>'
RIGHT = ('money', 'smoney', 'pct', 'spct', 'bar', 'num', 'price', 'shares')
NUMERIC_SORT = RIGHT + ('range', 'spark', 'date', 'tags')


def _tone(text: str) -> str:
    return next((t for k, t in TAG_TONES.items() if str(text).startswith(k)), 'mute')


def _a(href: str, text: str) -> str:
    return f'<a href="{esc(href, quote=True)}" target="_self">{text}</a>'


def _sv(v) -> str:
    f = _finite(v)
    return '' if f is None else f'{f:.6g}'


def range_bar(close, low, high) -> str:
    """Latest close placed between the 52-week low and high, with the
    distance from the high."""
    c, lo, hi = _finite(close), _finite(low), _finite(high)
    if c is None or lo is None or hi is None or hi <= 0:
        return NA
    pos = 50.0 if hi == lo else max(0.0, min(100.0, (c - lo) / (hi - lo) * 100))
    off = (c / hi - 1) * 100
    tone = 'hi' if off > -5 else 'lo' if pos < 20 else ''
    return (f'<div class="rg {tone}" title="52W low {price(lo)} · high {price(hi)}">'
            f'<span class="rg-t"><i style="left:{pos:.1f}%"></i></span>'
            f'<span class="rg-v">{price(c)}<em>{off:+.1f}% from high</em></span></div>')


def spark(dates, closes, marks=(), days: int = 365, w: int = 116, h: int = 30) -> tuple[str, float | None]:
    """(svg, 1-year % change): the last year's price line with each
    open-market insider buy (green) and sell (red) marked on the day it was
    made public. `marks` is a list of (date, 'BUY' | 'SELL')."""
    if dates is None or len(dates) < 5:
        return NA, None
    d = pd.DatetimeIndex(dates)
    keep = d >= d[-1] - pd.Timedelta(days=days)
    d, c = d[keep], closes[keep]
    if len(c) < 5:
        return NA, None
    step = max(1, len(c) // 60)
    idx = list(range(0, len(c), step)) + ([len(c) - 1] if (len(c) - 1) % step else [])
    lo, hi = float(min(c)), float(max(c))
    span = (hi - lo) or 1.0
    t0, t1 = d[0].value, d[-1].value

    def x(t):
        return 2 + (t - t0) / ((t1 - t0) or 1) * (w - 4)

    def y(v):
        return h - 3 - (v - lo) / span * (h - 6)

    pts = ' '.join(f'{x(d[i].value):.1f},{y(c[i]):.1f}' for i in idx)
    dots = []
    for when, side in marks:
        t = pd.Timestamp(when)
        if pd.isna(t) or t < d[0] or t > d[-1]:
            continue
        j = min(int(d.searchsorted(t)), len(c) - 1)
        cls = 'b' if side == 'BUY' else 's'
        dots.append(f'<circle cx="{x(d[j].value):.1f}" cy="{y(c[j]):.1f}" r="3.2" class="{cls}"/>')
    chg = float(c[-1] / c[0] - 1) * 100
    tone = 'up' if chg >= 0 else 'down'
    svg = (f'<div class="spw"><svg class="sp" viewBox="0 0 {w} {h}" width="{w}" height="{h}">'
           f'<polyline points="{pts}" class="{"u" if chg >= 0 else "d"}"/>{"".join(dots)}</svg>'
           f'<span class="{tone}">{chg:+.0f}%</span></div>')
    return svg, chg


def _cell(c: Col, r: dict, bar_max: dict) -> tuple[str, str, str]:
    """(html, sort value, class) for one cell."""
    v = r.get(c.key)
    k = c.kind
    if k == 'co':
        sym = next((x for x in (r.get('nse_symbol'), r.get('symbol')) if isinstance(x, str) and x), '')
        name = str(v if isinstance(v, str) and v else sym)
        sub = f'<span class="sym">{esc(str(sym))}</span>' + exchange_tags(str(r.get('listed_on') or '').lower())
        extra = r.get(c.sub) if c.sub else None
        if isinstance(extra, str) and extra:
            sub += f'<span class="ctx">{esc(extra)}</span>'
        flags = flag_tags(r.get('trade_flags'), r.get('trade_flag_notes'))
        return f'{_a(company_href(sym), esc(name))}<div class="sub">{sub}</div>{flags}', name, 'co'
    if k in ('person', 'client'):
        pid = r.get('person_id' if k == 'person' else 'client_id')
        sub = role(r.get('person_role')) if k == 'person' else str(r.get(c.sub) or '') if c.sub else ''
        name = str(v) if isinstance(v, str) else ''
        link = _a(entity_href(pid), esc(name)) if isinstance(pid, str) and pid and name else (esc(name) or NA)
        return link + (f'<div class="sub">{esc(sub)}</div>' if sub else ''), name, 'who'
    if k == 'side':
        return side_tag(v), str(v or ''), ''
    if k == 'money':
        return (rupees(v) if _finite(v) is not None else NA), _sv(v), 'r num'
    if k == 'smoney':
        f = _finite(v)
        tone = 'up' if f and f > 0 else 'down' if f and f < 0 else ''
        return (rupees(v, signed=True) if f is not None else NA), _sv(v), f'r num {tone}'
    if k in ('pct', 'spct'):
        f = _finite(v)
        if f is None:
            return NA, '', 'r'
        tone = ('up' if f > 0 else 'down' if f < 0 else '') if k == 'spct' else ''
        return pct(f, 2 if abs(f) >= 0.1 else 3, signed=(k == 'spct')), _sv(f), f'r num {tone}'
    if k == 'bar':
        f = _finite(v)
        if f is None:
            return NA, '', 'r'
        w = min(100.0, abs(f) / bar_max.get(c.key, 1.0) * 100)
        side = r.get('side')
        tone = 'sell' if (side == 'SELL' or (side not in ('BUY', 'SELL') and f < 0)) else 'buy'
        return (f'<div class="br"><span class="num">{pct(f, 2 if abs(f) >= 0.1 else 3, signed=f < 0)}</span>'
                f'<i class="{tone}" style="width:{w:.0f}%"></i></div>'), _sv(f), 'r'
    if k == 'range':
        return range_bar(r.get('latest_close'), r.get('low_52w'), r.get('high_52w')), _sv(r.get('pct_off_high')), ''
    if k == 'spark':
        return str(r.get('_spark') or NA), _sv(r.get('_chg_1y')), 'spk'
    if k == 'date':
        t = pd.to_datetime(v, errors='coerce')
        ok = pd.notna(t)
        sub = r.get(c.sub) if c.sub else None
        tail = f'<div class="sub">{esc(sub)}</div>' if isinstance(sub, str) and sub else ''
        return (t.strftime('%d %b %Y') if ok else NA) + tail, (t.strftime('%Y%m%d') if ok else ''), 'd'
    if k == 'tags':
        items = v if isinstance(v, (list, tuple)) else [x for x in str(v or '').split(',') if x.strip()]
        return ' '.join(tag(str(x).strip(), _tone(str(x).strip())) for x in items), str(len(items)), 'tags'
    if k == 'num':
        f = _finite(v)
        return (NA if f is None else indian(f, 0 if f == int(f) else 2)), _sv(f), 'r num'
    if k == 'price':
        f = _finite(v)
        return (NA if f is None else price(f)), _sv(f), 'r num'
    if k == 'shares':
        f = _finite(v)
        return (NA if f is None else shares(f)), _sv(f), 'r num'
    text = '' if v is None or (not isinstance(v, (list, tuple)) and pd.isna(v)) else str(v)
    sub = r.get(c.sub) if c.sub else None
    cell = esc(text) if text else NA
    return cell + (f'<div class="sub">{esc(str(sub))}</div>' if isinstance(sub, str) and sub else ''), text, 'tx'


SORT_JS = """
(function (id) {
  const wrap = document.getElementById(id);
  if (!wrap || wrap.dataset.ready) return;
  wrap.dataset.ready = '1';
  const tb = wrap.querySelector('tbody');
  // A row with a detail row under it opens in place; clicks on links still follow the link.
  tb.addEventListener('click', e => {
    if (e.target.closest('a')) return;
    const tr = e.target.closest('tr.has-dt');
    if (!tr) return;
    const dt = tr.nextElementSibling;
    if (dt && dt.classList.contains('dt')) { dt.hidden = !dt.hidden; tr.classList.toggle('open', !dt.hidden); }
  });
  wrap.querySelectorAll('th[data-k]').forEach(th => th.addEventListener('click', () => {
    const i = th.cellIndex, num = th.dataset.k === 'n';
    const dir = th.dataset.dir === 'desc' ? 'asc' : 'desc';
    th.closest('tr').querySelectorAll('th').forEach(h => { h.dataset.dir = ''; });
    th.dataset.dir = dir;
    const val = tr => { const v = tr.cells[i].dataset.v;
      return num ? (v === '' ? NaN : parseFloat(v)) : (v || '').toLowerCase(); };
    const groups = [];   // each row with its detail row, so they move together
    Array.from(tb.rows).forEach(r => { if (r.classList.contains('dt')) groups[groups.length - 1].push(r); else groups.push([r]); });
    groups.sort((a, b) => {
      const x = val(a[0]), y = val(b[0]);
      if (num) { if (isNaN(x)) return 1; if (isNaN(y)) return -1; return dir === 'asc' ? x - y : y - x; }
      return dir === 'asc' ? x.localeCompare(y) : y.localeCompare(x);
    }).forEach(g => g.forEach(r => tb.appendChild(r)));
  }));
})
"""


def facts(items: list[tuple[str, str]], links: list[tuple[str, str]] = ()) -> str:
    """The inside of a detail row: label / value pairs in a grid, then links
    (label, href). Values are text and are escaped here."""
    cells = ''.join(f'<div><b>{esc(k)}</b><span>{esc(v)}</span></div>' for k, v in items if v not in (None, ''))
    ln = ''.join(f'<a href="{esc(h, quote=True)}" target="_blank" rel="noopener">{esc(t)}</a>' for t, h in links if h)
    return f'<div class="dt-grid">{cells}</div>' + (f'<div class="dt-links">{ln}</div>' if ln else '')


def table(rows: pd.DataFrame, cols: list[Col], limit: int = 50, empty_text: str = 'Nothing here.',
          height: int = 600, download: str = '', row_px: int = 53, detail=None, key: str = '') -> None:
    """A ranked, sortable table drawn in the page (so it shares the page's
    styles and links work as links): the first `limit` rows drawn, the rest
    counted (and offered as a CSV when `download` names the file).
    `detail(row) -> html` adds a row under each row that opens on a click."""
    if rows is None or rows.empty:
        empty(empty_text)
        return
    shown = rows.head(limit)
    # A number column with no value in any shown row says nothing: drop it.
    cols = [c for c in cols if c.kind not in ('pct', 'spct', 'bar', 'money', 'smoney', 'num', 'price', 'shares')
            or c.key not in shown or pd.to_numeric(shown[c.key], errors='coerce').notna().any()]
    bar_max = {c.key: max(pd.to_numeric(shown[c.key], errors='coerce').abs().max(), 1e-9)
               for c in cols if c.kind == 'bar' and c.key in shown}
    head = ''.join(
        f'<th data-k="{"n" if c.kind in NUMERIC_SORT else "t"}" class="{"r" if c.kind in RIGHT else ""}'
        f'{"" if c.phone else " opt"}"' + (f' title="{esc(c.help, quote=True)}"' if c.help else '')
        + f'>{esc(c.label)}</th>' for c in cols)
    body = []
    for r in shown.to_dict('records'):
        cells = []
        for c in cols:
            inner, sv, cls = _cell(c, r, bar_max)
            cells.append(f'<td class="{cls}{"" if c.phone else " opt"}" data-v="{esc(sv, quote=True)}">{inner}</td>')
        more_html = detail(r) if detail else ''
        opener = ' class="has-dt"' if more_html else ''   # no backslash inside an f-string: Python 3.11 runs the site
        body.append(f'<tr{opener}>' + ''.join(cells) + '</tr>')
        if more_html:
            body.append(f'<tr class="dt" hidden><td colspan="{len(cols)}">{more_html}</td></tr>')
    tid = 'tb_' + hashlib.sha1(f'{key}|{download}|{len(rows)}|{"|".join(c.key for c in cols)}'.encode()).hexdigest()[:10]
    st.html(f'<div class="tbl-wrap" id="{tid}" style="max-height:{height}px"><table class="tbl"><thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div><script>{SORT_JS}("{tid}");</script>',
            unsafe_allow_javascript=True)
    more = len(rows) - len(shown)
    if more > 0 or download:
        c1, c2 = st.columns([3, 1], vertical_alignment='center')
        if more > 0:
            c1.html(f'<p class="tbl-cap">Top {len(shown):,} of {len(rows):,}</p>')
        if download:
            flat = rows[[c for c in rows.columns if not str(c).startswith('_')
                         and not rows[c].map(lambda x: isinstance(x, (list, dict))).any()]]
            c2.download_button('CSV', flat.to_csv(index=False).encode(), f'{download}.csv',
                               'text/csv', key=f'dl_{download}', type='tertiary', width='stretch')
