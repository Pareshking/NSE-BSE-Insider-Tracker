"""Official industry classification, four levels, for every listed company (19 Nov 2026).

Both exchanges publish the same four-level scheme (macro-economic sector > sector > industry > basic industry):

* NSE: `/api/quote-equity?symbol=SYM`, key `industryInfo` with `macro`, `sector`, `industry`, `basicIndustry`.
  One call per symbol. NSE refused this code's container (Akamai 403, 19 Nov 2026), so it is read from GitHub's
  runners like every other NSE collector.
* BSE: `ComHeadernew/w?quotetype=EQ&scripcode=CODE&seriesid=`, the header of BSE's quote page, with `Sector`,
  `IndustryNew`, `IGroup`, `ISubGroup` (ABB, 500002: Industrials / Capital Goods / Electrical Equipment / Heavy
  Electrical Equipment, the same four names as NSE's). One call per scrip, fetched 19 Nov 2026 (fixtures in
  tests/fixtures/industry/). BSE's scrip master (`ListofScripData/w`, and its CSV `LitsOfScripCSVDownload/w`)
  gives the list of active scrips with ISIN, but its industry fields came back empty for all 5,141 scrips on
  19 Nov 2026 (`INDUSTRY` null; the CSV's last five columns blank), so it is read for the list only.
* `vr_master`: the Value Research export (reference_data/security_master_*.csv, 01 Sep 2026), two levels of its
  own vocabulary (`sector`, `industry`), used only for a company neither exchange classified. Its words are not
  NSE's ("Financial" against NSE's "Financial Services"), so `source` says which list a row's names come from.

NSE wins when both exchanges classify an ISIN. Nothing is inferred between levels or vocabularies.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pandas as pd

COLUMNS = ['isin', 'nse_symbol', 'bse_code', 'macro', 'sector', 'industry', 'basic_industry', 'source', 'as_of']
LEVELS = ['macro', 'sector', 'industry', 'basic_industry']
# archive/industry/{nse,bse}.parquet: the latest answer per symbol or scrip code
NSE_ARCHIVE_COLUMNS = ['nse_symbol', 'isin', *LEVELS, 'status', 'fetched_at']
BSE_ARCHIVE_COLUMNS = ['bse_code', 'isin', *LEVELS, 'status', 'fetched_at']
# status: ok (at least one level), no_industry (answered, no classification), not_found (the exchange does not
# know the symbol), error (answer not readable: not JSON, or not the expected shape)
OK = 'ok'
MAX_AGE_DAYS = 30     # an `ok` answer is fetched again after this many days
RETRY_DAYS = 7        # any other answer is tried again after this many days
_BLANK = {'', '-', 'NA', 'N/A', 'NULL', 'NONE', 'NAN'}


def _v(x) -> str | None:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    s = ' '.join(str(x).split())
    return None if s.upper() in _BLANK else s


def _company_isin(x) -> str | None:
    s = (_v(x) or '').upper()
    return s if len(s) == 12 and s.startswith('INE') else None


def parse_nse(payload, symbol: str) -> dict:
    """One quote-equity answer -> an archive row (without fetched_at)."""
    row = {'nse_symbol': str(symbol).strip().upper(), 'isin': None, **{k: None for k in LEVELS}, 'status': 'error'}
    if not isinstance(payload, dict):
        return row
    info = payload.get('info') if isinstance(payload.get('info'), dict) else {}
    meta = payload.get('metadata') if isinstance(payload.get('metadata'), dict) else {}
    row['isin'] = _v(info.get('isin')) or _v(meta.get('isin'))
    if not payload or (not info and not meta and 'industryInfo' not in payload):
        row['status'] = 'not_found'
        return row
    ind = payload.get('industryInfo') if isinstance(payload.get('industryInfo'), dict) else {}
    row.update(macro=_v(ind.get('macro')), sector=_v(ind.get('sector')), industry=_v(ind.get('industry')),
               basic_industry=_v(ind.get('basicIndustry')))
    row['status'] = OK if any(row[k] for k in LEVELS) else 'no_industry'
    return row


def parse_bse(payload, code) -> dict:
    """One ComHeadernew answer -> an archive row (without fetched_at). BSE answers an unknown code with every
    field null (999999 on 19 Nov 2026) and a scrip it does not classify with blanks (a fund unit, 543000)."""
    row = {'bse_code': str(code).strip(), 'isin': None, **{k: None for k in LEVELS}, 'status': 'error'}
    if not isinstance(payload, dict):
        return row
    if not _v(payload.get('SecurityCode')):
        row['status'] = 'not_found'
        return row
    row.update(isin=_v(payload.get('ISIN')), macro=_v(payload.get('Sector')), sector=_v(payload.get('IndustryNew')),
               industry=_v(payload.get('IGroup')), basic_industry=_v(payload.get('ISubGroup')))
    row['status'] = OK if any(row[k] for k in LEVELS) else 'no_industry'
    return row


def parse_bse_list(payload) -> pd.DataFrame:
    """BSE's active equity scrips (ListofScripData) with a company ISIN (INE...): fund units (INF) and partly
    paid lines (IN9) carry no industry and are left out."""
    rows = payload if isinstance(payload, list) else []
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        code, isin = _v(r.get('SCRIP_CD')), _company_isin(r.get('ISIN_NUMBER'))
        if code and isin:
            out.append({'bse_code': code, 'isin': isin, 'bse_symbol': _v(r.get('scrip_id')),
                        'name': _v(r.get('Scrip_Name')), 'bse_group': _v(r.get('GROUP'))})
    return pd.DataFrame(out, columns=['bse_code', 'isin', 'bse_symbol', 'name', 'bse_group']).drop_duplicates('bse_code')


# raw_v2 datasets that hold the answers (scripts/industry.py stores every answer there, write-once)
RAW_DATASETS = {'nse': ('nse', 'quote_equity'), 'bse': ('bse', 'comheadernew')}


def _key_from_url(url: str, name: str) -> str | None:
    from urllib.parse import parse_qs, urlsplit
    vals = parse_qs(urlsplit(url or '').query).get(name)
    return vals[0] if vals else None


def parse_raw(exchange: str, record: dict, body: bytes | None) -> dict | None:
    """One raw_v2 fetch record and the bytes it names -> an archive row (with fetched_at), the same row the fetch
    made when the answer arrived; None when the record is not an answer for one symbol or scrip (not HTTP 200, no
    symbol, or the bytes are missing). Used to rebuild archive/industry/ from raw after a run that was cut off before
    its answers reached the archive (19 and 20 Nov 2026)."""
    if not isinstance(record, dict) or body is None or int(record.get('http_status') or 0) != 200:
        return None
    covers = record.get('covers') if isinstance(record.get('covers'), dict) else {}
    params = record.get('params') if isinstance(record.get('params'), dict) else {}
    try:
        payload = json.loads(body.decode('utf-8', errors='replace'))
    except ValueError:
        payload = None   # an HTML page where JSON was due: the fetch recorded it as `error` too
    if exchange == 'nse':
        if '/api/quote-equity' not in str(record.get('url') or ''):
            return None
        key = _v(covers.get('symbol')) or _v(_key_from_url(record.get('url'), 'symbol'))
        row = parse_nse(payload, key) if key else None
    else:
        key = _v(covers.get('scripcode')) or _v(params.get('scripcode')) or _v(_key_from_url(record.get('url'), 'scripcode'))
        row = parse_bse(payload, key) if key else None
    if row is None:
        return None
    at = pd.to_datetime(record.get('fetched_at_utc'), errors='coerce', utc=True)
    if pd.isna(at):
        return None
    row['fetched_at'] = at.tz_convert(None).to_pydatetime()
    return row


def due(keys, archive: pd.DataFrame | None, key: str, now: datetime, limit: int | None,
        max_age_days: int = MAX_AGE_DAYS, retry_days: int = RETRY_DAYS) -> list[str]:
    """The keys to fetch this run: never fetched first, then the oldest stale ones; at most `limit`."""
    keys = list(dict.fromkeys(str(k).strip() for k in keys if _v(k)))
    seen = {}
    if archive is not None and not archive.empty:
        for r in archive[[key, 'status', 'fetched_at']].itertuples(index=False):
            seen[str(r[0])] = (r[1], pd.Timestamp(r[2]))
    fresh_ok, fresh_other = pd.Timestamp(now - timedelta(days=max_age_days)), pd.Timestamp(now - timedelta(days=retry_days))
    missing, stale = [], []
    for k in keys:
        if k not in seen:
            missing.append(k)
            continue
        status, at = seen[k]
        if pd.isna(at) or at < (fresh_ok if status == OK else fresh_other):
            stale.append((at if not pd.isna(at) else pd.Timestamp.min, k))
    todo = missing + [k for _, k in sorted(stale)]
    return todo if limit is None else todo[:max(0, int(limit))]


def merge(old: pd.DataFrame | None, new: pd.DataFrame | None, key: str, columns) -> pd.DataFrame:
    """The archive with `new` laid over it: the later answer for a key wins."""
    frames = [f for f in (old, new) if f is not None and not f.empty]
    if not frames:
        return pd.DataFrame(columns=columns)
    df = pd.concat([f.reindex(columns=columns) for f in frames], ignore_index=True)
    df['fetched_at'] = pd.to_datetime(df['fetched_at'])
    df[key] = df[key].astype(str)
    return df.sort_values('fetched_at', kind='stable').drop_duplicates(key, keep='last').reset_index(drop=True)


def _as_of(ts) -> pd.Timestamp:
    return pd.Timestamp(ts).normalize()


def build(nse: pd.DataFrame | None, bse: pd.DataFrame | None, securities: pd.DataFrame | None = None,
          vr: pd.DataFrame | None = None) -> tuple[pd.DataFrame, dict]:
    """clean/current/industry.parquet: one row per ISIN, NSE's classification, else BSE's, else the VR export's.
    `securities` (clean/current/securities.parquet) supplies the other exchange's identifier and places a VR row
    by symbol or code (as insiders_clean/securities.py does). Returns (table, counts)."""
    sec = securities if securities is not None else pd.DataFrame(columns=['isin', 'nse_symbol', 'bse_code'])
    sec = sec.reindex(columns=['isin', 'nse_symbol', 'bse_code']).dropna(subset=['isin'])
    sec = sec.assign(isin=sec['isin'].astype(str).str.strip()).drop_duplicates('isin')
    nse_of = {i: _v(s) for i, s in zip(sec['isin'], sec['nse_symbol'])}
    bse_of = {i: _v(str(c).removesuffix('.0')) if _v(c) else None for i, c in zip(sec['isin'], sec['bse_code'])}
    isin_by_nse = {s: i for i, s in nse_of.items() if s}
    isin_by_bse = {c: i for i, c in bse_of.items() if c}
    out: dict[str, dict] = {}
    counts = {'nse': 0, 'bse': 0, 'vr_master': 0}

    def add(isin, src, levels, as_of, nse_symbol=None, bse_code=None):
        out[isin] = {'isin': isin, 'nse_symbol': nse_of.get(isin) or nse_symbol,
                     'bse_code': bse_of.get(isin) or bse_code, **levels, 'source': src, 'as_of': as_of}
        counts[src] += 1

    for src, df, key, by in (('nse', nse, 'nse_symbol', isin_by_nse), ('bse', bse, 'bse_code', isin_by_bse)):
        if df is None or df.empty:
            continue
        for r in df[df['status'] == OK].sort_values('fetched_at').to_dict('records'):
            isin = _company_isin(r.get('isin')) or by.get(str(r[key]))
            if not isin or (isin in out and out[isin]['source'] == 'nse' and src == 'bse'):
                continue
            if isin in out and out[isin]['source'] == src:
                counts[src] -= 1   # two symbols of one ISIN: the later answer stands
            add(isin, src, {k: _v(r.get(k)) for k in LEVELS}, _as_of(r['fetched_at']),
                **({key: str(r[key])}))
    if vr is not None and not vr.empty:
        vr = vr.fillna('')
        vr_nse = {str(r['nse_symbol']).strip().upper(): r for r in vr.to_dict('records') if str(r.get('nse_symbol', '')).strip()}
        vr_bse = {str(r['bse_scrip_code']).strip(): r for r in vr.to_dict('records') if str(r.get('bse_scrip_code', '')).strip()}
        vr_isin = {str(r['isin']).strip(): r for r in vr.to_dict('records') if str(r.get('isin', '')).strip()}
        places = [(i, nse_of.get(i), bse_of.get(i)) for i in sec['isin']]
        if not places:   # no securities table: the export's own ISINs
            places = [(str(r['isin']).strip(), None, None) for r in vr.to_dict('records') if str(r.get('isin', '')).strip()]
        for isin, sym, code in places:
            if isin in out or not _company_isin(isin):
                continue
            r = vr_nse.get(sym or '') or vr_bse.get(code or '')
            if r is None and not sym and not code:
                r = vr_isin.get(isin)
            if r is None or not (_v(r.get('sector')) or _v(r.get('industry'))):
                continue
            as_of = pd.to_datetime(_v(r.get('date')), errors='coerce')
            add(isin, 'vr_master', {'macro': None, 'sector': _v(r.get('sector')), 'industry': _v(r.get('industry')),
                                    'basic_industry': None}, as_of,
                nse_symbol=_v(r.get('nse_symbol')), bse_code=_v(r.get('bse_scrip_code')))
    table = pd.DataFrame(list(out.values()), columns=COLUMNS)
    table['as_of'] = pd.to_datetime(table['as_of'])
    table = table.sort_values('isin').reset_index(drop=True)
    counts['rows'] = int(len(table))
    counts['securities_without_class'] = int(len(set(i for i in sec['isin'] if _company_isin(i)) - set(table['isin'])))
    return table, counts
