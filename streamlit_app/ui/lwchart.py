"""The company price chart in TradingView's Lightweight Charts (owner, 22 Oct 2026): closes as an area,
3M / 6M / 1Y / All, every open-market insider trade marked on the day it was made public (one marker per day
and side, sized by value), and a hover box with the close and who traded. The library is Apache-2.0; its
logo is off and the site credits it on the Data quality page (screens/data_status.py), as its NOTICE asks.
"""
from __future__ import annotations

import hashlib
import json

import pandas as pd

from ui.theme import C

LIB = 'https://cdn.jsdelivr.net/npm/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js'
BUY, SELL, PRICE = C['buy'], C['sell'], C['accent']   # ui/theme.py

JS = """
(function start(id, spec, tries) {
  // st.html can run this before its HTML is in the page: wait for the element, briefly.
  const el = document.getElementById(id);
  if (!el) { if ((tries || 0) < 60) setTimeout(() => start(id, spec, (tries || 0) + 1), 50); return; }
  if (el.dataset.ready) return;
  el.dataset.ready = '1';
  const go = () => {
    const LW = window.LightweightCharts;
    const box = el.querySelector('.lw-plot'), tip = el.querySelector('.lw-tip');
    const chart = LW.createChart(box, {
      autoSize: true, height: spec.height,
      layout: { background: { color: 'transparent' }, textColor: '__INK3__', fontFamily: 'Geist, sans-serif', fontSize: 11,
                attributionLogo: false },
      grid: { vertLines: { visible: false }, horzLines: { color: '__LINE__' } },
      rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.12, bottom: 0.06 } },
      timeScale: { borderVisible: false, fixLeftEdge: true, fixRightEdge: true },
      crosshair: { horzLine: { visible: false, labelVisible: false }, vertLine: { color: '__LINE2__', width: 1, style: 2 } },
      handleScroll: false, handleScale: false,
    });
    if (spec.bands && spec.bands.length) {
      // results days as a tinted band behind the line (added first, so drawn under it), on a hidden scale of its own
      const b = chart.addHistogramSeries({ priceScaleId: 'bands', color: spec.band, priceLineVisible: false, lastValueVisible: false,
                                           priceFormat: { type: 'custom', formatter: () => '' } });
      chart.priceScale('bands').applyOptions({ visible: false, scaleMargins: { top: 0, bottom: 0 } });
      b.setData(spec.bands.map(t => ({ time: t, value: 1 })));
    }
    const s = chart.addAreaSeries({ lineColor: spec.color, topColor: spec.color + '2E', bottomColor: spec.color + '05',
                                     lineWidth: 2, priceLineVisible: false, lastValueVisible: true,
                                     priceFormat: { type: 'price', precision: 2, minMove: 0.01 } });
    s.setData(spec.data);
    s.setMarkers(spec.marks);
    const byDay = {}; spec.trades.forEach(t => { (byDay[t.time] = byDay[t.time] || []).push(t); });
    const fit = (days) => {
      const last = spec.data[spec.data.length - 1].time, d = new Date(last);
      if (!days) { chart.timeScale().fitContent(); return; }
      d.setDate(d.getDate() - days);
      chart.timeScale().setVisibleRange({ from: d.toISOString().slice(0, 10), to: last });
    };
    el.querySelectorAll('.lw-range button').forEach(b => b.addEventListener('click', () => {
      el.querySelectorAll('.lw-range button').forEach(x => x.classList.toggle('on', x === b));
      fit(parseInt(b.dataset.d, 10));
    }));
    fit(spec.start === undefined ? 365 : spec.start);
    chart.subscribeCrosshairMove(p => {
      if (!p || !p.time || !p.point) { tip.hidden = true; return; }
      const v = p.seriesData.get(s); if (!v) { tip.hidden = true; return; }
      // built with DOM calls: Streamlit does not run an st.html script whose text holds HTML tags
      const add = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; n.textContent = text; tip.appendChild(n); };
      tip.replaceChildren();
      add('b', '', new Date(p.time + 'T00:00:00').toLocaleDateString('en-GB', {day: '2-digit', month: 'short', year: 'numeric'}));
      add('span', '', 'Close ₹' + v.value.toLocaleString('en-IN', {maximumFractionDigits: 2}));
      (byDay[p.time] || []).forEach(t => add('div', t.side, t.text));
      tip.hidden = false;
      const w = box.clientWidth, x = Math.min(Math.max(p.point.x + 14, 0), w - 230);
      tip.style.left = x + 'px';
    });
  };
  if (window.LightweightCharts) { go(); return; }
  let tag = document.getElementById('lw-lib');
  if (!tag) { tag = document.createElement('script'); tag.id = 'lw-lib'; tag.src = spec.lib; document.head.appendChild(tag); }
  tag.addEventListener('load', go);
})
"""
JS = JS.replace('__INK3__', C['ink-3']).replace('__LINE2__', C['line-strong']).replace('__LINE__', C['line'])   # ui/theme.py


