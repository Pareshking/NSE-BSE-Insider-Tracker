"""The announcement reader: today's useful NSE and BSE filings read by a model, every value checked.

    python scripts/announcement_reader.py                 # collect today's filings, read the new ones, write R2
    python scripts/announcement_reader.py --dry-run --max 3   # read three, print, write nothing

Runs in GitHub Actions through the day (workflow Announcement reader); the site never calls a model, it
reads clean/current/announcement_reads.parquet. docs/ANNOUNCEMENT_READER.md has the decisions behind it.

1. Collect: yesterday's and today's NSE (main board and SME) and BSE filings into raw_v2/ and the archive,
   as the nightly collectors do (their count reports are left to the nightly run).
2. Choose: filings of today and yesterday, newest first, in a reading group (not routine, not concalls),
   with a PDF or ZIP. Read once: a filing already in the reads archive is skipped; the same filing on the
   other exchange (same ISIN, within six hours, subjects alike; the two copies are different files) and a
   file or text read before are copied, not read again. A company below Rs 100 Cr market cap is not sent.
3. Read: each lane of scripts/announcement_readers.txt reads every chosen filing, the lanes side by side.
   Within a lane the next model takes over when one is busy, refused or timing out; a model timing out
   twice running is left out for the rest of the run.
4. Check: a value is shown only when its quote is found in the filing's text, a number's digits are in
   its quote, and an amount's lakh, crore, million or billion is backed by the quote. Our code converts
   units; the model gives numbers as written. Entity labels are kept but not shown yet (the only field
   where wrong values passed the checks, 13 Oct). Everything else is held back with its reason.
5. Write: archive/announcement_reads/year=YYYY/month=MM.parquet by event_id, clean/current/
   announcement_reads.parquet (the last READ_DAYS days) and the day's usage log in
   clean/reports/announcement_reader/{date}.json (every call: model, answer, seconds).

Only public filing text goes in a prompt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import announcement_sample as s  # noqa: E402 -- prompts, model clients, document text and checks

IST = timezone(timedelta(hours=5, minutes=30))
PROMPT_VERSION = 'live-1'
LANES_FILE = HERE / 'announcement_readers.txt'
READS_PREFIX = 'archive/announcement_reads/'
CLEAN_KEY = 'clean/current/announcement_reads.parquet'
READ_DAYS = 60
COLLECT_DAYS = 2              # yesterday too: a filing made public after the nightly collection (22:45) and
                              # before midnight is read the same night; BSE stops at its first known page
MIN_MCAP = 100 * 1e7          # Rs 100 Cr: smaller companies' PDFs never go to a model
SAME_FILING_HOURS = 6
SAME_FILING_WORDS = 0.4       # share of the shorter subject's words found in the other
MAX_TRIES = 3                 # a filing that failed this often is left (counted in the report)
SLOW_STRIKES = 2              # timeouts in a row before a model is left out for the run
COPY_STATUSES = ('same_file', 'same_text', 'same_filing_other_exchange')
COLUMNS = ('event_id', 'exchange', 'market', 'isin', 'symbol', 'company', 'subject', 'detail', 'group',
           'broadcast_at', 'broadcast_date', 'file_url', 'file_sha256', 'text_sha256', 'text_chars', 'status',
           'same_as', 'tries', 'reason', 'reader', 'reader_lane', 'prompt_version', 'category', 'fields',
           'metrics', 'second_reader', 'second_category', 'second_fields', 'shown', 'held', 'agreed',
           'seconds', 'read_at')


def log(*parts):
    print(time.strftime('%H:%M:%S'), *parts, flush=True)


# --- lanes ---------------------------------------------------------------------------

def lanes_of(text: str) -> dict[str, list[str]]:
    """{'main': ['nvidia:moonshotai/kimi-k3', ...], 'second': [...]} from the lanes file."""
    out = {}
    for ln in text.splitlines():
        ln = ln.split('#', 1)[0].strip()
        if ':' in ln and ln.split(':', 1)[0].strip() in ('main', 'second'):
            name, rest = ln.split(':', 1)
            out[name.strip()] = [x.strip() for x in rest.split(',') if x.strip()]
    return out


class Lane:
    """One lane's models, each provider's in turn; slow models are left out after SLOW_STRIKES timeouts."""

    def __init__(self, name: str, entries: list[str], clients: dict):
        self.name, self.entries, self.clients = name, list(entries), clients
        self.strikes, self.dropped = {}, []

    def models(self) -> list[tuple[str, str]]:
        return [tuple(e.split(':', 1)) for e in self.entries if e not in self.dropped]

    def read(self, prompt: str) -> tuple[str, str, float]:
        """(reply text, entry that answered, seconds). RuntimeError when every model failed."""
        t0, errors = time.monotonic(), []
        for prov, model in self.models():
            client = self.clients.get(prov)
            if client is None:
                continue
            limit = s.MODEL_LIMITS.get(model.removesuffix('+thinking'), (None,))[0] or s.PROVIDERS[prov][2]
            if limit and len(prompt) > limit:
                errors.append(f'{prov}:{model}: {len(prompt):,} characters, over its limit')
                continue
            try:
                text, _, used = client.generate([model], prompt, 'read', json_mode=True)
                self.strikes[f'{prov}:{model}'] = 0
                return text, f'{prov}:{used}', round(time.monotonic() - t0, 1)
            except RuntimeError as exc:
                entry = f'{prov}:{model}'
                errors.append(f'{entry}: {exc}'[:200])
                if 'Timeout' in str(exc):
                    self.strikes[entry] = self.strikes.get(entry, 0) + 1
                    if self.strikes[entry] >= SLOW_STRIKES and entry not in self.dropped:
                        self.dropped.append(entry)
                        log(f'{self.name}: {entry} timed out {SLOW_STRIKES} times running; left out this run')
        raise RuntimeError('; '.join(errors) or f'{self.name}: no model available')


def clients_for(entries, env=os.environ) -> tuple[dict, list[str]]:
    """A client per provider named in the lanes (keys from the environment); notes for what is missing."""
    clients, notes = {}, []
    for prov in dict.fromkeys(e.split(':', 1)[0] for e in entries):
        if prov not in s.PROVIDERS:
            notes.append(f'{prov}: unknown provider')
            continue
        base, secret, _ = s.PROVIDERS[prov]
        key = env.get(secret, '').strip()
        if not key:
            notes.append(f'{secret} is not set; {prov} lanes skipped')
            continue
        clients[prov] = s.OpenAICompat(prov, base, key)
    for e in entries:
        prov, model = e.split(':', 1)
        if prov in s.FREE_ONLY and model.removesuffix('+thinking') not in s.FREE_ONLY[prov]:
            notes.append(f'{e}: not one of {prov}\'s free models; never used')
    return clients, notes


def usable(entries: list[str]) -> list[str]:
    return [e for e in entries if not (e.split(':', 1)[0] in s.FREE_ONLY
                                       and e.split(':', 1)[1].removesuffix('+thinking') not in s.FREE_ONLY[e.split(':', 1)[0]])]


# --- checks ----------------------------------------------------------------------------

# Currency marks as filings write them, right before a number ('US$ 809mn', 'Rs. 165.65', '₹ 28,200.00').
CURRENCY_MARKS = (('CAD', r'CAD|C\$'), ('AUD', r'AUD|A\$'), ('SGD', r'SGD|(?<!U)S\$'),   # before the plain $
                  ('USD', r'US\s?\$|USD|\$'), ('INR', r'₹|Rs\.?|INR|Rupees'), ('EUR', r'€|EUR'), ('GBP', r'£|GBP'),
                  ('AED', r'AED'), ('ZAR', r'ZAR'), ('JPY', r'JPY|¥'))
MONEY_FIELDS = ('price_per_share', 'max_price_per_share', 'amount')


def currency_in_quote(value, quote) -> str | None:
    """The currency the quote writes right before the value's number; None when it writes none."""
    v = s._num(value)
    if v is None:
        return None
    q = str(quote or '')
    for m in re.finditer(s.NUMBER, q):
        if abs(float(m.group(0).replace(',', '')) - v) < 1e-6 * max(1, abs(v)):
            before = q[max(0, m.start() - 14):m.start()].rstrip()
            for code, pat in CURRENCY_MARKS:
                if re.search(r'(?:' + pat + r')$', before, re.IGNORECASE):
                    return code
    return None


