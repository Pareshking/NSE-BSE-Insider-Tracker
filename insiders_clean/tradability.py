"""Tradability flags: can a reader trade this stock the normal way today? Shown as flags, never used to drop a row.

Sources (each answered with real data on 12 Oct 2026; fixtures in tests/fixtures/tradability/):
- NSE `/api/reportASM`: {'longterm': {'data': [...]}, 'shortterm': {'data': [...]}}, rows with isin, symbol,
  companyName, asmSurvIndicator ('Stage I'..'Stage IV'), survCode ('LTASM - I (13)'), survDesc, asmTime (list date).
- NSE `/api/reportGSM`: a list; the stage is read from survCode ('GSM - 0 (99)', 'GSM III & IBC - Receipt (65)').
  NSE's own `gsmStage` field is not the stage (it holds the code number in Roman numerals: 'LXII' for code 62).
  The same list carries the insolvency (IBC) codes.
- NSE `/api/reportESM`: a list, esmSurvIndicator ('Stage I', 'Stage II'), survCode ('ESM - I (34)').
- NSE `sec_list.csv` (nsearchives): Symbol, Series, Security Name, Band (2, 5, 10, 20, 40 or 'No Band'), Remarks.
  No ISIN: matched to one through the NSE bhavcopy (symbol and series).
- Trade-for-trade and SME from the series NSE prints in its daily bhavcopy (prices/daily/nse), point in time.
- Circuit-locked days are derived from the bhavcopy: see `circuit_days`.

Not available: a current list of suspended securities. NSE's `content/equities/suspension.csv` answers, but its
newest suspension is dated 16 Jul 2012, so it is not used. A suspended stock simply has no bhavcopy row.
Price bands are known only from the day we first fetched `sec_list.csv`; older days are judged on today's band.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Config:
    t2t_series: tuple = ('BE', 'BZ', 'ST')      # NSE trade-for-trade series (ST is the SME one)
    sme_series: tuple = ('SM', 'ST', 'SZ')      # NSE Emerge (SME board) series
    equity_series: tuple = ('EQ', 'BE', 'BZ', 'SM', 'ST', 'SZ')
    tight_band_max_pct: float = 5.0             # flag a band this tight or tighter (research: avoid 5%-band stocks)
    circuit_window: int = 20                    # sessions looked back for circuit-locked days
    circuit_tol_pct: float = 0.1                # points under the band still counted, plus Rs.0.01 for the tick


CONFIG = Config()
LISTS = ('asm_lt', 'asm_st', 'gsm', 'esm', 'ibc')
LABEL = {'asm_lt': 'LT-ASM {}', 'asm_st': 'ST-ASM {}', 'gsm': 'GSM {}', 'esm': 'ESM {}', 'ibc': 'IBC'}
NAME = {'asm_lt': 'Long-term additional surveillance (ASM)', 'asm_st': 'Short-term additional surveillance (ASM)',
        'gsm': 'Graded surveillance (GSM)', 'esm': 'Enhanced surveillance (ESM)',
        'ibc': 'Insolvency (IBC) surveillance code'}
SURV_COLUMNS = ['date', 'list', 'isin', 'symbol', 'company', 'stage', 'code', 'description', 'listed_at']
_ROMAN = r'(0|IV|V?I{1,3}|VI{0,3}|IX|X)'
_GSM = re.compile(r'(?<![A-Z])GSM\s*-?\s*' + _ROMAN + r'(?![A-Z])')
_IBC = re.compile(r'IBC\s*(?:-\s*)?(Receipt|' + _ROMAN + r')(?![A-Z])')


def _stage(indicator) -> str:
    """'Stage II' -> 'II'."""
    return re.sub(r'(?i)^stage\s*', '', str(indicator or '').strip())


def _row(day, lst, r, stage, listed_key) -> dict:
    return {'date': day, 'list': lst, 'isin': str(r.get('isin') or '').strip(), 'symbol': str(r.get('symbol') or '').strip(),
            'company': r.get('companyName'), 'stage': stage, 'code': r.get('survCode'), 'description': r.get('survDesc'),
            'listed_at': r.get(listed_key)}


def parse_surveillance(asm, gsm, esm, day) -> pd.DataFrame:
    """The three NSE answers of one day as one long table (one row per list and ISIN)."""
    day, rows = pd.Timestamp(day), []
    for part, lst in (('longterm', 'asm_lt'), ('shortterm', 'asm_st')):
        for r in ((asm or {}).get(part) or {}).get('data') or []:
            rows.append(_row(day, lst, r, _stage(r.get('asmSurvIndicator')), 'asmTime'))
    for r in esm or []:
        rows.append(_row(day, 'esm', r, _stage(r.get('esmSurvIndicator')), 'esmTime'))
    for r in gsm or []:
        code = str(r.get('survCode') or '')
        m = _GSM.search(code)
        if m:
            rows.append(_row(day, 'gsm', r, m.group(1), 'gsmTime'))
        m = _IBC.search(code)
        if m:
            rows.append(_row(day, 'ibc', r, m.group(1), 'gsmTime'))
    df = pd.DataFrame(rows, columns=SURV_COLUMNS)
    return df[df['isin'] != ''].drop_duplicates(['date', 'list', 'isin'])


def parse_sec_list(body, day) -> pd.DataFrame:
    """NSE's security list with the price band per symbol and series."""
    raw = pd.read_csv(io.BytesIO(body if isinstance(body, bytes) else body.encode()), dtype=str, keep_default_na=False)
    raw.columns = [c.strip() for c in raw.columns]
    missing = [c for c in ('Symbol', 'Series', 'Band') if c not in raw.columns]
    if missing:
        raise ValueError(f'not NSE sec_list.csv, missing columns: {missing}')
    band = raw['Band'].str.strip()
    out = pd.DataFrame({'date': pd.Timestamp(day), 'symbol': raw['Symbol'].str.strip(), 'series': raw['Series'].str.strip(),
                        'band_pct': pd.to_numeric(band, errors='coerce'), 'band_text': band,
                        'remarks': raw.get('Remarks', pd.Series('', index=raw.index)).str.strip().replace({'-': ''})})
    return out.drop_duplicates(['date', 'symbol', 'series'])


