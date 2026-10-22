"""Context for a card, computed from our own clean tables and never by a model (docs/ANNOUNCEMENT_READER.md, "Context on the
card"). Every figure carries its source and date; missing is shown as missing, never as zero.

Small real sample first (scripts/results_context_probe.py, 16 Oct 2026): results.parquet had 6,450 rows for 2,345 companies,
period_end from 2025-03-31, a median of one quarter a company and four or more for only 21 (the 12-quarter backfill is still
running), so a four-quarter sum is not possible yet. A March (fourth quarter) filing carries the full financial year in its
ytd_* columns for most companies, so the denominator used now is the last full financial year, named as such. Original and
revision rows both exist for a period; standalone and consolidated are separate rows.
"""
from __future__ import annotations

import pandas as pd


def _number(v):
    x = pd.to_numeric(v, errors='coerce')
    return float(x) if pd.notna(x) else None


def last_year(results: pd.DataFrame | None, isin, as_of) -> dict | None:
    """The last full financial year the company's March filing gives, as of a date: {'fy': 'FY26', 'revenue', 'profit',
    'basis', 'period_end'}; None when there is none. Consolidated before standalone, the latest revision of a period, revenue
    from operations else total income; a year of zero revenue is not used."""
    if results is None or results.empty or not isin or 'isin' not in results:
        return None
    r = results[results['isin'].astype(str).eq(str(isin))].copy()
    if r.empty:
        return None
    r['_end'] = pd.to_datetime(r['period_end'], errors='coerce')
    cut = pd.to_datetime(as_of, errors='coerce')
    r = r[(r['_end'].dt.month == 3) & r['_end'].notna()]
    if 'ytd_disagrees' in r:   # a filing whose quarter is above its own year: neither figure is taken (results.ytd_disagrees)
        r = r[~r['ytd_disagrees'].astype('boolean').fillna(False)]
    if pd.notna(cut):
        r = r[r['_end'] <= cut.tz_localize(None) if getattr(cut, 'tzinfo', None) else r['_end'] <= cut]
    if r.empty:
        return None
    r['_rev'] = [(_number(a) or 0) or (_number(b) or 0) for a, b in zip(r.get('ytd_revenue', pd.Series(dtype=float)),
                                                                          r.get('ytd_total_income', pd.Series(dtype=float)))] \
        if len(r) else []
    r = r[r['_rev'] > 0]
    if r.empty:
        return None
    r['_cons'] = r['consolidated'].astype(str).str.lower().eq('consolidated')
    r['_at'] = pd.to_datetime(r.get('broadcast_at'), errors='coerce', utc=True)
    best = r.sort_values(['_end', '_cons', '_at']).iloc[-1]
    end = best['_end']
    return {'fy': f'FY{end.year % 100:02d}', 'revenue': float(best['_rev']), 'profit': _number(best.get('ytd_profit')),
            'basis': 'consolidated' if best['_cons'] else 'standalone', 'period_end': end.date().isoformat()}


def quarter_label(period_end) -> str | None:
    """'Q1 FY27' for a quarter that ended 30 June 2026 (April-June is Q1 of the year that ends the next March)."""
    d = pd.to_datetime(period_end, errors='coerce')
    if pd.isna(d) or d.month not in (3, 6, 9, 12):
        return None
    q = {6: 1, 9: 2, 12: 3, 3: 4}[d.month]
    fy = d.year + 1 if d.month >= 4 else d.year
    return f'Q{q} FY{fy % 100:02d}'


def _quarter_rows(results: pd.DataFrame, isin) -> pd.DataFrame:
    r = results[results['isin'].astype(str).eq(str(isin))].copy()
    r['_end'] = pd.to_datetime(r['period_end'], errors='coerce')
    r = r[r['_end'].notna() & r['_end'].dt.month.isin([3, 6, 9, 12])]
    r['_rev'] = [(_number(a) or 0) or (_number(b) or 0) for a, b in zip(r.get('quarter_revenue', pd.Series(dtype=float, index=r.index)),
                                                                          r.get('quarter_total_income', pd.Series(dtype=float, index=r.index)))]
    r['_profit'] = [_number(x) for x in r.get('quarter_profit', pd.Series(dtype=float, index=r.index))]
    r['_cons'] = r['consolidated'].astype(str).str.lower().eq('consolidated')
    r['_at'] = pd.to_datetime(r.get('broadcast_at'), errors='coerce', utc=True)
    r = r[r['_rev'] > 0]
    # one row a period: consolidated before standalone, the latest revision
    return r.sort_values(['_end', '_cons', '_at']).drop_duplicates('_end', keep='last')


def last_quarter(results: pd.DataFrame | None, isin, as_of) -> dict | None:
    """The company's latest quarterly result published before `as_of` (the card's own date), from its XBRL: {'quarter': 'Q1 FY27',
    'revenue', 'profit', 'revenue_yoy', 'profit_yoy', 'basis'}. The growth figures are against the same quarter a year earlier when
    our table has it (a profit growth only when both profits are positive), else None. None when there is no earlier quarter."""
    if results is None or results.empty or not isin or 'isin' not in results:
        return None
    r = _quarter_rows(results, isin)
    if r.empty:
        return None
    cut = pd.to_datetime(as_of, errors='coerce')
    if pd.notna(cut):
        cut = cut.tz_convert(None) if getattr(cut, 'tzinfo', None) else cut
        r = r[r['_at'].dt.tz_convert(None) < cut]
    if r.empty:
        return None
    cur = r.iloc[-1]
    prior = r[(r['_end'] >= cur['_end'] - pd.Timedelta(days=380)) & (r['_end'] <= cur['_end'] - pd.Timedelta(days=350))]
    prior = prior.iloc[-1] if len(prior) else None

    def growth(a, b, positive_only=False):
        if a is None or b is None or b == 0 or (positive_only and (a <= 0 or b <= 0)):
            return None
        return (a / b - 1) * 100
    return {'quarter': quarter_label(cur['_end']), 'revenue': float(cur['_rev']), 'profit': cur['_profit'],
            'revenue_yoy': growth(float(cur['_rev']), float(prior['_rev'])) if prior is not None else None,
            'profit_yoy': growth(cur['_profit'], prior['_profit'], True) if prior is not None else None,
            'basis': 'consolidated' if cur['_cons'] else 'standalone', 'period_end': cur['_end'].date().isoformat()}
