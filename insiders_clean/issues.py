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

Filings by date window (from 12 Oct 2026). The nightly NSE events job
(`collectors/nse_events`, stream `issues`) also asks NSE for every filing
posted in a date window (no 100 cap) and archives one row per filing with
NSE's row (`raw_json`) and, for preferential filings and QIP allotments, the
parsed XBRL (`xbrl_json`). Those rows are stacked with the snapshots, so an
approval older than the latest-100 list can still be linked, and the XBRL adds
what the list lacks: the ICDR minimum price and relevant date as filed, the
instruments, every proposed allottee, and the lock-in lines the company filed.
QIPs (`clean_qip`) come only from these filings.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from datetime import date, timedelta

import pandas as pd

from insiders_clean.dates import parse_dates
from insiders_clean.entities import entity_display, entity_key
from insiders_clean.pipeline import PRODUCT_START

LINK_WINDOW_DAYS = 180   # an In-Principle record counts for a listing record filed within this long after it
LOCK_IN_MONTHS = {'PROMOTER': 18, 'NON_PROMOTER': 6}
# In-principle XBRL fields (add_xbrl) a matched listing record takes over.
LINK_CARRY_XBRL = ('instruments', 'securities_proposed', 'icdr_min_price', 'relevant_date')

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
                'dtOfAllotmentsOfShare': 'allotment_date', 'dateOfListing': 'listing_date',
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
    carry = [c for c in ('board_date', 'amount_total', 'allottee_category', 'consideration') + LINK_CARRY_XBRL
             if c in df.columns]
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
            for c in carry:   # the approval's value, never a blank over the record's own
                v = cand[c].iloc[0]
                if v is not None and not pd.isna(v):
                    df.at[i, c] = v
        else:
            df.at[i, 'link_status'] = 'ambiguous' if len(cand) > 1 else 'no_in_principle_in_data'
    return df


def check_links(df: pd.DataFrame) -> pd.DataFrame:
    """Preferential: a matched approval whose XBRL proposed fewer securities
    than this record allotted is not this allotment's approval (e.g. Kanpur
    Plastipack 452,000 shares allotted at Rs 130 against a share-swap approval
    of 333,700 at Rs 202.61). The link is dropped (link_status
    'more_shares_than_approved') and nothing is carried."""
    if 'securities_proposed' not in df.columns:
        return df
    df = df.copy()
    allotted = pd.to_numeric(df['shares_allotted'], errors='coerce')
    proposed = pd.to_numeric(df['securities_proposed'], errors='coerce')
    bad = (df['stage'] == 'listing') & (df['link_status'] == 'linked') & proposed.gt(0) & allotted.gt(proposed)
    df.loc[bad, 'link_status'] = 'more_shares_than_approved'
    for c in ('linked_app_id', 'board_date', 'amount_total', 'allottee_category', 'consideration') + LINK_CARRY_XBRL:
        if c in df.columns:
            df[c] = df[c].astype(object)
            df.loc[bad, c] = None
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


