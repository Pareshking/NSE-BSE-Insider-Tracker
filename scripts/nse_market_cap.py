"""NSE market cap reference data -- Phase 0.5 of ANALYTICS_PLAN.md.

Feeds the "% of market cap" materiality metric: a given rupee/share figure
means completely different things depending on company size, and nothing
in the pipeline computed that until now.

2026-09-01 finding, in order:

1. First version of this script called jugaad-data's NSELive().stock_quote()
   once per symbol -- worked, but ~638 individual live calls for one day's
   insider+bulk+block activity, ~1.7s each (~18 minutes), and needlessly
   exposed to NSE's anti-bot sensitivity that has already broken other parts
   of this pipeline (see nse_bulk.py's docstring).
2. User pointed at github.com/Pareshking/Paresh (a sibling quant project)
   which already solves this exact problem with a single whole-market file:
   NSE's Bhavcopy "PR" zip (a DIFFERENT, older report format from the
   sec_bhavdata_full/UDIFF bhavcopy variants, which do NOT carry market cap
   -- confirmed by inspecting both directly) at
   https://archives.nseindia.com/archives/equities/bhavcopy/pr/PR{DDMMYY}.zip,
   containing a `mcap{DDMMYYYY}.csv` member with an official, pre-computed
   `Market Cap(Rs.)` column for ~2,300-3,100 EQ-series stocks in ONE request.
   Verified live from this environment: the RELIANCE figure in this file
   matches jugaad-data's live NSELive() figure exactly (Rs.17,714,093,187,098).
   That sibling project also documents a months-long false belief that NSE
   blocks this fetch from CI -- it turned out to be a logging bug silently
   discarding a successful parse, the same shape of mistake this project's
   own bulk-deals "IP block" theory turned out to be. Treat any future
   "NSE is blocking us" claim here with the same suspicion until proven.
3. Real coverage check against this run's actual needed symbols (638, from
   insider+bulk+block's 90-day window): the PR zip covers 475/638 (74%) --
   the gap is SME/micro-cap-board names that bulk deals frequently include
   and NSE's mainboard PR archive does not track. No SME-equivalent bulk
   file was found (two guessed URL patterns both 404'd -- not chased further
   per this project's own rule against trusting a guessed endpoint shape).
   So: PR zip first (fast, official, most of the universe), then the
   original per-symbol NSELive() approach as a fallback ONLY for whatever
   the PR zip didn't cover -- typically under 200 symbols, not 638.

BSE-only symbols (no NSE listing at all) are NOT covered by either path --
see ANALYTICS_PLAN.md's Phase 0.5 section for the coarse `mcap_category`
fallback used for those.
"""
from __future__ import annotations
import io, json, os, time, zipfile
from datetime import date, timedelta
from pathlib import Path

import requests

TARGET = date.fromisoformat(os.getenv('TARGET_DATE', str(date.today())))
OUT = Path('artifacts/nse_market_cap')
OUT.mkdir(parents=True, exist_ok=True)
HTTP_HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

# Each entry: (artifact path, key holding the row list, field name for the
# NSE symbol within each row). insider_trading's full-row file is the 90d
# window file (report.json strips rows), bulk/block keep rows in report.json.
SYMBOL_SOURCES = [
    ('artifacts/nse_insider/90d.json', 'rows', 'symbol'),
    ('artifacts/nse_bulk/report.json', 'rows', 'BD_SYMBOL'),
    ('artifacts/nse_block/report.json', 'rows', 'BD_SYMBOL'),
]


def collect_symbols() -> list[str]:
    symbols = set()
    for path, rows_key, field in SYMBOL_SOURCES:
        p = Path(path)
        if not p.exists():
            print(f'  (skip, not found) {path}')
            continue
        try:
            obj = json.loads(p.read_text())
        except Exception as exc:
            print(f'  (skip, unreadable) {path}: {exc}')
            continue
        rows = obj.get(rows_key, []) if isinstance(obj, dict) else []
        found = {str(r.get(field, '')).strip().upper() for r in rows if r.get(field)}
        print(f'  {path}: {len(found)} distinct symbols')
        symbols |= found
    symbols.discard('')
    return sorted(symbols)


class NSEBlocked(Exception):
    """NSE refused the client outright (401/403/429) -- trying an earlier
    date cannot help, unlike a plain 404 which just means "not published
    yet" or "holiday, no archive for this date"."""