def _bool(v):
    t = str(v).strip().lower()
    return True if t in ('true', 'yes') else False if t in ('false', 'no') else None


def validate(out, doc: str) -> tuple[str | None, list[dict], list[dict]]:
    """(category, fields, metrics), each value with its checks, `shown` and, when held back, `reason`."""
    out = out if isinstance(out, dict) else {}
    named = {}
    for f in out.get('fields') or []:
        if isinstance(f, dict) and f.get('name') in s.FIELDS and f['name'] not in named:
            named[f['name']] = f
    unit = (named.get('amount_unit') or {}).get('value')
    cur = named.get('currency') or {}
    filing_currency = str(cur.get('value')).strip().upper() if cur.get('value') and s.quote_found(cur.get('quote'), doc)         else None
    fields = []
    for name, f in named.items():
        if name == 'amount_unit':
            continue
        value, quote = f.get('value'), f.get('quote')
        qf = s.quote_found(quote, doc)
        rec = {'name': name, 'value': value, 'quote': quote, 'evidence': qf or None, 'reason': None}
        reasons = [] if qf else ['quote not found in the filing']
        if name in s.NUMERIC:
            if not s.digits_in_quote(value, quote):
                reasons.append('number not in its quote')
            rec['number'] = s.in_units(value, unit) if name == 'amount' else s._num(value)
            if rec['number'] is None:
                reasons.append('not one number')
            if name == 'amount':
                rec['unit'] = unit
                if s.unit_backed(value, unit, quote, qf) is False:
                    reasons.append('unit not backed by its quote')
        if name in MONEY_FIELDS:   # the site writes the currency only when the filing does
            rec['currency'] = currency_in_quote(value, quote) or filing_currency
        if name.endswith('_date'):
            rec['date'] = s.as_date(value)
            if rec['date'] is None:
                reasons.append('date not readable')
        elif name == 'allottee_is_promoter':
            rec['flag'] = _bool(value)
            if rec['flag'] is None:
                reasons.append('not yes or no')
        if name == 'entity':
            reasons.append('entity labels not shown yet')
        rec['shown'], rec['reason'] = not reasons, '; '.join(reasons) or None
        fields.append(rec)
    metrics = []
    for m in out.get('metrics') or []:
        if not isinstance(m, dict):
            continue
        value, quote, unit_m = m.get('value'), m.get('quote'), m.get('unit')
        qf = s.quote_found(quote, doc)
        reasons = [] if qf else ['quote not found in the filing']
        if not s.digits_in_quote(value, quote):
            reasons.append('number not in its quote')
        money = str(unit_m or '').strip().lower().rstrip('.') in s.UNIT
        number = s.in_units(value, unit_m) if money else s._num(value)
        if number is None:
            reasons.append('not one number')
        if money and s.unit_backed(value, unit_m, quote, qf) is False:
            reasons.append('unit not backed by its quote')
        metrics.append({'label': m.get('label'), 'period': m.get('period'), 'value': value, 'unit': unit_m,
                        'number': number, 'quote': quote, 'evidence': qf or None,
                        'currency': currency_in_quote(value, quote) if money else None,
                        'shown': not reasons, 'reason': '; '.join(reasons) or None})
    cat = out.get('category') if out.get('category') in s.CATEGORIES else None
    return cat, fields, metrics


