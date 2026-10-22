"""BSE payloads -> the rows the rest of the pipeline already reads. Pure
functions, no I/O.

* insider CSV and bulk/block history -> the nightly BSE row shape
  (scripts/bse_validate.py::normalize), so r2_writer.canonicalize and the
  cleaners take them unchanged. Deals map to exactly the nightly row, so a
  deal seen by both gets one canonical_event_id; the insider CSV names modes
  and dates differently from the nightly JSON, so those copies are linked in
  the clean layer instead (insiders_clean/insider.py).
* SAST, corporate actions, board meetings and the shareholding filings list
  -> the columns of NSE's tables (collectors/nse_events/parsers.py), with
  `exchange` = 'BSE' and `bse_code`.
* a shareholding pattern's inline XBRL -> the plain facts NSE's XBRL parsers
  read (ixbrl_facts), so promoter %, pledge and the promoter-group members
  come from the same code for both exchanges.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

import pandas as pd

from collectors.nse_events.parsers import BM_COLUMNS, CA_COLUMNS, SAST_COLUMNS, SH_COLUMNS, action_purpose
from insiders_clean.dates import parse_dates
from insiders_clean.entities import entity_display, entity_key
from insiders_clean.history import BSE_DEALS_SOURCE as DEALS_SOURCE
from insiders_clean.history import BSE_INSIDER_SOURCE as INSIDER_SOURCE
_EMPTY = {'', '-', 'NA', 'N.A.', 'None', 'null'}


def _clean(v) -> str:
    s = '' if v is None else str(v).strip()
    return '' if s in _EMPTY else s


def _gf(row: dict, *keys) -> str:
    """scripts/bse_raw_capture_v2.py::gf: first non-empty value, as text."""
    for k in keys:
        v = str(row.get(k, '') or '').strip()
        if v and v.lower() not in ('none', 'null', ''):
            return v
    return ''


def _id(*parts) -> str:
    return hashlib.sha1('|'.join('' if p is None else str(p).strip() for p in parts).encode()).hexdigest()[:20]


def _num(v):
    s = _clean(v).replace(',', '')
    try:
        return float(s) if s else None
    except ValueError:
        return None


def _raw(r: dict) -> str:
    return json.dumps(r, ensure_ascii=False, sort_keys=True, default=str)


# --- insider (SEBI PIT) CSV ------------------------------------------------------

# BSE's CSV header (whitespace collapsed, lower case) -> field. The first
# sixteen are the nightly row's own names (bse_validate.normalize); the rest
# are what the CSV adds: the to-date, the intimation date, % before and after.
INSIDER_FIELDS = {
    'security code': 'security_code',
    'security name': 'company',
    'name of person': 'person',
    'category of person': 'person_category',
    'number of securities held prior to acquisition/disposed': 'holding_before',
    'type of securities acquired/disposed/pledge etc.': 'security_type',
    'number of securities acquired/disposed/pledge etc.': 'quantity',
    'value of securities acquired/disposed/pledge etc': 'transaction_value',
    'transaction type ( buy/sale/pledge/revoke/invoke)': 'transaction_type',
    'number of securities held post acquisition/disposed/pledge etc': 'holding_after',
    'date of acquisition of shares/sale of shares/date of allotment(from date)': 'transaction_date',
    'mode of acquisition': 'mode',
    'trading in derivative - type of contract': 'trading_in_derivatives',
    'derivatives - buy value (notional)': 'buy_value',
    'derivatives - sales value (notional)': 'sell_value',
    'reported to exchange': 'broadcast_date',
    'date of acquisition of shares/sale of shares/date of allotment( to date )': 'transaction_date_to',
    'date of intimation to company': 'intimation_date',
    'type of securities held prior to acquisition/disposed)': 'security_type_prior',
    '% of securities held prior to acquisition/disposed': 'pct_before',
    'type of securities held post acquisition/disposed/pledge etc': 'security_type_post',
    'post-transaction % of shareholding': 'pct_after',
    'derivative contract specification': 'derivative_specification',
    'derivatives - buy-number of units(contracts*lot size)': 'buy_units',
    'derivatives - sales-number of units(contracts * lot size)': 'sell_units',
    'exchange on which the trade was executed': 'trade_exchange',
}
INSIDER_REQUIRED = ('security_code', 'person', 'quantity', 'transaction_type', 'transaction_date', 'broadcast_date')


def _header(h) -> str:
    return re.sub(r'\s+', ' ', str(h or '').replace('﻿', '')).strip().lower()


def transaction_type(raw: str) -> str:
    """As the nightly parser (bse_raw_capture_v2.insider_row) reads it, except
    that an empty type stays empty (the nightly writes ACQUISITION)."""
    t = raw.upper()
    if 'ACQUI' in t or 'BUY' in t or 'PURCHASE' in t:
        return 'ACQUISITION'
    if 'DISP' in t or 'SELL' in t or 'SALE' in t:
        return 'DISPOSAL'
    return t


def insider_rows(csv_bytes: bytes) -> list[dict]:
    """BSE's insider CSV -> nightly-shaped BSE insider rows. Unknown columns
    are kept under `bse_<header>`, so nothing is lost if BSE adds one."""
    reader = csv.DictReader(io.StringIO(csv_bytes.decode('utf-8-sig', errors='replace')))
    fields = {h: INSIDER_FIELDS.get(_header(h), 'bse_' + re.sub(r'[^a-z0-9]+', '_', _header(h)).strip('_'))
              for h in reader.fieldnames or []}
    missing = [f for f in INSIDER_REQUIRED if f not in fields.values()]
    if missing:
        raise ValueError(f'BSE insider CSV without {missing}: header {reader.fieldnames}')
    out = []
    for r in reader:
        row = {fields[h]: _clean(v) for h, v in r.items() if h in fields}
        if not row.get('security_code'):
            continue
        row['transaction_type'] = transaction_type(row.get('transaction_type', ''))
        out.append(row)
    return out


# --- bulk / block deals history ------------------------------------------------------

def deal_rows(rows: list[dict]) -> list[dict]:
    """BulkDealData_ng rows -> exactly the nightly BSE deal row
    (bse_validate.normalize(bulk_block_row(r))): the history form writes the
    date as ISO, the name as `scripname` and a buy as 'P'; the nightly form
    (BulkDeal_Beta) writes DD/MM/YYYY, `ScripName` and 'B'. Checked on 09 Oct
    2026 (72 bulk deals) and 08 Oct 2026 (30 block deals): every row equal."""
    out = []
    for r in rows or []:
        raw_date = str(r.get('DEAL_DATE') or '').strip()
        try:
            day = datetime.fromisoformat(raw_date[:19]).strftime('%d/%m/%Y')
        except ValueError:
            day = raw_date
        side = str(r.get('TRANSACTION_TYPE') or '').strip().upper()
        side = {'P': 'B'}.get(side, side)
        nightly = dict(r, DEAL_DATE=day, ScripName=r.get('ScripName') or r.get('scripname'), TRANSACTION_TYPE=side)
        x = [_gf(nightly, 'DEAL_DATE', 'DealDate'), _gf(nightly, 'SCRIP_CODE', 'ScripCode'),
             _gf(nightly, 'ScripName', 'SCRIP_NAME'), _gf(nightly, 'CLIENT_NAME', 'ClientName'),
             _gf(nightly, 'TRANSACTION_TYPE', 'TransactionType'), _gf(nightly, 'QUANTITY', 'Qty'),
             _gf(nightly, 'PRICE', 'Price')]
        t = [re.sub(r'\s+', ' ', v.strip()) for v in x]
        out.append({'event_date': t[0], 'security_code': t[1], 'security_name': t[2], 'company': t[2],
                    'person': t[3], 'side': {'B': 'BUY', 'S': 'SELL'}.get(t[4].upper(), t[4].upper()),
                    'quantity': t[5], 'price': t[6], 'raw': x})
    return out


# --- SAST ----------------------------------------------------------------------------

BSE_SAST_COLUMNS = SAST_COLUMNS + ['exchange', 'bse_code', 'diluted_post_pct']
SAST_KEPT = {'29(1)': 'Reg29(1)', '29(2)': 'Reg29(2)'}  # NSE's own spelling


def sast_event_id(r: dict) -> str:
    # Company_Name is left out: BSE appends '-$' to it on some days.
    return _id('bse_sast', r.get('scrip_code'), r.get('shareholdername'), r.get('Acquisition_date'),
               r.get('Acq_Sale'), r.get('Acq_sale_qty'), r.get('Acquisition_After'), str(r.get('flag') or '').strip(),
               r.get('NEWDT'))


def parse_sast(rows: list[dict]) -> tuple[pd.DataFrame, dict]:
    """(Reg 29(1) and 29(2) disclosures, counts). BSE's list also holds
    Reg 10(5)/10(6) exemption reports and Reg 31 encumbrance notes; those are
    dropped and counted by regulation."""
    out, dropped = [], {}
    for r in rows or []:
        reg = str(r.get('flag') or '').strip()
        if reg not in SAST_KEPT:
            dropped[reg or 'blank'] = dropped.get(reg or 'blank', 0) + 1
            continue
        dates = re.findall(r'\d{1,2}/\d{1,2}/\d{4}', str(r.get('Acquisition_date') or ''))
        side = str(r.get('Acq_Sale') or '').strip().upper()
        acq, sale = side.startswith('ACQ'), side.startswith('SAL')
        qty, pct = _num(r.get('Acq_sale_qty')), _num(r.get('Acq_sale_Pct'))
        mode = _clean(r.get('FLD_MODE')) or None
        out.append({
            'event_id': sast_event_id(r),
            'symbol': _clean(r.get('scrip_code')) or None,
            'bse_code': _clean(r.get('scrip_code')) or None,
            'company': re.sub(r'\s*-\$\s*$', '', _clean(r.get('Company_Name'))) or None,
            'acquirer_name': entity_display(r.get('shareholdername')),
            'acquirer_id': entity_key(r.get('shareholdername')),
            'is_promoter': str(r.get('Fld_NameOfPG') or '').strip().upper() in ('YES', 'Y'),
            'regulation': SAST_KEPT[reg],
            'action_type': 'Acquisition' if acq else 'Sale' if sale else (_clean(r.get('Acq_Sale')).title() or None),
            'mode': mode,
            'is_market': (mode or '').strip().lower() in ('market', 'open market'),
            'trade_date_from': dates[0] if dates else None,
            'trade_date_to': dates[-1] if dates else None,
            'shares_acquired': qty if acq else None,
            'shares_sold': qty if sale else None,
            'shares_after': _num(r.get('Acquisition_After')),
            'pct_acquired': pct if acq else None,
            'pct_sold': pct if sale else None,
            'post_stake_pct': _num(r.get('Acquisition_Pct_After')),
            'diluted_post_pct': _num(r.get('Fld_TotDilPerAfterAcq')),
            'broadcast_ts': _clean(r.get('NEWDT')) or None,  # BSE gives the day only
            'application_no': None,
            'attachment': None,
            'exchange': 'BSE',
            'raw_json': _raw(r),
        })
    df = pd.DataFrame(out, columns=BSE_SAST_COLUMNS) if out else pd.DataFrame(columns=BSE_SAST_COLUMNS)
    for c in ('trade_date_from', 'trade_date_to'):
        df[c] = parse_dates(df[c])
    for c in ('shares_acquired', 'shares_sold', 'shares_after', 'pct_acquired', 'pct_sold', 'post_stake_pct',
              'diluted_post_pct'):
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df['target_company'] = df['company']
    df['transaction_date'] = df['trade_date_to']
    has_qty = df['shares_acquired'].notna() | df['shares_sold'].notna()
    has_pct = df['pct_acquired'].notna() | df['pct_sold'].notna()
    df['shares_traded'] = (df['shares_acquired'].fillna(0) - df['shares_sold'].fillna(0)).where(has_qty)
    df['percent_equity_traded'] = (df['pct_acquired'].fillna(0) - df['pct_sold'].fillna(0)).where(has_pct)
    # One disclosure can come back twice in one answer (and once per window
    # tile): kept once.
    return df[BSE_SAST_COLUMNS].drop_duplicates('event_id'), {'dropped_other_regulations': dropped}


# --- corporate actions -------------------------------------------------------------

BSE_CA_COLUMNS = CA_COLUMNS + ['exchange', 'bse_code']


def parse_actions(rows: list[dict]) -> tuple[pd.DataFrame, int]:
    """(kept actions, number dropped), on NSE's purposes: buyback, bonus,
    split, rights, dividend. BSE writes 'Final Dividend - Rs. - 5.0000',
    'Bonus issue 1:2', 'Stock  Split From Rs.5/- to Rs.1/-', 'Right Issue of
    Equity Shares' (no ratio or price), 'Buy Back of Shares'."""
    out, dropped = [], 0
    for r in rows or []:
        subject = re.sub(r'\s+', ' ', str(r.get('Purpose') or '')).strip()
        purpose = action_purpose(subject)
        if purpose is None:
            dropped += 1
            continue
        ratio = re.search(r'(\d+)\s*:\s*(\d+)', subject)
        fv = re.search(r'from\s+rs\.?\s*(\d+(?:\.\d+)?).*?to\s+rs\.?\s*(\d+(?:\.\d+)?)', subject, re.IGNORECASE)
        div = re.search(r'rs\.?\s*-?\s*(\d+(?:\.\d+)?)', subject, re.IGNORECASE)
        code = _clean(r.get('scrip_code')) or None
        out.append({
            'event_id': _id('bse_ca', code, subject, r.get('Ex_date'), r.get('RD_Date')),
            'symbol': code, 'bse_code': code, 'isin': None,
            'company': _clean(r.get('long_name')) or _clean(r.get('short_name')) or None,
            'series': None, 'purpose': purpose, 'subject': subject,
            'ex_date': _clean(r.get('Ex_date')) or None, 'record_date': _clean(r.get('RD_Date')) or None,
            'ratio': f'{ratio.group(1)}:{ratio.group(2)}' if ratio and purpose in ('bonus', 'rights') else None,
            'face_value': None, 'rights_premium': None, 'rights_issue_price': None,
            'dividend_per_share': float(div.group(1)) if div and purpose == 'dividend' else None,
            'face_value_from': float(fv.group(1)) if fv and purpose == 'split' else None,
            'face_value_to': float(fv.group(2)) if fv and purpose == 'split' else None,
            'needs_price_gap': purpose in ('buyback', 'rights'),
            'broadcast_date': None, 'exchange': 'BSE', 'raw_json': _raw(r),
        })
    df = pd.DataFrame(out, columns=BSE_CA_COLUMNS) if out else pd.DataFrame(columns=BSE_CA_COLUMNS)
    for c in ('ex_date', 'record_date', 'broadcast_date'):
        df[c] = parse_dates(df[c])
    return df.drop_duplicates('event_id'), dropped


