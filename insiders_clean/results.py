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
where a layout (banks, insurers) names them otherwise. Revenue and profit are read under each layout's own names
(TOP_LINE, PROFIT; 20 Nov 2026) and the revenue line says which one it is (`revenue_basis`). Nothing is derived or
guessed here.
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
                  'pdf_url', 'xbrl_size', 'xbrl_status', 'xbrl_json']
# 15 Nov 2026: NSE's listing gives each file's size; "0 Bytes" means NSE published no XBRL for that filing (Adani Green,
# UPL standalone, Apr-May 2026: their link answers HTTP 404). Such a filing is `no_xbrl_at_nse`, not fetched. A link
# that answers HTTP 404 is `no_xbrl_at_nse` too (older listings give no size: L&T's FY25 revisions, Jul 2025).
NO_FILE = 'no_xbrl_at_nse'


def nse_has_no_file(size) -> bool:
    return isinstance(size, str) and size.strip().lower() in ('0 bytes', '0 kb', '0')
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
# Revenue and profit under each layout's own names (20 Nov 2026, scripts/clean_peek.py RESULTS_TAGS on the 2026
# archive: HDFC Bank, SBI, ICICI Bank, Kotak (BANKING), Bajaj Finance (NBFC_INDAS), LIC, HDFC Life (LI), ICICI Lombard
# (GI)). The Results page showed "No revenue line" for banks and insurers: they file no RevenueFromOperations.
#   INDAS, NBFC_INDAS: RevenueFromOperations (Schedule III; NBFCs' Division III includes interest earned in it, Bajaj
#     Finance Sep 2026 standalone Rs 20,890.66 Cr), profit ProfitLossForPeriod.
#   NONINDAS (old Indian GAAP layout, 24 companies in 2026): RevenueFromOperations, profit ProfitLossForThePeriod.
#   BANKING: `Income`, the bank's total income = InterestEarned + OtherIncome (HDFC Bank Sep 2026 standalone:
#     83,426.60 + 13,831.02 = 97,257.62 Cr), chosen over InterestEarned alone because a bank's fees, commissions and
#     treasury income are its operations too and the banks' own segment note reports this figure as revenue from
#     operations (SegmentRevenueFromOperations = Income in every bank read). Profit ProfitLossForThePeriod (net
#     profit after tax, before minority interest, as ProfitLossForPeriod is for companies); owners' share
#     ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates.
#   LI (life insurers): NetPremiumIncome (premium net of reinsurance). Their `Income` adds investment income, which
#     swings with the market (LIC Sep 2026: Rs 1,14,983.77 Cr of investment income on Rs 1,47,018.18 Cr of net
#     premium), so it is not the top line. Profit ProfitLossAfterTaxAndExtraordinaryItems.
#   GI (general insurers): PremiumEarned (net premium earned), profit ProfitLossAfterTax.
#   INS_IND_AS (insurers filing under Ind AS 117, file IF_INS_COM_IND_AS_{id}_WebXMLFile_...xml): InsuranceRevenue
#     (21 Nov 2026, GODIGIT Sep 2026 quarter: InsuranceRevenue 27,204,900,000, all under the premium allocation
#     approach; investment income and finance results are reported separately). Profit ProfitLossForPeriod.
TOP_LINE = {'INDAS': ('ind_as_revenue', 'RevenueFromOperations'), 'NBFC_INDAS': ('ind_as_revenue', 'RevenueFromOperations'),
            'NONINDAS': ('igaap_revenue', 'RevenueFromOperations'), 'BANKING': ('bank_total_income', 'Income'),
            'LI': ('insurer_net_premium', 'NetPremiumIncome'), 'GI': ('insurer_premium_earned', 'PremiumEarned'),
            'INS_IND_AS': ('insurer_insurance_revenue', 'InsuranceRevenue')}
PROFIT = {'NONINDAS': 'ProfitLossForThePeriod', 'BANKING': 'ProfitLossForThePeriod',
          'LI': 'ProfitLossAfterTaxAndExtraordinaryItems', 'GI': 'ProfitLossAfterTax'}
PROFIT_OWNERS = {'BANKING': 'ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates'}
# What the site calls each basis (the revenue column is "Revenue" for companies).
BASIS_LABEL = {'ind_as_revenue': 'Revenue', 'igaap_revenue': 'Revenue', 'bank_total_income': 'Total income (bank)',
               'insurer_net_premium': 'Net premium (life insurer)',
               'insurer_premium_earned': 'Net premium earned (general insurer)',
               'insurer_insurance_revenue': 'Insurance revenue (Ind AS 117 insurer)'}


