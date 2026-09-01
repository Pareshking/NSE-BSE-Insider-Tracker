"""NSE market cap reference data -- Phase 0.5 of ANALYTICS_PLAN.md.

Feeds the "% of market cap" materiality metric: a given rupee/share figure
means completely different things depending on company size, and nothing
in the pipeline computed that until now.

Verified live (2026-09-01) before writing any of this: jugaad-data's
NSELive().stock_quote(symbol) call works from a plain Python process (no
Selenium/browser session needed, unlike the bulk/block/insider scripts --
this library handles NSE's session/cookie dance internally). The response
carries `tradeInfo.totalMarketCap` computed directly by NSE itself
(cross-checked against two real symbols: RELIANCE ~Rs.17.7 lakh Cr,
20 Microns ~Rs.756 Cr -- the latter matches security_master's own "Small
Cap" tag for that company). No need to multiply issuedSize x lastPrice
ourselves; NSE already does it.

Scope deliberately narrow: this fetches market cap only for NSE symbols
that actually appear in *this run's* insider/bulk/block data, not the
full ~3,100-symbol security-master universe -- there is no reason to make
3,000+ live calls a day for companies with zero activity, and it keeps
this well clear of NSE's anti-bot sensitivity that has caused real
breakage elsewhere in this project (see nse_bulk.py's docstring).

BSE-only symbols (no NSE listing) are NOT covered here -- see
ANALYTICS_PLAN.md's Phase 0.5 section for the coarse `mcap_category`
fallback used for those.
"""
from __future__ import annotations
import json, os, time
from datetime import date
from pathlib import Path

from jugaad_data.nse import NSELive

TARGET = date.fromisoformat(os.getenv('TARGET_DATE', str(date.today())))
OUT = Path('artifacts/nse_market_cap')
OUT.mkdir(parents=True, exist_ok=True)

# Each entry: (artifact path, key holding the row list, field name for the
# NSE symbol within each row). insider_trading's full-row file is the
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


def fetch_market_cap(nse_live: NSELive, symbol: str, retries: int = 2) -> dict:
    last_exc = None
    for attempt in range(retries + 1):
        try:
            q = nse_live.stock_quote(symbol)
            trade = q.get('tradeInfo', {}) or {}
            meta = q.get('metaData', {}) or {}
            issued_size = trade.get('issuedSize')
            last_price = trade.get('lastPrice')
            market_cap = trade.get('totalMarketCap')
            if market_cap is None and issued_size and last_price:
                market_cap = float(issued_size) * float(last_price)
            if market_cap is None:
                raise ValueError(f'no totalMarketCap/issuedSize+lastPrice in response (attempt {attempt+1})')
            return {
                'symbol': symbol,
                'isin': meta.get('isinCode'),
                'company_name': meta.get('companyName'),
                'issued_size': issued_size,
                'last_price': last_price,
                'market_cap': market_cap,
                'status': 'ok',
                'attempts': attempt + 1,
            }
        except Exception as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(2)
    return {'symbol': symbol, 'status': 'failed', 'error': str(last_exc), 'attempts': retries + 1}


def main():
    print(f'Collecting NSE symbols with activity on {TARGET}...')
    symbols = collect_symbols()
    print(f'Total distinct symbols needing market cap: {len(symbols)}')

    nse_live = NSELive()
    rows, failures = [], []
    for i, symbol in enumerate(symbols):
        result = fetch_market_cap(nse_live, symbol)
        if result['status'] == 'ok':
            rows.append(result)
        else:
            failures.append(result)
        if (i + 1) % 25 == 0:
            print(f'  ...{i + 1}/{len(symbols)} done ({len(rows)} ok, {len(failures)} failed)')
        time.sleep(0.5)

    print(f'Resolved: {len(rows)}/{len(symbols)} ({len(failures)} failed)')

    report = {
        'source': 'NSE', 'dataset': 'market_cap',
        'target_date': str(TARGET),
        'method': "jugaad_data.nse.NSELive().stock_quote(symbol), tradeInfo.totalMarketCap "
                  "(plain HTTP via jugaad-data, no Selenium needed -- verified live 2026-09-01)",
        'symbols_requested': len(symbols),
        'symbols_resolved': len(rows),
        'symbols_failed': len(failures),
        'failures': failures,
        'columns': ['symbol', 'isin', 'company_name', 'issued_size', 'last_price', 'market_cap'],
        'rows': rows,
    }
    Path(OUT / 'report.json').write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps({k: v for k, v in report.items() if k != 'rows'}, indent=2))


if __name__ == '__main__':
    main()
