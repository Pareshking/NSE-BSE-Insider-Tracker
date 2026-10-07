"""Insider trading filings (SEBI PIT) -> the clean `insider_trades` table.

One row per filing that survives cleaning. Rows are removed only for being
a copy of another row (a repeat filing, or an original that a revision
replaced); everything else is kept and labelled, so nothing disappears
without a reason in the cleaning report.

What a row gains:
* `kind` / `is_market` from the mode of acquisition. Only open-market
  trades are decisions to buy or sell; ESOP, gifts, inter-se transfers,
  pledges, schemes, conversions, offers for sale and allotments are filed
  the same way but say nothing about conviction. Signals use market trades
  only. A mode this module doesn't recognise becomes kind 'unrecognised',
  is never treated as market, and is listed in the report.
* `person_role` from the person category.
* One security (ISIN, display name, both exchange identifiers).
* Own-holding change, % of market cap, and the two Reg 7(2) deadlines.
* `flags`: reasons to hold a row back from rankings until checked.
* NSE/BSE copies of one filing: both kept, linked; NSE is primary (it
  carries the intimation date), BSE gets is_primary = False.
"""
from __future__ import annotations

import hashlib
import re

import numpy as np
import pandas as pd

from .calendar import Calendar, lateness
from .dates import parse_dates, to_datetime_day_first
from .entities import add_entity_columns, most_common
from .missing import is_missing, present
from .securities import SecurityMaster, display_name

# Below this many shares held before the trade, a % change in the person's
# own holding is not shown: a small base turns an ordinary buy into a
# four-digit percentage.
HOLDING_BASE_MIN = 25_000
# A trade worth more than this share of the company's market cap is held
# back for a look (an IPO offer for sale, a scheme, or a typo in the value).
VALUE_SHARE_OF_MCAP_REVIEW = 0.25
# A market trade that multiplies the person's holding by more than this is
# almost never an open-market buy; held back until the filing is checked.
HOLDING_MULTIPLE_REVIEW = 20

# Mode of acquisition -> kind. First match wins, so the more specific
# phrases ('off market', 'pledge invo...') come before broader ones.
_MODE_RULES = [
    (r'off[\s-]*market', 'off_market'),
    (r'invo[ck]', 'pledge_invoke'),
    (r'revo[ck]|release', 'pledge_revoke'),
    (r'pledge|encumb', 'pledge_create'),
    (r'esop|esos|employee|stock option|sweat', 'esop'),
    (r'gift', 'gift'),
    (r'inter[\s-]*se', 'inter_se'),
    (r'scheme|amalgamat|merger|demerger|arrangement', 'scheme'),
    (r'conver|warrant', 'conversion'),
    (r'offer for sale|\bofs\b', 'offer_for_sale'),
    (r'preferential', 'preferential'),
    (r'right', 'rights'),
    (r'bonus', 'bonus'),
    (r'buy[\s-]*back', 'buyback'),
    (r'transmission|inherit|succession', 'transmission'),
    (r'allot', 'allotment'),
    (r'market\s*(purchase|sale|sell|buy)|open market|on[\s-]*market|market', 'market'),
    (r'^others?$|^any other', 'other'),
]
_ROLE_RULES = [
    (r'promoter\s*group', 'promoter_group'),
    (r'promoter', 'promoter'),
    (r'director', 'director'),
    (r'key\s*managerial|\bkmp\b', 'kmp'),
    (r'designated', 'designated_person'),
    (r'immediate\s*relative|relative', 'immediate_relative'),
    (r'employee', 'employee'),
    (r'other', 'other'),
]


# What filers write when a field is empty.
_BLANK = {'', '-', '--', 'na', 'n.a.', 'nil', 'none', 'null'}


def classify_mode(mode) -> str:
    s = '' if is_missing(mode) else str(mode).strip().lower()
    if s in _BLANK:
        return 'missing'
    for pat, kind in _MODE_RULES:
        if re.search(pat, s):
            return kind
    return 'unrecognised'


