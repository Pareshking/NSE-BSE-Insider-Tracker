"""Everything a page needs: the clean tables, the eligible insider trades and
the 'as of' date (the latest filing in the data, never the wall clock). Built
once per 10 minutes and shared by every visitor and page run, not copied per
run (copies per run put the site over its memory limit): pages copy a frame
before changing it."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import streamlit as st
from data import store

from insiders_clean import issues as issue_clean
from insiders_clean import signals
from insiders_clean.calendar import DISCLOSURE_LIMIT_SESSIONS
from insiders_clean.bse_events import with_bse


@dataclass
class Ctx:
    trades: pd.DataFrame        # all clean insider filings
    eligible: pd.DataFrame      # open-market, primary, not held back
    deals: pd.DataFrame
    securities: pd.DataFrame
    sast: pd.DataFrame          # NSE's, plus BSE rows NSE has not got (listed_on 'bse')
    actions: pd.DataFrame
    meetings: pd.DataFrame
    shareholding: pd.DataFrame
    preferential: pd.DataFrame  # NSE preferential issue records, both stages, linked where certain
    rights: pd.DataFrame
    prices: pd.DataFrame        # per ISIN: latest_close, high_52w, pct_off_high, last_date
    ref: pd.Timestamp | None
    latest: dict
    marks: dict | None = None   # ISIN -> [(day made public, side)], for the sparklines
    results: pd.DataFrame | None = None   # NSE results (columns the cards use), for the size against the last full year
    encumbrances: pd.DataFrame | None = None   # SAST Reg 31 events: the lender on the pledge rows


def _display_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Columns only the pages use: value in crores, exchange in capitals. On a shallow copy: the table's
    other columns stay shared with the store's cached one, not held twice (setting a column replaces it in
    this frame only)."""
    if df.empty:
        return df
    df = df.copy(deep=False)
    if 'value' in df:
        df['value_cr'] = pd.to_numeric(df['value'], errors='coerce') / 1e7
    if 'listed_on' in df:
        df['listed_on'] = df['listed_on'].astype(str).str.upper()
    return df


def load() -> Ctx:
    return _shared()


@st.cache_resource(ttl=600, show_spinner=False, max_entries=1)
def _shared() -> Ctx:
    store.prefetch()   # every object a first visit reads, from R2 at once rather than one by one
    trades = _display_columns(store.table('insider_trades'))
    elig = signals.eligible(trades) if not trades.empty else trades
    deals = _display_columns(store.table('deals'))
    if not deals.empty:
        deals['date'] = pd.to_datetime(deals['date'], errors='coerce')
    return Ctx(trades=trades, eligible=elig, deals=deals, securities=store.table('securities'),
               sast=with_bse(store.table('sast'), store.table('bse_sast')),
               actions=with_bse(store.table('actions'), store.table('bse_actions')), meetings=store.table('meetings'),
               shareholding=with_bse(store.table('shareholding'), store.table('bse_shareholding')),
               preferential=store.table('preferential'),
               rights=store.table('rights'), prices=store.prices(), ref=signals.as_of(trades), latest=store.latest(),
               marks=_marks(elig), results=store.table('results'), encumbrances=store.table('encumbrances'))


def need_data(ctx: Ctx) -> bool:
    """Draws the explanation and returns False when there's nothing to show."""
    if ctx.trades.empty:
        from ui import kit
        kit.note('No clean data yet.',
                 'The nightly cleaning step writes clean/current/ in R2; this page fills in after its first run.'
                 if store.configured() else
                 'R2 credentials are not configured for this app (see .streamlit/secrets.toml.example).')
        return False
    return True


PRICE_COLS = ['latest_close', 'low_52w', 'high_52w', 'pct_off_high', 'mcap_bucket']


