"""NSE corporate-event payloads -> tidy rows. Pure functions, no I/O.

Every row gets `event_id` (a stable hash of the fields that identify the
event, so re-fetching the same event over the rolling window never adds it
twice) and keeps the NSE payload in `raw_json` for audit.
"""
from __future__ import annotations

import hashlib
import html
import json
import re

import pandas as pd

from insiders_clean.dates import parse_dates
from insiders_clean.entities import entity_display, entity_key


def _id(*parts) -> str:
    return hashlib.sha1('|'.join('' if p is None else str(p).strip() for p in parts).encode()).hexdigest()[:20]


def _num(v):
    if v is None:
        return None
    s = str(v).replace(',', '').strip()
    if s in ('', '-', 'NA', 'Nil', 'nil'):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _raw(r: dict) -> str:
    return json.dumps(r, ensure_ascii=False, sort_keys=True, default=str)


def _frame(rows: list[dict], columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=columns) if rows else pd.DataFrame(columns=columns)


# --- SAST Regulation 29 -------------------------------------------------------

SAST_COLUMNS = ['event_id', 'symbol', 'company', 'target_company', 'transaction_date', 'shares_traded',
                'percent_equity_traded', 'acquirer_name', 'acquirer_id', 'is_promoter', 'regulation',
                'action_type', 'mode', 'is_market', 'trade_date_from', 'trade_date_to', 'shares_acquired',
                'shares_sold', 'shares_after', 'pct_acquired', 'pct_sold', 'post_stake_pct', 'broadcast_ts',
                'application_no', 'attachment', 'instrument', 'raw_json']


def sast_instrument(raw_json) -> str | None:
    """What the stake is in, as filed (acqType: 'Equity shares', 'Warrant', 'Voting Rights other than by shares',
    'Others'), from a stored filing's raw JSON; None when not filed. A warrant or a voting right is not a
    share bought (audit 22 Oct: Craft Emerging's 5.79% of Jindal Supreme is voting rights)."""
    try:
        v = json.loads(raw_json).get('acqType') if isinstance(raw_json, str) else None
    except (ValueError, AttributeError):
        return None
    return v.strip() if isinstance(v, str) and v.strip() else None


def parse_sast(rows: list[dict]) -> pd.DataFrame:
    """Reg 29(1): crossing 5%. Reg 29(2): a holder of 5%+ moving 2% or more.
    This is where funds and individual investors outside the promoter group
    show up, which the insider (PIT) filings do not cover."""
    out = []
    for r in rows or []:
        span = str(r.get('acquirerDate') or '')
        dates = re.findall(r'\d{1,2}-[A-Za-z]{3}-\d{4}', span)
        out.append({
            'event_id': _id('sast', r.get('application_no'), r.get('acquirerName'), r.get('acqSaleType'),
                            r.get('noOfShareAcq'), r.get('noOfShareSale'), r.get('noOfShareAft')),
            'symbol': (r.get('symbol') or '').strip().upper() or None,
            'company': r.get('company'),
            'acquirer_name': entity_display(r.get('acquirerName')),
            'acquirer_id': entity_key(r.get('acquirerName')),
            'is_promoter': str(r.get('promoterType') or '').upper() == 'Y',
            'regulation': r.get('regType'),
            'action_type': r.get('acqSaleType'),          # Acquisition / Sale / Both
            'mode': r.get('acquisitionMode'),              # Open Market / Inter-se transfer / Preferential Allotment / Others ...
            'is_market': str(r.get('acquisitionMode') or '').strip().lower() == 'open market',
            'trade_date_from': dates[0] if dates else None,
            'trade_date_to': dates[-1] if dates else None,
            'shares_acquired': _num(r.get('noOfShareAcq')),
            'shares_sold': _num(r.get('noOfShareSale')),
            'shares_after': _num(r.get('noOfShareAft')),
            'pct_acquired': _num(r.get('totAcqShare')),
            'pct_sold': _num(r.get('totSaleShare')),
            'post_stake_pct': _num(r.get('totAftShare')),
            'broadcast_ts': r.get('timestamp') or r.get('sysTime'),
            'application_no': r.get('application_no'),
            'attachment': r.get('attachement'),
            'instrument': (r.get('acqType') or '').strip() or None,
            'raw_json': _raw(r),
        })
    df = _frame(out, SAST_COLUMNS)
    for c in ('trade_date_from', 'trade_date_to'):
        df[c] = parse_dates(df[c])
    for c in ('shares_acquired', 'shares_sold', 'shares_after', 'pct_acquired', 'pct_sold', 'post_stake_pct'):
        df[c] = pd.to_numeric(df[c], errors='coerce')
    # Names used in the PR 3 spec; the detailed columns stay alongside.
    df['target_company'] = df['company']
    df['transaction_date'] = df['trade_date_to']
    # Net of both sides ('Both' rows file a buy and a sale); empty when the
    # filing gives neither figure, never a made-up zero.
    has_qty = df['shares_acquired'].notna() | df['shares_sold'].notna()
    has_pct = df['pct_acquired'].notna() | df['pct_sold'].notna()
    df['shares_traded'] = (df['shares_acquired'].fillna(0) - df['shares_sold'].fillna(0)).where(has_qty)
    df['percent_equity_traded'] = (df['pct_acquired'].fillna(0) - df['pct_sold'].fillna(0)).where(has_pct)
    return df[SAST_COLUMNS]