def agreement(main: list[dict], second: list[dict]) -> dict:
    """Per shown field of the main read: True when the second read gives the same value, False when it
    gives another, None when it gives none."""
    other = {f['name']: f for f in second}
    out = {}
    for f in main:
        if not f['shown']:
            continue
        g = other.get(f['name'])
        if g is None:
            out[f['name']] = None
        elif 'number' in f:
            a, b = f.get('number'), g.get('number')
            out[f['name']] = a is not None and b is not None and abs(a - b) <= 0.005 * max(1.0, abs(a))
        else:
            key = 'date' if 'date' in f else 'flag' if 'flag' in f else 'value'
            out[f['name']] = str(f.get(key)).strip().lower() == str(g.get(key)).strip().lower()
    return out


# --- choosing what to read ---------------------------------------------------------------

def _words(text) -> set[str]:
    return set(re.findall(r'[a-z]{4,}', str(text or '').lower())) - {
        'limited', 'company', 'regulation', 'regulations', 'sebi', 'listing', 'obligations', 'disclosure',
        'requirements', 'informed', 'exchange', 'regarding', 'pursuant'}


def same_filing(a: dict, b: dict) -> bool:
    """The same filing sent to both exchanges: same ISIN, within SAME_FILING_HOURS, subjects alike."""
    if not a.get('isin') or a.get('isin') != b.get('isin') or a.get('exchange') == b.get('exchange'):
        return False
    ta, tb = pd.Timestamp(a['broadcast_at']), pd.Timestamp(b['broadcast_at'])
    if abs((ta - tb).total_seconds()) > SAME_FILING_HOURS * 3600:
        return False
    wa, wb = _words(f"{a['subject']} {a['detail']}"), _words(f"{b['subject']} {b['detail']}")
    return bool(wa and wb) and len(wa & wb) / min(len(wa), len(wb)) >= SAME_FILING_WORDS


