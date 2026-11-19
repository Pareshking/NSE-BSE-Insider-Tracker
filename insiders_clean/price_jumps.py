"""Audit of the site's price lines: every one-day close move of 40% or more in the product window.

Written by Precompute slim assets to `clean/reports/price_jumps.json` (read by the Data health page). Each move is
measured between a security's consecutive prints, NSE preferred and BSE filling the gaps (the same panel the site
draws), on the prices as printed (`raw_move`) and as adjusted for splits and bonuses (`adj_move`), and gets one status:

- `adjusted`: the print moved 40% or more and the adjusted line does not: a split or bonus was applied that day.
- `made_by_adjustment`: the print did not move 40% but the adjusted line does: an applied factor that is wrong.
  Added after IIFL Finance (19 Nov 2026, insiders_clean/adjust.py SIDE_SERIES); should stay at zero.
- `action_not_adjusted`: the adjusted line moves 40% or more and a corporate action is filed for the ISIN with an
  ex-date after the previous print and on or before this one, matched by ISIN or NSE symbol (rights, dividend,
  buyback, or a bonus or split whose factor did not match: adjust.py applies splits and bonuses only).
- `missing_session`: the layer lacks the session before this one (adjust.missing_previous_session: the Sunday
  sessions of 1 Feb 2026 and 8 Nov 2026), so the move spans two sessions.
- `exchange_reset_not_adjusted`: no action filed, but the exchange reset its base price by more than 5% that day
  (`kind` other_large: a demerger, a capital reduction, a relisting; NSE's action feed as parsed drops demergers
  and schemes, collectors/nse_events/parsers.py).
- `after_gap`: none of the above, and the previous print is more than GAP_DAYS calendar days before (a suspension,
  an illiquid stock): the move is real but spread over the gap.
- `unexplained`: none of the above.

Nothing here changes a price; the audit says where a line may be wrong.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

JUMP = 0.40
GAP_DAYS = 10
MAX_ROWS = 3000
STATUSES = ('made_by_adjustment', 'unexplained', 'exchange_reset_not_adjusted', 'action_not_adjusted', 'missing_session',
            'after_gap', 'adjusted')
ROW_COLUMNS = ['isin', 'symbol', 'name', 'date', 'prev_date', 'gap_days', 'prev_close', 'close', 'raw_move',
               'adj_move', 'factor', 'kind', 'kind_basis', 'actions', 'in_universe', 'status']


def _long(panel: pd.DataFrame, name: str) -> pd.DataFrame:
    """date x ISIN panel -> isin, date, value, previous print's date and value, one row per print."""
    d = panel.stack(future_stack=True).dropna().rename(name).reset_index()
    d.columns = ['date', 'isin', name]
    d = d.sort_values(['isin', 'date']).reset_index(drop=True)
    g = d.groupby('isin', sort=False)
    d[f'prev_{name}'] = g[name].shift(1)
    d['prev_date'] = g['date'].shift(1)
    return d


