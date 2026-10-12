"""Preferential and rights issues from NSE's two-stage filings (docs/TODO.md item H).

NSE returns the latest 100 records of each stage a day, so the stored data is a
set of daily snapshots of two kinds of record:

* In-Principle  -- board date, amount, consideration and, for preferential
                   issues, whether the allottee is a promoter.
* Listing Stage -- offer price, shares allotted, allotment date, listing and
                   trading-approval dates (rights: also ratio, record date,
                   issue open and close).

The two records of one issue have their own appId and carry no field that links
them. They are linked here by ISIN and date, and only when that is
unambiguous (`link_status` says what happened and the report counts each
outcome); a listing record whose link is not certain gets no promoter flag and
no lock-in date rather than a guessed one.

Field meanings that were checked against the stored rows (09 Oct 2026):
`boardResDate` / `boardResolutionDt` equal the NSE posting date (`systemDate` /
`sysDateTime`) on every sampled row, so they are NOT the board's meeting date;
that is `dateBrdResoln` (preferential) and `dateOfBrdResIssueApproving`
(rights), filled on In-Principle records only.

BSE's rights and preferential rows carry only the company, scrip code and the
two stage dates (no amount, price, allottee or stage), so they add nothing to
these tables and are not used.

Lock-in (SEBI ICDR, preferential allotments): promoters 18 months, others 6
months, counted from the trading-approval date.
"""
from __future__ import annotations

from datetime import timedelta

import pandas as pd

from insiders_clean.dates import parse_dates

LINK_WINDOW_DAYS = 180   # an In-Principle record counts for a listing record filed within this long after it
LOCK_IN_MONTHS = {'PROMOTER': 18, 'NON_PROMOTER': 6}

# canonical column -> clean name, per kind, per stage. Only columns seen in the stored data.
PREF_FIELDS = {
    'in_principle': {'dateBrdResoln': 'board_date', 'canonical_allottee_category': 'allottee_category',
                     'considerationBy': 'consideration', 'totalAmtRaised': 'amount_total'},
    'listing': {'offerPricePerSecurity': 'offer_price', 'totalNumOfSharesAllotted': 'shares_allotted',
                'numberOfEquitySharesListed': 'shares_listed', 'dateOfAllotmentOfShares': 'allotment_date',
                'dateOfListing': 'listing_date', 'dateOfTradingApproval': 'trading_approval_date',
                'amountRaised': 'amount_raised'},
}
RIGHTS_FIELDS = {
    'in_principle': {'dateOfBrdResIssueApproving': 'board_date', 'considerationBy': 'consideration',
                     'totalAmntRaised': 'amount_total'},
    'listing': {'offerPrice': 'offer_price', 'rightRatio': 'ratio', 'recordDate': 'record_date',
                'issueOpenDate': 'issue_open_date', 'issueCloseDate': 'issue_close_date',
                'noOfSharesAlloted': 'shares_allotted', 'noOfSharesListed': 'shares_listed',
                'dtOfAllotmentsOfShares': 'allotment_date', 'dateOfListing': 'listing_date',
                'dateOfTradingApp': 'trading_approval_date', 'amntRaised': 'amount_raised'},
}
NUMERIC = ('offer_price', 'shares_allotted', 'shares_listed', 'amount_raised', 'amount_total')
DATES = ('board_date', 'allotment_date', 'listing_date', 'trading_approval_date', 'record_date',
         'issue_open_date', 'issue_close_date')
STAGE = {'In-Principle': 'in_principle', 'Listing Stage': 'listing'}
AMOUNT_CEILING = 1e13   # rupees; anything above is a unit error, as in scripts/r2_writer.py


def _text(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series([None] * len(df), index=df.index, dtype='object')
    s = df[col].astype('string').str.strip()
    return s.mask(s.isin(['', 'None', 'nan', '<NA>']))


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype('string').str.replace(',', '', regex=False), errors='coerce')