def candidates(nse: pd.DataFrame | None, bse: pd.DataFrame | None, master) -> pd.DataFrame:
    """Both exchanges' filings in one shape, with ISIN, NSE symbol where there is one, group and market cap."""
    from collectors.bse import announcements as bann
    from collectors.nse_events import announcements as nann
    rows = []
    for r in (nse.to_dict('records') if nse is not None else []):
        isin = r.get('isin') or (master.resolve('nse', r.get('symbol'))[0] if master else None)
        rows.append({'event_id': r['event_id'], 'exchange': 'NSE', 'market': r.get('market') or 'equities',
                     'isin': isin, 'symbol': r.get('symbol'), 'company': r.get('company'),
                     'subject': r.get('subject'), 'detail': r.get('text'),
                     'group': nann.group_of(r.get('subject'), r.get('text')), 'file_url': r.get('file_url'),
                     'file_type': r.get('file_type'), 'broadcast_at': r.get('broadcast_at'),
                     'broadcast_date': r.get('broadcast_date')})
    for r in (bse.to_dict('records') if bse is not None else []):
        isin = master.resolve('bse', r.get('bse_code'))[0] if master and r.get('bse_code') else None
        rec = (master.record(isin) or {}) if master and isin else {}
        rows.append({'event_id': r['event_id'], 'exchange': 'BSE', 'market': 'bse', 'isin': isin,
                     'symbol': rec.get('nse_symbol') or r.get('bse_code'), 'company': r.get('company'),
                     'subject': r.get('subcategory') or r.get('category'), 'detail': r.get('headline'),
                     'group': bann.group_of(r.get('subcategory'), r.get('category')), 'file_url': r.get('file_url'),
                     'file_type': r.get('file_type'), 'broadcast_at': r.get('broadcast_at'),
                     'broadcast_date': r.get('broadcast_date')})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df['market_cap'] = [((master.record(i) or {}).get('market_cap') if master and i else None) for i in df['isin']]
    return df


def choose(cands: pd.DataFrame, done: pd.DataFrame | None, today: date) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """(to read, status rows written without a model call, counts). Today first, then yesterday, newest first."""
    counts = {}
    if cands is None or cands.empty:
        return pd.DataFrame(), pd.DataFrame(), {'candidates': 0}
    days = {today.isoformat(), (today - timedelta(days=1)).isoformat()}
    c = cands[cands['broadcast_date'].isin(days)].copy()
    counts['candidates'] = len(c)
    finished = set()
    tries = {}
    if done is not None and not done.empty:
        failed = done['status'] == 'failed'
        finished = set(done.loc[~failed | (done['tries'].fillna(0) >= MAX_TRIES), 'event_id'])
        tries = done.loc[failed].set_index('event_id')['tries'].to_dict()
    keep = c['group'].ne('routine') & c['file_url'].notna() & c['file_type'].isin(['pdf', 'zip'])
    counts['routine_or_no_file'] = int((~keep).sum())
    c = c[keep & ~c['event_id'].isin(finished)]
    counts['already_done'] = int(keep.sum()) - len(c)
    c = c.sort_values(['broadcast_date', 'broadcast_at'], ascending=False)
    c['tries'] = c['event_id'].map(tries).fillna(0).astype(int)
    status_rows, read_rows = [], []
    earlier = [] if done is None or done.empty else done[done['status'].isin(('read',) + COPY_STATUSES)] \
        .to_dict('records')
    for r in c.sort_values('broadcast_at').to_dict('records'):   # oldest first, so the first copy is read
        mcap = r.get('market_cap')
        if mcap is not None and pd.notna(mcap) and mcap < MIN_MCAP:
            status_rows.append({**r, 'status': 'below_100_cr', 'reason': f'market cap Rs {mcap / 1e7:,.0f} Cr'})
            continue
        twin = next((e for e in earlier + read_rows if same_filing(r, e)), None)
        if twin is not None:
            status_rows.append({**r, 'status': 'same_filing_other_exchange', 'same_as': twin['event_id']})
            continue
        read_rows.append(r)
    counts['below_100_cr'] = sum(x['status'] == 'below_100_cr' for x in status_rows)
    counts['same_filing_other_exchange'] = sum(x['status'] == 'same_filing_other_exchange' for x in status_rows)
    to_read = pd.DataFrame(read_rows)
    if not to_read.empty:
        to_read = to_read.sort_values(['broadcast_date', 'broadcast_at'], ascending=False)
    counts['to_read'] = len(to_read)
    return to_read, pd.DataFrame(status_rows), counts


