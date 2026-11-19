"""Funds: what mutual fund managers bought and sold in the month, from the fund houses' own month-end portfolios.

Owner, 19 Nov 2026: "I can't say anything what mutual funds or PMS etc buying this month or selling this month".
Every fund house files its schemes' holdings as on the last day of each month by the 10th of the next
(scripts/mf_portfolios.py collects them; insiders_clean/mf_holdings.py reads them). NPS pension fund managers file
the same month-end portfolios with PFRDA; they are collected too and shown in a section of their own, never mixed into
the mutual fund lists or the coverage line (which measures mutual funds). The month's change per stock is
what active schemes held at this month-end less what they held at the last (index funds and ETFs, which buy by rule,
kept apart; a bonus or split between the two dates applied first). The page says how many houses are in and what
share of mutual-fund holdings they are, measured against the companies' own shareholding filings.

PMS and AIFs file no holdings stock by stock; they appear only where they file a bulk or block deal or cross 5%
(Investor flows, Stakes), and the page says so instead of guessing.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st
from data import store

from screens import moves
from screens.ctx import load, need_data
from screens.proto import _company, _more, _num, _strip, _table
from ui import ds, kit
from ui.kit import esc

TOP = 15
MIN_NET_CR = 1.0          # a stock's net buying or selling under Rs 1 Cr is counted, not listed
NEW_MIN_HOUSES = 2        # "several houses started a position": two or more


def by_kind(df: pd.DataFrame | None, kind: str) -> pd.DataFrame | None:
    """Rows of one house kind: 'mf' (mutual funds; a table written before the column existed is all mutual funds) or
    'pension' (NPS pension fund managers)."""
    if df is None or df.empty:
        return df
    k = df['house_kind'].fillna('mf') if 'house_kind' in df else pd.Series('mf', index=df.index)
    return df[k == kind]


def months(stock: pd.DataFrame) -> list[str]:
    return sorted(stock['month'].dropna().unique(), reverse=True) if stock is not None and not stock.empty else []


def month_view(stock: pd.DataFrame, month: str, total_shares: dict) -> dict:
    """The month's lists: bought, sold, started by several houses, left; each row with % of the company where the
    company's total shares are known (from its latest shareholding filing)."""
    s = stock[stock['month'] == month].copy()
    if s.empty:
        return {'bought': s, 'sold': s, 'started': s, 'left': s, 'small': 0}
    tot = s['isin'].map(total_shares)
    s['pct_of_company'] = (s['active_net'] / tot * 100).where(tot.gt(0))
    big = s['active_net_cr'].abs().ge(MIN_NET_CR)
    bought = s[big & s['active_net'].gt(0)].sort_values('active_net_cr', ascending=False)
    sold = s[big & s['active_net'].lt(0)].sort_values('active_net_cr')
    started = s[s['houses_new'].ge(NEW_MIN_HOUSES)].sort_values(['houses_new', 'active_net_cr'], ascending=False)
    left = s[s['houses_exit'].ge(1)].sort_values(['houses_exit', 'houses_cutting'], ascending=False)
    small = int((~big & s['active_net'].ne(0)).sum())
    return {'bought': bought, 'sold': sold, 'started': started, 'left': left, 'small': small}


def _label(month: str) -> str:
    return pd.Period(month, 'M').strftime('%B %Y')


def _rows(df: pd.DataFrame, syms: dict, names: dict) -> list[dict]:
    out = []
    for r in df.head(TOP).to_dict('records'):
        isin = r['isin']
        out.append({
            'co': _company(names.get(isin) or r.get('name'), syms.get(isin)),
            'net': f'<b>{esc(kit.rupees(r["active_net_cr"] * 1e7))}</b>' if kit._finite(r.get('active_net_cr')) is not None else _num(None),
            'pct': _num(r.get('pct_of_company'), '{:+.2f}%'),
            'houses': f'{int(r["houses_adding"])} adding · {int(r["houses_cutting"])} cutting',
            'held': f'{int(r["houses_holding"])}',
            'price': esc(kit.price(r['price'])) if kit._finite(r.get('price')) is not None else _num(None),
        })
    return out


COLS = [('co', 'Company', 'l'), ('net', 'Net, active funds', 'r'), ('pct', '% of company', 'r'), ('houses', 'Fund houses', 'l'),
        ('held', 'Houses holding', 'r'), ('price', 'Month-end price', 'r')]


def _coverage_line(cov: pd.DataFrame) -> str:
    if cov is None or cov.empty or 'weighted_ratio' not in cov:
        return 'How much of the industry these houses are is measured at each quarter end; not measured yet.'
    c = cov.sort_values('month').iloc[-1]
    return (f'At the {_label(c["month"])} quarter end the {int(c["houses"])} houses collected held '
            f'{c["weighted_ratio"] * 100:.0f}% of the shares mutual funds held in {int(c["companies"]):,} companies '
            f'(their own shareholding filings).')


