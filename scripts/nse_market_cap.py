"""NSE market cap reference data -- Phase 0.5 of ANALYTICS_PLAN.md.

Feeds the "% of market cap" materiality metric: a given rupee/share figure
means completely different things depending on company size, and nothing
in the pipeline computed that until now.

2026-09-01 finding, in order:

1. First version called jugaad-data's NSELive().stock_quote() once per
   symbol -- worked, but ~638 individual live calls for one day's
   insider+bulk+block activity (~18 minutes), needlessly exposed to NSE's
   anti-bot sensitivity that has already broken other parts of this
   pipeline (see nse_bulk.py's docstring).
2. User pointed at github.com/Pareshking/Paresh (a sibling quant project),
   which solves this with a single whole-market file: NSE's Bhavcopy "PR"
   zip (a DIFFERENT, older report format from the sec_bhavdata_full/UDIFF
   bhavcopy variants, which do NOT carry market cap -- confirmed by
   inspecting both directly) at
   https://archives.nseindia.com/archives/equities/bhavcopy/pr/PR{DDMMYY}.zip,
   containing a `mcap{DDMMYYYY}.csv` member with an official, pre-computed
   `Market Cap(Rs.)` column for ~2,300-3,100 EQ-series stocks in ONE
   request. Verified live: the RELIANCE figure matches jugaad-data's live
   NSELive() figure exactly (Rs.17,714,093,187,098).
3. First version then added a per-symbol jugaad-data fallback for the
   ~26% of that day's needed symbols the PR zip didn't cover. Measured
   real cost/benefit: 160 of 163 fallback attempts failed outright
   (deterministic per symbol, not transient), rescuing only 3 net new
   symbols for several minutes of runtime and a hard dependency on
   nse_insider/nse_bulk/nse_block already having run first.
4. User's direction, matching that data: stop searching per-symbol
   entirely. Download the full file, use it for whatever symbols it
   covers, and treat "this stock is only listed on the other exchange (or
   not covered by this file)" as a real, accepted limit rather than a gap
   to patch with individual lookups. Dropped the fallback and the
   per-run symbol-collection step -- this script now just dumps the whole
   PR zip's universe every run, independent of any other acquisition step
   having completed first (same shape as scripts/bse_market_cap.py).
5. User then flagged that the mcap*.csv file wasn't being read fully: it
   was filtered to `Series == 'EQ'` only, on the (untested) assumption
   that other series might duplicate a symbol under a different paid-up
   value. Checked real data: the file has 3,171 rows across EQ (2,301),
   SM/ST (SME, 448+116), and BE/BZ/IV/RR/SZ/IT (870 total non-EQ) --
   exactly one Symbol value repeats across rows, and it's a "TOTAL"
   grand-total footer row, not a real security. So the EQ filter was
   discarding 870 legitimate rows for a collision risk that doesn't
   exist in practice. Removed the series filter (excluding "TOTAL" by
   name instead). Real coverage against that day's 638 actual
   NSE-transacting symbols: 475 (74.4%) with EQ-only -> 632 (99.1%)
   without it.
"""
from __future__ import annotations
import io, json, os, zipfile
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

TARGET = date.fromisoformat(os.getenv('TARGET_DATE', str(date.today())))
OUT = Path('artifacts/nse_market_cap')
OUT.mkdir(parents=True, exist_ok=True)
HTTP_HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}


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

    # NOT filtered to Series == 'EQ' -- checked real data (2026-09-01) and
    # that filter was silently discarding 870 of 3,171 rows: SM (448, SME
    # mainboard) and ST (116) are the user-flagged SME series, plus BE/BZ/IV/
    # RR/SZ/IT (real listed instruments too, not just noise). Real-data
    # coverage check against that day's 638 actual NSE-transacting symbols:
    # EQ-only found 475 (74.4%); no series filter found 632 (99.1%). The
    # user's own earlier concern that mixed series would cause one symbol's
    # row to overwrite another's under a different (possibly stale) paid-up
    # value turned out to be a non-issue in practice: exactly one Symbol
    # value repeats across rows in a real file, and it's a "TOTAL" grand-total
    # footer row, not a real security -- excluded by name below, not by
    # series, so no genuine duplicate-collision risk remains.
    df[col_sym] = df[col_sym].astype(str).str.strip().str.upper()
    df = df[df[col_sym] != 'TOTAL']
    df[col_mcap] = pd.to_numeric(df[col_mcap].astype(str).str.replace(',', ''), errors='coerce')
    df = df[df[col_mcap].notna() & (df[col_mcap] > 0)]

    result = {}
    for _, row in df.iterrows():
        result[row[col_sym]] = {
            'symbol': row[col_sym],
            'isin': row[col_isin] if col_isin else None,
            'market_cap': float(row[col_mcap]),
            'series': row[col_series] if col_series else None,
            'source': 'pr_zip',
            'pr_zip_date': str(target_date),
        }
    print(f'  PR zip for {target_date}: {len(result)} symbols with market cap (all series)')
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


def main():
    print(f'Fetching whole-market NSE PR bhavcopy zip for {TARGET}...')
    caps, pr_date = fetch_pr_zip_recent(TARGET)
    rows = list(caps.values())
    print(f'Total NSE symbols with market cap (all series): {len(rows)}')

    report = {
        'source': 'NSE', 'dataset': 'market_cap',
        'target_date': str(TARGET),
        'method': 'NSE PR bhavcopy zip (whole-market mcap*.csv, official Market Cap(Rs.) column, all '
                  'series -- EQ, SME (SM/ST), and others -- not filtered to EQ only) -- no per-symbol '
                  'lookups; a stock not in this file (BSE-only, or otherwise uncovered) is a real, '
                  'accepted limit, not patched with individual searches',
        'pr_zip_date_used': pr_date,
        'symbols_resolved': len(rows),
        'columns': ['symbol', 'isin', 'market_cap', 'series', 'source'],
        'rows': rows,
    }
    Path(OUT / 'report.json').write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps({k: v for k, v in report.items() if k != 'rows'}, indent=2))


if __name__ == '__main__':
    main()
