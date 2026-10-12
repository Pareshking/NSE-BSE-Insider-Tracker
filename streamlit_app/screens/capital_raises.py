"""Capital raises: dilution risk and promoter funding terms.

Sections from docs/DATA_TO_PAGES.md: S14 upcoming capital moves (board
meetings) and S15 corporate actions; S16 preferential issues and where each
stands, S17 offer price against the market, S18 lock-in expiries, and rights
issues, all from NSE's two-stage filings (insiders_clean/issues.py). The SEBI
ICDR minimum price needs VWAP from daily volumes and is not computed yet; the
page says so instead of showing a stand-in."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from ui import kit

from screens.ctx import load, with_prices

PURPOSES = {'buyback': 'Buyback', 'rights': 'Rights', 'bonus': 'Bonus', 'split': 'Split', 'dividend': 'Dividend'}
MEETING_FOCUS = ['fund_raising', 'preferential', 'buyback', 'rights', 'bonus', 'split', 'dividend', 'results']
ALLOTTEE_LABEL = {'PROMOTER': 'Promoters', 'NON_PROMOTER': 'Non-promoters', 'MIXED': 'Promoters and others'}
LOCK_IN_RECENT_DAYS = 30


def _vs_market(offer, close):
    ok = pd.to_numeric(offer, errors='coerce').gt(0) & pd.to_numeric(close, errors='coerce').gt(0)
    return ((pd.to_numeric(offer, errors='coerce') / pd.to_numeric(close, errors='coerce') - 1) * 100).where(ok)


def issue_rows(records: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """One row per issue as far as the data shows: an allotted or listed
    record (with its approval's amount and allottee when the two are linked),
    or an approval no listing record points to."""
    if records is None or records.empty:
        return pd.DataFrame()
    r = records.copy()
    linked = set(r.loc[r['stage'] == 'listing', 'linked_app_id'].dropna())
    approved = r[(r['stage'] == 'in_principle') & ~r['app_id'].isin(linked)].assign(status='Approved in principle')
    listed = r[r['stage'] == 'listing'].assign(status='Allotted or listed')
    rows = pd.concat([listed, approved], ignore_index=True)
    rows['nse_symbol'] = rows['symbol']
    rows['to'] = rows['allottee_category'].map(ALLOTTEE_LABEL) if 'allottee_category' in rows else None
    amount = rows['amount_total'] if 'amount_total' in rows else pd.Series(index=rows.index, dtype=float)
    rows['amount'] = amount.fillna(rows['amount_raised']) if 'amount_raised' in rows else amount
    rows = with_prices(rows, prices)
    rows['vs_market'] = _vs_market(rows.get('offer_price'), rows['latest_close'])
    return rows.sort_values('posted_on', ascending=False, na_position='last', kind='stable').reset_index(drop=True)


def lock_in_calendar(records: pd.DataFrame, prices: pd.DataFrame, today: pd.Timestamp) -> pd.DataFrame:
    """Lock-in expiries from the trading-approval date (promoters 18 months,
    others 6), earliest first, from a month ago on. A mixed allotment's split
    between promoters and others is not in the filing, so it shows the whole
    allotment and no market value."""
    if records is None or records.empty or 'lock_in_promoter_until' not in records:
        return pd.DataFrame()
    ls = records[records['stage'] == 'listing']
    parts = []
    for col, who in (('lock_in_promoter_until', 'Promoters'), ('lock_in_other_until', 'Others')):
        part = ls[ls[col].notna()]
        if not part.empty:
            parts.append(part.assign(expires=pd.to_datetime(part[col]), who=who))
    if not parts:
        return pd.DataFrame()
    rows = pd.concat(parts, ignore_index=True)
    rows = rows[rows['expires'] >= today.normalize() - pd.Timedelta(days=LOCK_IN_RECENT_DAYS)].copy()
    rows['nse_symbol'] = rows['symbol']
    rows['days_left'] = (rows['expires'] - today.normalize()).dt.days
    rows['note'] = rows['allottee_category'].map(lambda c: 'Mixed allotment: promoter and other split not filed' if c == 'MIXED' else '')
    rows = with_prices(rows, prices)
    rows['at_market'] = (pd.to_numeric(rows['shares_allotted'], errors='coerce') * pd.to_numeric(rows['latest_close'], errors='coerce')).where(rows['note'].eq(''))
    return rows.sort_values('expires').reset_index(drop=True)


def rights_rows(records: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """Rights issues: the listing record (ratio, price, dates) or an approval no listing record points to."""
    if records is None or records.empty:
        return pd.DataFrame()
    r = records.copy()
    linked = set(r.loc[r['stage'] == 'listing', 'linked_app_id'].dropna())
    approved = r[(r['stage'] == 'in_principle') & ~r['app_id'].isin(linked)].assign(status='Approved in principle')
    rows = pd.concat([r[r['stage'] == 'listing'].assign(status='Allotted or listed'), approved], ignore_index=True)
    rows['nse_symbol'] = rows['symbol']
    amount = rows['amount_total'] if 'amount_total' in rows else pd.Series(index=rows.index, dtype=float)
    rows['amount'] = amount.fillna(rows['amount_raised']) if 'amount_raised' in rows else amount
    rows = with_prices(rows, prices)
    rows['vs_market'] = _vs_market(rows.get('offer_price'), rows['latest_close'])
    return rows.sort_values('posted_on', ascending=False, na_position='last', kind='stable').reset_index(drop=True)


def link_summary(records: pd.DataFrame) -> str:
    ls = records[records['stage'] == 'listing'] if not records.empty else records
    if ls.empty:
        return ''
    c = ls['link_status'].value_counts()
    return (f"{len(ls)} allotment records: {int(c.get('linked', 0))} matched to their approval (same ISIN, one approval in "
            f"the 180 days before), {int(c.get('ambiguous', 0))} with more than one possible approval, "
            f"{int(c.get('no_in_principle_in_data', 0))} whose approval is not in NSE's latest-100 list. "
            "Only matched records show who gets the shares, the amount and a lock-in date.")


def render():
    ctx = load()
    kit.head('Capital raises', 'Who is about to raise money or buy back shares, and on what terms: dilution risk and '
                               'promoter funding in one place.')
    pref = ctx.preferential
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
                kit.Col('amount', 'Amount', 'money'), kit.Col('shares_allotted', 'Shares allotted', 'shares', phone=False),
                kit.Col('trading_approval_date', 'Trading approval', 'date', phone=False)],
                limit=100, download='preferential_issues')
            kit.caption(link_summary(pref))
        with kit.card('Offer price against the market', 'cr_px', 'allotted issues'):
            allotted = issues[(issues['status'] == 'Allotted or listed') & issues['offer_price'].notna()]
            kit.table(allotted, [
                kit.Col('posted_on', 'Posted', 'date'), kit.Col('company', 'Company', 'co'), kit.Col('to', 'Shares go to'),
                kit.Col('offer_price', 'Offer price', 'price'), kit.Col('latest_close', 'Market price now', 'price'),
                kit.Col('vs_market', 'Offer vs market now', 'spct', help='Negative = shares were offered below today\'s market price')],
                limit=100, empty_text='No allotted issues with an offer price yet.')
            kit.caption("Market price now is the latest close in our NSE and BSE price files, not the price when the issue was priced. "
                        "The SEBI ICDR minimum (higher of the 90-day and 10-day VWAP) needs daily volumes and is not computed yet.")
        with kit.card('Lock-in expiries', 'cr_lock', 'when newly allotted shares can first be sold'):
            cal = lock_in_calendar(pref, ctx.prices, today)
            kit.table(cal, [
                kit.Col('expires', 'Expires', 'date'), kit.Col('days_left', 'Days', 'num'), kit.Col('company', 'Company', 'co'),
                kit.Col('who', 'Whose shares'), kit.Col('shares_allotted', 'Shares allotted', 'shares', phone=False),
                kit.Col('at_market', 'At market now', 'money', phone=False), kit.Col('note', 'Note', phone=False)],
                limit=100, empty_text='No lock-in dates yet: they need an allotment record matched to its approval.')
            kit.caption('Promoters 18 months and others 6 months from the trading-approval date (SEBI ICDR, preferential allotments). '
                        'Dates come only from matched records; the first 30 days after an expiry stay on the list.')
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
            kit.caption(link_summary(ctx.rights))

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
            rows = rows[rows['meeting_date'] >= pd.Timestamp.now().normalize() - pd.Timedelta(days=7)].sort_values('meeting_date')
            if rows.empty:
                kit.empty('No meetings for these purposes from last week onwards.')
            else:
                kit.table(rows.assign(nse_symbol=rows['symbol'], what=rows['purposes'].str.replace('_', ' ').str.replace(',', ', ').str.capitalize()), [
                    kit.Col('meeting_date', 'Meeting', 'date'), kit.Col('company', 'Company', 'co'),
                    kit.Col('what', 'To consider'), kit.Col('description', 'As filed', phone=False)], limit=100)

    with kit.card('Corporate actions', 'cr_actions', 'buybacks, rights, bonuses, splits, dividends'):
        a = ctx.actions
        if a.empty:
            kit.empty('Corporate actions arrive with the daily NSE events collection.')
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
            kit.caption("Rights price = face value + the premium NSE lists. Buyback price and route (tender or open "
                        "market) are not in NSE's corporate-actions feed; they come from the offer documents later.")