# --- Corporate actions -----------------------------------------------------------

CA_COLUMNS = ['event_id', 'symbol', 'isin', 'company', 'series', 'purpose', 'subject', 'ex_date', 'record_date',
              'ratio', 'face_value', 'rights_premium', 'rights_issue_price', 'dividend_per_share', 'face_value_from', 'face_value_to', 'needs_price_gap',
              'broadcast_date', 'raw_json']
# Order matters: 'Scheme Of Arrangement - Bonus' is a bonus, not a scheme to skip.
_PURPOSES = [
    (r'buy\s*-?\s*back', 'buyback'),
    (r'\bbonus\b', 'bonus'),
    (r'split|sub-?division', 'split'),
    (r'\brights?\b', 'rights'),
    (r'dividend', 'dividend'),
]
KEPT_PURPOSES = {p for _, p in _PURPOSES}


def action_purpose(subject) -> str | None:
    s = str(subject or '').lower()
    for pat, purpose in _PURPOSES:
        if re.search(pat, s):
            return purpose
    return None


def parse_corporate_actions(rows: list[dict]) -> tuple[pd.DataFrame, int]:
    """(kept actions, number dropped). Kept: buyback, bonus, split, rights,
    dividend. Dropped: interest payments, unit distributions, demergers and
    other schemes (counted, not silently lost)."""
    out, dropped = [], 0
    for r in rows or []:
        subject = str(r.get('subject') or '').strip()
        purpose = action_purpose(subject)
        if purpose is None:
            dropped += 1
            continue
        ratio = re.search(r'(\d+)\s*:\s*(\d+)', subject)
        price = re.search(r'(?:premium|@|price)[^0-9]*(\d+(?:\.\d+)?)', subject, re.IGNORECASE)
        fv = re.search(r'from\s+r[se]\.?\s*(\d+(?:\.\d+)?).*?to\s+r[se]\.?\s*(\d+(?:\.\d+)?)', subject, re.IGNORECASE)
        divs = [float(x) for x in re.findall(r'r[se]\.?\s*(\d+(?:\.\d+)?)\s*per\s*sh', subject, re.IGNORECASE)]
        out.append({
            'event_id': _id('ca', r.get('symbol'), r.get('series'), subject, r.get('exDate'), r.get('recDate')),
            'symbol': (r.get('symbol') or '').strip().upper() or None,
            'isin': r.get('isin'),
            'company': r.get('comp'),
            'series': r.get('series'),
            'purpose': purpose,
            'subject': subject,
            'ex_date': r.get('exDate'),
            'record_date': r.get('recDate'),
            'ratio': f'{ratio.group(1)}:{ratio.group(2)}' if ratio and purpose in ('bonus', 'rights') else None,
            'face_value': _num(r.get('faceVal')),
            # Rights: NSE writes the premium over face value; the issue price
            # is face value + premium.
            'rights_premium': float(price.group(1)) if price and purpose == 'rights' else None,
            'rights_issue_price': (float(price.group(1)) + (_num(r.get('faceVal')) or 0))
                                  if price and purpose == 'rights' and _num(r.get('faceVal')) is not None else None,
            'dividend_per_share': sum(divs) if purpose == 'dividend' and divs else None,
            'face_value_from': float(fv.group(1)) if fv and purpose == 'split' else None,
            'face_value_to': float(fv.group(2)) if fv and purpose == 'split' else None,
            # Buyback price and route are not in this feed; the price-gap
            # work needs them from the offer documents.
            'needs_price_gap': purpose in ('buyback', 'rights'),
            'broadcast_date': r.get('caBroadcastDate'),
            'raw_json': _raw(r),
        })
    df = _frame(out, CA_COLUMNS)
    for c in ('ex_date', 'record_date', 'broadcast_date'):
        df[c] = parse_dates(df[c])
    return df, dropped