# --- board meetings --------------------------------------------------------------

BSE_BM_COLUMNS = BM_COLUMNS + ['exchange', 'bse_code', 'moved']
# BSE's purpose list (Corp_GetBoardPurposeMaster_ng, 27 names on 12 Oct 2026)
# -> NSE's flags. It has no fund-raising name: a meeting on a QIP or another
# raise is filed as 'General', so `fund_raising` stays false on BSE rows unless
# the purpose says so. 'Issue Of Warrants' counts as preferential (warrants are
# allotted preferentially, ICDR Chapter V); a rights issue of NCDs is not an
# equity rights issue.
BM_FLAGS = {
    'results': r'results',
    'dividend': r'^(interim |final |special )?dividend$',
    'buyback': r'buy\s*-?\s*back',
    'bonus': r'bonus',
    'fund_raising': r'fund\s*-?\s*rais|\bqip\b|qualified\s+institution',
    'split': r'split|sub\s*-?\s*division',
    'rights': r'^rights?\s+issue(?!.*\bncd\b)',
    'preferential': r'preferential|^issue of warrants$',
}


def _bse_ts(v) -> str | None:
    """BSE writes the intimation time two ways: '2026-01-30T14:32:22.893'
    (Table) and 'Jan 30 2026  2:32PM' (Table1); both -> ISO, to the minute
    or finer."""
    s = re.sub(r'\s+', ' ', _clean(v))
    if not s:
        return None
    try:
        return datetime.strptime(s, '%b %d %Y %I:%M%p').isoformat()
    except ValueError:
        return s