# --- reading ---------------------------------------------------------------------------

def read_filing(row: dict, doc: str, lanes: dict[str, Lane], pool: ThreadPoolExecutor | None = None) -> dict:
    """Both lanes on one filing, side by side; the main lane's checked values are the ones shown."""
    prompt = s.read_prompt({'exchange': row['exchange'], 'symbol': row.get('symbol') or row.get('company'),
                            'subject': row.get('subject')}, doc)

    def one(lane):
        try:
            text, used, secs = lane.read(prompt)
            return {'ok': True, 'reader': used, 'seconds': secs, 'out': s.parse_json(text)}
        except RuntimeError as exc:
            return {'ok': False, 'error': str(exc)[:300]}

    names = [n for n in ('main', 'second') if n in lanes]
    if pool is not None:
        res = dict(zip(names, pool.map(one, [lanes[n] for n in names])))
    else:
        res = {n: one(lanes[n]) for n in names}
    main, second = res.get('main') or {'ok': False}, res.get('second') or {'ok': False}
    rec = {'status': 'read', 'reader': None, 'reader_lane': None, 'category': None, 'fields': [], 'metrics': [],
           'second_reader': None, 'second_category': None, 'second_fields': [], 'reason': None}
    used = main if main['ok'] and main['out'] is not None else second if second['ok'] and second['out'] is not None \
        else None
    if used is None:
        rec.update(status='failed', reason='; '.join(x.get('error') or 'reply was not JSON' for x in (main, second)
                                                     if x)[:500])
        return rec
    cat, fields, metrics = validate(used['out'], doc)
    rec.update(reader=used['reader'], reader_lane='main' if used is main else 'second', category=cat,
               fields=fields, metrics=metrics, seconds=used['seconds'])
    if used is main and second['ok'] and second['out'] is not None:
        cat2, fields2, _ = validate(second['out'], doc)
        rec.update(second_reader=second['reader'], second_category=cat2, second_fields=fields2)
        rec['agreed'] = agreement(fields, fields2)
    return rec


def _sha(b) -> str:
    return hashlib.sha256(b if isinstance(b, bytes) else str(b).encode('utf-8')).hexdigest()


def finish(rec: dict) -> dict:
    """JSON columns and counts for the archive."""
    rec = dict(rec)
    rec['shown'] = sum(f['shown'] for f in rec.get('fields') or []) + sum(m['shown'] for m in rec.get('metrics') or [])
    rec['held'] = sum(not f['shown'] for f in rec.get('fields') or []) + \
        sum(not m['shown'] for m in rec.get('metrics') or [])
    for k in ('fields', 'metrics', 'second_fields', 'agreed'):
        rec[k] = json.dumps(rec.get(k) or ([] if k != 'agreed' else {}), ensure_ascii=False, default=str)
    return {c: rec.get(c) for c in COLUMNS}