# --- Board meetings ---------------------------------------------------------------

BM_COLUMNS = ['event_id', 'symbol', 'isin', 'company', 'meeting_date', 'purposes', 'results', 'dividend',
              'buyback', 'bonus', 'fund_raising', 'split', 'rights', 'preferential', 'description',
              'intimation_ts', 'raw_json']
_BM_FLAGS = {
    'results': r'financial\s+results|quarterly\s+results|audited|unaudited',
    'dividend': r'dividend',
    'buyback': r'buy\s*-?\s*back',
    'bonus': r'\bbonus\b',
    'fund_raising': r'fund\s*-?\s*rais|raising\s+of\s+funds|\bqip\b|qualified\s+institutions',
    'split': r'split|sub-?division',
    'rights': r'rights\s+issue',
    'preferential': r'preferential',
}


def parse_board_meetings(rows: list[dict]) -> tuple[pd.DataFrame, int]:
    """(meetings that consider results, dividend, buyback, bonus, fund
    raising, split, rights or preferential issue; number dropped). NSE files
    an 'intimation' row whose purpose is only in the description, so both
    fields are read; the rows for one meeting are combined into one."""
    out, dropped = [], 0
    for r in rows or []:
        text = f"{r.get('bm_purpose') or ''} {r.get('bm_desc') or ''}"
        flags = {k: bool(re.search(p, text, re.IGNORECASE)) for k, p in _BM_FLAGS.items()}
        if not any(flags.values()):
            dropped += 1
            continue
        out.append({'event_id': None, 'symbol': (r.get('bm_symbol') or '').strip().upper() or None,
                    'isin': r.get('sm_isin'), 'company': r.get('sm_name'), 'meeting_date': r.get('bm_date'),
                    **flags, 'description': (r.get('bm_desc') or '').strip(),
                    'intimation_ts': r.get('bm_timestamp'), 'raw_json': _raw(r)})
    df = _frame(out, BM_COLUMNS)
    if df.empty:
        return df, dropped
    flag_cols = list(_BM_FLAGS)
    df = (df.sort_values('intimation_ts')
            .groupby(['symbol', 'meeting_date'], as_index=False, sort=False)
            .agg({**{c: 'any' for c in flag_cols}, 'isin': 'first', 'company': 'first',
                  'description': lambda s: ' | '.join(dict.fromkeys(x for x in s if x)),
                  'intimation_ts': 'last', 'raw_json': lambda s: '[' + ','.join(s) + ']'}))
    df['purposes'] = df[flag_cols].apply(lambda row: ','.join(c for c in flag_cols if row[c]), axis=1)
    df['event_id'] = [_id('bm', s, d) for s, d in zip(df['symbol'], df['meeting_date'])]
    df['meeting_date'] = parse_dates(df['meeting_date'])
    return df[BM_COLUMNS], dropped


# --- Shareholding pattern -----------------------------------------------------------

SH_COLUMNS = ['event_id', 'record_id', 'symbol', 'isin', 'company', 'quarter_end', 'submission_date',
              'promoter_holding_pct', 'public_holding_pct', 'employee_trust_pct', 'revised', 'xbrl_url', 'raw_json']