def parse_board_meetings(payload: dict) -> tuple[pd.DataFrame, dict]:
    """(meetings that consider results, dividend, buyback, bonus, split,
    rights or a preferential issue, counts). `Table` rows are meetings as
    listed, one row a meeting; `Table1` rows, one a purpose, are dates a
    meeting was moved away from: kept with moved = true, so the clean step
    can drop the date they replace (insiders_clean/bse_events.py)."""
    out, dropped, moved_dates = [], 0, 0
    groups: dict = {}
    for moved, rows in ((False, (payload or {}).get('Table') or []), (True, (payload or {}).get('Table1') or [])):
        for r in rows:
            code, day = _clean(r.get('scrip_code')), _clean(r.get('MEETING_BOARD_DATE'))[:10]
            if not code or not day:
                dropped += 1
                continue
            g = groups.setdefault((moved, code, day), {'rows': [], 'purposes': []})
            g['rows'].append(r)
            g['purposes'] += [re.sub(r'\s+', ' ', p).strip() for p in str(r.get('PURPOSE_NAME') or '').split(';')]
    for (moved, code, day), g in groups.items():
        purposes = [p for p in dict.fromkeys(g['purposes']) if p]
        flags = {k: any(re.search(pat, p, re.IGNORECASE) for p in purposes) for k, pat in BM_FLAGS.items()}
        if not any(flags.values()):
            dropped += 1
            continue
        moved_dates += moved
        first = g['rows'][0]
        ts = max((_bse_ts(r.get('DT_TM')) or '' for r in g['rows']), default='') or None
        out.append({
            'event_id': _id('bse_bm_moved' if moved else 'bse_bm', code, day, ts if moved else None),
            'symbol': code, 'bse_code': code, 'isin': None,
            'company': re.sub(r'\s*-\$\s*$', '', _clean(first.get('Long_Name') or first.get('Long_name'))) or None,
            'meeting_date': day, **flags, 'purposes': ','.join(k for k in BM_FLAGS if flags[k]),
            'description': ' | '.join(purposes), 'intimation_ts': ts, 'exchange': 'BSE', 'moved': moved,
            'raw_json': _raw(first) if len(g['rows']) == 1 else '[' + ','.join(_raw(r) for r in g['rows']) + ']',
        })
    df = pd.DataFrame(out, columns=BSE_BM_COLUMNS) if out else pd.DataFrame(columns=BSE_BM_COLUMNS)
    df['meeting_date'] = parse_dates(df['meeting_date'])
    return df.drop_duplicates('event_id').reset_index(drop=True), {'dropped_other_purposes': dropped,
                                                                   'moved_dates': moved_dates}


