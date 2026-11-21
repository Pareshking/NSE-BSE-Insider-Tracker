"""Raw coverage audit (read-only): for every raw_v2 source and dataset, is everything in the raw bytes also in a table?

    python scripts/raw_coverage.py [--sources nse,bse,amc] [--sample 5] [--max-blobs 300] [--out artifacts/raw_coverage]

So the owner can decide, source by source, whether raw files could ever be deleted. Nothing here writes to or deletes
from R2: the R2 client is wrapped in `ReadOnly`, which offers only GET and LIST. Output goes to the job step summary
($GITHUB_STEP_SUMMARY when set) and to `--out` (report.md, report.json), which the workflow uploads as an artifact.

Datasets are found by listing R2 (raw_v2/{source}/{dataset}/{fetches|blobs}/..., the layout of
insiders_clean/raw_store.py), never from a fixed list. Each one found is matched to SPECS below, which names the
parser and the archive/clean table the code uses for it (read from the collectors; file names given in each spec):

* a spec with an adapter: the raw answers are parsed again by the collector's own parser (imported, never copied),
  and the rows are looked up in the table by the parser's own key;
* a spec without an adapter: the parser and table are named, the dataset is counted, and the verdict says why it
  was not re-parsed;
* no spec: "no parser found". Never skipped silently.

Per dataset: (1) counts: fetch records, distinct blobs, bytes, fetch days; rows in the re-parsed answers, rows the
parser yields, how many of them the table holds, rows the parser drops with its own reasons; (2) fields: raw field
names (JSON keys, CSV headers) against what the table keeps, as a column, inside a `raw_json` copy, or as a value
traced to a column; (3) values: `sample` random records, key fields raw -> parsed -> stored; (4) whether the source
still serves old data, quoted from the code or docs, else "unknown". Bounded by `max_blobs` distinct blobs per dataset
(a random sample when there are more, said in the verdict) and a time budget. One dataset failing is reported; the
others go on.
"""
from __future__ import annotations

import argparse
import csv
import fnmatch
import gzip
import io
import json
import os
import random
import re
import sys
import time
import zipfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

from insiders_clean import raw_store  # noqa: E402

RAW = raw_store.PREFIX + '/'
OLD_RAW = 'raw/'
WORKERS = 16
TRACE_ROWS = 300            # raw rows per dataset whose fields are traced into the table
RESERVOIR = 2000            # raw rows kept per dataset (a uniform random sample) for the field and value checks
MAX_LIST = 25               # lines of a list shown in markdown (the JSON has them all)
SKIP_COLUMNS = {'_key', 'first_seen', 'last_seen', 'ingested_at'}


# --- read-only R2 ---------------------------------------------------------------------------------------------------

class ReadOnly:
    """GET and LIST only. The wrapped client is private; there is no method that could write or delete."""

    def __init__(self, client, bucket: str | None):
        self.__client = client
        self.bucket = bucket or ''
        self.gets = 0
        self.lists = 0

    def get(self, key: str) -> bytes | None:
        self.gets += 1
        try:
            return self.__client.get_object(Bucket=self.bucket, Key=key)['Body'].read()
        except Exception as e:  # noqa: BLE001 - a missing key is an answer; anything else goes up
            if raw_store._missing(e):
                return None
            raise

    def list(self, prefix: str, delimiter: str | None = None) -> tuple[list[tuple[str, int]], list[str]]:
        objs, prefixes, token = [], [], None
        while True:
            kw = {'Bucket': self.bucket, 'Prefix': prefix}
            if delimiter:
                kw['Delimiter'] = delimiter
            if token:
                kw['ContinuationToken'] = token
            resp = self.__client.list_objects_v2(**kw)
            self.lists += 1
            objs += [(o['Key'], int(o.get('Size') or 0)) for o in resp.get('Contents', [])]
            prefixes += [p['Prefix'] for p in resp.get('CommonPrefixes', [])]
            if not resp.get('IsTruncated'):
                return objs, prefixes
            token = resp['NextContinuationToken']

    def blob(self, key: str) -> bytes | None:
        return raw_store.read_blob(self.get, key)

    def parquet(self, key: str) -> pd.DataFrame | None:
        body = self.get(key)
        return pd.read_parquet(io.BytesIO(body)) if body is not None else None


class TableMissing(Exception):
    pass


# --- value normalisation --------------------------------------------------------------------------------------------

_EMPTY = {'', '-', 'na', 'n.a.', 'none', 'null', 'nan', 'nat', '<na>'}
_NUM = re.compile(r'^[+-]?(\d{1,3}(,\d{2,3})+|\d+)?(\.\d+)?$')
_DATE_FORMATS = ('%d-%b-%Y', '%d-%m-%Y', '%d/%m/%Y', '%Y-%m-%d', '%d %b %Y', '%d-%b-%y', '%b %d %Y')
_TS_FORMATS = ('%d-%b-%Y %H:%M:%S', '%d-%b-%Y %H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M:%S.%f',
               '%d/%m/%Y %H:%M:%S', '%d-%m-%Y %H:%M:%S', '%Y-%m-%d %H:%M:%S%z', '%Y-%m-%dT%H:%M:%S%z')


def _num(x: float) -> str:
    return f'{float(x):.10g}'


def _when(dt) -> str:
    if getattr(dt, 'tzinfo', None) is not None:
        dt = dt.replace(tzinfo=None)
    if isinstance(dt, datetime) and (dt.hour, dt.minute, dt.second) != (0, 0, 0):
        return dt.strftime('%Y-%m-%d %H:%M')
    return dt.strftime('%Y-%m-%d')


def norm(v):
    """One spelling per value, so a raw '1,234' and a stored 1234.0, or '15-Oct-2025' and 2025-10-15, compare equal."""
    if v is None:
        return None
    if isinstance(v, (dict, list)):
        return json.dumps(v, sort_keys=True, default=str)
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, bool) or type(v).__name__ == 'bool_':
        return str(bool(v)).lower()
    if isinstance(v, (pd.Timestamp, datetime)):
        return _when(v.to_pydatetime() if isinstance(v, pd.Timestamp) else v)
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, (int, float)) or type(v).__module__ == 'numpy':
        try:
            return _num(v)
        except (TypeError, ValueError):
            return str(v)
    s = ' '.join(str(v).split())
    if s.lower() in _EMPTY:
        return None
    if _NUM.match(s) and any(c.isdigit() for c in s):
        return _num(s.replace(',', ''))
    if s.lower() in ('true', 'false'):
        return s.lower()
    if any(c.isdigit() for c in s) and len(s) <= 32:
        for fmt in _TS_FORMATS + _DATE_FORMATS:
            try:
                return _when(datetime.strptime(s, fmt))
            except ValueError:
                continue
    return s.casefold()


def _show(v, n=80) -> str:
    s = '' if v is None else str(v)
    return s if len(s) <= n else s[:n - 1] + '…'


# --- body helpers (reading only; parsing is the collectors') ---------------------------------------------------------

def json_rows(body: bytes, rec: dict | None = None) -> list[dict]:
    """The row list of a JSON answer, as the clients take it: a list, or the dict's `data` / `Table`."""
    data = json.loads(body.decode('utf-8', errors='replace'))
    if isinstance(data, dict):
        data = next((data[k] for k in ('data', 'Table') if isinstance(data.get(k), list)), [])
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []


def csv_rows(body: bytes, rec: dict | None = None) -> list[dict]:
    reader = csv.DictReader(io.StringIO(body.decode('utf-8-sig', errors='replace')))
    return [{k: v for k, v in r.items() if k is not None} for r in reader]


def rows_to_csv(rows: list[dict]) -> bytes:
    """Rows read by csv_rows back into a CSV, for a parser that takes the file's bytes (one row parsed at a time)."""
    if not rows:
        return b''
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=list(rows[0].keys()), extrasaction='ignore')
    w.writeheader()
    w.writerows(rows)
    return out.getvalue().encode('utf-8')


def col(name: str) -> Callable:
    return lambda df: df[name].astype(str)


def cols(*names: str) -> Callable:
    def key(df):
        parts = []
        for n in names:
            s = df[n]
            if n == 'date':
                s = pd.to_datetime(s, errors='coerce').dt.strftime('%Y-%m-%d')
            parts.append(s.astype(str).str.strip())
        out = parts[0]
        for p in parts[1:]:
            out = out + '|' + p
        return out
    return key


# --- stored tables ---------------------------------------------------------------------------------------------------

def _read_filtered(ro: ReadOnly, keys_of: Callable, wanted: set, parquet_keys: list[str]) -> pd.DataFrame:
    def one(k):
        df = ro.parquet(k)
        if df is None or df.empty:
            return None
        df = df.assign(_key=keys_of(df).values)
        return df[df['_key'].isin(wanted)]
    with ThreadPoolExecutor(WORKERS) as pool:
        frames = [f for f in pool.map(one, parquet_keys) if f is not None and len(f)]
    if not frames:
        return pd.DataFrame(columns=['_key'])
    return pd.concat(frames, ignore_index=True).drop_duplicates('_key', keep='last')