def parse_shareholding_listing(rows: list[dict]) -> pd.DataFrame:
    out = []
    for r in rows or []:
        out.append({
            'event_id': _id('shp', r.get('recordId')),
            'record_id': str(r.get('recordId') or ''),
            'symbol': (r.get('symbol') or '').strip().upper() or None,
            'isin': r.get('isin'),
            'company': r.get('name'),
            'quarter_end': r.get('date'),
            'submission_date': r.get('submissionDate'),
            'promoter_holding_pct': _num(r.get('pr_and_prgrp')),
            'public_holding_pct': _num(r.get('public_val')),
            'employee_trust_pct': _num(r.get('employeeTrusts')),
            'revised': str(r.get('revisedData') or '').upper() == 'Y',
            'xbrl_url': r.get('xbrl'),
            'raw_json': _raw(r),
        })
    df = _frame(out, SH_COLUMNS)
    for c in ('quarter_end', 'submission_date'):
        df[c] = parse_dates(df[c])
    return df


_PROMOTER_CTX = 'ShareholdingOfPromoterAndPromoterGroup_ContextI'
_PUBLIC_CTX = 'PublicShareholding_ContextI'
_TOTAL_CTX = 'ShareholdingPattern_ContextI'


def _fact(xml: str, tag: str, ctx: str):
    m = re.search(rf'<in-bse-shp:{tag}\b[^>]*contextRef="{ctx}"[^>]*>([^<]*)<', xml)
    return _num(m.group(1)) if m else None


_NON_PROMOTER_NON_PUBLIC_CTX = 'SharesHeldByNonPromoterNonPublicShareholders_ContextI'


def parse_shp_xbrl(xml: str) -> dict:
    """Promoter, public and total shares and promoter pledges from a
    shareholding-pattern XBRL (SEBI's in-bse-shp taxonomy, as NSE files it).

    promoter_pledge_pct is pledged shares as a % of the promoter group's own
    shares, which is what a pledge warning needs (Zee, Jun 2026: 2,060,000 of
    38,316,284 = 5.38%, matching the filing's own 0.0538), not a % of the
    company.

    A company with no promoter group (ITC, L&T, ICICI Bank, Swiggy, AYE, Jun
    2026) files no promoter context at all; when public plus non-promoter
    non-public shares then make up the whole total, promoter shares are 0 as
    filed (`no_promoter_group`), and the pledge % stays blank (nothing to
    pledge). Raises ValueError, with the reason, otherwise."""
    total = _fact(xml, 'NumberOfShares', _TOTAL_CTX)
    if not total:
        raise ValueError('total shares not found')
    promoter = _fact(xml, 'NumberOfShares', _PROMOTER_CTX)
    public = _fact(xml, 'NumberOfShares', _PUBLIC_CTX)
    no_group = False
    if promoter is None:
        if f'id="{_PROMOTER_CTX}"' in xml:
            raise ValueError('promoter context filed without a share count')
        rest = (public or 0.0) + (_fact(xml, 'NumberOfShares', _NON_PROMOTER_NON_PUBLIC_CTX) or 0.0)
        if public is None or abs(rest - total) >= 1:
            raise ValueError('no promoter context and public shares do not make up the total')
        promoter, no_group = 0.0, True
    pledged = _fact(xml, 'NumberOfSharesEncumberedUnderPledged', _PROMOTER_CTX) or 0.0
    encumbered = _fact(xml, 'NumberOfSharesEncumbered', _PROMOTER_CTX) or pledged
    return {
        'promoter_shares': promoter, 'public_shares': public, 'total_shares': total,
        'promoter_pledged_shares': pledged, 'promoter_encumbered_shares': encumbered,
        'promoter_pledge_pct': None if no_group else round(pledged / promoter * 100, 4) if promoter else 0.0,
        'promoter_encumbered_pct': None if no_group else round(encumbered / promoter * 100, 4) if promoter else 0.0,
        'promoter_holding_pct_xbrl': round(promoter / total * 100, 4),
        'public_holding_pct_xbrl': round(public / total * 100, 4) if public is not None else None,
        'no_promoter_group': no_group,
    }


# --- Buybacks: tender offers and daily open-market reports ------------------------

TENDER_COLUMNS = ['event_id', 'symbol', 'company', 'series', 'offer_type', 'offer_type_raw', 'issue_type',
                  'offer_price', 'shares_sought', 'shares_tendered', 'times_tendered', 'accepted_price',
                  'offer_open', 'offer_close', 'status', 'raw_json']


