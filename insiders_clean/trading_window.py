"""Results dates and the trading window (TODO 25). No I/O.

SEBI PIT (Schedule B): the trading window closes from the end of each quarter
until 48 hours after the financial results are declared. Insiders who want
to buy can do so only once it reopens, so a buy in the first sessions after
the window opens may be the first chance they had. Whether such buys do
better is for the Track record to measure; here it is only a fact.

Results date = the date of a board meeting whose purpose is results
(NSE board meetings, `results` flag), skipping a meeting NSE lists as
rescheduled (postponed) on that date. NSE gives the meeting date, not the
time the results were filed: the window is taken to open on the meeting date
+ 2 calendar days (the 48 hours end that day at the latest when results come
out on the meeting day). Results filed after midnight open it a day later
than shown here.
"""
from __future__ import annotations

import json
from datetime import timedelta

import pandas as pd

from .calendar import Calendar

WINDOW_OPEN_SESSIONS = 5    # a buy in the first N sessions after the window opens is marked
WINDOW_HOURS_DAYS = 2       # 48 hours after the results, in calendar days
MAX_LOOKBACK_DAYS = 100     # a results date further back than this is not this quarter's
COLUMNS = ['results_date', 'window_open_date', 'sessions_since_window_open', 'window_open_buy']


def _rescheduled(raw) -> bool:
    """True when one of NSE's rows for this meeting says it was rescheduled
    (those rows carry the original date and say it was postponed)."""
    try:
        rows = json.loads(raw) if isinstance(raw, str) else []
    except ValueError:
        return False
    rows = rows if isinstance(rows, list) else [rows]
    return any(str(r.get('bm_purpose') or '').lower().startswith('board meeting rescheduled') for r in rows if isinstance(r, dict))


def results_dates(meetings: pd.DataFrame | None) -> pd.DataFrame:
    """(symbol, results_date) for every results meeting that was not
    postponed, one row per company and day."""
    if meetings is None or meetings.empty or 'results' not in meetings:
        return pd.DataFrame(columns=['symbol', 'results_date'])
    m = meetings[meetings['results'].astype('boolean').fillna(False)].copy()
    if 'raw_json' in m:
        m = m[~m['raw_json'].map(_rescheduled)]
    m['results_date'] = pd.to_datetime(m['meeting_date'], errors='coerce')
    m['symbol'] = m['symbol'].astype('string').str.upper()
    return m.dropna(subset=['symbol', 'results_date'])[['symbol', 'results_date']].drop_duplicates().reset_index(drop=True)


def attach(trades: pd.DataFrame, meetings: pd.DataFrame | None, cal: Calendar, today=None,
           n: int = WINDOW_OPEN_SESSIONS) -> tuple[pd.DataFrame, dict]:
    """Adds results_date (the latest results meeting whose window had opened
    by the first trade day), window_open_date, sessions_since_window_open (0 =
    bought on the first session the window was open) and window_open_buy (an
    open-market buy in the first n sessions). Blank when the company has no
    results meeting in our data in the MAX_LOOKBACK_DAYS before the trade.
    Results meetings after `today` (announced ahead) are never used."""
    t = trades.copy()
    for c in COLUMNS:
        t[c] = None
    rd = results_dates(meetings)
    if today is not None:
        rd = rd[rd['results_date'] <= pd.Timestamp(today)]
    rep = {'results_dates': len(rd), 'companies_with_results': int(rd['symbol'].nunique()) if len(rd) else 0,
           'window_open_sessions': n}
    if t.empty or rd.empty or 'nse_symbol' not in t:
        t['window_open_buy'] = False
        rep.update(trades_with_results_date=0, window_open_buys=0)
        return t, rep
    rd = rd.assign(window_open_date=rd['results_date'] + pd.Timedelta(days=WINDOW_HOURS_DAYS)).sort_values('window_open_date')
    day = pd.to_datetime(t['trade_date_from'], errors='coerce').fillna(pd.to_datetime(t['trade_date_to'], errors='coerce'))
    left = pd.DataFrame({'_i': t.index, 'symbol': t['nse_symbol'].astype('string').str.upper(), 'day': day})
    ok = left.dropna(subset=['symbol', 'day']).sort_values('day')
    j = pd.merge_asof(ok, rd, left_on='day', right_on='window_open_date', by='symbol', direction='backward',
                      tolerance=pd.Timedelta(days=MAX_LOOKBACK_DAYS)).dropna(subset=['window_open_date'])
    since = [cal.sessions_after((o - timedelta(days=1)).date(), d.date()) for o, d in zip(j['window_open_date'], j['day'])]
    j['since'] = [None if s is None else max(int(s) - 1, 0) for s in since]
    idx = j['_i'].to_numpy()
    t.loc[idx, 'results_date'] = j['results_date'].dt.date.to_numpy()
    t.loc[idx, 'window_open_date'] = j['window_open_date'].dt.date.to_numpy()
    t.loc[idx, 'sessions_since_window_open'] = j['since'].to_numpy()
    t['sessions_since_window_open'] = pd.array(t['sessions_since_window_open'], dtype='Int64')
    buy = t['is_market'].astype('boolean').fillna(False) & t['side'].eq('BUY')
    t['window_open_buy'] = (buy & t['sessions_since_window_open'].lt(n)).fillna(False).astype(bool)
    rep.update(trades_with_results_date=int(t['results_date'].notna().sum()),
               window_open_buys=int(t['window_open_buy'].sum()))
    return t, rep