def _sessions(days: pd.Series, px: pd.DataFrame) -> pd.Series:
    """Each date on the session it falls on, or the next one; dates outside the price line are dropped."""
    d = pd.DataFrame({'day': pd.to_datetime(days, errors='coerce')}).reset_index()
    d['day'] = d['day'].dt.normalize()
    d = d.dropna(subset=['day'])
    d = d[(d['day'] >= px['date'].min()) & (d['day'] <= px['date'].max())].sort_values('day')
    if d.empty:
        return pd.Series(dtype=object)
    m = pd.merge_asof(d, px[['date', 'time']].rename(columns={'date': 'day'}), on='day', direction='forward')
    return m.set_index('index')['time'].dropna()


EVENT_LOOK = {   # kind -> (shape, position, colour): insiders are arrows, deals squares, SAST crossings circles
    'deal_buy': ('square', 'belowBar', BUY), 'deal_sell': ('square', 'aboveBar', SELL), 'sast': ('circle', 'aboveBar', C['mark-sast']),
}


def price_chart(dates, closes, trades: pd.DataFrame | None, height: int = 320, key: str = '',
                events: pd.DataFrame | None = None, bands: pd.DataFrame | None = None, start: int = 365) -> str | None:
    """HTML for st.html(..., unsafe_allow_javascript=True). `trades`: seen (day made public), side (BUY/SELL),
    value (rupees), person_name, role. `events` (Company page, 19 Nov 2026): day, kind ('deal_buy', 'deal_sell',
    'sast'), text; drawn as squares (deals) and circles (SAST crossings), each line in the hover box. `bands`: day,
    text; a tinted band on each results day. `start`: the range shown first, in days (0 for all). None when there are
    fewer than five closes."""
    px = pd.DataFrame({'date': pd.to_datetime(dates, errors='coerce'), 'close': pd.to_numeric(closes, errors='coerce')})
    px = px.dropna().sort_values('date').drop_duplicates('date', keep='last')
    if len(px) < 5:
        return None
    px['time'] = px['date'].dt.strftime('%Y-%m-%d')
    data = [{'time': t, 'value': round(float(v), 2)} for t, v in zip(px['time'], px['close'])]
    marks, tips = [], []
    if trades is not None and not trades.empty and 'seen' in trades:
        t = trades.dropna(subset=['seen']).copy()
        t['day'] = pd.to_datetime(t['seen'], errors='coerce').dt.normalize()
        t = t[(t['day'] >= px['date'].min()) & (t['day'] <= px['date'].max())].sort_values('day')
        if not t.empty:
            # each trade on the session it was made public (or the next one), as the old chart did
            t = pd.merge_asof(t, px[['date', 'time']].rename(columns={'date': 'day'}), on='day', direction='forward')
            t = t.dropna(subset=['time'])
            t['cr'] = pd.to_numeric(t['value'], errors='coerce') / 1e7
            top = float(t.groupby(['time', 'side'])['cr'].sum().max() or 1)
            for (day, side), g in t.groupby(['time', 'side'], sort=True):
                cr = float(g['cr'].sum())
                buy = side == 'BUY'
                marks.append({'time': day, 'position': 'belowBar' if buy else 'aboveBar', 'shape': 'arrowUp' if buy else 'arrowDown',
                              'color': BUY if buy else SELL, 'size': round(0.8 + 1.4 * (cr / top) ** 0.5, 2)})
                for r in g.to_dict('records'):
                    who = str(r.get('person_name') or '')
                    role = str(r.get('role') or '')
                    tips.append({'time': day, 'side': 'b' if buy else 's',
                                 'text': f'{"Bought" if buy else "Sold"} ₹{r["cr"]:,.2f} Cr · {who}' + (f' ({role})' if role else '')})
    if events is not None and not events.empty and {'day', 'kind', 'text'} <= set(events.columns):
        ev = events[events['kind'].isin(list(EVENT_LOOK))].copy()
        ev['time'] = _sessions(ev['day'], px)
        for (day, kind), g in ev.dropna(subset=['time']).groupby(['time', 'kind'], sort=True):
            shape, pos, colour = EVENT_LOOK[kind]
            marks.append({'time': day, 'position': pos, 'shape': shape, 'color': colour, 'size': 1})
            tips += [{'time': day, 'side': {'deal_buy': 'b', 'deal_sell': 's'}.get(kind, 'e'), 'text': str(x)} for x in g['text']]
    marks.sort(key=lambda m: m['time'])
    band = []
    if bands is not None and not bands.empty and 'day' in bands:
        bd = bands.assign(time=_sessions(bands['day'], px)).dropna(subset=['time'])
        band = sorted(set(bd['time']))
        texts = bd['text'] if 'text' in bd else pd.Series('Results', index=bd.index)
        tips += [{'time': t, 'side': 'r', 'text': str(x)} for t, x in zip(bd['time'], texts)]
    spec = {'lib': LIB, 'height': height, 'color': PRICE, 'data': data, 'marks': marks, 'trades': tips, 'bands': band,
            'band': C['band'], 'start': start}
    cid = 'lw_' + hashlib.sha1(f'{key}|{len(data)}|{data[-1]["time"]}|{len(marks)}|{len(band)}'.encode()).hexdigest()[:10]
    on = ' class="on"'   # no backslash inside an f-string: the site runs Python 3.11
    ranges = ''.join(f'<button data-d="{d}"{on if d == start else ""}>{label}</button>'
                     for d, label in ((91, '3M'), (182, '6M'), (365, '1Y'), (0, 'All')))
    return (f'<div class="lw" id="{cid}"><div class="lw-range">{ranges}</div>'
            f'<div class="lw-plot" style="height:{height}px"></div><div class="lw-tip" hidden></div></div>'
            f'<script>{JS}("{cid}", {json.dumps(spec).replace("</", "<" + chr(92) + "/")});</script>')