def tender_kind(offer_type) -> str:
    s = str(offer_type or '').lower()
    if re.search(r'buy\s*-?\s*back', s):
        return 'buyback'
    if 'delist' in s:
        return 'delisting'
    if re.search(r'take\s*-?\s*over', s):
        return 'takeover'
    return 'other'


def parse_tender_offers(past: list[dict], active: list[dict] = ()) -> pd.DataFrame:
    """NSE's tender-offer list -> one row per offer. NSE spells the type five
    ways ('Buy back', 'BuyBack', ...); offer_type is the normalised kind.
    offer_price is NSE's 'band' (past) or 'floorPrice' (active): the fixed
    buyback price, or the floor of a reverse book building."""
    out = []
    for r, status in [(r, 'past') for r in past or []] + [(r, 'active') for r in active or []]:
        sym = (r.get('symbol') or '').strip().upper() or None
        opened = r.get('offerDate') or r.get('todStartDate')
        out.append({
            'event_id': _id('tender', sym, r.get('series'), opened),
            'symbol': sym, 'company': r.get('company'), 'series': r.get('series'),
            'offer_type': tender_kind(r.get('offerType')), 'offer_type_raw': r.get('offerType'),
            'issue_type': r.get('issueType'),
            'offer_price': _num(r.get('band') if 'band' in r else r.get('floorPrice')),
            'shares_sought': _num(r.get('issueSize')),
            'shares_tendered': _num(r.get('totQty')),
            'times_tendered': _num(r.get('numberOfTimes') if 'numberOfTimes' in r else r.get('numberOfTImes')),
            'accepted_price': _num(r.get('allocatedPrice')),
            'offer_open': opened, 'offer_close': r.get('offerEndDate') or r.get('todEndDate'),
            'status': status,
            'raw_json': _raw({k: v for k, v in r.items() if k not in ('demand', 'bidDetails')}),
        })
    df = _frame(out, TENDER_COLUMNS)
    for c in ('offer_open', 'offer_close'):
        df[c] = parse_dates(df[c])
    # An offer that is still open is in both lists on its last day; the active row is newer.
    return df.drop_duplicates('event_id', keep='last').reset_index(drop=True)[TENDER_COLUMNS]


DAILY_BB_COLUMNS = ['event_id', 'symbol', 'company', 'report_ts', 'report_date', 'text', 'attachment', 'raw_json']


def parse_daily_buybacks(rows: list[dict]) -> pd.DataFrame:
    """Daily buyback reports, as filed. The share counts are only in the
    free text (and NSE does not say whether they are the day's or the total),
    so they are kept as text, not read into a number."""
    out = [{'event_id': _id('dbb', r.get('symbol'), r.get('exchdisstime') or r.get('an_dt'), r.get('attchmntFile')),
            'symbol': (r.get('symbol') or '').strip().upper() or None, 'company': r.get('sm_name'),
            'report_ts': r.get('exchdisstime') or r.get('an_dt'), 'report_date': r.get('exchdisstime') or r.get('an_dt'),
            'text': r.get('attchmntText'), 'attachment': r.get('attchmntFile'), 'raw_json': _raw(r)}
           for r in rows or []]
    df = _frame(out, DAILY_BB_COLUMNS)
    df['report_date'] = parse_dates(df['report_date'].astype('string').str[:11])
    return df.drop_duplicates('event_id').reset_index(drop=True)


# --- Promoter and promoter-group members (docs/TODO.md item 21) ------------------
#
# Table II of the shareholding pattern names every promoter and promoter-group
# member. In the XBRL each member has a pair of contexts on its own axis: a
# duration context `D_<Section>_Context<n>` carrying NameOfTheShareholder (and,
# for "any other", CategoryOfOther...Shareholders), and an instant context
# `<Section>_Context<n>` carrying NumberOfShares and the % of the company.
# Promoter members, and only they, also carry TypeOfPromoterShareholding
# (masked by NSE as '******', like the PAN). Checked on 14 filings, taxonomies
# 2025-05-31 and 2025-10-31 (ASIANPAINT, RELIANCE, NESTLEIND, COALINDIA, INFY,
# ADANIENT, ZEEL, CHEVIOT, BFINVEST, MOTILALOFS, JSWINFRA, RIIL, EMCURE,
# ANUHPHR): in every one the members' shares add up exactly to the promoter
# total. Public holders named in Table III (mutual funds, insurers, 1%+
# holders) sit on other axes and carry no promoter type. The PAN is never read.