def classify_role(category) -> str:
    s = '' if is_missing(category) else str(category).lower()
    if s.strip() in _BLANK:
        return 'missing'
    for pat, role in _ROLE_RULES:
        if re.search(pat, s):
            return role
    return 'other'


def _side_word(text) -> str | None:
    t = '' if is_missing(text) else str(text or '').upper()
    if re.search(r'PLEDGE|REVOK|INVOC|INVOK', t) and not re.search(r'BUY|SELL|PURCHASE|SALE', t):
        return None
    if re.search(r'BUY|ACQUI|PURCHASE', t):
        return 'BUY'
    if re.search(r'SELL|DISPOS|SALE', t):
        return 'SELL'
    return None


def side_of(transaction_type, mode) -> str | None:
    """The transaction type decides; the mode is only a fallback. Real
    filings contradict themselves (HCL Tech, appId 2894: mode 'Market
    Purchase', type 'Disposal', holding 37,894 -> 37,104 -- a sale)."""
    return _side_word(transaction_type) or _side_word(mode)


# NSE cuts names in its XBRL at about 30 characters, and not always at the
# same place: "Vama Sundari Investments (Delh" and "Vama Sundari
# \nInvestments (De" are one promoter of HCL Tech.
TRUNCATION_MIN_KEY = 15


def _merge_truncated_names(df: pd.DataFrame) -> pd.DataFrame:
    """Within one security, a person ID that is a prefix of exactly one
    longer ID there is the same person, cut short. Only within a security
    and only on a unique match, so two different people never merge."""
    df = df.copy()
    sec = df['isin'].fillna(df['symbol'].astype(str))
    for _, grp in df[df['person_id'].notna()].groupby(sec):
        ids = sorted(set(grp['person_id']), key=len, reverse=True)
        remap = {}
        for short in ids:
            if len(short) < TRUNCATION_MIN_KEY:
                continue
            longer = [i for i in ids if len(i) > len(short) and i.startswith(short) and i not in remap]
            if len(longer) == 1:
                remap[short] = longer[0]
        if remap:
            idx = grp.index[grp['person_id'].isin(list(remap))]
            df.loc[idx, 'person_id'] = df.loc[idx, 'person_id'].map(remap)
    # Longest spelling per person; on equal length the first seen.
    named = df[['person_id', 'person_name']].dropna()
    names = (named.assign(_len=named['person_name'].str.len(), _pos=np.arange(len(named)))
             .sort_values(['_len', '_pos'], ascending=[False, True])
             .drop_duplicates('person_id').set_index('person_id')['person_name'])
    df['person_name'] = df['person_id'].map(names)
    return df


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype('string').str.replace(',', '', regex=False), errors='coerce')


def _col(df: pd.DataFrame, *names) -> pd.Series:
    """First present column (canonical first, then native), aligned to df."""
    out = pd.Series([None] * len(df), index=df.index, dtype=object)
    for n in names:
        if n in df.columns:
            out = out.where(out.notna() & (out.astype(str) != ''), df[n])
    return out.where(out.astype(str).str.strip() != '', None)


def _row_id(parts) -> str:
    return hashlib.sha1('|'.join('' if p is None else str(p) for p in parts).encode()).hexdigest()[:16]


