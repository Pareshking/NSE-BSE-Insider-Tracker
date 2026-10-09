"""That day's traded range, from our own price layer, for the clean step's price checks.

The price layer (`prices/daily/{nse|bse}/YYYY-MM.parquet`, written by scripts/price_backfill.py and parsed by
insiders_clean/prices.py) holds one row per exchange, date, ISIN, symbol and series, as printed. The clean
step needs much less: for a security and a span of days, the lowest low and the highest high printed. This
module turns the price rows into that, and attaches it to filings and deals. No I/O except through the `get`
function the caller passes, so the clean step stays testable and works without prices (every check is then
reported as `no_price_layer`, nothing is flagged).

Price check outcomes (`price_check` column):
  inside              price within [low, high] widened by PRICE_TOLERANCE
  below / above       outside that band
  power_of_ten        price x 10^k (k = UNIT_POWERS) falls inside: value filed in lakh (k = 5), crore (7),
                      thousand (3) and so on, with the quantity in shares
  swapped             1 / price falls inside: quantity and value entered in each other's fields
  no_price            nothing to check: no quantity or no value filed
  no_isin, no_dates, span_too_long, no_print, no_price_layer
                      the check could not run (no security, no readable date, a trade span longer than
                      MAX_SPAN_DAYS, no traded print in the span, or no price layer loaded)
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

PRICE_KEY = 'prices/daily/{exchange}/{month}.parquet'
READ_COLUMNS = ['date', 'exchange', 'isin', 'series', 'high', 'low', 'close', 'volume']
RANGE_COLUMNS = ['exchange', 'isin', 'date', 'low', 'high', 'close']

# A filed value is total consideration, sometimes with charges, and is often rounded; a price this far
# outside the day's range still counts as inside. Calibrated on real filings (docs/CLEAN_LAYER.md).
PRICE_TOLERANCE = 0.02
# Trade spans longer than this many calendar days are not checked: the range over many weeks says little.
MAX_SPAN_DAYS = 31
# Powers of ten tried when a price is outside the range. 1 is left out: one tenth or ten times the market
# price is within reach of a real off-market price (face value, a fixed offer price).
UNIT_POWERS = (2, 3, 5, 6, 7)

NOT_CHECKED = ('no_price', 'no_isin', 'no_dates', 'span_too_long', 'no_print', 'no_price_layer')


def months_between(start: date, end: date) -> list[str]:
    """'YYYY-MM' for every month from start to end, both included."""
    if start > end:
        return []
    return [p.strftime('%Y-%m') for p in pd.period_range(start, end, freq='M')]


def load(get, months, exchanges=('nse', 'bse')):
    """Read the needed months of the price layer through `get(key) -> bytes | None` and reduce them to day
    ranges. Returns (ranges or None, info). A missing month is listed, never an error; a month that cannot be
    read is listed with its error, so a broken file costs that month's checks, not the clean step."""
    import io
    frames, found, missing, unreadable = [], [], [], {}
    for ex in exchanges:
        for m in months:
            key = PRICE_KEY.format(exchange=ex, month=m)
            try:
                body = get(key)
                if body is None:
                    missing.append(key)
                    continue
                frames.append(day_ranges(pd.read_parquet(io.BytesIO(body), columns=READ_COLUMNS)))
                found.append(key)
            except Exception as e:  # noqa: BLE001 -- one bad month must not stop the clean step
                unreadable[key] = f'{type(e).__name__}: {e}'
    info = {'months_read': len(found), 'months_missing': missing, 'months_unreadable': unreadable}
    if not frames:
        return None, info
    ranges = pd.concat(frames, ignore_index=True)
    info['sessions'] = int(ranges['date'].nunique())
    info['first'] = str(ranges['date'].min().date()) if len(ranges) else None
    info['last'] = str(ranges['date'].max().date()) if len(ranges) else None
    return ranges, info


def day_ranges(prices: pd.DataFrame) -> pd.DataFrame:
    """Price rows -> one row per exchange (lower case), ISIN and session: the lowest low and highest high
    over every series that traded (volume > 0) that day, and the close of the most traded series."""
    if prices is None or prices.empty:
        return pd.DataFrame(columns=RANGE_COLUMNS)
    p = prices[[c for c in READ_COLUMNS if c in prices.columns]].copy()
    p['isin'] = p['isin'].astype('string').str.strip()
    for c in ('high', 'low', 'close', 'volume'):
        p[c] = pd.to_numeric(p[c], errors='coerce')
    p['date'] = pd.to_datetime(p['date'], errors='coerce').dt.normalize()
    p = p[p['isin'].fillna('').ne('') & p['date'].notna() & (p['volume'] > 0) & (p['low'] > 0) & (p['high'] > 0)]
    if p.empty:
        return pd.DataFrame(columns=RANGE_COLUMNS)
    p['exchange'] = p['exchange'].astype(str).str.lower()
    p = p.sort_values('volume', ascending=False)
    g = p.groupby(['exchange', 'isin', 'date'], sort=False)
    out = g.agg(low=('low', 'min'), high=('high', 'max'), close=('close', 'first')).reset_index()
    out['isin'] = out['isin'].astype(object)
    return out[RANGE_COLUMNS]