PROMOTER_SECTIONS = {
    'IndividualsOrHUF': 'Individual or HUF',
    'CentralGovernmentOrStateGovernments': 'Central or state government',
    'OthersIndianShareholders': None,          # the filed category: Bodies Corporate, Trusts, ...
    'NonResidentIndividualsOrForeignIndividuals': 'Non-resident or foreign individual',
    'OtherForeignShareholders': None,          # the filed category: Bodies Corporate, Overseas Corporate Bodies, ...
}
_FACT = re.compile(r'<in-bse-shp:(\w+)\b[^>]*?contextRef="([^"]+)"[^>]*>([^<]*)<')
_MEMBER_CTX = re.compile(r'^D_(\w+?)_Context(\d+)$')


def _words(section: str) -> str:
    return re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', section).capitalize()


def parse_shp_members(xml: str) -> tuple[list[dict], dict]:
    """(members, check) from a shareholding-pattern XBRL. Each member: order in
    the filing, name as filed, section, sub-category, shares, % of the
    company, pledged shares. `check` compares the members' shares with the
    promoter total of the same file: 'match', 'mismatch', or 'no_members'
    when the file names nobody (a company with no promoter group: 0 = 0 is
    'match')."""
    facts: dict[str, dict] = {}
    for tag, ctx, val in _FACT.findall(xml):
        facts.setdefault(ctx, {})[tag] = html.unescape(val).strip()
    members = []
    for ctx, f in facts.items():
        m = _MEMBER_CTX.match(ctx)
        name = f.get('NameOfTheShareholder')
        if not m or not name:
            continue
        section = m.group(1)
        if 'TypeOfPromoterShareholding' not in f and section not in PROMOTER_SECTIONS:
            continue
        inst = facts.get(ctx[2:], {})
        pct = _num(inst.get('ShareholdingAsAPercentageOfTotalNumberOfShares'))
        filed_cat = f.get('CategoryOfOtherIndianShareholders') or f.get('CategoryOfOtherForeignShareholders')
        members.append({
            'member_no': int(m.group(2)),
            'member_name_filed': name,
            'section': section,
            'sub_category': filed_cat or PROMOTER_SECTIONS.get(section) or _words(section),
            'shares': _num(inst.get('NumberOfShares')),
            'pct_of_company': round(pct * 100, 4) if pct is not None else None,
            'pledged_shares': _num(inst.get('NumberOfSharesEncumberedUnderPledged')),
        })
    order = list(PROMOTER_SECTIONS)
    members.sort(key=lambda r: (order.index(r['section']) if r['section'] in order else len(order), r['member_no']))
    for i, r in enumerate(members, 1):
        r['member_no'] = i
    promoter = _fact(xml, 'NumberOfShares', _PROMOTER_CTX) or 0.0
    held = sum(r['shares'] or 0.0 for r in members)
    check = ('no_members' if not members and promoter else
             'match' if abs(held - promoter) < 1 else 'mismatch')
    return members, {'members': len(members), 'member_shares': held, 'promoter_shares': promoter, 'check': check}


# --- Ownership by investor type (Tables III and IV of the shareholding pattern) ----
#
# Every category of SEBI's shareholding pattern is an instant context
# `<Category>_ContextI` on CategoryOfShareholdersAxis carrying NumberOfShares.
# The public section (Table III) has four subtotals, each the sum of its
# sub-categories as filed; a category with no holders is left out of the file
# (read as 0). Context names are the same in taxonomies 2025-05-31 and
# 2025-10-31, checked on 44 filings, Jun 2025 to Sep 2026 (HDFCBANK,
# RELIANCE, SBIN, LT, ITC, INFY, ICICIBANK, ASIANPAINT, COALINDIA, LICI,
# ZEEL, MOTILALOFS and 21 more companies): in each one the sub-categories add up to
# their subtotal and the buckets below to the total.
#
# The % base is SEBI's: total shares less the shares a custodian holds
# against depository receipts (Table IV C1, `CustodianOrDRHolder`), "as a %
# of total no. of shares (calculated as per SCRR, 1957)". It is what each
# filing's own % column and NSE's listing (promoter_holding_pct) use: SBIN Sep
# 2026, promoter 5,079,775,288 of 9,230,766,786 shares with 70,396,990 under
# DRs = 55.45% as filed and listed (55.03% of all shares). The filed % of
# every category in the 44 filings matched shares / this base to 4 decimals.