def clean_issues(raw: pd.DataFrame, kind: str, filings: pd.DataFrame | None = None,
                 daily: pd.DataFrame | None = None, split_dates: dict | None = None) -> tuple[pd.DataFrame, dict]:
    """(clean table, report) for kind 'preferential' or 'rights'. `raw` is the
    stacked canonical snapshots; `filings` the archived window filings (all
    kinds, optional); `daily` the price rows our ICDR estimate reads and
    `split_dates` ISIN -> split/bonus dates (both optional)."""
    window = as_canonical(filings, kind)
    frames = [f for f in (raw, window) if f is not None and not f.empty]
    n_in = 0 if raw is None else len(raw)
    df = normalise(pd.concat(frames, ignore_index=True) if frames else None, kind)
    report = {'input_rows': n_in, 'records': len(df)}
    if filings is not None:
        report['window_filings'] = len(window)
    if df.empty:
        return df, report
    if kind == 'preferential':
        df = add_xbrl(df, xbrl_facts(filings), filings)
    df = link_stages(df)
    if kind == 'preferential':
        df = add_lock_in(check_links(df))
        df = add_icdr_estimate(df, daily, split_dates)
        df['vs_icdr_min'] = _pct_vs(df['offer_price'], df['icdr_min_price'])
    # Kept, not cut at the product window: an allotment from before it still has lock-ins running into it.
    old = pd.to_datetime(df['posted_on'], errors='coerce') < pd.Timestamp(PRODUCT_START)
    lst = df[df['stage'] == 'listing']
    report.update(
        in_principle=int((df['stage'] == 'in_principle').sum()), listing=len(lst),
        link_status={k: int(v) for k, v in lst['link_status'].value_counts().items()},
        amount_unreliable=int(df.get('amount_unreliable', pd.Series(dtype=bool)).sum()),
        no_isin=int(df['isin'].isna().sum()), posted_before_product_start=int(old.sum()))
    if kind == 'preferential':
        report['xbrl_status'] = {k: int(v) for k, v in df['xbrl_status'].fillna('not_collected').astype(str)
                                 .str.split(':').str[0].value_counts().items()}
        report['icdr_min_filed'] = int(df['icdr_min_price'].notna().sum())
        report['icdr_min_ours'] = int(df['icdr_min_ours'].notna().sum())
        report['icdr_ours_missing'] = {k: int(v) for k, v in df['icdr_ours_note'].value_counts().items()}
    return df, report


# --- filings by date window: archive rows, XBRL facts ---------------------------------------

KINDS = ('preferential', 'rights', 'qip')
STAGE_LABEL = {v: k for k, v in STAGE.items()}
POSTED_FIELD = {'preferential': 'systemDate', 'rights': 'sysDateTime', 'qip': 'boardResolutionDate'}
FILING_COLUMNS = ['event_id', 'kind', 'stage', 'app_id', 'symbol', 'isin', 'company', 'posted_on', 'xbrl_url',
                  'xbrl_status', 'xbrl_json', 'raw_json']
# Filings whose XBRL adds what the list lacks (rights in-principle adds only the security type: not fetched).
XBRL_WANTED = {('preferential', 'in_principle'), ('preferential', 'listing'), ('qip', 'listing')}
ALLOTTEE_CODE = {'Promoter': 'PROMOTER', 'Non Promoter': 'NON_PROMOTER', 'Promoter & Non Promoter': 'MIXED'}


def _clean_text(v) -> str | None:
    if v is None or (isinstance(v, float) and pd.isna(v)) or v is pd.NA:
        return None
    s = re.sub(r'\s+', ' ', str(v)).strip()
    return s if s and s.lower() not in ('none', 'null', 'nan', '<na>', '-', 'na', 'nil') else None


def _one_num(v) -> float | None:
    s = _clean_text(v)
    try:
        return float(s.replace(',', '')) if s else None
    except ValueError:
        return None


def _one_date(v) -> date | None:
    s = _clean_text(v)
    return parse_dates(pd.Series([s])).iloc[0] if s else None


def filing_rows(kind: str, stage: str, rows: list[dict]) -> pd.DataFrame:
    """NSE's window list rows for one kind and stage -> archive rows, one per
    filing (appId). NSE's whole row is kept in raw_json."""
    out = []
    for r in rows or []:
        app = _clean_text(r.get('appId'))
        if app is None:
            continue
        company = _clean_text(r.get('nameOfTheCompany') or r.get('companyName'))
        posted = _one_date(r.get(POSTED_FIELD[kind]))
        out.append({
            'event_id': f'{kind}:{stage}:{app}', 'kind': kind, 'stage': stage, 'app_id': app,
            'symbol': (_clean_text(r.get('nseSymbol') or r.get('nsesymbol')) or '').upper() or None,
            'isin': _clean_text(r.get('isin')),
            # NSE's rights listing rows have carried a BSE scrip code as the name (scripts/r2_writer.py)
            'company': None if company and company.isdigit() else company,
            'posted_on': posted.isoformat() if posted else None,
            'xbrl_url': _clean_text(r.get('xmlFileName')), 'xbrl_status': None, 'xbrl_json': None,
            'raw_json': json.dumps(r, ensure_ascii=False, sort_keys=True, default=str)})
    return pd.DataFrame(out, columns=FILING_COLUMNS)