def basis_label(basis) -> str:
    return BASIS_LABEL.get(basis, 'Revenue') if isinstance(basis, str) else 'Revenue'


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
    if m:
        return m.group(1)
    return 'INS_IND_AS' if re.search(r'IF_INS_COM_IND_AS_\d+', str(url or '')) else None


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
                    'pdf_url': _link(r.get('pdf_attach')), 'xbrl_size': _text(r.get('xbrlFileSize')),
                    'xbrl_status': None, 'xbrl_json': None})
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
    # A filing that reports only a half year or a full year has no quarter (13 Nov 2026: Emami's Sep 2026 consolidated
    # filing, IFIndAs V2.1, TypeOfReportingPeriod "Half Yearly", one context 1 Apr - 30 Sep; read as the quarter it
    # showed revenue +166% on the Sep 2025 quarter). The latest-starting context counts as the quarter only when it
    # spans about three months; otherwise it is the year to date and the quarter is blank.
    if _days(same[-1][1]) > QUARTER_MAX_DAYS:
        return None, quarter
    return quarter, (first[0] if first[1]['start'] < same[-1][1]['start'] else None)


QUARTER_MAX_DAYS = 100


def same_period(parsed: dict, ctx: str | None) -> dict:
    """The facts of `ctx` and of every other plain context (no dimension, not an instant) with the same start and
    end. Audit 21 Nov 2026: 43 Ind AS and 8 NBFC Sep 2026 filings (AAREYDRUGS, AFIL, AMANTA, HDBFS, KALAMANDIR ...)
    put DateOfEndOfReportingPeriod in a metadata context (StatementStatic1D) and their statement lines in another
    context for the same quarter, so revenue and profit read blank. A value filed in `ctx` itself wins."""
    if not ctx:
        return {}
    ctxs, facts = parsed['contexts'], parsed['facts']
    c = ctxs.get(ctx) or {}
    out = {}
    for k, o in ctxs.items():
        if k != ctx and not o.get('instant') and not o.get('dimension') and o.get('start') == c.get('start') \
                and o.get('end') == c.get('end'):
            for tag, v in facts.get(k, {}).items():
                out.setdefault(tag, v)
    return {**out, **facts.get(ctx, {})}


def _days(c: dict) -> int:
    try:
        return (pd.Timestamp(c['end']) - pd.Timestamp(c['start'])).days
    except (TypeError, ValueError):
        return 0


def summary(parsed: dict, kind: str | None = None) -> dict:
    """The filing's identity and the SUMMARY lines for the quarter and the year to date (blank when not filed
    under those names); revenue and profit under the layout's own names (TOP_LINE, PROFIT), `revenue_basis` naming
    the revenue line (blank when the filing has none)."""
    quarter, ytd = periods(parsed)
    facts = parsed['facts']
    # the identity is on the quarter, or on the year to date when the filing has no quarter (a half year): its ISIN
    # and codes are needed either way (13 Nov 2026)
    home = quarter or (ytd if 'ISIN' in facts.get(ytd, {}) else next((k for k, f in facts.items() if 'ISIN' in f), ytd))
    meta = facts.get(home, {}) if home else {}
    out = {k: (v if isinstance(v := meta.get(t), str) else None) for k, t in META.items()}
    out['period_end_xbrl'] = meta.get('DateOfEndOfReportingPeriod')
    basis, top_tag = TOP_LINE.get(kind, TOP_LINE['INDAS'])
    for prefix, ctx in (('quarter', quarter), ('ytd', ytd)):
        row = same_period(parsed, ctx)
        tags = {**SUMMARY, 'revenue': top_tag, 'profit': PROFIT.get(kind, SUMMARY['profit']),
                'profit_owners': PROFIT_OWNERS.get(kind, SUMMARY['profit_owners'])}
        for name, tag in tags.items():
            v = row.get(tag)
            out[f'{prefix}_{name}'] = v if isinstance(v, float) else None
    out['revenue_basis'] = basis if out['quarter_revenue'] is not None or out['ytd_revenue'] is not None else None
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
                s = summary(json.loads(r['xbrl_json']), r.get('kind') or kind_of(r.get('xbrl_url')))
            except (ValueError, KeyError, TypeError):
                s = {}
        rows.append({**{k: v for k, v in r.items() if k != 'xbrl_json'}, **s})
    out = pd.DataFrame(rows).sort_values('broadcast_at', ascending=False, na_position='last').reset_index(drop=True)
    out['ytd_disagrees'] = ytd_disagrees(out)
    return derive_quarters(mark_superseded(out))


# Lines that add up over periods (EPS does not: the share count changes), so a quarter is the year to date less the
# year to date before it.
ADDITIVE = [k for k in SUMMARY if not k.startswith('eps_')]