def partitioned(prefix: str, keys_of: Callable) -> Callable:
    """Every parquet under `prefix` (an archive's partitions), rows whose key is wanted."""
    def load(ro: ReadOnly, wanted: set, parsed: pd.DataFrame, recs: list) -> pd.DataFrame:
        found = sorted(k for k, _ in ro.list(prefix)[0] if k.endswith('.parquet'))
        if not found:
            raise TableMissing(f'no parquet under {prefix}')
        return _read_filtered(ro, keys_of, wanted, found)
    load.table = prefix
    return load


def monthly(prefix: str, keys_of: Callable, date_col: str = 'date') -> Callable:
    """{prefix}/{YYYY-MM}.parquet for the months the parsed rows fall in (the price layers)."""
    def load(ro, wanted, parsed, recs):
        months = sorted(pd.to_datetime(parsed[date_col], errors='coerce').dropna().dt.strftime('%Y-%m').unique())
        found = [f'{prefix}/{m}.parquet' for m in months]
        have = {k for k, _ in ro.list(prefix + '/')[0]}
        if not have:
            raise TableMissing(f'no parquet under {prefix}/')
        return _read_filtered(ro, keys_of, wanted, [k for k in found if k in have])
    load.table = prefix + '/{YYYY-MM}.parquet'
    return load


# --- specs -----------------------------------------------------------------------------------------------------------

@dataclass
class Spec:
    source: str
    dataset: str                        # fnmatch pattern on the dataset path under raw_v2/{source}/
    fmt: str                            # json, csv, xml (XBRL), spreadsheet, zip, html, text
    parser: str                         # the collector's parser, as named in the code
    table: str                          # the archive / clean table its rows land in
    refetch: str = 'unknown'            # what the code or docs say about the source serving old data (a quote)
    refetch_ref: str = ''               # file the quote is from
    level: str | None = None            # 'row' (row-level JSON/CSV), 'blob' (a file parsed whole), None (not wired)
    rows: Callable | None = None        # row: (body, rec) -> raw rows
    parse: Callable | None = None       # row: (rows, rec) -> (df, drops); blob: (body, rec) -> (df, drops, raw_rows)
    key: Callable | None = None         # parsed / stored df -> key Series
    stored: Callable | None = None      # (ro, wanted keys, parsed df, recs) -> stored rows with _key
    compare: dict | list = field(default_factory=dict)   # row: stored column -> raw field; blob: columns
    field_map: dict = field(default_factory=dict)        # raw field -> column, where the parser renames
    raw_fields: Callable | None = None  # blob: body -> (field names, file members not parsed)
    fields_note: str = ''               # blob formats where field-level comparison does not apply
    grouping: str = ''                  # the parser merges several raw rows into one by design
    why_not: str = ''                   # level None: why no adapter re-parses it here


def _nse_parsers():
    from collectors.nse_events import parsers
    return parsers


def _bse_parsers():
    from collectors.bse import parsers
    return parsers


def _nse_sast(rows, rec):
    return _nse_parsers().parse_sast(rows), {}


def _nse_actions(rows, rec):
    df, n = _nse_parsers().parse_corporate_actions(rows)
    return df, {'purpose not kept (parsers.action_purpose)': n}


def _nse_meetings(rows, rec):
    df, n = _nse_parsers().parse_board_meetings(rows)
    return df, {'no kept purpose (parsers._BM_FLAGS)': n}


def _nse_simple(fn_name):
    def parse(rows, rec):
        return getattr(_nse_parsers(), fn_name)(rows), {}
    return parse


def _bse_sast(rows, rec):
    df, extra = _bse_parsers().parse_sast(rows)
    return df, {f'regulation {k} not kept (parsers.SAST_KEPT)': n for k, n in extra['dropped_other_regulations'].items()}


def _bse_actions(rows, rec):
    df, n = _bse_parsers().parse_actions(rows)
    return df, {'purpose not kept (action_purpose)': n}


def _bse_meeting_rows(body, rec):
    data = json.loads(body.decode('utf-8', errors='replace'))
    data = data if isinstance(data, dict) else {}
    return [dict(r, __table=t) for t in ('Table', 'Table1') for r in (data.get(t) or []) if isinstance(r, dict)]


def _bse_meetings(rows, rec):
    payload = {'Table': [], 'Table1': []}
    for r in rows:
        payload[r.get('__table', 'Table')].append({k: v for k, v in r.items() if k != '__table'})
    df, counts = _bse_parsers().parse_board_meetings(payload)
    return df, {'meeting groups with no code, no date or no kept purpose (parsers.BM_FLAGS)': counts['dropped_other_purposes']}


def _bse_shareholding(rows, rec):
    return _bse_parsers().parse_shareholding_listing(rows), {}


def _market(rec) -> str:
    covers = rec.get('covers') or {}
    m = re.search(r'index=(\w+)', rec.get('url') or '')
    return covers.get('index') or (m.group(1) if m else 'equities')


def _nse_announcements(rows, rec):
    from collectors.nse_events import announcements as nann
    return nann.parse(rows, _market(rec)), {}


def _bse_announcements(rows, rec):
    from collectors.bse import announcements as bann
    df = bann.parse(rows)
    return df, {'no NEWSID (announcements.parse skips it)': len(rows) - len(df)}


def _canonical(exchange: str, category: str, mapped: list[dict]) -> pd.DataFrame:
    import r2_writer
    df = pd.DataFrame(mapped)
    df['canonical_event_id'] = [r2_writer.canonical_event_id(exchange, category, r) for r in mapped]
    return df


def _bse_insider(rows, rec):
    out = _bse_parsers().insider_rows(rows_to_csv(rows))
    return _canonical('bse', 'insider_trading', out), {'no security code (parsers.insider_rows skips it)': len(rows) - len(out)}


def _bse_deals(category):
    def parse(rows, rec):
        return _canonical('bse', category, _bse_parsers().deal_rows(rows)), {}
    return parse


def _nse_insider_history(rows, rec):
    from insiders_clean.history import pit_row
    return _canonical('nse', 'insider_trading', [pit_row(r) for r in rows]), {}


def _nse_deals(category):
    def parse(rows, rec):
        from insiders_clean import history
        out = history.deal_rows(rows_to_csv(rows))
        if rec.get('collector') != 'nse_history_backfill':     # the nightly's CSV rows (scripts/nse_deals_csv.py)
            import nse_deals_csv
            for r in out:
                r['source'] = nse_deals_csv.CSV_SOURCE
        return _canonical('nse', category, out), {'no symbol (history.deal_rows skips it)': len(rows) - len(out)}
    return parse


def _xml_text(body: bytes, rec: dict) -> str:
    return body.decode('utf-8', errors='replace')


def _nse_shp_xbrl(body, rec):
    params = rec.get('params') or {}
    try:
        facts = _nse_parsers().parse_shp_xbrl(_xml_text(body, rec))
    except ValueError as exc:
        return pd.DataFrame(columns=['record_id']), {f'parse_shp_xbrl: {exc}': 1}, 1
    return pd.DataFrame([dict(facts, record_id=str(params.get('record_id') or ''))]), {}, 1


def _house(rec):
    from collectors.mf_portfolios.houses import BY_KEY
    ds = rec.get('dataset') or ''
    house = BY_KEY.get(ds.split('/')[0])
    if house is None:
        raise KeyError(f'no house {ds.split("/")[0]!r} in collectors/mf_portfolios/houses.py')
    return house


def _mf_workbook(body, rec):
    from insiders_clean import mf_holdings
    house, month = _house(rec), (rec.get('covers') or {}).get('month')
    name = (rec.get('url') or '').split('?')[0].rsplit('/', 1)[-1]
    rows, rep = mf_holdings.parse_workbook(body, name, house.value_unit)
    sc = mf_holdings.scheme_holdings(rows, house.key, month, house.name)
    drops = {f'sheet skipped: {why}': n for why, n in rep.get('skipped', {}).items()}
    drops['non-equity lines (not in mf_schemes by design)'] = int(rep.get('lines', 0)) - int(rep.get('equity_lines', 0))
    drops['equity lines with no quantity (mf_holdings.holdings leaves them out)'] = int(rep.get('equity_lines_no_quantity', 0))
    merged = int(rep.get('equity_lines', 0)) - drops['equity lines with no quantity (mf_holdings.holdings leaves them out)'] - len(sc)
    if merged > 0:
        drops['equity lines summed into one scheme x ISIN row (scheme_holdings)'] = merged
    return sc, {k: v for k, v in drops.items() if v}, int(rep.get('lines', 0))


def _mf_stored(ro, wanted, parsed, recs):
    keys = sorted({f"archive/mf_schemes/month={(r.get('covers') or {}).get('month')}/{(r.get('dataset') or '').split('/')[0]}.parquet"
                   for r in recs})
    have = {k for k, _ in ro.list('archive/mf_schemes/')[0]}
    if not have:
        raise TableMissing('no parquet under archive/mf_schemes/')
    return _read_filtered(ro, cols('month', 'scheme_key', 'isin'), wanted, [k for k in keys if k in have])