def parse_xbrl(xml) -> dict:
    """Facts of one further-issue XBRL (SEBI's in-capmkt taxonomy as NSE files
    it): {'main': {tag: value}, 'groups': {name: {tag: value}}}. MainI/MainD
    facts describe the filing; the rest come in numbered groups
    (IssuedSecurity1, Allottees3, Option2 ...), the D_/I_ prefix dropped.
    Raises ValueError when the file holds no facts."""
    if isinstance(xml, bytes):
        xml = xml.decode('utf-8', errors='replace')
    root = ET.fromstring(re.sub(r'^\s*<\?xml[^>]*\?>', '', xml))
    main, groups = {}, {}
    for el in root:
        ctx = el.get('contextRef')
        value = _clean_text(''.join(el.itertext()))
        if ctx is None or value is None:
            continue
        tag = el.tag.split('}')[-1]
        if ctx in ('MainI', 'MainD'):
            main[tag] = value
        else:
            groups.setdefault(re.sub(r'^[DI]_', '', ctx), {})[tag] = value
    if not main and not groups:
        raise ValueError('no facts in further-issue XBRL')
    return {'main': main, 'groups': groups}


def groups_of(facts: dict | None, prefix: str) -> list[dict]:
    """Groups named prefix1, prefix2 ... in number order."""
    found = []
    for name, vals in ((facts or {}).get('groups') or {}).items():
        m = re.fullmatch(rf'{prefix}(\d+)', name, re.IGNORECASE)
        if m:
            found.append((int(m.group(1)), vals))
    return [v for _, v in sorted(found, key=lambda x: x[0])]


def xbrl_facts(filings: pd.DataFrame | None) -> dict:
    """(kind, stage, app_id) -> parsed XBRL facts, for filings parsed 'ok'."""
    if filings is None or filings.empty or 'xbrl_json' not in filings.columns:
        return {}
    ok = filings[filings['xbrl_status'].astype('string').eq('ok').fillna(False) & filings['xbrl_json'].notna()]
    out = {}
    for _, r in ok.iterrows():
        try:
            out[(r['kind'], r['stage'], str(r['app_id']))] = json.loads(r['xbrl_json'])
        except (TypeError, ValueError):
            continue
    return out


def as_canonical(filings: pd.DataFrame | None, kind: str) -> pd.DataFrame:
    """Archived window filings of one kind in the shape normalise() reads (the
    canonical snapshot columns), so both sources are cleaned the same way."""
    if filings is None or filings.empty:
        return pd.DataFrame()
    rows = []
    for _, f in filings[filings['kind'] == kind].iterrows():
        try:
            r = json.loads(f['raw_json'])
        except (TypeError, ValueError):
            continue
        rows.append({**{k: None if v is None else str(v) for k, v in r.items()},
                     'canonical_event_id': f['event_id'], 'canonical_stage': STAGE_LABEL[f['stage']],
                     'canonical_isin': f['isin'], 'canonical_symbol': f['symbol'], 'canonical_company': f['company'],
                     'canonical_allottee_category': ALLOTTEE_CODE.get(_clean_text(r.get('categoryOfAllottee')) or ''),
                     'ingested_at': str(f.get('last_seen') or '')})
    return pd.DataFrame(rows)


def _xbrl_status(df: pd.DataFrame, filings: pd.DataFrame | None, kind: str) -> pd.Series:
    if filings is None or filings.empty:
        return pd.Series([None] * len(df), index=df.index, dtype='object')
    f = filings[filings['kind'] == kind]
    status = {(s, str(a)): _clean_text(v) for s, a, v in zip(f['stage'], f['app_id'], f['xbrl_status'])}
    return pd.Series([status.get((s, str(a))) for s, a in zip(df['stage'], df['app_id'])], index=df.index, dtype='object')


def _single(values):
    vals = {v for v in values if v is not None}
    return vals.pop() if len(vals) == 1 else None


