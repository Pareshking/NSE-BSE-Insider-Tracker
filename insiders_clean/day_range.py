"""That day's traded range, from our own price layer, for the clean step's price check.

The price layer (`prices/daily/{nse|bse}/YYYY-MM.parquet`, written by scripts/price_backfill.py, parsed by
insiders_clean/prices.py) holds one row per exchange, date, ISIN, symbol and series, as printed, never
adjusted. The check needs much less: per ISIN and session, the lowest low and the highest high printed on
either exchange. No I/O except through the `get` the caller passes, so the clean step stays testable and runs
without prices (every row is then `no_price_layer`, nothing is flagged).

`price_check` outcomes, implied price (value / shares) against the range over the trade's sessions:
  inside              within [low, high] widened by PRICE_TOLERANCE
  below / above       outside that, by up to FAR_OUTSIDE more
  far_below/far_above further out than that
  power_of_ten        price x 10^k falls inside (k in UNIT_POWERS, either sign): value filed in lakh (k = 5),
                      crore (7), thousand (3), million (6), or paise (-2), with the quantity in shares
  swapped             1 / price falls inside: quantity and value entered in each other's fields
Not checked, and why:
  no_price            no quantity or no value filed (or a row that moves no shares: pledges, no side)
  no_isin, no_dates   no security, no readable trade date
  span_too_long       a trade span over MAX_SPAN_DAYS calendar days (a range over weeks says little)
  before_price_layer, after_price_layer
                      the trade is outside the days the price layer holds (it is extended by the Price
                      backfill workflow, not nightly)
  no_print            no traded print for that ISIN in the span (suspended, illiquid, or a gap in the layer)
  no_price_layer      no price layer loaded
"""
from __future__ import annotations

import io
from datetime import date

import numpy as np
import pandas as pd

PRICE_KEY = 'prices/daily/{exchange}/{month}.parquet'
READ_COLUMNS = ['date', 'isin', 'high', 'low', 'volume']
RANGE_COLUMNS = ['isin', 'date', 'low', 'high']

# A filed value is the consideration, sometimes with charges, often rounded: this far outside the day's
# range still counts as inside. Not yet calibrated on real filings: scripts/data_checks_diagnose.py
# reports how far outside the market trades fall, so this can be set from the data.
PRICE_TOLERANCE = 0.02
# 20% is the widest fixed daily price band on NSE and BSE (F&O stocks have none): charges or rounding never
# explain a price this far outside every print of those days, and a trade date one session off rarely does.
FAR_OUTSIDE = 0.20
MAX_SPAN_DAYS = 31
# 10x is left out: a tenth or ten times the market price is within reach of a real off-market price.
UNIT_POWERS = (2, 3, 5, 6, 7)

NOT_CHECKED = ('no_price', 'no_isin', 'no_dates', 'span_too_long', 'before_price_layer', 'after_price_layer',
               'no_print', 'no_price_layer')


def months_between(start: date, end: date) -> list[str]:
    """'YYYY-MM' for every month from start to end, both included."""
    if start > end:
        return []
    return [p.strftime('%Y-%m') for p in pd.period_range(start, end, freq='M')]


def load(get, months, exchanges=('nse', 'bse')):
    """Read the months of the price layer through `get(key) -> bytes | None` and reduce them to day ranges.
    Returns (ranges or None, info). A missing month is listed, never an error; an unreadable one is listed
    with its error, so a broken file costs that month's checks, not the clean step."""
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
    frames = [f for f in frames if len(f)]
    if not frames:
        return None, info
    ranges = day_ranges_merge(pd.concat(frames, ignore_index=True))
    info.update(sessions=int(ranges['date'].nunique()), first=str(ranges['date'].min().date()),
                last=str(ranges['date'].max().date()))
    return ranges, info