SHP_CATEGORIES = ('promoter', 'mf', 'insurance', 'banks_fi', 'aif', 'other_dii', 'fpi', 'other_foreign', 'govt',
                  'retail', 'hni', 'corporate', 'other_public', 'non_public_other')
# subtotal context -> {sub-category context: bucket}; SEBI's row in the comment.
SHP_PUBLIC = {
    'InstitutionsDomestic': {                                                       # B1
        'MutualFundsOrUTI': 'mf',                                                   # a
        'VentureCapitalFunds': 'other_dii',                                         # b
        'AlternativeInvestmentFunds': 'aif',                                        # c
        'Banks': 'banks_fi',                                                        # d
        'InsuranceCompanies': 'insurance',                                          # e
        'ProvidentFundsOrPensionFunds': 'other_dii',                                # f
        'AssetReconstructionCompanies': 'other_dii',                                # g
        'SovereignWealthFundsDomestic': 'other_dii',                                # h
        'NBFCsRegisteredWithRBI': 'banks_fi',                                       # i
        'OtherFinancialInstitutions': 'banks_fi',                                   # j
        'OtherInstitutionsDomestic': 'other_dii',                                   # k any other
    },
    'InstitutionsForeign': {                                                        # B2
        'ForeignDirectInvestment': 'other_foreign',                                 # a
        'ForeignVentureCapitalInvestors': 'other_foreign',                          # b
        'SovereignWealthFundsForeign': 'other_foreign',                             # c
        'InstitutionsForeignPortfolioInvestorCategoryOne': 'fpi',                   # d
        'InstitutionsForeignPortfolioInvestorCategoryTwo': 'fpi',                   # e
        'OverseasDepositories': 'other_foreign',                                    # f holding DRs
        'OtherInstitutionsForeign': 'other_foreign',                                # g any other
    },
    'Governments': {                                                                # B3
        'CentralGovernmentOrPresidentOfIndia': 'govt',                              # a
        'StateGovernmentsOrGovernors': 'govt',                                      # b
        'ShareholdingByCompaniesOrBodiesCorporateWhereCentralOrStateGovernmentIsPromoter': 'govt',  # c
    },
    'NonInstitutions': {                                                            # B4
        'AssociateCompaniesOrSubsidiaries': 'other_public',                         # a
        'DirectorsAndDirectorsRelatives': 'other_public',                           # b
        'KeyManagerialPersonnel': 'other_public',                                   # c
        'RelativesOfPromotersOtherThanPromoterGroup': 'other_public',               # d
        'TrustsWhereAnyPersonBelongingToPromoterAndPromoterGroupIsTrusteeOrBeneficiaryOrAuthorOfTrust':
            'other_public',                                                         # e
        'InvestorEducationAndProtectionFund': 'other_public',                       # f
        'ResidentIndividualShareholdersHoldingNominalShareCapitalUpToRsTwoLakh': 'retail',       # g
        'ResidentIndividualShareholdersHoldingNominalShareCapitalInExcessOfRsTwoLakh': 'hni',    # h
        'NonResidentIndians': 'other_public',                                       # i
        'ForeignNationals': 'other_public',                                         # j
        'ForeignCompanies': 'other_public',                                         # k
        'BodiesCorporate': 'corporate',                                             # l
        'OtherNonInstitutions': 'other_public',                                     # m any other: HUF, trusts, LLPs, ...
    },
}
# Table IV, non-promoter non-public: C1 custodian / DR holder (outside the % base, `dr`), C2 employee benefit trusts.
SHP_NON_PUBLIC = {'CustodianOrDRHolder': 'dr', 'EmployeeBenefitsTrusts': 'non_public_other'}
# Table II sub-categories: only the promoter total is used here (the members are parse_shp_members).
SHP_PROMOTER_PARTS = {'Indian', 'Foreign', 'IndividualsOrHinduUndividedFamily', 'CentralGovernmentOrStateGovernmentS',
                      'OtherIndianShareholders', 'NonResidentIndividualsOrForeignIndividuals',
                      'OtherForeignShareholders'}
