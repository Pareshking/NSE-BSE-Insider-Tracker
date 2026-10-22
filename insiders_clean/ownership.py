"""Ownership by investor type, quarter by quarter, for the Company page: the `{type}_pct` columns that
collectors/nse_events/parsers.parse_shp_categories reads from each shareholding-pattern XBRL (SEBI's
Table III and IV; % of total shares less shares under depository receipts, as the filing states them).

A quarter is used only when its categories were parsed and add up (`categories_check == 'match'`);
any other quarter is listed as not parsed, never filled in."""
from __future__ import annotations

import pandas as pd

# Shown rows -> the parser's investor types they add up.
ROWS = [('Promoter', ('promoter',)), ('Mutual funds', ('mf',)), ('Insurance', ('insurance',)), ('FPI', ('fpi',)),
        ('Other DII and AIF', ('banks_fi', 'aif', 'other_dii')), ('Retail (up to ₹2 L)', ('retail',)), ('HNI', ('hni',)),
        ('Bodies corporate', ('corporate',)),
        ('Other', ('other_foreign', 'govt', 'other_public', 'non_public_other'))]


def by_quarter(rows: pd.DataFrame | None, quarters: int = 5) -> tuple[pd.DataFrame, list]:
    """(table, not parsed): one row per ROWS label and one column per quarter end (oldest first) for the
    company's latest `quarters` quarters, values in % of shares; plus a `change` column, the latest
    parsed quarter less the one before it (points), when both are parsed. `not parsed` lists the quarter
    ends whose categories are missing or do not add up; their column is blank."""
    if rows is None or rows.empty or 'quarter_end' not in rows:
        return pd.DataFrame(), []
    r = rows.assign(q=pd.to_datetime(rows['quarter_end'], errors='coerce')).dropna(subset=['q'])
    r = r.sort_values('q').drop_duplicates('q', keep='last').tail(quarters)
    ok = (r['categories_check'] == 'match') if 'categories_check' in r else pd.Series(False, index=r.index)
    table = pd.DataFrame(index=[label for label, _ in ROWS])
    for (_, x), good in zip(r.iterrows(), ok):
        col = []
        for _, types in ROWS:
            vals = [pd.to_numeric(x.get(f'{t}_pct'), errors='coerce') for t in types]
            col.append(float(sum(vals)) if good and all(pd.notna(v) for v in vals) else float('nan'))
        table[x['q']] = col
    parsed = [q for q, good in zip(r['q'], ok) if good]
    table['change'] = (table[parsed[-1]] - table[parsed[-2]]) if len(parsed) >= 2 else float('nan')
    return table, [q for q, good in zip(r['q'], ok) if not good]
