"""Capital raises: dilution risk and promoter funding terms.

Sections from docs/DATA_TO_PAGES.md: S14 upcoming capital moves (board
meetings) and S15 corporate actions; S16 preferential issues and where each
stands, the proposed allottees, S17 offer price against the ICDR minimum and
the market, S18 lock-in expiries, rights issues and QIPs, all from NSE's
two-stage filings and their XBRL (insiders_clean/issues.py). The ICDR minimum
shown first is the one the company filed; ours (from the bhavcopy) sits beside
it as a check and is labelled."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from data import store
from ui import kit

# The issue row builders live in screens/ctx.py (shared with the Filings page); re-exported for the pages that import them here.
from screens.ctx import (ALLOTTEE_LABEL, LOCK_IN_RECENT_DAYS, _amount, _on_today, _stage_rows,  # noqa: F401
                         _vs_market, issue_rows, load, lock_in_calendar, qip_rows, rights_rows)

PURPOSES = {'buyback': 'Buyback', 'rights': 'Rights', 'bonus': 'Bonus', 'split': 'Split', 'dividend': 'Dividend'}
MEETING_FOCUS = ['fund_raising', 'preferential', 'buyback', 'rights', 'bonus', 'split', 'dividend', 'results']


def allottee_rows(allottees: pd.DataFrame, known_ids: set) -> pd.DataFrame:
    """Proposed or actual allottees, newest first; a name links to its page only
    when that person or fund also appears in our insider filings or deals."""
    if allottees is None or allottees.empty:
        return pd.DataFrame()
    a = allottees.copy()
    a['nse_symbol'] = a['symbol']
    a['client_id'] = a['allottee_id'].where(a['allottee_id'].isin(known_ids))
    if 'promoter' in a:
        a['promoter_text'] = a['promoter'].map(lambda v: 'Yes' if v is True else 'No' if v is False else '')
    return a.sort_values('posted_on', ascending=False, na_position='last', kind='stable').reset_index(drop=True)


def link_summary(records: pd.DataFrame, shown: str = 'who gets the shares, the amount and the filed ICDR minimum') -> str:
    ls = records[records['stage'] == 'listing'] if not records.empty else records
    if ls.empty:
        return ''
    c = ls['link_status'].value_counts()
    more = int(c.get('more_shares_than_approved', 0))
    return (f"{len(ls)} allotment records: {int(c.get('linked', 0))} matched to their approval (same ISIN, one approval in "
            f"the 180 days before), {int(c.get('ambiguous', 0))} with more than one possible approval, "
            f"{int(c.get('no_in_principle_in_data', 0))} whose approval is not in the filings we hold"
            + (f", {more} not matched because they allot more shares than the only approval proposed" if more else '')
            + f". Only matched records show {shown}.")


def _known_ids(ctx) -> set:
    ids = set()
    for df, col in ((ctx.trades, 'person_id'), (ctx.deals, 'client_id')):
        if df is not None and not df.empty and col in df:
            ids.update(df[col].dropna())
    return ids


def render():
    ctx = load()
    kit.head('Capital raises', 'Who is about to raise money or buy back shares, and on what terms: dilution risk and '
                               'promoter funding in one place.')
    pref = ctx.preferential
    known = _known_ids(ctx)
    if pref is None or pref.empty:
        kit.note('Preferential issue pipeline, offer price against the market and the lock-in calendar are pending.',
                 'The data is collected and cleaned nightly; these sections appear after the next clean run.')
    else:
        issues = issue_rows(pref, ctx.prices)
        today = ctx.ref if ctx.ref is not None else pd.Timestamp.now()
        with kit.card('Preferential issues', 'cr_pref', 'approved in principle, then allotted and listed'):
            kinds = st.pills('Stage', ['Allotted or listed', 'Approved in principle'], default=['Allotted or listed', 'Approved in principle'],
                             selection_mode='multi', key='cr_pref_stage')
            rows = issues[issues['status'].isin(kinds)] if kinds else issues
            kit.table(rows, [
                kit.Col('posted_on', 'Posted', 'date'), kit.Col('company', 'Company', 'co'), kit.Col('status', 'Stage'),
                kit.Col('to', 'Shares go to', help='From the In-Principle record, shown only when it is matched to the allotment'),
                kit.Col('instruments', 'Instrument', phone=False, help='As filed in the In-Principle XBRL'),
                kit.Col('amount', 'Amount', 'money'), kit.Col('shares_allotted', 'Shares allotted', 'shares', phone=False),
                kit.Col('icdr_min_price', 'ICDR minimum', 'price', phone=False, help='Minimum issue price per SEBI ICDR, as the company filed it'),
                kit.Col('trading_approval_date', 'Trading approval', 'date', phone=False)],
                limit=100, download='preferential_issues')
            kit.caption(link_summary(pref))
        with kit.card('Offer price against the ICDR minimum and the market', 'cr_px', 'allotted issues'):
            allotted = issues[(issues['status'] == 'Allotted or listed') & issues['offer_price'].notna()]
            kit.table(allotted, [
                kit.Col('posted_on', 'Posted', 'date'), kit.Col('company', 'Company', 'co'), kit.Col('to', 'Shares go to', phone=False),
                kit.Col('offer_price', 'Offer price', 'price'),
                kit.Col('icdr_min_price', 'ICDR minimum, filed', 'price', help='The minimum price the company filed with NSE (higher of the 90- and 10-day VWAP before the relevant date, or its own valuation)'),
                kit.Col('vs_icdr_min', 'Offer vs minimum', 'spct', phone=False),
                kit.Col('icdr_min_ours', 'Minimum, our estimate', 'price', phone=False, help='Ours: higher of the 90- and 10-session VWAP before the filed relevant date, from our NSE/BSE bhavcopy'),
                kit.Col('latest_close', 'Market price now', 'price', phone=False),
                kit.Col('vs_market', 'Offer vs market now', 'spct', help='Negative = shares were offered below today\'s market price')],
                limit=100, empty_text='No allotted issues with an offer price yet.')
            kit.caption('The filed minimum comes from the In-Principle XBRL and shows only on allotments matched to their approval. '
                        'Our estimate needs the relevant date in that filing and 90 trading sessions before it in our price files; '
                        'it is left blank across a split or bonus. Market price now is the latest close, not the price when the issue was priced.')
        allot = allottee_rows(store.table('preferential_allottees'), known)
        if not allot.empty:
            with kit.card('Who gets the shares', 'cr_allot', 'proposed allottees, from each In-Principle XBRL'):
                kit.table(allot, [
                    kit.Col('posted_on', 'Posted', 'date'), kit.Col('company', 'Company', 'co'),
                    kit.Col('allottee', 'Allottee', 'client', sub='security_type'),
                    kit.Col('securities', 'Securities', 'shares'),
                    kit.Col('promoter_text', 'Promoter', phone=False, help='From the issue\'s category; blank for an issue to promoters and others')],
                    limit=150, download='preferential_allottees')
                kit.caption('The XBRL names each proposed allottee but not whether that allottee is a promoter: an issue filed as '
                            'to promoters marks all its allottees Yes, one to non-promoters No, a mixed issue leaves it blank.')
        with kit.card('Lock-in expiries', 'cr_lock', 'when newly allotted shares can first be sold'):
            cal = lock_in_calendar(pref, ctx.prices, today, store.table('preferential_lockins'))
            kit.table(cal, [
                kit.Col('expires', 'Expires', 'date'), kit.Col('days_left', 'Days', 'num'), kit.Col('company', 'Company', 'co'),
                kit.Col('what', 'Lock-in'), kit.Col('shares', 'Shares', 'shares', phone=False),
                kit.Col('at_market', 'At market now', 'money', phone=False), kit.Col('note', 'Note', phone=False)],
                limit=100, empty_text='No lock-in dates yet.')
            kit.caption('"As filed": the lock-in lines in the company\'s listing XBRL, counted from the trading-approval date. '
                        '"Rule": none was filed, so promoters 18 months and others 6 (SEBI ICDR), only for allotments matched '
                        'to their approval. The first 30 days after an expiry stay on the list.')
    rights = rights_rows(ctx.rights, ctx.prices)
    if not rights.empty:
        with kit.card('Rights issues', 'cr_rights', 'approved in principle, then allotted and listed'):
            kit.table(rights, [
                kit.Col('posted_on', 'Posted', 'date'), kit.Col('company', 'Company', 'co'), kit.Col('status', 'Stage'),
                kit.Col('ratio', 'Ratio'), kit.Col('offer_price', 'Rights price', 'price'),
                kit.Col('latest_close', 'Market price now', 'price', phone=False),
                kit.Col('vs_market', 'Rights vs market now', 'spct', phone=False),
                kit.Col('record_date', 'Record date', 'date', phone=False),
                kit.Col('issue_close_date', 'Closes', 'date', phone=False), kit.Col('amount', 'Amount', 'money', phone=False)],
                limit=100, download='rights_issues')
            kit.caption(link_summary(ctx.rights, "the approval's amount"))
    qip = qip_rows(store.table('qip'), ctx.prices)
    if not qip.empty:
        with kit.card('QIPs', 'cr_qip', 'placements with institutions: approved, then allotted and listed'):
            kit.table(qip, [
                kit.Col('posted_on', 'Posted', 'date'), kit.Col('company', 'Company', 'co'), kit.Col('status', 'Stage'),
                kit.Col('issue_price', 'Issue price', 'price'),
                kit.Col('floor_price', 'Floor price', 'price', phone=False, help='Minimum issue price per unit, as filed'),
                kit.Col('discount_per_share', 'Discount/share', 'price', phone=False, help='As filed'),
                kit.Col('vs_market', 'Issue vs market now', 'spct', phone=False),
                kit.Col('amount', 'Amount', 'money'), kit.Col('allottees', 'Allottees', 'num', phone=False),
                kit.Col('trading_approval_date', 'Trading approval', 'date', phone=False)],
                limit=100, download='qips')
            kit.caption('From NSE\'s QIP filings, both stages. Floor price and discount are as filed: some filings give the '
                        'issue price as the floor. Market price now is the latest close.')
        buyers = allottee_rows(store.table('qip_allottees'), known)
        if not buyers.empty:
            with kit.card('Who bought the QIPs', 'cr_qip_buyers', 'allottees named in each QIP listing XBRL'):
                kit.table(buyers, [
                    kit.Col('allotment_date', 'Allotted', 'date'), kit.Col('company', 'Company', 'co'),
                    kit.Col('allottee', 'Allottee', 'client', sub='category'), kit.Col('shares', 'Shares', 'shares', phone=False),
                    kit.Col('pct_of_issue', '% of issue', 'pct')], limit=150, download='qip_allottees')

    with kit.card('Upcoming board meetings on capital moves', 'cr_meet', 'from NSE board-meeting intimations'):
        m = ctx.meetings
        if m.empty:
            kit.empty('Board meetings arrive with the daily NSE events collection.')
        else:
            m = m.copy()
            m['meeting_date'] = pd.to_datetime(m['meeting_date'], errors='coerce')
            focus = st.pills('Considering', MEETING_FOCUS, default=['fund_raising', 'preferential', 'buyback'],
                             selection_mode='multi', format_func=lambda x: x.replace('_', ' ').capitalize(), key='cr_focus')
            cols = [c for c in (focus or []) if c in m]
            rows = m[m[cols].astype('boolean').fillna(False).any(axis=1)] if cols else m
            rows = rows[rows['meeting_date'] >= (ctx.ref if ctx.ref is not None else pd.Timestamp.now()).normalize() - pd.Timedelta(days=7)].sort_values('meeting_date')
            if rows.empty:
                kit.empty('No meetings for these purposes from last week onwards.')
            else:
                kit.table(rows.assign(nse_symbol=rows['symbol'], what=rows['purposes'].str.replace('_', ' ').str.replace(',', ', ').str.capitalize()), [
                    kit.Col('meeting_date', 'Meeting', 'date'), kit.Col('company', 'Company', 'co'),
                    kit.Col('what', 'To consider'), kit.Col('description', 'As filed', phone=False)], limit=100)

    from screens import buybacks  # buyback price and route (TODO 12)
    buybacks.card(store.table('buybacks'), ctx.prices)

    with kit.card('Corporate actions', 'cr_actions', 'buybacks, rights, bonuses, splits, dividends'):
        a = ctx.actions
        if a.empty:
            kit.empty('Corporate actions arrive with the daily NSE and BSE events collections.')
        else:
            a = a.copy()
            a['ex_date'] = pd.to_datetime(a['ex_date'], errors='coerce')
            kinds = st.pills('Type', list(PURPOSES), default=['buyback', 'rights', 'bonus', 'split'],
                             selection_mode='multi', format_func=PURPOSES.get, key='cr_kinds')
            rows = a[a['purpose'].isin(kinds)] if kinds else a
            rows = rows.sort_values('ex_date', ascending=False)
            kit.table(rows.assign(nse_symbol=rows['symbol'], kind=rows['purpose'].map(PURPOSES)), [
                kit.Col('ex_date', 'Ex-date', 'date'), kit.Col('company', 'Company', 'co'), kit.Col('kind', 'Type'),
                kit.Col('subject', 'As filed', phone=False), kit.Col('ratio', 'Ratio'),
                kit.Col('rights_issue_price', 'Rights price', 'price', phone=False),
                kit.Col('dividend_per_share', 'Dividend/share', 'price', phone=False),
                kit.Col('record_date', 'Record date', 'date', phone=False)], limit=150, download='corporate_actions')
            kit.caption("Rights price = face value + the premium NSE lists; BSE's list gives no rights ratio or price. "
                        "An action on both exchanges is shown once (NSE's row); BSE rows are tagged BSE. Buyback price and "
                        "route are not in either corporate-actions feed; the Buybacks list above takes them from NSE's "
                        "tender-offer list and daily buyback reports.")