def run(to_read: pd.DataFrame, lanes: dict[str, Lane], earlier: pd.DataFrame | None, budget_seconds: float,
        fetch=s.download, max_filings: int | None = None, now=time.monotonic,
        on_row=None) -> tuple[list[dict], dict]:
    """Read the chosen filings in order until the time budget is used; (rows, notes). `on_row` gets each
    filing's row as soon as it is done (the live run saves it then, not at the end)."""
    started, rows, notes = now(), [], {'not_reached': 0}

    def add_row(rec: dict) -> None:
        rows.append(rec)
        if on_row is not None:
            on_row(rec)
    by_file, by_text = {}, {}
    if earlier is not None and not earlier.empty:
        for r in earlier[earlier['status'] == 'read'].to_dict('records'):
            by_file.setdefault(r.get('file_sha256'), r)
            by_text.setdefault(r.get('text_sha256'), r)
    with ThreadPoolExecutor(max_workers=2) as pool:
        for i, row in enumerate(to_read.to_dict('records') if to_read is not None else []):
            if (max_filings is not None and i >= max_filings) or now() - started > budget_seconds:
                notes['not_reached'] += 1
                continue
            base = {**row, 'tries': int(row.get('tries') or 0) + 1, 'prompt_version': PROMPT_VERSION,
                    'read_at': datetime.now(timezone.utc).isoformat()}
            log('---', row['exchange'], row.get('symbol'), row.get('subject'))
            try:
                data = fetch(row['file_url'])
                doc, doc_notes = s.text_of(data)
            except Exception as exc:  # noqa: BLE001 -- one filing failing never stops the run
                add_row(finish({**base, 'status': 'failed', 'reason': f'download: {type(exc).__name__}: {exc}'[:300]}))
                continue
            base.update(file_sha256=_sha(data), text_sha256=_sha(re.sub(r'\s+', ' ', doc).strip()),
                        text_chars=len(doc))
            twin = by_file.get(base['file_sha256'])
            twin = twin or (by_text.get(base['text_sha256']) if doc.strip() else None)
            if twin is not None:
                status = 'same_file' if twin.get('file_sha256') == base['file_sha256'] else 'same_text'
                copied = {k: twin.get(k) for k in ('reader', 'reader_lane', 'category', 'fields', 'metrics',
                                                   'second_reader', 'second_category', 'second_fields', 'agreed')}
                add_row({c: {**base, **copied, 'status': status, 'same_as': twin['event_id'],
                             'shown': twin.get('shown'), 'held': twin.get('held')}.get(c) for c in COLUMNS})
                continue
            if not doc.strip():
                add_row(finish({**base, 'status': 'no_text', 'reason': '; '.join(doc_notes)}))
                continue
            rec = finish({**base, **read_filing(row, doc, lanes, pool)})
            add_row(rec)
            if rec['status'] == 'read':
                by_file.setdefault(rec['file_sha256'], rec)
                by_text.setdefault(rec['text_sha256'], rec)
            log(row.get('symbol'), rec['status'], rec.get('reader'), f"shown {rec.get('shown')}, held {rec.get('held')}")
    return rows, notes


# --- R2 ---------------------------------------------------------------------------------

def months_back(today: date) -> list[str]:
    first = today.replace(day=1)
    prev = (first - timedelta(days=1)).replace(day=1)
    return [f'year={d.year}/month={d.month:02d}' for d in (prev, first)]