_mf_stored.table = 'archive/mf_schemes/month={month}/{house}.parquet'


def _price(fn: str, exchange: str | None = None):
    def parse(body, rec):
        from insiders_clean import index_close, market_cap, prices
        if fn == 'udiff':
            df = prices.parse_udiff(body, exchange)
            raw_n = len(pd.read_csv(io.BytesIO(prices.csv_bytes(body)), dtype=str, keep_default_na=False))
        elif fn == 'mcap':
            df = market_cap.parse_mcap(body)
            raw_n = None
        else:
            df = index_close.parse_index(body)
            raw_n = len(pd.read_csv(io.BytesIO(body), dtype=str))
        return df, {}, raw_n
    return parse


def _udiff_fields(body):
    from insiders_clean import prices
    return list(pd.read_csv(io.BytesIO(prices.csv_bytes(body)), dtype=str, nrows=0).columns), []


def _mcap_fields(body):
    from insiders_clean import market_cap
    if body[:2] != b'PK':
        return [c.strip().lower() for c in pd.read_csv(io.BytesIO(body), dtype=str, nrows=0).columns], []
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        member = market_cap.mcap_member(z)
        fields = [c.strip().lower() for c in pd.read_csv(io.BytesIO(z.read(member)), dtype=str, nrows=0).columns]
        others = sorted({re.sub(r'\d+', '#', n) for n in z.namelist() if n != member})
    return fields, others


def _index_fields(body):
    return [c.strip().lower() for c in pd.read_csv(io.BytesIO(body), dtype=str, nrows=0).columns], []


def _map(module: str, name: str) -> dict:
    import importlib
    try:
        return dict(getattr(importlib.import_module(module), name))
    except Exception:  # noqa: BLE001 - a field map that cannot be read only weakens the field check
        return {}


def _bse_insider_map() -> dict:
    return _map('collectors.bse.parsers', 'INSIDER_FIELDS')


def _pit_map() -> dict:
    """insiders_clean.history: PIT_FIELDS renames, PIT_KEPT fields kept as history_{name}."""
    try:
        from insiders_clean import history
    except Exception:  # noqa: BLE001
        return {}
    return {**history.PIT_FIELDS, **{k: f'history_{k}' for k in history.PIT_KEPT}}


# collectors/bse/parsers.deal_rows writes these fields under the nightly row's names (its `out.append({...})`; the side
# 'P' / 'S' becomes BUY / SELL), so a value of TRANSACTION_TYPE is not found as written.
BSE_DEAL_FIELDS = {'DEAL_DATE': 'event_date', 'SCRIP_CODE': 'security_code', 'scripname': 'security_name',
                   'ScripName': 'security_name', 'CLIENT_NAME': 'person', 'TRANSACTION_TYPE': 'side',
                   'QUANTITY': 'quantity', 'PRICE': 'price'}
Q_NSE_MEETINGS = ('`from` = `2025-07-01`: one call per calendar month from that day to 60 days ahead', 'docs/CLEAN_LAYER.md')
Q_NSE_ACTIONS = ('`run_daily --dataset actions --from` now backfills NSE\'s actions a month per call.', 'docs/CLEAN_LAYER.md')
Q_NSE_SHP = ('a filing with no raw copy (fetched before 12 Oct 2026) is fetched again by the normal path whenever it is '
             'in the listing window (`days=400`', 'docs/CLEAN_LAYER.md')
Q_BSE_HISTORY = ('(SAST, corporate actions, board meetings, shareholding patterns) read BSE\'s own history endpoints',
                 'docs/CLEAN_LAYER.md')
Q_BSE_BACKFILL = ('`scripts/bse_history_backfill.py` (insider, bulk, block) and `collectors/bse/events.py`',
                  'docs/CLEAN_LAYER.md')
Q_NSE_INSIDER = ('NSE serves from 19 Nov 2015; NSE\'s new system from 03 May is the nightly\'s', 'docs/CLEAN_LAYER.md')
Q_NSE_DEALS = ('NSE serves bulk back to Jan 2004 and block to Nov 2005', 'scripts/nse_history_backfill.py')
Q_ANN = ('By hand: any date range, one job a month', '.github/workflows/announcement-collect.yml')
Q_PR_ZIP = ('NSE keeps the file at that URL', 'scripts/storage_trim.py')
Q_UDIFF = ('Backfill and nightly increment of daily UDiFF bhavcopy prices for NSE and BSE.', 'scripts/price_backfill.py')
Q_BSE_UDIFF = ("BSE's old bhavcopy URLs answered HTTP 200 with BSE's home page", 'insiders_clean/raw_store.py')


def _row(source, dataset, parser, table, parse, key, stored, compare, rows=json_rows, fmt='json', refetch=None,
         field_map=None, grouping=''):
    q, ref = refetch or ('unknown', '')
    return Spec(source, dataset, fmt, parser, table, q, ref, 'row', rows, parse, key, stored, compare,
                field_map or {}, grouping=grouping)


def _ev(prefix):
    return partitioned(prefix, col('event_id'))


def _canon(exchange, category):
    return partitioned(f'archive/canonical/{exchange}/{category}/', col('canonical_event_id'))


