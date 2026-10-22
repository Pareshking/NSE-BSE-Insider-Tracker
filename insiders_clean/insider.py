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
* Own-holding change, % of market cap (at the trade's last day), and the
  two Reg 7(2) deadlines.
* `flags`: reasons to hold a row back from rankings until checked;
  `marks`: data checks that are counted and shown but hold nothing back
  (docs/CLEAN_LAYER.md, "Data checks").
* Holding-only disclosures (no shares traded) become kind 'holding_only'.
* NSE/BSE copies of one filing: both kept, linked; NSE is primary (it
  carries the intimation date), BSE gets is_primary = False. A copy agrees
  on person, security, side, kind, shares and trade dates; one BSE row per
  NSE row (`_pair_copies`).
"""
from __future__ import annotations

import hashlib
import re

import numpy as np
import pandas as pd

from . import day_range, market_cap
from .calendar import Calendar, lateness
from .dates import parse_dates, to_datetime_day_first
from .entities import add_entity_columns, most_common
from .history import BSE_INSIDER_SOURCE
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
    # A block or bulk deal is a trade on the exchange: BSE files the block-window sales NSE files as 'Market
    # Sale' (Stylam, Bajaj Finserv, Thyrocare 2183, audit 22 Oct), so the two copies must read alike.
    (r'block\s*deal|bulk\s*deal', 'market'),
    (r'market\s*(purchase|sale|sell|buy)|open market|on[\s-]*market|market', 'market'),
    (r'^others?$|^any other', 'other'),
]
_ROLE_RULES = [
    # A relative is filed under the insider's own word ("Directors Immediate Relative"), so the relative rules
    # come first: a director's relative is no director (audit 22 Oct: Mkventures Capital's "director" cluster of
    # 23 Sep 2026 was three relatives and an HUF). A promoter's immediate relative is promoter group by SEBI's
    # definition (ICDR Reg 2(1)(pp)(ii)).
    (r'promoters?\W*(immediate\s*)?relative', 'promoter_group'),
    (r'immediate\s*relative|relative', 'immediate_relative'),
    (r'promoter\s*group', 'promoter_group'),
    (r'promoter', 'promoter'),
    (r'director', 'director'),
    (r'key\s*managerial|\bkmp\b', 'kmp'),
    (r'designated', 'designated_person'),
    (r'immediate\s*relative|relative', 'immediate_relative'),
    (r'employee', 'employee'),
    (r'other', 'other'),
]
# The transaction type says pledge, release or invocation where the mode is blank (NSE 'PLEDGE REVOKE' 111 rows,
# BSE 'REVOKE' 60, audit 22 Oct): the kind is taken from it. First match wins.
_TYPE_KIND_RULES = [(r'invo[ck]', 'pledge_invoke'), (r'revo[ck]|releas', 'pledge_revoke'), (r'pledge|encumb', 'pledge_create')]


def kind_from_type(transaction_type) -> str | None:
    """A pledge kind from the filed transaction type, or None."""
    s = '' if is_missing(transaction_type) else str(transaction_type).strip().lower()
    for pat, kind in _TYPE_KIND_RULES:
        if re.search(pat, s):
            return kind
    return None


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
# A name cut at a word boundary is only taken as cut when its raw spelling is
# about as long as NSE's cut (the two Vama Sundari spellings are 30 and 29
# characters). "Ramesh Kumar Agarwal" (20) is a whole name, not a cut one.
TRUNCATION_RAW_LEN = (26, 32)
# Words that, added after a whole name, make another legal person: an
# individual's HUF or trust, or a company named after him (audit W5).
_OTHER_PERSON_WORDS = {'huf', 'trust', 'family', 'foundation', 'estate', 'minor'}
_CORPORATE_WORDS = {'private', 'limited', 'llp', 'company', 'corporation', 'holding', 'holdings', 'investment',
                    'investments', 'ventures', 'enterprises', 'capital', 'fund', 'industries', 'associates',
                    'partners', 'finance', 'securities', 'international', 'inc'}


def _is_truncation(short: str, long: str, raw_len: int) -> bool:
    """`long` starts with `short`; is `short` the same name cut short? Cut
    mid-word: yes. Cut at a word boundary: only when the raw spelling is as
    long as NSE's cut, and the added words never turn the person into
    another one (an HUF, a trust, or a company when `short` is no company)."""
    if long[len(short)] != '-':
        return True
    if not TRUNCATION_RAW_LEN[0] <= raw_len <= TRUNCATION_RAW_LEN[1]:
        return False
    added = set(long[len(short) + 1:].split('-'))
    if added & _OTHER_PERSON_WORDS:
        return False
    return not (added & _CORPORATE_WORDS) or bool(set(short.split('-')) & _CORPORATE_WORDS)


def _merge_truncated_names(df: pd.DataFrame) -> pd.DataFrame:
    """Within one security, a person ID that is a prefix of exactly one
    longer ID there is the same person, cut short (`_is_truncation`). Only
    within a security and only on a unique match, so two different people
    never merge; never "X" into "X HUF"."""
    df = df.copy()
    sec = df['isin'].fillna(df['symbol'].astype(str))
    raw = df['person_raw'] if 'person_raw' in df else df['person_name']
    raw_len = (pd.DataFrame({'id': df['person_id'], 'n': raw.astype('string').str.strip().str.len()})
               .dropna().groupby('id')['n'].max().to_dict())
    for _, grp in df[df['person_id'].notna()].groupby(sec):
        ids = sorted(set(grp['person_id']), key=len, reverse=True)
        remap = {}
        for short in ids:
            if len(short) < TRUNCATION_MIN_KEY:
                continue
            longer = [i for i in ids if len(i) > len(short) and i.startswith(short) and i not in remap]
            if len(longer) == 1 and _is_truncation(short, longer[0], int(raw_len.get(short, 0))):
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


def holding_check(df: pd.DataFrame) -> pd.Series:
    """Holding after - holding before against the shares traded, per row:
    `match`, `differs` (size off by more than 1% or 1 share), `against_side`
    (right size, wrong direction: a buy that lowers the holding),
    `against_side_and_differs`, `not_filed` (a holding or the quantity
    missing), `not_applicable` (no side, or a pledge: a pledge leaves the
    holding unchanged by design, 569 of the first 775 mismatches on a year of
    real filings)."""
    out = pd.Series('not_applicable', index=df.index, dtype=object)
    moves = _true(df['side'].notna() & ~df['kind'].str.startswith('pledge'))
    sign = df['side'].map({'BUY': 1, 'SELL': -1}).astype('Float64')
    moved = (df['holding_after'] - df['holding_before']).astype('Float64')
    qty = df['quantity'].astype('Float64')
    filed = _true(moved.notna() & (qty > 0))
    size_ok = _true((moved.abs() - qty).abs() <= (qty * 0.01).clip(lower=1))
    against = _true((moved * sign) < 0)
    out[moves & ~filed] = 'not_filed'
    m = moves & filed
    out[m & size_ok & ~against] = 'match'
    out[m & ~size_ok & ~against] = 'differs'
    out[m & size_ok & against] = 'against_side'
    out[m & ~size_ok & against] = 'against_side_and_differs'
    return out


def _true(mask) -> np.ndarray:
    """A comparison on nullable numbers -> plain bools, missing = False."""
    return np.asarray(pd.Series(mask).fillna(False), dtype=bool)


def _counts(s: pd.Series) -> dict:
    return {str(k): int(v) for k, v in s.value_counts().items()}


def _present(v) -> bool:
    return v is not None and not (isinstance(v, float) and np.isnan(v)) and not pd.isna(v)


def _dates_agree(n_from, n_to, b_from, b_to, b_nightly: bool) -> bool:
    """Do an NSE row's trade dates and a BSE row's say the same trade? BSE's
    nightly capture files one date (the from-date, as the to-date too), so
    such a row agrees when that date lies in the NSE row's span (audit W4);
    a row with its own to-date (BSE's insider CSV) agrees on the last day of
    the trade, as the link always has."""
    n_to = n_to if _present(n_to) else n_from
    n_from = n_from if _present(n_from) else n_to
    if not _present(n_to):
        return False
    if b_nightly or not _present(b_to):
        d = b_from if _present(b_from) else b_to
        return _present(d) and n_from <= d <= n_to
    return n_to == b_to


COPY_KEY = ['isin', 'person_id', '_side', 'kind', 'quantity']


def _pair_copies(nse: pd.DataFrame, bse: pd.DataFrame) -> list[tuple]:
    """(nse index, bse index) for each BSE row that is a copy of an NSE row:
    same security, person, side, kind and shares, and trade dates that agree
    (`_dates_agree`). One BSE row per NSE row, in date order; a row left over
    on either side is a trade of its own (audit W3: a buy and a sale of the
    same size on one day are two trades)."""
    pairs = []
    if nse.empty or bse.empty:
        return pairs
    n = nse.dropna(subset=['isin', 'person_id', 'quantity']).assign(_side=lambda d: d['side'].fillna('-'))
    b = bse.dropna(subset=['isin', 'person_id', 'quantity']).assign(_side=lambda d: d['side'].fillna('-'))
    b_groups = {k: g for k, g in b.groupby(COPY_KEY, sort=False)}
    for k, g in n.groupby(COPY_KEY, sort=False):
        cand = b_groups.get(k)
        if cand is None:
            continue
        cand = cand.sort_values(['trade_date_from', 'broadcast_ts'], na_position='last')
        nightly = (~cand['_bse_csv']).to_numpy() if '_bse_csv' in cand else np.ones(len(cand), dtype=bool)
        used = set()
        for i, nf, nt in zip(g.index, g['trade_date_from'], g['trade_date_to']):
            for j, bf, bt, night in zip(cand.index, cand['trade_date_from'], cand['trade_date_to'], nightly):
                if j not in used and _dates_agree(nf, nt, bf, bt, bool(night)):
                    pairs.append((i, j))
                    used.add(j)
                    break
    return pairs


def _pledge_quantity_from_bse(df: pd.DataFrame) -> int:
    """NSE's nightly rows carry no quantity for a pledge (its mapper keeps one only for a buy or a sale),
    so they never pair with their BSE copy and the pledge is counted on both exchanges. An NSE pledge row
    without shares takes them from the BSE row of the same security, person and kind whose trade dates
    agree (`_dates_agree`), one BSE row each; the pairing that follows then links the two. BSE's nightly
    feed files some pledges with neither a mode nor a transaction type (kind 'missing'): such a row, with no
    side and the holding unchanged as a pledge leaves it, is the copy too and takes the NSE row's kind
    (Thyrocare, Docon Technologies' release of 7,94,69,696 shares on 17 Aug 2026, NSE appId 2325: the BSE
    copy stood as a Rs 4,916 Cr trade of no kind, audit 22 Oct). Returns how many were filled (in the run
    report)."""
    pledge = df['kind'].astype(str).str.startswith('pledge')
    nan = pd.Series(np.nan, index=df.index)
    hb, ha = (pd.to_numeric(df[c], errors='coerce') if c in df else nan for c in ('holding_before', 'holding_after'))
    side = df['side'] if 'side' in df else nan
    blank = df['kind'].eq('missing') & side.isna() & _true(hb.notna() & (hb == ha))
    n = df[pledge & df['exchange'].eq('nse') & df['quantity'].isna()].dropna(subset=['isin', 'person_id'])
    b = df[(pledge | blank) & df['exchange'].eq('bse') & df['quantity'].notna()].dropna(subset=['isin', 'person_id'])
    if n.empty or b.empty:
        return 0
    groups = {k: g for k, g in b.groupby(['isin', 'person_id'], sort=False)}
    used, filled = set(), 0
    for i, r in n.iterrows():
        cand = groups.get((r['isin'], r['person_id']))
        if cand is None:
            continue
        cand = cand[cand['kind'].isin([r['kind'], 'missing'])]
        # A BSE row of the NSE row's own kind first, a blank one after.
        for j, c in sorted(cand.iterrows(), key=lambda x: x[1]['kind'] == 'missing'):
            if j not in used and _dates_agree(r['trade_date_from'], r['trade_date_to'], c['trade_date_from'],
                                              c['trade_date_to'], not bool(c.get('_bse_csv', False))):
                df.at[i, 'quantity'] = c['quantity']
                if c['kind'] == 'missing':
                    df.at[j, 'kind'] = r['kind']
                used.add(j)
                filled += 1
                break
    return filled


def _refiled_with_other_holdings(order: pd.DataFrame, key_cols: list[str]) -> pd.Index:
    """Rows of `order` (latest first) that repeat a later row but for the holdings (see the caller)."""
    key = [c for c in key_cols if c not in ('holding_before', 'holding_after')]
    sized = order[_true(order['quantity'] > 0) & _true(order['value'] > 0)].dropna(subset=['person_id'])
    many = sized[sized.duplicated(subset=key, keep=False)]
    out = []
    for _, g in many.groupby(key, dropna=False, sort=False):
        before, after = set(g['holding_before'].dropna()), set(g['holding_after'].dropna())
        if before & after:
            continue   # tranches: one row starts where another ended
        out.extend(g.index[1:])
    return pd.Index(out)


GROUP_TRANSFER_PRICE_GAP = 0.02


def _promoter_group_transfers(df: pd.DataFrame) -> pd.Series:
    """Market trades that move shares inside the promoter group: on one exchange, a promoter or promoter-group
    filer's market buy and another's market sale of the same company, on the same trade dates, of the same
    number of shares at prices within 2%, paired one to one. The group holds what it held: no decision to buy
    or sell, so they are read as an inter-se transfer (kind 'inter_se', never market), marked
    `promoter_group_transfer`. P&G Hygiene, 19 Jun 2026: P&G Home Products bought 6,19,683 shares from Temple
    Trees Impex at Rs 8,995.50; Bajaj Finserv, 27 Apr 2026: Bajaj Holdings & Investment bought 20,90,050 from
    Bajaj Auto Holdings in the block window (audit 22 Oct: 41 such pairs, Rs 1,745 Cr, both sides shown)."""
    out = pd.Series(False, index=df.index)
    m = df[df['kind'].eq('market') & df['person_role'].isin(['promoter', 'promoter_group']) & df['side'].isin(['BUY', 'SELL'])
           & _true(df['quantity'] > 0)].dropna(subset=['isin', 'person_id', 'trade_date_to'])
    if m.empty:
        return out
    frm = m['trade_date_from'].where(m['trade_date_from'].notna(), m['trade_date_to'])
    m = m.assign(gt_from=frm, gt_px=(m['value'] / m['quantity']))
    for _, g in m.groupby(['exchange', 'isin', 'gt_from', 'trade_date_to', 'quantity'], sort=False):
        if g['side'].nunique() < 2:
            continue
        sells = list(g[g['side'].eq('SELL')].itertuples())
        for b in g[g['side'].eq('BUY')].itertuples():
            for k, s_ in enumerate(sells):
                close = (pd.notna(b.gt_px) and pd.notna(s_.gt_px) and s_.gt_px > 0
                         and abs(b.gt_px - s_.gt_px) <= GROUP_TRANSFER_PRICE_GAP * s_.gt_px)
                if s_.person_id != b.person_id and close:
                    out.loc[[b.Index, s_.Index]] = True
                    sells.pop(k)
                    break
    return out


def _revision_marked(d: pd.DataFrame) -> pd.Series:
    """NSE rows of a filing NSE lists as a 'Revision' that carry no prevAppId we can follow."""
    st = d['nse_submission_type'].astype('string').str.strip().str.lower().fillna('')
    # A prevAppId that names no filing we hold says no more than a blank one: NSE's list numbers filings
    # apart from its prevAppId (Info Edge's revision 3962 of 08 Oct 2026 points at 47977; its original is 2427).
    known = set(d['app_id'].dropna()) - {''}
    return d['exchange'].eq('nse') & st.str.startswith('revis') & (d['prev_app_id'].isna() | ~d['prev_app_id'].isin(known))


def _superseded_by_marker(d: pd.DataFrame) -> tuple[pd.Index, dict]:
    """Rows replaced by a later NSE filing marked 'Revision' without
    prevAppId (audit W10). For each such filing and each person, security,
    trade dates and kind in it: the earlier NSE filings (other appId,
    broadcast before it) with rows of the same person, security, dates and
    kind are the candidates; those with a row of the same side are preferred.
    Exactly one candidate filing: its rows there are replaced. Several: none
    is removed (counted `ambiguous`). None: nothing to replace (the original
    is older than the archive, or its kind was corrected; counted)."""
    out = {'revision_rows': 0, 'replaced_rows': 0, 'ambiguous': 0, 'no_original': 0}
    rev = _revision_marked(d)
    out['revision_rows'] = int(rev.sum())
    if not rev.any():
        return pd.Index([]), out
    key = ['isin', 'person_id', '_from', 'trade_date_to', 'kind']
    nse = d[d['exchange'].eq('nse')].dropna(subset=['isin', 'person_id', 'trade_date_to']).copy()
    nse['_from'] = nse['trade_date_from'].where(nse['trade_date_from'].notna(), nse['trade_date_to'])
    nse = nse[nse['broadcast_ts'].notna()]
    by_key = {k: g for k, g in nse.groupby(key, sort=False)}
    removed: set = set()
    revs = nse[_revision_marked(nse)].sort_values('broadcast_ts')
    for (app, k), g in revs.groupby([revs['app_id'].fillna(''), revs[key].apply(tuple, axis=1)], sort=False):
        at = g['broadcast_ts'].max()
        pool = by_key.get(k)
        pool = pool[(pool['app_id'].fillna('') != app) & (pool['broadcast_ts'] < at) & ~pool.index.isin(list(removed))]
        if pool.empty:
            out['no_original'] += len(g)
            continue
        sides = set(g['side'].dropna())
        same = pool[pool['side'].isin(sides)] if sides else pool
        apps = (same if len(same) else pool)['app_id'].fillna('').unique()
        if len(apps) != 1:
            out['ambiguous'] += len(g)
            continue
        hit = pool.index[pool['app_id'].fillna('') == apps[0]]
        removed.update(hit)
        out['replaced_rows'] += len(hit)
    return pd.Index(sorted(removed)), out


def clean_insider(raw: pd.DataFrame, master: SecurityMaster, cal: Calendar, report, run_date,
                  price_ranges: pd.DataFrame | None = None,
                  market_cap_daily: pd.DataFrame | None = None) -> pd.DataFrame:
    """canonical insider rows (both exchanges, native columns included,
    an `exchange` column) -> clean insider_trades. `price_ranges`
    (insiders_clean.day_range.load) feeds the price check; without it the
    check is reported as not run and nothing is flagged for price.
    `market_cap_daily` (insiders_clean.market_cap.load_daily) dates the
    market cap behind `pct_of_mcap`; without it every row takes the latest."""
    t = report.table('insider_trades')
    if raw is None or raw.empty:
        return pd.DataFrame()
    t['input_rows'] += len(raw)
    df = pd.DataFrame(index=raw.index)
    df['source_id'] = _col(raw, 'canonical_event_id')
    df['exchange'] = raw['exchange'].astype(str).str.lower()
    df['app_id'] = _col(raw, 'canonical_app_id', 'appId').astype('string')
    df['prev_app_id'] = _col(raw, 'canonical_prev_app_id', 'prevAppId').astype('string')
    df['prev_app_id'] = df['prev_app_id'].where(df['prev_app_id'].str.strip().fillna('') != '', pd.NA)  # blank = not a revision
    df['nse_submission_type'] = _col(raw, 'canonical_submission_type', 'typeOfSubmission').astype('string')
    df['nse_revision_remark'] = _col(raw, 'canonical_revision_remark', 'revisionRemark').astype('string')
    df['symbol'] = _col(raw, 'canonical_symbol', 'symbol', 'security_code')
    df['company_raw'] = _col(raw, 'canonical_company', 'companyName', 'company')
    df['person_raw'] = _col(raw, 'canonical_person', 'acqName', 'person')
    df['person_category_raw'] = _col(raw, 'canonical_person_category', 'personCategory', 'person_category')
    df['mode_raw'] = _col(raw, 'canonical_mode', 'modeOfAcquisition', 'mode')
    df['security_type_raw'] = _col(raw, 'secType', 'security_type')
    df['transaction_type_raw'] = _col(raw, 'canonical_transaction_type', 'transactionType', 'transaction_type')
    df['source_url'] = _col(raw, 'canonical_source_url', 'xmlFileName').astype('string')   # NSE's XBRL file for the filing
    df['quantity'] = _num(_col(raw, 'canonical_quantity'))
    df['value'] = _num(_col(raw, 'canonical_value'))
    df['holding_before'] = _num(_col(raw, 'canonical_holding_before'))
    df['holding_after'] = _num(_col(raw, 'canonical_holding_after'))
    df['trade_date_from'] = parse_dates(_col(raw, 'canonical_transaction_date_from', 'acqfromDt'))
    df['trade_date_to'] = parse_dates(_col(raw, 'canonical_transaction_date_to', 'acqtoDt',
                                           'canonical_transaction_date'))
    # NSE carries the date the insider told the company, and so does BSE's
    # insider CSV (scripts/bse_history_backfill.py); the nightly BSE capture
    # doesn't, so for its rows the two deadlines can't be split.
    df['intimation_date'] = parse_dates(_col(raw, 'intimDt', 'intimation_date'))
    df['source'] = _col(raw, 'source').astype('string')
    broadcast_raw = _col(raw, 'canonical_broadcast_date', 'broadcastDt')
    df['broadcast_date'] = parse_dates(broadcast_raw)
    df['broadcast_ts'] = to_datetime_day_first(broadcast_raw)
    df['app_num'] = pd.to_numeric(df['app_id'], errors='coerce')

    # --- classification ---
    df['kind'] = df['mode_raw'].map(classify_mode)
    # No mode filed, but the transaction type says pledge, release or invocation: that is the kind.
    by_type = df['transaction_type_raw'].map(kind_from_type)
    from_type = df['kind'].eq('missing') & by_type.notna()
    df.loc[from_type, 'kind'] = by_type[from_type]
    t['kind_from_transaction_type'] = int(from_type.sum())
    df['is_market'] = df['kind'].eq('market')
    df['side'] = [side_of(tt, m) for tt, m in zip(df['transaction_type_raw'], df['mode_raw'])]
    df['person_role'] = df['person_category_raw'].map(classify_role)
    # Holding-only disclosures (on appointment, on becoming a promoter): no
    # shares change hands, yet NSE's nightly parser files an empty
    # transaction type as 'Acquisition'. Not a trade of any kind: kind
    # 'holding_only', no side, never market. Recognised from the numbers, not
    # the wording: no quantity, no value, a holding filed and unchanged.
    # Pledges keep their kind (a pledge never changes the holding).
    df['_filed_kind'] = df['kind']
    hb, ha = df['holding_before'], df['holding_after']
    holding_only = (~_true(df['quantity'] > 0) & ~_true(df['value'] > 0)
                    & ~_true(df['kind'].str.startswith('pledge'))
                    & _true(hb.notna() | ha.notna()) & ~_true(hb.notna() & ha.notna() & (hb != ha)))
    df.loc[holding_only, 'kind'] = 'holding_only'
    df.loc[holding_only, 'is_market'] = False
    df.loc[holding_only, 'side'] = None
    # A pledge moves no shares between owners, so it has no side: BSE's insider CSV files a pledge as
    # 'Acquisition', its nightly feed with none, and the two feeds' copies of one filing must match to be
    # one row (Aequs and Sical Logistics pledges were kept twice from BSE, audit 22 Oct).
    df.loc[_true(df['kind'].str.startswith('pledge')), 'side'] = None
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
    # % of market cap is taken at the trade's last day (NSE's daily mcap file,
    # issue size x close); `market_cap` stays the latest (audit W1).
    at = market_cap.at_trade_date(df['nse_symbol'], df['trade_date_to'], market_cap_daily, df['market_cap'],
                                  fallback_symbols=df['symbol'].where(df['exchange'].eq('nse')))
    for c in at.columns:
        df[c] = at[c].to_numpy()
    t['market_cap_basis'] = _counts(df['market_cap_basis'])
    report.unmatched(df.loc[df['isin'].isna(), ['exchange', 'symbol', 'company_raw']]
                     .rename(columns={'company_raw': 'name'}).astype(str).drop_duplicates()
                     .assign(table='insider_trades').to_dict('records'))

    # --- measures ---
    df['price'] = (df['value'] / df['quantity']).where(df['quantity'] > 0)
    df['holding_change_pct'] = ((df['holding_after'] - df['holding_before']) / df['holding_before'] * 100
                                ).where(df['holding_before'] >= HOLDING_BASE_MIN)
    df['pct_of_mcap'] = (df['value'] / df['market_cap_at_trade'] * 100).where(df['market_cap_at_trade'] > 0)
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
    df['_bse_csv'] = df['source'].eq(BSE_INSIDER_SOURCE).fillna(False).astype(bool)
    # Before the removals and the flags, so a blank BSE pledge copy is read with the kind it takes.
    t['pledge_quantity_from_bse'] = _pledge_quantity_from_bse(df)
    keep = pd.Series(True, index=df.index)
    known_app = set(df['app_id'].dropna()) - {''}
    superseded = df['app_id'].isin(set(df['prev_app_id'].dropna()) & known_app)
    report.removed('insider_trades', 'superseded_by_revision', df.loc[superseded, 'source_id'])
    keep &= ~superseded
    # Most NSE re-filings carry no prevAppId but are listed as 'Revision'
    # (typeOfSubmission; TODO A: 41 of 3,152 filings, 2 with prevAppId). A
    # revision that corrects the quantity or the value changes the very
    # fields the content match below compares, so both rows would count.
    # The marker settles it (`_superseded_by_marker`).
    by_marker, t['revision_marker'] = _superseded_by_marker(df[keep])
    report.removed('insider_trades', 'superseded_by_revision_marker', df.loc[by_marker, 'source_id'])
    keep.loc[by_marker] = False
    # The BSE copy of a replaced NSE row is the replaced filing too, unless it
    # is also a copy of a row still kept.
    replaced = df.index[superseded.to_numpy()].union(by_marker)
    if len(replaced):
        bse_rows = df[keep & df['exchange'].eq('bse')]
        to_old = {j for _, j in _pair_copies(df.loc[replaced], bse_rows)}
        to_kept = {j for _, j in _pair_copies(df[keep & df['exchange'].eq('nse')], bse_rows.loc[list(to_old)])}
        old_copies = pd.Index(sorted(to_old - to_kept))
        report.removed('insider_trades', 'bse_copy_of_replaced_filing', df.loc[old_copies, 'source_id'])
        keep.loc[old_copies] = False
    # BSE: the nightly capture (BSE's JSON) files only the from-date, as the
    # to-date too; BSE's insider CSV has both. So BSE rows are matched on the
    # from-date, and one filing seen by both feeds is one row: the CSV's is
    # kept (it adds the to-date and the intimation date), counted apart as
    # `bse_same_filing_two_feeds` (its mode is spelt differently in each feed,
    # so it would otherwise read as a correction).
    df['_key_to'] = df['trade_date_to'].where(df['exchange'] != 'bse', df['trade_date_from'])
    # The value to the nearest Rs 10: NSE's nightly XBRL parse and its history file round one value apart by a
    # rupee (Vikram Solar's two releases of 19 Feb 2026, Rs 1,577.56 Cr each, audit 22 Oct).
    df['_value_key'] = df['value'].round(-1)
    df['_has_mode'] = df['mode_raw'].notna()
    key_cols = ['exchange', 'isin', 'symbol', 'person_id', 'side', 'quantity', '_value_key',
                'trade_date_from', '_key_to', 'holding_before', 'holding_after']
    # Latest first; on a tie the copy that files a mode.
    order = (df[keep].assign(_b=df['broadcast_ts'])
             .sort_values(['_b', 'app_num', '_has_mode', '_bse_csv'], ascending=False, na_position='last'))
    groups = order.groupby(key_cols, dropna=False)
    latest_mode = groups['mode_raw'].transform('first')
    dup = order.duplicated(subset=key_cols, keep='first')
    two_feeds = dup & order['exchange'].eq('bse') & (order['_bse_csv'] != groups['_bse_csv'].transform('first'))
    corrected = dup & ~two_feeds & (order['mode_raw'].astype(str) != latest_mode.astype(str))
    report.removed('insider_trades', 'bse_same_filing_two_feeds', order.loc[two_feeds, 'source_id'])
    report.removed('insider_trades', 'corrected_refiling', order.loc[corrected, 'source_id'])
    report.removed('insider_trades', 'repeat_filing', order.loc[dup & ~corrected & ~two_feeds, 'source_id'])
    t['bse_rows_by_feed'] = {'csv': int((df['exchange'].eq('bse') & df['_bse_csv']).sum()),
                             'nightly_json': int((df['exchange'].eq('bse') & ~df['_bse_csv']).sum())}
    report.table('insider_trades')['removal_breakdown'] = _removal_breakdown(raw, df, order, dup, key_cols)
    keep.loc[dup[dup].index] = False
    # A trade filed again with other holdings: the same person, security, side, shares, value and trade dates,
    # the holdings before and after typed differently, and the rows not one after the other (no row's holding
    # after is another's holding before, as two tranches of one day would be). The latest broadcast is kept.
    # VIP Industries, 24 Dec 2025: BSE carries Multiples Private Equity's two buys (Rs 539.88 Cr and Rs 489.55
    # Cr) twice each, holdings 8,876 and 8,049 shares apart; Info Edge, Kapil Kapoor's Rs 68.05 Cr sale of
    # 18-20 Aug 2026, NSE appIds 2427 and 3962 (audit 22 Oct).
    refiled = _refiled_with_other_holdings(order[~dup], key_cols)
    report.removed('insider_trades', 'refiled_with_other_holdings', df.loc[refiled, 'source_id'])
    keep.loc[refiled] = False
    df = df[keep].copy()
    group_transfer = _promoter_group_transfers(df)
    df.loc[group_transfer, 'kind'] = 'inter_se'
    df.loc[group_transfer, 'is_market'] = False
    t['promoter_group_transfers_on_market'] = int(group_transfer.sum())

    # --- flags: kept, but held back from rankings until checked ---
    flags = [[] for _ in range(len(df))]

    def flag(mask, name):
        for i in np.flatnonzero(np.asarray(mask.fillna(False), dtype=bool)):
            flags[i].append(name)

    flag(df['isin'].isna(), 'unmatched_security')
    # Only equity shares are the company's shares: a trade in ADRs/GDRs/FCCBs, warrants, derivatives, debentures or
    # 'any other instrument' is held back (audit 22 Oct: 30 eligible NSE rows filed as ADR/GDR/FCCB, 12 as any other
    # instrument, 2 as convertible debentures; BSE 25 as any other instrument). Blank: taken as shares, as filed before.
    st = df['security_type_raw'].astype('string').str.strip().str.lower().fillna('')
    flag(pd.Series(st.ne('') & ~st.str.contains('equity'), index=df.index), 'not_equity_shares')
    flag(df['kind'].isin(['unrecognised', 'missing']), 'unrecognised_mode')
    flag(df['pct_of_mcap'] > VALUE_SHARE_OF_MCAP_REVIEW * 100, 'value_over_25pct_of_mcap')
    multiple = df['holding_after'] / df['holding_before'].where(df['holding_before'] > 0)
    flag(df['is_market'] & (multiple > HOLDING_MULTIPLE_REVIEW), 'holding_jump_on_market_trade')
    # Data checks (docs/CLEAN_LAYER.md): holding after - holding before =
    # shares traded, up for a buy and down for a sale.
    df['holding_check'] = holding_check(df)
    flag(df['holding_check'].isin(['differs', 'against_side_and_differs']), 'holding_change_differs_from_quantity')
    flag(df['holding_check'].str.startswith('against_side'), 'holding_moves_against_side')
    # Gifts, ESOP grants and transmissions are legitimately filed at zero.
    flag(df['is_market'] & (df['quantity'] > 0) & ~(df['value'] > 0), 'missing_or_zero_value')
    # A market trade with no shares filed: nothing to size it by. (No
    # shares, no value and an unchanged holding was made holding_only above.)
    flag(df['is_market'] & ~_true(df['quantity'] > 0), 'missing_quantity')
    mode_side = df['mode_raw'].map(_side_word)
    flag(df['is_market'] & mode_side.notna() & df['side'].notna() & (mode_side != df['side']),
         'mode_contradicts_side')
    to, frm = pd.to_datetime(df['trade_date_to']), pd.to_datetime(df['trade_date_from'])
    intim, bcast = pd.to_datetime(df['intimation_date']), pd.to_datetime(df['broadcast_date'])
    today = pd.Timestamp(run_date)
    flag((frm > to) | (intim > bcast), 'dates_out_of_order')
    # Told the company, or published, before the last day of the trade.
    flag((to > intim) | (to > bcast), 'disclosed_before_trade')
    flag(to > today, 'trade_date_in_future')
    flag((intim > today) | (bcast > today), 'disclosure_dated_in_future')

    # Implied price (value / shares) against the traded range of the trade's
    # sessions in our own price layer, either exchange. Only market trades
    # are flagged: ESOPs, allotments and transfers are priced off the market
    # by design (their outcomes are counted by kind, nothing more). A unit
    # error, a swap or a price far outside is held back; a price a little
    # outside is marked only, until the diagnostic has measured how often
    # honest filings land there.
    rng = day_range.attach(df, price_ranges, 'isin', 'trade_date_from', 'trade_date_to')
    checked = day_range.check(df['price'].where(df['side'].notna() & ~df['kind'].str.startswith('pledge')), rng,
                              value=df['value'])
    df['day_low'], df['day_high'], df['price_check'] = rng['day_low'], rng['day_high'], checked['price_check']
    market, pc = df['is_market'].astype(bool), df['price_check']
    flag(market & pc.eq('power_of_ten'), 'value_off_by_power_of_ten')
    flag(market & pc.eq('swapped'), 'quantity_value_swapped')
    flag(market & pc.eq('value_is_price'), 'value_filed_as_price_per_share')
    flag(market & pc.eq('face_value'), 'valued_at_face_value')
    flag(market & pc.isin(['far_below', 'far_above']), 'price_far_outside_day_range')
    marks = [[] for _ in range(len(df))]
    for i in np.flatnonzero(_true(market & pc.isin(['below', 'above']))):
        marks[i].append('price_outside_day_range')
    for i in np.flatnonzero(group_transfer.to_numpy()):
        marks[i].append('promoter_group_transfer')
    df['flags'] = [','.join(f) for f in flags]
    df['marks'] = [','.join(m) for m in marks]
    df['needs_review'] = df['flags'] != ''
    report.flagged('insider_trades', flags)
    report.marked('insider_trades', marks)
    only = df['kind'].eq('holding_only')
    t['data_checks'] = {
        'holding': {'all': _counts(df['holding_check']), 'market': _counts(df.loc[market, 'holding_check'])},
        'price': {'price_layer': price_ranges is not None, 'tolerance': day_range.PRICE_TOLERANCE,
                  'far_outside': day_range.FAR_OUTSIDE, 'max_span_days': day_range.MAX_SPAN_DAYS,
                  'market': _counts(pc[market]), 'all': _counts(pc),
                  'by_kind': {str(k): _counts(g) for k, g in pc.groupby(df['kind'])},
                  'power_of_ten': _counts(checked['unit_power'].dropna().astype(int).astype(str))},
        'holding_only': {'count': int(only.sum()), 'filed_as': _counts(df.loc[only, '_filed_kind']),
                         'examples': df.loc[only, 'source_id'].astype(str).head(25).tolist()},
    }

    # --- NSE/BSE copies of one filing ---
    df['trade_id'] = [_row_id(p) for p in zip(df['exchange'], df['source_id'])]
    # A BSE row is a copy of an NSE row only when person, security, side,
    # kind, shares and trade dates agree, one BSE row per NSE row; an NSE row
    # is never demoted (audit W3, W4). `_pair_copies` says which.
    df['is_primary'] = True
    df['primary_id'] = None
    df['listed_on'] = df['exchange']
    pairs = _pair_copies(df[df['exchange'].eq('nse')], df[df['exchange'].eq('bse')])
    if pairs:
        n_idx, b_idx = (list(x) for x in zip(*pairs))
        df.loc[b_idx, 'is_primary'] = False
        df.loc[b_idx, 'primary_id'] = df.loc[n_idx, 'trade_id'].to_numpy()
        df.loc[n_idx + b_idx, 'listed_on'] = 'bse,nse'
    bse_night = df['exchange'].eq('bse') & ~df['_bse_csv']
    t['nse_bse_copies'] = {'linked': len(pairs),
                           'linked_bse_nightly_on_span': int(bse_night.loc[[j for _, j in pairs]].sum()) if pairs else 0}

    cols = ['trade_id', 'source_id', 'exchange', 'listed_on', 'is_primary', 'primary_id', 'app_id',
            'prev_app_id', 'nse_submission_type', 'nse_revision_remark',
            'isin', 'security_match', 'company', 'nse_symbol', 'bse_code', 'symbol',
            'person_id', 'person_name', 'person_role', 'person_role_source', 'person_category_raw',
            'side', 'kind', 'is_market', 'mode_raw', 'transaction_type_raw', 'security_type_raw',
            'quantity', 'value', 'signed_value', 'price', 'day_low', 'day_high', 'price_check',
            'holding_before', 'holding_after', 'holding_check',
            'holding_change_pct', 'market_cap', 'market_cap_at_trade', 'market_cap_date', 'market_cap_basis',
            'pct_of_mcap', 'trade_date_from', 'trade_date_to', 'intimation_date', 'broadcast_date',
            'insider_to_company_sessions', 'insider_filed_late',
            'company_to_exchange_sessions', 'company_filed_late', 'trade_to_public_sessions',
            'source_url', 'flags', 'marks', 'needs_review']
    out = df[cols].reset_index(drop=True)
    t['output_rows'] += len(out)
    t['by_exchange'] = out['exchange'].value_counts().to_dict()
    return out
