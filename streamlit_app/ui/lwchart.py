"""The company price chart in TradingView's Lightweight Charts (owner, 22 Oct 2026): closes as an area,
3M / 6M / 1Y / All, every open-market insider trade marked on the day it was made public (one marker per day
and side, sized by value), and a hover box with the close and who traded. The library is Apache-2.0; its
logo is off and the site credits it in the footer (app.py), as its NOTICE asks.
"""
from __future__ import annotations

import hashlib
import json

import pandas as pd


LIB = 'https://cdn.jsdelivr.net/npm/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js'
BUY, SELL, PRICE = '#067647', '#B42318', '#4F46E5'

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
      layout: { background: { color: 'transparent' }, textColor: '#5E6878', fontFamily: 'Geist, sans-serif', fontSize: 11,
                attributionLogo: false },
      grid: { vertLines: { visible: false }, horzLines: { color: '#F0F2F5' } },
      rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.12, bottom: 0.06 } },
      timeScale: { borderVisible: false, fixLeftEdge: true, fixRightEdge: true },
      crosshair: { horzLine: { visible: false, labelVisible: false }, vertLine: { color: '#C9CED8', width: 1, style: 2 } },
      handleScroll: false, handleScale: false,
    });
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
    fit(365);
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


def price_chart(dates, closes, trades: pd.DataFrame | None, height: int = 320, key: str = '') -> str | None:
    """HTML for st.html(..., unsafe_allow_javascript=True). `trades`: seen (day made public), side (BUY/SELL),
    value (rupees), person_name, role. None when there are fewer than five closes."""
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
    spec = {'lib': LIB, 'height': height, 'color': PRICE, 'data': data, 'marks': marks, 'trades': tips}
    cid = 'lw_' + hashlib.sha1(f'{key}|{len(data)}|{data[-1]["time"]}'.encode()).hexdigest()[:10]
    on = ' class="on"'   # no backslash inside an f-string: the site runs Python 3.11
    ranges = ''.join(f'<button data-d="{d}"{on if d == 365 else ""}>{label}</button>'
                     for d, label in ((91, '3M'), (182, '6M'), (365, '1Y'), (0, 'All')))
    return (f'<div class="lw" id="{cid}"><div class="lw-range">{ranges}</div>'
            f'<div class="lw-plot" style="height:{height}px"></div><div class="lw-tip" hidden></div></div>'
            f'<script>{JS}("{cid}", {json.dumps(spec).replace("</", "<" + chr(92) + "/")});</script>')