def normalise(raw: pd.DataFrame, kind: str) -> pd.DataFrame:
    """Canonical NSE rows (any number of daily snapshots stacked) -> one tidy
    row per stage record, newest snapshot winning."""
    fields = PREF_FIELDS if kind == 'preferential' else RIGHTS_FIELDS
    if raw is None or raw.empty:
        return pd.DataFrame()
    df = raw.copy()
    df['_stage'] = _text(df, 'canonical_stage').map(STAGE)
    df = df[df['_stage'].notna()]
    out = pd.DataFrame(index=df.index)
    out['event_id'] = _text(df, 'canonical_event_id')
    out['app_id'] = _text(df, 'appId')
    out['stage'] = df['_stage']
    out['isin'] = _text(df, 'canonical_isin')
    out['symbol'] = _text(df, 'canonical_symbol')
    out['company'] = _text(df, 'canonical_company')
    posted = 'systemDate' if kind == 'preferential' else 'sysDateTime'
    out['posted_on'] = _text(df, posted)
    out['submitted_on'] = _text(df, 'dateOfSubmission' if kind == 'preferential' else 'dtOfSubmission')
    out.loc[out['stage'] == 'in_principle', 'submitted_on'] = _text(df, 'dateOfSubmission')
    out['xbrl_url'] = _text(df, 'xmlFileName')
    out['snapshot'] = _text(df, 'ingested_at')
    for stage, mapping in fields.items():
        sel = df['_stage'] == stage
        for src, dst in mapping.items():
            if dst not in out.columns:
                out[dst] = pd.Series([None] * len(out), index=out.index, dtype='object')
            out.loc[sel, dst] = _text(df.loc[sel], src)
    for c in DATES + ('posted_on', 'submitted_on'):
        if c in out.columns:
            out[c] = parse_dates(out[c])
    for c in NUMERIC:
        if c in out.columns:
            out[c] = _num(out[c])
    if 'amount_total' in out.columns:
        out['amount_unreliable'] = out['amount_total'].notna() & ~out['amount_total'].between(1, AMOUNT_CEILING)
        out.loc[out['amount_unreliable'], 'amount_total'] = None
    # one row per record: the newest snapshot of (stage, appId)
    out['_key'] = out['app_id'].fillna(out['event_id'])
    out = (out.sort_values('snapshot').drop_duplicates(['stage', '_key'], keep='last')
              .drop(columns=['snapshot', '_key']).reset_index(drop=True))
    return out


def link_stages(df: pd.DataFrame, window_days: int = LINK_WINDOW_DAYS) -> pd.DataFrame:
    """Adds `link_status` to listing records and, when exactly one In-Principle
    record of the same ISIN was filed in the `window_days` before it, that
    record's id, board date, amount and (preferential) allottee category."""
    if df.empty:
        return df
    df = df.copy()
    for c in ('linked_app_id', 'link_status'):
        df[c] = None
    ip = df[df['stage'] == 'in_principle']
    carry = [c for c in ('board_date', 'amount_total', 'allottee_category', 'consideration') if c in df.columns]
    for i in df.index[df['stage'] == 'listing']:
        row = df.loc[i]
        if not isinstance(row['isin'], str) or row['posted_on'] is None:
            df.at[i, 'link_status'] = 'no_isin_or_date'
            continue
        cand = ip[(ip['isin'] == row['isin']) & ip['posted_on'].notna()]
        start = row['posted_on'] - timedelta(days=window_days)
        cand = cand[(cand['posted_on'] <= row['posted_on']) & (cand['posted_on'] >= start)]
        if len(cand) == 1:
            df.at[i, 'link_status'] = 'linked'
            df.at[i, 'linked_app_id'] = cand['app_id'].iloc[0]
            for c in carry:
                df.at[i, c] = cand[c].iloc[0]
        else:
            df.at[i, 'link_status'] = 'ambiguous' if len(cand) > 1 else 'no_in_principle_in_data'
    return df


def add_lock_in(df: pd.DataFrame) -> pd.DataFrame:
    """Preferential only: lock-in expiry from the trading-approval date. A
    mixed allotment gets both dates (the split between promoter and others
    is not in the data); a record with no certain allottee category or no
    trading-approval date gets none."""
    df = df.copy()
    for c in ('lock_in_promoter_until', 'lock_in_other_until'):
        df[c] = None
    if df.empty or 'allottee_category' not in df.columns:
        return df
    ok = (df['stage'] == 'listing') & (df['link_status'] == 'linked') & df['trading_approval_date'].notna()
    for i in df.index[ok]:
        base = pd.Timestamp(df.at[i, 'trading_approval_date'])
        cat = df.at[i, 'allottee_category']
        if cat in ('PROMOTER', 'MIXED'):
            df.at[i, 'lock_in_promoter_until'] = (base + pd.DateOffset(months=LOCK_IN_MONTHS['PROMOTER'])).date()
        if cat in ('NON_PROMOTER', 'MIXED'):
            df.at[i, 'lock_in_other_until'] = (base + pd.DateOffset(months=LOCK_IN_MONTHS['NON_PROMOTER'])).date()
    return df


def clean_issues(raw: pd.DataFrame, kind: str) -> tuple[pd.DataFrame, dict]:
    """(clean table, report) for kind 'preferential' or 'rights'."""
    n_in = 0 if raw is None else len(raw)
    df = normalise(raw, kind)
    report = {'input_rows': n_in, 'records': len(df)}
    if df.empty:
        return df, report
    df = link_stages(df)
    if kind == 'preferential':
        df = add_lock_in(df)
    lst = df[df['stage'] == 'listing']
    report.update(
        in_principle=int((df['stage'] == 'in_principle').sum()), listing=len(lst),
        link_status={k: int(v) for k, v in lst['link_status'].value_counts().items()},
        amount_unreliable=int(df.get('amount_unreliable', pd.Series(dtype=bool)).sum()),
        no_isin=int(df['isin'].isna().sum()))
    return df, report