def add_xbrl(df: pd.DataFrame, facts: dict, filings: pd.DataFrame | None = None) -> pd.DataFrame:
    """Preferential: from the in-principle XBRL the instruments, the number of
    securities proposed, and the ICDR minimum price and relevant date as filed
    (only when every instrument of the issue states the same one; otherwise
    blank, never picked); from the listing XBRL whether lock-in lines were filed."""
    df = df.copy()
    for c in LINK_CARRY_XBRL + ('lock_in_filed',):
        df[c] = None
    df['xbrl_status'] = _xbrl_status(df, filings, 'preferential')
    for i, r in df.iterrows():
        x = facts.get(('preferential', r['stage'], str(r['app_id'])))
        if x is None:
            continue
        if r['stage'] == 'listing':
            df.at[i, 'lock_in_filed'] = bool(groups_of(x, 'Option'))
            continue
        secs = groups_of(x, 'IssuedSecurity')
        types = [t for t in (_clean_text(s.get('SecurityType')) for s in secs) if t]
        df.at[i, 'instruments'] = '; '.join(dict.fromkeys(types)) or None
        n = [_one_num(s.get('NumberOfSecurities')) for s in secs]
        df.at[i, 'securities_proposed'] = sum(n) if n and None not in n else None
        price = _single(_one_num(s.get('MinimumIssuePricePerUnit')) for s in secs)
        df.at[i, 'icdr_min_price'] = price if price and price > 0 else None
        df.at[i, 'relevant_date'] = _single(_one_date(s.get('RecordDateOrFutureRelevantDate')) for s in secs)
    df['securities_proposed'] = pd.to_numeric(df['securities_proposed'], errors='coerce')
    df['icdr_min_price'] = pd.to_numeric(df['icdr_min_price'], errors='coerce')
    return df


def _pct_vs(a, b) -> pd.Series:
    a, b = pd.to_numeric(a, errors='coerce'), pd.to_numeric(b, errors='coerce')
    return ((a / b - 1) * 100).where(a.gt(0) & b.gt(0))


# --- ICDR minimum: our own estimate from the bhavcopy -------------------------------------

ICDR_LONG, ICDR_SHORT = 90, 10   # trading days before the relevant date (SEBI ICDR Reg 164(1))


def icdr_floor_estimate(daily: pd.DataFrame | None, isin, relevant, split_dates=()) -> tuple:
    """(price, exchange), or (None, reason): the higher of the 90- and the
    10-trading-day volume-weighted average price before the relevant date, on
    the exchange with more volume over those 90 days, from our NSE/BSE
    bhavcopy (traded value / volume, all series of the ISIN). None when that
    exchange has fewer than 90 sessions with trades before the date, or a
    split or bonus falls inside the window (our daily prices are as printed)."""
    if daily is None or daily.empty or not isinstance(isin, str) or relevant is None:
        return None, 'no_prices'
    d = daily[(daily['isin'] == isin) & (daily['date'] < pd.Timestamp(relevant))]
    d = d[d['volume'].gt(0) & d['value'].gt(0)]
    if d.empty:
        return None, 'no_prices'
    day = d.groupby(['exchange', 'date'], as_index=False)[['volume', 'value']].sum().sort_values('date')
    best, best_vol = None, -1.0
    for ex, g in day.groupby('exchange'):
        g = g.tail(ICDR_LONG)
        if len(g) == ICDR_LONG and g['volume'].sum() > best_vol:
            best, best_vol = (ex, g), g['volume'].sum()
    if best is None:
        return None, 'under_90_sessions'
    ex, g = best
    start = g['date'].iloc[0]
    if any(start < pd.Timestamp(s) < pd.Timestamp(relevant) for s in split_dates or ()):
        return None, 'split_or_bonus_in_window'
    short = g.tail(ICDR_SHORT)
    vwap = max(g['value'].sum() / g['volume'].sum(), short['value'].sum() / short['volume'].sum())
    return round(vwap, 2), ex