_SHP_TOTALS = {'ShareholdingPattern', 'ShareholdingOfPromoterAndPromoterGroup', 'PublicShareholding',
               'SharesHeldByNonPromoterNonPublicShareholders'}
_CATEGORY_FACT = re.compile(r'<in-bse-shp:NumberOfShares\b[^>]*?contextRef="(\w+?)_ContextI"[^>]*>([^<]*)<')
_SHP_KNOWN = (_SHP_TOTALS | SHP_PROMOTER_PARTS | set(SHP_PUBLIC) | set(SHP_NON_PUBLIC)
              | {c for parts in SHP_PUBLIC.values() for c in parts})


def parse_shp_categories(xml: str) -> dict:
    """Shares and % by investor type from a shareholding-pattern XBRL:
    `{bucket}_shares` and `{bucket}_pct` for each of SHP_CATEGORIES, plus
    `dr_shares` (held by a custodian against depository receipts),
    `pct_base_shares` (total less dr_shares, SEBI's % base, see above),
    `categories_check` and `categories_unmapped`.

    Each bucket is the sum of the sub-categories mapped to it (SHP_PUBLIC,
    SHP_NON_PUBLIC); promoter is parse_shp_xbrl's promoter shares (0 as filed
    for a company with no promoter group). Nothing is filled by difference.
    `categories_check` is 'match' when each filed subtotal (domestic
    institutions, foreign institutions, government, non-institutions, public,
    non-promoter non-public) equals the sum of its filed sub-categories and
    the buckets plus dr_shares add up to the total, within one share (the %
    then add up to 100); 'mismatch' otherwise. `categories_unmapped` names
    what did not map: a subtotal's shares found in none of its filed
    sub-categories, or a category context this parser does not know
    (reported, never put in a bucket); blank when nothing. Raises ValueError,
    as parse_shp_xbrl does, when the totals are missing."""
    base = parse_shp_xbrl(xml)
    total = base['total_shares']
    filed: dict[str, float] = {}
    for ctx, val in _CATEGORY_FACT.findall(xml):
        n = _num(val)
        if n is not None:
            filed.setdefault(ctx, n)
    buckets = dict.fromkeys(SHP_CATEGORIES + ('dr',), 0.0)
    buckets['promoter'] = base['promoter_shares']
    notes, mismatch = [], False
    groups = dict(SHP_PUBLIC, SharesHeldByNonPromoterNonPublicShareholders=SHP_NON_PUBLIC)
    for subtotal, parts in groups.items():
        held = 0.0
        for ctx, bucket in parts.items():
            buckets[bucket] += filed.get(ctx, 0.0)
            held += filed.get(ctx, 0.0)
        gap = filed.get(subtotal, 0.0) - held
        if abs(gap) >= 1:
            notes.append(f'{subtotal}: {gap:.0f} shares in no filed sub-category')
            mismatch = True
    gap = filed.get('PublicShareholding', 0.0) - sum(filed.get(s, 0.0) for s in SHP_PUBLIC)
    if abs(gap) >= 1:
        notes.append(f'PublicShareholding: {gap:.0f} shares in no filed subtotal')
        mismatch = True
    for ctx in sorted(set(filed) - _SHP_KNOWN):
        notes.append(f'unknown category {ctx}: {filed[ctx]:.0f} shares')
    summed = sum(buckets.values())
    if abs(summed - total) >= 1:
        notes.append(f'categories add up to {summed:.0f}, total is {total:.0f}')
        mismatch = True
    pct_base = total - buckets['dr']
    if pct_base <= 0:
        raise ValueError('no shares outside depository receipts')
    out = {}
    for b in SHP_CATEGORIES:
        out[f'{b}_shares'] = buckets[b]
        out[f'{b}_pct'] = round(buckets[b] / pct_base * 100, 4)
    out['dr_shares'] = buckets['dr']
    out['pct_base_shares'] = pct_base
    out['categories_check'] = 'mismatch' if mismatch else 'match'
    out['categories_unmapped'] = '; '.join(notes) or None
    return out