def _fill_missing_roles(df: pd.DataFrame, report) -> pd.DataFrame:
    """About 19% of NSE filings (May 2025 - Apr 2026) carry '-' as the
    person category, 1,319 of them market trades. When the same person files
    for the same security with a category elsewhere, that role is used and
    `person_role_source` says so; otherwise the role stays 'missing' and the
    row never counts as a promoter or director trade."""
    df = df.copy()
    df['person_role_source'] = np.where(df['person_role'].eq('missing'), 'missing', 'filing')
    known = df[~df['person_role'].isin(['missing'])].dropna(subset=['person_id'])
    sec = known['isin'].fillna(known['symbol'].astype(str))
    lookup = most_common(pd.DataFrame({'sec': sec, 'person_id': known['person_id'],
                                       'role': known['person_role']}), ['sec', 'person_id'], 'role').to_dict()
    miss = df['person_role'].eq('missing') & df['person_id'].notna()
    keys = list(zip(df.loc[miss, 'isin'].fillna(df.loc[miss, 'symbol'].astype(str)), df.loc[miss, 'person_id']))
    filled = pd.Series([lookup.get(k) for k in keys], index=df.index[miss])
    hit = filled.notna()
    df.loc[filled.index[hit], 'person_role'] = filled[hit]
    df.loc[filled.index[hit], 'person_role_source'] = 'same_person_other_filing'
    t = report.table('insider_trades')
    t['roles_filled_from_other_filings'] = t.get('roles_filled_from_other_filings', 0) + int(hit.sum())
    t['roles_still_missing'] = int(df['person_role'].eq('missing').sum())
    return df


# Columns that are bookkeeping, not part of what the exchange filed.
_NOT_NATIVE = re.compile(r'^(canonical_|cross_exchange_|ingested_at$|first_seen$|last_seen$|exchange$|category$)')
BREAKDOWN_COMPARISONS = 3000


def _removal_breakdown(raw: pd.DataFrame, df: pd.DataFrame, order: pd.DataFrame, dup: pd.Series,
                       key_cols: list[str]) -> dict:
    """Why rows were removed as copies: per exchange, whether the copy has
    the same exchange filing ID as the row kept (one filing captured more
    than once) or a different one (re-filed), and which filed fields differ
    between them. Written to the cleaning report so a high removal count can
    be checked without opening the data."""
    removed = order[dup]
    out = {'removed': len(removed), 'by_exchange': removed['exchange'].value_counts().to_dict(),
           'same_filing_id': 0, 'different_filing_id': 0, 'no_filing_id': 0, 'differing_fields': {},
           'examples': []}
    if removed.empty:
        return out
    kept_idx = order.groupby(key_cols, dropna=False, sort=False).head(1)
    kept_by_key = {tuple(r): i for i, r in zip(kept_idx.index, kept_idx[key_cols].astype(str).itertuples(index=False))}
    native = [c for c in raw.columns if not _NOT_NATIVE.match(str(c))]
    fields = {}
    for n, (i, r) in enumerate(removed.iterrows()):
        k = kept_by_key.get(tuple(r[key_cols].astype(str)))
        if k is None:
            continue
        a, b = df.at[i, 'app_id'], df.at[k, 'app_id']
        if pd.isna(a) or pd.isna(b) or not str(a).strip():
            out['no_filing_id'] += 1
        elif str(a) == str(b):
            out['same_filing_id'] += 1
        else:
            out['different_filing_id'] += 1
        if n < BREAKDOWN_COMPARISONS:
            differ = [c for c in native if str(raw.at[i, c]) != str(raw.at[k, c])]
            for c in differ:
                fields[c] = fields.get(c, 0) + 1
            if len(out['examples']) < 8:
                out['examples'].append({'exchange': r['exchange'], 'kept': str(df.at[k, 'source_id']),
                                        'removed': str(df.at[i, 'source_id']), 'fields_that_differ': differ[:12]})
    out['differing_fields'] = dict(sorted(fields.items(), key=lambda x: -x[1])[:20])
    return out