def derive_quarters(df: pd.DataFrame) -> pd.DataFrame:
    """A filing that reports only its year to date (a half year, R13) gets its quarter as that year to date less the
    company's previous filing on the same basis that covers the same year to the quarter before: its own year to date,
    or its quarter when that quarter starts the year (Emami: 1 Apr - 30 Sep less 1 Apr - 30 Jun is the Sep quarter).
    Marked `quarter_derived` (the site says so); left blank where the earlier filing is missing, superseded only,
    or its end is not about three months before. EPS is not derived."""
    df = df.copy()
    df['quarter_derived'] = False
    need = {'symbol', 'consolidated', 'period_end', 'ytd_start', 'quarter_revenue', 'period_start'}
    if df.empty or not need <= set(df.columns):
        return df
    end = pd.to_datetime(df['period_end'], errors='coerce')
    ystart = pd.to_datetime(df['ytd_start'], errors='coerce')
    qstart = pd.to_datetime(df['period_start'], errors='coerce')
    blank = df[[f'quarter_{k}' for k in ADDITIVE]].isna().all(axis=1)
    todo = blank & ystart.notna() & end.notna() & ~df['ytd_disagrees'].astype('boolean').fillna(False)
    if not todo.any():
        return df
    live = ~df['superseded'].astype('boolean').fillna(False) if 'superseded' in df else pd.Series(True, index=df.index)
    basis = df['consolidated'].astype(str).str.strip().str.lower()
    # and the same revenue line (results.TOP_LINE): a bank's total income is never set against a company revenue
    top = df['revenue_basis'].fillna('').astype(str) if 'revenue_basis' in df else pd.Series('', index=df.index)
    sym = df['symbol'].astype(str).str.upper()
    for i in df.index[todo]:
        lo, hi = end[i] - pd.Timedelta(days=95), end[i] - pd.Timedelta(days=85)
        cand = df.index[live & (sym == sym[i]) & (basis == basis[i]) & (top == top[i]) & end.between(lo, hi)]
        prior = None
        for j in cand:
            if ystart[j] == ystart[i]:
                prior = {k: df.at[j, f'ytd_{k}'] for k in ADDITIVE}
            elif pd.isna(ystart[j]) and qstart[j] == ystart[i]:
                prior = {k: df.at[j, f'quarter_{k}'] for k in ADDITIVE}
            if prior is not None:
                break
        if prior is None or pd.isna(prior.get('revenue')) or pd.isna(df.at[i, 'ytd_revenue']):
            continue
        for k in ADDITIVE:
            a, b = df.at[i, f'ytd_{k}'], prior.get(k)
            df.at[i, f'quarter_{k}'] = a - b if pd.notna(a) and pd.notna(b) else None
        df.at[i, 'quarter_derived'] = True
    return df


def ytd_disagrees(df: pd.DataFrame) -> pd.Series:
    """True where a filing's own figures cannot both be right: a quarter's revenue above the revenue of the
    longer year to date that contains it, both positive (audit 23 Oct: Repro India's Sep 2025 revision, Rs 107.8
    Cr for the quarter and Rs 22.5 Cr for six months; Sejal Glass, Dec 2025). A loss larger in the quarter than
    in the year (negative revenue, NBFCs' fair value losses) is no contradiction. Shown with a note, never fixed."""
    if df.empty or not {'quarter_revenue', 'ytd_revenue', 'ytd_start', 'period_end'} <= set(df.columns):
        return pd.Series(False, index=df.index)
    q = pd.to_numeric(df['quarter_revenue'], errors='coerce')
    y = pd.to_numeric(df['ytd_revenue'], errors='coerce')
    start = pd.to_datetime(df['ytd_start'], errors='coerce')
    end = pd.to_datetime(df['period_end'], errors='coerce')
    longer = (end - start).dt.days > 100   # more than a quarter: the year to date is not the quarter itself
    return (longer & q.gt(0) & y.gt(0) & (q > y * 1.001)).fillna(False).astype(bool)


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


PROFIT_OVER_REVENUE = 3.0   # a quarter's profit (or the year-ago one) over 3x its revenue is read as a unit or tagging error


def doubt_reason(rev, profit, profit_year, rev_yoy) -> str:
    """Why a results row's figures look wrong and are held back from rankings ('' when they look fine). Audit of
    19 Nov 2026 on the Results page: revenue -Rs 27.71 Cr (VLS), a year-ago profit of Rs 6,306 Cr on Rs 29 Cr of revenue
    (Supreme Infrastructure), profit Rs 1,092 Cr on Rs 50.59 Cr (Veranda) led the page. The row is shown under "held
    back" with this reason, never altered."""
    import math
    f = lambda v: v if isinstance(v, (int, float)) and not (isinstance(v, float) and math.isnan(v)) else None  # noqa: E731
    rev, profit, profit_year, rev_yoy = f(rev), f(profit), f(profit_year), f(rev_yoy)
    if rev is not None and rev < 0:
        return 'negative revenue'
    if rev is not None and rev > 0:
        for p_, what in ((profit, 'profit'), (profit_year, 'year-ago profit')):
            if p_ is not None and abs(p_) > PROFIT_OVER_REVENUE * rev:
                return f'{what} over {PROFIT_OVER_REVENUE:g}x revenue'
    if rev_yoy is not None and rev_yoy <= -99.5:
        return 'revenue fell to almost nothing'
    return ''