def add_icdr_estimate(df: pd.DataFrame, daily: pd.DataFrame | None, split_dates: dict | None = None) -> pd.DataFrame:
    """icdr_min_ours and the exchange it is from, on every record with a filed
    relevant date; icdr_ours_note says why there is none."""
    df = df.copy()
    df['icdr_min_ours'], df['icdr_ours_exchange'], df['icdr_ours_note'] = None, None, None
    if 'relevant_date' in df.columns:
        for i in df.index[df['relevant_date'].notna()]:
            price, ex = icdr_floor_estimate(daily, df.at[i, 'isin'], df.at[i, 'relevant_date'],
                                            (split_dates or {}).get(df.at[i, 'isin'], ()))
            col = 'icdr_ours_note' if price is None else 'icdr_ours_exchange'
            df.at[i, col] = ex
            df.at[i, 'icdr_min_ours'] = price
    df['icdr_min_ours'] = pd.to_numeric(df['icdr_min_ours'], errors='coerce')
    return df


def price_months(filings: pd.DataFrame | None) -> list[str]:
    """'YYYY-MM' months of daily prices the ICDR estimate needs for the
    relevant dates in the preferential in-principle XBRLs (90 sessions fit in
    the five months before a date)."""
    days = set()
    for (kind, stage, _), x in xbrl_facts(filings).items():
        if (kind, stage) == ('preferential', 'in_principle'):
            days.update(d for d in (_one_date(s.get('RecordDateOrFutureRelevantDate'))
                                    for s in groups_of(x, 'IssuedSecurity')) if d)
    out = set()
    for d in days:
        t = pd.Timestamp(d)
        out.update(pd.period_range(t - pd.DateOffset(months=5), t, freq='M').strftime('%Y-%m'))
    return sorted(out)


# --- proposed allottees and filed lock-ins (preferential) ----------------------------------

ALLOTTEE_COLUMNS = ['app_id', 'isin', 'symbol', 'company', 'posted_on', 'board_date', 'allottee', 'allottee_id',
                    'security_type', 'securities', 'issue_category', 'promoter']
LOCKIN_COLUMNS = ['app_id', 'isin', 'symbol', 'company', 'allotment_date', 'trading_approval_date', 'basis',
                  'period_filed', 'months', 'who', 'shares', 'expires']
_PERIOD = re.compile(r'(\d+(?:\.\d+)?)\s*(month|year)s?', re.IGNORECASE)


def allottee_rows(df: pd.DataFrame, facts: dict) -> pd.DataFrame:
    """One row per proposed allottee in each preferential in-principle XBRL.
    The XBRL gives no promoter status per allottee, so `promoter` is the
    issue's: True for a promoter issue, False for a non-promoter one, blank
    for a mixed one."""
    out = []
    ip = df[df['stage'] == 'in_principle'] if not df.empty else df
    for _, r in ip.iterrows():
        cat = r.get('allottee_category')
        for g in groups_of(facts.get(('preferential', 'in_principle', str(r['app_id']))), 'Allottees'):
            name = _clean_text(g.get('NameOfAllottees'))
            if name is None:
                continue
            out.append({'app_id': r['app_id'], 'isin': r['isin'], 'symbol': r['symbol'], 'company': r['company'],
                        'posted_on': r['posted_on'], 'board_date': r.get('board_date'),
                        'allottee': entity_display(name), 'allottee_id': entity_key(name),
                        'security_type': _clean_text(g.get('AllottedSecurityType')),
                        'securities': _one_num(g.get('NumberOfSharesAllotted')), 'issue_category': cat,
                        'promoter': {'PROMOTER': True, 'NON_PROMOTER': False}.get(cat)})
    return pd.DataFrame(out, columns=ALLOTTEE_COLUMNS)


def lock_in_months(text) -> float | None:
    """Months in a filed lock-in period ('Equity shares for 18 months', '1
    year'); None when it states none (a day count can't become a date here)."""
    m = _PERIOD.search(str(text or ''))
    if not m:
        return None
    return float(m.group(1)) * (12 if m.group(2).lower() == 'year' else 1)


