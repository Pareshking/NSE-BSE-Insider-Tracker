"""Read-only diagnostic for the clean step's data checks (TODO 19) and NSE's revision markers (TODO 14).

Runs the clean step exactly as scripts/clean_writer.py does, on what is already in R2 (archive, reference
files, price layer), but writes nothing to R2: the R2 client is wrapped so any call other than a read raises.
Results go to artifacts/data_checks/ (uploaded by the workflow as a run artifact):

  summary.json          counts per check, per outcome, per kind; revision-marker counts
  insider_checks.csv    every clean insider row that a check touched (flagged, or price not inside), with
                        the fields the checks read (exchange filings are public; nothing personal)
  deals_checks.csv      the same for deals
  day_ranges_sample.csv day ranges for the ISINs and days of the rows above (for test fixtures)

Usage: TARGET_DATE=YYYY-MM-DD python scripts/data_checks_diagnose.py
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

import clean_writer  # noqa: E402
from r2_writer import SECURITY_MASTER_PATH, TARGET_DATE, r2_client  # noqa: E402

from insiders_clean.calendar import seed_state  # noqa: E402
from insiders_clean.pipeline import run  # noqa: E402

OUT = ROOT / 'artifacts' / 'data_checks'
NEW_FLAGS = ('holding_change_differs_from_quantity', 'holding_moves_against_side', 'price_outside_day_range',
             'value_off_by_power_of_ten', 'quantity_value_swapped', 'price_off_by_power_of_ten',
             'quantity_price_swapped', 'disclosed_before_trade', 'disclosure_dated_in_future',
             'dates_out_of_order', 'trade_date_in_future', 'date_in_future')


class ReadOnly:
    """An R2 client that can only read."""
    ALLOWED = frozenset({'get_object', 'list_objects_v2', 'head_object'})

    def __init__(self, client):
        self._client = client
        self.exceptions = client.exceptions

    def __getattr__(self, name):
        if name not in self.ALLOWED:
            raise PermissionError(f'read-only diagnostic: {name} refused')
        return getattr(self._client, name)


def counts(s: pd.Series) -> dict:
    return {str(k): int(v) for k, v in s.value_counts(dropna=False).items()}


def flag_counts(df: pd.DataFrame) -> dict:
    exploded = df['flags'].fillna('').str.split(',').explode()
    return counts(exploded[exploded != ''])


def text_not_numeric(s: pd.Series) -> dict:
    t = s.dropna().astype(str).str.strip()
    t = t[t != '']
    bad = t[pd.to_numeric(t.str.replace(',', '', regex=False), errors='coerce').isna()]
    return {str(k): int(v) for k, v in bad.value_counts().head(20).items()}


def revision_markers(arch: pd.DataFrame | None, clean: pd.DataFrame) -> dict:
    """TODO 14: are prevAppId / typeOfSubmission / revisionRemark filled on NSE rows collected since the
    collector started keeping them?"""
    out = {}
    if arch is not None and not arch.empty:
        a = arch.copy()
        src = a['source'].astype('string').fillna('') if 'source' in a.columns else pd.Series('', index=a.index)
        a['_history'] = src.str.contains('history')
        a['_first_seen'] = a['first_seen'].astype(str) if 'first_seen' in a.columns else ''

        def filled(col):
            if col not in a.columns:
                return pd.Series(False, index=a.index)
            v = a[col].astype('string').str.strip()
            return v.notna() & v.ne('') & v.ne('None') & v.ne('<NA>')

        cols = ('canonical_prev_app_id', 'canonical_submission_type', 'canonical_revision_remark')
        per_day = []
        for day, g in a[~a['_history']].groupby('_first_seen'):
            per_day.append({'first_seen': day, 'rows': len(g), **{c: int(filled(c)[g.index].sum()) for c in cols}})
        out['archive_nightly_by_first_seen'] = per_day[-12:]
        out['archive_rows'] = len(a)
        out['archive_history_rows'] = int(a['_history'].sum())
        out['archive_columns_present'] = [c for c in cols if c in a.columns]
        for c in cols:
            if c in a.columns:
                out[f'archive_{c}_values'] = counts(a.loc[filled(c), c].astype(str).str.slice(0, 60))
                if len(out[f'archive_{c}_values']) > 15:
                    out[f'archive_{c}_values'] = dict(list(out[f'archive_{c}_values'].items())[:15])
        recent = a[~a['_history'] & a['_first_seen'].ge('2026-10-09')]
        out['archive_rows_first_seen_from_2026_10_09'] = len(recent)
        out['archive_filled_from_2026_10_09'] = {c: int(filled(c)[recent.index].sum()) for c in cols}
        # last_seen: rows the 09 Oct+ collector returned again (filled only if it re-wrote them)
        if 'last_seen' in a.columns:
            seen = a[~a['_history'] & a['last_seen'].astype(str).ge('2026-10-09')]
            out['archive_rows_last_seen_from_2026_10_09'] = len(seen)
    nse = clean[clean['exchange'] == 'nse'] if len(clean) else clean
    if len(nse):
        out['clean_nse_rows'] = len(nse)
        out['clean_prev_app_id_filled'] = int(nse['prev_app_id'].notna().sum())
        out['clean_submission_type'] = counts(nse['nse_submission_type'].fillna('(empty)'))
        out['clean_revision_remark_filled'] = int(nse['nse_revision_remark'].fillna('').str.strip().ne('').sum())
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    client = ReadOnly(r2_client())
    run_day = date.fromisoformat(TARGET_DATE)
    notes = []
    canonical = {}
    for ex in ('nse', 'bse'):
        for cat in clean_writer.CATEGORIES:
            arch = clean_writer.read_archive(client, ex, cat)
            if arch is not None and not arch.empty:
                canonical[(ex, cat)] = arch
            print(f'archive {ex}/{cat}: {0 if arch is None else len(arch)} rows')

    mcap_body = clean_writer.last_good(client, 'reference/market_cap/{day}/data.json', run_day, include_today=True)
    market_cap_rows = json.loads(mcap_body) if mcap_body else []
    cal_body = clean_writer.get(client, clean_writer.CALENDAR_KEY)
    calendar_state = json.loads(cal_body) if cal_body else seed_state()
    vr_path = ROOT / SECURITY_MASTER_PATH
    vr_master = pd.read_csv(vr_path, dtype=str, keep_default_na=False) if vr_path.exists() else None
    import io
    lists = []
    for name in clean_writer.NSE_LISTS:
        body = clean_writer.last_good(client, f'reference/security_lists/{{day}}/{name}', run_day, include_today=True)
        if body:
            lists.append(pd.read_csv(io.BytesIO(body), dtype=str, keep_default_na=False))
        else:
            notes.append(f'{name}: no stored copy in the last 10 days')

    ranges, price_info = clean_writer.load_price_ranges(client, run_day, notes)
    print(f'price layer: {price_info}')
    tables, report = run(canonical, TARGET_DATE, calendar_state, vr_master=vr_master, nse_lists=lists,
                         market_cap_rows=market_cap_rows, price_ranges=ranges)
    ins, deals = tables['insider_trades'], tables['deals']

    summary = {'run_date': TARGET_DATE, 'notes': notes + report['notes'], 'price_layer': price_info,
               'insider': {}, 'deals': {}}
    # The report counts rows before the product window; these count what the clean tables hold.
    for name, df in (('insider', ins), ('deals', deals)):
        s = summary[name]
        s['rows'] = len(df)
        if df.empty:
            continue
        s['flags'] = flag_counts(df)
        s['needs_review'] = int(df['needs_review'].sum())
        s['price_check'] = counts(df['price_check'])
        s['price_check_by_exchange'] = {ex: counts(g['price_check']) for ex, g in df.groupby('exchange')}
        s['report_table'] = {k: v for k, v in report['tables'][
            'insider_trades' if name == 'insider' else 'deals'].items() if k not in ('removal_breakdown',)}
    s = summary['insider']
    s['price_check_market'] = counts(ins.loc[ins['is_market'], 'price_check'])
    s['price_check_by_kind'] = {k: counts(g['price_check']) for k, g in ins.groupby('kind')}
    s['kind'] = counts(ins['kind'])
    ratio = ins['price'] / ins['day_high'].where(ins['price'] > ins['day_high'])
    below = ins['day_low'] / ins['price'].where(ins['price'] < ins['day_low'])
    dev = pd.concat([ratio.dropna(), below.dropna()]) - 1
    mk = ins['is_market']
    dev_m = pd.concat([ratio[mk].dropna(), below[mk].dropna()]) - 1
    q = [0.1, 0.25, 0.5, 0.75, 0.9]
    s['outside_distance_quantiles_all'] = {str(k): round(float(v), 4) for k, v in dev.quantile(q).items()} if len(dev) else {}
    s['outside_distance_quantiles_market'] = {str(k): round(float(v), 4) for k, v in dev_m.quantile(q).items()} if len(dev_m) else {}
    bands = [0, 0.005, 0.01, 0.02, 0.03, 0.05, 0.1, 0.25, 0.5, 1, 10, 1e12]
    s['outside_distance_bands_market'] = counts(pd.cut(dev_m, bands).astype(str)) if len(dev_m) else {}
    s['outside_distance_bands_all'] = counts(pd.cut(dev, bands).astype(str)) if len(dev) else {}
    s['holding_check_by_kind'] = {k: counts(g) for k, g in
                                  pd.Series(_holding_status(ins), index=ins.index).groupby(ins['kind'])}
    no_qty = ~(ins['quantity'] > 0)
    s['no_quantity_rows'] = int(no_qty.sum())
    s['no_quantity_by_mode_type'] = counts((ins.loc[no_qty, 'mode_raw'].astype(str) + ' | '
                                            + ins.loc[no_qty, 'transaction_type_raw'].astype(str)).str.slice(0, 80))
    unchanged = (ins['quantity'] > 0) & (ins['holding_after'] == ins['holding_before'])
    s['holding_unchanged_with_quantity_by_kind'] = counts(ins.loc[unchanged, 'kind'])
    s['holding_unchanged_with_quantity_by_mode_type'] = counts(
        (ins.loc[unchanged, 'mode_raw'].astype(str) + ' | ' + ins.loc[unchanged, 'transaction_type_raw'].astype(str))
        .str.slice(0, 80))
    nse_ins = canonical.get(('nse', 'insider_trading'))
    if nse_ins is not None:
        s['native_holding_text_not_numeric'] = {c: text_not_numeric(nse_ins[c]) for c in
                                                ('beforeSharesNo', 'afterSharesNo', 'buyQuantity', 'sellquantity')
                                                if c in nse_ins.columns}
    if len(deals):
        summary['deals']['price_check_by_feed'] = {f: counts(g['price_check']) for f, g in deals.groupby('feeds')}
    else:
        deals = pd.DataFrame(columns=['exchange', 'feeds', 'date', 'isin', 'symbol', 'company', 'client_name',
                                      'client_is_market_maker', 'side', 'quantity', 'price', 'day_low', 'day_high',
                                      'price_check', 'trades', 'flags'])
    summary['revision_markers'] = revision_markers(canonical.get(('nse', 'insider_trading')), ins)

    (OUT / 'summary.json').write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps(summary, indent=2, default=str))

    hit_ins = ins[ins['flags'].fillna('').str.contains('|'.join(NEW_FLAGS))
                  | (~ins['price_check'].isin(['inside', 'no_price']))
                  | ~(ins['quantity'] > 0)]
    keep = ['exchange', 'app_id', 'source_id', 'isin', 'symbol', 'company', 'person_role', 'kind', 'is_market',
            'side', 'mode_raw', 'transaction_type_raw', 'quantity', 'value', 'price', 'day_low', 'day_high',
            'price_check', 'holding_before', 'holding_after', 'trade_date_from', 'trade_date_to',
            'intimation_date', 'broadcast_date', 'flags', 'source_url']
    hit_ins[keep].to_csv(OUT / 'insider_checks.csv', index=False)
    hit_deals = deals[deals['flags'].fillna('').str.contains('|'.join(NEW_FLAGS))
                      | ~deals['price_check'].isin(['inside'])]
    hit_deals[['exchange', 'feeds', 'date', 'isin', 'symbol', 'company', 'client_name', 'client_is_market_maker',
               'side', 'quantity', 'price', 'day_low', 'day_high', 'price_check', 'trades', 'flags']
              ].to_csv(OUT / 'deals_checks.csv', index=False)
    if ranges is not None:
        want = pd.concat([hit_ins[['isin', 'trade_date_to']].rename(columns={'trade_date_to': 'date'}),
                          hit_deals[['isin', 'date']]]).dropna()
        want['date'] = pd.to_datetime(want['date'])
        sample = ranges.merge(want.drop_duplicates(), on=['isin', 'date'], how='inner')
        sample.to_csv(OUT / 'day_ranges_sample.csv', index=False)
    print(f'wrote {len(hit_ins)} insider rows, {len(hit_deals)} deal rows to {OUT}')
    return 0


def _holding_status(df):
    from insiders_clean.insider import _holding_check
    return _holding_check(df).to_numpy()


if __name__ == '__main__':
    sys.exit(main())