# --- shareholding pattern ------------------------------------------------------------

BSE_SH_COLUMNS = SH_COLUMNS + ['exchange', 'bse_code', 'quarter_id']
XBRL_HOME = 'https://www.bseindia.com'


def parse_shareholding_listing(rows: list[dict]) -> pd.DataFrame:
    """Corp_Shareholding_ng rows -> NSE's shareholding listing columns. BSE's
    list holds no holdings: promoter and public % come from the XBRL
    (collectors/bse/events.py). `quarter_id` is BSE's quarter number; a
    fraction (129.01) marks a revised filing of that quarter, filed later. A
    row BSE marks IsXBRL 0 has no XBRL to read (xbrl_url blank)."""
    out = []
    for r in rows or []:
        code = _clean(r.get('FLD_ScripCode'))
        qid = str(r.get('nqtrid') or '').split('&', 1)[0].strip()
        att = _clean(r.get('XBRLAttachment'))
        has_xbrl = str(r.get('IsXBRL')).strip() == '1' and bool(att)
        out.append({
            'event_id': _id('bse_shp', code, qid, att, r.get('D')),
            'record_id': f'{code}:{qid}', 'symbol': code or None, 'bse_code': code or None, 'isin': None,
            'company': re.sub(r'\s*-\$\s*$', '', _clean(r.get('Company_NAme'))) or None,
            'quarter_end': _clean(r.get('EndDate'))[:10] or None,
            'submission_date': _clean(r.get('D')) or None,
            'promoter_holding_pct': None, 'public_holding_pct': None, 'employee_trust_pct': None,
            'revised': bool(re.search(r'\.\d*[1-9]\d*$', qid)),
            'xbrl_url': (XBRL_HOME + att if att.startswith('/') else att) if has_xbrl else None,
            'quarter_id': qid or None, 'exchange': 'BSE', 'raw_json': _raw(r),
        })
    df = pd.DataFrame(out, columns=BSE_SH_COLUMNS) if out else pd.DataFrame(columns=BSE_SH_COLUMNS)
    df['quarter_end'] = parse_dates(df['quarter_end'])
    df['submission_date'] = pd.to_datetime(df['submission_date'], errors='coerce')
    return df.drop_duplicates('event_id').reset_index(drop=True)