def _since(dates: list, stages: pd.Series, now) -> tuple:
    """(first snapshot of the unbroken run that ends today with today's stage, run reaches our first snapshot)."""
    since = dates[-1]
    for d in reversed(dates):
        if stages.get(d) != now:
            return since, False
        since = d
    return since, True


def surveillance_now(hist: pd.DataFrame) -> pd.DataFrame:
    """Per ISIN and list in the latest snapshot: stage and since when (from our own daily snapshots)."""
    if hist is None or hist.empty:
        return pd.DataFrame(columns=['isin', 'list', 'stage', 'code', 'description', 'since', 'since_floor'])
    hist = hist.assign(date=pd.to_datetime(hist['date']))
    dates = sorted(hist['date'].unique())
    now = hist[hist['date'] == dates[-1]]
    by = {k: g.set_index('date')['stage'] for k, g in hist[hist['isin'].isin(now['isin'])].groupby(['isin', 'list'])}
    out = []
    for r in now.itertuples():
        since, floor = _since(dates, by[(r.isin, r.list)], r.stage)
        out.append({'isin': r.isin, 'list': r.list, 'stage': r.stage, 'code': r.code, 'description': r.description,
                    'since': since, 'since_floor': floor})
    return pd.DataFrame(out)


def circuit_days(px: pd.DataFrame, band: pd.Series, cfg: Config = CONFIG) -> pd.DataFrame:
    """Sessions in the last `cfg.circuit_window` where the stock traded at one price all day (open = high = low =
    close, volume > 0) and that price is the band limit: the move from the previous close is at least the band,
    less `circuit_tol_pct` points and one paisa for the tick. `band`: ISIN -> band % (today's). Stocks without a
    band (F&O names, 'No Band') are not judged. Returns per ISIN: days, last date and side of the last one."""
    cols = ['isin', 'circuit_days', 'circuit_last', 'circuit_last_side']
    if px is None or px.empty:
        return pd.DataFrame(columns=cols)
    days = sorted(px['date'].unique())[-cfg.circuit_window:]
    p = px[px['date'].isin(days)].reset_index(drop=True)
    p['band'] = p['isin'].map(band)
    one = (p['open'] == p['high']) & (p['high'] == p['low']) & (p['low'] == p['close']) & (p['volume'].fillna(0) > 0)
    move = (p['close'] / p['prev_close'] - 1) * 100
    need = p['band'] - cfg.circuit_tol_pct - 0.01 / p['prev_close'] * 100
    hit = p[one & p['band'].notna() & (p['prev_close'] > 0) & (move.abs() >= need)].assign(
        side=move.map(lambda m: 'upper' if m > 0 else 'lower'))
    if hit.empty:
        return pd.DataFrame(columns=cols)
    hit = hit.sort_values('date')
    g = hit.groupby('isin')
    return pd.DataFrame({'circuit_days': g['date'].nunique(), 'circuit_last': g['date'].max(),
                         'circuit_last_side': g['side'].last()}).reset_index()


def _run_start(series_by_day: pd.Series, members: tuple) -> tuple:
    """For one ISIN's series by date (sorted): first day of the unbroken run in `members` that ends on the last day."""
    since, floor = None, True
    for d, s in zip(reversed(series_by_day.index), reversed(series_by_day.values)):
        if s not in members:
            floor = False
            break
        since = d
    return since, floor