def load_archive(r2, prefix: str, today: date) -> pd.DataFrame | None:
    from clean_writer import read_parquet
    frames = [f for f in (read_parquet(r2, f'{prefix}{m}.parquet') for m in months_back(today))
              if f is not None and not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else None


def write(r2, rows: list[dict], run_date: str, today: date) -> int:
    """Rows merged into the reads archive by event_id (a filing read again replaces its row), then the clean
    table rebuilt from it. Returns the number of filings new to the archive."""
    from clean_writer import put_parquet, read_parquet
    new = pd.DataFrame(rows, columns=list(COLUMNS))
    added = 0
    if not new.empty:
        new = new.drop_duplicates('event_id', keep='last')
        part = pd.to_datetime(new['broadcast_date'], errors='coerce')
        for key, g in new.groupby(part.dt.strftime('year=%Y/month=%m').fillna('month=unknown')):
            k = f'{READS_PREFIX}{key}.parquet'
            old = read_parquet(r2, k)
            if old is not None and not old.empty:
                added += int((~g['event_id'].isin(old['event_id'])).sum())
                cols = list(dict.fromkeys([*old.columns, *g.columns]))   # empty columns left out of the concat
                parts = [p.dropna(axis=1, how='all') for p in (old[~old['event_id'].isin(g['event_id'])], g)]
                g = pd.concat(parts, ignore_index=True).reindex(columns=cols)
            else:
                added += len(g)
            for c in ('tries', 'text_chars', 'seconds', 'shown', 'held'):
                g[c] = pd.to_numeric(g[c], errors='coerce')
            put_parquet(r2, k, g.reset_index(drop=True))
    arch = load_archive(r2, READS_PREFIX, today)
    if arch is not None:
        recent = arch[pd.to_datetime(arch['broadcast_date'], errors='coerce')
                      >= pd.Timestamp(today - timedelta(days=READ_DAYS))]
        put_parquet(r2, CLEAN_KEY, recent.reset_index(drop=True))
    return added


class Saver:
    """Rows written to R2 as the run reads them (at most one write every `every` seconds), so a filing reaches
    the site minutes after it is read and a run cut short keeps what it has read. A write that fails keeps its
    rows for the next one; only the last write, at the end of the run, raises."""

    def __init__(self, r2, run_date: str, today: date, every: float = 15.0, now=time.monotonic, writer=None):
        self.r2, self.run_date, self.today, self.every, self.now = r2, run_date, today, every, now
        self.writer = writer or write
        self.pending: list[dict] = []
        self.added, self.writes, self.last = 0, 0, None

    def add(self, rec: dict) -> None:
        self.pending.append(rec)
        if self.last is None or self.now() - self.last >= self.every:
            self.flush()

    def flush(self, final: bool = False) -> None:
        if not self.pending:
            return
        try:
            self.added += self.writer(self.r2, self.pending, self.run_date, self.today)
        except Exception as exc:  # noqa: BLE001 -- kept for the next write
            if final:
                raise
            log('save failed, kept for the next write:', type(exc).__name__, exc)
            return
        finally:
            self.last = self.now()
        self.writes += 1
        log(f'saved {len(self.pending)} filings to R2')
        self.pending = []


def usage(clients: dict, lanes: dict[str, Lane]) -> dict:
    """Every call this run: per model, answers by status and the median seconds of the answered ones."""
    out = {}
    for prov, c in clients.items():
        for model, status, secs in c.attempts:
            e = out.setdefault(f'{prov}:{model}', {'calls': 0, 'by_status': {}, 'seconds': []})
            e['calls'] += 1
            e['by_status'][str(status)] = e['by_status'].get(str(status), 0) + 1
            if status == 200:
                e['seconds'].append(secs)
    for e in out.values():
        secs = sorted(e.pop('seconds'))
        e['median_seconds_ok'] = secs[len(secs) // 2] if secs else None
    return {'models': out, 'left_out_as_slow': {n: lane.dropped for n, lane in lanes.items() if lane.dropped}}


def append_usage(r2, run_date: str, entry: dict):
    from clean_writer import get, put
    key = f'clean/reports/announcement_reader/{run_date}.json'
    body = get(r2, key)
    day = json.loads(body) if body else {'date': run_date, 'runs': []}
    day['runs'].append(entry)
    put(r2, key, json.dumps(day, indent=1, default=str).encode(), 'application/json')


def summary_markdown(counts: dict, rows: list[dict], notes: dict, use: dict, setup: list[str]) -> str:
    st = pd.Series([r['status'] for r in rows]).value_counts().to_dict() if rows else {}
    lines = ['### Announcement reader', '',
             f"Candidates today and yesterday: {counts.get('candidates', 0)}; routine or no file "
             f"{counts.get('routine_or_no_file', 0)}; done before {counts.get('already_done', 0)}; below Rs 100 Cr "
             f"{counts.get('below_100_cr', 0)}; same filing on the other exchange "
             f"{counts.get('same_filing_other_exchange', 0)}; chosen {counts.get('to_read', 0)}, "
             f"not reached this run {notes.get('not_reached', 0)}.", '',
             '| Outcome | Filings |', '|---|---|'] + [f'| {k} | {v} |' for k, v in st.items()]
    lines += ['', '| Model | Calls | Answers | Median seconds |', '|---|---|---|---|']
    lines += [f"| {m} | {e['calls']} | {', '.join(f'{k}: {v}' for k, v in e['by_status'].items())} | "
              f"{e['median_seconds_ok']} |" for m, e in use.get('models', {}).items()]
    read = [r for r in rows if r['status'] == 'read']
    if read:
        lines += ['', '| Filing | Category | Reader | Shown | Held back |', '|---|---|---|---|---|']
        lines += [f"| {r['exchange']} {r.get('symbol')} | {r.get('category')} | {r.get('reader')} | {r.get('shown')} | "
                  f"{r.get('held')} |" for r in read]
    lines += [f'- note: {n}' for n in setup]
    return '\n'.join(lines) + '\n'


def collect(r2, today: date, dry_run: bool, notes: list):
    """Today's filings of both exchanges. Live: into raw and the archive, then read back from it."""
    from collectors.bse import announcements as bann
    from collectors.bse.client import BSEClient
    from collectors.nse_events import announcements as nann
    from collectors.nse_events.client import NSEClient
    yesterday = today - timedelta(days=1)
    if dry_run:
        nse = NSEClient()
        frames = []
        for market in nann.FEEDS:
            try:
                frames.append(nann.parse(nse.announcements(yesterday, today, market), market))
            except Exception as exc:  # noqa: BLE001
                notes.append(f'NSE {market}: {type(exc).__name__}: {exc}'[:200])
        bse, bframes = BSEClient(), []
        try:
            for day in (today, yesterday):
                bframes.append(bann.parse(bann.fetch_day(bse, day)[0]))
        except Exception as exc:  # noqa: BLE001
            notes.append(f'BSE: {type(exc).__name__}: {exc}'[:200])
        finally:
            bse.close()
        return (pd.concat(frames, ignore_index=True) if frames else None),             (pd.concat(bframes, ignore_index=True) if bframes else None)
    from insiders_clean.raw_store import RawStore
    from r2_writer import BUCKET
    try:
        nann.run(r2, NSEClient(), today, days=COLLECT_DAYS, raw=RawStore(r2, bucket=BUCKET, collector='nse_announcements'),
                 write_report=False)
    except Exception as exc:  # noqa: BLE001 -- the archive may still hold earlier filings
        notes.append(f'NSE collect: {type(exc).__name__}: {exc}'[:200])
    bse = BSEClient(raw=RawStore(r2, collector='bse_announcements'))
    try:
        bann.run(r2, bse, today, days=COLLECT_DAYS, write_report=False, incremental=True)   # stops at known pages
    except Exception as exc:  # noqa: BLE001
        notes.append(f'BSE collect: {type(exc).__name__}: {exc}'[:200])
    finally:
        bse.close()
    return load_archive(r2, nann.PREFIX, today), load_archive(r2, bann.PREFIX, today)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--dry-run', action='store_true', help='fetch today\'s lists, read, print; write nothing')
    ap.add_argument('--max', type=int, default=None, help='read at most this many filings')
    ap.add_argument('--minutes', type=float, default=float(os.environ.get('READER_MINUTES', '22')),
                    help='stop taking new filings after this long')
    args = ap.parse_args(argv)
    today = datetime.now(IST).date()
    setup = []
    lane_spec = lanes_of(LANES_FILE.read_text(encoding='utf-8'))
    entries = [e for es in lane_spec.values() for e in es]
    clients, notes = clients_for(entries)
    setup += notes
    lanes = {n: Lane(n, usable(es), clients) for n, es in lane_spec.items()}
    if not any(lane.models() and any(p in clients for p, _ in lane.models()) for lane in lanes.values()):
        print('No lane has a usable model and key; nothing read.\n' + '\n'.join(setup))
        return 0
    r2 = None
    try:
        from r2_writer import r2_client
        r2 = r2_client()
    except Exception as exc:  # noqa: BLE001
        if not args.dry_run:
            raise
        setup.append(f'no R2 ({type(exc).__name__}); reads before this run not known')
    master = None
    if r2 is not None:
        from collectors.nse_events.run_daily import security_master
        try:
            master = security_master(r2, today.isoformat(), setup)
        except Exception as exc:  # noqa: BLE001
            setup.append(f'no security master ({type(exc).__name__}); market cap and BSE-NSE links unknown')
    nse, bse = collect(r2, today, args.dry_run, setup)
    done = load_archive(r2, READS_PREFIX, today) if r2 is not None else None
    to_read, status_rows, counts = choose(candidates(nse, bse, master), done, today)
    saver = None if args.dry_run else Saver(r2, today.isoformat(), today)
    rows, notes_run = run(to_read, lanes, done, args.minutes * 60, max_filings=args.max,
                          on_row=saver.add if saver else None)
    status = [finish({**r, 'prompt_version': PROMPT_VERSION, 'read_at': datetime.now(timezone.utc).isoformat()})
              for r in status_rows.to_dict('records')]
    rows += status
    use = usage(clients, lanes)
    text = summary_markdown(counts, rows, notes_run, use, setup)
    print(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as f:
            f.write(text)
    if args.dry_run:
        Path('announcement_reader_dry_run.json').write_text(json.dumps(rows, indent=1, ensure_ascii=False, default=str),
                                                            encoding='utf-8')
        return 0
    saver.pending += status
    saver.flush(final=True)
    added = saver.added
    append_usage(r2, today.isoformat(), {'at': datetime.now(timezone.utc).isoformat(), 'counts': counts,
                                         'outcomes': pd.Series([r['status'] for r in rows]).value_counts().to_dict()
                                         if rows else {}, 'added': added, 'usage': use, 'notes': setup})
    return 0


if __name__ == '__main__':
    sys.exit(main())