def lock_in_lines(df: pd.DataFrame, facts: dict) -> pd.DataFrame:
    """Lock-in lines per allotment: those the company filed in the listing XBRL
    (period and shares as filed, expiry counted from the trading-approval
    date), or, when none were filed, the rule dates of add_lock_in (promoters
    18 months, others 6; shares only when the issue has one category)."""
    out = []
    ls = df[df['stage'] == 'listing'] if not df.empty else df
    for _, r in ls.iterrows():
        tad = r.get('trading_approval_date')
        base = {'app_id': r['app_id'], 'isin': r['isin'], 'symbol': r['symbol'], 'company': r['company'],
                'allotment_date': r.get('allotment_date'), 'trading_approval_date': tad}
        filed = [(_clean_text(g.get('PeriodOfLockInShares')), _one_num(g.get('NumberOfLockInShares')))
                 for g in groups_of(facts.get(('preferential', 'listing', str(r['app_id']))), 'Option')]
        filed = [(t, n) for t, n in filed if t is not None or n is not None]
        for text, n in filed:
            months = lock_in_months(text)
            whole = months is not None and float(months).is_integer()
            expires = (pd.Timestamp(tad) + pd.DateOffset(months=int(months))).date() if whole and tad else None
            out.append({**base, 'basis': 'filed', 'period_filed': text, 'months': months, 'who': None,
                        'shares': n, 'expires': expires})
        if filed:
            continue
        one_cat = r.get('allottee_category') in ('PROMOTER', 'NON_PROMOTER')
        for col, who, months in (('lock_in_promoter_until', 'Promoters', LOCK_IN_MONTHS['PROMOTER']),
                                 ('lock_in_other_until', 'Others', LOCK_IN_MONTHS['NON_PROMOTER'])):
            if col in r and r[col] is not None and not pd.isna(r[col]):
                out.append({**base, 'basis': 'rule', 'period_filed': None, 'months': float(months), 'who': who,
                            'shares': r.get('shares_allotted') if one_cat else None, 'expires': r[col]})
    lines = pd.DataFrame(out, columns=LOCKIN_COLUMNS)
    for c in ('shares', 'months'):
        lines[c] = pd.to_numeric(lines[c], errors='coerce')
    return lines


def with_lock_in_basis(df: pd.DataFrame, lines: pd.DataFrame) -> pd.DataFrame:
    """lock_in_basis on listing records: 'filed', 'rule' or blank."""
    df = df.copy()
    basis = lines.groupby('app_id')['basis'].first() if not lines.empty else pd.Series(dtype=object)
    df['lock_in_basis'] = df['app_id'].map(basis).where(df['stage'] == 'listing')
    return df


# --- QIPs (only from the window filings) ---------------------------------------------------

QIP_FIELDS = {
    'in_principle': {'dateBrdResol': 'board_date', 'dateOfSHApp': 'shareholder_approval_date',
                     'totalAmtOfIssueSize': 'amount_total', 'listedAt': 'listed_at',
                     'prcntagePerSecrtyProDiscNotice': 'discount_in_notice_filed'},
    'listing': {'dtOfBIDOpening': 'bid_open_date', 'dtOfBIDClosing': 'bid_close_date', 'relavantDt': 'relevant_date',
                'minIssPricePerUnit': 'floor_price', 'issPricePerUnit': 'issue_price',
                'distPerShrsAvailed': 'discount_per_share', 'dtOfAllotmentOfShares': 'allotment_date',
                'noOfSharesAllotted': 'shares_allotted', 'noOfAllottees': 'allottees',
                'noOfEquitySharesListed': 'shares_listed', 'finalAmountOfIssueSize': 'amount_raised',
                'dateOfListing': 'listing_date', 'dateOfTradingApproval': 'trading_approval_date'},
}
QIP_NUMERIC = ('amount_total', 'floor_price', 'issue_price', 'discount_per_share', 'shares_allotted', 'allottees',
               'shares_listed', 'amount_raised')
QIP_DATES = ('board_date', 'shareholder_approval_date', 'bid_open_date', 'bid_close_date', 'relevant_date',
             'allotment_date', 'listing_date', 'trading_approval_date')
QIP_ALLOTTEE_COLUMNS = ['app_id', 'isin', 'symbol', 'company', 'posted_on', 'allotment_date', 'allottee', 'allottee_id',
                        'category', 'shares', 'pct_of_issue']