BARS_JS = """
(function start(id, spec, tries) {
  // Today's trend: companies made public each week, worth a look above the line, watch out below.
  const el = document.getElementById(id);
  if (!el) { if ((tries || 0) < 60) setTimeout(() => start(id, spec, (tries || 0) + 1), 50); return; }
  if (el.dataset.ready) return;
  el.dataset.ready = '1';
  const go = () => {
    const LW = window.LightweightCharts;
    const box = el.querySelector('.lw-plot'), tip = el.querySelector('.lw-tip');
    const chart = LW.createChart(box, {
      autoSize: true, height: spec.height,
      layout: { background: { color: 'transparent' }, textColor: '__INK3__', fontFamily: 'Geist, sans-serif', fontSize: 11,
                attributionLogo: false },
      grid: { vertLines: { visible: false }, horzLines: { color: '__LINE__' } },
      rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.08, bottom: 0.08 } },
      timeScale: { borderVisible: false, fixLeftEdge: true, fixRightEdge: true, barSpacing: 26 },
      crosshair: { horzLine: { visible: false, labelVisible: false }, vertLine: { color: '__LINE2__', width: 1, style: 2 } },
      handleScroll: false, handleScale: false,
    });
    const fmt = { type: 'custom', formatter: v => String(Math.abs(Math.round(v))) };
    const up = chart.addHistogramSeries({ color: spec.buy, priceFormat: fmt, priceLineVisible: false, lastValueVisible: false });
    const dn = chart.addHistogramSeries({ color: spec.sell, priceFormat: fmt, priceLineVisible: false, lastValueVisible: false });
    up.setData(spec.look); dn.setData(spec.warn);
    chart.timeScale().fitContent();
    const look = {}, warn = {};
    spec.look.forEach(p => { look[p.time] = p.value; }); spec.warn.forEach(p => { warn[p.time] = -p.value; });
    const add = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; n.textContent = text; tip.appendChild(n); };
    chart.subscribeCrosshairMove(p => {
      if (!p || !p.time || !p.point) { tip.hidden = true; return; }
      tip.replaceChildren();
      const d = new Date(p.time + 'T00:00:00');
      add('b', '', 'Week of ' + d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' }));
      add('div', 'b', (look[p.time] || 0) + ' worth a look');
      add('div', 's', (warn[p.time] || 0) + ' to watch out');
      tip.hidden = false;
      tip.style.left = Math.min(Math.max(p.point.x + 14, 0), box.clientWidth - 190) + 'px';
    });
  };
  if (window.LightweightCharts) { go(); return; }
  let tag = document.getElementById('lw-lib');
  if (!tag) { tag = document.createElement('script'); tag.id = 'lw-lib'; tag.src = spec.lib; document.head.appendChild(tag); }
  tag.addEventListener('load', go);
})
"""
BARS_JS = BARS_JS.replace('__INK3__', C['ink-3']).replace('__LINE2__', C['line-strong']).replace('__LINE__', C['line'])   # ui/theme.py