_IX_FACT = re.compile(r'<ix:(nonFraction|nonNumeric)\b([^>]*?)(?:/>|>(.*?)</ix:\1>)', re.S)
_IX_ATTR = re.compile(r"""([\w:]+)\s*=\s*(?:'([^']*)'|"([^"]*)")""")
_IX_CONTEXT = re.compile(r"""<xbrli:context\b[^>]*?\bid\s*=\s*['"]([^'"]+)['"]""")


def ixbrl_facts(text: str) -> str:
    """BSE's inline-XBRL shareholding pattern -> one plain fact a line, as in
    the XBRL NSE serves (`<in-bse-shp:Tag contextRef="ctx">value</...>`), plus
    each context id, so collectors/nse_events/parsers.parse_shp_xbrl and
    parse_shp_members read it unchanged. Numbers are the stored value: the
    figure shown times 10^scale (BSE shows 94.04 with scale -2 where NSE's
    XML holds 0.9404), negative with sign='-', commas dropped. Checked on 4
    filings of 12 Oct 2026 (Valencia Nutrition, Netripples Software, Cantabil
    Retail, Utique Enterprises; taxonomy 2025-10-31): each promoter-group
    member list adds up to its promoter total."""
    out = [f'<xbrli:context id="{c}"/>' for c in _IX_CONTEXT.findall(text)]
    for kind, attrs, body in _IX_FACT.findall(text):
        a = {k: v1 or v2 for k, v1, v2 in _IX_ATTR.findall(attrs)}
        name, ctx = a.get('name', ''), a.get('contextRef', '')
        if not name.startswith('in-bse-shp:') or not ctx:
            continue
        v = re.sub(r'<[^>]+>', '', body or '').strip()
        if kind == 'nonFraction' and v:
            try:
                d = Decimal(v.replace(',', '')).scaleb(int(a.get('scale') or 0))
            except (InvalidOperation, ValueError):
                continue
            d = -d if a.get('sign') == '-' else d
            v = str(int(d)) if d == d.to_integral() else format(d.normalize(), 'f')
        out.append(f'<{name} contextRef="{ctx}">{v}</{name}>')
    return '\n'.join(out)