def jumps(raw: pd.DataFrame, adj: pd.DataFrame, factors: pd.DataFrame | None = None,
          actions: pd.DataFrame | None = None, start=None, threshold: float = JUMP, universe: set | None = None,
          meta: pd.DataFrame | None = None, gap_days: int = GAP_DAYS) -> pd.DataFrame:
    """One row per ISIN and session whose raw or adjusted close moved `threshold` or more from the previous print,
    dated on or after `start`, with its status (see the module docstring). `raw` and `adj`: date x ISIN close panels
    of the same prints (slim.adjusted_and_raw)."""
    r = _long(raw, 'close')
    a = _long(adj, 'adj')[['isin', 'date', 'adj', 'prev_adj']]
    m = r.merge(a, on=['isin', 'date'], how='left')
    m = m[m['prev_close'].notna() & (m['prev_close'] > 0)]
    if start is not None:
        m = m[m['date'] >= pd.Timestamp(start)]
    with np.errstate(invalid='ignore', divide='ignore'):
        m['raw_move'] = m['close'] / m['prev_close'] - 1
        m['adj_move'] = m['adj'] / m['prev_adj'] - 1
    big_raw, big_adj = m['raw_move'].abs() >= threshold, m['adj_move'].abs() >= threshold
    m = m[big_raw | big_adj].copy()
    if m.empty:
        return pd.DataFrame(columns=ROW_COLUMNS)
    m['gap_days'] = (m['date'] - m['prev_date']).dt.days
    m['factor'], m['kind'], m['kind_basis'] = np.nan, '', ''
    if factors is not None and len(factors):
        f = factors.assign(_nse=factors['exchange'].ne('NSE')).sort_values('_nse').drop_duplicates(['isin', 'date'])
        f = f[['isin', 'date', 'factor', 'kind'] + (['kind_basis'] if 'kind_basis' in f else [])]
        m = m.drop(columns=['factor', 'kind', 'kind_basis']).merge(f, on=['isin', 'date'], how='left')
        if 'kind_basis' not in m:
            m['kind_basis'] = ''
        m['kind'], m['kind_basis'] = m['kind'].fillna(''), m['kind_basis'].fillna('')
    m['symbol'], m['name'] = None, None
    if meta is not None and len(meta):
        mm = meta.drop_duplicates('isin').set_index('isin')
        m['symbol'] = m['isin'].map(mm['symbol']) if 'symbol' in mm else None
        m['name'] = m['isin'].map(mm['name']) if 'name' in mm else None
    m['actions'] = ''
    if actions is not None and len(actions) and {'isin', 'purpose', 'ex_date'} <= set(actions.columns):
        ac = actions[['isin', 'purpose', 'ex_date'] + (['symbol'] if 'symbol' in actions else [])].copy()
        ac['ex_date'] = pd.to_datetime(ac['ex_date'], errors='coerce').dt.normalize()
        ac = ac.dropna(subset=['ex_date'])
        left = m[['isin', 'symbol', 'date', 'prev_date']].reset_index()
        # By ISIN, and by NSE symbol: a split's action may be filed under the ISIN it replaces.
        parts = [left.merge(ac.drop(columns=['symbol'], errors='ignore').dropna(subset=['isin']), on='isin')]
        if 'symbol' in ac:
            sy = ac.dropna(subset=['symbol']).drop(columns=['isin']).assign(symbol=lambda d: d['symbol'].astype(str).str.upper())
            parts.append(left.dropna(subset=['symbol']).assign(symbol=lambda d: d['symbol'].astype(str).str.upper())
                         .merge(sy, on='symbol'))
        x = pd.concat(parts, ignore_index=True)
        x = x[(x['ex_date'] > x['prev_date']) & (x['ex_date'] <= x['date'])]
        if len(x):
            lab = x.groupby('index')['purpose'].agg(lambda s: ','.join(sorted(set(s.astype(str)))))
            m.loc[lab.index, 'actions'] = lab.values
    big_raw, big_adj = m['raw_move'].abs() >= threshold, m['adj_move'].abs() >= threshold
    m['status'] = np.select(
        [~big_adj, ~big_raw, m['actions'].ne(''), m['kind_basis'].eq('previous_session_missing'),
         m['kind'].eq('other_large'), m['gap_days'] > gap_days],
        ['adjusted', 'made_by_adjustment', 'action_not_adjusted', 'missing_session', 'exchange_reset_not_adjusted',
         'after_gap'],
        'unexplained')
    m['in_universe'] = m['isin'].isin(universe) if universe is not None else None
    order = {s: i for i, s in enumerate(STATUSES)}
    m = m.assign(_o=m['status'].map(order), _a=-m[['raw_move', 'adj_move']].abs().max(axis=1))
    return m.sort_values(['_o', '_a', 'date'])[ROW_COLUMNS].reset_index(drop=True)


def report(rows: pd.DataFrame, raw: pd.DataFrame, start=None, threshold: float = JUMP, left_out: dict | None = None,
           max_rows: int = MAX_ROWS) -> dict:
    """The JSON report: counts of moves and of companies per status (all, and in the study universe), the rows
    (most suspect first, at most `max_rows`) and the side-window rows left out of every line (`left_out`)."""
    def counts(d):
        return {s: {'moves': int((d['status'] == s).sum()), 'companies': int(d.loc[d['status'] == s, 'isin'].nunique())}
                for s in STATUSES}
    win = raw.loc[pd.Timestamp(start):] if start is not None and len(raw) else raw
    uni = rows[rows['in_universe'].astype('boolean').fillna(False)] if 'in_universe' in rows and rows['in_universe'].notna().any() else None
    out = rows.head(max_rows).copy()
    for c in ('date', 'prev_date'):
        out[c] = pd.to_datetime(out[c]).dt.strftime('%Y-%m-%d')
    out = out.astype(object).where(out.notna(), None)
    return {
        'threshold': threshold, 'start': str(pd.Timestamp(start).date()) if start is not None else None,
        'sessions': int(len(win.index)), 'isins': int(win.notna().any().sum()) if len(win) else 0,
        'moves': int(len(rows)), 'by_status': counts(rows),
        'in_universe': counts(uni) if uni is not None else None,
        'left_out': {'side_window_series': left_out or {}},
        'rows_truncated': bool(len(rows) > max_rows),
        'rows': out.to_dict('records'),
    }