def weekly_bars(look: pd.DataFrame, warn: pd.DataFrame, height: int = 220, key: str = '') -> str | None:
    """Today's trend: one bar per week (Monday) of the companies whose lead event was made public that week,
    Worth a look up, Watch out down. `look` / `warn` are Today's rows (with `last`)."""
    def weeks(df: pd.DataFrame) -> pd.Series:
        if df is None or df.empty or 'last' not in df:
            return pd.Series(dtype=int)
        d = pd.to_datetime(df['last'], errors='coerce').dropna()
        return (d - pd.to_timedelta(d.dt.weekday, unit='D')).dt.normalize().value_counts()
    a, b = weeks(look), weeks(warn)
    days = sorted(set(a.index) | set(b.index))
    if not days:
        return None
    span = pd.date_range(days[0], days[-1], freq='W-MON')
    look_pts = [{'time': d.strftime('%Y-%m-%d'), 'value': int(a.get(d, 0))} for d in span]
    warn_pts = [{'time': d.strftime('%Y-%m-%d'), 'value': -int(b.get(d, 0))} for d in span]
    spec = {'lib': LIB, 'height': height, 'buy': BUY, 'sell': SELL, 'look': look_pts, 'warn': warn_pts}
    cid = 'lwb_' + hashlib.sha1(f'{key}|{len(span)}|{sum(a)}|{sum(b)}'.encode()).hexdigest()[:10]
    return (f'<div class="lw" id="{cid}"><div class="lw-plot" style="height:{height}px"></div><div class="lw-tip" hidden></div></div>'
            f'<script>{BARS_JS}("{cid}", {json.dumps(spec)});</script>')