SPECS: list[Spec] = [
    # NSE corporate events (collectors/nse_events/run_daily.py: raw_hook stores each answer, parsers.* parse it,
    # merge_into_archive writes archive/nse_events/{stream}/year=YYYY.parquet by event_id)
    _row('nse', 'sast', 'collectors.nse_events.parsers.parse_sast', 'archive/nse_events/sast/', _nse_sast,
         col('event_id'), _ev('archive/nse_events/sast/'),
         {'symbol': 'symbol', 'application_no': 'application_no', 'regulation': 'regType', 'mode': 'acquisitionMode',
          'shares_acquired': 'noOfShareAcq', 'shares_sold': 'noOfShareSale', 'shares_after': 'noOfShareAft',
          'post_stake_pct': 'totAftShare'}),
    _row('nse', 'actions', 'collectors.nse_events.parsers.parse_corporate_actions', 'archive/nse_events/actions/',
         _nse_actions, col('event_id'), _ev('archive/nse_events/actions/'),
         {'symbol': 'symbol', 'isin': 'isin', 'series': 'series', 'subject': 'subject', 'ex_date': 'exDate',
          'record_date': 'recDate', 'face_value': 'faceVal'}, refetch=Q_NSE_ACTIONS),
    _row('nse', 'meetings', 'collectors.nse_events.parsers.parse_board_meetings', 'archive/nse_events/meetings/',
         _nse_meetings, col('event_id'), _ev('archive/nse_events/meetings/'),
         {'symbol': 'bm_symbol', 'isin': 'sm_isin', 'meeting_date': 'bm_date'}, refetch=Q_NSE_MEETINGS,
         grouping='one row per symbol and meeting date (rows of one meeting combined)'),
    _row('nse', 'encumbrances', 'collectors.nse_events.parsers.parse_encumbrances', 'archive/nse_events/encumbrances/',
         _nse_simple('parse_encumbrances'), col('event_id'), _ev('archive/nse_events/encumbrances/'),
         {'symbol': 'symbol', 'lender': 'eventDetailsEntity', 'shares': 'eventDetailsHolding',
          'pct_of_company': 'eventDetailsPerc', 'post_event_holding': 'postEventHolding'}),
    _row('nse', 'daily_buybacks', 'collectors.nse_events.parsers.parse_daily_buybacks',
         'archive/nse_events/daily_buybacks/', _nse_simple('parse_daily_buybacks'), col('event_id'),
         _ev('archive/nse_events/daily_buybacks/'),
         {'symbol': 'symbol', 'attachment': 'attchmntFile', 'text': 'attchmntText'}),
    _row('nse', 'tenders', 'collectors.nse_events.parsers.parse_tender_offers', 'archive/nse_events/tenders/',
         _nse_simple('parse_tender_offers'), col('event_id'), _ev('archive/nse_events/tenders/'),
         {'symbol': 'symbol', 'series': 'series', 'offer_type_raw': 'offerType', 'shares_sought': 'issueSize',
          'shares_tendered': 'totQty'}),
    _row('nse', 'shareholding_list', 'collectors.nse_events.parsers.parse_shareholding_listing',
         'archive/nse_events/shareholding/', _nse_simple('parse_shareholding_listing'), col('event_id'),
         _ev('archive/nse_events/shareholding/'),
         {'record_id': 'recordId', 'symbol': 'symbol', 'isin': 'isin', 'quarter_end': 'date',
          'promoter_holding_pct': 'pr_and_prgrp', 'public_holding_pct': 'public_val', 'xbrl_url': 'xbrl'},
         refetch=Q_NSE_SHP),
    Spec('nse', 'shareholding_xbrl', 'xml', 'collectors.nse_events.parsers.parse_shp_xbrl',
         'archive/nse_events/shareholding/ (by record_id)', *Q_NSE_SHP, 'blob', None, _nse_shp_xbrl, col('record_id'),
         partitioned('archive/nse_events/shareholding/', col('record_id')),
         ['promoter_shares', 'total_shares', 'promoter_pledged_shares', 'promoter_encumbered_shares', 'promoter_pledge_pct'],
         fields_note='XBRL: field-level comparison not applicable. Re-run here: parse_shp_xbrl (promoter, public and '
                     'total shares, pledges). The same file also feeds parse_shp_members, parse_shp_categories and '
                     'parse_shp_public_holders, which are not re-run here.'),
    # BSE corporate events (collectors/bse/client.py stores each answer; collectors/bse/events.py parses and merges
    # into archive/bse_events/{stream}/year=YYYY.parquet by event_id)
    _row('bse', 'sast', 'collectors.bse.parsers.parse_sast', 'archive/bse_events/sast/', _bse_sast, col('event_id'),
         _ev('archive/bse_events/sast/'),
         {'bse_code': 'scrip_code', 'shares_after': 'Acquisition_After', 'post_stake_pct': 'Acquisition_Pct_After',
          'mode': 'FLD_MODE'}, refetch=Q_BSE_HISTORY),
    _row('bse', 'corporate_actions', 'collectors.bse.parsers.parse_actions', 'archive/bse_events/actions/', _bse_actions,
         col('event_id'), _ev('archive/bse_events/actions/'),
         {'bse_code': 'scrip_code', 'subject': 'Purpose', 'ex_date': 'Ex_date', 'record_date': 'RD_Date'},
         refetch=Q_BSE_HISTORY),
    _row('bse', 'board_meetings', 'collectors.bse.parsers.parse_board_meetings', 'archive/bse_events/meetings/',
         _bse_meetings, col('event_id'), _ev('archive/bse_events/meetings/'),
         {'bse_code': 'scrip_code', 'meeting_date': 'MEETING_BOARD_DATE'}, rows=_bse_meeting_rows,
         refetch=Q_BSE_HISTORY, grouping='one row per scrip code and meeting date (purposes combined)'),
    _row('bse', 'shareholding_filings', 'collectors.bse.parsers.parse_shareholding_listing',
         'archive/bse_events/shareholding/', _bse_shareholding, col('event_id'), _ev('archive/bse_events/shareholding/'),
         {'bse_code': 'FLD_ScripCode', 'quarter_end': 'EndDate'}, refetch=Q_BSE_HISTORY),
    # Announcements (collectors/{nse_events,bse}/announcements.py; scripts/announcements_from_raw.py reads raw the same way)
    _row('nse', 'announcements', 'collectors.nse_events.announcements.parse', 'archive/announcements/nse/',
         _nse_announcements, col('event_id'), _ev('archive/announcements/nse/'),
         {'seq_id': 'seq_id', 'symbol': 'symbol', 'isin': 'sm_isin', 'company': 'sm_name', 'subject': 'desc',
          'text': 'attchmntText'}, refetch=Q_ANN),
    _row('bse', 'announcements', 'collectors.bse.announcements.parse', 'archive/announcements/bse/',
         _bse_announcements, col('event_id'), _ev('archive/announcements/bse/'),
         {'news_id': 'NEWSID', 'bse_code': 'SCRIP_CD', 'subject': 'NEWSSUB', 'headline': 'HEADLINE',
          'category': 'CATEGORYNAME', 'subcategory': 'SUBCATNAME'}, refetch=Q_ANN),
    # Insider trades and deals from the history endpoints (scripts/{nse,bse}_history_backfill.py -> r2_writer's
    # rows_to_parquet_bytes -> archive/canonical/{exchange}/{category}/ by canonical_event_id)
    _row('bse', 'insider_csv', 'collectors.bse.parsers.insider_rows -> r2_writer.rows_to_parquet_bytes',
         'archive/canonical/bse/insider_trading/', _bse_insider, col('canonical_event_id'),
         _canon('bse', 'insider_trading'),
         {'security_code': 'Security Code', 'person': 'Name of Person', 'quantity':
          'Number of Securities Acquired/Disposed/Pledge etc.', 'broadcast_date': 'Reported to Exchange'},
         rows=csv_rows, fmt='csv', refetch=Q_BSE_BACKFILL, field_map=None),
    _row('bse', 'bulk_deals_history', 'collectors.bse.parsers.deal_rows -> r2_writer.rows_to_parquet_bytes',
         'archive/canonical/bse/bulk_deals/', _bse_deals('bulk_deals'), col('canonical_event_id'),
         _canon('bse', 'bulk_deals'),
         {'security_code': 'SCRIP_CODE', 'person': 'CLIENT_NAME', 'quantity': 'QUANTITY', 'price': 'PRICE',
          'event_date': 'DEAL_DATE'}, refetch=Q_BSE_BACKFILL),
    _row('bse', 'block_deals_history', 'collectors.bse.parsers.deal_rows -> r2_writer.rows_to_parquet_bytes',
         'archive/canonical/bse/block_deals/', _bse_deals('block_deals'), col('canonical_event_id'),
         _canon('bse', 'block_deals'),
         {'security_code': 'SCRIP_CODE', 'person': 'CLIENT_NAME', 'quantity': 'QUANTITY', 'price': 'PRICE',
          'event_date': 'DEAL_DATE'}, refetch=Q_BSE_BACKFILL),
    _row('nse', 'insider', 'insiders_clean.history.pit_row -> r2_writer.rows_to_parquet_bytes',
         'archive/canonical/nse/insider_trading/', _nse_insider_history, col('canonical_event_id'),
         _canon('nse', 'insider_trading'),
         {'symbol': 'symbol', 'companyName': 'company', 'acqName': 'acqName', 'acqfromDt': 'acqfromDt',
          'acqtoDt': 'acqtoDt', 'intimDt': 'intimDt', 'broadcastDt': 'date'}, refetch=Q_NSE_INSIDER),
    _row('nse', 'bulk_deals', 'insiders_clean.history.deal_rows -> r2_writer.rows_to_parquet_bytes',
         'archive/canonical/nse/bulk_deals/', _nse_deals('bulk_deals'), col('canonical_event_id'),
         _canon('nse', 'bulk_deals'),
         {'BD_DT_DATE': 'Date', 'BD_SYMBOL': 'Symbol', 'BD_CLIENT_NAME': 'Client Name', 'BD_BUY_SELL': 'Buy / Sell',
          'BD_QTY_TRD': 'Quantity Traded', 'BD_TP_WATP': 'Trade Price / Wght. Avg. Price'},
         rows=csv_rows, fmt='csv', refetch=Q_NSE_DEALS),
    _row('nse', 'block_deals', 'insiders_clean.history.deal_rows -> r2_writer.rows_to_parquet_bytes',
         'archive/canonical/nse/block_deals/', _nse_deals('block_deals'), col('canonical_event_id'),
         _canon('nse', 'block_deals'),
         {'BD_DT_DATE': 'Date', 'BD_SYMBOL': 'Symbol', 'BD_CLIENT_NAME': 'Client Name', 'BD_BUY_SELL': 'Buy / Sell',
          'BD_QTY_TRD': 'Quantity Traded', 'BD_TP_WATP': 'Trade Price / Wght. Avg. Price'},
         rows=csv_rows, fmt='csv', refetch=Q_NSE_DEALS),
    # Fund-house month-end portfolios (scripts/mf_portfolios.py: raw_rows / run_house)
    Spec('amc', '*/portfolio_month', 'spreadsheet',
         'insiders_clean.mf_holdings.parse_workbook -> scheme_holdings', _mf_stored.table, 'unknown', '', 'blob', None,
         _mf_workbook, cols('month', 'scheme_key', 'isin'), _mf_stored, ['shares', 'value_lakh', 'name'],
         fields_note='Spreadsheet (xls/xlsx/zip of workbooks): field-level comparison not applicable. Extracted per '
                     'holding line: sheet, scheme, ISIN, name, quantity, value, % of AUM; the table keeps equity lines '
                     'with a quantity, summed per scheme and ISIN.'),
    # Exchange files for the price layers (scripts/price_backfill.py SOURCES)
    Spec('exchange_files', 'nse_udiff_cm', 'zip', 'insiders_clean.prices.parse_udiff', 'prices/daily/nse/{YYYY-MM}.parquet',
         *Q_UDIFF, 'blob', None, _price('udiff', 'NSE'), cols('date', 'exchange', 'isin', 'symbol', 'series'),
         monthly('prices/daily/nse', cols('date', 'exchange', 'isin', 'symbol', 'series')),
         ['open', 'high', 'low', 'close', 'volume'], raw_fields=_udiff_fields,
         field_map=_map('insiders_clean.prices', '_MAP')),
    Spec('exchange_files', 'bse_udiff_cm', 'csv', 'insiders_clean.prices.parse_udiff', 'prices/daily/bse/{YYYY-MM}.parquet',
         *Q_BSE_UDIFF, 'blob', None, _price('udiff', 'BSE'), cols('date', 'exchange', 'isin', 'symbol', 'series'),
         monthly('prices/daily/bse', cols('date', 'exchange', 'isin', 'symbol', 'series')),
         ['open', 'high', 'low', 'close', 'volume'], raw_fields=_udiff_fields,
         field_map=_map('insiders_clean.prices', '_MAP')),
    Spec('exchange_files', 'nse_pr_zip', 'zip', 'insiders_clean.market_cap.parse_mcap (mcap member only)',
         'marketcap/daily/nse/{YYYY-MM}.parquet', *Q_PR_ZIP, 'blob', None, _price('mcap'), cols('date', 'symbol', 'series'),
         monthly('marketcap/daily/nse', cols('date', 'symbol', 'series')), ['issue_size', 'close', 'market_cap'],
         raw_fields=_mcap_fields, field_map=_map('insiders_clean.market_cap', '_MAP')),
    Spec('exchange_files', 'nse_index_close', 'csv', 'insiders_clean.index_close.parse_index',
         'indices/daily/nse/{YYYY-MM}.parquet', 'unknown', '', 'blob', None, _price('index'), cols('date', 'symbol'),
         monthly('indices/daily/nse', cols('date', 'symbol')), ['close'], raw_fields=_index_fields,
         field_map=_map('insiders_clean.index_close', '_MAP')),
]