def with_prices(df: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """Adds the latest close and 52-week range by ISIN (blank where the stock
    has no price in our NSE/BSE files)."""
    if df.empty or prices.empty or 'isin' not in df:
        return df.assign(**{c: None for c in PRICE_COLS})
    p = prices.drop_duplicates('isin').set_index('isin')
    return df.assign(**{c: df['isin'].map(p[c]) if c in p else None for c in PRICE_COLS})


def pre_public_move(df: pd.DataFrame) -> pd.Series:
    """Per filing, the stock's move (%) from the last trade date to the day it
    was made public, on split-adjusted closes (artifacts/price_history.parquet,
    the last ~400 days): what the market had already done before a reader
    could know. Blank where either close is missing."""
    hist = store.price_history()
    out = pd.Series(np.nan, index=df.index)
    if df.empty or not hist:
        return out
    to = pd.to_datetime(df['trade_date_to'], errors='coerce').to_numpy()
    seen = pd.to_datetime(df['broadcast_date'], errors='coerce').dt.normalize().to_numpy()
    for k, (i, a, b) in enumerate(zip(df['isin'], to, seen)):
        h = hist.get(i)
        if h is None or pd.isna(a) or pd.isna(b) or b < a:
            continue
        d, c = h
        ia, ib = np.searchsorted(d, a, side='right') - 1, np.searchsorted(d, b, side='right') - 1
        if ia >= 0 and ib >= 0 and c[ia] > 0:
            out.iloc[k] = (c[ib] / c[ia] - 1) * 100
    return out


def split_since(df: pd.DataFrame, prices: pd.DataFrame, date_col='trade_date_to') -> pd.Series:
    """Per row, the split/bonus factor that puts a price of `date_col`'s day
    (a trade, an allotment, a buyback offer) on the basis of today's adjusted
    close (price x factor; shares / factor): 1 when none came after that day,
    the factor when one did, blank when more than one may have (the summary
    keeps only the last) or the date is unreadable. `date_col` may be a list:
    the first readable date per row is used."""
    one = pd.Series(1.0, index=df.index)
    if df.empty or prices.empty or 'last_split_date' not in prices or 'isin' not in df:
        return one
    p = prices.drop_duplicates('isin').set_index('isin')
    when = pd.Series(pd.NaT, index=df.index)
    for c in [date_col] if isinstance(date_col, str) else date_col:
        if c in df:
            when = when.fillna(pd.to_datetime(df[c], errors='coerce'))
    split = pd.to_datetime(df['isin'].map(p['last_split_date']), errors='coerce')
    n = pd.to_numeric(df['isin'].map(p['n_splits']), errors='coerce').fillna(0)
    f = pd.to_numeric(df['isin'].map(p['last_split_factor']), errors='coerce')
    after = split.notna() & (when.isna() | (when < split))
    return one.where(~after, f).where(~(after & (when.isna() | (n > 1))))


def with_flags(df: pd.DataFrame) -> pd.DataFrame:
    """Adds today's tradability flags by ISIN (NSE surveillance stage, trade for trade, SME, tight band,
    circuit-locked days), drawn as amber badges under the company name. Flags, never a filter."""
    return signals.with_tradability(df, store.table('tradability'))


def _marks(eligible: pd.DataFrame) -> dict:
    """ISIN -> [(day made public, side)] for open-market insider trades."""
    if eligible.empty:
        return {}
    e = eligible.dropna(subset=['isin', 'seen'])
    return {i: list(zip(g['seen'], g['side'])) for i, g in e.groupby('isin', sort=False)}


def with_sparks(df: pd.DataFrame, ctx: Ctx) -> pd.DataFrame:
    """Adds `_spark` (the year's price line, insider trades marked) and
    `_chg_1y` by ISIN."""
    from ui import kit
    if df.empty or 'isin' not in df:
        return df
    hist, marks = store.price_history(), ctx.marks if ctx.marks is not None else _marks(ctx.eligible)
    drawn = [kit.spark(*hist[i], marks.get(i, ())) if isinstance(i, str) and i in hist else (None, None)
             for i in df['isin']]
    return df.assign(_spark=[s for s, _ in drawn], _chg_1y=[c for _, c in drawn])


# ---- Issue rows (preferential, rights, QIP): one builder for every page that lists them ----------
# Moved from screens/capital_raises.py (21 Oct) so the Filings page and Capital raises share it.

ALLOTTEE_LABEL = {'PROMOTER': 'Promoters', 'NON_PROMOTER': 'Non-promoters', 'MIXED': 'Promoters and others'}
LOCK_IN_RECENT_DAYS = 30


def _on_today(price, rows, prices, dates):
    """A filed price put on the basis of today's split- and bonus-adjusted close (audit W9)."""
    return pd.to_numeric(price, errors='coerce') * split_since(rows, prices, dates)


def _amount(rows: pd.DataFrame) -> pd.Series:
    """One meaning for "Amount" on every issue kind (audit W11): what was raised once the
    securities are allotted, the approved size before that; the Stage column says which."""
    empty = pd.Series(index=rows.index, dtype=float)
    raised = pd.to_numeric(rows['amount_raised'], errors='coerce') if 'amount_raised' in rows else empty
    approved = pd.to_numeric(rows['amount_total'], errors='coerce') if 'amount_total' in rows else empty
    return raised.fillna(approved)


def _vs_market(offer, close):
    ok = pd.to_numeric(offer, errors='coerce').gt(0) & pd.to_numeric(close, errors='coerce').gt(0)
    return ((pd.to_numeric(offer, errors='coerce') / pd.to_numeric(close, errors='coerce') - 1) * 100).where(ok)


def _stage_rows(records: pd.DataFrame) -> pd.DataFrame:
    """Allotted or listed records, and approvals no listing record points to."""
    r = records.copy()
    linked = set(r.loc[r['stage'] == 'listing', 'linked_app_id'].dropna())
    approved = r[(r['stage'] == 'in_principle') & ~r['app_id'].isin(linked)].assign(status='Approved in principle')
    return pd.concat([r[r['stage'] == 'listing'].assign(status='Allotted or listed'), approved], ignore_index=True)


def issue_rows(records: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """One row per issue as far as the data shows: an allotted or listed
    record (with its approval's amount, allottee and filed ICDR minimum when
    the two are linked), or an approval no listing record points to."""
    if records is None or records.empty:
        return pd.DataFrame()
    rows = _stage_rows(records)
    rows['nse_symbol'] = rows['symbol']
    rows['to'] = rows['allottee_category'].map(ALLOTTEE_LABEL) if 'allottee_category' in rows else None
    rows['amount'] = _amount(rows)
    for c in ('icdr_min_price', 'icdr_min_ours', 'vs_icdr_min', 'instruments'):
        if c not in rows:
            rows[c] = None
    rows = with_prices(rows, prices)
    rows['vs_market'] = _vs_market(_on_today(rows.get('offer_price'), rows, prices, ['allotment_date', 'listing_date', 'board_date', 'posted_on']), rows['latest_close'])
    rows['ours_vs_filed'] = _vs_market(rows['icdr_min_ours'], rows['icdr_min_price'])
    return rows.sort_values('posted_on', ascending=False, na_position='last', kind='stable').reset_index(drop=True)


def lock_in_calendar(records: pd.DataFrame, prices: pd.DataFrame, today: pd.Timestamp,
                     lines: pd.DataFrame | None = None) -> pd.DataFrame:
    """Lock-in expiries, earliest first, from a month ago on: the lines the
    company filed where the listing XBRL has them, the rule otherwise
    (promoters 18 months, others 6, from the trading-approval date). `lines`
    is the preferential_lockins table; without it the rule lines are built
    from `records`. A rule line of a mixed allotment has no share count (the
    split is not filed), so no market value."""
    if lines is None or lines.empty:
        if records is None or records.empty or 'lock_in_promoter_until' not in records:
            return pd.DataFrame()
        lines = issue_clean.lock_in_lines(records, {})
    rows = lines[lines['expires'].notna()].copy()
    if rows.empty:
        return pd.DataFrame()
    rows['expires'] = pd.to_datetime(rows['expires'])
    rows = rows[rows['expires'] >= today.normalize() - pd.Timedelta(days=LOCK_IN_RECENT_DAYS)].copy()
    rows['nse_symbol'] = rows['symbol']
    rows['days_left'] = (rows['expires'] - today.normalize()).dt.days
    months = rows['months'].map(lambda m: f'{m:g} months' if pd.notna(m) else '')
    rows['what'] = [f'{m}, as filed' if b == 'filed' else f'{w}, {m} (rule)'
                    for b, w, m in zip(rows['basis'], rows['who'], months)]
    rows['note'] = ['Mixed allotment: promoter and other split not filed' if b == 'rule' and pd.isna(s) else ''
                    for b, s in zip(rows['basis'], rows['shares'])]
    rows = with_prices(rows, prices)
    # Shares restated for any split or bonus since trading approval, so the value is at today's price (audit W10).
    shares_now = pd.to_numeric(rows['shares'], errors='coerce') / split_since(rows, prices, ['trading_approval_date', 'allotment_date'])
    rows['at_market'] = shares_now * pd.to_numeric(rows['latest_close'], errors='coerce')
    return rows.sort_values('expires').reset_index(drop=True)


def rights_rows(records: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """Rights issues: the listing record (ratio, price, dates) or an approval no listing record points to."""
    if records is None or records.empty:
        return pd.DataFrame()
    rows = _stage_rows(records)
    rows['nse_symbol'] = rows['symbol']
    rows['amount'] = _amount(rows)
    rows = with_prices(rows, prices)
    rows['vs_market'] = _vs_market(_on_today(rows.get('offer_price'), rows, prices, ['record_date', 'allotment_date', 'posted_on']), rows['latest_close'])
    return rows.sort_values('posted_on', ascending=False, na_position='last', kind='stable').reset_index(drop=True)


def qip_rows(records: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """QIPs: the allotment (issue and floor price, discount, allottees) or an
    approval no allotment points to."""
    if records is None or records.empty:
        return pd.DataFrame()
    rows = _stage_rows(records)
    rows['nse_symbol'] = rows['symbol']
    rows['amount'] = _amount(rows)
    rows = with_prices(rows, prices)
    rows['vs_market'] = _vs_market(_on_today(rows['issue_price'], rows, prices, ['allotment_date', 'relevant_date', 'posted_on']), rows['latest_close'])
    return rows.sort_values('posted_on', ascending=False, na_position='last', kind='stable').reset_index(drop=True)


# ---- Insider filing facts in words: shared by the Filings page and the pages it replaces ----------

# The cleaner's reasons for holding a row back (`flags`) or marking it (`marks`), in words
# (insiders_clean/insider.py and deals.py name them).
FLAG_WORDS = {
    'unmatched_security': 'company not found in the NSE/BSE lists', 'unrecognised_mode': 'mode of acquisition not stated',
    'value_over_25pct_of_mcap': "value over 25% of the company's market cap",
    'holding_jump_on_market_trade': 'holding multiplied 20x or more on a market trade',
    'holding_change_differs_from_quantity': "holding change doesn't match the shares traded",
    'holding_moves_against_side': 'holding moves against the side (a buy that lowers it)',
    'missing_or_zero_value': 'market trade with no value', 'missing_quantity': 'market trade with no shares filed',
    'mode_contradicts_side': 'mode says buy, type says sell (or the reverse)', 'dates_out_of_order': 'dates out of order',
    'disclosed_before_trade': 'disclosed before the trade ended', 'trade_date_in_future': 'trade date in the future',
    'disclosure_dated_in_future': 'disclosure dated in the future',
    'value_off_by_power_of_ten': 'value off by a power of ten (lakh, crore)', 'quantity_value_swapped': 'shares and value swapped',
    'value_filed_as_price_per_share': 'value filed as the price per share', 'valued_at_face_value': 'valued at face value',
    'price_far_outside_day_range': "price far outside the day's range",
    'price_outside_day_range': "price a little outside the day's range",
    'missing_price_or_quantity': 'no price or no shares', 'missing_side': 'no side', 'date_in_future': 'deal dated in the future',
}


def flag_words(text) -> list[str]:
    """'a,b' (a `flags` or `marks` cell) -> the reasons in words."""
    return [FLAG_WORDS.get(f, f.replace('_', ' ')) for f in str(text or '').split(',')
            if f.strip() and f not in ('nan', '<NA>', 'None')]


def late_text(r) -> str:
    """'Filed late by 3 trading days (insider to company)', or ''."""
    parts = []
    for col, step in (('insider_to_company_sessions', 'insider to company'),
                      ('company_to_exchange_sessions', 'company to exchange')):
        n = pd.to_numeric(r.get(col), errors='coerce')
        if pd.notna(n) and n > DISCLOSURE_LIMIT_SESSIONS:
            x = int(n - DISCLOSURE_LIMIT_SESSIONS)
            parts.append(f'Filed late by {x} trading day{"s" if x != 1 else ""} ({step})')
    return '; '.join(parts)


def window_text(r) -> str:
    """'2 sessions after the trading window reopened (results 15 Oct)' for a marked buy, or ''."""
    from ui import kit
    v = r.get('window_open_buy')
    if not (pd.notna(v) and bool(v)):
        return ''
    n = int(r['sessions_since_window_open'])
    when = 'First session' if n == 0 else f'{n} session{"s" if n != 1 else ""}'
    return f'{when} after the trading window reopened (results {kit.day(r.get("results_date"), with_year=False)})'