AMOUNT_TOLERANCE = 2.0   # a filed amount more than 2x away from shares x price is not shown


def clean_qip(filings: pd.DataFrame | None) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """(QIP records, QIP allottees, report). One row per filing, both stages;
    listing records linked to their approval as preferential ones are. The
    listing XBRL names the allottees (name, shares, % of the issue, category)."""
    f = filings[filings['kind'] == 'qip'] if filings is not None and not filings.empty else pd.DataFrame()
    report = {'filings': len(f)}
    if f.empty:
        return pd.DataFrame(), pd.DataFrame(columns=QIP_ALLOTTEE_COLUMNS), report
    rows = []
    for _, x in f.iterrows():
        try:
            r = json.loads(x['raw_json'])
        except (TypeError, ValueError):
            continue
        row = {'event_id': x['event_id'], 'app_id': str(x['app_id']), 'stage': x['stage'], 'isin': x['isin'],
               'symbol': x['symbol'], 'company': x['company'], 'posted_on': x['posted_on'],
               'submitted_on': r.get('dateOfSubmission'), 'xbrl_url': x['xbrl_url'],
               'xbrl_status': _clean_text(x.get('xbrl_status'))}
        for stage, mapping in QIP_FIELDS.items():
            for src, dst in mapping.items():
                row[dst] = _clean_text(r.get(src)) if stage == x['stage'] else None
        rows.append(row)
    df = pd.DataFrame(rows)
    for c in QIP_DATES + ('posted_on', 'submitted_on'):
        df[c] = parse_dates(df[c])
    for c in QIP_NUMERIC:
        df[c] = _num(df[c])
    implied = df['shares_allotted'] * df['issue_price']
    ratio = df['amount_raised'] / implied
    bad_total = df['amount_total'].notna() & ~df['amount_total'].between(1, AMOUNT_CEILING)
    bad_raised = df['amount_raised'].notna() & (~df['amount_raised'].between(1, AMOUNT_CEILING)
                                                | (implied.gt(0) & ~ratio.between(1 / AMOUNT_TOLERANCE, AMOUNT_TOLERANCE)))
    df['amount_unreliable'] = bad_total | bad_raised
    df.loc[bad_total, 'amount_total'] = None
    df.loc[bad_raised, 'amount_raised'] = None
    df['issue_vs_floor'] = _pct_vs(df['issue_price'], df['floor_price'])
    df = link_stages(df)
    old = pd.to_datetime(df['posted_on'], errors='coerce') < pd.Timestamp(PRODUCT_START)   # counted, kept
    facts = xbrl_facts(f)
    allot = []
    for _, r in df[df['stage'] == 'listing'].iterrows():
        for g in groups_of(facts.get(('qip', 'listing', r['app_id'])), 'Allottees'):
            name = _clean_text(g.get('NameOfAllottees'))
            if name is None:
                continue
            share = _one_num(g.get('PercentageOfTotalIssueSize'))
            allot.append({'app_id': r['app_id'], 'isin': r['isin'], 'symbol': r['symbol'], 'company': r['company'],
                          'posted_on': r['posted_on'], 'allotment_date': r['allotment_date'],
                          'allottee': entity_display(name), 'allottee_id': entity_key(name),
                          'category': _clean_text(g.get('CategoryOfAllotees')),
                          'shares': _one_num(g.get('NumberOfSharesAllotted')),
                          'pct_of_issue': None if share is None else round(share * 100, 4)})  # filed as a fraction
    allottees = pd.DataFrame(allot, columns=QIP_ALLOTTEE_COLUMNS)
    lst = df[df['stage'] == 'listing']
    report.update(records=len(df), in_principle=int((df['stage'] == 'in_principle').sum()), listing=len(lst),
                  link_status={k: int(v) for k, v in lst['link_status'].value_counts().items()},
                  amount_unreliable=int(df['amount_unreliable'].sum()), posted_before_product_start=int(old.sum()),
                  allottee_rows=len(allottees), listings_with_allottees=int(allottees['app_id'].nunique()))
    return df, allottees, report
