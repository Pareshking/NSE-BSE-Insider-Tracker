"""Frames in, clean tables out. No I/O here: scripts/clean_writer.py reads
R2 and the exchange lists, calls run(), and writes what it returns."""
from __future__ import annotations

import pandas as pd

from datetime import date

from .calendar import Calendar
from .deals import clean_deals
from .insider import clean_insider
from .missing import normalise
from .report import Report
from .securities import SecurityMaster, bse_list_frame, nse_list_frame

# The product holds transactions dated on or after this day (owner decision,
# 09 Oct 2026). Earlier filings stay in the raw archive for offline research
# only and never reach a clean table. Insider ranges use the LAST day of the
# range (trade_date_to); a filing with no readable date is held out, because
# nothing proves it is not older.
PRODUCT_START = date(2026, 1, 1)


def apply_product_window(table: pd.DataFrame, date_col: str, name: str, report, id_col: str) -> pd.DataFrame:
    if table is None or table.empty:
        return table
    d = pd.to_datetime(table[date_col], errors='coerce')
    before = d < pd.Timestamp(PRODUCT_START)
    undated = d.isna()
    report.removed(name, 'before_product_start', table.loc[before, id_col])
    report.removed(name, 'no_readable_transaction_date', table.loc[undated, id_col])
    kept = table.loc[~before & ~undated].reset_index(drop=True)
    report.table(name)['output_rows'] = len(kept)
    report.table(name)['by_exchange'] = kept['exchange'].value_counts().to_dict() if len(kept) else {}
    return kept


def run(canonical: dict, run_date: str, calendar_state: dict, vr_master: pd.DataFrame | None = None,
        nse_lists=(), market_cap_rows=None):
    """
    canonical: {(exchange, category): DataFrame} as stored under canonical/
               in R2 (native + canonical_* columns).
    Returns ({table_name: DataFrame}, report_dict).
    """
    report = Report(run_date)
    master = SecurityMaster(vr_master=vr_master, nse_list=nse_list_frame(*nse_lists),
                            bse_list=bse_list_frame(market_cap_rows), market_cap_rows=market_cap_rows)
    cal = Calendar.from_state(calendar_state)
    report.data['calendar'] = {'confirmed_through': cal.confirmed_through.isoformat(),
                               'first': cal.first.isoformat() if cal.first else None}
    report.data['security_sources'] = {
        'nse_symbols': len(master.by_nse), 'bse_codes': len(master.by_bse), 'isins': len(master.records)}

    def frames(category):
        parts = []
        for ex in ('nse', 'bse'):
            f = canonical.get((ex, category))
            if f is not None and not f.empty:
                parts.append(normalise(f).assign(exchange=ex, category=category))
        return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()

    insider = clean_insider(frames('insider_trading'), master, cal, report, run_date)
    deals_raw = pd.concat([frames('bulk_deals'), frames('block_deals')], ignore_index=True)
    deals = clean_deals(deals_raw, master, report, run_date)

    insider = apply_product_window(insider, 'trade_date_to', 'insider_trades', report, 'trade_id')
    deals = apply_product_window(deals, 'date', 'deals', report, 'deal_id')

    used = pd.concat([s for s in (insider.get('isin'), deals.get('isin')) if s is not None]).dropna()
    securities = master.frame(used.unique())
    return {'insider_trades': insider, 'deals': deals, 'securities': securities}, report.data