def attach(df: pd.DataFrame, ranges: pd.DataFrame | None, isin_col: str, from_col: str, to_col: str,
           exchange_col: str | None = None, max_span_days: int = MAX_SPAN_DAYS) -> pd.DataFrame:
    """For each row: day_low / day_high over the sessions from `from_col` to `to_col` (missing from = to),
    `day_sessions` printed in that span, and `range_status` (ok or why not). With `exchange_col` the row's own
    exchange is used; without it, both exchanges together (an insider may trade on either)."""
    out = pd.DataFrame({'day_low': np.nan, 'day_high': np.nan, 'day_sessions': 0,
                        'range_status': 'no_price_layer'}, index=df.index)
    if ranges is None:
        return out
    isin = df[isin_col].astype(object)
    to = pd.to_datetime(df[to_col], errors='coerce')
    frm = pd.to_datetime(df[from_col], errors='coerce').fillna(to)
    to = to.fillna(frm)
    start, end = np.minimum(frm, to), np.maximum(frm, to)
    span = (end - start).dt.days
    has_isin = isin.notna() & isin.astype(str).str.strip().ne('')
    status = pd.Series('ok', index=df.index, dtype=object)
    status[~has_isin] = 'no_isin'
    status[has_isin & start.isna()] = 'no_dates'
    status[has_isin & start.notna() & (span > max_span_days)] = 'span_too_long'
    ok = status.eq('ok').to_numpy()
    if ok.any():
        pos = np.flatnonzero(ok)
        n = span.to_numpy()[pos].astype(int) + 1
        rep = np.repeat(pos, n)
        offset = np.arange(len(rep)) - np.repeat(np.cumsum(n) - n, n)
        days = pd.DataFrame({'_pos': rep, 'isin': isin.to_numpy()[rep],
                             'date': start.to_numpy()[rep] + offset.astype('timedelta64[D]')})
        key = ['isin', 'date']
        r = ranges
        if exchange_col is not None:
            days['exchange'] = df[exchange_col].astype(str).str.lower().to_numpy()[rep]
            key = ['exchange'] + key
        else:
            r = ranges.groupby(['isin', 'date'], sort=False).agg(low=('low', 'min'), high=('high', 'max')).reset_index()
        hit = days.merge(r[key + ['low', 'high']], on=key, how='inner')
        agg = hit.groupby('_pos').agg(low=('low', 'min'), high=('high', 'max'), n=('low', 'size'))
        idx = df.index[agg.index.to_numpy()]
        out.loc[idx, 'day_low'] = agg['low'].to_numpy()
        out.loc[idx, 'day_high'] = agg['high'].to_numpy()
        out.loc[idx, 'day_sessions'] = agg['n'].to_numpy()
        status[ok & ~df.index.isin(idx)] = 'no_print'
    out['range_status'] = status
    return out


def check(price: pd.Series, rng: pd.DataFrame, tolerance: float = PRICE_TOLERANCE,
          powers=UNIT_POWERS) -> pd.DataFrame:
    """Price against the attached range -> `price_check` (see the module docstring) and `unit_power`
    (the k of a power_of_ten outcome, signed: +5 means the filed price is 10^5 too small)."""
    p = pd.to_numeric(price, errors='coerce')
    lo, hi = rng['day_low'] * (1 - tolerance), rng['day_high'] * (1 + tolerance)

    def inside(x):
        return (x >= lo) & (x <= hi)

    res = pd.Series(rng['range_status'].to_numpy(), index=rng.index, dtype=object)
    power = pd.Series(pd.NA, index=rng.index, dtype='Int64')
    ok = res.eq('ok')
    res[ok & ~(p > 0)] = 'no_price'
    todo = ok & (p > 0)
    res[todo & inside(p)] = 'inside'
    left = todo & ~inside(p)
    for k in powers:
        for signed in (k, -k):
            hit = left & inside(p * 10.0 ** signed)
            res[hit] = 'power_of_ten'
            power[hit] = signed
            left &= ~hit
    hit = left & inside(1 / p)
    res[hit] = 'swapped'
    left &= ~hit
    res[left & (p < lo)] = 'below'
    res[left & (p > hi)] = 'above'
    return pd.DataFrame({'price_check': res, 'unit_power': power}, index=rng.index)