def build(surv_hist: pd.DataFrame | None, sec_list: pd.DataFrame | None, px: pd.DataFrame | None,
          cfg: Config = CONFIG) -> pd.DataFrame:
    """One row per ISIN in the latest NSE bhavcopy (equity series) or on a surveillance list today.
    `sec_list`: the latest NSE security list. `px`: NSE bhavcopy rows (prices/daily/nse), a few months."""
    px = pd.DataFrame() if px is None else px
    if not px.empty:
        px = px[(px['exchange'] == 'NSE') & px['series'].isin(cfg.equity_series)
                & (px['isin'].astype(str) != '')].reset_index(drop=True)
        px['date'] = pd.to_datetime(px['date'])
    last = (px.sort_values('date').drop_duplicates('isin', keep='last')[['isin', 'symbol', 'series', 'date']]
            .rename(columns={'date': 'last_price_date'}) if not px.empty
            else pd.DataFrame(columns=['isin', 'symbol', 'series', 'last_price_date']))
    surv = surveillance_now(surv_hist)
    out = pd.concat([last, surv[~surv['isin'].isin(last['isin'])][['isin']].drop_duplicates()], ignore_index=True)
    if not surv.empty and surv_hist is not None:
        ids = surv_hist.drop_duplicates('isin', keep='last').set_index('isin')['symbol']
        out['symbol'] = out['symbol'].fillna(out['isin'].map(ids))
    out['as_of'] = pd.to_datetime(surv_hist['date']).max() if surv_hist is not None and len(surv_hist) else pd.NaT
    for lst in LISTS:
        s = surv[surv['list'] == lst].set_index('isin')
        out[f'{lst}_stage'] = out['isin'].map(s['stage']) if len(s) else None
        out[f'{lst}_since'] = out['isin'].map(s['since']) if len(s) else pd.NaT
        out[f'{lst}_since_floor'] = out['isin'].map(s['since_floor']) if len(s) else None
    out['surveillance_codes'] = out['isin'].map(surv.groupby('isin')['code'].agg(lambda c: '; '.join(sorted({str(x) for x in c if x}))))
    out['trade_for_trade'] = out['series'].isin(cfg.t2t_series)
    out['sme'] = out['series'].isin(cfg.sme_series)
    runs = {}
    if not px.empty:
        t2t_isins = set(out.loc[out['trade_for_trade'], 'isin'])
        for i, g in px[px['isin'].isin(t2t_isins)].sort_values('date').groupby('isin'):
            runs[i] = _run_start(g.drop_duplicates('date', keep='last').set_index('date')['series'], cfg.t2t_series)
    out['t2t_since'] = out['isin'].map(lambda i: runs.get(i, (pd.NaT, None))[0])
    out['t2t_since_floor'] = out['isin'].map(lambda i: runs.get(i, (None, None))[1])
    out['band_pct'], out['band_text'], out['sec_list_date'] = float('nan'), None, pd.NaT
    if sec_list is not None and not sec_list.empty:
        sl = sec_list.drop_duplicates(['symbol', 'series']).set_index(['symbol', 'series'])
        key = list(zip(out['symbol'], out['series']))
        out['band_pct'] = [sl['band_pct'].get(k) for k in key]
        out['band_text'] = [sl['band_text'].get(k) for k in key]
        out['sec_list_date'] = pd.to_datetime(sec_list['date']).max()
    out['band_pct'] = pd.to_numeric(out['band_pct'], errors='coerce')
    cd = circuit_days(px, out.set_index('isin')['band_pct'].dropna(), cfg)
    out = out.merge(cd, on='isin', how='left')
    out['circuit_days'] = pd.to_numeric(out['circuit_days'], errors='coerce').fillna(0).astype(int)
    out['circuit_window'] = cfg.circuit_window
    flags = [_flags(r, cfg) for r in out.to_dict('records')]
    out['trade_flags'] = [[f for f, _ in x] for x in flags]
    out['trade_flag_notes'] = [[n for _, n in x] for x in flags]
    return out.sort_values('isin').reset_index(drop=True)


def _day(v) -> str:
    t = pd.to_datetime(v, errors='coerce')
    return '' if pd.isna(t) else t.strftime('%d %b %Y')


def _flags(r: dict, cfg: Config) -> list[tuple[str, str]]:
    """(short label, one-line explanation) per flag, the order a reader should weigh them."""
    out = []
    for lst in ('gsm', 'esm', 'asm_lt', 'asm_st', 'ibc'):
        st = r.get(f'{lst}_stage')
        if isinstance(st, str) and st:
            since = _day(r.get(f'{lst}_since'))
            when = (f', on the list since {"at least " if r.get(f"{lst}_since_floor") else ""}{since}' if since else '')
            out.append((LABEL[lst].format(st), f'{NAME[lst]}, stage {st}{when} (NSE)'))
    if r.get('trade_for_trade'):
        since = _day(r.get('t2t_since'))
        out.append(('T2T', f'Trade for trade (series {r.get("series")}): every trade is settled by delivery, no intraday'
                           + (f'; in this series since {"at least " if r.get("t2t_since_floor") else ""}{since}' if since else '')))
    if r.get('sme'):
        out.append(('SME', f'SME board (NSE Emerge, series {r.get("series")})'))
    b = r.get('band_pct')
    if b == b and b is not None and b <= cfg.tight_band_max_pct:
        out.append((f'{b:g}% band', f'Price band {b:g}%: the price can move at most {b:g}% from the previous close in a day'))
    n = int(r.get('circuit_days') or 0)
    if n:
        out.append((f'Circuit {n}/{cfg.circuit_window}',
                    f'Locked at the band on {n} of the last {cfg.circuit_window} sessions (one price all day), '
                    f'last {r.get("circuit_last_side")} on {_day(r.get("circuit_last"))}; judged on today\'s band'))
    return out