def clean_insider(raw: pd.DataFrame, master: SecurityMaster, cal: Calendar, report, run_date) -> pd.DataFrame:
    """canonical insider rows (both exchanges, native columns included,
    an `exchange` column) -> clean insider_trades."""
    t = report.table('insider_trades')
    if raw is None or raw.empty:
        return pd.DataFrame()
    t['input_rows'] += len(raw)
    df = pd.DataFrame(index=raw.index)
    df['source_id'] = _col(raw, 'canonical_event_id')
    df['exchange'] = raw['exchange'].astype(str).str.lower()
    df['app_id'] = _col(raw, 'canonical_app_id', 'appId').astype('string')
    df['prev_app_id'] = _col(raw, 'canonical_prev_app_id', 'prevAppId').astype('string')
    df['symbol'] = _col(raw, 'canonical_symbol', 'symbol', 'security_code')
    df['company_raw'] = _col(raw, 'canonical_company', 'companyName', 'company')
    df['person_raw'] = _col(raw, 'canonical_person', 'acqName', 'person')
    df['person_category_raw'] = _col(raw, 'canonical_person_category', 'personCategory', 'person_category')
    df['mode_raw'] = _col(raw, 'canonical_mode', 'modeOfAcquisition', 'mode')
    df['transaction_type_raw'] = _col(raw, 'canonical_transaction_type', 'transactionType', 'transaction_type')
    df['quantity'] = _num(_col(raw, 'canonical_quantity'))
    df['value'] = _num(_col(raw, 'canonical_value'))
    df['holding_before'] = _num(_col(raw, 'canonical_holding_before'))
    df['holding_after'] = _num(_col(raw, 'canonical_holding_after'))
    df['trade_date_from'] = parse_dates(_col(raw, 'canonical_transaction_date_from', 'acqfromDt'))
    df['trade_date_to'] = parse_dates(_col(raw, 'canonical_transaction_date_to', 'acqtoDt',
                                           'canonical_transaction_date'))
    # NSE carries the date the insider told the company; BSE's capture
    # doesn't, so the two deadlines can't be split for BSE rows.
    df['intimation_date'] = parse_dates(_col(raw, 'intimDt'))
    broadcast_raw = _col(raw, 'canonical_broadcast_date', 'broadcastDt')
    df['broadcast_date'] = parse_dates(broadcast_raw)
    df['broadcast_ts'] = to_datetime_day_first(broadcast_raw)
    df['app_num'] = pd.to_numeric(df['app_id'], errors='coerce')

    # --- classification ---
    df['kind'] = df['mode_raw'].map(classify_mode)
    df['is_market'] = df['kind'].eq('market')
    df['side'] = [side_of(tt, m) for tt, m in zip(df['transaction_type_raw'], df['mode_raw'])]
    df['person_role'] = df['person_category_raw'].map(classify_role)
    report.unrecognised('mode_of_acquisition', df.loc[df['kind'].eq('unrecognised'), 'mode_raw'].astype(str))
    df = add_entity_columns(df, 'person_raw', prefix='person')

    # --- security ---
    # Re-resolved against today's exchange lists; the writer's ISIN (from
    # the 01 Sep export alone) is only a last resort.
    resolved = [master.resolve(ex, sym) for ex, sym in zip(df['exchange'], df['symbol'])]
    writer_isin = _col(raw, 'canonical_isin')
    df['isin'] = [r[0] or (w if present(w) else None) for r, w in zip(resolved, writer_isin)]
    df['security_match'] = [r[1] if r[0] or not present(w) else 'writer_isin' for r, w in zip(resolved, writer_isin)]
    recs = {i: master.record(i) for i in df['isin'].dropna().unique()}
    df['company'] = [(recs.get(i) or {}).get('display_name') or display_name(c)
                     for i, c in zip(df['isin'], df['company_raw'])]
    df['nse_symbol'] = df['isin'].map(lambda i: (recs.get(i) or {}).get('nse_symbol'))
    df['bse_code'] = df['isin'].map(lambda i: (recs.get(i) or {}).get('bse_code'))
    df['market_cap'] = pd.to_numeric(df['isin'].map(lambda i: (recs.get(i) or {}).get('market_cap')), errors='coerce')
    report.unmatched(df.loc[df['isin'].isna(), ['exchange', 'symbol', 'company_raw']]
                     .rename(columns={'company_raw': 'name'}).astype(str).drop_duplicates()
                     .assign(table='insider_trades').to_dict('records'))

    # --- measures ---
    df['price'] = (df['value'] / df['quantity']).where(df['quantity'] > 0)
    df['holding_change_pct'] = ((df['holding_after'] - df['holding_before']) / df['holding_before'] * 100
                                ).where(df['holding_before'] >= HOLDING_BASE_MIN)
    df['pct_of_mcap'] = (df['value'] / df['market_cap'] * 100).where(df['market_cap'] > 0)
    sign = df['side'].map({'BUY': 1, 'SELL': -1})
    df['signed_value'] = df['value'] * sign

    # --- deadlines (Reg 7(2)(a) and (b)), in trading sessions ---
    a = [lateness(cal, s, e) for s, e in zip(df['trade_date_to'], df['intimation_date'])]
    b = [lateness(cal, s, e) for s, e in zip(df['intimation_date'], df['broadcast_date'])]
    tot = [cal.sessions_after(s, e) for s, e in zip(df['trade_date_to'], df['broadcast_date'])]
    df['insider_to_company_sessions'] = pd.array([x[0] for x in a], dtype='Int64')
    df['insider_filed_late'] = pd.array([x[1] for x in a], dtype='boolean')
    df['company_to_exchange_sessions'] = pd.array([x[0] for x in b], dtype='Int64')
    df['company_filed_late'] = pd.array([x[1] for x in b], dtype='boolean')
    df['trade_to_public_sessions'] = pd.array(tot, dtype='Int64')

    # --- removals: a filing replaced by a later one ---
    # NSE's prevAppId would mark revisions, but real corrections arrive
    # without it (HCL Tech appId 3119 re-files 3082 with 'Market Purchase'
    # corrected to 'Market Sale'; prevAppId empty on both). So a revision is
    # recognised by content: same person, security, side, quantity, value,
    # trade dates and holdings before and after -- the holdings make two
    # genuine trades with all of these equal practically impossible. The
    # latest broadcast is kept. If the mode changed it was a correction,
    # otherwise a repeat (Prakash Steelage appIds 3136 and 3138, identical).
    df = _merge_truncated_names(df)
    df = _fill_missing_roles(df, report)
    keep = pd.Series(True, index=df.index)
    known_app = set(df['app_id'].dropna())
    superseded = df['app_id'].isin(set(df['prev_app_id'].dropna()) & known_app)
    report.removed('insider_trades', 'superseded_by_revision', df.loc[superseded, 'source_id'])
    keep &= ~superseded
    key_cols = ['exchange', 'isin', 'symbol', 'person_id', 'side', 'quantity', 'value',
                'trade_date_from', 'trade_date_to', 'holding_before', 'holding_after']
    order = (df[keep].assign(_b=df['broadcast_ts'])
             .sort_values(['_b', 'app_num'], ascending=False, na_position='last'))
    latest_mode = order.groupby(key_cols, dropna=False)['mode_raw'].transform('first')
    dup = order.duplicated(subset=key_cols, keep='first')
    corrected = dup & (order['mode_raw'].astype(str) != latest_mode.astype(str))
    report.removed('insider_trades', 'corrected_refiling', order.loc[corrected, 'source_id'])
    report.removed('insider_trades', 'repeat_filing', order.loc[dup & ~corrected, 'source_id'])
    report.table('insider_trades')['removal_breakdown'] = _removal_breakdown(raw, df, order, dup, key_cols)
    keep.loc[dup[dup].index] = False
    df = df[keep].copy()

    # --- flags: kept, but held back from rankings until checked ---
    flags = [[] for _ in range(len(df))]

    def flag(mask, name):
        for i in np.flatnonzero(np.asarray(mask.fillna(False), dtype=bool)):
            flags[i].append(name)

    flag(df['isin'].isna(), 'unmatched_security')
    flag(df['kind'].isin(['unrecognised', 'missing']), 'unrecognised_mode')
    flag(df['pct_of_mcap'] > VALUE_SHARE_OF_MCAP_REVIEW * 100, 'value_over_25pct_of_mcap')
    multiple = df['holding_after'] / df['holding_before'].where(df['holding_before'] > 0)
    flag(df['is_market'] & (multiple > HOLDING_MULTIPLE_REVIEW), 'holding_jump_on_market_trade')
    moved = (df['holding_after'] - df['holding_before']).abs()
    # Only for rows that move shares: a pledge leaves the holding unchanged
    # by design (569 of the first 775 hits on a year of real filings).
    flag(df['side'].notna() & ~df['kind'].str.startswith('pledge')
         & ((moved - df['quantity']).abs() > np.maximum(1, df['quantity'] * 0.01)),
         'holding_change_differs_from_quantity')
    # Gifts, ESOP grants and transmissions are legitimately filed at zero.
    flag(df['is_market'] & (df['quantity'] > 0) & ~(df['value'] > 0), 'missing_or_zero_value')
    mode_side = df['mode_raw'].map(_side_word)
    flag(df['is_market'] & mode_side.notna() & df['side'].notna() & (mode_side != df['side']),
         'mode_contradicts_side')
    to, frm = pd.to_datetime(df['trade_date_to']), pd.to_datetime(df['trade_date_from'])
    intim, bcast = pd.to_datetime(df['intimation_date']), pd.to_datetime(df['broadcast_date'])
    flag((frm > to) | (to > intim) | (intim > bcast) | (to > bcast), 'dates_out_of_order')
    flag(to > pd.Timestamp(run_date), 'trade_date_in_future')
    df['flags'] = [','.join(f) for f in flags]
    df['needs_review'] = df['flags'] != ''
    report.flagged('insider_trades', flags)

    # --- NSE/BSE copies of one filing ---
    df['trade_id'] = [_row_id(p) for p in zip(df['exchange'], df['source_id'])]
    link = ['isin', 'person_id', 'quantity', 'trade_date_to']
    df['is_primary'] = True
    df['primary_id'] = None
    df['listed_on'] = df['exchange']
    linkable = df.dropna(subset=['isin', 'person_id', 'quantity', 'trade_date_to'])
    # Only groups on both exchanges can link; filtering first avoids one
    # pandas frame per row on a full history.
    linkable = linkable[linkable.groupby(link)['exchange'].transform('nunique') > 1]
    for _, grp in linkable.groupby(link):
        if grp['exchange'].nunique() < 2:
            continue
        nse = grp[grp['exchange'] == 'nse']
        primary = nse.index[0] if len(nse) else grp.index[0]
        others = grp.index.drop(primary)
        df.loc[others, 'is_primary'] = False
        df.loc[others, 'primary_id'] = df.at[primary, 'trade_id']
        df.loc[grp.index, 'listed_on'] = ','.join(sorted(grp['exchange'].unique()))

    cols = ['trade_id', 'source_id', 'exchange', 'listed_on', 'is_primary', 'primary_id', 'app_id',
            'isin', 'security_match', 'company', 'nse_symbol', 'bse_code', 'symbol',
            'person_id', 'person_name', 'person_role', 'person_role_source', 'person_category_raw',
            'side', 'kind', 'is_market', 'mode_raw', 'transaction_type_raw',
            'quantity', 'value', 'signed_value', 'price', 'holding_before', 'holding_after',
            'holding_change_pct', 'market_cap', 'pct_of_mcap',
            'trade_date_from', 'trade_date_to', 'intimation_date', 'broadcast_date',
            'insider_to_company_sessions', 'insider_filed_late',
            'company_to_exchange_sessions', 'company_filed_late', 'trade_to_public_sessions',
            'flags', 'needs_review']
    out = df[cols].reset_index(drop=True)
    t['output_rows'] += len(out)
    t['by_exchange'] = out['exchange'].value_counts().to_dict()
    return out
