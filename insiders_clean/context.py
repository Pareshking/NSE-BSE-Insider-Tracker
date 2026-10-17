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