def fetch_pr_zip_market_caps(target_date: date) -> dict:
    """One request, whole market. Returns {} if this date's archive isn't
    published (weekend/holiday/too-recent) -- caller tries an earlier date."""
    zip_date = target_date.strftime('%d%m%y')
    csv_date = target_date.strftime('%d%m%Y')
    url = f'https://archives.nseindia.com/archives/equities/bhavcopy/pr/PR{zip_date}.zip'
    resp = requests.get(url, headers=HTTP_HEADERS, timeout=20)
    if resp.status_code in (401, 403, 429):
        raise NSEBlocked(f'HTTP {resp.status_code} for {url}')
    if resp.status_code != 200:
        print(f'  PR zip for {target_date}: HTTP {resp.status_code} (not published, or holiday)')
        return {}

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        names = zf.namelist()
        mcap_name = f'mcap{csv_date}.csv'
        if mcap_name not in names:
            mcap_name = next((n for n in names if n.lower().startswith('mcap')), None)
        if not mcap_name:
            print(f'  PR zip for {target_date}: no mcap*.csv member found')
            return {}
        import pandas as pd
        with zf.open(mcap_name) as f:
            df = pd.read_csv(f)
    df.columns = df.columns.str.strip()
    col_sym = next((c for c in df.columns if 'symbol' in c.lower()), None)
    col_mcap = next((c for c in df.columns if 'market cap' in c.lower()), None)
    col_series = next((c for c in df.columns if c.lower().strip() == 'series'), None)
    col_isin = next((c for c in df.columns if 'isin' in c.lower()), None)
    if not col_sym or not col_mcap:
        print(f'  PR zip for {target_date}: missing symbol/market-cap column, got {list(df.columns)}')
        return {}

    if col_series is not None:
        df = df[df[col_series].astype(str).str.strip().str.upper() == 'EQ']
    df[col_sym] = df[col_sym].astype(str).str.strip().str.upper()
    df[col_mcap] = pd.to_numeric(df[col_mcap].astype(str).str.replace(',', ''), errors='coerce')
    df = df[df[col_mcap].notna() & (df[col_mcap] > 0)]

    result = {}
    for _, row in df.iterrows():
        result[row[col_sym]] = {
            'symbol': row[col_sym],
            'isin': row[col_isin] if col_isin else None,
            'market_cap': float(row[col_mcap]),
            'source': 'pr_zip',
            'pr_zip_date': str(target_date),
        }
    print(f'  PR zip for {target_date}: {len(result)} EQ-series symbols with market cap')
    return result


def fetch_pr_zip_recent(latest: date, lookback_days: int = 6) -> tuple[dict, str | None]:
    """Walk back through recent days -- today's archive isn't published
    until after close, weekends/holidays have none. Stops immediately on a
    real block (401/403/429): every earlier date would be refused too."""
    for i in range(lookback_days):
        d = latest - timedelta(days=i)
        try:
            result = fetch_pr_zip_market_caps(d)
        except NSEBlocked as exc:
            print(f'  PR archive blocked ({exc}); not trying earlier dates.')
            return {}, None
        if result:
            return result, str(d)
    return {}, None


def fetch_single_via_nselive(symbol: str, retries: int = 2) -> dict:
    """Fallback for symbols the PR zip doesn't cover (mostly SME board)."""
    from jugaad_data.nse import NSELive
    last_exc = None
    for attempt in range(retries + 1):
        try:
            q = NSELive().stock_quote(symbol)
            trade = q.get('tradeInfo', {}) or {}
            meta = q.get('metaData', {}) or {}
            market_cap = trade.get('totalMarketCap')
            if market_cap is None:
                issued, last = trade.get('issuedSize'), trade.get('lastPrice')
                if issued and last:
                    market_cap = float(issued) * float(last)
            if market_cap is None:
                raise ValueError('no totalMarketCap/issuedSize+lastPrice in response')
            return {
                'symbol': symbol, 'isin': meta.get('isinCode'), 'market_cap': market_cap,
                'source': 'nselive_fallback', 'status': 'ok',
            }
        except Exception as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(2)
    return {'symbol': symbol, 'status': 'failed', 'error': str(last_exc), 'source': 'nselive_fallback'}


def main():
    print(f'Collecting NSE symbols with activity on {TARGET}...')
    symbols = collect_symbols()
    print(f'Total distinct symbols needing market cap: {len(symbols)}')

    print('Fetching whole-market NSE PR bhavcopy zip (primary source)...')
    pr_caps, pr_date = fetch_pr_zip_recent(TARGET)

    rows, failures = [], []
    missing = []
    for symbol in symbols:
        if symbol in pr_caps:
            rows.append(pr_caps[symbol])
        else:
            missing.append(symbol)

    print(f'Covered by PR zip: {len(rows)}/{len(symbols)}; falling back per-symbol for {len(missing)}...')
    # Sequential-with-sleep took ~6 minutes for ~163 symbols -- the sibling
    # Paresh project's own yfinance fallback (same shape of problem: no bulk
    # endpoint, one request per name) runs 8 concurrent workers instead.
    # NSELive() sessions aren't shared across threads (each call makes its
    # own instance), so this parallelizes safely the same way.
    from concurrent.futures import ThreadPoolExecutor, as_completed
    done = 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(fetch_single_via_nselive, s): s for s in missing}
        for fut in as_completed(futures):
            result = fut.result()
            if result.get('status') == 'ok' or 'market_cap' in result:
                rows.append(result)
            else:
                failures.append(result)
            done += 1
            if done % 25 == 0:
                print(f'  ...{done}/{len(missing)} fallback done')

    print(f'Resolved: {len(rows)}/{len(symbols)} ({len(failures)} failed)')

    report = {
        'source': 'NSE', 'dataset': 'market_cap',
        'target_date': str(TARGET),
        'method': 'NSE PR bhavcopy zip (whole-market mcap*.csv, official Market Cap(Rs.) column) '
                  'as primary source, jugaad_data.nse.NSELive().stock_quote() per-symbol fallback '
                  'for names the PR zip does not cover (mostly SME board)',
        'pr_zip_date_used': pr_date,
        'symbols_requested': len(symbols),
        'symbols_from_pr_zip': sum(1 for r in rows if r.get('source') == 'pr_zip'),
        'symbols_from_fallback': sum(1 for r in rows if r.get('source') == 'nselive_fallback'),
        'symbols_resolved': len(rows),
        'symbols_failed': len(failures),
        'failures': failures,
        'columns': ['symbol', 'isin', 'market_cap', 'source'],
        'rows': rows,
    }
    Path(OUT / 'report.json').write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps({k: v for k, v in report.items() if k != 'rows'}, indent=2))


if __name__ == '__main__':
    main()
