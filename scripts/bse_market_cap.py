"""BSE market cap reference data -- closes the gap nse_market_cap.py leaves
for BSE-only names (no NSE listing at all).

User pointed at BSE's own "List of Listed Companies" utility (Segment:
Equity, Status: Active) as a two-step workaround: bhavcopy close price +
a shares-outstanding master, multiplied together. Checked what the `bse`
package (already in requirements.txt for other BSE scripts) actually
exposes before building that two-step join: `BSE().listSecurities(group=...)`
already returns a `Mktcap` field directly, in Rs. Crore, precomputed by BSE
itself -- same shape of finding as NSE's PR zip (an official file already
has the computed number, no need to derive it from two datasets). Verified
2026-09-01: RELIANCE's BSE Mktcap (Rs.17,69,176.45 Cr) matches NSE's live
figure for the same company (Rs.17,71,409.3 Cr) to within same-day price
movement, and it's fast -- four groups (A/B/T/X) returned 3,906 rows in
under 4 seconds combined, not the whole-day job the two-step approach
would have been.

`listSecurities` is scoped per BSE group (A, B, T, X, Z, ...) -- there is
no single "all groups" call, so this makes one request per group (24
total, ~15-20s all in) rather than one bulk request like NSE's PR zip.
Still one order of magnitude cheaper than per-symbol NSE-style calls.
"""
from __future__ import annotations
import json, os
from datetime import date
from pathlib import Path

from bse import BSE

TARGET = date.fromisoformat(os.getenv('TARGET_DATE', str(date.today())))
OUT = Path('artifacts/bse_market_cap')
OUT.mkdir(parents=True, exist_ok=True)


def fetch_all_groups() -> tuple[dict, list]:
    b = BSE(download_folder='/tmp/bse_market_cap_dl')
    rows, failures = {}, []
    for group in b.valid_groups:
        try:
            entries = b.listSecurities(group=group)
        except Exception as exc:
            failures.append({'group': group, 'error': str(exc)})
            print(f'  group {group}: FAILED ({exc})')
            continue
        added = 0
        for e in entries:
            scrip = str(e.get('SCRIP_CD') or '').strip()
            mktcap_raw = e.get('Mktcap')
            if not scrip or mktcap_raw in (None, '', '0', '0.00'):
                continue
            try:
                market_cap_cr = float(str(mktcap_raw).replace(',', ''))
            except ValueError:
                continue
            if market_cap_cr <= 0:
                continue
            # Already-seen scrip code from an earlier group takes precedence
            # -- BSE's own group listing shouldn't have real duplicates, but
            # never silently overwrite with a second, possibly stale figure.
            if scrip in rows:
                continue
            rows[scrip] = {
                'symbol': scrip,
                'isin': e.get('ISIN_NUMBER'),
                'company_name': e.get('Scrip_Name'),
                'market_cap': market_cap_cr * 1e7,  # Cr -> raw rupees, matching NSE's units
                'source': 'bse_list_securities',
                'group': group,
            }
            added += 1
        print(f'  group {group}: {len(entries)} securities, {added} with a usable market cap')
    return rows, failures


def main():
    print(f'Fetching BSE market cap for all listed-security groups on {TARGET}...')
    rows_by_scrip, failures = fetch_all_groups()
    rows = list(rows_by_scrip.values())
    print(f'Total BSE scrips with market cap: {len(rows)} ({len(failures)} group fetch failures)')

    report = {
        'source': 'BSE', 'dataset': 'market_cap',
        'target_date': str(TARGET),
        'method': "bse.BSE().listSecurities(group=...) across all valid_groups -- official, "
                  "pre-computed Mktcap (Rs. Crore) field, one request per BSE group",
        'groups_fetched': len(failures) == 0,
        'group_failures': failures,
        'symbols_resolved': len(rows),
        'columns': ['symbol', 'isin', 'company_name', 'market_cap', 'source', 'group'],
        'rows': rows,
    }
    Path(OUT / 'report.json').write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps({k: v for k, v in report.items() if k != 'rows'}, indent=2))


if __name__ == '__main__':
    main()