def day_ranges(prices: pd.DataFrame) -> pd.DataFrame:
    """Price rows -> one row per ISIN and session: lowest low and highest high over every exchange and
    series that traded (volume > 0) that day."""
    if prices is None or prices.empty:
        return pd.DataFrame(columns=RANGE_COLUMNS)
    p = prices[[c for c in READ_COLUMNS if c in prices.columns]].copy()
    p['isin'] = p['isin'].astype('string').str.strip()
    for c in ('high', 'low', 'volume'):
        p[c] = pd.to_numeric(p[c], errors='coerce')
    p['date'] = pd.to_datetime(p['date'], errors='coerce').dt.normalize()
    p = p[p['isin'].fillna('').ne('') & p['date'].notna() & (p['volume'] > 0) & (p['low'] > 0) & (p['high'] > 0)]
    if p.empty:
        return pd.DataFrame(columns=RANGE_COLUMNS)
    return day_ranges_merge(p)


def day_ranges_merge(r: pd.DataFrame) -> pd.DataFrame:
    out = r.groupby(['isin', 'date'], sort=False).agg(low=('low', 'min'), high=('high', 'max')).reset_index()
    out['isin'] = out['isin'].astype(object)
    return out[RANGE_COLUMNS]


def attach(df: pd.DataFrame, ranges: pd.DataFrame | None, isin_col: str, from_col: str, to_col: str,
           max_span_days: int = MAX_SPAN_DAYS) -> pd.DataFrame:
    """Per row: day_low / day_high over the sessions from `from_col` to `to_col` (a missing end takes the
    other), the sessions printed in that span, and `range_status` (ok, or why not)."""
    out = pd.DataFrame({'day_low': np.nan, 'day_high': np.nan, 'day_sessions': 0,
                        'range_status': 'no_price_layer'}, index=df.index)
    if ranges is None or ranges.empty:
        return out
    isin = df[isin_col].astype(object)
    to = pd.to_datetime(df[to_col], errors='coerce')
    frm = pd.to_datetime(df[from_col], errors='coerce').fillna(to)
    to = to.fillna(frm)
    start, end = frm.where(frm <= to, to), to.where(frm <= to, frm)
    span = (end - start).dt.days
    first, last = ranges['date'].min(), ranges['date'].max()
    has_isin = isin.notna() & isin.astype(str).str.strip().ne('')
    status = pd.Series('ok', index=df.index, dtype=object)
    status[~has_isin] = 'no_isin'
    dated = has_isin & start.notna()
    status[has_isin & start.isna()] = 'no_dates'
    status[dated & (span > max_span_days)] = 'span_too_long'
    status[status.eq('ok') & (start > last)] = 'after_price_layer'
    status[status.eq('ok') & (end < first)] = 'before_price_layer'
    ok = status.eq('ok').to_numpy()
    if ok.any():
        pos = np.flatnonzero(ok)
        n = span.to_numpy()[pos].astype(int) + 1
        rep = np.repeat(pos, n)
        offset = np.arange(len(rep)) - np.repeat(np.cumsum(n) - n, n)
        days = pd.DataFrame({'_pos': rep, 'isin': isin.to_numpy()[rep],
                             'date': start.to_numpy()[rep] + offset.astype('timedelta64[D]')})
        hit = days.merge(ranges, on=['isin', 'date'], how='inner')
        agg = hit.groupby('_pos').agg(low=('low', 'min'), high=('high', 'max'), n=('low', 'size'))
        idx = df.index[agg.index.to_numpy()]
        out.loc[idx, 'day_low'] = agg['low'].to_numpy()
        out.loc[idx, 'day_high'] = agg['high'].to_numpy()
        out.loc[idx, 'day_sessions'] = agg['n'].to_numpy()
        status[ok & ~df.index.isin(idx)] = 'no_print'
    out['range_status'] = status
    return out


def check(price: pd.Series, rng: pd.DataFrame, tolerance: float = PRICE_TOLERANCE, far: float = FAR_OUTSIDE,
          powers=UNIT_POWERS) -> pd.DataFrame:
    """Price against the attached range -> `price_check` (module docstring) and `unit_power` (signed k of a
    power_of_ten outcome: +5 means the filed price is 10^5 too small, as when value is filed in lakh)."""
    p = pd.to_numeric(price, errors='coerce').astype(float)
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
    res[left & (p < lo * (1 - far))] = 'far_below'
    res[left & (p > hi * (1 + far))] = 'far_above'
    return pd.DataFrame({'price_check': res, 'unit_power': power}, index=rng.index)