def render():
    ctx = load()
    if not need_data(ctx):
        return
    stock_all, cov, ch_all = store.table('mf_stock_month'), store.table('mf_coverage'), store.table('mf_changes')
    stock, ch = by_kind(stock_all, 'mf'), by_kind(ch_all, 'mf')        # the page's lists: mutual funds
    nps = by_kind(stock_all, 'pension')                                # NPS pension funds: a section of their own
    ms = months(stock_all)
    _strip(ctx, ['fund houses\' month-end portfolios', 'active schemes; index funds and ETFs apart', 'PMS and AIFs file no holdings'])
    if not ms:
        ds.head('Funds', 'What did fund managers buy and sell this month?',
                ['The fund houses\' month-end portfolios are not collected yet. Until they are, fund buying shows only in '
                 'bulk and block deals (Investor flows) and 5% crossings (Stakes).'])
        st.html(_more('investor-flows', 'Fund trades in bulk and block deals'))
        return
    with st.container(key='fd_bar', horizontal=True):
        month = st.selectbox('Month', ms, format_func=_label, key='fd_month', label_visibility='collapsed', width=200)
    px, hold, names = moves.lookups(ctx)
    sec = ctx.securities
    syms = dict(zip(sec['isin'], sec['nse_symbol'])) if sec is not None and not sec.empty and 'nse_symbol' in sec else {}
    tot = {i: r.get('total_shares') for i, r in hold.items()}
    v = month_view(stock, month, tot)
    houses = int(ch.loc[ch['month'] == month, 'amc'].nunique()) if ch is not None and not ch.empty else 0
    lead_b = ', '.join(names.get(i) or n for i, n in zip(v['bought']['isin'].head(3), v['bought']['name'].head(3)))
    lead_s = ', '.join(names.get(i) or n for i, n in zip(v['sold']['isin'].head(2), v['sold']['name'].head(2)))
    ds.head(f'Funds · month-end {_label(month)} · {houses} fund houses',
            (f'Fund managers bought most of <b>{esc(lead_b)}</b>' if lead_b else 'No net buying of ₹1 Cr or more')
            + (f' and sold most of <b>{esc(lead_s)}</b>' if lead_s else ''),
            [_coverage_line(cov)])
    ds.stats([('Stocks bought', f'{len(v["bought"]):,}', f'net ₹1 Cr and over', 'up'),
              ('Stocks sold', f'{len(v["sold"]):,}', 'net ₹1 Cr and over', 'down'),
              ('New in several houses', f'{len(v["started"]):,}', f'{NEW_MIN_HOUSES}+ houses started'),
              ('Houses leaving', f'{len(v["left"]):,}', 'stocks at least one house sold out of')])
    ds.section(f'What did fund managers buy most in {_label(month)}?',
               'Shares active schemes held at the month end less at the month end before, at the month-end price')
    ds.html(_table(COLS, _rows(v['bought'], syms, names)) if len(v['bought']) else '<p class="dt-empty">No stock bought for ₹1 Cr or more.</p>')
    ds.section('What did they sell most?', 'The same, for net selling')
    ds.html(_table(COLS, _rows(v['sold'], syms, names)) if len(v['sold']) else '<p class="dt-empty">No stock sold for ₹1 Cr or more.</p>')
    ds.section(f'Where did {NEW_MIN_HOUSES} or more houses start a position?', 'A house holding none at the month end before')
    ds.html(_table(COLS, _rows(v['started'], syms, names)) if len(v['started']) else '<p class="dt-empty">None this month.</p>')
    ds.section('Where are houses selling out?', 'A house that held it at the month end before and holds none now')
    ds.html(_table(COLS, _rows(v['left'], syms, names)) if len(v['left']) else '<p class="dt-empty">None this month.</p>')
    if nps is not None and not nps.empty and (nps['month'] == month).any():
        pv = month_view(nps, month, tot)
        mgrs = int(ch_all.loc[(ch_all['month'] == month) & ch_all['house_kind'].eq('pension'), 'amc'].nunique()) \
            if ch_all is not None and not ch_all.empty and 'house_kind' in ch_all else 0
        ds.section('What did NPS pension funds add and cut?',
                   f'{mgrs} NPS pension fund managers, every scheme (E, C, G, government, APY ...), month end to month end. '
                   'PFRDA\'s investment rules keep NPS equity to large listed companies and the schemes largely follow '
                   'the index: read this as where pension money went, not as stock picks. Not in the lists above.')
        ds.html('<p><b>Added most</b></p>' + (_table(COLS, _rows(pv['bought'], syms, names)) if len(pv['bought']) else
                '<p class="dt-empty">No stock added for ₹1 Cr or more.</p>'))
        ds.html('<p><b>Cut most</b></p>' + (_table(COLS, _rows(pv['sold'], syms, names)) if len(pv['sold']) else
                '<p class="dt-empty">No stock cut for ₹1 Cr or more.</p>'))
    ds.record(f'{v["small"]:,} stocks with net moves under ₹{MIN_NET_CR:.0f} Cr counted, not listed. Index funds and ETFs are left out '
              'of these lists: they buy what their index holds. PMS and AIFs file no holdings stock by stock; they show only in '
              'bulk and block deals and 5% crossings.')
    st.html(_more('investor-flows', 'Fund trades in bulk and block deals'))
    st.html(_more('ownership', 'Quarterly fund holdings, every fund (shareholding filings)'))
