"""NSE corporate-event payloads -> tidy rows. Pure functions, no I/O.

Every row gets `event_id` (a stable hash of the fields that identify the
event, so re-fetching the same event over the rolling window never adds it
twice) and keeps the NSE payload in `raw_json` for audit.
"""
from __future__ import annotations

import hashlib
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
                'application_no', 'attachment', 'raw_json']


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


def parse_shp_xbrl(xml: str) -> dict:
    """Promoter, public and total shares and promoter pledges from a
    shareholding-pattern XBRL (SEBI's in-bse-shp taxonomy, as NSE files it).

    promoter_pledge_pct is pledged shares as a % of the promoter group's own
    shares, which is what a pledge warning needs (Zee, Jun 2026: 2,060,000 of
    38,316,284 = 5.38%, matching the filing's own 0.0538), not a % of the
    company. Raises ValueError when the promoter or total figure is missing."""
    promoter = _fact(xml, 'NumberOfShares', _PROMOTER_CTX)
    total = _fact(xml, 'NumberOfShares', _TOTAL_CTX)
    if promoter is None or not total:
        raise ValueError('promoter or total shares not found in shareholding XBRL')
    public = _fact(xml, 'NumberOfShares', _PUBLIC_CTX)
    pledged = _fact(xml, 'NumberOfSharesEncumberedUnderPledged', _PROMOTER_CTX) or 0.0
    encumbered = _fact(xml, 'NumberOfSharesEncumbered', _PROMOTER_CTX) or pledged
    return {
        'promoter_shares': promoter, 'public_shares': public, 'total_shares': total,
        'promoter_pledged_shares': pledged, 'promoter_encumbered_shares': encumbered,
        'promoter_pledge_pct': round(pledged / promoter * 100, 4) if promoter else 0.0,
        'promoter_encumbered_pct': round(encumbered / promoter * 100, 4) if promoter else 0.0,
        'promoter_holding_pct_xbrl': round(promoter / total * 100, 4),
        'public_holding_pct_xbrl': round(public / total * 100, 4) if public is not None else None,
    }