# Mapped from the code, no adapter here (parser and table named; counted; verdict says why).
_NOT_WIRED = [
    ('nse', 'announcements_xbrl', 'json', 'collectors.nse_events.announcements.parse_xbrl', 'not traced',
     'companion rows; how they are merged was not traced for this audit'),
    ('nse', 'announcements_integrated', 'json', 'collectors.nse_events.announcements.parse_integrated_xbrl', 'not traced',
     'companion rows; how they are merged was not traced for this audit'),
    ('nse', 'further_issues', 'json', 'collectors.nse_events.run_daily.issue_filings', 'archive/nse_events/issues/',
     'list rows are joined to their XBRL before archiving; a row-level adapter is not written'),
    ('nse', 'further_issue_xbrl', 'xml', 'insiders_clean.issues.parse_xbrl', 'archive/nse_events/issues/',
     'XBRL facts land on the issue row; an adapter is not written'),
    ('nse', 'results_list', 'json', 'collectors.nse_events.run_daily.results_filings', 'archive/nse_events/results/',
     'list rows are joined to their XBRL before archiving; an adapter is not written'),
    ('nse', 'results_xbrl', 'xml', 'insiders_clean.results.parse_xbrl', 'archive/nse_events/results/',
     'blobs of read filings were deleted by scripts/storage_trim.py (results_xbrl step); an adapter is not written'),
    ('nse', 'insider_filing_list', 'json', 'scripts/nse_insider.py fetch_filing_list -> to_row',
     'archive/canonical/nse/insider_trading/', 'a row is the list entry joined to its XBRL; an adapter is not written'),
    ('nse', 'insider_xbrl', 'xml', 'scripts/nse_insider.py parse_disclosures -> to_row',
     'archive/canonical/nse/insider_trading/', 'XBRL joined to the list entry; an adapter is not written'),
    ('nse', 'preferential_issue', 'json', 'scripts/nse_preferential.py', 'canonical/nse/ (dated snapshots, not archived)',
     'docs/CLEAN_LAYER.md: the rights and preferential snapshots in canonical/ are not archived'),
    ('nse', 'rights_issue', 'json', 'scripts/nse_rights.py', 'canonical/nse/ (dated snapshots, not archived)',
     'docs/CLEAN_LAYER.md: the rights and preferential snapshots in canonical/ are not archived'),
    ('nse', 'asm', 'json', 'insiders_clean.tradability.parse_surveillance (asm, gsm, esm of one day together)',
     'archive/tradability/surveillance/', 'the three lists of a day are parsed together; an adapter is not written'),
    ('nse', 'gsm', 'json', 'insiders_clean.tradability.parse_surveillance', 'archive/tradability/surveillance/',
     'the three lists of a day are parsed together; an adapter is not written'),
    ('nse', 'esm', 'json', 'insiders_clean.tradability.parse_surveillance', 'archive/tradability/surveillance/',
     'the three lists of a day are parsed together; an adapter is not written'),
    ('nse', 'sec_list', 'csv', 'insiders_clean.tradability.parse_sec_list', 'archive/tradability/sec_list/',
     'one snapshot a day; an adapter is not written'),
    ('nse', 'fiidii_*', 'json', 'insiders_clean.market_flows.parse_nse', 'archive/market_flows/nse/',
     'an adapter is not written'),
    ('nsdl', 'fpi_daily', 'html', 'insiders_clean.market_flows.parse_nsdl_daily', 'archive/market_flows/nsdl/',
     'HTML page: an adapter is not written'),
    ('nsdl', 'fpi_sector*', 'html', 'insiders_clean.market_flows.parse_nsdl_sectors', 'archive/market_flows/nsdl_sector/',
     'HTML page: an adapter is not written'),
    ('sebi', 'mf_trends', 'html', 'insiders_clean.market_flows.parse_sebi', 'archive/market_flows/sebi/',
     'HTML page: an adapter is not written'),
    ('nse', 'quote_equity', 'json', 'insiders_clean.industry.parse_raw (parse_nse)', 'archive/industry/nse.parquet',
     'the archive keeps only the latest answer per symbol, so older answers differ by design; an adapter is not written'),
    ('bse', 'comheadernew', 'json', 'insiders_clean.industry.parse_raw (parse_bse)', 'archive/industry/bse.parquet',
     'the archive keeps only the latest answer per scrip code; an adapter is not written'),
    ('bse', 'scrip_list', 'json', 'insiders_clean.industry.parse_bse_list', 'archive/industry/bse.parquet',
     'an adapter is not written'),
    ('bse', 'shareholding_xbrl', 'xml', 'collectors.bse.parsers.ixbrl_facts -> collectors.nse_events.parsers.parse_shp_xbrl',
     'archive/bse_events/shareholding/', 'inline XBRL joined to its listing row by URL; an adapter is not written'),
    ('amfi', 'nav_history', 'text', 'insiders_clean.mf_holdings.parse_amfi_nav', 'archive/amfi_schemes/',
     'an adapter is not written'),
    ('bse', 'bulkdeal_beta', 'json', 'scripts/bse_raw_capture_v2.py bulk_block_row -> bse_validate.normalize',
     'archive/canonical/bse/bulk_deals/', 'nightly page capture; an adapter is not written'),
    ('bse', 'blockdeal_beta', 'json', 'scripts/bse_raw_capture_v2.py bulk_block_row -> bse_validate.normalize',
     'archive/canonical/bse/block_deals/', 'nightly page capture; an adapter is not written'),
    ('bse', 'getcorp_regulation_ng', 'json', 'scripts/bse_raw_capture_v2.py insider_row -> bse_validate.normalize',
     'archive/canonical/bse/insider_trading/', 'nightly page capture; an adapter is not written'),
    ('bse', 'pubissues_furtherissuesummary_*', 'json', 'scripts/bse_raw_capture_v2.py',
     'canonical/bse/ (dated snapshots, not archived)', 'nightly page capture; an adapter is not written'),
]
SPECS += [Spec(s, d, f, p, t, why_not=w) for s, d, f, p, t, w in _NOT_WIRED]
for _s in SPECS:       # field maps read from the parsers' own modules
    if _s.source == 'bse' and _s.dataset == 'insider_csv':
        _s.field_map = _bse_insider_map()
    if _s.source == 'nse' and _s.dataset == 'insider':
        _s.field_map = _pit_map()
    if _s.source == 'nse' and _s.dataset in ('bulk_deals', 'block_deals'):
        _s.field_map = _map('insiders_clean.history', 'DEAL_FIELDS')
    if _s.source == 'bse' and _s.dataset in ('bulk_deals_history', 'block_deals_history'):
        _s.field_map = BSE_DEAL_FIELDS


def spec_for(source: str, dataset: str) -> Spec | None:
    return next((s for s in SPECS if s.source == source and fnmatch.fnmatchcase(dataset, s.dataset)), None)


# --- discovery ---------------------------------------------------------------------------------------------------------

def _dataset_of(key: str) -> tuple[str, str, str] | None:
    """raw_v2/{source}/{dataset...}/{fetches|blobs}/... -> (source, dataset, kind)."""
    parts = key.split('/')
    for i in range(2, len(parts) - 1):
        if parts[i] in ('fetches', 'blobs'):
            return parts[1], '/'.join(parts[2:i]), parts[i]
    return None


def discover(ro: ReadOnly, sources: set | None) -> dict:
    """{(source, dataset): {'fetches': [(key, size)], 'blobs': [...], 'other': [...]}} from listing raw_v2/."""
    _, prefixes = ro.list(RAW, delimiter='/')
    found: dict = {}
    for p in sorted(prefixes):
        src = p[len(RAW):].strip('/')
        if sources and src not in sources:
            continue
        objs, _ = ro.list(p)
        for key, size in objs:
            got = _dataset_of(key)
            if got is None:
                found.setdefault((src, '(outside the raw_store layout)'), {'fetches': [], 'blobs': [], 'other': []})['other'].append((key, size))
                continue
            s, ds, kind = got
            found.setdefault((s, ds), {'fetches': [], 'blobs': [], 'other': []})[kind].append((key, size))
    return found


