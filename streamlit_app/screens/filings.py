"""Filings read: every filing the announcement reader has read (clean/current/announcement_reads.parquet,
last 60 days), as the Brief's cards, with filters by heading, period, exchange, company size, search and
"2 readers agree". The page address keeps the heading and period, so a view can be bookmarked."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from data import store
from ui import kit

from screens import filings_read as fr
from screens.ctx import load

# Headings over the reader's categories (scripts/announcement_sample.py CATEGORIES); a category missing here
# goes under Other, so a new one is never hidden.
HEADINGS = {
    'Fund raising': ('qip', 'preferential', 'rights', 'warrant_conversion', 'debt_issue', 'esop'),
    'Buybacks & payouts': ('buyback_open_market', 'buyback_tender', 'dividend', 'bonus_split'),
    'Acquisitions & restructuring': ('acquisition', 'divestment', 'merger_demerger', 'agreement', 'open_offer',
                                     'delisting', 'stake_change'),
    'Orders & business': ('order_win', 'product_launch', 'licence_approval', 'operations_start', 'business_update'),
    'Capex & capacity': ('capex',),
    'Results': ('financial_results',),
    'Ratings': ('rating_upgrade', 'rating_downgrade', 'rating_reaffirmed', 'rating_assigned'),
    'Debt & distress': ('default', 'restructuring', 'insolvency'),
    'Legal & regulatory': ('legal_regulatory', 'fraud'),
    'Disruption': ('disruption',),
    'Management & governance': ('auditor_resignation', 'management_change', 'corporate_change', 'pledge'),
}   # 'deal_or_dispute' (reads before live-3: deals and legal matters in one) goes under Other
OTHER = 'Other'
PERIODS = {1: 'Today and yesterday', 7: 'Last 7 days', 30: 'Last 30 days', 60: 'Last 60 days'}
SIZES = ('Large', 'Mid', 'Small', 'Micro')
LIMIT = 120


def heading_of(category) -> str:
    return next((h for h, cats in HEADINGS.items() if category in cats), OTHER)


def _agreed(x) -> bool:
    return any(v is True for v in fr._json(x, {}).values())


def pick(r: pd.DataFrame, headings, exchanges, sizes, query: str, agreed_only: bool, size_of: dict) -> pd.DataFrame:
    """The cards the filters keep (rows of filings_read.recent)."""
    if r.empty:
        return r
    keep = r['category'].map(heading_of).isin(headings)
    if exchanges:
        keep &= r['exchange'].isin(exchanges)
    if sizes and len(sizes) < len(SIZES):
        keep &= r['isin'].map(size_of).isin(sizes) if 'isin' in r else False
    q = (query or '').strip().lower()
    if q:
        text = (r['symbol'].fillna('').astype(str) + ' ' + r['company'].fillna('').astype(str)).str.lower()
        keep &= text.str.contains(q, regex=False)
    if agreed_only:
        keep &= r['agreed'].map(_agreed) if 'agreed' in r else False
    return r[keep]


def render():
    kit.head('Filings read', 'NSE and BSE announcements read by the backend: what happened, the key terms and '
                             'the figures, every number checked against the filing\'s own words.')
    reads = store.table('announcement_reads')
    if reads.empty:
        kit.empty('No filings read yet: the reader writes its table as it reads (every 10 to 15 minutes).')
        return
    qp = st.query_params
    days = int(qp.get('days', 7)) if str(qp.get('days', 7)).isdigit() and int(qp.get('days', 7)) in PERIODS else 7
    since = pd.Timestamp.now(tz='Asia/Kolkata').tz_localize(None).normalize() - pd.Timedelta(days=days)
    r = fr.recent(reads, since)
    counts = r['category'].map(heading_of).value_counts() if not r.empty else pd.Series(dtype=int)
    names = [h for h in [*HEADINGS, OTHER] if counts.get(h, 0)]
    wanted = [h for h in str(qp.get('h', '')).split(',') if h in names] or names

    c1, c2 = st.columns([3, 1])
    with c1:
        headings = st.pills('Heading', names, default=wanted, selection_mode='multi', key='fl_h',
                            format_func=lambda h: f'{h} · {int(counts.get(h, 0))}')
    with c2:
        days_new = st.selectbox('Period', list(PERIODS), index=list(PERIODS).index(days), format_func=PERIODS.get, key='fl_d')
    c3, c4, c5, c6 = st.columns([1, 2, 2, 1])
    with c3:
        exchanges = st.pills('Exchange', ['NSE', 'BSE'], default=['NSE', 'BSE'], selection_mode='multi', key='fl_x')
    with c4:
        sizes = st.pills('Company size', SIZES, default=list(SIZES), selection_mode='multi', key='fl_s')
    with c5:
        query = st.text_input('Search', placeholder='Company or symbol', key='fl_q', label_visibility='collapsed')
    with c6:
        agreed_only = st.toggle('2 readers agree', value=False, key='fl_a', help='Only cards where a second model read '
                                'a value the same way')

    chosen = sorted(headings or [], key=[*HEADINGS, OTHER].index)
    qp['days'] = str(days_new)                 # the address keeps the view, so it can be bookmarked
    if chosen and set(chosen) != set(names):
        qp['h'] = ','.join(chosen)
    elif 'h' in qp:
        del qp['h']
    if days_new != days:
        st.rerun()

    ctx = load()
    size_of = (ctx.prices.drop_duplicates('isin').set_index('isin')['mcap_bucket'].to_dict()
               if not ctx.prices.empty and 'mcap_bucket' in ctx.prices else {})
    shown = pick(r, chosen, exchanges, sizes, query, agreed_only, size_of)
    st.html(fr.coverage_html(fr.coverage(reads, since)))
    with kit.card(f'{kit.plural(len(shown), "filing")}', 'fl_cards',
                  f'{PERIODS[days].lower()}, newest first' + (f'; the first {LIMIT}' if len(shown) > LIMIT else '')):
        if shown.empty:
            kit.empty('Nothing matches these filters.')
        else:
            st.html(fr.LEGEND + fr.cards_html(shown, reads, ctx, store.price_history(), limit=LIMIT))
    kit.caption('Read by free models in the backend (NVIDIA, Z.ai, Groq, Gemini); a value is shown only when its quote '
                'is in the filing, and every figure in a headline or point is one of its quote\'s numbers. Routine '
                'filings, companies below Rs 100 Cr and concall notices are not read. Check the filing before acting.')
