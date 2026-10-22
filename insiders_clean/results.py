"""Quarterly and annual financial results as companies file them with NSE, read from their XBRL (no model).

Source (confirmed 15 Oct 2026, scripts/results_xbrl_probe.py): NSE's integrated filing of financials,
/api/integrated-filing-results?index=equities&from_date=&to_date=&type=Integrated Filing- Financials, pages of
`size` rows ({'data', 'size', 'page', 'totalCount'}). Each row is one filing: symbol, company, quarter end
(qe_Date), audited or not, standalone or consolidated, Original or Revision (with its date and remark), and links
to the XBRL instance (`xbrl`), its iXBRL page (`ixbrl`) and a PDF (`pdf_attach`, often '.../corporate/null': none).
The XBRL file name names its layout: INDAS (companies), NBFC_INDAS, BANKING, GI and LI (insurers).

The XBRL holds the filing's own identity (ISIN, BSE code, symbol), its periods and every line it reports: the
quarter (a duration context matching DateOfStart/EndOfReportingPeriod), the year to date (a longer duration ending
on the same day) and balance-sheet instants. Values are rupees as filed (the `decimals` attribute says how they
were rounded). The file has no prior-year quarter: year-on-year comparisons come from our own history.

Kept as filed: every fact in `xbrl_json`; a few lines that the INDAS layout names (SUMMARY) as columns, blank
where a layout (banks, insurers) names them otherwise. Nothing is derived or guessed here.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from datetime import timedelta, timezone

import pandas as pd

IST = timezone(timedelta(hours=5, minutes=30))
TYPE = 'Integrated Filing- Financials'
FILING_COLUMNS = ['event_id', 'seq_id', 'symbol', 'company', 'period_end', 'audited', 'consolidated', 'revision',
                  'revised_at', 'revision_remark', 'broadcast_at', 'broadcast_date', 'kind', 'xbrl_url', 'ixbrl_url',
                  'pdf_url', 'xbrl_status', 'xbrl_json']
# INDAS names of the lines kept as columns (quarter_ and ytd_ prefixed); other layouts keep them in xbrl_json.
SUMMARY = {'revenue': 'RevenueFromOperations', 'other_income': 'OtherIncome', 'total_income': 'Income',
           'total_expenses': 'Expenses', 'finance_costs': 'FinanceCosts',
           'depreciation': 'DepreciationDepletionAndAmortisationExpense',
           'profit_before_exceptional_and_tax': 'ProfitBeforeExceptionalItemsAndTax',
           'exceptional_items': 'ExceptionalItemsBeforeTax', 'profit_before_tax': 'ProfitBeforeTax',
           'tax': 'TaxExpense', 'profit': 'ProfitLossForPeriod',
           'profit_owners': 'ProfitOrLossAttributableToOwnersOfParent',
           'eps_basic': 'BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations',
           'eps_diluted': 'DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations'}
META = {'isin': 'ISIN', 'bse_code': 'ScripCode', 'xbrl_symbol': 'Symbol', 'rounding': 'LevelOfRounding',
        'reporting_quarter': 'ReportingQuarter', 'period_type': 'TypeOfReportingPeriod',
        'period_start': 'DateOfStartOfReportingPeriod', 'board_meeting': 'DateOfBoardMeetingWhenFinancialResultsWereApproved',
        'audit_opinion': 'DeclarationOfUnmodifiedOpinionOrStatementOnImpactOfAuditQualification',
        'segments': 'IsCompanyReportingMultisegmentOrSingleSegment'}


def _text(v):
    return v.strip() if isinstance(v, str) and v.strip() and v.strip().lower() not in ('null', '-') else None


def _link(v):
    """An NSE link, or None for its 'no file' forms ('.../corporate/null', '.../corporate/-', null)."""
    v = _text(v)
    if not v or not v.lower().startswith('http'):
        return None
    last = v.rstrip('/').rsplit('/', 1)[-1]
    return None if last.lower() in ('', '-', 'null') else v


def _ist(v) -> pd.Timestamp | None:
    t = pd.to_datetime(_text(v), errors='coerce', format='mixed', dayfirst=True)
    return None if pd.isna(t) else (t.tz_localize(IST) if t.tzinfo is None else t.tz_convert(IST))


def kind_of(url) -> str | None:
    """'INDAS', 'NBFC_INDAS', 'BANKING', 'GI', 'LI' ... from INTEGRATED_FILING_{kind}_{id}_{stamp}_WEB.xml."""
    m = re.search(r'INTEGRATED_FILING_([A-Z_]+?)_\d+_\d+', str(url or ''))
    return m.group(1) if m else None


def filing_rows(rows: list[dict]) -> pd.DataFrame:
    """One row per filing as NSE lists it; broadcast_at is NSE's broadcast time, else the filing's creation time."""
    out = []
    for r in rows or []:
        seq = _text(str(r.get('seq_Id') or ''))
        if not seq:
            continue
        at = _ist(r.get('broadcast_Date')) or _ist(r.get('creation_Date'))
        qe = pd.to_datetime(_text(r.get('qe_Date')), errors='coerce', format='mixed', dayfirst=True)
        revised = _ist(r.get('revised_Date'))
        xbrl = _link(r.get('xbrl'))
        out.append({'event_id': f'nse:result:{seq}', 'seq_id': seq, 'symbol': _text(r.get('symbol')),
                    'company': _text(r.get('smName')) or _text(r.get('cmName')),
                    'period_end': None if pd.isna(qe) else qe.date().isoformat(),
                    'audited': _text(r.get('audited')), 'consolidated': _text(r.get('consolidated')),
                    'revision': _text(r.get('type_Sub')), 'revised_at': revised.isoformat() if revised is not None else None,
                    'revision_remark': _text(r.get('revision_Remark')),
                    'broadcast_at': at.isoformat() if at is not None else None,
                    'broadcast_date': at.date().isoformat() if at is not None else None,
                    'kind': kind_of(xbrl), 'xbrl_url': xbrl, 'ixbrl_url': _link(r.get('ixbrl')),
                    'pdf_url': _link(r.get('pdf_attach')), 'xbrl_status': None, 'xbrl_json': None})
    return pd.DataFrame(out, columns=FILING_COLUMNS)


def parse_xbrl(xml) -> dict:
    """{'contexts': {id: {'start','end' or 'instant', 'dimension': bool}}, 'facts': {context: {name: value}},
    'units': {name: unit}}. Numbers become floats, the rest stays text. Raises ValueError when there are no facts."""
    if isinstance(xml, bytes):
        xml = xml.decode('utf-8', errors='replace')
    root = ET.fromstring(re.sub(r'^\s*<\?xml[^>]*\?>', '', xml.lstrip('﻿')))
    contexts, facts, units = {}, {}, {}
    for el in root:
        tag = el.tag.split('}')[-1]
        if tag == 'context':
            period = {c.tag.split('}')[-1]: (c.text or '').strip() for c in el.iter()
                      if c.tag.split('}')[-1] in ('startDate', 'endDate', 'instant')}
            contexts[el.get('id')] = {'start': period.get('startDate'), 'end': period.get('endDate') or period.get('instant'),
                                      'instant': 'instant' in period,
                                      'dimension': any(c.tag.split('}')[-1] == 'explicitMember' for c in el.iter())}
            continue
        ctx = el.get('contextRef')
        value = (el.text or '').strip()
        if ctx is None or value == '':
            continue
        if el.get('unitRef'):
            try:
                value = float(value)
            except ValueError:
                pass
            units[tag] = el.get('unitRef')
        facts.setdefault(ctx, {})[tag] = value
    if not facts:
        raise ValueError('no facts in results XBRL')
    return {'contexts': contexts, 'facts': facts, 'units': units}


def periods(parsed: dict) -> tuple[str | None, str | None]:
    """(quarter context, year-to-date context): plain durations (no dimension) that report a period end. The
    quarter is the one starting latest among those ending on the latest end; the year to date the one starting
    earliest, when it starts earlier than the quarter."""
    ctx, facts = parsed['contexts'], parsed['facts']
    plain = [(k, c) for k, c in ctx.items() if not c['instant'] and not c['dimension'] and c['start'] and c['end']
             and 'DateOfEndOfReportingPeriod' in facts.get(k, {})]
    if not plain:
        return None, None
    end = max(c['end'] for _, c in plain)
    same = sorted([(k, c) for k, c in plain if c['end'] == end], key=lambda kc: kc[1]['start'])
    quarter, first = same[-1][0], same[0]
    return quarter, (first[0] if first[1]['start'] < same[-1][1]['start'] else None)


def summary(parsed: dict) -> dict:
    """The filing's identity and the SUMMARY lines for the quarter and the year to date (blank when not filed
    under those names)."""
    quarter, ytd = periods(parsed)
    facts = parsed['facts']
    meta = facts.get(quarter, {}) if quarter else {}
    out = {k: (v if isinstance(v := meta.get(t), str) else None) for k, t in META.items()}
    out['period_end_xbrl'] = meta.get('DateOfEndOfReportingPeriod')
    for prefix, ctx in (('quarter', quarter), ('ytd', ytd)):
        row = facts.get(ctx, {}) if ctx else {}
        for name, tag in SUMMARY.items():
            v = row.get(tag)
            out[f'{prefix}_{name}'] = v if isinstance(v, float) else None
    out['ytd_start'] = parsed['contexts'][ytd]['start'] if ytd else None
    return out


def clean(filings: pd.DataFrame) -> pd.DataFrame:
    """The site's table: one row per filing with its summary, newest first; xbrl_json stays in the archive."""
    if filings is None or filings.empty:
        return pd.DataFrame()
    rows = []
    for r in filings.to_dict('records'):
        s = {}
        if r.get('xbrl_status') == 'ok' and r.get('xbrl_json'):
            try:
                s = summary(json.loads(r['xbrl_json']))
            except (ValueError, KeyError, TypeError):
                s = {}
        rows.append({**{k: v for k, v in r.items() if k != 'xbrl_json'}, **s})
    out = pd.DataFrame(rows).sort_values('broadcast_at', ascending=False, na_position='last').reset_index(drop=True)
    return mark_superseded(out)


def mark_superseded(df: pd.DataFrame) -> pd.DataFrame:
    """`superseded`: a later filing of the same company, period end and basis (standalone or consolidated) was
    broadcast, a revision mostly (audit 22 Oct: 1,639 rows share a company, period and basis, 891 of them
    revisions; HCL Tech's 31 Mar 2026 standalone result was listed twice on the Company page). Kept, not dropped:
    a card dated before the revision still reads the filing it could have seen (insiders_clean/context.py)."""
    df = df.copy()
    if df.empty or not {'symbol', 'period_end', 'consolidated', 'broadcast_at'} <= set(df.columns):
        df['superseded'] = False
        return df
    at = pd.to_datetime(df['broadcast_at'], errors='coerce', utc=True)
    key = [df['symbol'].astype(str).str.upper(), df['period_end'].astype(str),
           df['consolidated'].astype(str).str.strip().str.lower()]
    latest = at.groupby(key).transform('max')
    df['superseded'] = (at < latest).fillna(False).astype(bool)
    return df