def inventory(objs: dict) -> dict:
    fetches = [(k, s) for k, s in objs['fetches'] if k.endswith('.json')]
    days = sorted({k.split('/fetches/', 1)[1].split('/', 1)[0] for k, _ in fetches if '/fetches/' in k})
    shas = {}
    for k, s in objs['blobs']:
        name = k.rsplit('/', 1)[-1]
        shas.setdefault(name.split('.', 1)[0], 0)
        shas[name.split('.', 1)[0]] += s
    prefixes = {sha[:12] for sha in shas}
    no_blob = sum(1 for k, _ in fetches if k.rsplit('_', 1)[-1][:-5] not in prefixes)
    return {'fetch_records': len(fetches), 'fetch_days': len(days), 'first_day': days[0] if days else None,
            'last_day': days[-1] if days else None, 'distinct_blobs': len(shas),
            'blob_bytes': sum(shas.values()), 'fetch_bytes': sum(s for _, s in objs['fetches']),
            'other_objects': len(objs['other']), 'records_without_blob_by_name': no_blob}


# --- one dataset -----------------------------------------------------------------------------------------------------

def _records(ro: ReadOnly, fetch_keys: list[str], max_blobs: int, rng: random.Random) -> tuple[list[dict], int, bool]:
    """Fetch records in random order until `max_blobs` distinct blobs are named (or all are read).
    Returns (records read, records listed, bounded)."""
    keys = list(fetch_keys)
    rng.shuffle(keys)
    cap = max(max_blobs * 5, 50)
    out, blobs, read = [], set(), 0
    batch = max(WORKERS * 4, 64)
    with ThreadPoolExecutor(WORKERS) as pool:
        while read < len(keys) and len(blobs) < max_blobs and read < cap:
            chunk = keys[read:read + batch]
            read += len(chunk)
            for k, body in zip(chunk, pool.map(ro.get, chunk)):
                try:
                    rec = json.loads(body) if body else None
                except ValueError:
                    rec = None
                if not isinstance(rec, dict):
                    out.append({'fetch_key': k, '_unreadable': True})
                    continue
                rec['fetch_key'] = k
                out.append(rec)
                if rec.get('blob_key') and len(blobs) < max_blobs:
                    blobs.add(rec['blob_key'])
    return out, len(keys), read < len(keys)


def _body(ro: ReadOnly, rec: dict) -> tuple[bytes | None, str]:
    """The bytes as sent and '' , or None and why not. Checks the SHA-256 the record names."""
    data = ro.blob(rec['blob_key'])
    if data is None:
        return None, 'blob missing'
    params = rec.get('params') or {}
    if params.get('stored_as') == 'gzip' and rec['blob_key'].endswith('.gz'):    # gzipped by the collector itself
        if raw_store.sha256_hex(data) != rec.get('sha256'):
            return None, 'sha256 differs from the record'
        try:
            data = gzip.decompress(data)
        except OSError:
            return None, 'gzip unreadable'
        want = params.get('sha256_as_sent')
        if want and raw_store.sha256_hex(data) != want:
            return None, 'sha256 differs from the record'
        return data, ''
    if raw_store.sha256_hex(data) != rec.get('sha256'):
        return None, 'sha256 differs from the record'
    return data, ''


def _trace(raw_row: dict, stored_row: dict | None, parsed_row: dict | None, field_map: dict) -> dict:
    """Each raw field with a value -> 'column', 'raw_json', 'value' (its value found in a stored column) or 'no'."""
    target = stored_row if stored_row is not None else (parsed_row or {})
    cols_ = {c for c in target if c not in SKIP_COLUMNS}
    values = {norm(v) for c, v in target.items() if c not in SKIP_COLUMNS and c != 'raw_json'}
    inside: set = set()
    rj = target.get('raw_json')
    if isinstance(rj, str) and rj:
        try:
            obj = json.loads(rj)
            for o in (obj if isinstance(obj, list) else [obj]):
                if isinstance(o, dict):
                    inside |= set(o)
        except ValueError:
            pass
    lower_map = {str(k).strip().lower(): v for k, v in field_map.items()}
    out = {}
    for f, v in raw_row.items():
        if str(f).startswith('__') or norm(v) is None:
            continue
        mapped = field_map.get(f) or lower_map.get(' '.join(str(f).split()).lower())
        if f in cols_ or (mapped and mapped in cols_):
            out[f] = 'column'
        elif f in inside:
            out[f] = 'raw_json'
        elif norm(v) in values:
            out[f] = 'value'
        else:
            out[f] = 'no'
    return out


def _raw_value(row: dict, name: str):
    if name in row:
        return row[name]
    want = ' '.join(name.split()).lower()
    for k, v in row.items():
        if ' '.join(str(k).split()).lower() == want:
            return v
    return None


def audit_dataset(ro: ReadOnly, source: str, dataset: str, objs: dict, sample: int, max_blobs: int,
                  seed: int = 0, max_seconds: float = float('inf')) -> dict:
    spec = spec_for(source, dataset)
    inv = inventory(objs)
    res = {'source': source, 'dataset': dataset, 'inventory': inv, 'format': spec.fmt if spec else None,
           'parser': spec.parser if spec else None, 'table': spec.table if spec else None,
           'refetch': spec.refetch if spec else 'unknown', 'refetch_ref': spec.refetch_ref if spec else ''}
    if spec is None:
        res['verdict'] = 'no parser found'
        res['gaps'] = ['no parser or table for this dataset was found in the code']
        return res
    if spec.level is None:
        res['verdict'] = f'not checked: {spec.why_not}'
        return res
    rng = random.Random(f'{seed}:{source}/{dataset}')
    recs, listed, more = _records(ro, [k for k, _ in objs['fetches'] if k.endswith('.json')], max_blobs, rng)
    rs = Counter()
    by_blob: dict = {}
    for r in recs:
        if r.get('_unreadable'):
            rs['unreadable_records'] += 1
            continue
        if int(r.get('http_status') or 0) != 200:
            rs['non_200_records'] += 1
            continue
        if r.get('content_check'):
            rs[f"content_check:{r['content_check']}"] += 1
            continue
        if r.get('blob_key'):
            by_blob.setdefault(r['blob_key'], r)
    blobs = list(by_blob.items())[:max_blobs]
    res['records_read'] = len(recs)
    res['record_status'] = dict(rs)
    raw_rows: list[tuple[dict, dict]] = []      # (raw row, record): a uniform random sample of RESERVOIR rows
    seen_rows = 0
    frames, drops, errors, body_status = [], Counter(), Counter(), Counter()
    raw_total, identical, done = 0, 0, 0
    field_sets: Counter = Counter()
    unparsed_members: set = set()
    t0 = time.monotonic()
    timed_out = False
    with ThreadPoolExecutor(WORKERS) as pool:
        for i in range(0, len(blobs), WORKERS):       # a few bodies in memory at a time (fund-house files are MBs)
            if time.monotonic() - t0 > max_seconds:
                timed_out = True
                break
            chunk = blobs[i:i + WORKERS]
            for (blob_key, rec), (body, why) in zip(chunk, pool.map(lambda kv: _body(ro, kv[1]), chunk)):
                done += 1
                if body is None:
                    body_status[why] += 1
                    continue
                rec = dict(rec, dataset=dataset)
                try:
                    if spec.level == 'row':
                        rows = spec.rows(body, rec)
                        df, d = spec.parse(rows, rec)
                        raw_total += len(rows)
                        identical += len(rows) - len({json.dumps(r, sort_keys=True, default=str) for r in rows})
                        for r in rows:
                            field_sets.update(k for k in r if not str(k).startswith('__'))
                            seen_rows += 1
                            if len(raw_rows) < RESERVOIR:
                                raw_rows.append((r, rec))
                            else:
                                j = rng.randrange(seen_rows)
                                if j < RESERVOIR:
                                    raw_rows[j] = (r, rec)
                    else:
                        df, d, n = spec.parse(body, rec)
                        raw_total += n if n is not None else len(df) + sum(d.values())
                        if spec.raw_fields is not None:
                            names, others = spec.raw_fields(body)
                            field_sets.update(names)
                            unparsed_members |= set(others)
                    drops.update({k: v for k, v in d.items() if v})
                    if df is not None and len(df):
                        frames.append(df.assign(_key=spec.key(df).values, _blob=blob_key))
                except Exception as exc:  # noqa: BLE001 - one answer that does not parse is counted, the rest go on
                    errors[f'{type(exc).__name__}: {str(exc)[:120]}'] += 1
    res['blob_status'] = dict(body_status)
    bounded = more or len(by_blob) > done
    why = []
    if more or len(by_blob) > len(blobs):
        why.append(f'max_blobs {max_blobs}')
    if timed_out:
        why.append(f'{max_seconds:.0f} s for this dataset')
    res['reparsed'] = {'blobs': done, 'of_distinct_blobs': inv['distinct_blobs'],
                       'how': (f'random sample of {done} blobs ({", ".join(why)})' if bounded else f'all {done} blobs')}
    parsed = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=['_key'])
    parsed_rows = len(parsed)
    keys = set(parsed['_key'].astype(str))
    res['counts'] = {'raw_rows': raw_total, 'parsed_rows': parsed_rows, 'parsed_keys': len(keys),
                     'identical_raw_rows': identical, 'dropped': dict(drops), 'parse_errors': dict(errors)}
    try:
        stored = spec.stored(ro, keys, parsed, [r for _, r in blobs]) if keys else pd.DataFrame(columns=['_key'])
        res['table_found'] = True
    except TableMissing as exc:
        stored, res['table_found'] = pd.DataFrame(columns=['_key']), False
        res['table_note'] = str(exc)
    stored_by = {str(k): row for k, row in zip(stored['_key'], stored.to_dict('records'))}
    missing = sorted(keys - set(stored_by))
    res['counts']['in_table'] = len(keys) - len(missing)
    res['counts']['missing_from_table'] = len(missing)
    res['missing_examples'] = missing[:MAX_LIST]
    # rows the parser does not account for (not dropped with a reason, not identical copies, not merged by design)
    explained = sum(drops.values()) + identical
    unexplained = raw_total - parsed_rows - explained if not spec.grouping else 0
    res['counts']['unexplained_drop'] = max(int(unexplained), 0)
    if spec.grouping:
        res['counts']['merged_by_design'] = max(raw_total - parsed_rows - explained, 0)
        res['grouping'] = spec.grouping
    # fields
    res['fields'] = _fields(spec, raw_rows, parsed, stored_by, field_sets, unparsed_members, rng)
    # values
    res['mismatches'], res['values_compared'] = _values(spec, raw_rows, parsed, stored_by, sample, rng)
    res['bounded'] = bool(bounded)
    res['verdict'], res['gaps'] = _verdict(res, spec, inv)
    return res


