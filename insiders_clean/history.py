"""NSE's historical endpoints -> the same native fields the nightly
scrapers write, so history and daily data share one cleaning path.

Confirmed on 07 Oct 2026 (one request per check):
* Insider trading: /api/corporates-pit?index=equities&from_date=&to_date=
  returns full rows back to 19 Nov 2015 (01-07 Mar 2016: 578 rows). The
  nightly scraper uses /api/corporates-pit-gg plus one XBRL file per filing;
  this endpoint carries the same facts under older names.
* Bulk / block deals: /api/historicalOR/bulk-block-short-deals?optionType=
  bulk_deals|block_deals&from=&to=&csv=true, back to Jan 2004 / Nov 2005.

The maps below are explicit: every historical field either lands on the
nightly name or is kept under its own name. Nothing is dropped, so a field
can still be audited after mapping.
"""
from __future__ import annotations

import csv
import io

# Historical insider field -> nightly field (scripts/nse_insider.py::to_row).
PIT_FIELDS = {
    'symbol': 'symbol',
    'company': 'companyName',
    'acqName': 'acqName',
    'personCategory': 'personCategory',
    'secType': 'secType',
    'acqMode': 'modeOfAcquisition',
    'befAcqSharesNo': 'beforeSharesNo',
    'afterAcqSharesNo': 'afterSharesNo',
    'acqfromDt': 'acqfromDt',
    'acqtoDt': 'acqtoDt',
    'intimDt': 'intimDt',
    'date': 'broadcastDt',      # "07-Mar-2016 18:50": when NSE published it
}
# Kept as they are, under a history_ prefix (no nightly equivalent).
PIT_KEPT = ('did', 'pid', 'exchange', 'anex', 'remarks', 'befAcqSharesPer', 'afterAcqSharesPer',
            'derivativeType', 'tdpDerivativeContractType', 'securitiesTypePost', 'xbrl')
# Values NSE uses for "nothing" in this feed.
_EMPTY = {'-', '', 'NA', 'N.A.', 'None', 'null'}
_ZERO = {'Nil', 'NIL', 'nil'}

# Bulk/block CSV header (BOM and trailing spaces stripped) -> nightly field
# (scripts/nse_bulk.py / nse_block.py, read by r2_writer.canonicalize).
DEAL_FIELDS = {
    'Date': 'BD_DT_DATE',
    'Symbol': 'BD_SYMBOL',
    'Security Name': 'BD_SCRIP_NAME',
    'Client Name': 'BD_CLIENT_NAME',
    'Buy / Sell': 'BD_BUY_SELL',
    'Quantity Traded': 'BD_QTY_TRD',
    'Trade Price / Wght. Avg. Price': 'BD_TP_WATP',
    'Remarks': 'BD_REMARKS',
}


def _clean(v):
    if v is None:
        return ''
    s = str(v).strip()
    if s in _EMPTY:
        return ''
    if s in _ZERO:
        return '0'
    return s


def _positive(v) -> bool:
    try:
        return float(str(v).replace(',', '')) > 0
    except ValueError:
        return False


def pit_row(h: dict) -> dict:
    """One historical insider row -> the nightly row shape."""
    row = {new: _clean(h.get(old)) for old, new in PIT_FIELDS.items()}
    for k in PIT_KEPT:
        row[f'history_{k}'] = _clean(h.get(k))
    tdp = _clean(h.get('tdpTransactionType'))
    # Side: the feed's own Buy/Sell first; for ESOP/pledge rows fall back to
    # which quantity is filled, as the nightly parser does.
    if tdp.lower() == 'buy' or (tdp.lower() not in ('sell',) and _positive(h.get('buyQuantity'))):
        txn = 'Acquisition'
    elif tdp.lower() == 'sell' or _positive(h.get('sellquantity')):
        txn = 'Disposal'
    else:
        txn = tdp or ''
    row['transactionType'] = txn
    row['history_tdpTransactionType'] = tdp
    qty, val = _clean(h.get('secAcq')), _clean(h.get('secVal'))
    # canonicalize() takes the first non-empty of buy/sell, and the feed
    # writes '0' in the unused one -- so the unused side must be empty.
    row['buyQuantity'] = qty if txn == 'Acquisition' else ''
    row['sellquantity'] = qty if txn == 'Disposal' else ''
    row['buyValue'] = val if txn == 'Acquisition' else ''
    row['sellValue'] = val if txn == 'Disposal' else ''
    if txn not in ('Acquisition', 'Disposal'):
        # Pledges: no side; keep the quantity where canonicalize finds it.
        row['buyQuantity'], row['buyValue'] = qty, val
    # The nightly 'date' is the intimation date (falls back to broadcast).
    row['date'] = row['intimDt'] or row['broadcastDt']
    row['appId'] = ''
    row['source'] = 'nse_corporates_pit_history'
    return row


def deal_rows(csv_bytes: bytes) -> list[dict]:
    """NSE's historical bulk/block CSV -> nightly-shaped rows."""
    text = csv_bytes.decode('utf-8-sig', errors='replace')
    reader = csv.DictReader(io.StringIO(text))
    out = []
    for r in reader:
        clean = {str(k).strip(): v for k, v in r.items() if k is not None}
        row = {new: _clean(clean.get(old)) for old, new in DEAL_FIELDS.items()}
        if not row['BD_SYMBOL']:
            continue
        row['source'] = 'nse_historical_deals_csv'
        out.append(row)
    return out
