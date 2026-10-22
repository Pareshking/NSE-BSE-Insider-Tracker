"""Frames in, clean tables out. No I/O here: scripts/clean_writer.py reads
R2 and the exchange lists, calls run(), and writes what it returns."""
from __future__ import annotations

import pandas as pd

from datetime import date

from .calendar import Calendar
from .deals import clean_deals
from . import universe
from .participants import add_participant_columns, report as participants_report
from .insider import clean_insider
from .missing import normalise
from .promoter_group import link as link_promoter_group
from .report import Report
from .securities import SecurityMaster, bse_list_frame, nse_list_frame

# The product holds transactions dated on or after this day: the last one
# year as of 08 Oct 2026, growing daily from there (owner decision, 08 Oct
# 2026, confirmed 09 Oct). Earlier filings stay in the raw archive and never
# reach a clean table. Insider ranges use the LAST day of the range
# (trade_date_to); a filing with no readable date is held out, because
# nothing proves it is not older.
PRODUCT_START = date(2025, 10, 8)


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
        nse_lists=(), market_cap_rows=None, price_ranges: pd.DataFrame | None = None,
        promoter_group: pd.DataFrame | None = None, market_cap_daily: pd.DataFrame | None = None):
    """
    canonical: {(exchange, category): DataFrame} as stored under canonical/
               in R2 (native + canonical_* columns).
    price_ranges: day ranges from our price layer (insiders_clean.day_range);
               None skips the price check (noted in the report, never an error).
    promoter_group: clean/current/promoter_group.parquet (written by the NSE
               events collector); filings by a member of the company's latest
               list are linked to it (insiders_clean/promoter_group.py).
    market_cap_daily: NSE's daily market caps (insiders_clean.market_cap.load_daily);
               % of market cap is taken on the trade's day. None: every row
               takes the latest market cap (noted in the report).
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

    if price_ranges is None:
        report.note('price check not run: no price layer loaded')
    if market_cap_daily is None:
        report.note('% of market cap on the latest market cap: no daily market-cap layer loaded')
    insider = clean_insider(frames('insider_trading'), master, cal, report, run_date, price_ranges=price_ranges,
                            market_cap_daily=market_cap_daily)
    deals_raw = pd.concat([frames('bulk_deals'), frames('block_deals')], ignore_index=True)
    deals = clean_deals(deals_raw, master, report, run_date, market_cap_daily=market_cap_daily)
    deals = add_participant_columns(deals)  # client type and investor group (TODO 23, 16)
    report.table('deals')['participants'] = participants_report(deals)

    insider = apply_product_window(insider, 'trade_date_to', 'insider_trades', report, 'trade_id')
    if insider is not None and not insider.empty:
        insider, report.data['promoter_group_link'] = link_promoter_group(insider, promoter_group)
    deals = apply_product_window(deals, 'date', 'deals', report, 'deal_id')

    # Every company the master knows, not only those with insider or deal filings: a company with only a
    # corporate action, SAST or shareholding filing needs its name and page too (VRL Logistics, audit 22 Oct).
    securities = master.frame()
    uni = universe.table(master.frame())   # every ISIN we know, not only those in filings
    report.data['universe'] = universe.report(uni)
    return {'insider_trades': insider, 'deals': deals, 'securities': securities, 'universe': uni}, report.data