def _fields(spec, raw_rows, parsed, stored_by, field_sets, unparsed_members, rng) -> dict:
    if spec.level == 'blob':
        if spec.raw_fields is None:
            return {'applicable': False, 'note': spec.fields_note}
        fm = {str(k).strip().lower(): v for k, v in spec.field_map.items()}
        kept = sorted(f for f in field_sets if str(f).strip().lower() in fm)
        unkept = sorted(f for f in field_sets if str(f).strip().lower() not in fm)
        unkept += [f'file in archive not parsed: {m}' for m in sorted(unparsed_members)]
        return {'applicable': True, 'raw_fields': sorted(field_sets), 'kept': kept, 'not_kept': unkept,
                'how': 'raw CSV header against the parser\'s column map'}
    picks = raw_rows if len(raw_rows) <= TRACE_ROWS else rng.sample(raw_rows, TRACE_ROWS)
    status: dict = {}
    by_key = {}
    if len(parsed):
        by_key = {k: row for k, row in zip(parsed['_key'], parsed.to_dict('records'))}
    for row, rec in picks:
        key, prow = _key_of_row(spec, row, rec)
        out = _trace(row, stored_by.get(key), prow or by_key.get(key), spec.field_map)
        for f, how in out.items():
            status.setdefault(f, Counter())[how] += 1
    seen = sorted(field_sets)
    kept_col = sorted(f for f, c in status.items() if c['column'])
    in_json = sorted(f for f, c in status.items() if not c['column'] and c['raw_json'])
    by_value = sorted(f for f, c in status.items() if not c['column'] and not c['raw_json'] and c['value'])
    unkept = sorted(f for f, c in status.items() if not c['column'] and not c['raw_json'] and not c['value'])
    partly = sorted(f for f in by_value if status[f]['no'])     # value found in some traced rows, not in others
    never = sorted(set(seen) - set(status))
    return {'applicable': True, 'raw_fields': seen, 'kept_as_column': kept_col, 'kept_in_raw_json': in_json,
            'value_found_in_a_column': by_value, 'value_not_found_in_some_rows': partly, 'not_kept': unkept, 'empty_in_traced_rows': never,
            'rows_traced': len(picks),
            'how': 'each traced raw row against its stored row (else the parsed row): column name, the parser\'s '
                   'field map, the stored raw_json copy, or the value itself in a column'}


def _key_of_row(spec, row, rec) -> tuple[str | None, dict | None]:
    try:
        df, _ = spec.parse([row], rec)
    except Exception:  # noqa: BLE001
        return None, None
    if df is None or not len(df):
        return None, None
    k = spec.key(df)
    return str(k.iloc[0]), df.iloc[0].to_dict()


def _values(spec, raw_rows, parsed, stored_by, sample, rng) -> tuple[list, int]:
    out, compared = [], 0
    if spec.level == 'row':
        pool_ = list(raw_rows)
        rng.shuffle(pool_)
        for row, rec in pool_:
            if compared >= sample:
                break
            key, prow = _key_of_row(spec, row, rec)
            if key is None or key not in stored_by:
                continue
            compared += 1
            srow = stored_by[key]
            for c, f in spec.compare.items():
                rv, pv, sv = _raw_value(row, f), (prow or {}).get(c), srow.get(c)
                if c not in srow:
                    out.append({'key': key, 'field': c, 'raw_field': f, 'raw': _show(rv), 'parsed': _show(pv),
                                'stored': '(column not in table)'})
                elif norm(rv) != norm(sv):
                    out.append({'key': key, 'field': c, 'raw_field': f, 'raw': _show(rv), 'parsed': _show(pv),
                                'stored': _show(sv)})
        return out, compared
    keys = [k for k in parsed['_key'].astype(str).unique() if k in stored_by] if len(parsed) else []
    rng.shuffle(keys)
    first = None
    if len(parsed):
        first = parsed.drop_duplicates('_key')
        first = first.set_index(first['_key'].astype(str))
    for key in keys[:sample]:
        compared += 1
        prow, srow = first.loc[key].to_dict(), stored_by[key]
        for c in spec.compare:
            if c not in prow:
                continue
            if c not in srow:
                out.append({'key': key, 'field': c, 'raw': _show(prow.get(c)), 'parsed': _show(prow.get(c)),
                            'stored': '(column not in table)'})
            elif norm(prow.get(c)) != norm(srow.get(c)):
                out.append({'key': key, 'field': c, 'raw': _show(prow.get(c)), 'parsed': _show(prow.get(c)),
                            'stored': _show(srow.get(c))})
    return out, compared


def _verdict(res, spec, inv) -> tuple[str, list]:
    gaps = []
    c = res['counts']
    if inv['records_without_blob_by_name']:
        gaps.append(f"{inv['records_without_blob_by_name']:,} fetch records whose blob is gone (by name)")
    for why, n in res.get('blob_status', {}).items():
        gaps.append(f'{n} re-read blobs: {why}')
    if c['parse_errors']:
        gaps.append(f"{sum(c['parse_errors'].values())} answers the parser could not read")
    if not res.get('table_found', True):
        gaps.append(f"table not found ({res.get('table_note')})")
    elif c['missing_from_table']:
        gaps.append(f"{c['missing_from_table']:,} of {c['parsed_keys']:,} parsed rows not in {spec.table}")
    if c['unexplained_drop']:
        gaps.append(f"{c['unexplained_drop']:,} raw rows neither parsed nor dropped with a reason")
    f = res['fields']
    if f.get('applicable') and f.get('not_kept'):
        gaps.append(f"raw fields no table keeps: {', '.join(map(str, f['not_kept'][:10]))}"
                    + (f' (+{len(f["not_kept"]) - 10})' if len(f['not_kept']) > 10 else ''))
    if res['mismatches']:
        gaps.append(f"{len(res['mismatches'])} value mismatches in {res['values_compared']} sampled records")
    # Rows the parser drops on purpose still exist only in raw: for the delete decision they are a gap (a parser
    # dropped BSE 'Spin Off' rows on purpose until 20 Nov 2026, and only raw let them be recovered).
    if c['dropped']:
        gaps.append(f"{sum(c['dropped'].values()):,} rows the parser drops (only in raw): "
                    + '; '.join(f'{k} {v:,}' for k, v in c['dropped'].items()))
    if gaps:
        return 'gaps: ' + '; '.join(gaps), gaps
    if not c['parsed_rows']:
        return 'not checked: no answer re-parsed gave a row' + (' (bounded sample)' if res['bounded'] else ''), gaps
    design = ''
    if res['bounded']:
        return (f"not checked: only {res['reparsed']['blobs']:,} of {inv['distinct_blobs']:,} blobs re-parsed "
                f"({res['reparsed']['how'].split('(', 1)[-1].rstrip(')')}); no gap in those{design}"), gaps
    return 'fully captured' + design, gaps


# --- the old raw/ layout -------------------------------------------------------------------------------------------------

def old_raw(ro: ReadOnly) -> list[dict]:
    objs, _ = ro.list(OLD_RAW)
    groups: dict = {}
    for k, s in objs:
        parts = k.split('/')
        g = '/'.join(parts[:3]) if len(parts) > 3 else '/'.join(parts[:2])
        e = groups.setdefault(g, {'prefix': g, 'objects': 0, 'bytes': 0})
        e['objects'] += 1
        e['bytes'] += s
    return [dict(v, verdict='not checked: dated snapshot layout written by scripts/r2_writer.py (no fetch records); '
                            'outside this audit') for _, v in sorted(groups.items())]


# --- report ----------------------------------------------------------------------------------------------------------------

def _mb(n) -> str:
    if (n or 0) < 1e6:
        return f"{(n or 0) / 1e3:,.1f} KB"
    return f'{(n or 0) / 1e6:,.1f} MB'


def _cell(s) -> str:
    return str(s).replace('|', '\\|').replace('\n', ' ')


def markdown(report: dict) -> str:
    out = ['## Raw coverage audit (read-only)', '',
           f"Run {report['started']} · sources {', '.join(report['sources']) or 'all'} · sample {report['sample']} · "
           f"max_blobs {report['max_blobs']} · {report['elapsed_s']:.0f} s · R2 reads: {report['r2_gets']:,} GET, "
           f"{report['r2_lists']:,} LIST, 0 writes.", '',
           'Verdict per dataset: **fully captured** only if every re-parsed row is in its table, no raw row is lost '
           'without a reason, no raw field is unkept and no sampled value differs; **gaps** with the specifics; '
           '**not checked** with the reason; **no parser found** when the code names none.', '']
    by_source: dict = {}
    for d in report['datasets']:
        by_source.setdefault(d['source'], []).append(d)
    for src, rows in by_source.items():
        out += [f'### raw_v2/{src}', '',
                '| dataset | parser → table | fetch records (days) | blobs (stored) | re-parsed | raw rows → parsed → in table '
                '| dropped by parser | raw fields not kept | value mismatches | serves old data? | verdict |',
                '|---|---|---|---|---|---|---|---|---|---|---|']
        for d in rows:
            inv = d['inventory']
            c = d.get('counts') or {}
            f = d.get('fields') or {}
            fields = ('n/a: ' + f.get('note', '')[:60]) if f and not f.get('applicable') else \
                (', '.join(map(str, f.get('not_kept', [])[:8])) + (' …' if len(f.get('not_kept', [])) > 8 else '') if f else '')
            counts = (f"{c.get('raw_rows', 0):,} → {c.get('parsed_rows', 0):,} → {c.get('in_table', 0):,}" if c else '')
            dropped = '; '.join(f'{k}: {v:,}' for k, v in (c.get('dropped') or {}).items())
            if c.get('unexplained_drop'):
                dropped += f"{'; ' if dropped else ''}unexplained: {c['unexplained_drop']:,}"
            if c.get('merged_by_design'):
                dropped += f"{'; ' if dropped else ''}merged by design: {c['merged_by_design']:,}"
            refetch = d['refetch'] if d['refetch'] == 'unknown' else f"\"{d['refetch']}\" ({d['refetch_ref']})"
            out.append('| ' + ' | '.join(_cell(x) for x in (
                d['dataset'], f"{d.get('parser') or '—'} → {d.get('table') or '—'}",
                f"{inv['fetch_records']:,} ({inv['first_day'] or '—'} … {inv['last_day'] or '—'})",
                f"{inv['distinct_blobs']:,} ({_mb(inv['blob_bytes'])})",
                (d.get('reparsed') or {}).get('how', '—'), counts, dropped, fields,
                f"{len(d.get('mismatches') or [])} in {d.get('values_compared', 0)}" if 'mismatches' in d else '',
                refetch, d['verdict'])) + ' |')
        out.append('')
        for d in rows:
            detail = []
            if d.get('error'):
                detail.append(f"- audit failed: `{d['error']}`")
            if d.get('record_status'):
                detail.append(f"- fetch records not re-parsed: {d['record_status']}")
            if (d.get('counts') or {}).get('parse_errors'):
                detail.append(f"- parse errors: {d['counts']['parse_errors']}")
            if d.get('missing_examples'):
                detail.append(f"- keys not in the table (first {len(d['missing_examples'])}): "
                              + ', '.join(f'`{k}`' for k in d['missing_examples'][:10]))
            f = d.get('fields') or {}
            if f.get('applicable') and f.get('not_kept'):
                detail.append('- raw fields no table keeps: ' + ', '.join(f'`{x}`' for x in f['not_kept'][:MAX_LIST]))
            if f.get('kept_in_raw_json'):
                detail.append('- kept only inside the stored `raw_json`: ' + ', '.join(f'`{x}`' for x in f['kept_in_raw_json'][:MAX_LIST]))
            if f.get('value_found_in_a_column'):
                detail.append('- kept under another name (value found in a column): '
                              + ', '.join(f'`{x}`' for x in f['value_found_in_a_column'][:MAX_LIST]))
            if d.get('mismatches'):
                detail += ['', '| record key | field | raw | parsed | stored |', '|---|---|---|---|---|']
                detail += ['| ' + ' | '.join(_cell(m.get(k, '')) for k in ('key', 'field', 'raw', 'parsed', 'stored')) + ' |'
                           for m in d['mismatches'][:MAX_LIST]]
            if detail:
                out += [f"**{src}/{d['dataset']}**", ''] + detail + ['']
    if report.get('old_raw'):
        out += ['### raw/ (older layout)', '', '| prefix | objects | bytes | verdict |', '|---|---|---|---|']
        out += [f"| {g['prefix']} | {g['objects']:,} | {_mb(g['bytes'])} | {g['verdict']} |" for g in report['old_raw']]
        out.append('')
    return '\n'.join(out) + '\n'


def _stub(src, ds, objs, verdict, **extra) -> dict:
    spec = spec_for(src, ds)
    return {'source': src, 'dataset': ds, 'inventory': inventory(objs), 'parser': spec.parser if spec else None,
            'table': spec.table if spec else None, 'refetch': spec.refetch if spec else 'unknown',
            'refetch_ref': spec.refetch_ref if spec else '', 'verdict': verdict, **extra}


def run(client, bucket: str | None, sources: set | None = None, sample: int = 5, max_blobs: int = 300,
        budget_s: float = 50 * 60, seed: int = 0, log=print) -> dict:
    ro = ReadOnly(client, bucket)
    t0 = time.monotonic()
    report = {'started': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'), 'sources': sorted(sources or []),
              'sample': sample, 'max_blobs': max_blobs, 'datasets': []}
    raw_sources = {s for s in sources if s != 'raw'} if sources else None
    found = discover(ro, raw_sources) if (sources is None or raw_sources) else {}
    todo = sorted(found.items())
    wired = sum(1 for (s_, d_), _ in todo if getattr(spec_for(s_, d_), 'level', None))
    for (src, ds), objs in todo:
        left = budget_s - (time.monotonic() - t0)
        share = max(15.0, left / max(wired, 1))        # each dataset with an adapter gets a fair share of what is left
        if getattr(spec_for(src, ds), 'level', None):
            wired -= 1
        if left <= 0:
            report['datasets'].append(_stub(src, ds, objs, 'not checked: time budget reached'))
            continue
        log(f'{src}/{ds}: {len(objs["fetches"])} fetch objects, {len(objs["blobs"])} blob objects')
        try:
            report['datasets'].append(audit_dataset(ro, src, ds, objs, sample, max_blobs, seed, share))
        except Exception as exc:  # noqa: BLE001 - one dataset failing is reported, the others go on
            report['datasets'].append(_stub(src, ds, objs, f'not checked: audit failed ({type(exc).__name__})',
                                            error=f'{type(exc).__name__}: {exc}'[:300]))
        log(f'  -> {report["datasets"][-1]["verdict"][:160]}')
    if sources is None or 'raw' in sources:
        report['old_raw'] = old_raw(ro)
    report['elapsed_s'] = time.monotonic() - t0
    report['r2_gets'], report['r2_lists'] = ro.gets, ro.lists
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--sources', default='', help='comma list of raw_v2 sources (nse, bse, amc ...) and/or raw; empty = all')
    ap.add_argument('--sample', type=int, default=5)
    ap.add_argument('--max-blobs', type=int, default=300)
    ap.add_argument('--budget-minutes', type=float, default=50)
    ap.add_argument('--out', default='artifacts/raw_coverage')
    a = ap.parse_args(argv)
    import boto3
    client = boto3.client('s3', endpoint_url=f"https://{os.environ['CLOUDFLARE_ACCOUNT_ID']}.r2.cloudflarestorage.com",
                          aws_access_key_id=os.environ['R2_ACCESS_KEY_ID'],
                          aws_secret_access_key=os.environ['R2_SECRET_ACCESS_KEY'], region_name='auto')
    sources = {s.strip() for s in a.sources.split(',') if s.strip() and s.strip() != 'all'} or None
    report = run(client, os.environ.get('R2_BUCKET_NAME'), sources, a.sample, a.max_blobs, a.budget_minutes * 60)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    text = markdown(report)
    (out / 'report.md').write_text(text)
    (out / 'report.json').write_text(json.dumps(report, indent=2, default=str))
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a') as fh:
            fh.write(text if len(text) < 900_000 else text[:900_000] + '\n\n(truncated: the full report is in the artifact)\n')
    print(text)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
